"""Камера: Юки видит человека, узнаёт его и понимает, здесь ли он.

Кадры не копятся: поток захвата держит только последний, интерфейс и аватар забирают
его сами. Лицо ищется десятком миллисекунд (YuNet), опознаётся вектором на 128 чисел
(SFace) — обе модели работают на процессоре и не ходят в сеть.

Что это даёт ассистенту:
    • взгляд аватара держит настоящее лицо, а не курсор;
    • понятно, на месте человек или отошёл — можно не говорить в пустоту;
    • голос слушается своего: хозяина видно, значит команда его.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import config, gestures

MODELS = config.ROOT / "models" / "face"
DETECTOR = MODELS / "face_detection_yunet_2023mar.onnx"
RECOGNIZER = MODELS / "face_recognition_sface_2021dec.onnx"
FACES_FILE = config.ROOT / "data" / "faces.json"

# порог косинусной близости SFace: выше — тот же человек (значение из документации OpenCV)
SAME_PERSON = 0.363
# сколько кадров подряд без лица считается «человек отошёл»
AWAY_FRAMES = 25
# сколько секунд имя остаётся действительным между опознаниями
IDENTITY_TTL = 8.0


class CameraError(RuntimeError):
    """Камера недоступна или модели не скачаны."""


def models_ready() -> bool:
    return DETECTOR.exists() and RECOGNIZER.exists()


def _ascii_path(path: Path) -> str:
    """Путь, который поймёт сишный загрузчик OpenCV.

    Папка проекта называется по-русски, а OpenCV открывает файлы через ANSI и на
    кириллице честно говорит «не могу прочитать». Короткое имя 8.3 не подходит: оно
    обрезает расширение, и OpenCV перестаёт узнавать формат. Поэтому держим копию
    модели в temp — там путь заведомо латиницей.
    """
    import shutil
    import tempfile

    if str(path).isascii():
        return str(path)

    mirror = Path(tempfile.gettempdir()) / "jarvis_models" / path.name
    mirror.parent.mkdir(parents=True, exist_ok=True)
    if not mirror.exists() or mirror.stat().st_size != path.stat().st_size:
        shutil.copy2(path, mirror)
    return str(mirror)


@dataclass
class Face:
    """Найденное лицо в кадре."""

    box: tuple[int, int, int, int] = (0, 0, 0, 0)   # x, y, ширина, высота
    score: float = 0.0
    name: str = ""                                   # имя, если узнали
    similarity: float = 0.0
    center: tuple[float, float] = (0.0, 0.0)         # -1..1 относительно центра кадра
    size: float = 0.0                                # доля кадра по высоте: чем больше, тем ближе
    at: float = 0.0

    @property
    def known(self) -> bool:
        return bool(self.name)


@dataclass
class Vision:
    """Состояние камеры для интерфейса и аватара."""

    present: bool = False
    face: Face | None = None
    people: int = 0
    fps: float = 0.0
    error: str = ""
    healthy: bool = True
    frames: int = 0
    since_seen: float = 1e9
    names: tuple[str, ...] = field(default_factory=tuple)
    # кто перед камерой. Опознание идёт не каждый кадр, поэтому имя держится
    # некоторое время — иначе подпись мигала бы «хозяин / незнакомый».
    identity: str = ""
    identity_at: float = 0.0
    identity_score: float = 0.0
    gesture: str = ""   # что показывает рука прямо сейчас

    @property
    def known(self) -> bool:
        return bool(self.identity) and (time.monotonic() - self.identity_at) < IDENTITY_TTL


class Camera:
    """Фоновый захват с поиском и опознанием лица."""

    def __init__(
        self,
        index: int = 0,
        width: int = 640,
        height: int = 480,
        fps: float = 15.0,
        detect_every: int = 2,
        recognize_every: int = 10,
        hands_every: int = 3,
        on_gesture: Any = None,
    ) -> None:
        self.index = int(index)
        self.width, self.height = int(width), int(height)
        self.target_fps = max(1.0, float(fps))
        self.detect_every = max(1, int(detect_every))
        self.recognize_every = max(1, int(recognize_every))
        self.hands_every = max(1, int(hands_every))

        # чтение жестов включается, только если модель рук скачана
        self._hands: Any | None = None
        if on_gesture is not None and gestures.model_ready():
            self._hands = gestures.HandReader(on_event=on_gesture)

        self.vision = Vision()
        self.preview: bytes = b""     # последний кадр в JPEG для интерфейса
        self.preview_id = 0

        self._capture: Any | None = None
        self._detector: Any | None = None
        self._recognizer: Any | None = None
        self._known: dict[str, np.ndarray] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._misses = 0
        self._last_frame_at = 0.0

    # ---------------------------------------------------------------- жизненный цикл

    def start(self) -> None:
        if self._thread is not None:
            return
        if not models_ready():
            raise CameraError(
                "модели лиц не скачаны. Выполни: python scripts/download_face_models.py"
            )
        self._load_known()
        self._open_models()  # тяжёлая модель грузится до старта: первый кадр не ждёт её
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jarvis-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=3.0)
        if self._hands is not None:
            self._hands.close()
        self._release()

    @property
    def running(self) -> bool:
        return self._thread is not None and not self._stop.is_set()

    def _release(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass

    # ---------------------------------------------------------------- модели

    def _open_models(self) -> None:
        import cv2

        if self._detector is None:
            self._detector = cv2.FaceDetectorYN.create(
                _ascii_path(DETECTOR), "", (self.width, self.height), 0.75, 0.3, 5000
            )
        if self._recognizer is None:
            self._recognizer = cv2.FaceRecognizerSF.create(_ascii_path(RECOGNIZER), "")

    def _open_camera(self) -> Any:
        import cv2

        capture = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"камера {self.index} не открывается")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # берём свежий кадр, а не из очереди
        return capture

    # ---------------------------------------------------------------- знакомые лица

    def _load_known(self) -> None:
        if not FACES_FILE.exists():
            return
        try:
            raw = json.loads(FACES_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for name, vector in (raw.get("faces") or {}).items():
            try:
                self._known[str(name)] = np.asarray(vector, dtype=np.float32)
            except (TypeError, ValueError):
                continue

    def _save_known(self) -> None:
        FACES_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"faces": {name: vector.tolist() for name, vector in self._known.items()}}
        FACES_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @property
    def known_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._known))

    def forget_face(self, name: str) -> bool:
        removed = self._known.pop(name.strip(), None) is not None
        if removed:
            self._save_known()
        return removed

    # ---------------------------------------------------------------- основной цикл

    def _loop(self) -> None:

        period = 1.0 / self.target_fps
        failures = 0
        counter = 0
        last_faces: list[Face] = []

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                if self._capture is None:
                    self._open_models()
                    self._capture = self._open_camera()
                ok, frame = self._capture.read()
                if not ok or frame is None:
                    raise CameraError("кадр не получен")
                failures = 0
            except Exception as err:
                failures += 1
                self.vision.error = str(err)[:120]
                self.vision.healthy = failures < 3
                self.vision.present = False
                self._release()
                self._stop.wait(min(3.0, 0.5 * failures))
                continue

            counter += 1
            with self._lock:
                self._frame = frame

            if counter % self.detect_every == 0:
                last_faces = self._detect(frame, recognize=counter % self.recognize_every == 0)
                self._update(last_faces)

            reader = self._hands
            if reader is not None and counter % self.hands_every == 0:
                try:
                    self.vision.gesture = reader.process(frame)
                except Exception as err:
                    self.vision.error = f"жесты: {str(err)[:80]}"
                    self._hands = None

            self._encode(frame, last_faces)
            self.vision.frames = counter
            now = time.monotonic()
            if self._last_frame_at:
                # частота считается по интервалу между кадрами, а не по времени работы
                self.vision.fps = 1.0 / max(now - self._last_frame_at, 1e-3)
            self._last_frame_at = now
            self.vision.healthy = True
            self._stop.wait(max(0.0, period - (now - started)))

    def _detect(self, frame: np.ndarray, recognize: bool) -> list[Face]:
        import cv2

        detector = self._detector
        if detector is None:
            return []
        height, width = frame.shape[:2]
        detector.setInputSize((width, height))
        try:
            _, raw = detector.detect(frame)
        except cv2.error:
            return []
        if raw is None:
            return []

        faces: list[Face] = []
        for row in raw:
            x, y, w, h = (int(value) for value in row[:4])
            face = Face(
                box=(x, y, w, h),
                score=float(row[-1]),
                center=((x + w / 2) / width * 2 - 1, (y + h / 2) / height * 2 - 1),
                size=h / height,
                at=time.monotonic(),
            )
            if recognize:
                name, similarity = self._identify(frame, row)
                face.name, face.similarity = name, similarity
            faces.append(face)
        faces.sort(key=lambda item: item.size, reverse=True)  # ближайший — главный
        return faces

    def _identify(self, frame: np.ndarray, row: np.ndarray) -> tuple[str, float]:
        import cv2

        recognizer = self._recognizer
        if recognizer is None or not self._known:
            return "", 0.0
        try:
            aligned = recognizer.alignCrop(frame, row)
            vector = recognizer.feature(aligned).flatten()
        except cv2.error:
            return "", 0.0

        best_name, best_score = "", 0.0
        for name, known in self._known.items():
            score = float(np.dot(vector, known) / (np.linalg.norm(vector) * np.linalg.norm(known) + 1e-9))
            if score > best_score:
                best_name, best_score = name, score
        return (best_name, best_score) if best_score >= SAME_PERSON else ("", best_score)

    def _update(self, faces: list[Face]) -> None:
        vision = self.vision
        vision.people = len(faces)
        vision.names = tuple(face.name for face in faces if face.known)
        for face in faces:
            if face.known:  # опознали — держим имя, пока человек не ушёл
                vision.identity = face.name
                vision.identity_at = time.monotonic()
                vision.identity_score = face.similarity
                break
        if faces:
            vision.face = faces[0]
            vision.present = True
            vision.since_seen = 0.0
            self._misses = 0
        else:
            self._misses += 1
            vision.since_seen = self._misses / max(1.0, self.target_fps / self.detect_every)
            if self._misses >= AWAY_FRAMES:
                vision.present = False
                vision.face = None
                vision.identity = ""  # человек ушёл — имя больше не действует

    def _encode(self, frame: np.ndarray, faces: list[Face]) -> None:
        """Кадр для интерфейса: с рамкой и подписью, кто это."""
        import cv2

        preview = frame.copy()
        for face in faces:
            x, y, w, h = face.box
            colour = (255, 190, 90) if (face.known or self.vision.known) else (150, 150, 150)
            cv2.rectangle(preview, (x, y), (x + w, y + h), colour, 2)
            label = face.name or (self.vision.identity if self.vision.known else "гость")
            cv2.putText(
                preview, label, (x, max(16, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2, cv2.LINE_AA
            )
        ok, buffer = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 62])
        if ok:
            self.preview = buffer.tobytes()
            self.preview_id += 1

    # ---------------------------------------------------------------- знакомство

    def enroll(self, name: str, samples: int = 12, timeout_s: float = 12.0) -> str:
        """Запоминает лицо: усредняет несколько кадров, чтобы не зависеть от одного ракурса."""
        import cv2

        clean = str(name or "").strip()
        if not clean:
            raise CameraError("нужно имя")
        if not self.running:
            raise CameraError("камера выключена")

        recognizer = self._recognizer
        detector = self._detector
        if recognizer is None or detector is None:
            raise CameraError("модели лиц не загружены")

        vectors: list[np.ndarray] = []
        deadline = time.monotonic() + timeout_s
        while len(vectors) < samples and time.monotonic() < deadline:
            with self._lock:
                frame = None if self._frame is None else self._frame.copy()
            if frame is None:
                time.sleep(0.1)
                continue
            height, width = frame.shape[:2]
            detector.setInputSize((width, height))
            try:
                _, raw = detector.detect(frame)
                if raw is None:
                    time.sleep(0.15)
                    continue
                row = max(raw, key=lambda item: item[3])  # самое крупное лицо
                aligned = recognizer.alignCrop(frame, row)
                vectors.append(recognizer.feature(aligned).flatten())
            except cv2.error:
                pass
            time.sleep(0.15)

        if len(vectors) < 3:
            raise CameraError("лицо не поймалось — сядь ровно перед камерой и попробуй ещё раз")

        average = np.mean(np.stack(vectors), axis=0).astype(np.float32)
        self._known[clean] = average
        self._save_known()
        return f"запомнил лицо: {clean} ({len(vectors)} кадров)"

    # ---------------------------------------------------------------- снимок для модели зрения

    def snapshot(self, side: int = 512, quality: int = 78) -> bytes:
        """Кадр с камеры в JPEG — для модели зрения: «что я делаю», «как выгляжу»."""
        import cv2

        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        if frame is None:
            raise CameraError("кадра ещё нет")
        height, width = frame.shape[:2]
        scale = side / max(height, width)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise CameraError("кадр не кодируется")
        return buffer.tobytes()

    def describe(self) -> str:
        """Короткая сводка для голосового ответа."""
        vision = self.vision
        if not vision.healthy:
            return f"камера недоступна: {vision.error}"
        if not vision.present:
            return "перед камерой никого"
        face = vision.face
        who = vision.identity if vision.known else "незнакомый человек"
        distance = "близко" if face and face.size > 0.45 else "на расстоянии"
        others = f", всего людей: {vision.people}" if vision.people > 1 else ""
        return f"вижу: {who}, {distance}{others}"
