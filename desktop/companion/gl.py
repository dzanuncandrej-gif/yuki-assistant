"""Персонаж на видеокарте: деформируемая сетка поверх оригинального рисунка.

Это не картинка, которую двигают по экрану, и не веб-страница. Это виджет
десктопного приложения (`QOpenGLWidget`), который каждый кадр натягивает
исходный рисунок на сетку 64×128 и деформирует её в вершинном шейдере:

* голова поворачивается вокруг шеи, кожа и волосы тянутся за ней плавно;
* веки закрываются сжатием области глаза — так делают двумерные марионетки,
  и рисунок при этом остаётся авторским;
* рот раскрывается растяжением области губ, внутри проявляется полость;
* пряди волос качаются по цепочке звеньев (физика считается на процессоре,
  результат уходит в шейдер массивом смещений);
* корпус дышит и покачивается.

Одна сетка на всю фигуру — поэтому нет швов, дыр и «двойных контуров», которые
неизбежны при раскладывании персонажа на отдельные картинки.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QOpenGLFunctions, QVector2D, QVector3D, QVector4D
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from core import config

from .rig import Pose

PARTS_DIR = config.ROOT / "assets" / "companion" / "parts"

GRID_X = 64
GRID_Y = 128
HAIR_NODES = 10

GL_TRIANGLES = 0x0004
GL_UNSIGNED_INT = 0x1405
GL_COLOR_BUFFER_BIT = 0x4000
GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303


def assets_ready() -> bool:
    return (PARTS_DIR / "parts.json").exists() and (PARTS_DIR / "figure.png").exists()


VERT = """#version 330 core
layout(location = 0) in vec2 aUV;

out vec2 vUV;
out vec2 vPos;

uniform vec2  uAspect;      // соотношение сторон холста и рисунка
uniform float uScale;
uniform vec2  uCenter;      // точка рисунка, которая окажется в центре кадра
uniform float uZoom;        // 1 — фигура целиком, больше — крупный план

uniform vec2  uNeck;        // шея в координатах рисунка 0..1
uniform vec3  uHead;        // поворот, наклон, кивок
uniform float uBreath;
uniform float uSway;
uniform float uLean;

uniform vec4  uEyeL;        // x,y,w,h области глаза
uniform vec4  uEyeR;
uniform vec2  uEyeClose;    // насколько закрыт каждый глаз
uniform vec4  uMouth;
uniform float uMouthOpen;

uniform float uHairL[10];   // смещения прядей по высоте
uniform float uHairR[10];
uniform vec2  uHairLBox;    // x, ширина
uniform vec2  uHairRBox;
uniform float uHairTop;     // с какой высоты начинаются пряди

float weightAround(vec2 p, vec2 center, vec2 radius) {
    vec2 d = (p - center) / radius;
    float distance = dot(d, d);
    return exp(-distance * 2.2);
}

// плавная ступенька по вертикали: используется для дыхания и наклона
float band(float value, float low, float high) {
    return smoothstep(low, low + 0.08, value) * (1.0 - smoothstep(high - 0.08, high, value));
}

float hairOffset(float v, float offsets[10], float top) {
    float t = clamp((v - top) / max(0.0001, 1.0 - top), 0.0, 1.0);
    float scaled = t * 9.0;
    int index = int(floor(scaled));
    int next = min(index + 1, 9);
    float fraction = scaled - float(index);
    return mix(offsets[index], offsets[next], fraction) * t;
}

