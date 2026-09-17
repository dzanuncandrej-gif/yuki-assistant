"""Риг персонажа: поза и её отрисовка.

Здесь нет ни таймеров, ни состояний ассистента — только чистая функция
«поза + скин → кадр». Благодаря этому персонажа можно нарисовать куда угодно:
в панель на рабочем столе, в окно звонка, в превью настроек.

Система координат холста — 1000 × 1500 условных единиц, начало в левом верхнем
углу. Виджет сам масштабирует её под свой размер, сохраняя пропорции.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from .skin import DEFAULT_SKIN, Skin

CANVAS_W = 1000.0
CANVAS_H = 1500.0

# ---------------------------------------------------------------- опорные точки лица
HEAD_CX = 500.0
HEAD_CY = 400.0
FACE_TOP = 190.0
FACE_CHIN = 645.0
EYE_Y = 472.0
EYE_DX = 82.0          # смещение центров глаз от оси
EYE_RX = 52.0
EYE_RY = 40.0
BROW_Y = 398.0
MOUTH_Y = 588.0
SHOULDER_Y = 726.0


@dataclass
class Pose:
    """Полное состояние персонажа в конкретном кадре. Все величины нормированы."""

    # голова и корпус
    head_yaw: float = 0.0        # -1 влево, 1 вправо
    head_pitch: float = 0.0      # -1 вниз, 1 вверх
    head_tilt: float = 0.0       # наклон вбок, -1..1
    body_sway: float = 0.0       # покачивание корпуса, -1..1
    breath: float = 0.0          # дыхание, -1..1
    lean: float = 0.0            # наклон к экрану

    # глаза
    blink: float = 0.0           # 0 открыты, 1 закрыты
    wink: float = 0.0            # закрыт только левый глаз
    eye_open: float = 1.0
    eye_round: float = 1.0
    look_x: float = 0.0
    look_y: float = 0.0
    pupil: float = 1.0           # размер зрачка: страх сужает, интерес расширяет
    sparkle: float = 0.25

    # брови и рот
    brow_raise: float = 0.0
    brow_angle: float = 0.0
    smile: float = 0.2
    mouth_open: float = 0.0

    # мелочи, которые делают лицо живым
    blush: float = 0.0
    sweat: float = 0.0

    # волосы и уши
    hair_sway: float = 0.0       # -1..1, инерция прядей
    hair_lift: float = 0.0       # подъём прядей при резком движении
    ear_perk: float = 0.0        # -1 прижаты, 1 торчком
    ear_twitch: float = 0.0

    # руки
    wave: float = 0.0            # приветственный взмах, 0..1
    arm_swing: float = 0.0       # покачивание рук при дыхании

    # общее
    glow: float = 0.5            # яркость ауры
    scale: float = 1.0


# ---------------------------------------------------------------- геометрия


def _fade(color: QColor, alpha: float) -> QColor:
    faded = QColor(color)
    faded.setAlphaF(max(0.0, min(1.0, alpha)))
    return faded


# ---------------------------------------------------------------- части персонажа


def _face_path() -> QPainterPath:
    """Череп и подбородок одним контуром: округлый свод, мягкий острый подбородок."""
    path = QPainterPath()
    path.moveTo(HEAD_CX - 172, HEAD_CY - 26)
    path.cubicTo(HEAD_CX - 178, FACE_TOP - 12, HEAD_CX + 178, FACE_TOP - 12, HEAD_CX + 172, HEAD_CY - 26)
    path.cubicTo(HEAD_CX + 168, HEAD_CY + 78, HEAD_CX + 150, HEAD_CY + 128, HEAD_CX + 116, HEAD_CY + 162)
    path.cubicTo(HEAD_CX + 82, FACE_CHIN - 24, HEAD_CX + 44, FACE_CHIN, HEAD_CX, FACE_CHIN)
    path.cubicTo(HEAD_CX - 44, FACE_CHIN, HEAD_CX - 82, FACE_CHIN - 24, HEAD_CX - 116, HEAD_CY + 162)
    path.cubicTo(HEAD_CX - 150, HEAD_CY + 128, HEAD_CX - 168, HEAD_CY + 78, HEAD_CX - 172, HEAD_CY - 26)
    path.closeSubpath()
    return path


def _ear_path(side: int, perk: float, twitch: float) -> QPainterPath:
    """Кошачье ухо. perk: -1 прижато, 1 торчком; twitch — короткое подёргивание."""
    base_x = HEAD_CX + side * 96
    lift = 26 * perk + 14 * twitch
    spread = 1.0 - 0.22 * max(0.0, -perk)
    tip_x = HEAD_CX + side * (168 * spread) + side * twitch * 12
    tip_y = 108 - lift
    path = QPainterPath()
    path.moveTo(base_x, 268)
    path.cubicTo(base_x + side * 10, 210, tip_x - side * 24, tip_y + 62, tip_x, tip_y)
    path.cubicTo(tip_x + side * 22, tip_y + 72, base_x + side * 96, 246, base_x + side * 84, 292)
    path.cubicTo(base_x + side * 52, 300, base_x + side * 18, 292, base_x, 268)
    path.closeSubpath()
    return path


def _ear_inner_path(side: int, perk: float, twitch: float) -> QPainterPath:
    base_x = HEAD_CX + side * 106
    lift = 24 * perk + 12 * twitch
    tip_x = HEAD_CX + side * 150 + side * twitch * 10
    tip_y = 142 - lift
    path = QPainterPath()
    path.moveTo(base_x, 262)
    path.cubicTo(base_x + side * 12, 214, tip_x - side * 18, tip_y + 46, tip_x, tip_y)
    path.cubicTo(tip_x + side * 14, tip_y + 58, base_x + side * 70, 236, base_x + side * 62, 274)
    path.cubicTo(base_x + side * 40, 282, base_x + side * 16, 280, base_x, 262)
    path.closeSubpath()
    return path


def _back_hair_path(sway: float, lift: float) -> QPainterPath:
    """Длинная масса волос за спиной. sway качает нижний край, lift приподнимает пряди."""
    drift = sway * 46
    path = QPainterPath()
    path.moveTo(HEAD_CX - 190, 340)
    path.cubicTo(HEAD_CX - 228, 150, HEAD_CX + 228, 150, HEAD_CX + 190, 340)
    # правая сторона вниз: масса чуть шире плеч, но не прячет костюм
    path.cubicTo(HEAD_CX + 226, 470, HEAD_CX + 238 + drift * 0.4, 720, HEAD_CX + 214 + drift, 980)
    path.cubicTo(HEAD_CX + 206 + drift * 1.2, 1090 - lift * 30, HEAD_CX + 186 + drift * 1.4, 1150, HEAD_CX + 142 + drift * 1.5, 1194)
    # нижний волнистый край
    path.cubicTo(HEAD_CX + 96 + drift, 1130, HEAD_CX + 52 + drift, 1222, HEAD_CX + 8 + drift * 0.8, 1160)
    path.cubicTo(HEAD_CX - 40 + drift * 0.6, 1228, HEAD_CX - 90 + drift * 0.4, 1130, HEAD_CX - 142 + drift * 0.4, 1190)
    # левая сторона вверх
    path.cubicTo(HEAD_CX - 190 + drift * 0.2, 1120, HEAD_CX - 226 + drift * 0.2, 880, HEAD_CX - 222, 700)
    path.cubicTo(HEAD_CX - 236, 540, HEAD_CX - 220, 430, HEAD_CX - 190, 340)
    path.closeSubpath()
    return path


def _side_lock(side: int, sway: float) -> QPainterPath:
    """Боковая прядь у лица: спускается ниже плеча и качается сильнее общей массы."""
    drift = sway * 30 * (1.0 if side > 0 else 0.8)
    top_x = HEAD_CX + side * 150
    path = QPainterPath()
    # внешняя кромка пряди
    path.moveTo(top_x, 300)
    path.cubicTo(
        top_x + side * 30, 430,
        top_x + side * 26 + drift, 640,
        top_x + side * 12 + drift * 1.4, 856,
    )
    # острый кончик
    path.cubicTo(
        top_x + side * 6 + drift * 1.5, 900,
        top_x + side * 2 + drift * 1.4, 918,
        top_x - side * 6 + drift * 1.3, 940,
    )
    # внутренняя кромка вдоль щеки
    path.cubicTo(
        top_x - side * 26 + drift, 860,
        top_x - side * 34 + drift * 0.6, 620,
        top_x - side * 30, 430,
    )
    path.cubicTo(top_x - side * 26, 366, top_x - side * 14, 322, top_x, 300)
    path.closeSubpath()
    return path


def _bangs_path(sway: float) -> QPainterPath:
    """Чёлка острыми прядями. Каждый зубец слегка смещается от инерции."""
    drift = sway * 12
    path = QPainterPath()
    path.moveTo(HEAD_CX - 186, 372)
    path.cubicTo(HEAD_CX - 200, 168, HEAD_CX + 200, 168, HEAD_CX + 186, 372)
    # правый край чёлки уходит вниз к скуле
    path.cubicTo(HEAD_CX + 176, 420, HEAD_CX + 168, 462, HEAD_CX + 150, 500)
    # пары «вершина пряди — впадина между прядями»: мягкий зубец, не пила
    points = (
        (118, 366), (100, 438), (72, 378), (44, 432), (16, 372),
        (-16, 426), (-52, 368), (-88, 436), (-122, 376), (-156, 456),
    )
    for index in range(0, len(points), 2):
        peak_x, peak_y = points[index]
        valley_x, valley_y = points[index + 1]
        path.cubicTo(
            HEAD_CX + peak_x + 20 + drift, peak_y + 40,
            HEAD_CX + peak_x + drift, peak_y,
            HEAD_CX + valley_x + drift, valley_y,
        )
    path.cubicTo(HEAD_CX - 176, 452, HEAD_CX - 184, 410, HEAD_CX - 186, 372)
    path.closeSubpath()
    return path


def _ahoge_path(phase: float, sway: float) -> QPainterPath:
    """Торчащая прядь-антенна: живёт своей жизнью и выдаёт настроение."""
    bend = math.sin(phase) * 18 + sway * 14
    path = QPainterPath()
    path.moveTo(HEAD_CX - 14, 246)
    path.cubicTo(HEAD_CX - 20, 196, HEAD_CX + 30 + bend, 176, HEAD_CX + 54 + bend * 1.3, 140 + abs(bend) * 0.2)
    path.cubicTo(HEAD_CX + 40 + bend * 1.1, 176, HEAD_CX + 18 + bend * 0.5, 200, HEAD_CX + 16, 248)
    path.closeSubpath()
    return path


def _eye_path(cx: float, cy: float, rx: float, ry: float, side: int = 1) -> QPainterPath:
    """Миндалевидный глаз: внешний угол выше внутреннего, поэтому форма зеркальна."""
    inner = -side
    outer = side
    path = QPainterPath()
    path.moveTo(cx + inner * rx, cy + ry * 0.12)
    path.cubicTo(
        cx + inner * rx * 0.86, cy - ry * 1.16,
        cx + outer * rx * 0.72, cy - ry * 1.22,
        cx + outer * rx, cy - ry * 0.26,
    )
    path.cubicTo(
        cx + outer * rx * 0.92, cy + ry * 0.74,
        cx + outer * rx * 0.42, cy + ry * 1.06,
        cx + inner * rx * 0.06, cy + ry,
    )
    path.cubicTo(
        cx + inner * rx * 0.56, cy + ry * 0.94,
        cx + inner * rx * 0.92, cy + ry * 0.66,
        cx + inner * rx, cy + ry * 0.12,
    )
    path.closeSubpath()
    return path


def _mouth_path(smile: float, openness: float) -> QPainterPath:
    """Рот: от грустной дуги до широкой улыбки, с раскрытием по громкости речи."""
    width = 34 + 22 * max(0.0, smile) + 10 * openness
    curve = 22 * smile
    drop = 46 * openness
    path = QPainterPath()
    path.moveTo(HEAD_CX - width, MOUTH_Y)
    path.cubicTo(
        HEAD_CX - width * 0.5, MOUTH_Y + curve + drop * 0.35,
        HEAD_CX + width * 0.5, MOUTH_Y + curve + drop * 0.35,
        HEAD_CX + width, MOUTH_Y,
    )
    if openness > 0.02:
        path.cubicTo(
            HEAD_CX + width * 0.55, MOUTH_Y + drop,
            HEAD_CX - width * 0.55, MOUTH_Y + drop,
            HEAD_CX - width, MOUTH_Y,
        )
    else:
        path.cubicTo(
            HEAD_CX + width * 0.5, MOUTH_Y + curve * 0.55,
            HEAD_CX - width * 0.5, MOUTH_Y + curve * 0.55,
            HEAD_CX - width, MOUTH_Y,
        )
    path.closeSubpath()
    return path


# ---------------------------------------------------------------- отрисовка


def draw_character(painter: QPainter, rect: QRectF, pose: Pose, skin: Skin = DEFAULT_SKIN,
                   phase: float = 0.0) -> None:
    """Рисует персонажа целиком внутри rect, сохраняя пропорции холста."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    factor = min(rect.width() / CANVAS_W, rect.height() / CANVAS_H) * pose.scale
    painter.translate(
        rect.center().x() - CANVAS_W * factor / 2.0,
        rect.bottom() - CANVAS_H * factor,
    )
    painter.scale(factor, factor)

    _draw_aura(painter, pose, skin)

    # волосы за спиной живут в системе координат головы, но лежат под фигурой
    _head_transform(painter, pose)
    _draw_back_hair(painter, pose, skin)
    painter.restore()

    painter.save()
    painter.translate(pose.body_sway * 14.0, -pose.breath * 6.0)
    _draw_legs(painter, pose, skin)
    _draw_skirt(painter, pose, skin)
    _draw_arm(painter, pose, skin, side=-1, front=False)
    _draw_torso(painter, pose, skin)
    _draw_neck(painter, pose, skin)
    painter.restore()

    # голова: поворот, наклон, дыхание
    _head_transform(painter, pose)
    _draw_ears(painter, pose, skin)
    _draw_face(painter, pose, skin)
    _draw_eyes(painter, pose, skin, phase)
    _draw_mouth(painter, pose, skin)
    _draw_extras(painter, pose, skin)
    _draw_front_hair(painter, pose, skin, phase)
    # брови рисуются поверх чёлки: так читается мимика, как в аниме
    _draw_brows(painter, pose, skin)
    painter.restore()

    painter.save()
    painter.translate(pose.body_sway * 14.0, -pose.breath * 6.0)
    _draw_arm(painter, pose, skin, side=1, front=True)
    painter.restore()

    painter.restore()


