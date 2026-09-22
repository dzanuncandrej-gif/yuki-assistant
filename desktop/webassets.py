"""Отдача файлов сцены персонажа внутрь встроенного браузера.

Приложение остаётся десктопным, поэтому никакого веб-сервера и портов здесь нет.
Регистрируется собственная схема `jarvis:`, и виджет QWebEngineView читает по ней
файлы прямо с диска. Заодно по этой же схеме отдаётся `qwebchannel.js` — он лежит
в ресурсах Qt, а не отдельным файлом.

Схему обязательно регистрировать до создания QApplication, иначе Chromium уже
собрал список известных схем и новую не увидит.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QFile, QIODevice, QMimeDatabase, QUrl
from PySide6.QtWebEngineCore import (
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)

SCHEME = b"jarvis"
ROOT = Path(__file__).resolve().parent.parent / "ui3d"

# путь внутри схемы → ресурс Qt: канал связи страницы с питоном
_QT_RESOURCES = {"vendor/qwebchannel.js": ":/qtwebchannel/qwebchannel.js"}

_MIME = QMimeDatabase()


_registered = False


def register_scheme() -> None:
    """Объявляет схему `jarvis:`. Вызывать до создания QApplication.

    Синтаксис именно `Host`, а не `HostAndPort`: с портом Chromium не считает
    схему обычной и отказывает fetch — страница поднимается, но ни манифест, ни
    модель загрузить не может. Проверить это через `schemeByName` нельзя, она в
    PySide6 возвращает пустую заготовку даже для `http`, поэтому держим флаг сами.
    """
    global _registered
    if _registered:
        return
    scheme = QWebEngineUrlScheme(QByteArray(SCHEME))
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme          # модули и WebGL требуют «надёжного» источника
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.FetchApiAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    _registered = True


def url(path: str, query: str = "") -> QUrl:
    """Собирает адрес вида `jarvis://ui/companion.html?character=…`."""
    return QUrl(f"jarvis://ui/{path.lstrip('/')}" + (f"?{query}" if query else ""))


def _guess(path: Path) -> bytes:
    guess, _ = mimetypes.guess_type(path.name)
    if guess:
        return guess.encode()
    # .glb и .webp система знает не всегда
    return (_MIME.mimeTypeForFile(str(path)).name() or "application/octet-stream").encode()


class AssetHandler(QWebEngineUrlSchemeHandler):
    """Читает файлы из `ui3d/`, не выпуская запросы за пределы этой папки."""

    def __init__(self, root: Path = ROOT, parent=None) -> None:
        super().__init__(parent)
        self.root = root.resolve()

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        relative = job.requestUrl().path().lstrip("/") or "companion.html"

        resource = _QT_RESOURCES.get(relative)
        if resource is not None:
            self._reply_resource(job, resource, b"application/javascript")
            return

        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root) or not target.is_file():
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return

        handle = QFile(str(target))
        handle.setParent(job)  # Qt читает файл асинхронно: объект должен пережить вызов
        if not handle.open(QIODevice.OpenModeFlag.ReadOnly):
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return
        job.reply(_guess(target), handle)

    def _reply_resource(self, job: QWebEngineUrlRequestJob, path: str, mime: bytes) -> None:
        source = QFile(path)
        if not source.open(QIODevice.OpenModeFlag.ReadOnly):
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        buffer = QBuffer(job)
        buffer.setData(source.readAll())
        source.close()
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(mime, buffer)


def characters() -> list[dict[str, object]]:
    """Список собранных персонажей для меню выбора."""
    import json

    index = ROOT / "characters" / "index.json"
    if not index.is_file():
        return []
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("characters", [])
    return [item for item in items if (ROOT / "characters" / str(item.get("id")) / "avatar.glb").is_file()]


def available() -> bool:
    """Есть ли хотя бы один собранный персонаж и сам движок отображения."""
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        return False
    return bool(characters())
