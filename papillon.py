#!/usr/bin/env python3
"""
Papillon — Beautiful butterflies fill your Ubuntu desktop.
Wing geometry and texture logic adapted from the Papillon CodePen
by Pink Pixel (Apache-2.0).
"""

import sys
import math
import random
import time
import platform

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt5.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QPen,
    QBrush,
    QImage,
)
import numpy as np


# ── Configuration ───────────────────────────────────────

DURATION_SECONDS = 120
BUTTERFLY_COUNT = 24
FPS = 60
SPAWN_INTERVAL_MS = 350

MIN_SCALE = 12
MAX_SCALE = 22

CLICK_THROUGH = True
MOUSE_REPEL_RADIUS = 160
MOUSE_REPEL_STRENGTH = 2.0

# Flight rhythm, in 1/60 s physics steps and pixels per step.
CRUISE_FRAMES = (120, 180)
HOVER_FRAMES = (30, 90)
CRUISE_SPEED = (0.7, 1.2)
HOVER_SPEED = 0.12
TURN_RANGE = (0.5, 1.8)
MAX_TURN_RATE = 0.035
GLIDE_SINK = 0.12

PRESETS = {
    "monarch": {
        "primary": QColor("#e18a32"),
        "secondary": QColor("#f5c66b"),
        "edge": QColor("#211d19"),
    },
    "morpho": {
        "primary": QColor("#269ac9"),
        "secondary": QColor("#9cd9e5"),
        "edge": QColor("#172c35"),
    },
    "luna": {
        "primary": QColor("#b9cd8b"),
        "secondary": QColor("#e9e5b0"),
        "edge": QColor("#535640"),
    },
}

PRESET_NAMES = list(PRESETS.keys())


# ── Wing outline paths (CodePen coordinates, Y negated for Qt) ──

def make_forewing(s):
    path = QPainterPath()
    path.moveTo(0.08 * s, -0.26 * s)
    path.cubicTo(
        0.50 * s, -1.15 * s,
        1.90 * s, -2.22 * s,
        2.95 * s, -2.32 * s,
    )
    path.cubicTo(
        3.35 * s, -2.36 * s,
        2.94 * s, -1.04 * s,
        2.56 * s, -0.44 * s,
    )
    path.cubicTo(
        2.22 * s, 0.13 * s,
        1.04 * s, 0.51 * s,
        0.10 * s, 0.22 * s,
    )
    path.quadTo(0.04 * s, 0.0, 0.08 * s, -0.26 * s)
    path.closeSubpath()
    return path


def make_hindwing(s):
    path = QPainterPath()
    path.moveTo(0.10 * s, -0.03 * s)
    path.cubicTo(
        0.80 * s, 0.0,
        1.75 * s, -0.06 * s,
        2.37 * s, 0.32 * s,
    )
    path.cubicTo(
        2.55 * s, 0.65 * s,
        2.16 * s, 1.06 * s,
        2.13 * s, 1.18 * s,
    )
    path.cubicTo(
        2.05 * s, 1.48 * s,
        1.79 * s, 1.43 * s,
        1.69 * s, 1.65 * s,
    )
    path.cubicTo(
        1.54 * s, 1.88 * s,
        1.34 * s, 1.72 * s,
        1.20 * s, 1.88 * s,
    )
    path.cubicTo(
        0.66 * s, 2.04 * s,
        0.23 * s, 1.17 * s,
        0.10 * s, 0.32 * s,
    )
    path.lineTo(0.10 * s, -0.03 * s)
    path.closeSubpath()
    return path


def sample_outline(path, n=160):
    return [path.pointAtPercent(i / n) for i in range(n)]


# ── Wing texture rendering ─────────────────────────────