def _head_transform(painter: QPainter, pose: Pose) -> None:
    """Ставит систему координат головы. Вызывающий обязан сделать painter.restore()."""
    painter.save()
    painter.translate(pose.body_sway * 20.0, -pose.breath * 9.0 + pose.head_pitch * -16.0)
    painter.translate(HEAD_CX, HEAD_CY)
    painter.rotate(pose.head_tilt * 9.0)
    painter.translate(pose.head_yaw * 26.0, 0.0)
    painter.scale(1.0 - 0.08 * abs(pose.head_yaw), 1.0 - 0.03 * abs(pose.head_pitch))
    painter.translate(-HEAD_CX, -HEAD_CY)


def _draw_aura(painter: QPainter, pose: Pose, skin: Skin) -> None:
    """Мягкое свечение за фигурой — связывает персонажа с интерфейсом Юки."""
    glow = QRadialGradient(QPointF(HEAD_CX, 700), 640)
    glow.setColorAt(0.0, _fade(skin.aura, 0.20 * pose.glow))
    glow.setColorAt(0.45, _fade(skin.aura, 0.10 * pose.glow))
    glow.setColorAt(1.0, _fade(skin.aura, 0.0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(QPointF(HEAD_CX, 700), 640, 780)

    floor = QRadialGradient(QPointF(HEAD_CX, 1440), 360)
    floor.setColorAt(0.0, _fade(skin.aura, 0.26 * pose.glow))
    floor.setColorAt(1.0, _fade(skin.aura, 0.0))
    painter.setBrush(QBrush(floor))
    painter.drawEllipse(QPointF(HEAD_CX, 1440), 340, 74)


def _draw_back_hair(painter: QPainter, pose: Pose, skin: Skin) -> None:
    gradient = QLinearGradient(HEAD_CX, 200, HEAD_CX, 1240)
    gradient.setColorAt(0.0, skin.hair_light)
    gradient.setColorAt(0.35, skin.hair)
    gradient.setColorAt(1.0, skin.hair_dark)
    painter.setPen(QPen(_fade(skin.hair_dark, 0.55), 3.0))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(_back_hair_path(pose.hair_sway, pose.hair_lift))


def _draw_ears(painter: QPainter, pose: Pose, skin: Skin) -> None:
    for side in (-1, 1):
        twitch = pose.ear_twitch * (1.0 if side > 0 else -0.6)
        outer = _ear_path(side, pose.ear_perk, twitch)
        gradient = QLinearGradient(HEAD_CX + side * 120, 100, HEAD_CX + side * 120, 300)
        gradient.setColorAt(0.0, skin.ear_outer)
        gradient.setColorAt(1.0, skin.hair_dark)
        painter.setPen(QPen(_fade(skin.line, 0.7), 3.0))
        painter.setBrush(QBrush(gradient))
        painter.drawPath(outer)

        inner = _ear_inner_path(side, pose.ear_perk, twitch)
        inner_gradient = QLinearGradient(HEAD_CX + side * 120, 130, HEAD_CX + side * 120, 280)
        inner_gradient.setColorAt(0.0, skin.ear_inner)
        inner_gradient.setColorAt(1.0, _fade(skin.ear_inner, 0.35))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(inner_gradient))
        painter.drawPath(inner)

        # золотая накладка у основания — деталь костюма с референса
        painter.setBrush(QBrush(_fade(skin.gold, 0.85)))
        painter.drawEllipse(QPointF(HEAD_CX + side * 128, 258), 22, 12)


def _draw_face(painter: QPainter, pose: Pose, skin: Skin) -> None:
    face = _face_path()
    gradient = QLinearGradient(HEAD_CX, FACE_TOP, HEAD_CX, FACE_CHIN)
    gradient.setColorAt(0.0, skin.skin)
    gradient.setColorAt(0.62, skin.skin)
    gradient.setColorAt(1.0, skin.skin_shade)
    painter.setPen(QPen(_fade(skin.skin_deep, 0.5), 2.4))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(face)

    # тень от чёлки: без неё лицо выглядит плоским
    painter.setPen(Qt.PenStyle.NoPen)
    shade = QLinearGradient(HEAD_CX, FACE_TOP + 40, HEAD_CX, EYE_Y + 10)
    shade.setColorAt(0.0, _fade(skin.skin_deep, 0.35))
    shade.setColorAt(1.0, _fade(skin.skin_deep, 0.0))
    painter.setBrush(QBrush(shade))
    painter.drawPath(face)

    # румянец
    if pose.blush > 0.01:
        for side in (-1, 1):
            cheek = QRadialGradient(QPointF(HEAD_CX + side * 132, EYE_Y + 62), 60)
            cheek.setColorAt(0.0, _fade(skin.blush, 0.5 * pose.blush))
            cheek.setColorAt(1.0, _fade(skin.blush, 0.0))
            painter.setBrush(QBrush(cheek))
            painter.drawEllipse(QPointF(HEAD_CX + side * 132, EYE_Y + 62), 62, 34)
            # аниме-штрихи по щекам
            painter.setPen(QPen(_fade(skin.blush, 0.55 * pose.blush), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for offset in (-18, 0, 18):
                painter.drawLine(
                    QPointF(HEAD_CX + side * 132 + offset - 6, EYE_Y + 74),
                    QPointF(HEAD_CX + side * 132 + offset + 6, EYE_Y + 50),
                )
            painter.setPen(Qt.PenStyle.NoPen)

    # нос — крошечная тень, как в аниме
    painter.setPen(QPen(_fade(skin.skin_deep, 0.75), 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(HEAD_CX + 8, MOUTH_Y - 44), QPointF(HEAD_CX + 20, MOUTH_Y - 32))
    painter.setPen(Qt.PenStyle.NoPen)


def _draw_eyes(painter: QPainter, pose: Pose, skin: Skin, phase: float) -> None:
    for side in (-1, 1):
        cx = HEAD_CX + side * EYE_DX + pose.head_yaw * 10.0
        rx = EYE_RX * (1.0 + 0.06 * pose.eye_round)
        ry = EYE_RY * pose.eye_round

        closed = max(pose.blink, pose.wink if side < 0 else 0.0)
        open_amount = max(0.02, pose.eye_open * (1.0 - closed))

        painter.save()
        painter.translate(cx, EYE_Y + ry * 0.55)
        painter.scale(1.0, open_amount)
        painter.translate(-cx, -(EYE_Y + ry * 0.55))

        socket = _eye_path(cx, EYE_Y, rx, ry, side)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(skin.sclera))
        painter.drawPath(socket)

        # тень верхнего века на белке
        painter.save()
        painter.setClipPath(socket)
        shadow = QLinearGradient(cx, EYE_Y - ry, cx, EYE_Y + ry * 0.4)
        shadow.setColorAt(0.0, _fade(skin.lash, 0.45))
        shadow.setColorAt(1.0, _fade(skin.lash, 0.0))
        painter.setBrush(QBrush(shadow))
        painter.drawPath(socket)

        # радужка
        iris_x = cx + pose.look_x * rx * 0.34
        iris_y = EYE_Y + pose.look_y * ry * 0.30 + 3
        iris_r = rx * 0.72
        iris = QRadialGradient(QPointF(iris_x, iris_y + iris_r * 0.3), iris_r * 1.3)
        iris.setColorAt(0.0, skin.iris_glow)
        iris.setColorAt(0.45, skin.iris)
        iris.setColorAt(1.0, skin.iris_deep)
        painter.setBrush(QBrush(iris))
        painter.drawEllipse(QPointF(iris_x, iris_y), iris_r * 0.86, iris_r)

        # лимб и вертикальные волокна — глаз перестаёт быть плоским кружком
        painter.setPen(QPen(_fade(skin.iris_deep, 0.85), 4.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(iris_x, iris_y), iris_r * 0.86, iris_r)
        painter.setPen(QPen(_fade(skin.iris_deep, 0.35), 2.0))
        for step in range(-3, 4):
            angle = step * 0.38
            painter.drawLine(
                QPointF(iris_x + math.sin(angle) * iris_r * 0.34, iris_y + math.cos(angle) * iris_r * 0.34),
                QPointF(iris_x + math.sin(angle) * iris_r * 0.8, iris_y + math.cos(angle) * iris_r * 0.9),
            )

        # зрачок
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(skin.pupil))
        painter.drawEllipse(QPointF(iris_x, iris_y), iris_r * 0.34 * pose.pupil, iris_r * 0.42 * pose.pupil)

        # блики: крупный сверху, мелкий снизу, плюс искра настроения
        painter.setBrush(QBrush(_fade(skin.white, 0.95)))
        painter.drawEllipse(QPointF(iris_x - iris_r * 0.34, iris_y - iris_r * 0.42), iris_r * 0.30, iris_r * 0.26)
        painter.setBrush(QBrush(_fade(skin.white, 0.65)))
        painter.drawEllipse(QPointF(iris_x + iris_r * 0.30, iris_y + iris_r * 0.44), iris_r * 0.16, iris_r * 0.14)
        if pose.sparkle > 0.05:
            twinkle = 0.55 + 0.45 * math.sin(phase * 2.6 + side)
            painter.setBrush(QBrush(_fade(skin.white, 0.8 * pose.sparkle * twinkle)))
            painter.drawEllipse(QPointF(iris_x + iris_r * 0.1, iris_y - iris_r * 0.02), iris_r * 0.12, iris_r * 0.10)
        painter.restore()

        # ресницы: обводим верх той же миндалины, что и сам глаз — так обе стороны
        # получаются зеркальными сами собой, без ручного подбора точек
        outer = cx + side * rx * 1.06
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.save()
        painter.setClipRect(QRectF(cx - rx * 1.6, EYE_Y - ry * 2.0, rx * 3.2, ry * 2.05))
        painter.setPen(QPen(skin.lash, 14.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(socket)
        painter.restore()

        # внешняя ресничка вверх и в сторону
        painter.setPen(QPen(skin.lash, 9.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(
            QPointF(outer, EYE_Y - ry * 0.30),
            QPointF(outer + side * 26, EYE_Y - ry * 0.92),
        )

        # нижнее веко — тонкая линия, иначе взгляд «вытаращенный»
        painter.save()
        painter.setClipRect(QRectF(cx - rx * 1.6, EYE_Y + ry * 0.45, rx * 3.2, ry * 1.4))
        painter.setPen(QPen(_fade(skin.lash, 0.5), 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(socket)
        painter.restore()
        painter.restore()

        # закрытый глаз: аккуратная дуга вместо щели
        if closed > 0.75:
            painter.setPen(QPen(skin.lash, 11.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            arc = QPainterPath()
            arc.moveTo(cx - rx * 0.98, EYE_Y + ry * 0.24)
            arc.cubicTo(cx - rx * 0.4, EYE_Y + ry * 0.86, cx + rx * 0.4, EYE_Y + ry * 0.86, cx + rx * 0.98, EYE_Y + ry * 0.14)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(arc)


def _draw_brows(painter: QPainter, pose: Pose, skin: Skin) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for side in (-1, 1):
        cx = HEAD_CX + side * EYE_DX + pose.head_yaw * 10.0
        raise_y = -pose.brow_raise * 22.0
        # brow_angle > 0 — внутренний край вниз (строгость), < 0 — вверх («домиком»)
        inner_x = cx - side * 52
        outer_x = cx + side * 56
        inner_y = BROW_Y + raise_y + pose.brow_angle * 18.0
        outer_y = BROW_Y + raise_y - pose.brow_angle * 8.0
        path = QPainterPath()
        path.moveTo(inner_x, inner_y + 4)
        path.cubicTo(
            cx - side * 18, inner_y - 14,
            cx + side * 22, outer_y - 12,
            outer_x, outer_y + 6,
        )
        painter.setPen(QPen(skin.brow, 11.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)


def _draw_mouth(painter: QPainter, pose: Pose, skin: Skin) -> None:
    mouth = _mouth_path(pose.smile, pose.mouth_open)
    if pose.mouth_open > 0.02:
        inner = QLinearGradient(HEAD_CX, MOUTH_Y, HEAD_CX, MOUTH_Y + 50)
        inner.setColorAt(0.0, QColor("#5c2733"))
        inner.setColorAt(0.55, QColor("#8c3b47"))
        inner.setColorAt(1.0, QColor("#c96a72"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(inner))
        painter.drawPath(mouth)
        # язык виден только при широком раскрытии
        if pose.mouth_open > 0.45:
            painter.setBrush(QBrush(QColor("#e08a92")))
            painter.drawEllipse(
                QPointF(HEAD_CX, MOUTH_Y + 34 * pose.mouth_open),
                26 * pose.mouth_open, 12 * pose.mouth_open,
            )
        painter.setPen(QPen(_fade(skin.skin_deep, 0.8), 3.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(mouth)
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_fade(skin.skin_deep, 0.95), 6.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(mouth)


def _draw_extras(painter: QPainter, pose: Pose, skin: Skin) -> None:
    """Капля пота и прочие аниме-знаки состояния."""
    if pose.sweat > 0.05:
        painter.setPen(Qt.PenStyle.NoPen)
        drop = QPainterPath()
        x, y = HEAD_CX + 176, 380 + 18 * pose.sweat
        drop.moveTo(x, y - 26)
        drop.cubicTo(x + 20, y - 4, x + 16, y + 22, x, y + 22)
        drop.cubicTo(x - 16, y + 22, x - 20, y - 4, x, y - 26)
        painter.setBrush(QBrush(_fade(QColor("#9fd8ff"), 0.85 * pose.sweat)))
        painter.drawPath(drop)


def _draw_front_hair(painter: QPainter, pose: Pose, skin: Skin, phase: float) -> None:
    gradient = QLinearGradient(HEAD_CX, 180, HEAD_CX, 520)
    gradient.setColorAt(0.0, skin.hair_light)
    gradient.setColorAt(0.55, skin.hair)
    gradient.setColorAt(1.0, skin.hair_dark)

    painter.setPen(QPen(_fade(skin.hair_dark, 0.6), 3.0))
    for side in (-1, 1):
        painter.setBrush(QBrush(gradient))
        painter.drawPath(_side_lock(side, pose.hair_sway))

    painter.setBrush(QBrush(gradient))
    painter.drawPath(_bangs_path(pose.hair_sway))

    # блик-«нимб» поперёк чёлки
    painter.setPen(Qt.PenStyle.NoPen)
    shine = QLinearGradient(HEAD_CX - 160, 300, HEAD_CX + 160, 320)
    shine.setColorAt(0.0, _fade(skin.hair_shine, 0.0))
    shine.setColorAt(0.5, _fade(skin.hair_shine, 0.55))
    shine.setColorAt(1.0, _fade(skin.hair_shine, 0.0))
    painter.setBrush(QBrush(shine))
    band = QPainterPath()
    band.moveTo(HEAD_CX - 168, 306)
    band.cubicTo(HEAD_CX - 60, 262, HEAD_CX + 60, 262, HEAD_CX + 168, 300)
    band.cubicTo(HEAD_CX + 60, 300, HEAD_CX - 60, 300, HEAD_CX - 168, 306)
    band.closeSubpath()
    painter.drawPath(band)

    # антенна
    painter.setPen(QPen(_fade(skin.hair_dark, 0.6), 3.0))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(_ahoge_path(phase * 0.9, pose.hair_sway))

    # заколки у виска
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(skin.gold))
    for index in range(3):
        painter.drawRoundedRect(QRectF(HEAD_CX + 128 + index * 6, 336 + index * 26, 44, 9), 4, 4)


def _draw_neck(painter: QPainter, pose: Pose, skin: Skin) -> None:
    neck = QPainterPath()
    neck.moveTo(HEAD_CX - 52, FACE_CHIN - 60)
    neck.cubicTo(HEAD_CX - 56, FACE_CHIN + 30, HEAD_CX - 60, FACE_CHIN + 54, HEAD_CX - 66, SHOULDER_Y - 4)
    neck.lineTo(HEAD_CX + 66, SHOULDER_Y - 4)
    neck.cubicTo(HEAD_CX + 60, FACE_CHIN + 54, HEAD_CX + 56, FACE_CHIN + 30, HEAD_CX + 52, FACE_CHIN - 60)
    neck.closeSubpath()

    gradient = QLinearGradient(HEAD_CX, FACE_CHIN - 40, HEAD_CX, SHOULDER_Y)
    gradient.setColorAt(0.0, skin.skin_deep)
    gradient.setColorAt(0.5, skin.skin_shade)
    gradient.setColorAt(1.0, skin.skin)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawPath(neck)

    # чокер с звёздчатой подвеской — с референса
    painter.setBrush(QBrush(skin.cloth_dark))
    painter.drawRoundedRect(QRectF(HEAD_CX - 62, FACE_CHIN + 16, 124, 26), 10, 10)
    painter.setBrush(QBrush(skin.white))
    _draw_star(painter, HEAD_CX, FACE_CHIN + 29, 13)


def _draw_star(painter: QPainter, cx: float, cy: float, radius: float) -> None:
    path = QPainterPath()
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        length = radius if index % 2 == 0 else radius * 0.45
        point = QPointF(cx + math.cos(angle) * length, cy + math.sin(angle) * length)
        path.moveTo(point) if index == 0 else path.lineTo(point)
    path.closeSubpath()
    painter.drawPath(path)


def _draw_torso(painter: QPainter, pose: Pose, skin: Skin) -> None:
    body = QPainterPath()
    body.moveTo(HEAD_CX - 170, SHOULDER_Y + 6)
    body.cubicTo(HEAD_CX - 100, SHOULDER_Y - 38, HEAD_CX + 100, SHOULDER_Y - 38, HEAD_CX + 170, SHOULDER_Y + 6)
    body.cubicTo(HEAD_CX + 182, 830, HEAD_CX + 156, 930, HEAD_CX + 140, 1010)
    body.cubicTo(HEAD_CX + 70, 1042, HEAD_CX - 70, 1042, HEAD_CX - 140, 1010)
    body.cubicTo(HEAD_CX - 156, 930, HEAD_CX - 182, 830, HEAD_CX - 170, SHOULDER_Y + 6)
    body.closeSubpath()

    gradient = QLinearGradient(HEAD_CX, SHOULDER_Y, HEAD_CX, 1030)
    gradient.setColorAt(0.0, skin.cloth_dark)
    gradient.setColorAt(1.0, skin.cloth_dark_2)
    painter.setPen(QPen(_fade(skin.line, 0.6), 3.0))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(body)

    # бирюзовый воротник-накидка
    cape = QPainterPath()
    cape.moveTo(HEAD_CX - 176, SHOULDER_Y + 10)
    cape.cubicTo(HEAD_CX - 100, SHOULDER_Y - 34, HEAD_CX + 100, SHOULDER_Y - 34, HEAD_CX + 176, SHOULDER_Y + 10)
    cape.cubicTo(HEAD_CX + 124, SHOULDER_Y + 100, HEAD_CX - 124, SHOULDER_Y + 100, HEAD_CX - 176, SHOULDER_Y + 10)
    cape.closeSubpath()
    cape_gradient = QLinearGradient(HEAD_CX, SHOULDER_Y - 20, HEAD_CX, SHOULDER_Y + 100)
    cape_gradient.setColorAt(0.0, skin.cloth_teal)
    cape_gradient.setColorAt(1.0, skin.cloth_teal_deep)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(cape_gradient))
    painter.drawPath(cape)

    # белая кромка воротника
    painter.setPen(QPen(_fade(skin.white, 0.8), 5.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    edge = QPainterPath()
    edge.moveTo(HEAD_CX - 170, SHOULDER_Y + 16)
    edge.cubicTo(HEAD_CX - 94, SHOULDER_Y - 26, HEAD_CX + 94, SHOULDER_Y - 26, HEAD_CX + 170, SHOULDER_Y + 16)
    painter.drawPath(edge)

    # золотой узел на груди
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(skin.gold))
    painter.drawEllipse(QPointF(HEAD_CX, 852), 34, 34)
    painter.setBrush(QBrush(skin.gold_deep))
    painter.drawEllipse(QPointF(HEAD_CX, 852), 18, 18)
    painter.setBrush(QBrush(skin.gold))
    for side in (-1, 1):
        painter.drawEllipse(QPointF(HEAD_CX + side * 46, 838), 18, 22)
    # кисточки
    painter.setPen(QPen(skin.gold, 6.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    swing = pose.body_sway * 8.0
    for side in (-1, 1):
        painter.drawLine(QPointF(HEAD_CX + side * 20, 884), QPointF(HEAD_CX + side * 26 + swing, 962))

    # блик по ткани — костюм перестаёт быть плоским пятном
    painter.setPen(Qt.PenStyle.NoPen)
    sheen = QLinearGradient(HEAD_CX - 150, 800, HEAD_CX + 20, 1000)
    sheen.setColorAt(0.0, _fade(skin.white, 0.10))
    sheen.setColorAt(1.0, _fade(skin.white, 0.0))
    painter.setBrush(QBrush(sheen))
    painter.drawPath(body)


def _draw_skirt(painter: QPainter, pose: Pose, skin: Skin) -> None:
    drift = pose.body_sway * 12.0

    # газовая накидка сзади — полупрозрачная, как на референсе
    gauze = QPainterPath()
    gauze.moveTo(HEAD_CX - 150, 1000)
    gauze.cubicTo(HEAD_CX - 250 + drift, 1180, HEAD_CX - 268 + drift, 1330, HEAD_CX - 236 + drift, 1430)
    gauze.lineTo(HEAD_CX + 236 + drift, 1430)
    gauze.cubicTo(HEAD_CX + 268 + drift, 1330, HEAD_CX + 250 + drift, 1180, HEAD_CX + 150, 1000)
    gauze.closeSubpath()
    veil = QLinearGradient(HEAD_CX, 1000, HEAD_CX, 1440)
    veil.setColorAt(0.0, _fade(skin.cloth_gauze, 0.55))
    veil.setColorAt(1.0, _fade(skin.cloth_gauze, 0.05))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(veil))
    painter.drawPath(gauze)

    # юбка в складку
    skirt = QPainterPath()
    skirt.moveTo(HEAD_CX - 146, 996)
    skirt.cubicTo(HEAD_CX - 176, 1080, HEAD_CX - 196 + drift * 0.6, 1140, HEAD_CX - 204 + drift, 1196)
    step = 408 / 8
    for index in range(8):
        x0 = HEAD_CX - 204 + drift + index * step
        skirt.cubicTo(x0 + step * 0.3, 1176, x0 + step * 0.7, 1232, x0 + step, 1196)
    skirt.cubicTo(HEAD_CX + 196 + drift * 0.6, 1140, HEAD_CX + 176, 1080, HEAD_CX + 146, 996)
    skirt.cubicTo(HEAD_CX + 60, 1030, HEAD_CX - 60, 1030, HEAD_CX - 146, 996)
    skirt.closeSubpath()

    gradient = QLinearGradient(HEAD_CX, 990, HEAD_CX, 1210)
    gradient.setColorAt(0.0, skin.cloth_teal_deep)
    gradient.setColorAt(0.55, skin.cloth_teal)
    gradient.setColorAt(1.0, skin.cloth_teal_deep)
    painter.setPen(QPen(_fade(skin.line, 0.5), 3.0))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(skirt)

    # складки
    painter.setPen(QPen(_fade(skin.cloth_teal_deep, 0.8), 4.0))
    for index in range(1, 8):
        x = HEAD_CX - 204 + drift + index * step
        painter.drawLine(QPointF(x - drift * 0.4, 1040), QPointF(x, 1190))

    # пояс с золотой пряжкой
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(skin.cloth_dark))
    painter.drawRoundedRect(QRectF(HEAD_CX - 150, 976, 300, 40), 14, 14)
    painter.setBrush(QBrush(skin.gold))
    painter.drawRoundedRect(QRectF(HEAD_CX + 78, 968, 66, 58), 12, 12)
    painter.setBrush(QBrush(skin.gold_deep))
    painter.drawRoundedRect(QRectF(HEAD_CX + 90, 982, 42, 30), 8, 8)


def _draw_legs(painter: QPainter, pose: Pose, skin: Skin) -> None:
    gradient = QLinearGradient(HEAD_CX, 1150, HEAD_CX, 1420)
    gradient.setColorAt(0.0, skin.skin)
    gradient.setColorAt(1.0, skin.skin_shade)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    for side in (-1, 1):
        leg = QPainterPath()
        top = HEAD_CX + side * 62
        leg.moveTo(top - 54, 1120)
        leg.cubicTo(top - 58, 1260, top - 48, 1360, top - 44, 1440)
        leg.lineTo(top + 44, 1440)
        leg.cubicTo(top + 48, 1360, top + 58, 1260, top + 54, 1120)
        leg.closeSubpath()
        painter.drawPath(leg)

    # тёмные гетры с золотой каймой
    painter.setBrush(QBrush(skin.cloth_dark))
    for side in (-1, 1):
        top = HEAD_CX + side * 62
        painter.drawRoundedRect(QRectF(top - 56, 1352, 112, 148), 22, 22)
        painter.setBrush(QBrush(skin.gold))
        painter.drawRoundedRect(QRectF(top - 56, 1352, 112, 12), 6, 6)
        painter.setBrush(QBrush(skin.cloth_dark))


def _draw_arm(painter: QPainter, pose: Pose, skin: Skin, side: int, front: bool) -> None:
    """Рука из двух сегментов. Правая умеет махать — приветствие и жесты при речи."""
    shoulder_x = HEAD_CX + side * 172
    shoulder_y = SHOULDER_Y + 18

    wave = pose.wave if side > 0 else 0.0
    swing = pose.arm_swing * 3.0 * (1.0 if side > 0 else -1.0)
    # руки висят вдоль корпуса и чуть расходятся наружу — так силуэт читается
    upper_angle = side * (-6.0 + swing) - side * wave * 130.0
    fore_angle = side * 6.0 - side * wave * 40.0

    painter.save()
    painter.translate(shoulder_x, shoulder_y)
    painter.rotate(upper_angle)

    # плечевая часть: бирюзовый рукав-накидка
    sleeve = QPainterPath()
    sleeve.moveTo(-40, -22)
    sleeve.cubicTo(-54, 60, -46, 130, -34, 176)
    sleeve.lineTo(38, 176)
    sleeve.cubicTo(48, 120, 52, 50, 40, -22)
    sleeve.closeSubpath()
    gradient = QLinearGradient(0, -20, 0, 180)
    gradient.setColorAt(0.0, skin.cloth_teal)
    gradient.setColorAt(1.0, skin.cloth_teal_deep)
    painter.setPen(QPen(_fade(skin.line, 0.5), 3.0))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(sleeve)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(_fade(skin.white, 0.85)))
    painter.drawRoundedRect(QRectF(-42, 160, 86, 18), 8, 8)

    # предплечье в чёрной перчатке
    painter.translate(0, 176)
    painter.rotate(fore_angle)
    fore = QPainterPath()
    fore.moveTo(-34, 0)
    fore.cubicTo(-40, 70, -36, 140, -30, 196)
    fore.lineTo(32, 196)
    fore.cubicTo(38, 140, 40, 70, 34, 0)
    fore.closeSubpath()
    glove = QLinearGradient(0, 0, 0, 200)
    glove.setColorAt(0.0, skin.cloth_dark)
    glove.setColorAt(1.0, skin.cloth_dark_2)
    painter.setPen(QPen(_fade(skin.line, 0.5), 3.0))
    painter.setBrush(QBrush(glove))
    painter.drawPath(fore)

    # кисть
    painter.setPen(Qt.PenStyle.NoPen)
    hand = QLinearGradient(0, 190, 0, 260)
    hand.setColorAt(0.0, skin.skin)
    hand.setColorAt(1.0, skin.skin_shade)
    painter.setBrush(QBrush(hand))
    painter.drawEllipse(QPointF(0, 216), 30, 38)
    if wave > 0.15:
        painter.setPen(QPen(_fade(skin.skin_deep, 0.6), 3.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(-1, 3):
            painter.drawLine(QPointF(index * 12, 196), QPointF(index * 12, 232))
    painter.restore()