void main() {
    vec2 p = aUV;
    vUV = aUV;

    // --- голова: поворот вокруг шеи с мягким затуханием вниз ---
    float headMask = smoothstep(uNeck.y + 0.10, uNeck.y - 0.16, p.y);
    vec2 fromNeck = (p - uNeck) * vec2(1.0, 1.0);

    float tilt = uHead.z * 0.10 * headMask;
    float cosT = cos(tilt), sinT = sin(tilt);
    vec2 rotated = vec2(
        fromNeck.x * cosT - fromNeck.y * sinT * 0.42,
        fromNeck.x * sinT * 2.2 + fromNeck.y * cosT
    );
    p = uNeck + rotated;

    // цилиндрический разворот: дальняя щека уходит, ближняя выступает
    float turn = uHead.x * headMask;
    float depth = sin(3.14159 * clamp((aUV.x - uNeck.x) * 2.6 + 0.5, 0.0, 1.0));
    p.x += turn * 0.035 * depth;
    p.x -= (aUV.x - uNeck.x) * abs(turn) * 0.12 * headMask;
    p.y -= uHead.y * 0.020 * headMask;

    // --- дыхание и покачивание корпуса ---
    float chest = band(aUV.y, uNeck.y, uNeck.y + 0.30);
    p.y -= uBreath * 0.0045 * (headMask + chest);
    p.x += (aUV.x - 0.5) * uBreath * 0.004 * chest;

    float rise = pow(1.0 - aUV.y, 1.5);
    p.x += uSway * 0.010 * rise;
    p.y -= uLean * 0.004 * rise;

    // --- волосы: цепочка звеньев тянет пряди в стороны ---
    float leftBand = 1.0 - smoothstep(uHairLBox.x + uHairLBox.y * 0.55,
                                      uHairLBox.x + uHairLBox.y * 1.15, aUV.x);
    leftBand *= smoothstep(uHairTop - 0.05, uHairTop + 0.05, aUV.y);
    p.x += hairOffset(aUV.y, uHairL, uHairTop) * leftBand;

    float rightBand = smoothstep(uHairRBox.x - uHairRBox.y * 0.15,
                                 uHairRBox.x + uHairRBox.y * 0.45, aUV.x);
    rightBand *= smoothstep(uHairTop - 0.05, uHairTop + 0.05, aUV.y);
    p.x += hairOffset(aUV.y, uHairR, uHairTop) * rightBand;

    // --- веки: область глаза сжимается к линии нижних ресниц ---
    vec4 eyes[2] = vec4[2](uEyeL, uEyeR);
    for (int i = 0; i < 2; i++) {
        vec4 box = eyes[i];
        vec2 center = box.xy + box.zw * 0.5;
        float influence = weightAround(aUV, center, box.zw * 1.35);
        float bottom = box.y + box.w * 0.92;
        float close = uEyeClose[i] * influence;
        p.y += (bottom - aUV.y) * close * 0.92;
    }

    // --- рот: губы расходятся, подбородок чуть опускается ---
    vec2 mouthCenter = uMouth.xy + uMouth.zw * 0.5;
    float mouthInfluence = weightAround(aUV, mouthCenter, uMouth.zw * 1.9);
    float side = sign(aUV.y - mouthCenter.y);
    p.y += side * uMouthOpen * uMouth.w * 0.55 * mouthInfluence;
    p.x += (aUV.x - mouthCenter.x) * uMouthOpen * 0.10 * mouthInfluence;

    vPos = p;
    vec2 clip = (p - uCenter) * 2.0 * uAspect * uScale * uZoom;
    gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}
"""

FRAG = """#version 330 core
in vec2 vUV;
in vec2 vPos;
out vec4 fragColor;

uniform sampler2D uTexture;
uniform vec4  uMouth;
uniform float uMouthOpen;
uniform vec2  uEyeClose;
uniform vec4  uEyeL;
uniform vec4  uEyeR;
uniform float uBlush;
uniform float uSpark;
uniform float uGlow;
uniform vec3  uAccent;
uniform float uTime;

float ellipse(vec2 p, vec2 center, vec2 radius) {
    vec2 d = (p - center) / max(radius, vec2(0.0001));
    return dot(d, d);
}