def _render_single_wing(painter, wing_path, s, preset_name, is_hind):
    preset = PRESETS[preset_name]
    primary = preset["primary"]
    secondary = preset["secondary"]
    edge = preset["edge"]

    # 1 ── Base fill
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(primary))
    painter.drawPath(wing_path)

    # 2 ── Textured flecks (clipped to wing shape)
    painter.save()
    painter.setClipPath(wing_path)

    bounds = wing_path.boundingRect()
    rng = random.Random(hash((preset_name, is_hind, int(s * 100))))
    area = bounds.width() * bounds.height()
    fleck_count = min(900, max(150, int(area * 0.5)))

    for _ in range(fleck_count):
        x = bounds.x() + rng.random() * bounds.width()
        y = bounds.y() + rng.random() * bounds.height()
        c = QColor(secondary if rng.randint(0, 2) else edge)
        c.setAlpha(int(15 + rng.random() * 35))
        fw = 0.8 + rng.random() * 1.2
        fh = 1.2 + rng.random() * 1.8
        painter.fillRect(QRectF(x, y, fw, fh), c)

    # 3 ── Color cells between veins
    outline = sample_outline(wing_path, 160)
    root = QPointF(0.12 * s, 0.10 * s if is_hind else -0.18 * s)

    cell_color = QColor(secondary)
    cell_color.setAlpha(65)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(cell_color))

    for i in range(12, 143, 13):
        end = outline[i]
        next_pt = outline[min(i + 9, 155)]
        cell = QPainterPath()
        cell.moveTo(root)
        ctrl = QPointF(
            end.x() * 0.48,
            root.y() * 0.45 + end.y() * 0.55,
        )
        near_end = QPointF(
            end.x() * 0.88 + root.x() * 0.12,
            end.y() * 0.88 + root.y() * 0.12,
        )
        near_next = QPointF(
            next_pt.x() * 0.88 + root.x() * 0.12,
            next_pt.y() * 0.88 + root.y() * 0.12,
        )
        cell.quadTo(ctrl, near_end)
        cell.lineTo(near_next)
        cell.closeSubpath()
        painter.drawPath(cell)

    painter.restore()

    # 4 ── Dark wing-edge border
    edge_w = max(1.0, s * 0.08)
    painter.setPen(
        QPen(edge, edge_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    )
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(wing_path)

    # 5 ── Veins
    inner_mids = []
    vw = max(0.5, s * (0.018 if preset_name == "luna" else 0.032))
    vein_pen = QPen(edge, vw, Qt.SolidLine, Qt.RoundCap)

    for i in range(8, 151, 13):
        end = outline[i]
        mid = QPointF(
            root.x() + (end.x() - root.x()) * 0.6,
            root.y() + (end.y() - root.y()) * 0.6,
        )
        inner_mids.append(mid)

        painter.setPen(vein_pen)
        vein = QPainterPath()
        vein.moveTo(root)
        vein.quadTo(
            QPointF(mid.x(), mid.y() - s * 0.08), end
        )
        painter.drawPath(vein)

        branch_idx = min(i + 6, 159)
        branch = outline[branch_idx]
        branch_pen = QPen(
            edge, max(0.3, vw * 0.55), Qt.SolidLine, Qt.RoundCap
        )
        painter.setPen(branch_pen)
        bp = QPainterPath()
        bp.moveTo(mid)
        bp.quadTo(
            QPointF((mid.x() + branch.x()) / 2, mid.y()),
            branch,
        )
        painter.drawPath(bp)

    # Inner vein ring
    if len(inner_mids) > 1:
        ring_w = max(
            0.4, s * (0.012 if preset_name == "luna" else 0.022)
        )
        painter.setPen(
            QPen(edge, ring_w, Qt.SolidLine, Qt.RoundCap)
        )
        ring = QPainterPath()
        ring.moveTo(inner_mids[0])
        for mp in inner_mids[1:]:
            ring.lineTo(mp)
        painter.drawPath(ring)

    # 6 ── Margin dots
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("#f5edce")))

    wing_center = QPointF(
        (1.0 if is_hind else 1.3) * s,
        (0.7 if is_hind else -0.65) * s,
    )

    for i in range(13, 145, 5):
        pt = outline[i]
        dot = QPointF(
            pt.x() + (wing_center.x() - pt.x()) * 0.045,
            pt.y() + (wing_center.y() - pt.y()) * 0.045,
        )
        painter.save()
        painter.translate(dot)
        painter.rotate(math.degrees(i * 0.09))
        painter.drawEllipse(QPointF(0, 0), s * 0.015, s * 0.022)
        painter.restore()

    # 7 ── Luna eyespots
    if preset_name == "luna":
        ex = (1.25 if is_hind else 1.9) * s
        ey = (0.85 if is_hind else -1.1) * s
        spots = [
            (s * 0.092, edge),
            (s * 0.072, secondary),
            (s * 0.041, QColor("#655f40")),
            (s * 0.017, QColor("#d8dcbd")),
        ]
        for radius, color in spots:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.save()
            painter.translate(ex, ey)
            painter.rotate(-23)
            painter.drawEllipse(QPointF(0, 0), radius, radius * 0.8)
            painter.restore()

    # 8 ── Fine outer outline for crispness
    fine_edge = QColor(
        edge.red(), edge.green(), edge.blue(), 180
    )
    painter.setPen(
        QPen(
            fine_edge,
            max(0.5, s * 0.015),
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.RoundJoin,
        )
    )
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(wing_path)


