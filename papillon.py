#!/usr/bin/env python3
"""
Papillon — Beautiful butterflies fill your Ubuntu desktop.
16 species with accurate wing shapes, patterns, and rarity tiers.
Wing geometry adapted from the Papillon CodePen by Pink Pixel (Apache-2.0).
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
    QCursor,
    QLinearGradient,
    QRadialGradient,
)
import numpy as np


# ── Configuration ───────────────────────────────────────

FPS = 60
SPAWN_INTERVAL_MS = 350
MAX_ON_SCREEN = 25
ROTATION_SPAWN_MS = 4000

CLICK_THROUGH = True
MOUSE_REPEL_RADIUS = 160
MOUSE_REPEL_STRENGTH = 2.0

CRUISE_FRAMES = (120, 180)
HOVER_FRAMES = (30, 90)
CRUISE_SPEED = (0.7, 1.2)
HOVER_SPEED = 0.12
TURN_RANGE = (0.5, 1.8)
MAX_TURN_RATE = 0.035
GLIDE_SINK = 0.12

RARITY_UNLOCK = {0: 0, 1: 30, 2: 90, 3: 180}
RARITY_WEIGHT = {0: 10, 1: 5, 2: 2, 3: 1}


# ── Wing path helper ──────────────────────────────────

def _path(s, cmds):
    path = QPainterPath()
    for c in cmds:
        t = c[0]
        p = [v * s for v in c[1:]]
        if t == 'M':
            path.moveTo(p[0], p[1])
        elif t == 'C':
            path.cubicTo(p[0], p[1], p[2], p[3], p[4], p[5])
        elif t == 'Q':
            path.quadTo(p[0], p[1], p[2], p[3])
        elif t == 'L':
            path.lineTo(p[0], p[1])
    path.closeSubpath()
    return path


# ── Wing shape templates ──────────────────────────────
# Each returns a QPainterPath. Y is negated for Qt (negative = up).

# -- Round (small butterflies: cabbage white, common blue, 88) --

def _fw_round(s):
    return _path(s, [
        ('M', 0.06, -0.15),
        ('C', 0.30, -0.85, 1.20, -1.55, 2.00, -1.65),
        ('C', 2.30, -1.68, 2.15, -0.80, 1.90, -0.35),
        ('C', 1.60, 0.10, 0.80, 0.35, 0.08, 0.18),
        ('Q', 0.03, 0.0, 0.06, -0.15),
    ])

def _hw_round(s):
    return _path(s, [
        ('M', 0.08, -0.02),
        ('C', 0.55, 0.0, 1.30, -0.04, 1.75, 0.22),
        ('C', 1.90, 0.45, 1.75, 0.85, 1.55, 1.10),
        ('C', 1.30, 1.35, 0.75, 1.40, 0.50, 1.30),
        ('C', 0.25, 1.15, 0.12, 0.75, 0.08, 0.25),
        ('L', 0.08, -0.02),
    ])

# -- Nymphalid (monarch, painted lady, fritillary, red admiral) --

def _fw_nymphalid(s):
    return _path(s, [
        ('M', 0.08, -0.26),
        ('C', 0.50, -1.15, 1.90, -2.22, 2.95, -2.32),
        ('C', 3.35, -2.36, 2.94, -1.04, 2.56, -0.44),
        ('C', 2.22, 0.13, 1.04, 0.51, 0.10, 0.22),
        ('Q', 0.04, 0.0, 0.08, -0.26),
    ])

def _hw_nymphalid(s):
    return _path(s, [
        ('M', 0.10, -0.03),
        ('C', 0.80, 0.0, 1.75, -0.06, 2.37, 0.32),
        ('C', 2.55, 0.65, 2.16, 1.06, 2.13, 1.18),
        ('C', 2.05, 1.48, 1.79, 1.43, 1.69, 1.65),
        ('C', 1.54, 1.88, 1.34, 1.72, 1.20, 1.88),
        ('C', 0.66, 2.04, 0.23, 1.17, 0.10, 0.32),
        ('L', 0.10, -0.03),
    ])

# -- Angular (peacock, malachite, clipper) --

def _fw_angular(s):
    return _path(s, [
        ('M', 0.08, -0.28),
        ('C', 0.45, -1.20, 1.85, -2.40, 3.10, -2.50),
        ('C', 3.50, -2.48, 3.10, -1.10, 2.70, -0.50),
        ('C', 2.30, 0.08, 1.10, 0.48, 0.10, 0.20),
        ('Q', 0.04, 0.0, 0.08, -0.28),
    ])

def _hw_angular(s):
    return _path(s, [
        ('M', 0.10, -0.03),
        ('C', 0.75, 0.0, 1.70, -0.08, 2.30, 0.28),
        ('C', 2.50, 0.58, 2.25, 1.00, 2.10, 1.25),
        ('C', 1.95, 1.50, 1.60, 1.55, 1.40, 1.70),
        ('C', 1.10, 1.80, 0.60, 1.50, 0.35, 1.20),
        ('C', 0.18, 0.90, 0.10, 0.55, 0.10, 0.28),
        ('L', 0.10, -0.03),
    ])

# -- Broad (morpho, birdwing) --

def _fw_broad(s):
    return _path(s, [
        ('M', 0.10, -0.30),
        ('C', 0.55, -1.10, 2.10, -2.30, 3.30, -2.20),
        ('C', 3.70, -2.15, 3.30, -0.90, 2.80, -0.30),
        ('C', 2.35, 0.20, 1.15, 0.55, 0.12, 0.25),
        ('Q', 0.05, 0.0, 0.10, -0.30),
    ])

def _hw_broad(s):
    return _path(s, [
        ('M', 0.10, -0.03),
        ('C', 0.85, 0.0, 1.90, -0.05, 2.55, 0.35),
        ('C', 2.75, 0.65, 2.45, 1.15, 2.30, 1.40),
        ('C', 2.10, 1.70, 1.65, 1.80, 1.30, 1.85),
        ('C', 0.80, 1.90, 0.30, 1.30, 0.10, 0.40),
        ('L', 0.10, -0.03),
    ])

# -- Swallowtail (tiger swallowtail, sunset moth) --

def _fw_swallowtail(s):
    return _path(s, [
        ('M', 0.08, -0.30),
        ('C', 0.55, -1.25, 2.00, -2.50, 3.15, -2.65),
        ('C', 3.55, -2.60, 3.15, -1.10, 2.70, -0.45),
        ('C', 2.30, 0.10, 1.10, 0.50, 0.10, 0.22),
        ('Q', 0.04, 0.0, 0.08, -0.30),
    ])

def _hw_swallowtail(s, tail=0.4):
    return _path(s, [
        ('M', 0.10, -0.03),
        ('C', 0.80, 0.0, 1.80, -0.06, 2.40, 0.35),
        ('C', 2.58, 0.65, 2.20, 1.05, 2.15, 1.20),
        ('C', 2.08, 1.48, 1.82, 1.45, 1.72, 1.65),
        ('C', 1.65, 1.75 + tail * 0.3, 1.58, 1.85 + tail * 0.8, 1.52, 1.88 + tail),
        ('C', 1.46, 1.85 + tail * 0.8, 1.40, 1.75 + tail * 0.3, 1.22, 1.88),
        ('C', 0.68, 2.04, 0.25, 1.20, 0.10, 0.35),
        ('L', 0.10, -0.03),
    ])

# -- Moth (luna moth) --

def _fw_moth(s):
    return _path(s, [
        ('M', 0.10, -0.22),
        ('C', 0.60, -0.95, 1.70, -1.85, 2.60, -2.00),
        ('C', 3.00, -2.05, 2.80, -1.00, 2.45, -0.40),
        ('C', 2.10, 0.15, 1.10, 0.50, 0.12, 0.25),
        ('Q', 0.05, 0.0, 0.10, -0.22),
    ])

def _hw_moth(s, tail=0.6):
    return _path(s, [
        ('M', 0.10, -0.03),
        ('C', 0.75, 0.0, 1.70, -0.04, 2.35, 0.30),
        ('C', 2.55, 0.60, 2.30, 1.10, 2.15, 1.35),
        ('C', 2.00, 1.55, 1.75, 1.55, 1.65, 1.70),
        ('C', 1.58, 1.85 + tail * 0.2, 1.50, 2.00 + tail * 0.6, 1.42, 2.10 + tail),
        ('C', 1.34, 2.00 + tail * 0.6, 1.28, 1.85 + tail * 0.2, 1.15, 1.85),
        ('C', 0.60, 2.00, 0.22, 1.15, 0.10, 0.30),
        ('L', 0.10, -0.03),
    ])

# -- Narrow (glasswing) --

def _fw_narrow(s):
    return _path(s, [
        ('M', 0.06, -0.20),
        ('C', 0.35, -0.90, 1.50, -1.90, 2.50, -1.95),
        ('C', 2.80, -1.92, 2.55, -0.85, 2.20, -0.35),
        ('C', 1.85, 0.08, 0.85, 0.30, 0.08, 0.15),
        ('Q', 0.03, 0.0, 0.06, -0.20),
    ])

def _hw_narrow(s):
    return _path(s, [
        ('M', 0.08, -0.02),
        ('C', 0.50, 0.0, 1.20, -0.03, 1.65, 0.20),
        ('C', 1.80, 0.42, 1.60, 0.80, 1.40, 1.05),
        ('C', 1.15, 1.25, 0.70, 1.20, 0.45, 1.05),
        ('C', 0.22, 0.85, 0.10, 0.50, 0.08, 0.22),
        ('L', 0.08, -0.02),
    ])


def sample_outline(path, n=160):
    return [path.pointAtPercent(i / n) for i in range(n)]


# ── Paint primitives ──────────────────────────────────

def _fill_wing(painter, path, color):
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    painter.drawPath(path)


def _draw_border(painter, path, s, color, width=1.0):
    painter.setPen(QPen(color, max(0.8, s * 0.06 * width),
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


def _draw_veins(painter, path, s, color, width=1.0, count=11):
    outline = sample_outline(path, 160)
    bounds = path.boundingRect()
    root = QPointF(bounds.left() + bounds.width() * 0.04,
                   bounds.top() + bounds.height() * 0.45)
    vw = max(0.4, s * 0.028 * width)
    painter.setPen(QPen(color, vw, Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    step = max(1, 140 // count)
    for i in range(5, 150, step):
        end = outline[min(i, 159)]
        vein = QPainterPath()
        vein.moveTo(root)
        mid = QPointF(root.x() + (end.x() - root.x()) * 0.55,
                      root.y() + (end.y() - root.y()) * 0.55)
        vein.quadTo(QPointF(mid.x(), mid.y() - s * 0.06), end)
        painter.drawPath(vein)


def _draw_border_dots(painter, path, s, color, count=26):
    outline = sample_outline(path, 160)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    step = max(1, 140 // count)
    for i in range(5, 150, step):
        pt = outline[min(i, 159)]
        painter.drawEllipse(pt, s * 0.025, s * 0.025)


def _draw_eyespot(painter, cx, cy, s, rings):
    for radius_frac, color in rings:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        r = s * radius_frac
        painter.drawEllipse(QPointF(cx, cy), r, r * 0.85)


def _draw_spots(painter, path, s, color, positions, radius=0.06):
    bounds = path.boundingRect()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    for fx, fy in positions:
        x = bounds.left() + bounds.width() * fx
        y = bounds.top() + bounds.height() * fy
        painter.drawEllipse(QPointF(x, y), s * radius, s * radius)


def _draw_band(painter, path, s, color, start_frac, end_frac, width):
    outline = sample_outline(path, 160)
    si = int(start_frac * 159)
    ei = int(end_frac * 159)
    painter.setPen(QPen(color, max(1.0, s * width), Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    band = QPainterPath()
    band.moveTo(outline[si])
    for i in range(si + 1, ei + 1):
        band.lineTo(outline[min(i, 159)])
    painter.drawPath(band)


def _draw_stripes(painter, path, s, color, width, count):
    bounds = path.boundingRect()
    painter.save()
    painter.setClipPath(path)
    sw = max(0.8, s * width)
    painter.setPen(QPen(color, sw, Qt.SolidLine))
    painter.setBrush(Qt.NoBrush)
    for i in range(count):
        frac = (i + 0.5) / count
        x = bounds.left() + bounds.width() * frac
        painter.drawLine(QPointF(x, bounds.top() - 2),
                         QPointF(x, bounds.bottom() + 2))
    painter.restore()


def _flecks(painter, path, s, colors, count=400, seed_extra=0):
    bounds = path.boundingRect()
    rng = random.Random(hash(('flecks', seed_extra, int(s * 100))))
    painter.save()
    painter.setClipPath(path)
    for _ in range(count):
        x = bounds.x() + rng.random() * bounds.width()
        y = bounds.y() + rng.random() * bounds.height()
        c = QColor(rng.choice(colors))
        c.setAlpha(int(15 + rng.random() * 40))
        painter.fillRect(QRectF(x, y, 0.8 + rng.random(), 1.2 + rng.random() * 1.5), c)
    painter.restore()


# ── Species paint functions ───────────────────────────
# Each: (painter, wing_path, s, is_hind) → draws the full wing texture.

def _paint_cabbage_white(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#f5f2e0"))
    _flecks(painter, path, s, ["#e8e4cc", "#d8d4b8"], 200, 1)
    _draw_veins(painter, path, s, QColor("#b0ab90"), 0.4, 8)
    if not is_hind:
        _draw_spots(painter, path, s, QColor("#3a3830"),
                    [(0.55, 0.35), (0.50, 0.55)], 0.055)
    _draw_border(painter, path, s, QColor("#8a8570"), 0.6)


def _paint_painted_lady(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#d4793c"))
    _flecks(painter, path, s, ["#e8a060", "#c06828"], 350, 2)
    if not is_hind:
        # Black forewing tip
        painter.save()
        painter.setClipPath(path)
        bounds = path.boundingRect()
        tip_x = bounds.right() - bounds.width() * 0.35
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#1e1610")))
        tip = QPainterPath()
        tip.addEllipse(QPointF(tip_x, bounds.top() + bounds.height() * 0.2),
                       bounds.width() * 0.35, bounds.height() * 0.45)
        painter.drawPath(tip)
        # White spots in black area
        _draw_spots(painter, path, s, QColor("#f0ebe0"),
                    [(0.78, 0.18), (0.85, 0.28), (0.72, 0.30)], 0.035)
        painter.restore()
    else:
        _draw_spots(painter, path, s, QColor("#2a1e12"),
                    [(0.40, 0.25), (0.55, 0.45), (0.35, 0.55), (0.50, 0.70)], 0.04)
    _draw_veins(painter, path, s, QColor("#2e1f14"), 0.7, 9)
    _draw_border(painter, path, s, QColor("#2e1f14"), 1.0)


def _paint_monarch(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#e18a32"))
    _flecks(painter, path, s, ["#f5c66b", "#cc7020"], 400, 3)
    # Thick black vein grid — the monarch's signature
    _draw_veins(painter, path, s, QColor("#1a1610"), 2.8, 12)
    # Heavy black border
    _draw_band(painter, path, s, QColor("#1a1610"), 0.0, 1.0, 0.12)
    _draw_border(painter, path, s, QColor("#1a1610"), 1.8)
    # White dots along the dark border
    _draw_border_dots(painter, path, s, QColor("#f0ece0"), 30)


def _paint_common_blue(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#5b8ec9"))
    _flecks(painter, path, s, ["#8ab8e8", "#4070a0"], 300, 4)
    _draw_veins(painter, path, s, QColor("#2a3850"), 0.5, 8)
    _draw_border(painter, path, s, QColor("#1a2433"), 0.9)
    if is_hind:
        # Orange crescents near hindwing border
        outline = sample_outline(path, 160)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#e08030")))
        for i in range(30, 130, 15):
            pt = outline[min(i, 159)]
            painter.drawEllipse(pt, s * 0.03, s * 0.02)
    _draw_border_dots(painter, path, s, QColor("#1a2433"), 20)


def _paint_red_admiral(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#1a1410"))
    _flecks(painter, path, s, ["#2a2018", "#0e0a08"], 250, 5)
    if not is_hind:
        # Red diagonal band across forewing
        painter.save()
        painter.setClipPath(path)
        bounds = path.boundingRect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#d83018")))
        band = QPainterPath()
        bw = bounds.width() * 0.18
        band.moveTo(bounds.left() + bounds.width() * 0.15, bounds.bottom())
        band.lineTo(bounds.left() + bounds.width() * 0.15 + bw, bounds.bottom())
        band.lineTo(bounds.right() - bounds.width() * 0.10, bounds.top() + bounds.height() * 0.25)
        band.lineTo(bounds.right() - bounds.width() * 0.10 - bw, bounds.top() + bounds.height() * 0.25)
        band.closeSubpath()
        painter.drawPath(band)
        # White spots near forewing tip
        _draw_spots(painter, path, s, QColor("#f0ece0"),
                    [(0.80, 0.12), (0.88, 0.20), (0.78, 0.25)], 0.03)
        painter.restore()
    else:
        # Red border band on hindwing
        _draw_band(painter, path, s, QColor("#d83018"), 0.25, 0.85, 0.10)
    _draw_border(painter, path, s, QColor("#0e0a08"), 1.2)


def _paint_tiger_swallowtail(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#f0d44c"))
    _flecks(painter, path, s, ["#fae88e", "#d8b830"], 350, 6)
    # Black tiger stripes
    _draw_stripes(painter, path, s, QColor("#1a1a0e"), 0.10, 5)
    _draw_veins(painter, path, s, QColor("#1a1a0e"), 1.2, 9)
    _draw_border(painter, path, s, QColor("#1a1a0e"), 1.5)
    if is_hind:
        # Blue and orange spots near the tail
        bounds = path.boundingRect()
        painter.save()
        painter.setClipPath(path)
        for i, fx in enumerate([0.45, 0.55, 0.65]):
            _draw_eyespot(painter,
                          bounds.left() + bounds.width() * fx,
                          bounds.top() + bounds.height() * 0.80,
                          s, [(0.05, QColor("#3050a0")),
                              (0.025, QColor("#1a1a0e"))])
        _draw_spots(painter, path, s, QColor("#e08020"),
                    [(0.42, 0.85), (0.58, 0.88)], 0.035)
        painter.restore()


def _paint_fritillary(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#d4853a"))
    _flecks(painter, path, s, ["#e8a860", "#c07028"], 300, 7)
    # Checkered black spots — grid pattern
    painter.save()
    painter.setClipPath(path)
    bounds = path.boundingRect()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("#2a1c10")))
    cols = 7
    rows = 5
    for r in range(rows):
        for c in range(cols):
            fx = (c + 0.5) / cols
            fy = (r + 0.5) / rows
            x = bounds.left() + bounds.width() * fx
            y = bounds.top() + bounds.height() * fy
            if (r + c) % 2 == 0:
                painter.drawEllipse(QPointF(x, y), s * 0.05, s * 0.04)
    painter.restore()
    _draw_veins(painter, path, s, QColor("#2a1c10"), 0.6, 9)
    _draw_border(painter, path, s, QColor("#2a1c10"), 1.0)


def _paint_peacock(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#a83020"))
    _flecks(painter, path, s, ["#c84030", "#802018"], 300, 8)
    bounds = path.boundingRect()
    # Large eyespot — the peacock's signature
    cx = bounds.left() + bounds.width() * (0.50 if is_hind else 0.58)
    cy = bounds.top() + bounds.height() * (0.45 if is_hind else 0.40)
    _draw_eyespot(painter, cx, cy, s, [
        (0.14, QColor("#1a1210")),
        (0.11, QColor("#3050b0")),
        (0.08, QColor("#6080d0")),
        (0.05, QColor("#e8d830")),
        (0.025, QColor("#1a1210")),
    ])
    _draw_veins(painter, path, s, QColor("#1a1210"), 0.5, 8)
    _draw_border(painter, path, s, QColor("#1a1210"), 1.2)


def _paint_morpho(painter, path, s, is_hind):
    # Brilliant iridescent blue
    _fill_wing(painter, path, QColor("#1890d0"))
    _flecks(painter, path, s, ["#30b8f0", "#0868a0", "#20a0e0"], 500, 9)
    # Shimmer effect — lighter streaks
    painter.save()
    painter.setClipPath(path)
    bounds = path.boundingRect()
    shimmer = QColor("#60d0ff")
    shimmer.setAlpha(50)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(shimmer))
    rng = random.Random(hash(('morpho_shimmer', int(s * 100))))
    for _ in range(15):
        x = bounds.x() + rng.random() * bounds.width()
        y = bounds.y() + rng.random() * bounds.height()
        painter.drawEllipse(QPointF(x, y), s * 0.15, s * 0.04)
    painter.restore()
    # Dark edges
    _draw_border(painter, path, s, QColor("#0a1820"), 2.0)
    _draw_border_dots(painter, path, s, QColor("#f0f0f0"), 15)


def _paint_malachite(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#1a3020"))
    _flecks(painter, path, s, ["#2a4830", "#0e2018"], 250, 10)
    # Pale green translucent patches
    painter.save()
    painter.setClipPath(path)
    bounds = path.boundingRect()
    painter.setPen(Qt.NoPen)
    patches = [(0.35, 0.30, 0.22, 0.18),
               (0.55, 0.50, 0.20, 0.16),
               (0.40, 0.65, 0.18, 0.14),
               (0.60, 0.25, 0.16, 0.14)]
    for fx, fy, rw, rh in patches:
        c = QColor("#90d8a0")
        c.setAlpha(160)
        painter.setBrush(QBrush(c))
        x = bounds.left() + bounds.width() * fx
        y = bounds.top() + bounds.height() * fy
        painter.drawEllipse(QPointF(x, y), bounds.width() * rw, bounds.height() * rh)
    painter.restore()
    _draw_veins(painter, path, s, QColor("#0e2018"), 0.6, 8)
    _draw_border(painter, path, s, QColor("#0e2018"), 1.0)


def _paint_glasswing(painter, path, s, is_hind):
    # Transparent wings with dark borders — unique look
    # Fill with very faint color (the wing_alpha handles transparency)
    painter.save()
    painter.setClipPath(path)
    bounds = path.boundingRect()
    # Mostly transparent center
    center_c = QColor("#e8eef0")
    center_c.setAlpha(40)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(center_c))
    painter.drawPath(path)
    # Dark opaque borders
    border_c = QColor("#3a3020")
    painter.setBrush(QBrush(border_c))
    outline = sample_outline(path, 160)
    for i in range(160):
        pt = outline[i]
        painter.drawEllipse(pt, s * 0.04, s * 0.04)
    # White band
    if not is_hind:
        white_band = QColor("#f8f4f0")
        white_band.setAlpha(80)
        painter.setBrush(QBrush(white_band))
        for i in range(40, 90):
            pt = outline[min(i, 159)]
            painter.drawEllipse(pt, s * 0.06, s * 0.06)
    painter.restore()
    _draw_veins(painter, path, s, QColor("#3a3020"), 0.5, 6)
    _draw_border(painter, path, s, QColor("#3a3020"), 1.5)


def _paint_clipper(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#2a2420"))
    _flecks(painter, path, s, ["#3a3028", "#1a1810"], 250, 11)
    # Blue-white streaky band
    painter.save()
    painter.setClipPath(path)
    bounds = path.boundingRect()
    painter.setPen(Qt.NoPen)
    band_y = bounds.top() + bounds.height() * 0.35
    band_h = bounds.height() * 0.30
    grad = QLinearGradient(bounds.left(), band_y, bounds.left(), band_y + band_h)
    grad.setColorAt(0.0, QColor(60, 120, 180, 0))
    grad.setColorAt(0.3, QColor(140, 190, 220, 180))
    grad.setColorAt(0.5, QColor(220, 235, 245, 200))
    grad.setColorAt(0.7, QColor(140, 190, 220, 180))
    grad.setColorAt(1.0, QColor(60, 120, 180, 0))
    painter.setBrush(QBrush(grad))
    painter.drawRect(QRectF(bounds.left(), band_y, bounds.width(), band_h))
    painter.restore()
    _draw_veins(painter, path, s, QColor("#1a1810"), 0.5, 8)
    _draw_border(painter, path, s, QColor("#1a1810"), 1.0)


def _paint_birdwing(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#0e1a10"))
    _flecks(painter, path, s, ["#1a2a18", "#0a100a"], 200, 12)
    # Bright green/teal patches on black
    painter.save()
    painter.setClipPath(path)
    bounds = path.boundingRect()
    painter.setPen(Qt.NoPen)
    if is_hind:
        patches = [(0.35, 0.30, 0.25, 0.22),
                   (0.55, 0.50, 0.22, 0.20),
                   (0.40, 0.70, 0.20, 0.18)]
    else:
        patches = [(0.40, 0.30, 0.18, 0.20),
                   (0.55, 0.50, 0.16, 0.18),
                   (0.65, 0.35, 0.14, 0.16)]
    for fx, fy, rw, rh in patches:
        painter.setBrush(QBrush(QColor("#28b848")))
        x = bounds.left() + bounds.width() * fx
        y = bounds.top() + bounds.height() * fy
        painter.drawEllipse(QPointF(x, y), bounds.width() * rw, bounds.height() * rh)
    # Yellow accents
    if is_hind:
        painter.setBrush(QBrush(QColor("#e8d430")))
        painter.drawEllipse(
            QPointF(bounds.left() + bounds.width() * 0.25,
                    bounds.top() + bounds.height() * 0.50),
            s * 0.08, s * 0.06)
    painter.restore()
    _draw_border(painter, path, s, QColor("#0e1a10"), 1.5)


def _paint_sunset_moth(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#0e0a08"))
    # Rainbow bands — the sunset moth's signature
    painter.save()
    painter.setClipPath(path)
    bounds = path.boundingRect()
    rainbow = [
        (0.15, "#d04830"),
        (0.30, "#e08830"),
        (0.45, "#e8c830"),
        (0.60, "#40b050"),
        (0.75, "#3068c0"),
        (0.90, "#6838a0"),
    ]
    painter.setPen(Qt.NoPen)
    bw = bounds.height() / len(rainbow)
    for i, (frac, col) in enumerate(rainbow):
        c = QColor(col)
        c.setAlpha(180)
        painter.setBrush(QBrush(c))
        y = bounds.top() + bounds.height() * (frac - 0.07)
        painter.drawRect(QRectF(bounds.left(), y, bounds.width(), bw * 1.1))
    painter.restore()
    _draw_veins(painter, path, s, QColor("#0e0a08"), 0.8, 8)
    _draw_border(painter, path, s, QColor("#0e0a08"), 1.5)


def _paint_eighty_eight(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#1a1a1e"))
    _flecks(painter, path, s, ["#2a2a30", "#0e0e12"], 200, 14)
    bounds = path.boundingRect()
    if not is_hind:
        # Red band on forewing
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#d82020")))
        band = QPainterPath()
        bx = bounds.left() + bounds.width() * 0.20
        by = bounds.top() + bounds.height() * 0.25
        band.addEllipse(QPointF(bx + bounds.width() * 0.20, by + bounds.height() * 0.25),
                        bounds.width() * 0.22, bounds.height() * 0.18)
        painter.drawPath(band)
        painter.restore()
    else:
        # "88" pattern on hindwing — white background with dark "8" shapes
        painter.save()
        painter.setClipPath(path)
        cx = bounds.left() + bounds.width() * 0.48
        cy = bounds.top() + bounds.height() * 0.45
        # White disc
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#e8e4e0")))
        painter.drawEllipse(QPointF(cx, cy), s * 0.12, s * 0.14)
        # Two dark circles forming "8"
        painter.setBrush(QBrush(QColor("#1a1a1e")))
        painter.drawEllipse(QPointF(cx, cy - s * 0.045), s * 0.045, s * 0.04)
        painter.drawEllipse(QPointF(cx, cy + s * 0.045), s * 0.045, s * 0.04)
        # Second "8" next to it
        cx2 = cx + s * 0.06
        painter.setBrush(QBrush(QColor("#e8e4e0")))
        painter.drawEllipse(QPointF(cx2, cy), s * 0.10, s * 0.12)
        painter.setBrush(QBrush(QColor("#1a1a1e")))
        painter.drawEllipse(QPointF(cx2, cy - s * 0.035), s * 0.035, s * 0.03)
        painter.drawEllipse(QPointF(cx2, cy + s * 0.035), s * 0.035, s * 0.03)
        painter.restore()
    _draw_border(painter, path, s, QColor("#0a0a0c"), 1.0)


def _paint_luna(painter, path, s, is_hind):
    _fill_wing(painter, path, QColor("#b9cd8b"))
    _flecks(painter, path, s, ["#d0e0a0", "#a0b878"], 350, 15)
    _draw_veins(painter, path, s, QColor("#8a9868"), 0.4, 8)
    # Eyespot on each wing
    bounds = path.boundingRect()
    cx = bounds.left() + bounds.width() * (0.45 if is_hind else 0.55)
    cy = bounds.top() + bounds.height() * (0.40 if is_hind else 0.38)
    _draw_eyespot(painter, cx, cy, s, [
        (0.09, QColor("#535640")),
        (0.07, QColor("#e9e5b0")),
        (0.04, QColor("#655f40")),
        (0.018, QColor("#d8dcbd")),
    ])
    # Fine trailing edge line
    _draw_border(painter, path, s, QColor("#8a9860"), 0.7)
    painter.setPen(QPen(QColor("#e9e5b0"), max(0.3, s * 0.015), Qt.SolidLine))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


# ── Antenna data per type ─────────────────────────────

ANTENNA_CLUB = np.array([
    [0.07, 0.64, 0.08],
    [0.16, 1.00, 0.12],
    [0.38, 1.35, 0.11],
    [0.44, 1.42, 0.12],
])

ANTENNA_FEATHER = np.array([
    [0.08, 0.60, 0.08],
    [0.18, 0.82, 0.12],
    [0.30, 0.95, 0.11],
    [0.34, 1.00, 0.12],
])


# ── Species catalog ────────────────────────────────────

SPECIES = [
    # Common (rarity 0)
    {"name": "cabbage_white", "rarity": 0, "size": (14, 20),
     "fw": _fw_round, "hw": _hw_round,
     "paint": _paint_cabbage_white, "antenna": ANTENNA_CLUB,
     "spec": 0.08, "wing_alpha": 1.0, "body_scale": 0.85},

    {"name": "painted_lady", "rarity": 0, "size": (15, 21),
     "fw": _fw_nymphalid, "hw": _hw_nymphalid,
     "paint": _paint_painted_lady, "antenna": ANTENNA_CLUB,
     "spec": 0.10, "wing_alpha": 1.0, "body_scale": 1.0},

    {"name": "monarch", "rarity": 0, "size": (18, 25),
     "fw": _fw_nymphalid, "hw": _hw_nymphalid,
     "paint": _paint_monarch, "antenna": ANTENNA_CLUB,
     "spec": 0.10, "wing_alpha": 1.0, "body_scale": 1.0},

    {"name": "common_blue", "rarity": 0, "size": (12, 17),
     "fw": _fw_round, "hw": _hw_round,
     "paint": _paint_common_blue, "antenna": ANTENNA_CLUB,
     "spec": 0.12, "wing_alpha": 1.0, "body_scale": 0.75},

    # Uncommon (rarity 1)
    {"name": "red_admiral", "rarity": 1, "size": (16, 22),
     "fw": _fw_nymphalid, "hw": _hw_nymphalid,
     "paint": _paint_red_admiral, "antenna": ANTENNA_CLUB,
     "spec": 0.10, "wing_alpha": 1.0, "body_scale": 1.0},

    {"name": "tiger_swallowtail", "rarity": 1, "size": (20, 27),
     "fw": _fw_swallowtail, "hw": lambda s: _hw_swallowtail(s, tail=0.5),
     "paint": _paint_tiger_swallowtail, "antenna": ANTENNA_CLUB,
     "spec": 0.10, "wing_alpha": 1.0, "body_scale": 1.1},

    {"name": "fritillary", "rarity": 1, "size": (15, 21),
     "fw": _fw_nymphalid, "hw": _hw_nymphalid,
     "paint": _paint_fritillary, "antenna": ANTENNA_CLUB,
     "spec": 0.10, "wing_alpha": 1.0, "body_scale": 0.95},

    {"name": "peacock", "rarity": 1, "size": (17, 23),
     "fw": _fw_angular, "hw": _hw_angular,
     "paint": _paint_peacock, "antenna": ANTENNA_CLUB,
     "spec": 0.12, "wing_alpha": 1.0, "body_scale": 1.0},

    # Rare (rarity 2)
    {"name": "morpho", "rarity": 2, "size": (21, 27),
     "fw": _fw_broad, "hw": _hw_broad,
     "paint": _paint_morpho, "antenna": ANTENNA_CLUB,
     "spec": 0.40, "wing_alpha": 1.0, "body_scale": 0.9},

    {"name": "malachite", "rarity": 2, "size": (18, 24),
     "fw": _fw_angular, "hw": _hw_angular,
     "paint": _paint_malachite, "antenna": ANTENNA_CLUB,
     "spec": 0.12, "wing_alpha": 1.0, "body_scale": 1.0},

    {"name": "glasswing", "rarity": 2, "size": (13, 18),
     "fw": _fw_narrow, "hw": _hw_narrow,
     "paint": _paint_glasswing, "antenna": ANTENNA_CLUB,
     "spec": 0.05, "wing_alpha": 0.50, "body_scale": 0.7},

    {"name": "clipper", "rarity": 2, "size": (18, 25),
     "fw": _fw_angular, "hw": _hw_angular,
     "paint": _paint_clipper, "antenna": ANTENNA_CLUB,
     "spec": 0.10, "wing_alpha": 1.0, "body_scale": 1.0},

    # Ultra-rare (rarity 3)
    {"name": "birdwing", "rarity": 3, "size": (24, 30),
     "fw": _fw_broad, "hw": _hw_broad,
     "paint": _paint_birdwing, "antenna": ANTENNA_CLUB,
     "spec": 0.12, "wing_alpha": 1.0, "body_scale": 1.2},

    {"name": "sunset_moth", "rarity": 3, "size": (18, 24),
     "fw": _fw_swallowtail, "hw": lambda s: _hw_swallowtail(s, tail=0.6),
     "paint": _paint_sunset_moth, "antenna": ANTENNA_FEATHER,
     "spec": 0.20, "wing_alpha": 1.0, "body_scale": 1.15},

    {"name": "eighty_eight", "rarity": 3, "size": (13, 18),
     "fw": _fw_round, "hw": _hw_round,
     "paint": _paint_eighty_eight, "antenna": ANTENNA_CLUB,
     "spec": 0.08, "wing_alpha": 1.0, "body_scale": 0.8},

    {"name": "luna", "rarity": 3, "size": (22, 28),
     "fw": _fw_moth, "hw": lambda s: _hw_moth(s, tail=0.8),
     "paint": _paint_luna, "antenna": ANTENNA_FEATHER,
     "spec": 0.08, "wing_alpha": 1.0, "body_scale": 1.2},
]


def pick_species(elapsed):
    available = [sp for sp in SPECIES if elapsed >= RARITY_UNLOCK[sp["rarity"]]]
    weights = [RARITY_WEIGHT[sp["rarity"]] for sp in available]
    return random.choices(available, weights=weights, k=1)[0]


# ── 3D model (port of the Three.js scene) ──────────────

SUPERSAMPLE = 1.15
TEXTURE_DPR = 1.45
BODY_SPACING = 0.9
CAMERA_DIST = 14.0
L_LEVELS = 64
L_SCALE = 20.0


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


_KEY = _unit([-3, -5, -7])
_FILL = _unit([4, 1, 5])
_HALF = _unit(_KEY + np.array([0.0, 0.0, -1.0]))
LIGHT_DIRS = np.stack(
    [[0.0, -1.0, 0.0], _KEY, _FILL, _HALF, [0.0, 0.0, 1.0]], axis=1
)

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
    levels = np.arange(32, dtype=np.uint32)
    byte = ((levels << 3) | (levels >> 2)).astype(np.float32)
    lin = _srgb_to_lin(byte).astype(np.float32)
    light = (np.arange(L_LEVELS, dtype=np.float32) / L_SCALE) * 0.72
    x = lin[:, None] * light[None, :]
    toned = x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14)
    ch = np.round(_lin_to_srgb(toned)).astype(np.uint32)
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


def _wing_points(scale, species, hind):
    s = scale
    path_fn = species["hw"] if hind else species["fw"]
    path = path_fn(s)
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
    species["paint"](p, path, s, hind)
    p.end()

    arr = _qimage_to_array(img)
    vs, us = np.nonzero(arr[:, :, 3] >= 110)
    if len(vs) == 0:
        vs, us = np.nonzero(arr[:, :, 3] >= 20)
    if len(vs) == 0:
        return PointSet(np.zeros((1, 3)), np.array([[0, 0, 1.0]]),
                        np.array([[128, 128, 128]]), 0.0)
    x = ((us + 0.5) / dpr + b.left()) / s
    y = -((vs + 0.5) / dpr + b.top()) / s

    k = np.pi / 3.2
    z = (0.13 * np.sin(x * k) + 0.06 * np.sin(2 * y) * x / 3.2
         + (-0.055 if hind else 0.035))
    dzdx = 0.13 * k * np.cos(x * k) + 0.06 * np.sin(2 * y) / 3.2
    dzdy = 0.12 * np.cos(2 * y) * x / 3.2
    nrm = np.stack([-dzdx, -dzdy, np.ones_like(x)], axis=1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)

    sp = species.get("spec", 0.10)
    return PointSet(np.stack([x, y, z], axis=1), nrm, arr[vs, us, :3], sp)


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


class ButterflyModel:

    def __init__(self, scale, species):
        density = scale * SUPERSAMPLE / BODY_SPACING
        fore = _wing_points(scale, species, hind=False)
        hind = _wing_points(scale, species, hind=True)
        self.centroid = fore.pos.mean(axis=0)
        self.wings = _merge([hind, fore])
        bs = species.get("body_scale", 1.0)
        self.body = _merge([
            _ellipsoid((0, -0.57, 0.01),
                       (0.105 * bs, 0.5 * bs, 0.115 * bs),
                       density, _abdomen_bands),
            _ellipsoid((0, 0.02, 0.04),
                       (0.16 * bs, 0.46 * bs, 0.19 * bs),
                       density, _thorax_dots),
            _ellipsoid((0, 0.52 * bs, 0.08),
                       (0.14 * bs, 0.16 * bs, 0.14 * bs), density),
        ] + [
            _ellipsoid((side * 0.105 * bs, 0.55 * bs, 0.16),
                       (0.065 * bs, 0.074 * bs, 0.055 * bs),
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

    def __init__(self, x, y, vx, vy, sw, sh, species):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.sw = sw
        self.sh = sh
        self.species = species

        min_sz, max_sz = species["size"]
        self.scale = random.uniform(min_sz, max_sz)

        scale_norm = (self.scale - min_sz) / max(1, max_sz - min_sz)
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
        self.model = ButterflyModel(self.scale, species)
        self.wing_theta = 0.3

        self.bbox = (0, 0, 0, 0)
        self.interaction = None
        self.interact_timer = 0
        self.nervous = 0.0
        self.held_offset_x = 0.0
        self.held_offset_y = 0.0

        self.retiring = False
        self.retire_alpha = 1.0

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

    def start_retire(self):
        if self.interaction == "held":
            return
        self.retiring = True
        self.interaction = None
        ex = 0 if self.x < self.sw / 2 else self.sw
        ey = 0 if self.y < self.sh / 2 else self.sh
        self.heading = math.atan2(ey - self.y, ex - self.x)
        self.target_heading = self.heading
        self.speed = self.cruise_speed * 1.5
        self.state = "go"

    def startle(self, from_x, from_y):
        self.interaction = "startled"
        self.interact_timer = 90
        dx, dy = self.x - from_x, self.y - from_y
        dist = math.hypot(dx, dy)
        if dist > 1:
            self.heading = math.atan2(dy, dx)
        else:
            self.heading += math.pi
        self.target_heading = self.heading
        self.speed = self.cruise_speed * 2.8
        self.state = "go"
        self.flapping = True

    def hold(self, grab_x, grab_y):
        self.interaction = "held"
        self.held_offset_x = self.x - grab_x
        self.held_offset_y = self.y - grab_y
        self.speed = 0.0
        self.vx = self.vy = 0.0
        self.escape_x = self.escape_y = 0.0

    def release(self, throw_vx, throw_vy):
        self.interaction = "tumble"
        self.interact_timer = 30
        speed = math.hypot(throw_vx, throw_vy)
        if speed > 0.5:
            self.heading = math.atan2(throw_vy, throw_vx)
            self.speed = min(speed * 0.3, self.cruise_speed * 2.0)
        else:
            self.heading += random.uniform(-1.0, 1.0)
            self.speed = self.cruise_speed * 0.5
        self.target_heading = self.heading
        self.vx = math.cos(self.heading) * self.speed
        self.vy = math.sin(self.heading) * self.speed

    def update(self, mx, my):
        if self.retiring:
            self.phase += self.base_flap_speed
            self.wing_theta += (0.3 + 0.85 * math.sin(self.phase) - self.wing_theta) * 0.5
            tx = math.cos(self.heading) * self.speed
            ty = math.sin(self.heading) * self.speed
            self.vx += (tx - self.vx) * 0.15
            self.vy += (ty - self.vy) * 0.15
            self.x += self.vx
            self.y += self.vy
            amp = self.scale * 0.09
            self.bob += (-amp * math.sin(self.phase) - self.bob) * 0.3
            diff = (math.degrees(self.heading) - self.angle + 180) % 360 - 180
            self.angle += diff * 0.15
            return

        if self.interaction == "held":
            self.wing_theta += (0.10 - self.wing_theta) * 0.12
            self.phase += self.base_flap_speed * 0.25
            self.bob *= 0.9
            return

        if self.interaction == "tumble":
            self.interact_timer -= 1
            self.phase += self.base_flap_speed * 2.8
            self.wing_theta = 0.3 + 0.55 * math.sin(self.phase * 2.7)
            self.x += self.vx
            self.y += self.vy + 0.4
            self.angle += random.uniform(-8, 8)
            self.bob = self.scale * 0.1 * math.sin(self.phase)
            if self.interact_timer <= 0:
                self.interaction = None
                self._pick_new_heading()
                self.state = "go"
            return

        if self.interaction == "startled":
            self.interact_timer -= 1
            if self.interact_timer <= 0:
                self.interaction = None
                self._start_cruise()

        self.state_timer -= 1

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

        if self.interaction == "startled":
            target_speed = self.cruise_speed * 2.8

        ease = 0.06 if target_speed < self.speed else 0.03
        self.speed += (target_speed - self.speed) * ease

        error = _wrap_angle(self.target_heading - self.heading)
        rate = max(-MAX_TURN_RATE, min(MAX_TURN_RATE, error * 0.06))
        if self.state == "hover" and self.speed > self.cruise_speed * 0.5:
            rate = 0.0
        self.turn_rate += (rate - self.turn_rate) * 0.2
        self.heading += self.turn_rate

        if self.flapping:
            flap_mult = 1.15 if self.state == "hover" else 1.0
            flap_mult += self.nervous * 0.5
            self.phase += self.base_flap_speed * flap_mult
            target = 0.3 + 0.85 * math.sin(self.phase)
        else:
            target = 0.22
        self.wing_theta += (target - self.wing_theta) * 0.5

        if self.flapping:
            amp = self.scale * (0.18 if self.state == "hover" else 0.09)
            bob_target = -amp * math.sin(self.phase)
        else:
            bob_target = 0.0
        self.bob += (bob_target - self.bob) * 0.3

        drift = 0.02 if self.state == "hover" else 0.004
        self.drift_x = self.drift_x * 0.95 + random.gauss(0, drift)
        self.drift_y = self.drift_y * 0.95 + random.gauss(0, drift)

        dx = self.x - mx
        dy = self.y - my
        dist = math.hypot(dx, dy)
        if self.interaction != "startled":
            if 1 < dist < MOUSE_REPEL_RADIUS:
                push = (1 - dist / MOUSE_REPEL_RADIUS) * MOUSE_REPEL_STRENGTH
                self.escape_x += dx / dist * push * 0.25
                self.escape_y += dy / dist * push * 0.25
                self.target_heading = math.atan2(dy, dx)
                if self.state == "hover":
                    self.state = "go"
        if dist < MOUSE_REPEL_RADIUS * 1.5:
            self.nervous = min(1.0, self.nervous + 0.06)
        else:
            self.nervous = max(0.0, self.nervous - 0.02)
        self.escape_x *= 0.93
        self.escape_y *= 0.93

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
    base_alpha = min(1.0, age / 1.5) * b.retire_alpha
    if base_alpha < 0.01:
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
    b.bbox = (left, top, left + w_disp, top + h_disp)

    wing_alpha = b.species.get("wing_alpha", 1.0)
    painter.setOpacity(base_alpha * wing_alpha)
    off = b.scale * 1.4
    painter.drawImage(
        QRectF(left + off * 0.6 - w_disp * 0.03, top + off - h_disp * 0.03,
               w_disp * 1.06, h_disp * 1.06),
        shadow_img,
    )
    painter.drawImage(QRectF(left, top, w_disp, h_disp), img)

    # Antennae
    painter.setOpacity(base_alpha)
    antenna = b.species.get("antenna", ANTENNA_CLUB)
    s = b.scale
    ant_w = max(0.8, s * 0.04)
    is_moth = antenna is ANTENNA_FEATHER
    if is_moth:
        ant_w *= 1.8
    painter.setPen(QPen(QColor(48, 41, 31), ant_w,
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    for side in (-1, 1):
        pts = antenna * np.array([side, 1.0, 1.0])
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
        tip_r = s * (0.06 if is_moth else 0.045)
        painter.drawEllipse(
            QPointF(b.x + xs[3], by + ys[3]), tip_r, tip_r
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

        self.mouse_x = -10000
        self.mouse_y = -10000

        self.butterflies = []
        self._dragging = None
        self._drag_prev = (0.0, 0.0)
        self._initial_fill_done = False

        self.start_time = time.monotonic()
        self.physics_steps = 0

        self.spawn_timer = QTimer(self)
        self.spawn_timer.timeout.connect(self._spawn)
        self.spawn_timer.start(SPAWN_INTERVAL_MS)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick)
        self.anim_timer.start(int(1000 / FPS))

        self.show()
        self.raise_()

        if CLICK_THROUGH:
            QTimer.singleShot(300, self._enable_click_through)

    def _spawn(self):
        elapsed = time.monotonic() - self.start_time
        active = [b for b in self.butterflies if not b.retiring]

        if len(active) >= MAX_ON_SCREEN:
            if not self._initial_fill_done:
                self._initial_fill_done = True
                self.spawn_timer.setInterval(ROTATION_SPAWN_MS)
                return
            oldest = min(active, key=lambda b: b.born)
            oldest.start_retire()

        species = pick_species(elapsed)
        x, y, vx, vy = spawn_position(self.sw, self.sh)
        self.butterflies.append(
            Butterfly(x, y, vx, vy, self.sw, self.sh, species)
        )

        if not self._initial_fill_done and len(active) + 1 >= MAX_ON_SCREEN:
            self._initial_fill_done = True
            self.spawn_timer.setInterval(ROTATION_SPAWN_MS)

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
                from Xlib import display, X, XK
                from Xlib.ext import shape

                self.xdisplay = display.Display()
                self._x11_window = self.xdisplay.create_resource_object(
                    "window", int(self.winId())
                )
                self._x11_shape = shape
                self._x11_X = X
                self._x11_window.shape_rectangles(
                    shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, [],
                )

                root = self.xdisplay.screen().root
                self._hotkey_code = self.xdisplay.keysym_to_keycode(
                    XK.string_to_keysym("b")
                )
                mods = X.ControlMask | X.ShiftMask
                for extra in (0, X.Mod2Mask, X.LockMask,
                              X.Mod2Mask | X.LockMask):
                    root.grab_key(
                        self._hotkey_code, mods | extra,
                        True, X.GrabModeAsync, X.GrabModeAsync,
                    )

                self.xdisplay.sync()

                self._hotkey_timer = QTimer(self)
                self._hotkey_timer.timeout.connect(self._check_hotkey)
                self._hotkey_timer.start(150)
            except Exception as e:
                print("X11 setup error:", e)

    def _check_hotkey(self):
        try:
            from Xlib import X
            while self.xdisplay.pending_events():
                ev = self.xdisplay.next_event()
                if ev.type == X.KeyPress:
                    self._quit()
                    return
        except Exception:
            pass

    def _quit(self):
        self.anim_timer.stop()
        self.spawn_timer.stop()
        if hasattr(self, '_hotkey_timer'):
            self._hotkey_timer.stop()
        try:
            from Xlib import X
            root = self.xdisplay.screen().root
            root.ungrab_key(self._hotkey_code, X.AnyModifier)
            self.xdisplay.sync()
        except Exception:
            pass
        self.close()
        QApplication.quit()

    def _update_input_region(self):
        if not hasattr(self, '_x11_window'):
            return
        if self._dragging:
            return
        pad = 10
        rects = []
        for b in self.butterflies:
            x1, y1, x2, y2 = b.bbox
            rects.append((
                max(0, int(x1) - pad), max(0, int(y1) - pad),
                int(x2 - x1) + 2 * pad, int(y2 - y1) + 2 * pad,
            ))
        try:
            self._x11_window.shape_rectangles(
                self._x11_shape.SO.Set, self._x11_shape.SK.Input,
                self._x11_X.Unsorted, 0, 0, rects,
            )
            self.xdisplay.flush()
        except Exception:
            pass

    def _hit_butterfly(self, x, y):
        for b in reversed(self.butterflies):
            bx1, by1, bx2, by2 = b.bbox
            if bx1 <= x <= bx2 and by1 <= y <= by2:
                return b
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x, y = event.x(), event.y()
            b = self._hit_butterfly(x, y)
            if b:
                if b.interaction == "held":
                    return
                b.hold(x, y)
                self._dragging = b
                self._drag_prev = (x, y)
                self.grabMouse()
                if hasattr(self, '_x11_window'):
                    try:
                        self._x11_window.shape_rectangles(
                            self._x11_shape.SO.Set, self._x11_shape.SK.Input,
                            self._x11_X.Unsorted, 0, 0,
                            [(0, 0, self.sw, self.sh)],
                        )
                        self.xdisplay.flush()
                    except Exception:
                        pass

    def mouseMoveEvent(self, event):
        x, y = event.x(), event.y()
        if self._dragging:
            b = self._dragging
            b.x = x + b.held_offset_x
            b.y = y + b.held_offset_y
            self._drag_prev = (x, y)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            b = self._dragging
            x, y = event.x(), event.y()
            px, py = self._drag_prev
            b.release(x - px, y - py)
            self._dragging = None
            self.releaseMouse()
            return
        if event.button() == Qt.LeftButton:
            x, y = event.x(), event.y()
            b = self._hit_butterfly(x, y)
            if b and b.interaction != "held":
                b.startle(x, y)

    def _tick(self):
        cursor = QCursor.pos()
        self.mouse_x = cursor.x()
        self.mouse_y = cursor.y()

        margin = 120
        self.butterflies = [
            b for b in self.butterflies
            if (not b.retiring
                or (-margin < b.x < self.sw + margin
                    and -margin < b.y < self.sh + margin))
            or b is self._dragging
        ]

        elapsed = time.monotonic() - self.start_time
        steps = min(4, int(elapsed * FPS) - self.physics_steps)
        self.physics_steps += steps
        for _ in range(steps):
            for b in self.butterflies:
                b.update(self.mouse_x, self.mouse_y)

        self.update()
        self._update_input_region()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        for b in self.butterflies:
            draw_butterfly(painter, b)

        painter.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._quit()


# ── Entry point ─────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    print("Papillon — press Ctrl+Shift+B to close")
    print("Rare species appear over time. Keep watching!")
    overlay = ButterflyOverlay()
    sys.exit(app.exec_())