void main() {
    vec4 color = texture(uTexture, vUV);
    if (color.a < 0.004) discard;

    // полость рта: темнеет между губами, когда рот раскрыт
    if (uMouthOpen > 0.02) {
        vec2 center = uMouth.xy + uMouth.zw * vec2(0.5, 0.58);
        vec2 radius = uMouth.zw * vec2(0.30, 0.16 + 0.42 * uMouthOpen);
        float inside = ellipse(vUV, center, radius);
        float mask = smoothstep(1.0, 0.35, inside) * clamp(uMouthOpen * 1.6, 0.0, 1.0);
        vec3 cavity = mix(vec3(0.34, 0.13, 0.16), vec3(0.62, 0.26, 0.28), 0.35);
        color.rgb = mix(color.rgb, cavity, mask * 0.92);
        // язык у нижнего края полости
        float tongue = smoothstep(1.0, 0.2, ellipse(vUV, center + vec2(0.0, radius.y * 0.55),
                                                    radius * vec2(0.55, 0.35)));
        color.rgb = mix(color.rgb, vec3(0.78, 0.42, 0.44), tongue * mask * 0.6);
    }

    // линия ресниц на краю опускающегося века
    vec4 eyes[2] = vec4[2](uEyeL, uEyeR);
    for (int i = 0; i < 2; i++) {
        float close = uEyeClose[i];
        if (close < 0.05) continue;
        vec4 box = eyes[i];
        float lid = box.y + box.w * (0.30 + 0.58 * close);
        float line = smoothstep(box.w * 0.16, 0.0, abs(vUV.y - lid));
        float span = smoothstep(box.z * 0.62, box.z * 0.34, abs(vUV.x - (box.x + box.z * 0.5)));
        color.rgb = mix(color.rgb, vec3(0.16, 0.12, 0.10), line * span * close * 0.55);
    }

    // румянец на щеках
    if (uBlush > 0.01) {
        vec2 leftCheek = uEyeL.xy + uEyeL.zw * vec2(0.5, 2.1);
        vec2 rightCheek = uEyeR.xy + uEyeR.zw * vec2(0.5, 2.1);
        float glowLeft = smoothstep(1.0, 0.0, ellipse(vUV, leftCheek, uEyeL.zw * vec2(1.1, 0.7)));
        float glowRight = smoothstep(1.0, 0.0, ellipse(vUV, rightCheek, uEyeR.zw * vec2(1.1, 0.7)));
        color.rgb = mix(color.rgb, vec3(0.96, 0.55, 0.55), (glowLeft + glowRight) * uBlush * 0.32);
    }

    // искра в глазах
    if (uSpark > 0.02) {
        float twinkle = 0.5 + 0.5 * sin(uTime * 2.4);
        vec2 sparkL = uEyeL.xy + uEyeL.zw * vec2(0.62, 0.34);
        vec2 sparkR = uEyeR.xy + uEyeR.zw * vec2(0.62, 0.34);
        float dot1 = smoothstep(1.0, 0.0, ellipse(vUV, sparkL, uEyeL.zw * 0.16));
        float dot2 = smoothstep(1.0, 0.0, ellipse(vUV, sparkR, uEyeR.zw * 0.16));
        float amount = uSpark * (0.45 + 0.55 * twinkle) * (1.0 - max(uEyeClose.x, uEyeClose.y));
        color.rgb += vec3(1.0) * (dot1 + dot2) * amount * 0.55;
    }

    // контровой свет по силуэту — фигура вписывается в тёмный интерфейс
    float rim = smoothstep(0.35, 1.0, 1.0 - color.a) + 0.0;
    float edge = 1.0 - smoothstep(0.15, 0.9, color.a);
    color.rgb += uAccent * edge * (0.25 + 0.55 * uGlow);

    fragColor = vec4(color.rgb, color.a);
}
"""


@dataclass(frozen=True)
class Marks:
    """Опорные точки в долях от размера рисунка — так их удобно слать в шейдер."""

    width: float
    height: float
    neck: tuple[float, float]
    eye_left: tuple[float, float, float, float]
    eye_right: tuple[float, float, float, float]
    mouth: tuple[float, float, float, float]
    hair_left: tuple[float, float]
    hair_right: tuple[float, float]
    hair_top: float


def _load_marks() -> Marks | None:
    path = PARTS_DIR / "parts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    width = float(data["figure"]["width"])
    height = float(data["figure"]["height"])

    def box(values: list[float]) -> tuple[float, float, float, float]:
        left, top, right, bottom = values
        return (left / width, top / height, (right - left) / width, (bottom - top) / height)

    hair_left = box(data["hair_left_box"])
    hair_right = box(data["hair_right_box"])
    return Marks(
        width=width,
        height=height,
        neck=(data["neck_pivot"][0] / width, data["neck_pivot"][1] / height),
        eye_left=box(data["eye_left"]),
        eye_right=box(data["eye_right"]),
        mouth=box(data["mouth_box"]),
        hair_left=(hair_left[0], hair_left[2]),
        hair_right=(hair_right[0], hair_right[2]),
        hair_top=hair_left[1],
    )


class HairChain:
    """Цепочка звеньев: верх закреплён у головы, низ отстаёт — прядь живёт инерцией."""

    def __init__(self, nodes: int = HAIR_NODES) -> None:
        self.offsets = np.zeros(nodes, dtype=np.float32)
        self.speeds = np.zeros(nodes, dtype=np.float32)

    def step(self, drive: float, elasticity: float = 0.24, damping: float = 0.86) -> np.ndarray:
        count = len(self.offsets)
        self.offsets[0] = drive * 0.2
        for index in range(1, count):
            weight = index / (count - 1)
            target = drive * weight * weight
            self.speeds[index] += (self.offsets[index - 1] - self.offsets[index]) * elasticity
            self.speeds[index] += (target - self.offsets[index]) * 0.05
            self.speeds[index] *= damping
            self.offsets[index] += self.speeds[index]
        return self.offsets


class GLCharacter(QOpenGLWidget):
    """Виджет живого персонажа. Снаружи задаются поза, состояние и громкость."""

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        self.marks = _load_marks()
        self.available = self.marks is not None and (PARTS_DIR / "figure.png").exists()
        self.error = ""

        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo: QOpenGLBuffer | None = None
        self._ibo: QOpenGLBuffer | None = None
        self._texture: QOpenGLTexture | None = None
        self._indices = 0

        self._chain_left = HairChain()
        self._chain_right = HairChain()
        self._hair_drive = 0.0
        self._hair_speed = 0.0
        self._time = 0.0
        self._accent = QColor("#58b6ff")
        # кадрирование по умолчанию — поясной план: лицо крупное, мимика видна
        self._camera = (0.5, 0.30)
        self._zoom = 1.0
        self.pose = Pose()
        self.set_framing("bust")

    # ---------------------------------------------------------------- внешнее API

    def set_accent(self, color: QColor) -> None:
        self._accent = QColor(color)

    def set_framing(self, mode: str) -> None:
        """Кадр: «full» — фигура целиком, «bust» — по пояс, «face» — крупный план.

        На общем плане лицо занимает несколько десятков пикселей, и никакая мимика
        не читается. Поэтому по умолчанию камера подходит ближе.
        """
        frames = {
            "full": ((0.5, 0.50), 1.0),
            "bust": ((0.5, 0.28), 2.05),
            "face": ((0.5, 0.16), 3.4),
        }
        self._camera, self._zoom = frames.get(mode, frames["bust"])

    def set_pose(self, pose: Pose) -> None:
        self.pose = pose

    def advance(self, delta: float) -> None:
        """Физика волос считается здесь: шейдеру уходит уже готовый массив смещений."""
        self._time += delta
        pose = self.pose
        target = pose.hair_sway * 0.05 + math.sin(self._time * 0.6) * 0.004
        self._hair_speed += (target - self._hair_drive) * 0.18
        self._hair_speed *= 0.86
        self._hair_drive += self._hair_speed
        self._chain_left.step(-self._hair_drive - pose.head_yaw * 0.012)
        self._chain_right.step(self._hair_drive + pose.head_yaw * 0.012)

    # ---------------------------------------------------------------- OpenGL

    def initializeGL(self) -> None:  # noqa: N802 — Qt-нейминг
        if not self.available:
            return
        functions = QOpenGLFunctions(self.context())
        functions.initializeOpenGLFunctions()

        program = QOpenGLShaderProgram(self)
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERT):
            self.error = program.log()
            return
        if not program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FRAG):
            self.error = program.log()
            return
        if not program.link():
            self.error = program.log()
            return
        self._program = program

        vertices = self._build_grid()
        self._indices = len(vertices)

        self._vao = QOpenGLVertexArrayObject(self)
        self._vao.create()
        self._vao.bind()

        self._vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vbo.create()
        self._vbo.bind()
        self._vbo.allocate(vertices.tobytes(), vertices.nbytes)
        program.bind()
        program.enableAttributeArray(0)
        program.setAttributeBuffer(0, 0x1406, 0, 2, 0)  # GL_FLOAT

        self._vao.release()
        program.release()

        image = QImage(str(PARTS_DIR / "figure.png")).convertToFormat(QImage.Format.Format_RGBA8888)
        # координата v=0 — верх рисунка, поэтому переворачивать текстуру не нужно
        texture = QOpenGLTexture(image)
        texture.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
        texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        self._texture = texture

    @staticmethod
    def _build_grid() -> np.ndarray:
        """Развёрнутый список треугольников.

        Индексный буфер PySide6 через glDrawElements не отдаёт смещение, поэтому
        сетка разворачивается один раз при запуске — памяти это стоит копейки.
        """
        xs = np.linspace(0.0, 1.0, GRID_X + 1, dtype=np.float32)
        ys = np.linspace(0.0, 1.0, GRID_Y + 1, dtype=np.float32)
        grid = np.stack(np.meshgrid(xs, ys, indexing="xy"), axis=-1).astype(np.float32)

        top_left = grid[:-1, :-1]
        top_right = grid[:-1, 1:]
        bottom_left = grid[1:, :-1]
        bottom_right = grid[1:, 1:]

        triangles = np.stack(
            [top_left, top_right, bottom_left, top_right, bottom_right, bottom_left], axis=2
        )
        return triangles.reshape(-1, 2).astype(np.float32)

    def paintGL(self) -> None:  # noqa: N802
        functions = QOpenGLFunctions(self.context())
        functions.initializeOpenGLFunctions()
        functions.glClearColor(0.0, 0.0, 0.0, 0.0)
        functions.glClear(GL_COLOR_BUFFER_BIT)
        if self._program is None or self._vao is None or self._texture is None or self.marks is None:
            return

        functions.glEnable(GL_BLEND)
        functions.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        marks = self.marks
        pose = self.pose
        program = self._program
        program.bind()
        self._vao.bind()
        self._texture.bind(0)
        place = program.uniformLocation

        # холст и рисунок редко совпадают по пропорциям: вписываем фигуру целиком
        widget_ratio = max(1e-3, self.width() / max(1.0, self.height()))
        art_ratio = marks.width / marks.height
        if widget_ratio > art_ratio:
            aspect = QVector2D(art_ratio / widget_ratio, 1.0)
        else:
            aspect = QVector2D(1.0, widget_ratio / art_ratio)

        program.setUniformValue(place("uAspect"), aspect)
        program.setUniformValue1f(place("uScale"), float(pose.scale))
        program.setUniformValue(place("uCenter"), QVector2D(*self._camera))
        program.setUniformValue1f(place("uZoom"), float(self._zoom))
        program.setUniformValue(place("uNeck"), QVector2D(*marks.neck))
        program.setUniformValue(
            place("uHead"),
            QVector3D(float(pose.head_yaw), float(pose.head_pitch), float(pose.head_tilt)),
        )
        program.setUniformValue1f(place("uBreath"), float(pose.breath))
        program.setUniformValue1f(place("uSway"), float(pose.body_sway))
        program.setUniformValue1f(place("uLean"), float(pose.lean))

        program.setUniformValue(place("uEyeL"), QVector4D(*marks.eye_left))
        program.setUniformValue(place("uEyeR"), QVector4D(*marks.eye_right))
        closed = min(1.0, pose.blink + (1.0 - min(1.0, pose.eye_open)) * 0.8)
        program.setUniformValue(
            place("uEyeClose"), QVector2D(min(1.0, closed + pose.wink), closed)
        )
        program.setUniformValue(place("uMouth"), QVector4D(*marks.mouth))
        program.setUniformValue1f(place("uMouthOpen"), float(pose.mouth_open))

        for name, chain in (("uHairL", self._chain_left), ("uHairR", self._chain_right)):
            for index, value in enumerate(chain.offsets):
                program.setUniformValue1f(place(f"{name}[{index}]"), float(value))
        program.setUniformValue(place("uHairLBox"), QVector2D(*marks.hair_left))
        program.setUniformValue(place("uHairRBox"), QVector2D(*marks.hair_right))
        program.setUniformValue1f(place("uHairTop"), float(marks.hair_top))

        program.setUniformValue1f(place("uBlush"), float(pose.blush))
        program.setUniformValue1f(place("uSpark"), float(pose.sparkle))
        program.setUniformValue1f(place("uGlow"), float(pose.glow))
        program.setUniformValue(
            place("uAccent"),
            QVector3D(self._accent.redF(), self._accent.greenF(), self._accent.blueF()),
        )
        program.setUniformValue1f(place("uTime"), float(self._time))
        program.setUniformValue1i(place("uTexture"), 0)

        functions.glDrawArrays(GL_TRIANGLES, 0, self._indices)

        self._texture.release()
        self._vao.release()
        program.release()