# ── 3D model (port of the Three.js scene) ──────────────
#
# Everything below works in CodePen units (x right, y toward the head,
# z out of the butterfly's back).  Each surface is sampled densely enough
# that every sample lands on its own sub-pixel, then splatted per frame.

SUPERSAMPLE = 1.15
TEXTURE_DPR = 1.45
BODY_SPACING = 0.9
CAMERA_DIST = 14.0
L_LEVELS = 64
L_SCALE = 20.0


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


# Screen frame is X right, Y down, Z away from the viewer; CodePen
# (x, y, z) maps to (x, -y, -z).  Light positions are the CodePen ones.
_KEY = _unit([-3, -5, -7])
_FILL = _unit([4, 1, 5])
_HALF = _unit(_KEY + np.array([0.0, 0.0, -1.0]))
LIGHT_DIRS = np.stack(
    [[0.0, -1.0, 0.0], _KEY, _FILL, _HALF, [0.0, 0.0, 1.0]], axis=1
)

# HemisphereLight(0xfff6e7, 0x7e8990, 2.4), key 3.1, fill 1.7, all / pi.
HEMI_A = 0.435
HEMI_B = 0.249
KEY_K = 0.99
FILL_K = 0.54

FLIP = np.diag([1.0, -1.0, -1.0])


def _srgb_to_lin(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(
        c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055
    ) * 255.0


def _build_shade_lut():
    # (5-bit-per-channel albedo, light level) -> packed opaque ARGB32 pixel,
    # ACES-filmic toned with exposure 1.2 like the CodePen renderer.
    levels = np.arange(32, dtype=np.uint32)
    byte = ((levels << 3) | (levels >> 2)).astype(np.float32)
    lin = _srgb_to_lin(byte).astype(np.float32)
    light = (np.arange(L_LEVELS, dtype=np.float32) / L_SCALE) * 0.72
    x = lin[:, None] * light[None, :]
    toned = x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14)
    ch = np.round(_lin_to_srgb(toned)).astype(np.uint32)  # 32 x L_LEVELS
    b = ch[:, None, None, :]
    g = ch[None, :, None, :]
    r = ch[None, None, :, :]
    return (0xFF000000 | (r << 16) | (g << 8) | b).reshape(-1)


SHADE_LUT = _build_shade_lut()


class PointSet:

    def __init__(self, pos, nrm, bgr, spec=0.0):
        self.pos = np.ascontiguousarray(pos, dtype=np.float32)
        self.nrm = np.ascontiguousarray(nrm, dtype=np.float32)
        q = bgr.astype(np.int32) >> 3
        self.base = ((q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2]) * L_LEVELS
        self.spec = spec * 4.0


