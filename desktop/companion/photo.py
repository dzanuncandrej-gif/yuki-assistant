"""Оживление оригинального рисунка персонажа.

Никакой перерисовки: на экране те же пиксели, что на референсе. Движение
получается разбором рисунка на слои и мягкими деформациями — так работают
двумерные марионетки (Live2D и подобные):

* голова вырезана отдельно и поворачивается вокруг шеи;
* веки закрываются сжатием полосы глаз, поверх ложится линия ресниц;
* рот раскрывается вставкой тёмной полости между губами;
* боковые пряди уводит наружу и возвращает пружиной;
* корпус дышит и покачивается едва заметным масштабом и наклоном.

Слои готовит `scripts/build_companion_assets.py`. Если их нет, панель рисует
векторного персонажа из rig.py — приложение работает и без ассетов.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

from core import config

from .rig import Pose

PARTS_DIR = config.ROOT / "assets" / "companion" / "parts"


@dataclass(frozen=True)
class Landmarks:
    """Опорные прямоугольники в координатах исходной фигуры."""

    figure: QRectF
    head: QRectF
    neck: QPointF
    eye_left: QRectF
    eye_right: QRectF
    mouth: QRectF
    brow: QRectF
    hair_left: QRectF
    hair_right: QRectF
    floor_y: float
    torso_top: float


def _rect(values: list[float]) -> QRectF:
    left, top, right, bottom = values
    return QRectF(left, top, right - left, bottom - top)


class PhotoRig:
    """Марионетка из оригинального рисунка."""

    def __init__(self, parts: Path = PARTS_DIR) -> None:
        self.available = False
        self._parts = parts
        manifest_path = parts / "parts.json"
        if not manifest_path.exists():
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            figure = QImage(str(parts / "figure.png"))
            head = QImage(str(parts / "head.png"))
            hair_left = QImage(str(parts / "hair_left.png"))
            hair_right = QImage(str(parts / "hair_right.png"))
        except (OSError, ValueError):
            return
        if figure.isNull() or head.isNull():
            return

        self.marks = Landmarks(
            figure=QRectF(0, 0, manifest["figure"]["width"], manifest["figure"]["height"]),
            head=_rect(manifest["head_box"]),
            neck=QPointF(*manifest["neck_pivot"]),
            eye_left=_rect(manifest["eye_left"]),
            eye_right=_rect(manifest["eye_right"]),
            mouth=_rect(manifest["mouth_box"]),
            brow=_rect(manifest["brow_band"]),
            hair_left=_rect(manifest["hair_left_box"]),
            hair_right=_rect(manifest["hair_right_box"]),
            floor_y=float(manifest["floor_y"]),
            torso_top=float(manifest["torso_top"]),
        )

        self._body = QPixmap.fromImage(self._without_head(figure))
        self._head = QPixmap.fromImage(head)
        self._hair_left = QPixmap.fromImage(hair_left)
        self._hair_right = QPixmap.fromImage(hair_right)
        self._skin = self._sample_skin(figure)
        self._lash = self._sample_lash(figure)
        self.available = True

    # ---------------------------------------------------------------- подготовка

    def _without_head(self, figure: QImage) -> QImage:
        """Вырезает из фигуры овал головы.

        Голова рисуется отдельным слоем поверх. Если её не убрать, при повороте
        из-под слоя выглядывает исходная, неподвижная голова.
        """
        head = self.marks.head
        hole = QRectF(
            head.left() + head.width() * 0.10,
            head.top() + head.height() * 0.06,
            head.width() * 0.80,
            head.height() * 0.86,
        )
        result = figure.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.black)
        painter.drawEllipse(hole)
        painter.end()
        return result

    def _sample_skin(self, figure: QImage) -> QColor:
        """Тон кожи со щеки под глазом — им закрывается глаз при моргании.

        Брать образец над глазом нельзя: там лежит чёлка, и веко получилось бы
        цвета волос.
        """
        band = self.marks.eye_left
        x = int(band.center().x())
        y = int(band.bottom() + band.height() * 0.45)
        return self._average(figure, x - 6, y - 3, 12, 6, QColor("#f6e3d5"))

    def _sample_lash(self, figure: QImage) -> QColor:
        """Тон ресниц — верхняя, самая тёмная строка глаза."""
        band = self.marks.eye_left
        return self._average(
            figure, int(band.left() + 4), int(band.top() + 2), int(band.width() - 8), 3,
            QColor("#4a3b31"),
        )

    @staticmethod
    def _average(image: QImage, x: int, y: int, width: int, height: int, fallback: QColor) -> QColor:
        red = green = blue = count = 0
        for row in range(max(0, y), min(image.height(), y + height)):
            for column in range(max(0, x), min(image.width(), x + width)):
                pixel = image.pixelColor(column, row)
                if pixel.alpha() < 200:
                    continue
                red += pixel.red()
                green += pixel.green()
                blue += pixel.blue()
                count += 1
        if not count:
            return fallback
        return QColor(red // count, green // count, blue // count)

    # ---------------------------------------------------------------- кадр

    def draw(self, painter: QPainter, area: QRectF, pose: Pose, phase: float,
             aura: QColor | None = None) -> None:
        marks = self.marks
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        factor = min(area.width() / marks.figure.width(), area.height() / marks.figure.height())
        factor *= pose.scale
        painter.translate(
            area.center().x() - marks.figure.width() * factor / 2.0,
            area.bottom() - marks.figure.height() * factor,
        )
        painter.scale(factor, factor)

        if aura is not None:
            self._draw_aura(painter, pose, aura)

        # корпус: дыхание вытягивает фигуру, покачивание слегка наклоняет её
        painter.save()
        painter.translate(marks.figure.center().x(), marks.floor_y)
        painter.rotate(pose.body_sway * 0.7)
        painter.scale(1.0 - pose.breath * 0.004, 1.0 + pose.breath * 0.006)
        painter.translate(-marks.figure.center().x(), -marks.floor_y)

        painter.drawPixmap(0, 0, self._body)
        self._draw_hair(painter, pose, phase)
        self._draw_head(painter, pose, phase)
        painter.restore()
        painter.restore()

    def _draw_aura(self, painter: QPainter, pose: Pose, aura: QColor) -> None:
        marks = self.marks
        glow = QRadialGradient(QPointF(marks.figure.center().x(), marks.figure.height() * 0.45),
                               marks.figure.width() * 0.95)
        glow.setColorAt(0.0, self._fade(aura, 0.20 * pose.glow))
        glow.setColorAt(0.55, self._fade(aura, 0.08 * pose.glow))
        glow.setColorAt(1.0, self._fade(aura, 0.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(
            QPointF(marks.figure.center().x(), marks.figure.height() * 0.45),
            marks.figure.width() * 0.95, marks.figure.height() * 0.55,
        )

        floor = QRadialGradient(QPointF(marks.figure.center().x(), marks.floor_y + 26),
                                marks.figure.width() * 0.5)
        floor.setColorAt(0.0, self._fade(aura, 0.32 * pose.glow))
        floor.setColorAt(1.0, self._fade(aura, 0.0))
        painter.setBrush(floor)
        painter.drawEllipse(
            QPointF(marks.figure.center().x(), marks.floor_y + 26),
            marks.figure.width() * 0.46, 34,
        )

    def _draw_hair(self, painter: QPainter, pose: Pose, phase: float) -> None:
        """Пряди уводит только наружу.

        Внутрь двигать нельзя: под слоем лежит та же прядь из общей фигуры, и
        сдвиг внутрь оставил бы за собой двойной контур.
        """
        marks = self.marks
        drift = abs(pose.hair_sway) * 7.0 + 1.5 * abs(math.sin(phase * 0.7))
        lift = pose.hair_lift * 2.0

        for pixmap, box, direction in (
            (self._hair_left, marks.hair_left, -1.0),
            (self._hair_right, marks.hair_right, 1.0),
        ):
            wave = drift * (0.6 + 0.4 * math.sin(phase * 1.1 + direction))
            painter.save()
            painter.translate(box.center().x(), box.top())
            painter.shear(direction * wave * 0.006, 0.0)
            painter.scale(1.0, 1.0 + lift * 0.002)
            painter.translate(-box.center().x(), -box.top())
            painter.drawPixmap(box.topLeft(), pixmap)
            painter.restore()

    def _draw_head(self, painter: QPainter, pose: Pose, phase: float) -> None:
        marks = self.marks
        painter.save()
        painter.translate(marks.neck)
        painter.rotate(pose.head_tilt * 3.4 + pose.head_yaw * 1.6)
        painter.translate(pose.head_yaw * 7.0, -pose.head_pitch * 4.0 - pose.breath * 1.5)
        painter.scale(1.0 - abs(pose.head_yaw) * 0.012, 1.0)
        painter.translate(-marks.neck)

        painter.drawPixmap(marks.head.topLeft(), self._head)
        self._draw_eyes(painter, pose, phase)
        self._draw_mouth(painter, pose)
        self._draw_blush(painter, pose)
        painter.restore()

    # ---------------------------------------------------------------- лицо

    def _draw_eyes(self, painter: QPainter, pose: Pose, phase: float) -> None:
        marks = self.marks
        for index, box in enumerate((marks.eye_left, marks.eye_right)):
            closed = max(pose.blink, pose.wink if index == 0 else 0.0)
            closed = min(1.0, closed + (1.0 - min(1.0, pose.eye_open)) * 0.8)
            if closed <= 0.01:
                self._draw_gaze(painter, box, pose, phase)
                continue

            open_part = 1.0 - closed
            source = QRectF(
                box.left() - marks.head.left(), box.top() - marks.head.top(),
                box.width(), box.height(),
            )

            painter.save()
            # мягкая форма глазницы: прямоугольник выдал бы себя углами на волосах
            socket = QPainterPath()
            socket.addEllipse(box.adjusted(-1.5, -1.0, 1.5, 1.0))
            painter.setClipPath(socket)

            # край опускающегося века: полностью закрытый глаз — это линия чуть
            # ниже середины глазницы, а не заливка на всю высоту
            lid_y = box.top() + box.height() * (0.16 + 0.64 * closed)

            # веко: тон взят со щеки этого же рисунка, сверху чуть темнее — так
            # закрытый глаз выглядит объёмным, а не залитым пятном
            lid = QRectF(box.left() - 1.5, box.top() + box.height() * 0.06,
                         box.width() + 3.0, lid_y - box.top() - box.height() * 0.06)
            shade = QLinearGradient(lid.topLeft(), lid.bottomLeft())
            # верхний край растворяется: пряди чёлки, лежащие на глазах, остаются видны
            shade.setColorAt(0.0, self._fade(self._shade(self._skin, 0.88), 0.0))
            shade.setColorAt(0.28, self._shade(self._skin, 0.90))
            shade.setColorAt(0.75, self._skin)
            shade.setColorAt(1.0, self._shade(self._skin, 0.94))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawRect(lid)

            # открытая часть глаза — оригинальные пиксели, сжатые по вертикали
            if open_part > 0.02:
                target = QRectF(box.left(), lid_y, box.width(), box.bottom() - lid_y)
                painter.drawPixmap(target, self._head, source)

            # ресницы вдоль края века: тёмная дуга, как в оригинальном рисунке
            lash = self._shade(self._lash, 0.72)
            lash.setAlphaF(min(1.0, 0.55 + 0.45 * closed))
            arc = QPainterPath()
            arc.moveTo(box.left() + 1.0, lid_y - box.height() * 0.10)
            arc.quadTo(box.center().x(), lid_y + box.height() * 0.14,
                       box.right() - 1.0, lid_y - box.height() * 0.12)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(lash, max(1.6, box.height() * 0.15),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(arc)
            painter.restore()

    def _draw_gaze(self, painter: QPainter, box: QRectF, pose: Pose, phase: float) -> None:
        """Живой взгляд: зрачок ведёт вслед за курсором, в глазу играет блик."""
        shift_x = pose.look_x * box.width() * 0.10
        shift_y = pose.look_y * box.height() * 0.08
        if abs(shift_x) > 0.4 or abs(shift_y) > 0.4:
            source = QRectF(
                box.left() - self.marks.head.left(), box.top() - self.marks.head.top(),
                box.width(), box.height(),
            )
            inner = box.adjusted(box.width() * 0.16, box.height() * 0.18,
                                 -box.width() * 0.16, -box.height() * 0.10)
            inner_source = QRectF(
                source.left() + source.width() * 0.16, source.top() + source.height() * 0.18,
                source.width() * 0.68, source.height() * 0.72,
            )
            painter.save()
            painter.setClipRect(box.adjusted(1, 1, -1, -1))
            painter.drawPixmap(inner.translated(shift_x, shift_y), self._head, inner_source)
            painter.restore()

        if pose.sparkle > 0.05:
            twinkle = 0.5 + 0.5 * math.sin(phase * 2.4 + box.left())
            highlight = QColor(255, 255, 255)
            highlight.setAlphaF(min(0.75, 0.35 * pose.sparkle * (0.6 + twinkle)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(highlight)
            painter.drawEllipse(
                QPointF(box.center().x() + shift_x + box.width() * 0.14,
                        box.center().y() + shift_y - box.height() * 0.18),
                box.width() * 0.10, box.height() * 0.09,
            )

    def _draw_mouth(self, painter: QPainter, pose: Pose) -> None:
        """Раскрытие рта: между губами появляется тёмная полость, губа уходит вниз."""
        if pose.mouth_open <= 0.02 and pose.smile <= 0.05:
            return
        marks = self.marks
        box = marks.mouth
        openness = min(1.0, pose.mouth_open)
        drop = box.height() * 0.75 * openness

        source = QRectF(
            box.left() - marks.head.left(), box.top() - marks.head.top(),
            box.width(), box.height(),
        )

        if openness <= 0.02:
            return

        # полость рта: овал между губами. Растягивать нижнюю губу вниз нельзя —
        # под ней чокер и грудь, кожа поехала бы поверх костюма.
        cavity = QRectF(
            box.center().x() - box.width() * 0.24,
            box.center().y() - box.height() * 0.02,
            box.width() * 0.48,
            box.height() * 0.22 + drop,
        )
        path = QPainterPath()
        path.addEllipse(cavity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(104, 48, 56, int(240 * min(1.0, openness * 1.8))))
        painter.drawPath(path)

        if openness > 0.4:
            painter.setBrush(QColor(198, 108, 114, 200))
            painter.drawEllipse(
                QPointF(cavity.center().x(), cavity.bottom() - cavity.height() * 0.22),
                cavity.width() * 0.34, cavity.height() * 0.16,
            )

        # верхняя губа возвращается поверх полости — линия рта остаётся авторской
        upper = QRectF(box.left(), box.top(), box.width(), box.height() * 0.52)
        upper_source = QRectF(source.left(), source.top(), source.width(), source.height() * 0.52)
        painter.drawPixmap(upper, self._head, upper_source)

        # мягкая тень под нижней губой — подбородок не выглядит плоским
        shade = QRadialGradient(
            QPointF(cavity.center().x(), cavity.bottom() + cavity.height() * 0.18),
            cavity.width() * 0.8,
        )
        shade.setColorAt(0.0, QColor(150, 96, 84, int(70 * openness)))
        shade.setColorAt(1.0, QColor(150, 96, 84, 0))
        painter.setBrush(shade)
        painter.drawEllipse(
            QPointF(cavity.center().x(), cavity.bottom() + cavity.height() * 0.16),
            cavity.width() * 0.8, cavity.height() * 0.4,
        )

    def _draw_blush(self, painter: QPainter, pose: Pose) -> None:
        if pose.blush <= 0.02:
            return
        marks = self.marks
        for box in (marks.eye_left, marks.eye_right):
            center = QPointF(box.center().x(), box.bottom() + box.height() * 0.75)
            radius = box.width() * 0.9
            glow = QRadialGradient(center, radius)
            glow.setColorAt(0.0, QColor(240, 130, 130, int(90 * pose.blush)))
            glow.setColorAt(1.0, QColor(240, 130, 130, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, radius, radius * 0.6)

    @staticmethod
    def _shade(color: QColor, factor: float) -> QColor:
        return QColor(
            max(0, min(255, int(color.red() * factor))),
            max(0, min(255, int(color.green() * factor))),
            max(0, min(255, int(color.blue() * factor))),
        )

    @staticmethod
    def _fade(color: QColor, alpha: float) -> QColor:
        faded = QColor(color)
        faded.setAlphaF(max(0.0, min(1.0, alpha)))
        return faded