def _qimage_to_array(img):
    img = img.convertToFormat(QImage.Format_ARGB32)
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    arr = np.frombuffer(ptr, dtype=np.uint8)
    arr = arr.reshape(img.height(), img.bytesPerLine() // 4, 4)
    return arr[:, : img.width()].copy()


def _wing_points(scale, preset_name, hind):
    s = scale
    path = make_hindwing(s) if hind else make_forewing(s)
    pad = s * 0.12
    b = path.boundingRect().adjusted(-pad, -pad, pad, pad)

    dpr = TEXTURE_DPR
    img = QImage(
        int(b.width() * dpr) + 2,
        int(b.height() * dpr) + 2,
        QImage.Format_ARGB32_Premultiplied,
    )
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(dpr, dpr)
    p.translate(-b.left(), -b.top())
    _render_single_wing(p, path, s, preset_name, hind)
    p.end()

    arr = _qimage_to_array(img)
    vs, us = np.nonzero(arr[:, :, 3] >= 110)
    x = ((us + 0.5) / dpr + b.left()) / s
    y = -((vs + 0.5) / dpr + b.top()) / s

    # Membrane curvature straight from the CodePen geometry.
    k = np.pi / 3.2
    z = (0.13 * np.sin(x * k) + 0.06 * np.sin(2 * y) * x / 3.2
         + (-0.055 if hind else 0.035))
    dzdx = 0.13 * k * np.cos(x * k) + 0.06 * np.sin(2 * y) / 3.2
    dzdy = 0.12 * np.cos(2 * y) * x / 3.2
    nrm = np.stack([-dzdx, -dzdy, np.ones_like(x)], axis=1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)

    spec = 0.35 if preset_name == "morpho" else 0.10
    return PointSet(
        np.stack([x, y, z], axis=1), nrm, arr[vs, us, :3], spec
    )


BODY_BGR = np.array([31, 41, 48])
LIGHT_BGR = np.array([147, 182, 201])
EYE_BGR = np.array([12, 15, 16])


def _ellipsoid(center, radii, density, colorize=None, base=BODY_BGR):
    rx, ry, rz = radii
    n_lat = max(6, int(math.pi * ry * density) + 1)
    n_lon = max(8, int((math.pi + 0.8) * max(rx, rz) * density) + 1)
    phi, lam = np.meshgrid(
        np.linspace(-math.pi / 2, math.pi / 2, n_lat),
        np.linspace(-0.4, math.pi + 0.4, n_lon),
        indexing="ij",
    )
    ux = (np.cos(phi) * np.cos(lam)).ravel()
    uy = np.sin(phi).ravel()
    uz = (np.cos(phi) * np.sin(lam)).ravel()

    pos = np.stack(
        [center[0] + ux * rx, center[1] + uy * ry, center[2] + uz * rz],
        axis=1,
    )
    nrm = np.stack([ux / rx, uy / ry, uz / rz], axis=1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)

    bgr = np.tile(base, (len(pos), 1))
    if colorize is not None:
        bgr[colorize(pos)] = LIGHT_BGR
    return PointSet(pos, nrm, bgr)


def _abdomen_bands(pos):
    bands = -0.29 - 0.1 * np.arange(7)
    d = np.abs(pos[:, 1:2] - bands[None, :]).min(axis=1)
    return d < 0.016


def _thorax_dots(pos):
    hit = np.zeros(len(pos), dtype=bool)
    for side in (-1, 1):
        for i in range(13):
            dx = pos[:, 0] - side * (0.09 + math.sin(i * 2.4) * 0.035)
            dy = pos[:, 1] - (0.35 - i * 0.032)
            hit |= (dx / 0.018) ** 2 + (dy / 0.025) ** 2 <= 1.0
    return hit & (pos[:, 2] > 0.1)


ANTENNA = np.array([
    [0.07, 0.64, 0.08],
    [0.16, 1.00, 0.12],
    [0.38, 1.35, 0.11],
    [0.44, 1.42, 0.12],
])


class ButterflyModel:

    def __init__(self, scale, preset_name):
        density = scale * SUPERSAMPLE / BODY_SPACING
        fore = _wing_points(scale, preset_name, hind=False)
        hind = _wing_points(scale, preset_name, hind=True)
        self.centroid = fore.pos.mean(axis=0)
        # Sets are splatted in order, so later parts land on top.
        self.wings = _merge([hind, fore])
        self.body = _merge([
            _ellipsoid((0, -0.57, 0.01), (0.105, 0.5, 0.115),
                       density, _abdomen_bands),
            _ellipsoid((0, 0.02, 0.04), (0.16, 0.46, 0.19),
                       density, _thorax_dots),
            _ellipsoid((0, 0.52, 0.08), (0.14, 0.16, 0.14), density),
        ] + [
            _ellipsoid((side * 0.105, 0.55, 0.16), (0.065, 0.074, 0.055),
                       density, base=EYE_BGR)
            for side in (-1, 1)
        ])


def _merge(sets):
    merged = PointSet.__new__(PointSet)
    merged.pos = np.concatenate([s.pos for s in sets])
    merged.nrm = np.concatenate([s.nrm for s in sets])
    merged.base = np.concatenate([s.base for s in sets])
    merged.spec = sets[0].spec
    return merged


# ── Edge / corner spawning ──────────────────────────────

def spawn_position(sw, sh):
    margin = 60

    if random.random() < 0.3:
        cx = random.choice([0, sw])
        cy = random.choice([0, sh])
        x = -margin if cx == 0 else sw + margin
        y = -margin if cy == 0 else sh + margin
        angle = math.atan2(sh / 2 - y, sw / 2 - x)
        angle += random.uniform(-0.6, 0.6)
        speed = random.uniform(1.0, 2.5)
        return x, y, math.cos(angle) * speed, math.sin(angle) * speed

    edge = random.randint(0, 3)
    if edge == 0:
        x, y = random.uniform(0, sw), -margin
        vx, vy = random.uniform(-1, 1), random.uniform(0.5, 2.0)
    elif edge == 1:
        x, y = random.uniform(0, sw), sh + margin
        vx, vy = random.uniform(-1, 1), random.uniform(-2.0, -0.5)
    elif edge == 2:
        x, y = -margin, random.uniform(0, sh)
        vx, vy = random.uniform(0.5, 2.0), random.uniform(-1, 1)
    else:
        x, y = sw + margin, random.uniform(0, sh)
        vx, vy = random.uniform(-2.0, -0.5), random.uniform(-1, 1)

    return x, y, vx, vy


# ── Butterfly ───────────────────────────────────────────

def _wrap_angle(a):
    return (a + math.pi) % math.tau - math.pi


class Butterfly:
    """Cruise straight -> slow down -> hover and turn -> accelerate away."""

    def __init__(self, x, y, vx, vy, sw, sh):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.sw = sw
        self.sh = sh

        self.scale = random.uniform(MIN_SCALE, MAX_SCALE)
        self.preset_name = random.choice(PRESET_NAMES)

        scale_norm = (self.scale - MIN_SCALE) / max(1, MAX_SCALE - MIN_SCALE)
        self.energy = (1.3 - scale_norm * 0.6) * random.uniform(0.85, 1.15)
        self.base_flap_speed = random.uniform(0.12, 0.22) * self.energy
        self.cruise_speed = random.uniform(*CRUISE_SPEED) * math.sqrt(self.energy)

        self.phase = random.uniform(0, math.tau)
        self.heading = math.atan2(vy, vx)
        self.target_heading = self.heading
        self.angle = math.degrees(self.heading)
        self.speed = min(math.hypot(vx, vy), self.cruise_speed)
        self.turn_rate = 0.0

        self.escape_x = self.escape_y = 0.0
        self.drift_x = self.drift_y = 0.0
        self.bob = 0.0
        self.flapping = True
        self._start_cruise()

        self.born = time.monotonic()
        self.model = ButterflyModel(self.scale, self.preset_name)
        self.wing_theta = 0.3

    def _start_cruise(self):
        self.state = "cruise"
        self.state_timer = random.randint(*CRUISE_FRAMES)
        self.glide_left = 0
        self.glide_at = (
            random.randint(40, self.state_timer - 40)
            if random.random() < 0.6 else -1
        )

    def _pick_new_heading(self):
        margin_x, margin_y = self.sw * 0.15, self.sh * 0.15
        near_edge = (
            self.x < margin_x or self.x > self.sw - margin_x
            or self.y < margin_y or self.y > self.sh - margin_y
        )
        if near_edge:
            inward = math.atan2(self.sh / 2 - self.y, self.sw / 2 - self.x)
            self.target_heading = inward + random.uniform(-0.6, 0.6)
        else:
            turn = random.uniform(*TURN_RANGE) * random.choice((-1, 1))
            self.target_heading = self.heading + turn

    def update(self, mx, my):
        self.state_timer -= 1

        # ── Behaviour state ──────────────────────────────
        if self.state == "cruise":
            target_speed = self.cruise_speed
            self.target_heading += random.gauss(0, 0.002)
            if self.glide_left > 0:
                self.glide_left -= 1
            elif self.state_timer == self.glide_at:
                self.glide_left = random.randint(20, 40)
            self.flapping = self.glide_left == 0
            if self.state_timer <= 0:
                self.state = "hover"
                self.state_timer = random.randint(*HOVER_FRAMES)
                self.glide_left = 0
                self.flapping = True
                self._pick_new_heading()
        elif self.state == "hover":
            target_speed = HOVER_SPEED
            error = _wrap_angle(self.target_heading - self.heading)
            if self.state_timer <= 0 and abs(error) < 0.05:
                self.state = "go"
        else:
            target_speed = self.cruise_speed
            if self.speed > self.cruise_speed * 0.9:
                self._start_cruise()

        # ── Speed eases in and out ───────────────────────
        ease = 0.06 if target_speed < self.speed else 0.03
        self.speed += (target_speed - self.speed) * ease

        # ── Smooth turning (only once slowed while hovering) ──
        error = _wrap_angle(self.target_heading - self.heading)
        rate = max(-MAX_TURN_RATE, min(MAX_TURN_RATE, error * 0.06))
        if self.state == "hover" and self.speed > self.cruise_speed * 0.5:
            rate = 0.0
        self.turn_rate += (rate - self.turn_rate) * 0.2
        self.heading += self.turn_rate

        # ── Wings ────────────────────────────────────────
        if self.flapping:
            flap_mult = 1.15 if self.state == "hover" else 1.0
            self.phase += self.base_flap_speed * flap_mult
            target = 0.3 + 0.85 * math.sin(self.phase)
        else:
            target = 0.22
        self.wing_theta += (target - self.wing_theta) * 0.5

        # Body rises on each downstroke; a hovering flutter bobs more.
        if self.flapping:
            amp = self.scale * (0.18 if self.state == "hover" else 0.09)
            bob_target = -amp * math.sin(self.phase)
        else:
            bob_target = 0.0
        self.bob += (bob_target - self.bob) * 0.3

        # ── Hover drift ──────────────────────────────────
        drift = 0.02 if self.state == "hover" else 0.004
        self.drift_x = self.drift_x * 0.95 + random.gauss(0, drift)
        self.drift_y = self.drift_y * 0.95 + random.gauss(0, drift)

        # ── Mouse: dart away ─────────────────────────────
        dx = self.x - mx
        dy = self.y - my
        dist = math.hypot(dx, dy)
        if 1 < dist < MOUSE_REPEL_RADIUS:
            push = (1 - dist / MOUSE_REPEL_RADIUS) * MOUSE_REPEL_STRENGTH
            self.escape_x += dx / dist * push * 0.25
            self.escape_y += dy / dist * push * 0.25
            self.target_heading = math.atan2(dy, dx)
            if self.state == "hover":
                self.state = "go"
        self.escape_x *= 0.93
        self.escape_y *= 0.93

        # ── Motion ───────────────────────────────────────
        tx = math.cos(self.heading) * self.speed
        ty = math.sin(self.heading) * self.speed
        self.vx += (tx - self.vx) * 0.15
        self.vy += (ty - self.vy) * 0.15

        self.x += self.vx + self.escape_x + self.drift_x
        self.y += self.vy + self.escape_y + self.drift_y
        if not self.flapping:
            self.y += GLIDE_SINK

        diff = (math.degrees(self.heading) - self.angle + 180) % 360 - 180
        self.angle += diff * 0.15

        # ── Screen wrap ──────────────────────────────────
        m = self.scale * 4
        if self.x < -m:
            self.x = self.sw + m
        elif self.x > self.sw + m:
            self.x = -m
        if self.y < -m:
            self.y = self.sh + m
        elif self.y > self.sh + m:
            self.y = -m


# ── 3D rendering ───────────────────────────────────────

def _rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _project(pos, m, px_per_unit):
    p = pos @ m.T.astype(np.float32)
    f = (CAMERA_DIST / (CAMERA_DIST + p[:, 2])) * px_per_unit
    return p[:, 0] * f, p[:, 1] * f


def _shade(ps, m):
    d = ps.nrm @ (m.T @ LIGHT_DIRS).astype(np.float32)
    # Double-sided material: flip normals that face away from the viewer.
    d[d[:, 4] > 0] *= -1.0
    light = HEMI_A + HEMI_B * d[:, 0]
    np.maximum(d, 0, out=d)
    light += KEY_K * d[:, 1] + FILL_K * d[:, 2]
    if ps.spec:
        h = d[:, 3] * d[:, 3]
        h *= h
        h *= h
        h *= h
        light += h * ps.spec
    light *= L_SCALE
    np.minimum(light, L_LEVELS - 1, out=light)
    idx = light.astype(np.int32)
    idx += ps.base
    return SHADE_LUT[idx]


def _fill_holes(buf):
    a = buf[:, :, 3] > 0
    hole = np.zeros_like(a)
    hole[1:-1, 1:-1] = ~a[1:-1, 1:-1] & (
        (a[1:-1, :-2] & a[1:-1, 2:]) | (a[:-2, 1:-1] & a[2:, 1:-1])
    )
    ys, xs = np.nonzero(hole)
    buf[ys, xs] = np.maximum(buf[ys, xs - 1], buf[ys - 1, xs])


def draw_butterfly(painter, b):
    age = time.monotonic() - b.born
    alpha = min(1.0, age / 1.5)
    if alpha < 0.01:
        return

    m = b.model
    ss = SUPERSAMPLE
    r = b.scale * ss
    by = b.y + b.bob

    pitch = max(-0.45, min(0.45, -b.vy * 0.12))
    if b.flapping:
        pitch += 0.12 * math.cos(b.phase)
    bank = max(-0.3, min(0.3, b.turn_rate * 3.0))

    body = (_rot_z(math.radians(b.angle + 90)) @ FLIP
            @ _rot_x(pitch) @ _rot_y(bank))

    sides = []
    for side in (-1, 1):
        w = body @ _rot_y(-side * b.wing_theta) @ np.diag([side, 1.0, 1.0])
        sides.append(((w @ m.centroid)[2], w))
    sides.sort(key=lambda t: -t[0])

    layers = [(m.wings, w) for _, w in sides] + [(m.body, body)]

    projected = [(ps, mat) + _project(ps.pos, mat, r) for ps, mat in layers]
    x0 = math.floor(min(p[2].min() for p in projected)) - 1
    y0 = math.floor(min(p[3].min() for p in projected)) - 1
    w_px = math.ceil(max(p[2].max() for p in projected)) - x0 + 2
    h_px = math.ceil(max(p[3].max() for p in projected)) - y0 + 2

    buf = np.zeros((h_px, w_px, 4), dtype=np.uint8)
    flat = buf.view(np.uint32).reshape(-1)
    for ps, mat, xs, ys in projected:
        xs -= x0
        ys -= y0
        idx = ys.astype(np.int32)
        idx *= w_px
        idx += xs.astype(np.int32)
        flat[idx] = _shade(ps, mat)
    _fill_holes(buf)

    shadow = np.zeros_like(buf)
    np.floor_divide(buf[:, :, 3], 5, out=shadow[:, :, 3])

    img = QImage(buf.data, w_px, h_px, w_px * 4, QImage.Format_ARGB32)
    shadow_img = QImage(
        shadow.data, w_px, h_px, w_px * 4, QImage.Format_ARGB32_Premultiplied
    )

    left = b.x + x0 / ss
    top = by + y0 / ss
    w_disp = w_px / ss
    h_disp = h_px / ss

    painter.setOpacity(alpha)
    off = b.scale * 1.4
    painter.drawImage(
        QRectF(left + off * 0.6 - w_disp * 0.03, top + off - h_disp * 0.03,
               w_disp * 1.06, h_disp * 1.06),
        shadow_img,
    )
    painter.drawImage(QRectF(left, top, w_disp, h_disp), img)

    # Antennae: thin tubes read better as anti-aliased strokes.
    s = b.scale
    painter.setPen(QPen(QColor(48, 41, 31), max(0.8, s * 0.04),
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    for side in (-1, 1):
        pts = ANTENNA * np.array([side, 1.0, 1.0])
        xs, ys = _project(pts.astype(np.float32), body, s)
        path = QPainterPath(QPointF(b.x + xs[0], by + ys[0]))
        path.cubicTo(
            QPointF(b.x + xs[1], by + ys[1]),
            QPointF(b.x + xs[2], by + ys[2]),
            QPointF(b.x + xs[3], by + ys[3]),
        )
        painter.drawPath(path)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(48, 41, 31))
        painter.drawEllipse(
            QPointF(b.x + xs[3], by + ys[3]), s * 0.045, s * 0.045
        )
        painter.restore()

    painter.setOpacity(1.0)


# ── Overlay window ──────────────────────────────────────

class ButterflyOverlay(QWidget):

    def __init__(self):
        super().__init__()

        screen = QApplication.primaryScreen().geometry()
        self.sw = screen.width()
        self.sh = screen.height()
        self.setGeometry(screen)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        if CLICK_THROUGH:
            self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.mouse_x = -10000
        self.mouse_y = -10000

        self.butterflies = []
        self.spawned = 0

        self.start_time = time.monotonic()
        self.physics_steps = 0

        self.spawn_timer = QTimer(self)
        self.spawn_timer.timeout.connect(self._spawn)
        self.spawn_timer.start(SPAWN_INTERVAL_MS)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick)
        self.anim_timer.start(int(1000 / FPS))

        self.showFullScreen()

        if CLICK_THROUGH:
            QTimer.singleShot(300, self._enable_click_through)

    def _spawn(self):
        if self.spawned >= BUTTERFLY_COUNT:
            self.spawn_timer.stop()
            return
        x, y, vx, vy = spawn_position(self.sw, self.sh)
        self.butterflies.append(
            Butterfly(x, y, vx, vy, self.sw, self.sh)
        )
        self.spawned += 1

    def _enable_click_through(self):
        system = platform.system()

        if system == "Windows":
            import ctypes

            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, -20)
            style |= 0x00080000 | 0x00000020 | 0x00000080
            user32.SetWindowLongW(hwnd, -20, style)

        elif system == "Linux":
            try:
                from Xlib import display, X
                from Xlib.ext import shape

                self.xdisplay = display.Display()
                window = self.xdisplay.create_resource_object(
                    "window", int(self.winId())
                )
                window.shape_rectangles(
                    shape.SO.Set,
                    shape.SK.Input,
                    X.Unsorted,
                    0,
                    0,
                    [],
                )
                self.xdisplay.sync()
            except Exception as e:
                print("X11 click-through error:", e)

    def _tick(self):
        elapsed = time.monotonic() - self.start_time
        if elapsed >= DURATION_SECONDS:
            self.anim_timer.stop()
            self.spawn_timer.stop()
            self.close()
            QApplication.quit()
            return

        # Physics is tuned per 1/60 s step; catch up when rendering is slower.
        steps = min(4, int(elapsed * FPS) - self.physics_steps)
        self.physics_steps += steps
        for _ in range(steps):
            for b in self.butterflies:
                b.update(self.mouse_x, self.mouse_y)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        for b in self.butterflies:
            draw_butterfly(painter, b)

        painter.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.anim_timer.stop()
            self.spawn_timer.stop()
            self.close()
            QApplication.quit()


# ── Entry point ─────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    overlay = ButterflyOverlay()
    sys.exit(app.exec_())
