#!/usr/bin/env python3
"""
Arachne — realistic spiders crawl across your desktop.
29 researched species released into one closed box (the screen). Over 1–2 hours
they build webs in corners, hunt and eat each other, court, mate, lay egg sacs,
hatch, balloon away and molt — a community emerges, as it would in reality.
Reuses Papillon's overlay window (click-through, drag & throw, Ctrl+Shift+B).

Legs are 3-segment IK chains with feet planted on the screen and an
alternating-tetrapod gait. Shadows are projected from real 3D joint heights.
Each species has its own proportions, gait and signature behaviour:
pholcid whirling, wolf-spider mothers carrying young, jumping-spider saccades
and pounces, peacock fan dances, tarantula hair flicking, spitting-spider glue,
golden-wheel cartwheels, trapdoor ambushes, net casting, bolas swinging, ...
"""

import sys
import math
import random
import time
import copy

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QPointF, QRectF, QLineF, QTimer
from PyQt5.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QImage, QRadialGradient, QPolygonF,
)

from papillon import ButterflyOverlay, _wrap_angle


# ── Configuration ───────────────────────────────────────

MAX_ON_SCREEN = 18
SIZE_SCALE = 0.765            # global spider size knob
SPAWN_INTERVAL_MS = 3500
ROTATION_SPAWN_MS = 5000
DESCEND_CHANCE = 0.4          # silk spinners sometimes drop from the top edge

RARITY_UNLOCK = {0: 0, 1: 30, 2: 90, 3: 180}      # seconds
RARITY_WEIGHT = {0: 10, 1: 5, 2: 2.5, 3: 1.2}

SX, SY = 0.55, 0.85           # shadow shift per px of height (light top-left)
LIGHT = (-0.55, -0.83)        # direction towards the light, screen space
BODY_DPR = 3.0                # body texture supersampling
FREEZE_RADIUS = 200

SPECIAL_FRAMES = {
    "groom": (60, 120), "bounce": (40, 90), "whirl": (70, 130),
    "shake": (40, 70), "dead": (160, 320), "threat": (130, 220),
    "hiss": (60, 100), "hairflick": (90, 130), "spit": (45, 45),
    "strike": (26, 26), "netstrike": (32, 32), "holdnet": (300, 700),
    "bolas": (400, 900), "display": (160, 280), "plates": (220, 320),
    "drum": (30, 60),
}


# ── World state (clock, season, insects, hiding places, cursor) ─────────
# colony.py updates this every tick; spiders and the ecology read it.

class _World:
    night = 0.0                   # 0 = full day, 1 = deep night
    season = "spring"
    year_s = 4 * 30 * 60          # one compressed year (4 seasons of 30 min)
    insects = []
    hides = []                    # QRectF regions spiders can slip under (windows)
    cursor = (-1e4, -1e4)
    windows = []                  # [(window id, QRectF)] real app windows (X11 only)
    cursor_still = 0.0            # seconds the cursor has rested
    flick = 0.0                   # cursor speed spike, px/frame
    log = None                    # callable(text, kind) for the colony journal


WORLD = _World()

NAMES = ("Mira", "Kavi", "Tara", "Juno", "Bodhi", "Ira", "Nyx", "Sol", "Riya", "Ojas",
         "Luna", "Ash", "Pip", "Zara", "Indu", "Vela", "Moss", "Kiki", "Rumi", "Esha",
         "Orla", "Taro", "Nila", "Fern", "Arya", "Bixi", "Coco", "Dhruv", "Echo", "Fable",
         "Gigi", "Hana", "Ishi", "Jai", "Koko", "Leela", "Milo", "Nori", "Opal", "Puck",
         "Quill", "Ravi", "Sage", "Teja", "Umi", "Vik", "Wren", "Xia", "Yuki", "Zev")
_uid = [0]


def common_name(name):
    return name.replace("_", " ").title()


# ── Painting helpers (unit coords: +x forward, 1 = body unit) ─────────

def _col(c, a=255):
    q = QColor(c)
    q.setAlpha(a)
    return q


def _E(p, cx, cy, rx, ry, c, a=255):
    p.setPen(Qt.NoPen)
    p.setBrush(_col(c, a))
    p.drawEllipse(QPointF(cx, cy), rx, ry)


def _ell_path(cx, rx, ry, cy=0.0):
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), rx, ry)
    return path


def _clip(p, path):
    p.save()
    p.setClipPath(path)


def _fur(p, path, colors, n, rng, length=0.14, width=0.035):
    b = path.boundingRect()
    p.save()
    p.setClipPath(path)
    for _ in range(n):
        x = b.left() + rng.random() * b.width()
        y = b.top() + rng.random() * b.height()
        a = math.pi + rng.gauss(0, 0.5) + y * 0.8   # hairs sweep backwards/out
        ln = length * rng.uniform(0.6, 1.3)
        p.setPen(QPen(_col(rng.choice(colors), rng.randint(60, 150)), width,
                      Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x, y), QPointF(x + math.cos(a) * ln, y + math.sin(a) * ln))
    p.restore()


def _blotches(p, path, colors, n, rng, rmin=0.04, rmax=0.1, alpha=200):
    b = path.boundingRect()
    p.save()
    p.setClipPath(path)
    for _ in range(n):
        r = rng.uniform(rmin, rmax)
        _E(p, b.left() + rng.random() * b.width(), b.top() + rng.random() * b.height(),
           r, r * rng.uniform(0.6, 1.0), rng.choice(colors), alpha)
    p.restore()


def _stripes_x(p, path, xs, color, width, curve=0.0, ry=1.0):
    p.save()
    p.setClipPath(path)
    p.setPen(QPen(_col(color), width, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for x in xs:
        q = QPainterPath(QPointF(x, -ry))
        q.quadTo(QPointF(x - curve, 0), QPointF(x, ry))
        p.drawPath(q)
    p.restore()


# ── Species dorsal patterns: fn(p, ceph_path, abd_path, sp, rng) ──────

def _pat_house(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, cp)
    for side in (-1, 1):
        _E(p, cx, side * 0.2, rx * 0.8, 0.09, "#3e2c1e")
    p.restore()
    _clip(p, ap)
    _E(p, ax + 0.1, 0, arx * 0.85, 0.055, "#b79a74", 200)
    for i in range(6):
        x = ax + arx * 0.62 - i * arx * 0.25
        for side in (-1, 1):
            _E(p, x, side * (0.13 + 0.02 * i), 0.075, 0.05, "#b79a74")
    p.restore()


def _pat_cellar(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _E(p, cx, 0, 0.18, 0.14, "#8c8070", 170)
    _blotches(p, ap, ["#9a8a78", "#8c8070"], 8, rng, 0.05, 0.1, 110)


def _pat_wolf(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, cp)
    for side in (-1, 1):
        _E(p, cx, side * 0.24, rx * 0.9, 0.1, "#3d3025")
    _E(p, cx, 0, rx * 0.95, 0.09, "#9a8264")
    p.restore()
    _clip(p, ap)
    _E(p, ax + 0.3, 0, 0.36, 0.11, "#2a2018")
    p.setPen(QPen(_col("#3d3025", 180), 0.05))
    for i in range(4):
        x = ax - 0.1 - i * 0.2
        p.drawLine(QPointF(x, 0), QPointF(x - 0.14, -0.3))
        p.drawLine(QPointF(x, 0), QPointF(x - 0.14, 0.3))
    p.restore()
    _blotches(p, ap, ["#b8a488", "#9a8264"], 22, rng, 0.03, 0.05, 170)


def _pat_cross(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    _E(p, ax - 0.05, 0, arx * 0.78, ary * 0.6, "#4a3020", 200)
    p.setPen(QPen(_col("#5a3414"), 0.05))
    for side in (-1, 1):
        for i in range(4):
            x = ax + 0.4 - i * 0.32
            p.drawLine(QPointF(x, side * 0.2), QPointF(x - 0.25, side * 0.55))
    for x, y in ((0.45, 0), (0.25, 0), (0.05, 0), (-0.18, 0), (0.25, 0.2),
                 (0.25, -0.2), (0.25, 0.37), (0.25, -0.37)):
        _E(p, ax + x, y, 0.065, 0.065, "#f2eee0")
    p.restore()


def _pat_zebra(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, cp)
    _E(p, cx - 0.22, 0, 0.12, ry, "#f0f0f0")
    p.setPen(QPen(_col("#f0f0f0"), 0.07))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, 0), rx * 0.95, ry * 0.95)
    p.restore()
    _stripes_x(p, ap, (ax + 0.42, ax + 0.08, ax - 0.26), "#ecece4", 0.1, 0.18, ary)


def _pat_widow(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    for x, r in ((-0.55, 0.075), (-0.3, 0.06)):
        _E(p, ax + x, 0, r, r, "#c8141e")


def _pat_crab(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    if sp.get("streak"):
        for side in (-1, 1):
            _E(p, ax, side * 0.55, arx * 0.75, 0.09, sp["streak"], 210)
    _E(p, ax + 0.1, 0, 0.28, 0.16, "#ffffff", 90)
    p.restore()


def _pat_huntsman(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, cp)
    _E(p, cx + rx * 0.75, 0, 0.14, ry, "#e0cfa8", 220)
    _E(p, cx - 0.1, 0, 0.22, 0.16, "#5a4028", 200)
    p.restore()
    _clip(p, ap)
    _E(p, ax + 0.25, 0, 0.35, 0.1, "#6a5030", 180)
    p.restore()
    _blotches(p, ap, ["#4a3420"], 26, rng, 0.03, 0.07, 150)


def _pat_wheel(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    _E(p, ax + 0.25, 0, 0.35, 0.1, "#b08a3a", 170)
    p.restore()
    _fur(p, ap, ["#f0dca0", "#b08a3a"], 60, rng, 0.1, 0.03)


def _pat_redknee(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    _clip(p, cp)
    p.setPen(QPen(_col("#c48a4a"), 0.12))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, 0), rx * 0.92, ry * 0.92)
    p.setPen(QPen(_col("#0e0a08"), 0.05))
    for k in range(8):
        a = k * math.tau / 8
        p.drawLine(QPointF(cx - 0.05, 0),
                   QPointF(cx - 0.05 + math.cos(a) * rx * 0.6, math.sin(a) * ry * 0.6))
    p.restore()
    _fur(p, ap, ["#9a4a2a", "#c86a30"], 110, rng, 0.22, 0.03)


def _pat_goliath(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _fur(p, cp, ["#a8845a", "#3a2818"], 120, rng, 0.16, 0.03)
    _fur(p, ap, ["#a8845a", "#3a2818"], 200, rng, 0.2, 0.03)
    _E(p, ax - 0.2, 0.05, 0.3, 0.22, "#3a2a1c", 200)   # bald patch from hair kicking


def _pat_gooty(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, cp)
    p.setPen(QPen(_col("#1c2440"), 0.07))
    for k in range(8):
        a = k * math.tau / 8
        p.drawLine(QPointF(cx - 0.05, 0),
                   QPointF(cx - 0.05 + math.cos(a) * rx * 0.75, math.sin(a) * ry * 0.75))
    p.restore()
    _clip(p, ap)
    _E(p, ax, 0, arx * 0.85, 0.2, "#1c2440")
    for i in range(5):
        for side in (-1, 1):
            _E(p, ax + 0.55 - i * 0.28, side * 0.34, 0.08, 0.06, "#c8d4e8")
            _E(p, ax + 0.42 - i * 0.28, side * 0.5, 0.06, 0.05, "#1c2440")
    p.restore()
    _fur(p, ap, ["#9ab0e0", "#304878"], 60, rng, 0.16, 0.025)


def _pat_golden_orb(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    for i in range(7):
        for side in (-1, 1):
            _E(p, ax + 0.8 - i * 0.27, side * 0.16, 0.065, 0.055, "#f2e6a0")
    p.restore()


def _pat_wasp(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    _E(p, ax + arx * 0.8, 0, 0.18, ary, "#f4f0e0")
    p.restore()
    _stripes_x(p, ap, [ax + 0.55 - i * 0.22 for i in range(6)], "#111111", 0.08, 0.1, ary)


def _pat_mirror(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _blotches(p, ap, ["#c8a060", "#e07a30", "#b08040"], 14, rng, 0.05, 0.1, 200)


def _pat_peacock(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, cp)
    for side in (-1, 1):
        _E(p, cx - 0.1, side * 0.28, rx * 0.8, 0.07, "#e8f0ff", 200)
        _E(p, cx - 0.1, side * 0.16, rx * 0.8, 0.05, "#e05a20", 200)
    p.restore()
    _clip(p, ap)                     # folded flaps: only a hint of colour
    _E(p, ax, 0, arx * 0.6, ary * 0.5, "#1e8aa0", 90)
    _E(p, ax, 0, arx * 0.35, ary * 0.3, "#e05a20", 90)
    p.restore()


def _pat_spiny(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    for x, y in ((0.0, 0.3), (0.0, -0.3), (-0.22, 0.12), (-0.22, -0.12),
                 (0.25, 0.0), (0.2, 0.55), (0.2, -0.55), (-0.25, 0.6), (-0.25, -0.6),
                 (0.28, 0.3), (0.28, -0.3), (-0.3, 0.3), (-0.3, -0.3)):
        _E(p, ax + x, y, 0.06, 0.06, "#101010")


def _spines(p, sp):
    ax, arx, ary = sp["abd"]
    for a, ln in ((60, 0.2), (100, 0.42), (140, 0.24)):
        for side in (-1, 1):
            r = math.radians(a)
            bx, by = ax + math.cos(r) * arx * 0.85, side * math.sin(r) * ary * 0.85
            tx, ty = bx + math.cos(r) * ln, by + side * math.sin(r) * ln
            nx, ny = -math.sin(r) * 0.08, side * math.cos(r) * 0.08
            p.setPen(Qt.NoPen)
            p.setBrush(_col(sp.get("spine", "#c02020")))
            p.drawPolygon(QPolygonF([QPointF(bx + nx, by + ny), QPointF(tx, ty),
                                     QPointF(bx - nx, by - ny)]))


def _pat_ladybird(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _blotches(p, cp, ["#f0f0f0"], 30, rng, 0.015, 0.03, 200)
    _clip(p, ap)
    _E(p, ax - arx, 0, 0.25, 0.3, "#0a0a0a")
    for x, y, r in ((0.3, 0.3, 0.18), (0.3, -0.3, 0.18), (-0.2, 0.32, 0.18),
                    (-0.2, -0.32, 0.18), (-0.5, 0.15, 0.09), (-0.5, -0.15, 0.09)):
        _E(p, ax + x, y, r, r, "#0a0a0a")
    p.restore()


def _pat_ant(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    _E(p, ax + arx * 0.85, 0, 0.08, ary, "#c8b08a", 200)   # pale "waist" band
    p.restore()


def _pat_net(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _E(p, cx - 0.1, 0, rx * 0.8, 0.05, "#b8a488", 200)
    _clip(p, ap)
    _E(p, ax, 0, arx * 0.95, 0.06, "#b8a488", 200)
    p.restore()
    _blotches(p, ap, ["#5a4838", "#9a846a"], 16, rng, 0.04, 0.08, 150)


def _pat_spitting(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    _clip(p, cp)                     # lyre-shaped carapace markings
    p.setPen(QPen(_col("#2a2018"), 0.07, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for side in (-1, 1):
        q = QPainterPath(QPointF(cx + rx * 0.6, side * 0.08))
        q.cubicTo(QPointF(cx, side * 0.5), QPointF(cx - rx * 0.5, side * 0.1),
                  QPointF(cx - rx * 0.9, side * 0.2))
        p.drawPath(q)
    p.restore()
    _blotches(p, cp, ["#2a2018"], 10, rng, 0.03, 0.06, 220)
    _blotches(p, ap, ["#2a2018"], 18, rng, 0.04, 0.08, 230)


def _pat_trapdoor(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    _E(p, cx - 0.05, 0, 0.08, 0.06, "#1a0a06", 220)       # fovea


def _pat_bolas(p, cp, ap, sp, rng):
    _blotches(p, ap, ["#b89a70", "#6a4a30", "#f4ecd8"], 30, rng, 0.06, 0.16, 200)
    _blotches(p, cp, ["#b89a70", "#6a4a30"], 8, rng, 0.04, 0.08, 200)


def _pat_regal(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    m = sp["mark"]
    _clip(p, ap)
    _E(p, ax + arx * 0.85, 0, 0.12, ary, m)
    p.setPen(Qt.NoPen)
    p.setBrush(_col(m))
    p.drawPolygon(QPolygonF([QPointF(ax + 0.2, 0), QPointF(ax - 0.1, -0.15),
                             QPointF(ax - 0.1, 0.15)]))
    for side in (-1, 1):
        _E(p, ax - 0.35, side * 0.2, 0.08, 0.06, m)
    p.restore()
    _fur(p, ap, ["#ffffff", "#000000"], 50, rng, 0.1, 0.025)


def _pat_bird(p, cp, ap, sp, rng):
    _blotches(p, ap, ["#2a1e18", "#8a8478", "#e8e2d0"], 26, rng, 0.05, 0.16, 220)
    _blotches(p, cp, ["#2a1e18", "#8a8478"], 6, rng, 0.04, 0.08, 200)


def _pat_flower(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    g = QRadialGradient(QPointF(ax, 0), arx * 1.3)
    g.setColorAt(0, _col(sp["petal_mid"], 200))
    g.setColorAt(1, _col(sp["petal_mid"], 0))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(ax, 0), arx * 1.3, ary * 1.3)


def _pat_wandering(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _E(p, cx, 0, rx * 0.85, 0.06, "#3a2e22", 220)
    _clip(p, ap)
    _E(p, ax + 0.1, 0, arx * 0.9, 0.06, "#3a2e22", 220)
    for i in range(4):
        for side in (-1, 1):
            _E(p, ax + 0.45 - i * 0.3, side * 0.2, 0.06, 0.05, "#c8b89a")
    p.restore()
    _fur(p, ap, ["#8a7a64", "#3a2e22"], 90, rng, 0.14, 0.03)


def _pat_bagheera(p, cp, ap, sp, rng):
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    _clip(p, cp)
    p.setPen(QPen(_col("#6a2018"), 0.14))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, 0), rx, ry)
    p.restore()
    _clip(p, ap)
    _E(p, ax, 0, arx * 0.6, ary * 0.4, "#3a7a3a", 180)
    p.restore()


def _pat_social(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    p.setPen(QPen(_col("#4a3420", 220), 0.1, Qt.SolidLine, Qt.RoundCap))
    for i in range(4):
        x = ax + 0.45 - i * 0.3
        p.drawLine(QPointF(x, 0), QPointF(x - 0.2, -0.3))
        p.drawLine(QPointF(x, 0), QPointF(x - 0.2, 0.3))
    p.restore()


def _pat_dewdrop(p, cp, ap, sp, rng):
    ax, arx, ary = sp["abd"]
    _clip(p, ap)
    _E(p, ax + 0.1, -0.15, arx * 0.6, ary * 0.5, "#ffffff", 220)
    for x, y in ((0.2, 0.25), (-0.15, 0.3), (-0.4, 0.05)):
        _E(p, ax + x, y, 0.06, 0.06, "#1a1a1a")
    p.restore()


def _pat_diving(p, cp, ap, sp, rng):
    _fur(p, ap, ["#8a8a88", "#3a3a38"], 120, rng, 0.08, 0.03)


# ── Species catalog ─────────────────────────────────────
# size: body unit in px (body length ≈ 2.4 units). speed: px/frame at 60 fps.
# reach: horizontal hip→foot distance per leg pair, in body units.
# threat: what the spider does when the cursor gets close.

DEFAULTS = dict(
    size=(10, 12), angles=(38, 72, 112, 150), reach=(2.0, 1.8, 1.6, 2.0),
    ceph=(0.45, 0.5, 0.4), abd=(-0.7, 0.72, 0.5), extra=(), hip=None,
    ceph_col="#555", abd_col="#555", pat=None, leg="#444", leg_hi="#999",
    thick=0.15, knee=None, knee_r=0.75, band=None, chel="#141010",
    hairy=False, spec=60, eyes="std", abd_alpha=255, height=0.35,
    speed=1.0, walk=(40, 120), pause=(60, 240), side_walk=0.0,
    gait="normal", threat="flee", idle=None, silk=False, hang=40,
    decor=None, world=None, ground=None, always=None, spawn="edge",
    variants=None, spinnerets=False, spines=False,
)


def _sp(name, rarity, **kw):
    d = dict(DEFAULTS)
    d.update(kw)
    d["name"], d["rarity"] = name, rarity
    if d["idle"] is None:
        d["idle"] = {"groom": 0.002, "tap": 0.004}
    return d


# Always-on leg postures ──────────────────────────────────

def _always_crab(o):
    """Crab spiders sit with the first two leg pairs held wide open."""
    if o.state in ("pause", "watch", "turn") or (o.state == "special" and o.special != "strike"):
        o.ov(0, (1.05, -18, o.s * 0.35))
        o.ov(1, (1.0, -10, o.s * 0.25))


def _always_bird(o):
    if o.state == "pause":
        for i in range(4):
            o.ov(i, (0.5, 8, o.s * 0.15))


def _always_ant(o):
    """Ant mimics hold L1 up as fake antennae and wave it constantly."""
    for side in (-1, 1):
        w = math.sin(o.frame * 0.45 + side * 1.3)
        o.ov(0, (0.75, 28 + w * 10, o.s * (1.3 + 0.45 * w)), side)


def _always_regal(o):
    if o.state == "watch" and math.hypot(o.x - o.mouse[0], o.y - o.mouse[1]) < 170:
        o.ov(0, (0.95, 15, o.s * 1.4))


# Decor: drawn in the body frame, before (post=False) / after lighting ────

def _decor_wolf(p, o, post):
    sp = o.sp
    ax, arx, ary = sp["abd"]
    if o.variant == "babies" and not post:   # a few restless ones shuffle about
        for i, (bx, by, r, c) in enumerate(o.babies):
            bx += math.sin(o.frame * 0.05 + i * 2) * arx * 0.3
            by += math.cos(o.frame * 0.04 + i * 3) * ary * 0.3
            _E(p, bx, by, r, r * 0.8, c)
            _E(p, bx + r * 0.3, by, r * 0.35, r * 0.3, "#3a2e22")
    if o.variant == "eggsac" and post:
        ex, r = ax - arx - 0.35 * ary, ary * 0.75
        g = QRadialGradient(QPointF(ex - r * 0.3, -r * 0.3), r * 1.3)
        g.setColorAt(0, QColor("#ffffff"))
        g.setColorAt(1, QColor("#b8b0a0"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(ex, 0), r, r)


def _decor_mirror(p, o, post):
    if not post:
        return
    a = o.angle
    sz = 0.17 * o.plates
    p.setPen(Qt.NoPen)
    for x, y, ph in o.tiles:
        glint = max(0.0, math.sin(a * 3 + o.frame * 0.05 + ph))
        v = int(200 + 55 * glint)
        p.setBrush(QColor(v, min(255, v + 4), min(255, v + 10)))
        p.drawRoundedRect(QRectF(x - sz / 2, y - sz / 2, sz, sz), 0.04, 0.04)
        if glint > 0.93:
            _E(p, x, y, sz * 0.25, sz * 0.25, "#ffffff")


def _decor_peacock(p, o, post):
    if not post or o.fan <= 0.01:
        return
    sp = o.sp
    ax, arx, ary = sp["abd"]
    e = o.fan * (1 + 0.06 * math.sin(o.frame * 1.3))
    hue = (0.5 + 0.05 * math.sin(o.angle * 2 + o.frame * 0.03)) % 1.0
    teal = QColor.fromHsvF(hue, 0.8, 0.85)
    fx = ax + arx * 0.1
    p.setPen(QPen(QColor(255, 255, 255, 220), 0.06))
    p.setBrush(QColor("#e0402a"))
    p.drawEllipse(QPointF(fx, 0), arx * 1.6 * e, ary * 2.3 * e)
    p.setPen(Qt.NoPen)
    for col, k in ((teal, 0.82), (QColor("#f0a020"), 0.62), (teal.lighter(120), 0.45),
                   (QColor("#e0402a"), 0.28), (QColor("#0a0a0a"), 0.12)):
        p.setBrush(col)
        p.drawEllipse(QPointF(fx, 0), arx * 1.6 * e * k, ary * 2.3 * e * k)
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawEllipse(QPointF(fx - 0.2, -0.3 * e), arx * 0.4 * e, ary * 0.5 * e)


def _decor_regal(p, o, post):
    if not post:
        return
    cx, rx, ry = o.sp["ceph"]
    hue = 0.3 + 0.45 * (0.5 + 0.5 * math.sin(o.angle * 2 + o.frame * 0.04))
    for side in (-1, 1):
        _E(p, cx + rx + 0.02, side * 0.12, 0.15, 0.1, QColor.fromHsvF(hue, 0.85, 0.9).name())
        _E(p, cx + rx - 0.02, side * 0.12 - 0.04, 0.05, 0.03, "#ffffff", 200)


def _decor_diving(p, o, post):
    if not post:
        return
    ax, arx, ary = o.sp["abd"]
    w = 1.08 + 0.02 * math.sin(o.frame * 0.1)
    g = QRadialGradient(QPointF(ax - 0.2, -0.2), arx * 1.3)
    g.setColorAt(0, QColor(255, 255, 255, 235))
    g.setColorAt(0.4, QColor(210, 222, 232, 190))
    g.setColorAt(1, QColor(140, 160, 180, 160))
    p.setPen(QPen(QColor(255, 255, 255, 150), 0.03))
    p.setBrush(g)
    p.drawEllipse(QPointF(ax, 0), arx * w, ary * w * 1.05)


def _decor_widow(p, o, post):
    if post and o.state in ("descend", "land"):
        ax = o.sp["abd"][0]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#d01010"))
        p.drawPolygon(QPolygonF([QPointF(ax + 0.3, -0.17), QPointF(ax + 0.3, 0.17),
                                 QPointF(ax + 0.02, 0.04), QPointF(ax - 0.3, 0.17),
                                 QPointF(ax - 0.3, -0.17), QPointF(ax + 0.02, -0.04)]))


def _decor_bagheera(p, o, post):
    if post and o.variant == "beltian":
        cx, rx, ry = o.sp["ceph"]
        _E(p, cx + rx + 0.3, 0, 0.14, 0.11, "#e8a030")
        _E(p, cx + rx + 0.26, -0.04, 0.04, 0.03, "#fff0c0")


# World-space decor (after the body) ─────────────────────

def _world_net(p, o):
    if o.state != "special" or o.special not in ("holdnet", "netstrike"):
        return
    j = o.joints
    a, b, c, d = j[0][3], j[4][3], j[5][3], j[1][3]      # L1 L, L1 R, L2 R, L2 L
    for pen in (QPen(QColor(40, 50, 70, 90), 1.8), QPen(QColor(225, 238, 250, 230), 0.9)):
        p.setPen(pen)
        for t in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            p.drawLine(QPointF(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                       QPointF(d[0] + (c[0] - d[0]) * t, d[1] + (c[1] - d[1]) * t))
            p.drawLine(QPointF(a[0] + (d[0] - a[0]) * t, a[1] + (d[1] - a[1]) * t),
                       QPointF(b[0] + (c[0] - b[0]) * t, b[1] + (c[1] - b[1]) * t))


def _world_bolas(p, o):
    if o.state != "special" or o.special != "bolas":
        return
    fx, fy, fz = o.joints[5][3]
    k = 1 - o.timer / o.timer_total
    phi = o.frame * 0.12 if 0.45 < k < 0.7 else math.sin(o.frame * 0.06) * 1.0
    base = o.angle + math.pi / 2
    ln = o.s * 3.0
    gx, gy = fx + math.cos(base + phi) * ln, fy + math.sin(base + phi) * ln
    gz = max(0.0, fz - o.s * 0.8)
    p.setPen(QPen(QColor(0, 0, 0, 30), 1.0))
    p.drawLine(QPointF(fx + fz * SX, fy + fz * SY), QPointF(gx + gz * SX, gy + gz * SY))
    p.setPen(QPen(QColor(235, 235, 240, 170), 0.8))
    p.drawLine(QPointF(fx, fy), QPointF(gx, gy))
    r = o.s * 0.28
    g = QRadialGradient(QPointF(gx - r * 0.3, gy - r * 0.3), r * 1.2)
    g.setColorAt(0, QColor("#fff4c8"))
    g.setColorAt(1, QColor("#d8b060"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(gx, gy), r, r)


# Ground decor (under everything) ─────────────────────────

def _ground_bird(p, o):
    if o.splat_alpha <= 0.01:
        return
    sx, sy, sa = o.splat
    p.save()
    p.translate(sx, sy)
    p.rotate(math.degrees(sa))
    p.scale(o.s, o.s)
    p.setPen(Qt.NoPen)
    for dx, dy, rx, ry, c in o.splat_blobs:
        p.setBrush(_col(c, int(235 * o.splat_alpha)))
        p.drawEllipse(QPointF(dx, dy), rx, ry)
    p.restore()


def _ground_trapdoor(p, o):
    bx, by = o.burrow
    r = o.s * 1.45
    hinge = o.lid_angle + math.pi                 # lid hinges at the back
    hx, hy = bx + math.cos(hinge) * r, by + math.sin(hinge) * r
    open_ = o.lid
    p.setPen(Qt.NoPen)
    if open_ > 0.02:                              # dark burrow mouth
        p.setBrush(QColor(20, 12, 6, 230))
        p.drawEllipse(QPointF(bx, by), r * 0.95, r * 0.95)
        if o.hidden:                              # peeking leg tips + eyeshine
            fa = o.lid_angle
            for side in (-1, 1):
                ex = bx + math.cos(fa) * r * 0.75 + math.cos(fa + side * 1.5) * r * 0.3
                ey = by + math.sin(fa) * r * 0.75 + math.sin(fa + side * 1.5) * r * 0.3
                p.setPen(QPen(QColor("#3a1a10"), max(1.0, o.s * 0.12), Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(ex, ey), QPointF(ex + math.cos(fa) * r * 0.35 * open_ * 3,
                                                    ey + math.sin(fa) * r * 0.35 * open_ * 3))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(200, 220, 190, 160))
                p.drawEllipse(QPointF(bx + math.cos(fa) * r * 0.5 + math.cos(fa + side * 1.5) * r * 0.1,
                                      by + math.sin(fa) * r * 0.5 + math.sin(fa + side * 1.5) * r * 0.1),
                              0.9, 0.9)
    # The lid: foreshortened as it swings up around the hinge
    squash = math.cos(open_ * math.pi * 0.45)
    lift = math.sin(open_ * math.pi * 0.45) * r
    p.save()
    p.translate(hx, hy)
    p.rotate(math.degrees(o.lid_angle))
    cxl = r * squash
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawEllipse(QPointF(cxl + lift * 0.6, lift * 0.5), r * squash, r)
    p.setBrush(QColor("#6a5238"))
    p.drawEllipse(QPointF(cxl, 0), r * squash, r)
    p.setBrush(QColor("#4a3824"))
    for dx, dy, rr in o.lid_specks:
        p.drawEllipse(QPointF(cxl + dx * r * squash, dy * r), rr, rr)
    p.setPen(QPen(QColor("#3a2a18"), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cxl, 0), r * squash, r)
    p.restore()


_HUNTER = (38, 72, 112, 150)
_LATERI = (55, 80, 105, 130)
_CRAB = (60, 85, 120, 145)
_JUMP = (30, 70, 110, 150)

SPECIES = [
    # ── Common ──
    _sp("house_spider", 0, size=(12, 15), reach=(3.4, 3.0, 2.6, 3.4),
        ceph=(0.45, 0.5, 0.4), abd=(-0.72, 0.74, 0.48),
        ceph_col="#8a6a4a", abd_col="#6b4e36", pat=_pat_house,
        leg="#7a5c40", leg_hi="#b89a74", thick=0.12, band="#5a4230", hairy=True,
        speed=8.0, walk=(8, 30), pause=(90, 600), spinnerets=True),
    _sp("cellar_spider", 0, size=(9, 11), reach=(8.0, 5.8, 4.4, 5.8),
        ceph=(0.35, 0.4, 0.38), abd=(-1.05, 1.05, 0.34),
        ceph_col="#d8c9a8", abd_col="#cbbba0", pat=_pat_cellar, abd_alpha=215,
        leg="#cbb895", leg_hi="#f4efe0", thick=0.05, knee="#f4efe0", knee_r=1.4,
        height=1.1, speed=0.7, walk=(60, 200), pause=(100, 400), threat="whirl",
        idle={"bounce": 0.002, "groom": 0.001}, silk=True, spec=40),
    _sp("wolf_spider", 0, size=(16, 20), reach=(2.3, 2.1, 1.9, 2.6),
        ceph=(0.5, 0.55, 0.42), abd=(-0.72, 0.72, 0.52),
        ceph_col="#6e5a45", abd_col="#5a4838", pat=_pat_wolf,
        leg="#5a4838", leg_hi="#9a8264", thick=0.17, band="#3d3025", hairy=True,
        eyes="wolf", speed=5.0, walk=(20, 90), pause=(60, 300),
        decor=_decor_wolf),
    _sp("garden_cross", 0, size=(13, 16), reach=(2.3, 2.0, 1.3, 1.8),
        ceph=(0.42, 0.42, 0.36), abd=(-0.8, 0.85, 0.8),
        extra=[(-0.25, -0.5, 0.2, 0.18, "#8a5a2e"), (-0.25, 0.5, 0.2, 0.18, "#8a5a2e")],
        ceph_col="#6a4424", abd_col="#8a5a2e", pat=_pat_cross,
        leg="#b08a5c", leg_hi="#d8b890", thick=0.13, band="#4a3020", hairy=True,
        speed=0.9, walk=(50, 150), pause=(100, 320), threat="dead", silk=True),
    _sp("zebra_jumper", 0, size=(9, 10.5), angles=_JUMP, reach=(1.5, 1.3, 1.3, 1.4),
        ceph=(0.5, 0.58, 0.46), abd=(-0.62, 0.62, 0.44),
        ceph_col="#151515", abd_col="#151515", pat=_pat_zebra,
        leg="#2a2a2a", leg_hi="#d0d0c8", thick=0.2, band="#dcdcd4", hairy=True,
        eyes="jumper", gait="jumper", threat="jumper", speed=1.8,
        walk=(40, 120), pause=(30, 140)),
    _sp("crab_spider", 0, size=(10, 12), angles=_CRAB, reach=(2.4, 2.3, 1.1, 1.1),
        ceph=(0.35, 0.45, 0.45), abd=(-0.62, 0.64, 0.74),
        ceph_col="#f2d93a", abd_col="#f2d93a", pat=_pat_crab,
        leg="#e8d470", leg_hi="#fff8c0", thick=0.17,
        speed=0.45, walk=(40, 120), pause=(200, 700), side_walk=0.8,
        threat="ambush", always=_always_crab, idle={"groom": 0.001},
        variants=[{"ceph_col": "#f2d93a", "abd_col": "#f2d93a", "leg": "#e8d470"},
                  {"ceph_col": "#f4f2e8", "abd_col": "#f4f2e8", "leg": "#ece8d8",
                   "streak": "#c0405a"},
                  {"ceph_col": "#f2d93a", "abd_col": "#f2e060", "streak": "#c0405a"}]),

    # ── Uncommon ──
    _sp("black_widow", 1, size=(12, 14), reach=(3.2, 2.2, 1.8, 2.8),
        ceph=(0.3, 0.34, 0.28), abd=(-0.72, 0.8, 0.74),
        ceph_col="#0e0e10", abd_col="#0a0a0c", pat=_pat_widow,
        leg="#0e0e10", leg_hi="#606878", thick=0.1, spec=220,
        speed=0.8, walk=(40, 140), pause=(100, 300), threat="dead",
        silk=True, hang=140, decor=_decor_widow),
    _sp("huntsman", 1, size=(17, 20), angles=_LATERI, reach=(4.2, 4.8, 3.6, 3.8),
        ceph=(0.42, 0.52, 0.5), abd=(-0.72, 0.72, 0.5),
        ceph_col="#9a7a55", abd_col="#9a7a55", pat=_pat_huntsman,
        leg="#9a7a55", leg_hi="#d0b088", thick=0.15, band="#5a4028", hairy=True,
        height=0.16, speed=12.0, walk=(6, 22), pause=(150, 700), side_walk=0.4,
        idle={"drum": 0.001, "groom": 0.001}),
    _sp("wasp_spider", 1, size=(12, 14), angles=(26, 38, 138, 152),
        reach=(3.0, 2.8, 1.8, 2.6), ceph=(0.36, 0.4, 0.34), abd=(-0.8, 0.85, 0.55),
        ceph_col="#d8d8d8", abd_col="#f2d021", pat=_pat_wasp,
        leg="#e8d8a0", leg_hi="#fff4d0", thick=0.1, band="#202020",
        speed=0.9, walk=(50, 150), pause=(100, 300), threat="dead", silk=True),
    _sp("spitting_spider", 1, size=(8.5, 9.5), reach=(4.8, 3.2, 2.6, 3.8),
        ceph=(0.25, 0.72, 0.56), abd=(-0.95, 0.52, 0.44),
        ceph_col="#e8d8a8", abd_col="#e8d8a8", pat=_pat_spitting,
        leg="#e8d8a8", leg_hi="#fff4d8", thick=0.07, band="#2a2018",
        eyes="six", speed=0.45, walk=(40, 140), pause=(80, 240), threat="spit",
        idle={"tap": 0.012, "groom": 0.001}),
    _sp("redknee_tarantula", 1, size=(26, 30), angles=(35, 70, 110, 150),
        reach=(2.1, 1.9, 1.8, 2.2), ceph=(0.5, 0.62, 0.55), abd=(-0.9, 0.85, 0.68),
        ceph_col="#1a1512", abd_col="#1a1210", pat=_pat_redknee,
        leg="#1c1410", leg_hi="#6a5040", thick=0.27, knee="#e0601e", band="#d88a4a",
        hairy=True, spec=25, height=0.42, speed=0.45, walk=(80, 260), pause=(150, 500),
        threat="hairflick", idle={"tap": 0.006, "groom": 0.0015}),
    _sp("golden_orb", 1, size=(19, 23), angles=(32, 66, 118, 150),
        reach=(4.0, 3.4, 2.0, 3.2), ceph=(0.38, 0.4, 0.32), abd=(-1.05, 1.05, 0.38),
        ceph_col="#d8d8d0", abd_col="#c8903a", pat=_pat_golden_orb,
        leg="#b0602a", leg_hi="#e8a060", thick=0.09, band="#1a1a1a",
        knee="#1a1a1a", knee_r=1.5, spec=90,
        speed=0.8, walk=(50, 150), pause=(100, 300), threat="dead", silk=True),
    _sp("spiny_orb", 1, size=(10, 11.5), reach=(1.3, 1.2, 1.0, 1.2),
        ceph=(0.35, 0.3, 0.28), abd=(-0.35, 0.55, 1.0),
        ceph_col="#1a1a1a", abd_col="#f2f2ea", pat=_pat_spiny, spines=True,
        leg="#1a1a1a", leg_hi="#707070", thick=0.12, spec=120,
        speed=0.6, walk=(40, 120), pause=(150, 400), threat="freeze", silk=True,
        variants=[{}, {"abd_col": "#f0d030"}, {"spine": "#101010"}]),

    # ── Rare ──
    _sp("ant_mimic", 2, size=(9, 10.5), reach=(2.0, 1.7, 1.6, 2.1),
        ceph=(0.62, 0.32, 0.26), hip=(0.05, 0.36, 0.24), abd=(-0.78, 0.46, 0.34),
        extra=[(0.05, 0.0, 0.36, 0.22, "#8a3a20"), (-0.32, 0.0, 0.08, 0.06, "#2a1a12")],
        ceph_col="#8a3a20", abd_col="#2a1a12", pat=_pat_ant, spec=150,
        leg="#3a2418", leg_hi="#8a6a50", thick=0.09, eyes="jumper",
        gait="ant", speed=1.6, walk=(80, 240), pause=(20, 60), always=_always_ant,
        idle={"groom": 0.002}),
    _sp("regal_jumper", 2, size=(13, 15), angles=_JUMP, reach=(1.7, 1.3, 1.3, 1.5),
        ceph=(0.5, 0.6, 0.48), abd=(-0.66, 0.68, 0.5),
        ceph_col="#0e0e0e", abd_col="#0e0e0e", pat=_pat_regal, mark="#f4f4f4",
        leg="#1a1a1a", leg_hi="#e0e0e0", thick=0.22, band="#e8e8e8", hairy=True,
        eyes="jumper", gait="jumper", threat="jumper", speed=2.0,
        walk=(40, 120), pause=(30, 140), always=_always_regal, decor=_decor_regal,
        variants=[{}, {"ceph_col": "#d8702a", "abd_col": "#d8702a", "mark": "#fff0e0",
                       "leg": "#8a4a20", "band": "#f0c8a0"},
                  {"ceph_col": "#8a8a8a", "abd_col": "#7a7a7a", "mark": "#ffffff",
                   "leg": "#4a4a4a"}]),
    _sp("ladybird_spider", 2, size=(11, 13), reach=(1.5, 1.4, 1.4, 1.7),
        ceph=(0.45, 0.5, 0.46), abd=(-0.72, 0.75, 0.64),
        ceph_col="#101010", abd_col="#e03a1a", pat=_pat_ladybird,
        leg="#121212", leg_hi="#5a5a5a", thick=0.2, band="#e8e8e8", hairy=True, spec=50,
        speed=2.0, walk=(80, 250), pause=(30, 90)),
    _sp("net_caster", 2, size=(15, 18), angles=(12, 24, 155, 170),
        reach=(5.5, 5.0, 2.0, 4.0), ceph=(0.5, 0.6, 0.26), abd=(-1.3, 1.2, 0.32),
        ceph_col="#7a6450", abd_col="#7a6450", pat=_pat_net,
        leg="#6a5644", leg_hi="#a08a70", thick=0.07, eyes="ogre",
        speed=0.5, walk=(40, 120), pause=(100, 300), threat="net",
        idle={"holdnet": 0.006, "groom": 0.001}, world=_world_net),
    _sp("trapdoor_spider", 2, size=(14, 17), reach=(1.5, 1.4, 1.3, 1.6),
        ceph=(0.45, 0.58, 0.5), abd=(-0.8, 0.72, 0.62),
        ceph_col="#3a1a10", abd_col="#3a3028", pat=_pat_trapdoor,
        leg="#2a1a12", leg_hi="#7a5a48", thick=0.24, spec=170,
        speed=1.2, walk=(60, 160), pause=(60, 200), spawn="burrow",
        ground=_ground_trapdoor),
    _sp("wandering_spider", 2, size=(22, 26), reach=(4.0, 3.8, 2.8, 3.4),
        ceph=(0.5, 0.6, 0.46), abd=(-0.8, 0.8, 0.5),
        ceph_col="#6a5a48", abd_col="#6a5a48", pat=_pat_wandering,
        leg="#5a4a3a", leg_hi="#9a8a74", thick=0.15, band="#e8e0c8", hairy=True,
        chel="#c04a2a", eyes="wolf", speed=3.0, walk=(30, 100), pause=(60, 240),
        threat="threat", sway=True),
    _sp("bird_dropping", 2, size=(13, 15), angles=_CRAB, reach=(2.0, 1.9, 1.0, 1.0),
        ceph=(0.35, 0.42, 0.4), abd=(-0.6, 0.8, 0.82),
        extra=[(-0.3, 0.45, 0.3, 0.26, "#f4f2ea"), (-0.9, -0.3, 0.28, 0.25, "#f4f2ea"),
               (-0.2, -0.55, 0.22, 0.2, "#e8e2d0")],
        ceph_col="#e8e2d0", abd_col="#f4f2ea", pat=_pat_bird, spec=170,
        leg="#8a8478", leg_hi="#e8e2d0", thick=0.14,
        speed=0.3, walk=(20, 60), pause=(400, 900), side_walk=0.5,
        threat="freeze", always=_always_bird, ground=_ground_bird, idle={}),
    _sp("bagheera", 2, size=(9, 10), angles=_JUMP, reach=(1.9, 1.5, 1.5, 1.9),
        ceph=(0.5, 0.62, 0.42), abd=(-0.6, 0.55, 0.36),
        ceph_col="#2e7a3a", abd_col="#6a4a30", pat=_pat_bagheera, spec=160,
        leg="#d8c07a", leg_hi="#fff0b0", thick=0.12, eyes="jumper",
        gait="jumper", threat="jumper", speed=2.8, walk=(30, 90), pause=(20, 90),
        variants=[{"variant": "beltian"}, {}], decor=_decor_bagheera),
    _sp("goliath_birdeater", 2, size=(36, 42), angles=(35, 70, 110, 150),
        reach=(1.9, 1.7, 1.6, 2.0), ceph=(0.5, 0.64, 0.58), abd=(-0.95, 0.9, 0.72),
        ceph_col="#5a3e2a", abd_col="#5a3e2a", pat=_pat_goliath,
        leg="#4a3222", leg_hi="#a8845a", thick=0.28, band="#8a6a48",
        hairy=True, spec=30, height=0.4, speed=0.35, walk=(80, 260), pause=(200, 600),
        threat="hiss", idle={"tap": 0.005, "groom": 0.001}),

    # ── Ultra-rare ──
    _sp("peacock_spider", 3, size=(10, 11), angles=_JUMP, reach=(1.2, 1.1, 1.7, 1.3),
        ceph=(0.45, 0.52, 0.44), abd=(-0.58, 0.6, 0.48),
        ceph_col="#2a2020", abd_col="#6a4a3a", pat=_pat_peacock,
        leg="#2a2020", leg_hi="#a0a0a0", thick=0.18, band="#f0f0f0", hairy=True,
        eyes="jumper", gait="jumper", threat="jumper", speed=1.5,
        walk=(30, 90), pause=(30, 140), idle={"display": 0.006, "groom": 0.001},
        decor=_decor_peacock),
    _sp("gooty_sapphire", 3, size=(26, 30), angles=(35, 70, 110, 150),
        reach=(2.6, 2.3, 2.1, 2.6), ceph=(0.5, 0.62, 0.55), abd=(-0.9, 0.85, 0.66),
        ceph_col="#4f6fb0", abd_col="#3a5aa0", pat=_pat_gooty,
        leg="#2a5cc8", leg_hi="#9ab8ff", thick=0.24, knee="#101828", band="#f2d21e",
        hairy=True, spec=150, height=0.36, speed=3.5, walk=(12, 45), pause=(150, 450),
        threat="threat"),
    _sp("mirror_spider", 3, size=(10, 11), reach=(2.4, 2.0, 1.4, 2.0),
        ceph=(0.3, 0.34, 0.3), abd=(-0.66, 0.7, 0.66),
        ceph_col="#d8c890", abd_col="#b89060", pat=_pat_mirror,
        leg="#c8c87a", leg_hi="#f0f0c0", thick=0.09, spec=160,
        speed=0.35, walk=(20, 60), pause=(300, 700), threat="plates", silk=True,
        decor=_decor_mirror),
    _sp("golden_wheel", 3, size=(13, 15), angles=_LATERI, reach=(3.2, 3.4, 2.8, 2.9),
        ceph=(0.42, 0.5, 0.46), abd=(-0.68, 0.68, 0.5),
        ceph_col="#d9b25c", abd_col="#d9b25c", pat=_pat_wheel,
        leg="#e6cf8e", leg_hi="#fff4d0", thick=0.11, speed=3.0, walk=(20, 60),
        pause=(80, 300), side_walk=0.4, threat="roll"),
    _sp("flower_crab", 3, size=(13, 15), angles=_CRAB, reach=(2.4, 2.2, 1.1, 1.1),
        ceph=(0.35, 0.4, 0.38), abd=(-0.6, 0.62, 0.66),
        extra=[(-0.1, 0.62, 0.34, 0.26), (-0.1, -0.62, 0.34, 0.26),
               (-0.95, 0.42, 0.32, 0.26), (-0.95, -0.42, 0.32, 0.26), (-1.2, 0, 0.26, 0.24)],
        ceph_col="#f8f4f0", abd_col="#f8f4f0", pat=_pat_flower, abd_alpha=240,
        leg="#f0e8e8", leg_hi="#ffffff", thick=0.15, spec=80,
        speed=0.3, walk=(30, 90), pause=(300, 800), side_walk=0.8,
        threat="ambush", always=_always_crab, idle={},
        variants=[{"petal": "#f8f4f0", "petal_mid": "#e8a0c0"},
                  {"petal": "#f2e070", "petal_mid": "#f8f4f0", "ceph_col": "#f2e070",
                   "abd_col": "#f2e070"},
                  {"petal": "#e8a0c0", "petal_mid": "#fff0f8", "ceph_col": "#f0c0d8",
                   "abd_col": "#e8a0c0", "leg": "#f0c0d8"},
                  {"petal": "#b070c8", "petal_mid": "#f0d8f8", "ceph_col": "#c890d8",
                   "abd_col": "#b070c8", "leg": "#d8b0e8"}]),
    _sp("bolas_spider", 3, size=(13, 15), reach=(1.9, 1.8, 1.0, 1.0),
        ceph=(0.35, 0.38, 0.34), abd=(-0.7, 0.8, 0.95),
        extra=[(-0.1, -0.6, 0.24, 0.22, "#e8e0cc"), (-0.1, 0.6, 0.24, 0.22, "#e8e0cc")],
        ceph_col="#b89a70", abd_col="#e8e0cc", pat=_pat_bolas, spec=110,
        leg="#8a6a48", leg_hi="#d8c0a0", thick=0.16,
        speed=0.25, walk=(20, 50), pause=(300, 800), threat="freeze",
        idle={"bolas": 0.006}, world=_world_bolas),
    _sp("social_spider", 2, size=(6, 7), reach=(2.0, 1.8, 1.5, 1.9),
        ceph=(0.4, 0.45, 0.38), abd=(-0.68, 0.7, 0.55),
        ceph_col="#b08850", abd_col="#d8c49a", pat=_pat_social,
        leg="#c8a870", leg_hi="#f0e0b8", thick=0.11, band="#7a5a38",
        speed=1.0, walk=(40, 120), pause=(60, 220), idle={"groom": 0.002}),
    _sp("dewdrop_spider", 1, size=(6, 7), reach=(3.0, 2.2, 1.4, 2.4),
        ceph=(0.3, 0.32, 0.28), abd=(-0.55, 0.62, 0.62),
        ceph_col="#b8682a", abd_col="#d8dde4", pat=_pat_dewdrop, spec=200,
        leg="#c8783a", leg_hi="#f0b080", thick=0.07,
        speed=0.9, walk=(30, 100), pause=(60, 200)),
    _sp("diving_bell", 3, size=(12, 14), reach=(2.2, 2.0, 1.8, 2.3),
        ceph=(0.45, 0.5, 0.4), abd=(-0.72, 0.72, 0.52),
        ceph_col="#6a4a2a", abd_col="#5a5a58", pat=_pat_diving,
        leg="#6a4a2a", leg_hi="#b89a74", thick=0.13, hairy=True,
        speed=1.8, walk=(40, 120), pause=(60, 200), decor=_decor_diving),
]


def pick_species(elapsed):
    available = [sp for sp in SPECIES if elapsed >= RARITY_UNLOCK[sp["rarity"]]]
    weights = [RARITY_WEIGHT[sp["rarity"]] for sp in available]
    return random.choices(available, weights=weights, k=1)[0]


def _segs(sp):
    """Every body ellipse as (cx, cy, rx, ry): lighting + shadow use these."""
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    out = [(ax, 0.0, arx, ary), (cx, 0.0, rx, ry)]
    out += [(e[0], e[1], e[2], e[3]) for e in sp["extra"]]
    return out


def build_body(sp, s):
    """Pre-render the body (segments, pattern, palps, eyes) once per spider."""
    cx, rx, ry = sp["ceph"]
    ax, arx, ary = sp["abd"]
    segs = _segs(sp)
    x0 = min(c - r for c, _, r, _ in segs) - 0.3
    x1 = cx + rx + 0.55
    half = max(abs(y) + r2 for _, y, _, r2 in segs) + (0.5 if sp["spines"] else 0.2)
    k = s * BODY_DPR
    img = QImage(int((x1 - x0) * k) + 2, int(2 * half * k) + 2,
                 QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(k, k)
    p.translate(-x0, half)
    rng = random.Random(sp["name"])

    cp = _ell_path(cx, rx, ry)
    ap = _ell_path(ax, arx, ary)

    # Pedipalps and chelicerae poke out in front
    p.setPen(QPen(_col(sp["leg"]), max(0.06, sp["thick"] * 0.7),
                  Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for side in (-1, 1):
        path = QPainterPath(QPointF(cx + rx * 0.6, side * ry * 0.35))
        path.quadTo(QPointF(cx + rx + 0.2, side * ry * 0.55),
                    QPointF(cx + rx + 0.38, side * ry * 0.3))
        p.drawPath(path)
        _E(p, cx + rx * 0.9, side * 0.09, 0.16, 0.1, sp["chel"])

    if sp["spines"]:
        _spines(p, sp)
    if sp["spinnerets"]:
        p.setPen(QPen(_col(sp["abd_col"]), 0.07, Qt.SolidLine, Qt.RoundCap))
        for side in (-1, 1):
            p.drawLine(QPointF(ax - arx + 0.05, side * 0.05),
                       QPointF(ax - arx - 0.22, side * 0.1))
    _E(p, ax, 0, arx, ary, sp["abd_col"], sp["abd_alpha"])
    for e in sp["extra"]:
        _E(p, e[0], e[1], e[2], e[3], e[4] if len(e) > 4 else sp.get("petal", sp["abd_col"]),
           sp["abd_alpha"])
    _E(p, (ax + arx * 0.9 + cx - rx * 0.9) / 2, 0, 0.12, 0.1, sp["ceph_col"])
    _E(p, cx, 0, rx, ry, sp["ceph_col"])
    if sp["pat"]:
        sp["pat"](p, cp, ap, sp, rng)
    if sp["hairy"]:
        hi = QColor(sp["leg_hi"]).name()
        _fur(p, ap, [hi, "#000000"], 160, rng)
        _fur(p, cp, [hi, "#000000"], 80, rng)
    if sp.get("variant") == "babies":      # wolf mother: young packed on her back
        n = 0
        while n < 70:
            bx, by = rng.uniform(-1, 1), rng.uniform(-1, 1)
            if bx * bx + by * by < 0.9:
                r = rng.uniform(0.06, 0.09)
                _E(p, ax + bx * arx, by * ary, r, r * 0.8,
                   rng.choice(["#b8a488", "#a08c70", "#c8b898"]))
                _E(p, ax + bx * arx + r * 0.3, by * ary, r * 0.35, r * 0.3, "#3a2e22")
                n += 1

    # Eyes
    ex = cx + rx * 0.72
    style = sp["eyes"]

    def eye(x, y, r, shine=160):
        _E(p, x, y, r, r, "#050505")
        _E(p, x + r * 0.2, y - r * 0.3, r * 0.35, r * 0.35, "#ffffff", shine)

    for side in (-1, 1):
        if style == "jumper":
            eye(ex, side * 0.16, 0.14, 220)
            eye(ex - 0.12, side * 0.33, 0.06)
            eye(cx - rx * 0.2, side * ry * 0.75, 0.05)
        elif style == "ogre":
            eye(ex - 0.05, side * 0.13, 0.17, 230)
            eye(ex + 0.1, side * 0.24, 0.04)
        elif style == "wolf":
            eye(ex + 0.06, side * 0.05, 0.035)
            eye(ex + 0.05, side * 0.14, 0.035)
            eye(ex - 0.1, side * 0.12, 0.085, 220)
            eye(ex - 0.28, side * 0.18, 0.06)
        elif style == "six":
            for dx, dy in ((0.0, 0.08), (-0.04, 0.17), (0.03, 0.26)):
                eye(ex + dx, side * dy, 0.04)
        else:
            for dx, dy, r in ((0.0, 0.07, 0.05), (0.02, 0.17, 0.045),
                              (-0.08, 0.1, 0.04), (-0.07, 0.2, 0.04)):
                eye(ex + dx, side * dy, r)
    p.end()

    # Soft body shadow, blurred once by down/up-scaling
    pad = 0.5
    ks = max(2.0, s)
    simg = QImage(int((x1 - x0 + 2 * pad) * ks) + 2, int((2 * half + 2 * pad) * ks) + 2,
                  QImage.Format_ARGB32_Premultiplied)
    simg.fill(Qt.transparent)
    q = QPainter(simg)
    q.setRenderHint(QPainter.Antialiasing)
    q.scale(ks, ks)
    q.translate(-x0 + pad, half + pad)
    q.setPen(Qt.NoPen)
    q.setBrush(QColor(0, 0, 0, 120))
    shadow = QPainterPath()
    shadow.setFillRule(Qt.WindingFill)
    for c, y, r1, r2 in segs:
        shadow.addEllipse(QPointF(c, y), r1, r2)
    q.drawPath(shadow)
    q.end()
    w, h = simg.width(), simg.height()
    simg = simg.scaled(max(1, w // 4), max(1, h // 4), Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation).scaled(w, h, Qt.IgnoreAspectRatio,
                                                       Qt.SmoothTransformation)
    srect = QRectF(x0 - pad, -half - pad, x1 - x0 + 2 * pad, 2 * half + 2 * pad)
    return img, QRectF(x0, -half, x1 - x0, 2 * half), (simg, srect)


# ── Spider ──────────────────────────────────────────────

class Leg:
    __slots__ = ("side", "i", "group", "hx", "hy", "rx", "ry", "L1", "L2",
                 "bend", "fx", "fy", "fz", "stepping", "t", "dt", "sx", "sy",
                 "sz", "lead", "err", "tap", "free")


def _smooth(k):
    return k * k * (3 - 2 * k)


class Spider:

    def __init__(self, base, sw, sh, sex=None, scale=1.0, size_roll=None):
        sp = dict(base)
        if sp["variants"]:
            sp.update(random.choice(sp["variants"]))
        if sp.get("variant") == "babies":
            sp["variant"] = None              # babies now come from real egg sacs
        self.variant = sp.get("variant")
        self.species = self.sp = sp
        self.base_sp = base
        self.sw, self.sh = sw, sh
        self.eco = ECO.get(base["name"], ECO_DEFAULT)
        self.sex = sex or random.choice("fm")
        self.scale = scale                    # growth stage: 1.0 = adult
        k = scale if self.sex == "f" else min(scale, self.eco["dim"])
        self.size_roll = size_roll or random.uniform(*sp["size"])
        s = self.s = self.size_roll * SIZE_SCALE * k
        hcx, hrx, hry = sp["hip"] or sp["ceph"]

        self.hh = s * sp["height"]
        self.legs = []
        for side in (-1, 1):
            for i in range(4):
                L = Leg()
                L.side, L.i = side, i
                L.group = (i + (side > 0)) % 2       # alternating tetrapod
                h = math.radians((35, 70, 110, 145)[i])
                L.hx = (hcx + hrx * 0.7 * math.cos(h)) * s
                L.hy = side * hry * 0.7 * math.sin(h) * s
                a = math.radians(sp["angles"][i] + random.uniform(-4, 4))
                R = sp["reach"][i] * s * random.uniform(0.95, 1.05)
                L.rx = L.hx + R * math.cos(a)
                L.ry = L.hy + side * R * math.sin(a)
                tot = R * 1.5 + self.hh * 0.6
                L.L1, L.L2 = tot * 0.47, tot * 0.53
                L.bend = side * (0.12 if i < 2 else -0.12)
                L.fx = L.fy = L.fz = 0.0
                L.stepping = L.free = False
                L.t = L.dt = L.sx = L.sy = L.sz = L.lead = L.err = L.tap = 0.0
                self.legs.append(L)
        reach = sp["reach"]
        self.R = max(reach) * s * 1.1
        self.thr = sum(reach) / 4 * s * 0.38
        self.lift = s * 0.55 + self.hh * 0.3
        self.react_r = max(80.0, self.R * 1.3)

        self.body_img, self.body_rect, self.shadow_path = build_body(sp, s)
        self.segs = _segs(sp)

        self.x = self.y = 0.0
        self.angle = self.base = 0.0
        self.side_walk = 0
        self.speed = self.walk_speed = 0.0
        self.vx = self.vy = 0.0
        self.turn = 0.0
        self.target_angle = 0.0
        self.z = self.vz = 0.0
        self.ox = self.oy = 0.0
        self.bob = 0.0
        self.rear = self.rear_t = 0.0
        self.wobble = 0.0
        self.frame = random.randint(0, 1000)
        self.state = "walk"
        self.timer = 0
        self.timer_total = 1
        self.special = None
        self.after = "pause"
        self.sdata = 1
        self.cool = 0
        self.still = 0
        self.hop = None
        self.thread = None            # [anchor_x, end_x, end_y, alpha, attached]
        self.drag = None              # dragline [x0, y0, alpha, attached]
        self.fx_particles = []
        self.fx_spit = []
        self.throw = (0.0, 0.0)
        self.mouse = (-1e4, -1e4)
        self.leg_ov = {}
        self.hidden = False
        self.fan = 0.0
        self.plates = self.plate_t = 1.0
        self.gone = False             # eaten / ballooned away
        self.struggle = 0.0
        self.caught_k = 0.9
        # ecology
        now = time.monotonic()
        self.hunger = random.uniform(0.25, 0.6)
        self.home = None              # (x, y)
        self.web = None
        self.target = None            # prey or mate being approached
        self.prey = None              # corpse being handled
        self.partner = None
        self.goal = None
        self.on_arrive = None
        self.danger = None
        self.wrap = 0.0
        self.carry_sac = False
        self.gravid_at = None
        self.mated_until = 0.0
        self.immune_until = now + 45
        self.settle_at = now + random.uniform(10, 45)
        self.next_molt = now + random.uniform(150, 300)
        self.soft_until = 0.0
        self.husk_until = 0.0
        self.exuvia = False
        self.eco_until = 0.0
        self.home_return_at = now + random.uniform(60, 180)
        self.ball_c = None
        # identity, family and life history
        _uid[0] += 1
        self.uid = _uid[0]
        self.name = random.choice(NAMES)
        self.gen = 0
        self.mother_uid = None
        self.kills = 0
        self.children = 0
        self.meals = 0
        self.age_s = 0.0 if scale < 1 else random.uniform(0.1, 0.45) * self._lifespan_years() * WORLD.year_s
        self.lifespan_s = self._lifespan_years() * WORLD.year_s * random.uniform(0.85, 1.15)
        self.laid_in_autumn = False
        self.hide_rect = None
        self.pluck_until = 0.0
        self.colony = None            # communal web for social spiders
        self.flee_from = (0.0, 0.0)

        rng = random.Random()
        ax, arx, ary = sp["abd"]
        if self.variant == "babies":
            self.babies = []
            while len(self.babies) < 6:
                bx, by = rng.uniform(-1, 1), rng.uniform(-1, 1)
                if bx * bx + by * by < 0.9:
                    self.babies.append((ax + bx * arx, by * ary, rng.uniform(0.06, 0.09),
                                        rng.choice(["#b8a488", "#a08c70", "#c8b898"])))
        if sp["decor"] is _decor_mirror:
            self.tiles = []
            for i in range(-3, 4):
                for j in range(-3, 4):
                    x, y = ax + i * 0.2, j * 0.2
                    if ((x - ax) / arx) ** 2 + (y / ary) ** 2 < 0.8:
                        self.tiles.append((x, y, rng.uniform(0, 6.28)))
        if sp["ground"] is _ground_bird:
            self.splat = (0.0, 0.0, 0.0)
            self.splat_alpha = 0.0
            self.splat_blobs = [(rng.gauss(0, 0.9), rng.gauss(0, 0.9), rng.uniform(0.3, 1.0),
                                 rng.uniform(0.25, 0.8), rng.choice(["#f8f8f4", "#f8f8f4", "#e8e4dc"]))
                                for _ in range(16)]
        if sp["ground"] is _ground_trapdoor:
            self.lid = self.lid_t = 0.0
            self.lid_angle = 0.0
            self.burrow = (0.0, 0.0)
            self.lunge = 0
            self.lid_specks = [(rng.uniform(-0.7, 0.7), rng.uniform(-0.7, 0.7), rng.uniform(0.8, 2.0))
                               for _ in range(14)]

        self.born = time.monotonic()
        self.retiring = False
        self.interaction = None
        self.held_offset_x = self.held_offset_y = 0.0
        self.bbox = (0, 0, 0, 0)
        self.joints = []

    # ── spawning ──

    def spawn(self):
        sp = self.sp
        if sp["spawn"] == "burrow":
            self.spawn_burrow()
        elif sp["silk"] and random.random() < DESCEND_CHANCE:
            self.spawn_descend()
        else:
            self.spawn_edge()

    def spawn_edge(self):
        m = self.R + 20
        edge = random.randint(0, 3)
        if edge == 0:
            self.x, self.y = random.uniform(0, self.sw), -m
        elif edge == 1:
            self.x, self.y = random.uniform(0, self.sw), self.sh + m
        elif edge == 2:
            self.x, self.y = -m, random.uniform(0, self.sh)
        else:
            self.x, self.y = self.sw + m, random.uniform(0, self.sh)
        self.angle = math.atan2(self.sh / 2 - self.y, self.sw / 2 - self.x)
        self.angle += random.uniform(-0.6, 0.6)
        self._set("enter", 9999)
        self.walk_speed = max(1.0, min(4.0, self.sp["speed"] * 0.8))
        self.plant_all()

    def spawn_descend(self):
        self.x = random.uniform(self.sw * 0.08, self.sw * 0.92)
        self.y = -self.R
        self.angle = math.pi / 2            # hangs head-down
        self.z = self.s * 4
        self.land_y = random.uniform(0.2, 0.7) * self.sh
        self.thread = [self.x, 0, 0, 1.0, True]
        self._set("descend", 9999)
        self._tuck(0.75)

    def spawn_burrow(self):
        m = self.R + 60
        self.x = random.uniform(m, self.sw - m)
        self.y = random.uniform(m, self.sh - m)
        self.burrow = (self.x, self.y)
        self.angle = self.lid_angle = random.uniform(0, math.tau)
        self.hidden = True
        self._set("burrow", 99999)
        self.plant_all()

    # ── helpers ──

    def _set(self, state, frames):
        self.state = state
        self.timer = self.timer_total = max(1, int(frames))

    def ov(self, i, spec, side=None):
        """Override a leg's foot target: (reach_k, deg_toward_front, z) or
        ('p', local_x_units, local_y_units, z)."""
        if side is None:
            self.leg_ov[(i, -1)] = spec
            self.leg_ov[(i, 1)] = spec
        else:
            self.leg_ov[(i, side)] = spec

    def _rest_world(self, L, c, sn):
        return (self.x + L.rx * c - L.ry * sn, self.y + L.rx * sn + L.ry * c)

    def plant_all(self):
        c, sn = math.cos(self.angle), math.sin(self.angle)
        for L in self.legs:
            L.fx, L.fy = self._rest_world(L, c, sn)
            L.fz = 0.0
            L.stepping = L.free = False
            L.tap = 0.0

    def _tuck(self, k, wiggle=0.0):
        """Feet hang off the body (airborne): rest pose scaled by k."""
        c, sn = math.cos(self.angle), math.sin(self.angle)
        for L in self.legs:
            w = math.sin(self.frame * 0.45 + L.i * 1.7 + L.side) * wiggle
            lx = L.hx + (L.rx - L.hx) * (k + w * 0.15)
            ly = L.hy + (L.ry - L.hy) * (k - w * 0.1)
            L.fx = self.x + lx * c - ly * sn
            L.fy = self.y + lx * sn + ly * c
            L.fz = max(0.0, self.z - self.s * 0.2 + w * self.s * 0.6)
            L.stepping = False
            L.free = True

    def _steer(self, move_dir, gain=0.15, cap=0.08):
        cur = self.angle + self.side_walk * math.pi / 2
        err = _wrap_angle(move_dir - cur)
        d = max(-cap, min(cap, err * gain))
        self.angle += d
        self.base += d

    def _inward(self):
        m = self.R + 40
        if m < self.x < self.sw - m and m < self.y < self.sh - m:
            return None
        return math.atan2(self.sh / 2 - self.y, self.sw / 2 - self.x)

    def _start_walk(self):
        sp = self.sp
        self._set("walk", random.randint(*sp["walk"]))
        self.walk_speed = sp["speed"] * random.uniform(0.7, 1.25) * (0.55 if self.old() else 1.0)
        self.side_walk = random.choice((-1, 1)) if random.random() < sp["side_walk"] else 0
        self.base = self.angle

    def _start_pause(self, lo=None, hi=None):
        lo = lo if lo is not None else self.sp["pause"][0]
        hi = hi if hi is not None else self.sp["pause"][1]
        self._set("pause", random.randint(lo, max(lo, hi)))

    def _start_flee(self, fx, fy, frames=None, sideways=False):
        self._set("flee", frames or random.randint(40, 80))
        self.flee_from = (fx, fy)
        self.side_walk = random.choice((-1, 1)) if sideways else 0

    def _start_hop(self, direction, dist, dragline=True):
        self.angle = direction
        tx = self.x + math.cos(direction) * dist
        ty = self.y + math.sin(direction) * dist
        m = self.R
        tx = max(m, min(self.sw - m, tx))
        ty = max(m, min(self.sh - m, ty))
        self.hop = (self.x, self.y, tx, ty, self.s * 1.2 + dist * 0.18)
        if dragline:
            self.drag = [self.x, self.y, 1.0, True]
        self._set("hop", 12 + dist / 8)

    def _start_roll(self, direction):
        self.roll_dir = direction
        self.roll_speed = 22.0
        self.roll_phase = 0.0
        self._set("roll", random.randint(45, 70))

    def _special(self, name, after="pause"):
        lo, hi = SPECIAL_FRAMES[name]
        self._set("special", random.randint(lo, hi))
        self.special = name
        self.after = after
        self.sdata = random.choice((-1, 1))
        self.side_walk = 0
        if name == "hairflick":            # turn the rear toward the threat
            mx, my = self.mouse
            self.target_angle = math.atan2(self.y - my, self.x - mx)
        elif name == "spit":
            mx, my = self.mouse
            self.target_angle = math.atan2(my - self.y, mx - self.x)
            self.spat = False

    def _end_special(self):
        a = self.after
        self.special = None
        if isinstance(a, tuple):
            self._special(a[1], a[2] if len(a) > 2 else "pause")
        elif a == "flee":
            self._start_flee(*(self.danger or self.mouse))
        elif a == "flee_side":
            self._start_flee(*(self.danger or self.mouse), sideways=True)
        elif a == "walk":
            self._start_walk()
        else:
            self._start_pause()

    # ── interaction hooks used by ButterflyOverlay ──

    def start_retire(self):
        if self.interaction == "held" or self.state in ECO_BUSY or self.state in DEADISH:
            return
        self.retiring = True
        if self.state == "burrow":
            self._set("emerge", 40)
            return
        if self.state in ("descend", "land", "hop", "fall", "roll", "emerge"):
            return
        self._set("exit", 99999)
        self.walk_speed = max(1.2, min(5.0, self.sp["speed"]))
        self.side_walk = 0

    def startle(self, fx, fy):
        if self.state == "burrow":
            self.lunge = 16
            return
        if self.state in ("walk", "pause", "turn", "watch", "stalk", "flee", "enter", "special"):
            self.cool = 0
            self.mouse = (fx, fy)
            dist = math.hypot(self.x - fx, self.y - fy)
            self._react(fx, fy, min(dist, self.react_r * 0.4), True,
                        math.atan2(fy - self.y, fx - self.x), forced=True)

    def hold(self, gx, gy):
        self.interaction = "held"
        self.held_offset_x = self.x - gx
        self.held_offset_y = self.y - gy
        self.speed = 0.0
        self.hidden = False
        self.special = None
        self.fan = 0.0
        if self.thread:
            self.thread[4] = False
            self.thread[1], self.thread[2] = self.x, self.y

    def release(self, tvx, tvy):
        self.interaction = None
        self.throw = (max(-25, min(25, tvx * 0.6)), max(-25, min(25, tvy * 0.6)))
        self.vz = 0.0
        self._set("fall", 999)

    # ── simulation ──

    def _update_fx(self):
        for q in self.fx_particles:
            q[0] += q[2]
            q[1] += q[3]
            q[2] *= 0.95
            q[3] = q[3] * 0.95 + 0.03
            q[4] -= 1
        self.fx_particles = [q for q in self.fx_particles if q[4] > 0]
        for f in self.fx_spit:
            f[2] -= 1 / 240
        self.fx_spit = [f for f in self.fx_spit if f[2] > 0]
        if self.thread and not self.thread[4]:
            self.thread[3] -= 0.015
            if self.thread[3] <= 0:
                self.thread = None
        if self.drag and not self.drag[3]:
            self.drag[2] -= 0.01
            if self.drag[2] <= 0:
                self.drag = None
        showing = ((self.special == "display" and self.state == "special") or
                   (self.state == "court" and self.sp["name"] == "peacock_spider"))
        self.fan += ((1.0 if showing else 0.0) - self.fan) * 0.12
        self.plates += ((0.55 if self.special == "plates" and self.state == "special" else 1.0)
                        - self.plates) * 0.03

    def update(self, mx, my):
        self.frame += 1
        pmx, pmy = self.mouse
        mouse_moving = math.hypot(mx - pmx, my - pmy) > 1.5
        self.mouse = (mx, my)
        self._update_fx()
        self.leg_ov = {}

        if self.sp["ground"] is _ground_bird:
            if self.state == "pause" and self.speed < 0.05:
                if self.splat_alpha < 0.02:
                    self.splat = (self.x, self.y, random.uniform(0, math.tau))
                self.splat_alpha = min(1.0, self.splat_alpha + 0.01)
            else:
                self.splat_alpha = max(0.0, self.splat_alpha - 0.004)

        st = self.state
        if self.interaction is None:
            if st in ("caught", "dead", "grapple", "stuck", "mate"):
                # moved by the ecology (fights, feeding, mating)
                self.struggle *= 0.995 if st == "dead" else 1.0
                self._tuck(self.caught_k, wiggle=self.struggle)
                return
            if st == "husk":
                return
            if st == "molt":
                self._tuck(0.5, wiggle=0.05)
                return
            if st == "balloon":
                self.z += 0.6 + self.z * 0.01
                self.x += math.sin(self.frame * 0.03) * 0.6 + 0.4
                self.y -= 0.3
                self._tuck(0.8, wiggle=0.2)
                if self.z > self.s * 60:
                    self.gone = True
                return

        if self.interaction == "held":
            self.z += (self.s * 3.5 - self.z) * 0.15
            self.angle += math.sin(self.frame * 0.07) * 0.01
            self._tuck(0.8, wiggle=1.0)
            return

        st = self.state
        if st == "fall":
            self.vz += 0.5
            self.z -= self.vz
            tx, ty = self.throw
            self.x = max(0, min(self.sw, self.x + tx))
            self.y = max(0, min(self.sh, self.y + ty))
            self.throw = (tx * 0.9, ty * 0.9)
            self.angle += tx * 0.01
            if self.z <= 0:
                self.z = 0.0
                self.plant_all()
                if self.retiring:
                    self._set("exit", 99999)
                elif self.sp["threat"] == "dead":
                    self._special("dead", "walk")
                else:
                    self._start_flee(mx, my, 60)
            else:
                self._tuck(0.9, wiggle=0.6)
            return

        if st == "descend":
            dy = self.land_y - self.y
            if self.frame % 240 < self.sp["hang"] and self.y > 0:
                speed = 0.0                  # pauses mid-thread, like they do
            else:
                speed = max(0.35, min(1.6, dy * 0.015))
            self.y += speed
            sway = math.sin(self.frame * 0.035) * self.s * 0.6
            self.x = self.thread[0] + sway
            self.angle = math.pi / 2 - sway * 0.02
            self._tuck(0.75, wiggle=0.25)
            if dy <= 1:
                self._set("land", 24)
                self.thread[4] = False
                self.thread[1], self.thread[2] = self._spinneret()
            return

        if st == "land":
            self.timer -= 1
            self.z *= 0.82
            self._tuck(0.75 + 0.25 * (1 - self.timer / self.timer_total))
            if self.timer <= 0:
                self.z = 0.0
                self.plant_all()
                if self.retiring:
                    self._set("exit", 99999)
                else:
                    self._start_pause(20, 90)
            return

        if st == "hop":
            self.timer -= 1
            x0, y0, x1, y1, H = self.hop
            k = 1 - self.timer / self.timer_total
            self.x = x0 + (x1 - x0) * k
            self.y = y0 + (y1 - y0) * k
            self.z = 4 * H * k * (1 - k)
            self._tuck(0.55 if 0.1 < k < 0.85 else 0.9)
            if self.timer <= 0:
                self.z = 0.0
                self.plant_all()
                if self.drag:
                    self.drag[3] = False
                if self.target is not None and self.target.state not in DEADISH:
                    self._set("hunt", 120)
                else:
                    self._start_pause(20, 70)
            return

        if st == "roll":
            self.timer -= 1
            self.x += math.cos(self.roll_dir) * self.roll_speed
            self.y += math.sin(self.roll_dir) * self.roll_speed
            self.roll_speed = max(6.0, self.roll_speed * 0.985)
            self.roll_phase += self.roll_speed / (self.R * 0.55)
            m = self.R
            if not (m < self.x < self.sw - m and m < self.y < self.sh - m):
                self.x = max(m, min(self.sw - m, self.x))
                self.y = max(m, min(self.sh - m, self.y))
                self.timer = min(self.timer, 3)
            if self.timer <= 0:
                self.angle = self.roll_dir
                self.plant_all()
                self._start_pause(60, 160)
            return

        if st in ("burrow", "emerge"):
            self._update_burrow(mx, my)
            return

        if self.sp["always"]:
            self.sp["always"](self)
        self._behave(mx, my, mouse_moving)
        self._move()
        self._step_legs()

    def _update_burrow(self, mx, my):
        bx, by = self.burrow
        self.lid += (self.lid_t - self.lid) * 0.3
        if self.state == "emerge":
            self.timer -= 1
            self.hidden = False
            self.lid_t = 1.0
            k = 1 - self.timer / self.timer_total
            self.z = 0.0
            self.x = bx + math.cos(self.lid_angle) * self.s * 1.5 * k
            self.y = by + math.sin(self.lid_angle) * self.s * 1.5 * k
            self.angle = self.lid_angle
            self._tuck(0.6 + 0.4 * k)
            if self.timer <= 0:
                self.plant_all()
                self.lid_t = 0.0
                self._set("exit", 99999)
                self.walk_speed = self.sp["speed"]
            return
        dist = math.hypot(mx - bx, my - by)
        if self.lunge > 0:
            self.lunge -= 1
            e = math.sin(math.pi * (1 - self.lunge / 16))
            self.lid_t = 1.0
            self.hidden = e < 0.15
            self.x = bx + math.cos(self.lid_angle) * self.s * 2.8 * e
            self.y = by + math.sin(self.lid_angle) * self.s * 2.8 * e
            self.angle = self.lid_angle
            self.z = 0.0
            self._tuck(0.7 + 0.3 * e)
            if self.lunge == 0:
                self.cool = 120
        else:
            self.hidden = True
            self.x, self.y = bx, by
            self.lid_t = 0.14 + 0.05 * math.sin(self.frame * 0.02)
            if self.cool > 0:
                self.cool -= 1
                self.lid_t = 0.0             # slammed shut, holding it down
            elif dist < self.react_r * 1.1:
                self.lid_angle += _wrap_angle(math.atan2(my - by, mx - bx) - self.lid_angle) * 0.5
                self.lunge = 16
            self._tuck(0.6)

    def _react(self, mx, my, dist, moving, to_mouse, forced=False):
        st = self.state
        t = self.sp["threat"]
        r = self.react_r
        if st == "special" and self.special == "holdnet":
            if dist < r * 1.8 and abs(_wrap_angle(to_mouse - self.angle)) < 1.0:
                self._special("netstrike", ("special", "holdnet", "pause"))
            return
        if st in ("flee", "enter", "exit", "special", "hop", "roll") and not forced:
            return
        if t == "jumper":
            if dist < 75 and (moving or forced):
                self._start_hop(to_mouse + math.pi + random.uniform(-0.7, 0.7),
                                self.s * random.uniform(8, 13))
            elif dist < 300 and st not in ("watch", "stalk"):
                self._set("watch", random.randint(200, 420))
            return
        if dist >= r:
            if (t in ("flee", "threat", "hiss", "hairflick", "roll", "spit") and
                    dist < FREEZE_RADIUS and moving and st in ("walk", "turn") and
                    random.random() < 0.08):
                self._start_pause(40, 150)   # freeze when something moves nearby
            return
        if t in ("freeze", "plates", "ambush") and self.cool > 0:
            return
        if t == "flee" or (self.cool > 0 and t not in ("whirl",)):
            if self.sp["gait"] == "ant":
                self.walk_speed = self.sp["speed"] * 2.2
            self._start_flee(mx, my)
            return
        self.cool = 260
        if t == "whirl":
            self._special("whirl" if random.random() < 0.7 else "bounce", "pause")
        elif t == "threat":
            self._special("threat", "flee")
        elif t == "hiss":
            self._special("hiss", ("special", "threat", "flee"))
        elif t == "hairflick":
            self._special("hairflick", ("special", "threat", "flee"))
        elif t == "spit":
            self._special("spit", "pause")
        elif t == "dead":
            self._special("shake", ("special", "dead", "walk"))
        elif t == "roll":
            self._start_roll(to_mouse + math.pi + random.uniform(-0.4, 0.4))
        elif t == "freeze":
            if dist < r * 0.5:
                self._start_flee(mx, my, 40, sideways=self.sp["side_walk"] > 0)
            else:
                self._start_pause(200, 500)
        elif t == "ambush":
            self._special("strike", "flee_side")
        elif t == "net":
            self._special("netstrike", "pause")
        elif t == "plates":
            self._special("plates", "pause")

    def _behave(self, mx, my, mouse_moving):
        sp = self.sp
        gait = sp["gait"]
        self.timer -= 1
        if self.cool > 0:
            self.cool -= 1
        dist = math.hypot(self.x - mx, self.y - my)
        to_mouse = math.atan2(my - self.y, mx - self.x)
        self.still = 0 if mouse_moving else self.still + 1
        self.rear_t = 0.0
        self.ox *= 0.8
        self.oy *= 0.8
        self.bob *= 0.85

        if not self.retiring and self.state not in ECO_BUSY:
            self._react(mx, my, dist, mouse_moving, to_mouse)
        st = self.state
        ts = 0.0

        if st in ECO_STATES:
            ts = self._eco_behave(st, mx, my)
            self.rear += (self.rear_t - self.rear) * 0.15
            self.speed += (ts - self.speed) * (0.3 if ts > self.speed else 0.4)
            return

        if st == "enter":
            ts = self.walk_speed
            self._steer(math.atan2(self.sh / 2 - self.y, self.sw / 2 - self.x), 0.03, 0.02)
            m = self.R + 60
            if m < self.x < self.sw - m and m < self.y < self.sh - m:
                self._start_walk()

        elif st == "walk":
            ts = self.walk_speed
            if gait == "jumper":
                if (self.frame // 9) % 2:        # jerky step bursts
                    ts = 0.0
                if random.random() < 0.015:      # saccade turn
                    self.angle += random.uniform(0.3, 1.4) * random.choice((-1, 1))
                if random.random() < 0.004:
                    self._start_hop(self.angle, self.s * random.uniform(5, 10))
                    return
            elif gait == "ant":                  # winding trail, 100 ms stops
                self.turn = max(-0.02, min(0.02, self.turn * 0.97 + random.gauss(0, 0.004)))
                self.base += self.turn
                self.angle = self.base + math.sin(self.frame * 0.11) * 0.5
                if self.frame % 50 < 8:
                    ts = 0.0
            else:
                self.turn = max(-0.045, min(0.045, self.turn * 0.96 + random.gauss(0, 0.006)))
                self.angle += self.turn
            inward = self._inward()
            if inward is not None:
                self._steer(inward, 0.1, 0.06)
            if self.timer <= 0:
                if random.random() < 0.35:
                    self._set("turn", 90)
                    self.target_angle = self.angle + random.uniform(0.6, 2.2) * random.choice((-1, 1))
                else:
                    self._start_pause()

        elif st == "pause":
            for name, prob in sp["idle"].items():
                if name == "display" and self.sex != "m":
                    continue                     # only males court with the fan
                if name in ("holdnet", "bolas"):  # nets and bolas come out at night
                    if WORLD.night < 0.5:
                        continue
                    prob *= 3
                if random.random() < prob:
                    if name == "tap":
                        random.choice([L for L in self.legs if L.i == 0]).tap = 1.0
                    else:
                        self._special(name, "pause" if name != "display" else "walk")
                    return
            if self.timer <= 0:
                if not self.active() and random.random() < 0.8:
                    self._start_pause()          # not its time of day: stay put
                elif random.random() < 0.5:
                    self._set("turn", 90)
                    self.target_angle = self.angle + random.uniform(-2.5, 2.5)
                else:
                    self._start_walk()

        elif st == "turn":
            err = _wrap_angle(self.target_angle - self.angle)
            if gait == "jumper":
                if self.frame % 12 == 0:
                    self.angle += err * 0.8
            else:
                self.angle += max(-0.05, min(0.05, err * 0.2))
                ts = 0.1
            if abs(err) < 0.04 or self.timer <= 0:
                self._start_walk()

        elif st == "flee":
            fx, fy = self.flee_from
            ts = max(2.5, min(14.0, sp["speed"] * 2.0))
            away = math.atan2(self.y - fy, self.x - fx)
            inward = self._inward()
            self._steer(away if inward is None else inward, 0.2, 0.12)
            if gait == "ant":
                self.angle += math.sin(self.frame * 0.3) * 0.08
            if self.timer <= 0:
                self._start_pause(80, 300)       # sprint, then freeze

        elif st == "watch":
            # Jumping spiders turn to face you in small, sharp snaps
            err = _wrap_angle(to_mouse - self.angle)
            if abs(err) > 0.25 and self.frame % 12 == 0:
                self.angle += err * 0.85
            if (sp["name"] == "peacock_spider" and self.sex == "m" and dist < 220
                    and random.random() < 0.01):
                self._special("display", "watch")
            elif self.still > 50 and dist < 260 and self.cool <= 0:
                self._set("stalk", 400)
            elif self.timer <= 0 or dist > 320:
                self._start_walk()

        elif st == "stalk":
            err = _wrap_angle(to_mouse - self.angle)
            if abs(err) > 0.15 and self.frame % 10 == 0:
                self.angle += err * 0.9
            ts = sp["speed"] * 0.3 if abs(err) < 0.3 else 0.0
            self.bob = -self.hh * 0.45          # crouch low
            if dist < 115:
                self._start_hop(to_mouse, max(10.0, dist - 18))
                self.cool = 240
                return
            if mouse_moving:
                self._set("watch", 200)
            elif self.timer <= 0:
                self._start_walk()

        elif st == "special":
            k = 1 - self.timer / self.timer_total
            ts = getattr(self, "_sp_" + self.special)(k) or 0.0
            if self.timer <= 0:
                self._end_special()

        elif st == "exit":
            ts = self.walk_speed
            if min(self.x, self.sw - self.x) < min(self.y, self.sh - self.y):
                target = 0.0 if self.x > self.sw / 2 else math.pi
            else:
                target = math.pi / 2 if self.y > self.sh / 2 else -math.pi / 2
            self._steer(target, 0.05, 0.04)

        self.rear += (self.rear_t - self.rear) * 0.15
        ease = 0.25 if ts > self.speed else 0.35     # quick start, abrupt stop
        self.speed += (ts - self.speed) * ease

    # ── signature behaviours (k = 0..1 progress; return target speed) ──

    def _env(self, k, edge=6.0):
        return max(0.0, min(1.0, k * edge, (1 - k) * edge))

    def _sp_groom(self, k):
        cx, rx, ry = self.sp["ceph"]
        w = math.sin(self.frame * 0.25) * 0.12
        self.ov(0, ("p", cx + rx + 0.1 + w, 0.18, self.hh * 1.2 + self.s * 0.2), self.sdata)

    def _sp_bounce(self, k):
        self.bob = math.sin(self.frame * 0.55) * self.s * 0.6 * (1 - k)

    def _sp_whirl(self, k):
        # Pholcids swing their body in circles on fixed feet to blur themselves
        r = self.s * 1.2 * (1 - k * 0.8)
        ph = self.frame * 0.9
        self.ox, self.oy = math.cos(ph) * r, math.sin(ph) * r

    def _sp_drum(self, k):
        self.bob = math.sin(self.frame * 1.6) * self.s * 0.12

    def _sp_shake(self, k):
        a = math.sin(self.frame * 2.3) * self.s * 0.3 * (1 - k * 0.5)
        self.ox, self.oy = math.cos(self.angle) * a, math.sin(self.angle) * a

    def _sp_dead(self, k):
        e = self._env(k, 10)
        for i in range(4):
            self.ov(i, (0.3, 8, self.s * 0.3 * e))
        self.bob = -self.hh * 0.6 * e

    def _sp_threat(self, k):
        e = self._env(k)
        self.rear_t = e
        self.ov(0, (0.95, 28, self.s * 2.0 * e))
        self.ov(1, (0.9, 14, self.s * 1.4 * e))
        if self.sp.get("sway"):
            a = math.sin(self.frame * 0.16) * self.s * 0.35 * e
            self.ox, self.oy = -math.sin(self.angle) * a, math.cos(self.angle) * a

    def _sp_hiss(self, k):
        e = self._env(k)
        self.rear_t = 0.5 * e
        self.ov(0, (0.8, 20, self.s * (1.3 + 0.3 * math.sin(self.frame * 2.2)) * e))
        self.ox += random.uniform(-0.3, 0.3)

    def _sp_hairflick(self, k):
        err = _wrap_angle(self.target_angle - self.angle)
        self.angle += max(-0.08, min(0.08, err * 0.25))
        if abs(err) > 0.3:
            return 0.1
        ax, arx, ary = self.sp["abd"]
        stroke = math.sin(self.frame * 0.6)
        self.ov(3, ("p", ax + stroke * arx * 0.5, 0.3, self.hh + self.s * 0.5))
        if stroke > 0.9 and len(self.fx_particles) < 120:
            mx, my = self.mouse
            rx, ry = self._spinneret()
            d = math.atan2(my - ry, mx - rx)
            for _ in range(8):
                a = d + random.gauss(0, 0.5)
                v = random.uniform(1.0, 3.5)
                self.fx_particles.append([rx, ry, math.cos(a) * v, math.sin(a) * v,
                                          random.randint(40, 90)])

    def _sp_spit(self, k):
        err = _wrap_angle(self.target_angle - self.angle)
        if k < 0.3:
            self.angle += err * 0.3
            self.ov(0, (1.1, 10, self.s * 0.3))
            return
        if not self.spat:
            self.spat = True
            cx, rx, _ = self.sp["ceph"]
            d = (cx + rx + 0.4) * self.s
            mx0 = self.x + math.cos(self.angle) * d
            my0 = self.y + math.sin(self.angle) * d
            mx, my = self.mouse
            L = max(self.s * 4, min(self.R * 3.5, math.hypot(mx - mx0, my - my0)))
            ux, uy = math.cos(self.angle), math.sin(self.angle)
            px, py = -uy, ux
            for off in (-1, 1):
                pts = []
                for n in range(61):
                    u = n / 60
                    w = self.s * 0.9 * u * math.sin(u * math.pi * 16)
                    o = off * self.s * 0.35 * u
                    pts.append(QPointF(mx0 + ux * L * u + px * (w + o),
                                       my0 + uy * L * u + py * (w + o)))
                self.fx_spit.append([QPolygonF(pts), off, 1.0])
            self.ox -= math.cos(self.angle) * self.s * 0.5     # recoil
            self.oy -= math.sin(self.angle) * self.s * 0.5

    def _sp_strike(self, k):
        if k < 0.3:                          # arms snap shut in a blink
            self.ov(0, (0.8, 55, self.s * 0.3))
            self.ov(1, (0.8, 40, self.s * 0.2))

    def _sp_holdnet(self, k):
        cx, rx, _ = self.sp["ceph"]
        f = cx + rx
        w = math.sin(self.frame * 0.05) * 0.1
        self.ov(0, ("p", f + 1.5 + w, 0.7, self.s * 1.1))
        self.ov(1, ("p", f + 0.4 + w, 0.75, self.s * 1.1))

    def _sp_netstrike(self, k):
        e = math.sin(math.pi * k)
        cx, rx, _ = self.sp["ceph"]
        f = cx + rx
        self.ov(0, ("p", f + 1.5 + 2.2 * e, 0.7 + 1.1 * e, self.s * (1.1 - 0.9 * e)))
        self.ov(1, ("p", f + 0.4 + 1.8 * e, 0.75 + 1.1 * e, self.s * (1.1 - 0.9 * e)))
        self.ox = math.cos(self.angle) * self.s * 1.4 * e
        self.oy = math.sin(self.angle) * self.s * 1.4 * e

    def _sp_bolas(self, k):
        self.ov(1, (1.05, -25, self.s * 1.6), 1)

    def _sp_display(self, k):
        # Peacock courtship: L3 raised and waved, fan up, side-to-side shuffle
        e = self._env(k, 8)
        w = math.sin(self.frame * 0.4)
        self.ov(2, (1.0, 45, self.s * (2.2 + 0.5 * w) * e))
        a = math.sin(self.frame * 0.18) * self.s * 0.8 * e
        self.ox, self.oy = -math.sin(self.angle) * a, math.cos(self.angle) * a

    def _sp_plates(self, k):
        pass                                 # plates shrink via self.plates easing

    # ── life history ──

    def _lifespan_years(self):
        yrs = LIFESPAN_YEARS.get(self.base_sp["name"], 1.0)
        return yrs * (0.5 if self.sex == "m" and yrs > 1.5 else 0.8 if self.sex == "m" else 1.0)

    def old(self):
        return self.age_s > self.lifespan_s * 0.85

    def active(self):
        """Is it this species' time of day (and not deep winter)?"""
        t = ACTIVE_TIME.get(self.base_sp["name"], "N")
        n = WORLD.night
        on = n > 0.45 if t == "N" else n < 0.55 if t == "D" else True
        return on and not (WORLD.season == "winter" and random.random() < 0.5)

    # ── ecology behaviours ──

    def _goto(self, x, y, on_arrive):
        self.goal = (x, y)
        self.on_arrive = on_arrive
        self._set("goto", 60 * 90)
        self.walk_speed = max(0.8, min(4.0, self.sp["speed"] * 0.9))
        self.side_walk = 0

    def _face(self, x, y, rate=0.12):
        err = _wrap_angle(math.atan2(y - self.y, x - self.x) - self.angle)
        self.angle += max(-rate, min(rate, err * 0.3))
        return err

    def _eco_behave(self, st, mx, my):
        s = self.s
        now = time.monotonic()
        if st == "goto":
            gx, gy = self.goal
            d = math.hypot(gx - self.x, gy - self.y)
            self._face(gx, gy, 0.08)
            if d < max(6.0, s * 0.8) or self.timer <= 0:
                cb, self.on_arrive = self.on_arrive, None
                self.goal = None
                if callable(cb):
                    cb()
                else:
                    self._start_pause()
                return 0.0
            burst = self.sp["gait"] != "jumper" or (self.frame // 9) % 2 == 0
            return min(self.walk_speed, d * 0.2) if burst else 0.0

        if st in ("hunt", "seek"):
            t = self.target
            if (t is None or t.gone or t.state in DEADISH or t.hidden
                    or self.timer <= 0):
                self.target = None
                self._start_pause()
                return 0.0
            d = math.hypot(t.x - self.x, t.y - self.y)
            self._face(t.x, t.y, 0.15)
            if st == "seek":
                return max(0.8, min(3.0, self.sp["speed"]))
            name = self.sp["name"]
            if self.sp["gait"] == "jumper" and d < s * 16 and self.z == 0:
                self._start_hop(math.atan2(t.y - self.y, t.x - self.x), max(4.0, d - t.s * 0.8))
                return 0.0
            if name == "spitting_spider" and d < self.R * 2.6 and t.state != "stuck":
                self.mouse = (t.x, t.y)
                self._special("spit", "pause")
                self.state = "hunt"           # keep hunting after the spit
                self._sp_spit(0.31)
                self.special = None
                t.stuck(random.uniform(4, 7))
                self.timer = 240
                return 0.0
            if (name == "cellar_spider" and getattr(t, "web", None) is not None
                    and d < t.web.r * 1.4 and now > self.pluck_until - 30
                    and t.state == "hub" and self.pluck_until < now):
                # aggressive mimicry: pluck the victim's web like struggling prey
                self.pluck_until = now + random.uniform(3, 6)
                t._goto(self.x, self.y, None)
                t.walk_speed = max(1.5, t.sp["speed"] * 1.5)
                if WORLD.log:
                    WORLD.log(f"{self.name} the Cellar Spider plucks {t.name}'s web, luring it out", "lure")
            if now < self.pluck_until:
                self._sp_drum(0.5)
                return 0.0
            if (name == "cellar_spider" and d < self.R * 1.3 and t.state != "stuck"):
                # throws silk from a distance with its long legs
                self.fx_spit.append([QPolygonF([QPointF(self.x, self.y), QPointF(t.x, t.y)]), 0, 1.0])
                t.stuck(random.uniform(3, 6))
                self.timer = 240
            active = self.eco["act"] in ("AH", "W")
            if not active and d > self.R * 1.6:
                return 0.0                    # ambushers wait for it to come closer
            return max(1.2, min(9.0, self.sp["speed"] * 1.4))

        if st == "feed":
            self.ov(0, (0.7, 25, s * 0.35))
            if self.prey is not None and self.wrap_needed():
                self.prey.angle += 0.06       # turning the bundle while wrapping
            return 0.0

        if st == "build":
            w = self.web
            if w is None:
                self._start_pause()
                return 0.0
            k = w.progress
            if w.kind == "orb":               # circle the hub, laying spiral
                ang = k * math.tau * 9
                rad = w.r * (0.15 + 0.8 * min(1.0, k * 1.2))
                tx, ty = w.cx + math.cos(ang) * rad, w.cy + math.sin(ang) * rad
            else:
                tx = w.cx + math.sin(k * 37) * w.r * 0.5
                ty = w.cy + math.cos(k * 23) * w.r * 0.5
            self._face(tx, ty, 0.2)
            return min(2.0, math.hypot(tx - self.x, ty - self.y) * 0.15)

        if st == "hub":
            if self.web is not None and self.web.kind == "orb":
                err = _wrap_angle(math.pi / 2 - self.angle)   # hangs head-down
                self.angle += err * 0.05
            return 0.0

        if st == "court":
            f = self.partner
            if f is None or f.state in DEADISH:
                self.partner = None
                self._start_pause()
                return 0.0
            self._face(f.x, f.y, 0.2)
            k = 1 - self.timer / max(1, self.timer_total)
            name = self.sp["name"]
            if name == "peacock_spider":
                self._sp_display(min(0.99, k))
            elif self.sp["gait"] == "jumper":    # zig-zag dance, front legs up
                self.ov(0, (0.95, 20, s * (1.2 + 0.4 * math.sin(self.frame * 0.3))))
                a = math.sin(self.frame * 0.12) * s * 0.8
                self.ox, self.oy = -math.sin(self.angle) * a, math.cos(self.angle) * a
            elif self.eco["web"] in ("orb", "tangle", "sheet"):
                self._sp_drum(k)              # plucking / drumming the silk
            else:
                self._sp_drum(k)
                if self.frame % 30 == 0:
                    random.choice([L for L in self.legs if L.i == 0]).tap = 1.0
            return 0.0

        if st == "spin":                      # spinning an egg sac
            self.angle += math.sin(self.frame * 0.05) * 0.03
            self.bob = math.sin(self.frame * 0.3) * s * 0.15
            return 0.0

        if st == "ball":                      # spiderling cluster
            cx, cy = self.ball_c
            if self.goal is None or math.hypot(self.goal[0] - self.x, self.goal[1] - self.y) < 2:
                self.goal = (cx + random.uniform(-14, 14), cy + random.uniform(-14, 14))
            self._face(*self.goal, 0.2)
            return 0.35 if self.frame % 40 < 15 else 0.0

        if st == "hide":                       # tucked under a window edge / off-screen
            if self.timer <= 0:
                tx = min(max(self.x, self.R), self.sw - self.R)
                ty = min(max(self.y, self.R), self.sh - self.R)

                def out():
                    self.hide_rect = None
                    self._start_walk()
                self._goto(tx, ty, out)       # walk back out, don't pop
            return 0.0

        if st == "guard":
            return 0.0
        return 0.0

    def wrap_needed(self):
        return self.eco["web"] in ("orb", "tangle", "sheet") or self.sp["name"] in (
            "spitting_spider", "cellar_spider")

    def stuck(self, secs):
        if self.state in DEADISH or self.interaction is not None:
            return
        self.state = "stuck"
        self.eco_until = time.monotonic() + secs
        self.struggle = 1.0
        self.caught_k = 0.85
        self.special = None
        self.z = 0.0

    def _move(self):
        md = self.angle + self.side_walk * math.pi / 2
        self.vx = math.cos(md) * self.speed
        self.vy = math.sin(md) * self.speed
        self.x += self.vx
        self.y += self.vy
        if self.state not in ("enter", "exit") and self.hide_rect is None:
            m = self.R * 0.5
            self.x = max(m, min(self.sw - m, self.x))
            self.y = max(m, min(self.sh - m, self.y))

    def _step_legs(self):
        c, sn = math.cos(self.angle), math.sin(self.angle)
        speed = math.hypot(self.vx, self.vy)
        moving = speed > 0.15
        thr = self.thr if moving else self.thr * 0.3
        thr = min(self.R * 0.7, max(thr, speed * 3.5))
        foot_speed = max(speed * 3.0, self.s * 0.3)
        bx, by = self.x + self.ox, self.y + self.oy

        def start(L):
            dur = max(2, min(16, int((L.err + speed * 6) / foot_speed)))
            L.stepping = True
            L.t = 0.0
            L.dt = 1.0 / dur
            L.sx, L.sy, L.sz = L.fx, L.fy, L.fz
            L.lead = dur * 0.8
            L.tap = 0.0

        stepping_group = None
        for L in self.legs:
            spec = self.leg_ov.get((L.i, L.side))
            if spec is not None:
                if spec[0] == "p":
                    lx, ly, tz = spec[1] * self.s, spec[2] * L.side * self.s, spec[3]
                else:
                    k, dang, tz = spec
                    vx, vy = L.rx - L.hx, L.ry - L.hy
                    ang = math.atan2(vy, vx) - L.side * math.radians(dang)
                    ln = math.hypot(vx, vy) * k
                    lx, ly = L.hx + math.cos(ang) * ln, L.hy + math.sin(ang) * ln
                tx, ty = bx + lx * c - ly * sn, by + lx * sn + ly * c
                L.fx += (tx - L.fx) * 0.35
                L.fy += (ty - L.fy) * 0.35
                L.fz += (tz - L.fz) * 0.35
                L.stepping = False
                L.free = True
                L.err = 0.0
                continue
            tx, ty = self._rest_world(L, c, sn)
            if L.free:                      # released from a pose: swing it down
                L.free = False
                L.err = math.hypot(tx - L.fx, ty - L.fy)
                start(L)
            if L.stepping:
                L.t = min(1.0, L.t + L.dt)
                e = _smooth(L.t)
                tx += self.vx * L.lead
                ty += self.vy * L.lead
                L.fx = L.sx + (tx - L.sx) * e
                L.fy = L.sy + (ty - L.sy) * e
                L.fz = L.sz * (1 - e) + math.sin(math.pi * L.t) * self.lift
                if L.t >= 1.0:
                    L.stepping = False
                    L.fz = 0.0
                    L.err = 0.0              # stale err would re-trigger the step forever
                else:
                    stepping_group = L.group
            else:
                L.err = math.hypot(tx - L.fx, ty - L.fy)
                if L.tap > 0:
                    L.tap = max(0.0, L.tap - 0.04)
                    L.fz = math.sin(math.pi * L.tap) * self.lift * 1.4
                else:
                    L.fz = 0.0

        if stepping_group is None:
            errs = [0.0, 0.0]
            need = False
            for L in self.legs:
                if L.free or (L.i, L.side) in self.leg_ov:
                    continue
                if L.err > thr:
                    need = True
                errs[L.group] += L.err
            if need:
                g = 0 if errs[0] >= errs[1] else 1
                for L in self.legs:
                    if (L.group == g and L.err > thr * 0.4 and not L.stepping
                            and (L.i, L.side) not in self.leg_ov):
                        start(L)
                stepping_group = g
        for L in self.legs:
            if (not L.stepping and L.err > thr * 2.5
                    and (L.i, L.side) not in self.leg_ov):
                start(L)

        # Body yaws slightly toward the swinging tripod, like the real gait
        target = 0.0
        if stepping_group is not None and moving:
            target = 0.035 if stepping_group == 0 else -0.035
        self.wobble += (target - self.wobble) * 0.2

    def _spinneret(self):
        ax, arx, _ = self.sp["abd"]
        d = (ax - arx) * self.s
        return (self.x + self.ox + math.cos(self.angle) * d,
                self.y + self.oy + math.sin(self.angle) * d)

    def body_z(self):
        return self.hh + self.z + self.rear * self.s * 0.7 + self.bob

    # ── pose for rendering ──

    def pose(self):
        if self.hidden or self.state == "roll":
            r = self.R if self.state == "roll" else self.s * 2
            self.joints = []
            self.bbox = (self.x - r, self.y - r, self.x + r, self.y + r)
            return
        a = self.angle + self.wobble
        c, sn = math.cos(a), math.sin(a)
        bx, by = self.x + self.ox, self.y + self.oy
        bz = self.body_z()
        joints = []
        xs, ys = [bx], [by]
        for L in self.legs:
            hx = bx + L.hx * c - L.hy * sn
            hy = by + L.hx * sn + L.hy * c
            fx, fy, fz = L.fx, L.fy, L.fz
            dx, dy = fx - hx, fy - hy
            D = math.hypot(dx, dy) or 1e-3
            ux, uy = dx / D, dy / D
            dz = fz - bz
            d = math.hypot(D, dz)
            d = max(abs(L.L1 - L.L2) + 1e-3, min(d, (L.L1 + L.L2) * 0.999))
            cosb = (L.L1 * L.L1 + d * d - L.L2 * L.L2) / (2 * L.L1 * d)
            ka = math.atan2(dz, D) + math.acos(max(-1.0, min(1.0, cosb)))
            kd = L.L1 * math.cos(ka)
            kz = bz + L.L1 * math.sin(ka)
            px, py = -uy * L.bend * D, ux * L.bend * D
            kx, ky = hx + ux * kd + px, hy + uy * kd + py
            ax_ = kx + (fx - kx) * 0.62 + px * 0.35
            ay_ = ky + (fy - ky) * 0.62 + py * 0.35
            az_ = kz + (fz - kz) * 0.62
            joints.append(((hx, hy, bz), (kx, ky, kz), (ax_, ay_, az_), (fx, fy, fz)))
            xs += (kx, fx)
            ys += (ky, fy)
        self.joints = joints
        pad = self.s * 1.5
        self.bbox = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


# ── Rendering ───────────────────────────────────────────

def _shadow_pt(x, y, z):
    return QPointF(x + z * SX, y + z * SY)


def _roll_spokes(o):
    d = o.roll_dir
    ux, uy = math.cos(d), math.sin(d)
    px, py = -uy, ux
    Rw = o.R * 0.55
    out = []
    for n in range(8):
        a = o.roll_phase + n * math.pi / 4
        along, up = math.cos(a) * Rw, math.sin(a) * Rw + Rw
        side = o.s * 0.2 * (1 if n % 2 else -1)
        out.append((o.x + ux * along + px * side, o.y + uy * along + py * side, up))
    return out, Rw


def draw_shadow(p, o):
    if o.hidden:
        return
    s = o.s
    sp = o.sp
    k = max(0.3, 1.0 - o.z / (s * 8))
    if o.state == "husk":
        k *= 0.35 * max(0.0, min(1.0, (o.husk_until - time.monotonic()) / 60))
    w0 = max(0.9, s * sp["thick"])

    if o.state == "roll":
        spokes, Rw = _roll_spokes(o)
        hub = _shadow_pt(o.x, o.y, Rw)
        p.setPen(QPen(QColor(0, 0, 0, 45), w0, Qt.SolidLine, Qt.RoundCap))
        for x, y, z in spokes:
            p.drawLine(hub, _shadow_pt(x, y, z))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(hub, s * 1.2, s * 1.2)
        return

    for width, alpha in ((w0 * 1.1, 60),):
        p.setPen(QPen(QColor(0, 0, 0, int(alpha * k)), width,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        for j in o.joints:
            fz = j[3][2]
            if fz > s * 0.5:              # raised legs cast fainter, softer shadows
                p.setPen(QPen(QColor(0, 0, 0, int(alpha * k * max(0.15, 1 - fz / (s * 2.5)))),
                              width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(QPolygonF([_shadow_pt(*pt) for pt in j]))
                p.setPen(QPen(QColor(0, 0, 0, int(alpha * k)), width,
                              Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            else:
                p.drawPolyline(QPolygonF([_shadow_pt(*pt) for pt in j]))

    bz = o.body_z()
    bx, by = o.x + o.ox, o.y + o.oy
    simg, srect = o.shadow_path
    p.save()
    p.translate(bx + bz * SX, by + bz * SY)
    p.rotate(math.degrees(o.angle + o.wobble))
    blur = 1 + o.z / (s * 10)                # higher = bigger and softer
    p.scale(s * blur, s * blur)
    p.setOpacity(k)
    p.drawImage(srect, simg)
    p.restore()

    if o.z < s:  # ambient occlusion right under the body
        r = s * 1.6
        g = QRadialGradient(QPointF(bx, by), r)
        g.setColorAt(0, QColor(0, 0, 0, 60))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(bx, by), r, r)

    if o.thread:
        ax, ex, ey, alpha, attached = o.thread
        if attached:
            ex, ey = o._spinneret()
        p.setPen(QPen(QColor(0, 0, 0, int(60 * alpha)), 1.0))
        p.drawLine(QPointF(ax + s * 4 * SX, -30), QPointF(ex + bz * SX, ey + bz * SY))


def draw_spider(p, o):
    if o.state != "husk":
        _draw_spider(p, o)
        return
    # dried-out husk (prey remains) or pale shed skin (exuvia), fading away
    fade = max(0.0, min(1.0, (o.husk_until - time.monotonic()) / 60))
    p.save()
    p.setOpacity((0.45 if o.exuvia else 0.75) * fade)
    _draw_spider(p, o, QColor(228, 218, 196) if o.exuvia else QColor(96, 80, 64))
    p.translate(o.x, o.y)
    p.rotate(math.degrees(o.angle))
    p.scale(o.s, o.s)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(236, 226, 205, 150) if o.exuvia else QColor(70, 56, 42, 150))
    for cx, cy, rx, ry in o.segs:
        p.drawEllipse(QPointF(cx, cy), rx * 0.92, ry * (0.7 if not o.exuvia else 0.92))
    p.restore()


def _draw_spider(p, o, leg_col=None):
    if o.hidden:
        return
    s = o.s
    sp = o.sp
    base = leg_col or QColor(sp["leg"])
    hi = _col(sp["leg_hi"], 110)
    band = QColor(sp["band"]) if sp["band"] else None
    w0 = max(0.8, s * sp["thick"])
    widths = (w0, w0 * 0.75, w0 * 0.5)

    if o.state == "roll":
        spokes, Rw = _roll_spokes(o)
        dark = QColor(sp["leg"]).darker(170)
        for ghost, alpha in ((-0.25, 80), (0.0, 240)):
            dark.setAlpha(alpha)
            p.setPen(QPen(dark, w0 * 1.3, Qt.SolidLine, Qt.RoundCap))
            for n, (x, y, z) in enumerate(spokes):
                if ghost:
                    a = o.roll_phase + ghost + n * math.pi / 4
                    x = o.x + math.cos(o.roll_dir) * math.cos(a) * Rw
                    y = o.y + math.sin(o.roll_dir) * math.cos(a) * Rw
                p.drawLine(QPointF(o.x, o.y), QPointF(x, y))
        p.save()
        p.translate(o.x, o.y)
        p.rotate(math.degrees(o.roll_dir))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(sp["abd_col"]))
        p.drawEllipse(QPointF(0, 0), s * 1.2, s * 0.35)
        p.restore()
        return

    # Silk thread / dragline
    if o.thread:
        ax, ex, ey, alpha, attached = o.thread
        if attached:
            ex, ey = o._spinneret()
        p.setPen(QPen(QColor(230, 235, 240, int(150 * alpha)), 0.8))
        p.drawLine(QPointF(ax, -30), QPointF(ex, ey))
    if o.drag:
        x0, y0, alpha, _ = o.drag
        ex, ey = o._spinneret()
        p.setPen(QPen(QColor(235, 240, 245, int(120 * alpha)), 0.7))
        p.drawLine(QPointF(x0, y0), QPointF(ex, ey))

    # Legs
    hairs = []
    for j in o.joints:
        pts = [QPointF(x, y) for x, y, _ in j]
        for seg in range(3):
            a, b = pts[seg], pts[seg + 1]
            w = widths[seg]
            p.setPen(QPen(base, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(a, b)
            if band is not None and seg > 0:
                mid = QPointF(a.x() + (b.x() - a.x()) * 0.3, a.y() + (b.y() - a.y()) * 0.3)
                p.setPen(QPen(band, w * 1.05, Qt.SolidLine, Qt.FlatCap))
                p.drawLine(a, mid)
            if w > 2.5:
                off = QPointF(-0.25 * w, -0.35 * w)
                p.setPen(QPen(hi, w * 0.3, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(a + off, b + off)
            if sp["hairy"] and seg < 2:
                dx, dy = b.x() - a.x(), b.y() - a.y()
                ln = math.hypot(dx, dy) or 1
                nx, ny = -dy / ln * w * 1.1, dx / ln * w * 1.1
                for t in (0.25, 0.5, 0.75):
                    cx, cy = a.x() + dx * t, a.y() + dy * t
                    hairs.append(QLineF(cx - nx, cy - ny, cx + nx - dx * 0.08, cy + ny - dy * 0.08))
        if sp["knee"]:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(sp["knee"]))
            p.drawEllipse(pts[1], w0 * sp["knee_r"] * 0.75, w0 * sp["knee_r"] * 0.75)
    if hairs:
        p.setPen(QPen(_col(sp["leg_hi"], 90), max(0.5, w0 * 0.12)))
        p.drawLines(hairs)

    # Body: cached texture + live lighting so highlights stay put as it turns
    a = o.angle + o.wobble
    p.save()
    p.translate(o.x + o.ox, o.y + o.oy)
    p.rotate(math.degrees(a))
    sc = s * (1 + (o.body_z() - o.hh) * 0.004)
    p.scale(sc, sc)
    p.drawImage(o.body_rect, o.body_img)
    decor = sp["decor"]
    if decor:
        decor(p, o, False)

    c, sn = math.cos(a), math.sin(a)
    lx = LIGHT[0] * c + LIGHT[1] * sn
    ly = -LIGHT[0] * sn + LIGHT[1] * c
    p.setPen(Qt.NoPen)
    for cx, cy, rx, ry in o.segs:
        g = QRadialGradient(QPointF(cx + lx * rx * 0.45, cy + ly * ry * 0.45), max(rx, ry) * 1.3)
        g.setColorAt(0.0, QColor(255, 255, 255, sp["spec"]))
        g.setColorAt(0.3, QColor(255, 255, 255, 0))
        g.setColorAt(0.7, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 0, 0, 120))
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), rx, ry)
    if decor:
        decor(p, o, True)
    if o.carry_sac:                           # egg sac held in the fangs
        cx, rx, _ = sp["ceph"]
        _E(p, cx + rx + 0.4, 0, 0.45, 0.45, "#f4f0e6")
        _E(p, cx + rx + 0.3, -0.12, 0.15, 0.12, "#ffffff")
    if o.wrap > 0.02:                         # silk-wrapped bundle
        p.setBrush(QColor(246, 246, 250, int(215 * o.wrap)))
        for cx, cy, rx, ry in o.segs:
            p.drawEllipse(QPointF(cx, cy), rx * 1.12, ry * 1.12)
        p.setPen(QPen(QColor(255, 255, 255, int(200 * o.wrap)), 0.05))
        for k in range(int(10 * o.wrap)):
            y = -0.6 + k * 0.13
            p.drawLine(QPointF(-1.4, y), QPointF(0.9, -y * 0.8))
    p.restore()


def draw_fx(p, o):
    if o.sp["world"] and not o.hidden:
        o.sp["world"](p, o)
    for f in o.fx_spit:
        poly, off, alpha = f
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(30, 32, 40, int(110 * alpha)), 2.0,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(poly)
        p.setPen(QPen(QColor(248, 244, 225, int(210 * alpha)), 1.1,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(poly)
    if o.fx_particles:
        p.setPen(Qt.NoPen)
        for x, y, _, _, life in o.fx_particles:
            p.setBrush(QColor(170, 110, 60, min(200, life * 3)))
            p.drawEllipse(QPointF(x, y), 0.9, 0.9)


# ── Ecology: the screen is a closed box full of spiders ─────────────────
# Trait scores from the literature (araneophagy, aggression, fighting power,
# defence, conspecific tolerance, cannibalism), web type, preferred site,
# activity (SW sit-and-wait, AH active hunter, W wanderer), detection range in
# cm, sexual-cannibalism probability and male/female size ratio.
# Time is compressed: webs in ~1 min, egg sacs ~5 min after mating, etc.

def _eco(ara, agg, fight, dfn, tol, cann, web, site, act, det, scann, dim):
    return dict(ara=ara, agg=agg, fight=fight, dfn=dfn, tol=tol, cann=cann, web=web,
                site=site, act=act, det=det, scann=scann, dim=dim)


ECO_DEFAULT = _eco(0.2, 0.4, 0.4, 0.4, 0.3, 0.3, "none", "floor", "W", 5, 0.1, 0.85)
ECO = {
    "house_spider":      _eco(0.35, 0.5, 0.5, 0.5, 0.15, 0.5, "sheet", "corner_low", "SW", 6, 0.1, 0.9),
    "cellar_spider":     _eco(0.85, 0.6, 0.55, 0.6, 0.6, 0.5, "tangle", "corner_high", "SW", 8, 0.1, 0.9),
    "wolf_spider":       _eco(0.5, 0.75, 0.65, 0.5, 0.15, 0.7, "none", "floor", "AH", 12, 0.2, 0.85),
    "garden_cross":      _eco(0.15, 0.3, 0.4, 0.3, 0.3, 0.45, "orb", "edge", "SW", 5, 0.25, 0.55),
    "zebra_jumper":      _eco(0.3, 0.5, 0.25, 0.5, 0.3, 0.3, "none", "edge", "AH", 22, 0.05, 0.85),
    "crab_spider":       _eco(0.15, 0.3, 0.45, 0.4, 0.25, 0.3, "none", "edge", "SW", 3, 0.1, 0.45),
    "black_widow":       _eco(0.3, 0.4, 0.85, 0.6, 0.3, 0.4, "tangle", "corner_low", "SW", 5, 0.3, 0.45),
    "huntsman":          _eco(0.5, 0.55, 0.7, 0.85, 0.3, 0.5, "none", "edge", "AH", 6, 0.15, 0.85),
    "wasp_spider":       _eco(0.1, 0.3, 0.45, 0.4, 0.3, 0.8, "orb", "edge", "SW", 5, 0.8, 0.4),
    "spitting_spider":   _eco(0.85, 0.5, 0.6, 0.4, 0.3, 0.4, "none", "corner_high", "AH", 6, 0.1, 0.85),
    "redknee_tarantula": _eco(0.4, 0.35, 0.75, 0.8, 0.05, 0.6, "mat", "edge", "SW", 3, 0.15, 0.85),
    "golden_orb":        _eco(0.1, 0.25, 0.55, 0.5, 0.55, 0.25, "orb", "edge", "SW", 5, 0.1, 0.3),
    "spiny_orb":         _eco(0.05, 0.15, 0.2, 0.85, 0.5, 0.2, "orb", "edge", "SW", 3, 0.1, 0.45),
    "ant_mimic":         _eco(0.1, 0.2, 0.15, 0.75, 0.4, 0.2, "none", "edge", "W", 15, 0.05, 0.9),
    "regal_jumper":      _eco(0.45, 0.65, 0.5, 0.55, 0.15, 0.5, "none", "edge", "AH", 22, 0.1, 0.9),
    "ladybird_spider":   _eco(0.3, 0.4, 0.45, 0.7, 0.55, 0.3, "mat", "floor", "W", 5, 0.1, 0.8),
    "net_caster":        _eco(0.05, 0.25, 0.25, 0.6, 0.3, 0.2, "none", "edge", "SW", 4, 0.1, 0.8),
    "trapdoor_spider":   _eco(0.35, 0.5, 0.55, 0.9, 0.1, 0.4, "burrow", "burrow", "SW", 4, 0.1, 0.8),
    "wandering_spider":  _eco(0.6, 0.95, 0.9, 0.75, 0.05, 0.6, "none", "floor", "AH", 8, 0.15, 0.85),
    "bird_dropping":     _eco(0.1, 0.15, 0.3, 0.8, 0.3, 0.2, "none", "edge", "SW", 3, 0.1, 0.45),
    "bagheera":          _eco(0.05, 0.15, 0.1, 0.6, 0.45, 0.15, "none", "edge", "W", 18, 0.05, 0.9),
    "goliath_birdeater": _eco(0.4, 0.6, 0.95, 0.9, 0.0, 0.5, "mat", "edge", "SW", 3, 0.15, 0.85),
    "peacock_spider":    _eco(0.05, 0.2, 0.05, 0.45, 0.4, 0.2, "none", "floor", "AH", 18, 0.1, 0.9),
    "gooty_sapphire":    _eco(0.35, 0.5, 0.8, 0.7, 0.45, 0.4, "mat", "edge", "SW", 4, 0.1, 0.8),
    "mirror_spider":     _eco(0.05, 0.1, 0.1, 0.4, 0.3, 0.2, "tangle", "corner_high", "SW", 3, 0.1, 0.8),
    "golden_wheel":      _eco(0.3, 0.4, 0.45, 0.85, 0.2, 0.3, "none", "floor", "W", 6, 0.1, 1.0),
    "flower_crab":       _eco(0.1, 0.25, 0.35, 0.5, 0.3, 0.25, "none", "edge", "SW", 3, 0.1, 0.4),
    "bolas_spider":      _eco(0.0, 0.1, 0.15, 0.75, 0.3, 0.1, "none", "edge", "SW", 2, 0.1, 0.35),
    "diving_bell":       _eco(0.3, 0.5, 0.4, 0.4, 0.35, 0.5, "none", "corner_low", "SW", 5, 0.1, 1.15),
}
ECO["social_spider"] = _eco(0.05, 0.4, 0.2, 0.4, 1.0, 0.0, "tangle", "edge", "SW", 5, 0.0, 0.8)
ECO["dewdrop_spider"] = _eco(0.1, 0.2, 0.15, 0.6, 0.5, 0.1, "none", "edge", "W", 10, 0.05, 0.85)
DIURNAL = {"zebra_jumper", "crab_spider", "wasp_spider", "golden_orb", "spiny_orb", "ant_mimic",
           "regal_jumper", "bird_dropping", "bagheera", "peacock_spider", "flower_crab"}
ACTIVE_TIME = {n: ("D" if n in DIURNAL else "B" if n in ("social_spider", "dewdrop_spider") else "N")
               for n in ECO}
LIFESPAN_YEARS = {"house_spider": 2, "cellar_spider": 2.5, "black_widow": 1.5, "wolf_spider": 1.5,
                  "huntsman": 2, "redknee_tarantula": 15, "goliath_birdeater": 12,
                  "gooty_sapphire": 10, "trapdoor_spider": 8, "golden_wheel": 2,
                  "wandering_spider": 2, "spitting_spider": 2}           # others: annual
SOCIAL_CAP = 20
CRYPTIC = {"bird_dropping": 0.6, "bolas_spider": 0.6, "mirror_spider": 0.4, "flower_crab": 0.5,
           "crab_spider": 0.4, "net_caster": 0.5}
PREY_MULT = {"ant_mimic": 0.33, "spiny_orb": 0.3}

ECO_STATES = {"goto", "hunt", "seek", "feed", "build", "hub", "court", "spin", "ball", "guard", "hide"}
DEADISH = {"dead", "husk", "caught"}
ECO_BUSY = ECO_STATES | DEADISH | {"grapple", "stuck", "mate", "molt", "balloon"}
FREE = {"walk", "pause", "turn", "watch", "stalk", "special", "hub", "goto", "guard"}
TARGETABLE = FREE | {"feed", "build", "stuck", "molt", "court", "ball", "spin", "seek", "hunt", "flee"}

ECO_K = 0.25                    # global predation pressure knob
CAP_ADULTS = 22
MAX_JUV = 16
MAX_PER_SPECIES = 4             # niche limit: extra spiderlings balloon away
MIN_SPECIES = 12                # immigrants keep arriving while variety is low
INITIAL_COUNT = 16
IMMIGRATION_S = (60, 120)
PX_PER_CM = 14


class Web:
    """Orb, tangle (cobweb), funnel sheet, or tarantula silk mat."""

    def __init__(self, owner, kind, cx, cy, r, corner):
        self.owner = owner
        self.species = owner.sp["name"]
        self.kind, self.cx, self.cy, self.r = kind, cx, cy, r
        self.corner = corner                  # (cx, cy) of the screen corner/edge anchor
        self.progress = 0.0
        self.integrity = 1.0
        self.cache = None
        rng = random.Random()
        self.lines = []
        golden = self.species == "golden_orb"
        self.color = QColor(232, 205, 110) if golden else QColor(236, 240, 246)
        if kind == "orb":
            n = rng.randint(18, 26)
            self.radials = []
            for k in range(n):
                a = k * math.tau / n + rng.uniform(-0.08, 0.08)
                rr = r * rng.uniform(0.85, 1.05)
                self.radials.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
            self.spiral = []
            turns = rng.randint(14, 20)
            m = turns * n
            for k in range(m + 1):
                f = k / m
                a = f * turns * math.tau
                rr = r * (0.18 + 0.78 * f) * rng.uniform(0.97, 1.03)
                self.spiral.append(QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr))
            ax, ay = corner
            self.anchor_pts = []
            for px, py in ((ax, cy), (cx, ay)):
                if abs(px - cx) > 1 or abs(py - cy) > 1:
                    self.anchor_pts.append((px, py))
        else:
            npts = {"tangle": 55, "sheet": 70, "mat": 40}[kind]
            ax, ay = corner
            for _ in range(npts):
                def pt():
                    a = rng.uniform(0, math.tau)
                    rr = r * math.sqrt(rng.random())
                    return cx + math.cos(a) * rr, cy + math.sin(a) * rr
                if kind == "sheet" and rng.random() < 0.35:   # funnel lines into the corner
                    x0, y0 = pt()
                    self.lines.append((x0, y0, ax + (x0 - ax) * 0.15, ay + (y0 - ay) * 0.15))
                elif kind == "mat":
                    x0, y0 = pt()
                    a = rng.uniform(0, math.tau)
                    ln = r * rng.uniform(0.2, 0.6)
                    self.lines.append((x0, y0, x0 + math.cos(a) * ln, y0 + math.sin(a) * ln))
                else:
                    x0, y0 = pt()
                    x1, y1 = pt()
                    self.lines.append((x0, y0, x1, y1))
            if self.species == "black_widow":             # sticky gumfoot lines
                for _ in range(7):
                    x0 = cx + rng.uniform(-r, r) * 0.7
                    y0 = cy + rng.uniform(-r, r) * 0.3
                    self.lines.append((x0, y0, x0 + rng.uniform(-6, 6), y0 + r * rng.uniform(0.8, 1.4)))

    def hub(self):
        if self.kind == "sheet":
            ax, ay = self.corner
            return self.cx + (ax - self.cx) * 0.35, self.cy + (ay - self.cy) * 0.35
        return self.cx, self.cy

    def contains(self, x, y):
        return math.hypot(x - self.cx, y - self.cy) < self.r

    def draw(self, p):
        if self.progress <= 0.01 or self.integrity <= 0.02:
            return
        if self.progress < 1.0:
            self._layers(p, self.integrity)   # still being spun: draw live
            return
        if self.cache is None:                # finished webs never change shape
            xs = [self.cx - self.r - 4, self.cx + self.r + 4]
            ys = [self.cy - self.r - 4, self.cy + self.r + 4]
            for x, y in getattr(self, "anchor_pts", []):
                xs.append(x)
                ys.append(y)
            for x0, y0, x1, y1 in self.lines:
                xs += (x0, x1)
                ys += (y0, y1)
            x0, y0 = math.floor(min(xs)) - 2, math.floor(min(ys)) - 2
            img = QImage(int(max(xs) - x0) + 4, int(max(ys) - y0) + 4,
                         QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            q = QPainter(img)
            q.setRenderHint(QPainter.Antialiasing)
            q.translate(-x0, -y0)
            self._layers(q, 1.0)
            q.end()
            self.cache = (img, x0, y0)
        img, x0, y0 = self.cache
        p.save()
        p.setOpacity(self.integrity)
        p.drawImage(QPointF(x0, y0), img)
        p.restore()

    def _layers(self, p, a):
        """Shadow strands under the silk, so webs read on light *and* dark screens."""
        p.save()
        p.translate(1.3, 2.0)
        self._paint(p, a, dark=True)
        p.restore()
        self._paint(p, a)

    def _paint(self, p, a, dark=False):
        if dark:
            a *= 0.6
        col = QColor(30, 32, 40) if dark else QColor(self.color)
        if self.kind == "orb":
            k = self.progress
            nr = int(len(self.radials) * min(1.0, k / 0.3))
            col.setAlpha(int(120 * a))
            p.setPen(QPen(col, 0.7))
            for x, y in self.radials[:nr]:
                p.drawLine(QPointF(self.cx, self.cy), QPointF(x, y))
            if k > 0.3 and nr:
                for x, y in self.anchor_pts:
                    p.drawLine(QPointF(self.cx, self.cy), QPointF(x, y))
                ns = int(len(self.spiral) * (k - 0.3) / 0.7)
                if ns > 2:
                    col.setAlpha(int(85 * a))
                    p.setPen(QPen(col, 0.55))
                    p.drawPolyline(QPolygonF(self.spiral[-ns:]))
            if k >= 1 and self.species == "wasp_spider":  # zig-zag stabilimentum
                col.setAlpha(int(200 * a))
                p.setPen(QPen(col, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                for d in (-1, 1):
                    pts = [QPointF(self.cx + (5 if j % 2 else -5), self.cy + d * (8 + j * 5))
                           for j in range(int(self.r / 7))]
                    p.drawPolyline(QPolygonF(pts))
            if k >= 1 and self.species == "spiny_orb":    # silk tufts on the frame
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(30, 32, 40, int(170 * a)) if dark
                           else QColor(255, 255, 255, int(170 * a)))
                for x, y in self.radials[::3]:
                    p.drawEllipse(QPointF(x, y), 1.6, 1.6)
        else:
            n = int(len(self.lines) * self.progress)
            alpha = {"tangle": 70, "sheet": 55, "mat": 45}[self.kind]
            col.setAlpha(int(alpha * a))
            p.setPen(QPen(col, 0.6 if self.kind != "mat" else 1.2))
            for x0, y0, x1, y1 in self.lines[:n]:
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            if self.kind in ("sheet", "mat") and self.progress > 0.5:
                g = QRadialGradient(QPointF(*self.hub()), self.r)
                tone = (30, 32, 40) if dark else (240, 240, 245)
                g.setColorAt(0, QColor(*tone, int(55 * a * self.progress)))
                g.setColorAt(1, QColor(*tone, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawEllipse(QPointF(*self.hub()), self.r, self.r)


class EggSac:
    def __init__(self, mother, x, y, hatch_at):
        self.base = mother.base_sp
        self.mother = mother
        self.x, self.y = x, y
        self.hatch_at = hatch_at
        self.carried = mother.sp["name"] in ("wolf_spider", "cellar_spider", "spitting_spider")
        name = mother.sp["name"]
        self.r = max(3.0, mother.s * 0.7)
        self.style = ("tan" if name == "black_widow" else
                      "urn" if name == "wasp_spider" else
                      "fluff" if name == "golden_orb" else "white")
        self.gone = False

    def draw(self, p):
        if self.carried:
            return
        r = self.r
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(QPointF(self.x + r * 0.5, self.y + r * 0.7), r, r)
        cols = {"tan": ("#e8d8b0", "#a88a5a"), "urn": ("#c8a070", "#6a4a28"),
                "fluff": ("#f8ec90", "#c8a830"), "white": ("#ffffff", "#c8c0b0")}[self.style]
        g = QRadialGradient(QPointF(self.x - r * 0.3, self.y - r * 0.3), r * 1.3)
        g.setColorAt(0, QColor(cols[0]))
        g.setColorAt(1, QColor(cols[1]))
        p.setBrush(g)
        if self.style == "urn":
            p.drawEllipse(QPointF(self.x, self.y), r * 0.8, r * 1.2)
        else:
            p.drawEllipse(QPointF(self.x, self.y), r, r)
        if self.style == "fluff":
            p.setPen(QPen(QColor(248, 236, 140, 140), 0.6))
            for k in range(10):
                a = k * math.tau / 10
                p.drawLine(QPointF(self.x + math.cos(a) * r, self.y + math.sin(a) * r),
                           QPointF(self.x + math.cos(a) * r * 1.5, self.y + math.sin(a) * r * 1.5))


class Fight:
    """Two spiders locked together; resolved when the clock runs out."""

    def __init__(self, a, b, kind, p_success, secs):
        self.a, self.b, self.kind = a, b, kind
        self.p = p_success
        self.end = time.monotonic() + secs
        self.mx, self.my = (a.x + b.x) / 2, (a.y + b.y) / 2
        self.phase = math.atan2(b.y - a.y, b.x - a.x)
        for o in (a, b):
            o.state = "grapple"
            o.special = None
            o.struggle = 1.3
            o.caught_k = 0.9
            o.z = 0.0
            o.target = None


def _ratio(a, b):
    return (a.s / max(0.5, b.s)) ** 3                     # mass ~ length³


INSECT_KINDS = {
    "fly":      dict(s=3.2, body="#2a2a2e", wing=(215, 222, 235), speed=3.0, land=0.006, eye="#a02020"),
    "fruitfly": dict(s=1.9, body="#c08a4a", wing=(230, 230, 236), speed=1.3, land=0.01, eye="#c02020"),
    "moth":     dict(s=4.6, body="#8a7258", wing=(168, 148, 118), speed=2.0, land=0.004, eye="#202020"),
    "bee":      dict(s=3.6, body="#e0b020", wing=(228, 230, 240), speed=2.8, land=0.0, eye="#202020"),
}


class Insect:
    """Prey that drifts into the box: buzzes about, lands, blunders into webs."""

    def __init__(self, kind, sw, sh):
        self.kind = kind
        k = self.k = INSECT_KINDS[kind]
        self.s = k["s"] * random.uniform(0.85, 1.15)
        self.sw, self.sh = sw, sh
        edge = random.randint(0, 3)
        self.x, self.y = ((random.uniform(0, sw), -20), (random.uniform(0, sw), sh + 20),
                          (-20, random.uniform(0, sh)), (sw + 20, random.uniform(0, sh)))[edge]
        self.z = random.uniform(25, 45)
        self.heading = math.atan2(sh / 2 - self.y, sw / 2 - self.x)
        self.speed = k["speed"]
        self.state = "fly"
        self.timer = 0
        self.life = random.randint(60 * 40, 60 * 120)
        self.phase = random.uniform(0, 6.28)
        self.gone = self.hidden = False
        self.wrap = 0.0
        self.web = None
        self.hunted = None
        self.stuck_t = 0
        self.angle = self.heading
        self.goal = None

    def stuck(self, secs=30):
        self.state = "stuck"
        self.stuck_t = int(secs * 60)
        self.z = 0.0

    def update(self):
        self.phase += 0.9
        st = self.state
        if st in ("caught", "dead"):
            return
        if st == "stuck":
            self.stuck_t -= 1
            self.angle += math.sin(self.phase * 0.7) * 0.1
            if self.stuck_t <= 0:
                if random.random() < 0.5:     # tore free
                    self.state, self.web, self.z = "fly", None, 20.0
                else:
                    self.stuck_t = 600
            return
        self.life -= 1
        if st == "land":
            self.timer -= 1
            self.z *= 0.8
            if self.timer % 90 < 40:          # little walks between grooming bouts
                self.x += math.cos(self.angle) * 0.25
                self.y += math.sin(self.angle) * 0.25
            if self.timer <= 0:
                self.state, self.z = "fly", 6.0
            return
        # flight: wander between random points; moths circle the cursor at night
        cx, cy = WORLD.cursor
        if self.kind == "moth" and WORLD.night > 0.5 and math.hypot(cx - self.x, cy - self.y) < 500:
            a = math.atan2(self.y - cy, self.x - cx) + 0.5
            self.goal = (cx + math.cos(a) * 45, cy + math.sin(a) * 45)
        elif self.life <= 0:
            self.goal = (self.x + math.cos(self.heading) * 900, self.y + math.sin(self.heading) * 900)
        elif self.goal is None or math.hypot(self.goal[0] - self.x, self.goal[1] - self.y) < 20:
            self.goal = (random.uniform(60, self.sw - 60), random.uniform(60, self.sh - 60))
        want = math.atan2(self.goal[1] - self.y, self.goal[0] - self.x)
        jitter = 0.5 if self.kind in ("fly", "fruitfly") else 0.25
        self.heading += _wrap_angle(want - self.heading) * 0.08 + random.gauss(0, jitter)
        self.x += math.cos(self.heading) * self.speed
        self.y += math.sin(self.heading) * self.speed
        self.z += (35 - self.z) * 0.05 + math.sin(self.phase * 0.1) * 0.5
        self.angle = self.heading
        if self.life <= 0 and not (-60 < self.x < self.sw + 60 and -60 < self.y < self.sh + 60):
            self.gone = True
        if self.k["land"] and random.random() < self.k["land"] and self.life > 0:
            self.state, self.timer = "land", random.randint(120, 420)


def draw_insect(p, b, shadow):
    k = b.k
    s = b.s
    if shadow:
        if b.state == "caught":
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int(70 * max(0.25, 1 - b.z / 60))))
        p.drawEllipse(QPointF(b.x + b.z * SX + 1, b.y + b.z * SY + 1), s * 1.1, s * 0.7)
        return
    p.save()
    p.translate(b.x, b.y)
    p.rotate(math.degrees(b.angle))
    sc = 1 + b.z * 0.01
    p.scale(sc, sc)
    flying = b.state in ("fly", "stuck")
    flap = abs(math.sin(b.phase)) if flying else 0.15
    wc = QColor(*k["wing"], 110 if b.kind != "moth" else 220)
    p.setPen(QPen(QColor(40, 40, 50, 90), 0.4))
    p.setBrush(wc)
    for side in (-1, 1):                      # wings: a blur when flying
        if b.kind == "moth":
            p.drawPolygon(QPolygonF([QPointF(s * 0.3, 0),
                                     QPointF(-s * 0.9, side * s * (1.7 - flap * 0.6)),
                                     QPointF(-s * 1.3, side * s * 0.4)]))
        else:
            p.drawEllipse(QPointF(-s * 0.35, side * s * (0.55 + 0.35 * flap)), s * 0.9, s * 0.42)
    if b.state in ("land", "stuck"):          # six little legs
        p.setPen(QPen(QColor(k["body"]).darker(150), 0.5))
        for side in (-1, 1):
            for dx in (0.4, 0.0, -0.4):
                p.drawLine(QPointF(s * dx, 0), QPointF(s * (dx + 0.2), side * s * 0.9))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(k["body"]))
    p.drawEllipse(QPointF(-s * 0.2, 0), s * 0.75, s * 0.42)
    p.drawEllipse(QPointF(s * 0.5, 0), s * 0.32, s * 0.32)
    if b.kind == "bee":
        p.setBrush(QColor("#1a1a1a"))
        for dx in (-0.5, -0.15):
            p.drawRect(QRectF(s * dx, -s * 0.38, s * 0.14, s * 0.76))
    p.setBrush(QColor(k["eye"]))
    for side in (-1, 1):
        p.drawEllipse(QPointF(s * 0.62, side * s * 0.2), s * 0.13, s * 0.13)
    if b.wrap > 0.02:                         # wrapped in silk
        p.setBrush(QColor(246, 246, 250, int(220 * b.wrap)))
        p.drawEllipse(QPointF(0, 0), s * 1.1, s * 0.7)
    p.restore()


class Ecology:

    def __init__(self, world):
        self.world = world
        self.webs = []
        self.sacs = []
        self.fights = []
        self.pending = []
        self.seen = {}
        self.last = time.monotonic()
        self.stats = {"kills": 0, "matings": 0, "cannibal": 0, "sacs": 0, "hatched": 0,
                      "molts": 0, "ballooned": 0, "webs": 0, "insects": 0, "deaths": 0,
                      "thefts": 0}
        self.insects = WORLD.insects
        self.insect_clock = 0.0
        self.gather_clock = 0.0

    def log(self, text, kind="info"):
        if WORLD.log:
            WORLD.log(text, kind)

    def spiders(self):
        return [b for b in self.world.butterflies if isinstance(b, Spider)]

    # ── helpers ──

    def _det(self, a):
        return max(a.R * 1.4, a.eco["det"] * PX_PER_CM * (0.5 + 0.5 * min(1.0, a.scale)))

    def _attack_score(self, a, b, same):
        e, f = a.eco, b.eco
        R = _ratio(a, b)
        tactic = (a.sp["name"] in ("cellar_spider", "spitting_spider") and
                  (b.state in ("hub", "build", "stuck") or b.web is not None))
        Rf = R * 2 if tactic else R
        fR = 1 / (1 + math.exp(-3 * (Rf - 1.3)))
        drive = e["cann"] * (1 - e["tol"]) if same else e["ara"]
        score = e["agg"] * fR * (0.3 + drive) * a.hunger * (1 - 0.5 * f["dfn"])
        score *= PREY_MULT.get(b.sp["name"], 1.0)
        if a.web is not None and a.web.contains(b.x, b.y):
            score *= 1.5
        if b.state in ("molt", "stuck", "feed"):
            score *= 1.6
        if a.scale < 0.6:
            score *= 0.3
        if _ratio(b, a) < 0.1:
            score *= 0.15                     # prey under 1/10 own mass is mostly ignored
        return score * ECO_K

    def _p_success(self, a, b):
        R = _ratio(a, b)
        p = 0.5 + 0.35 * math.tanh(1.5 * math.log(max(1e-3, R))) + 0.25 * (a.eco["fight"] - b.eco["fight"])
        if a.state == "hub" or a.eco["act"] == "SW":
            p += 0.1
        if b.state == "stuck":
            p += 0.25
        if time.monotonic() < b.soft_until or b.state == "molt":
            p = max(p, 0.9)
        return max(0.05, min(0.95, p))

    def _alarm(self, victim, pred):
        """The victim notices a predator coming: flee, freeze or defend."""
        if victim.state not in FREE or victim.interaction is not None:
            return
        d = math.hypot(victim.x - pred.x, victim.y - pred.y)
        if d > self._det(victim):
            return
        victim.danger = (pred.x, pred.y)
        r = random.random()
        defend = victim.sp["threat"] not in ("flee", "jumper")
        if defend and r < 0.55:
            victim.mouse = (pred.x, pred.y)
            victim.cool = 0
            victim._react(pred.x, pred.y, victim.react_r * 0.3, True,
                          math.atan2(pred.y - victim.y, pred.x - victim.x), forced=True)
        elif r < 0.75 or victim.sp["threat"] == "jumper":
            if victim.sp["gait"] == "jumper":
                victim._start_hop(math.atan2(victim.y - pred.y, victim.x - pred.x),
                                  victim.s * random.uniform(8, 12))
            else:
                victim._start_flee(pred.x, pred.y)
        else:
            victim._start_pause(60, 200)      # freeze and hope

    # ── homes & webs ──

    def _site(self, o):
        kind = o.eco["web"]
        sw, sh = o.sw, o.sh
        if kind == "orb":
            r = o.s * {"golden_orb": 9, "spiny_orb": 4.5}.get(o.sp["name"], 7) / max(0.5, o.scale ** 0.5)
            r = min(r, 170)
        elif kind == "tangle":
            r = 170 if o.base_sp["name"] == "social_spider" else max(o.R * 1.6, 50)
        elif kind == "sheet":
            r = max(o.R * 1.8, 60)
        else:
            r = max(o.R * 0.9, 30)
        pad = 0 if kind in ("orb", "tangle", "sheet") else o.R + 15
        cands = []
        for ex, ey in ((0, 0), (sw, 0), (0, sh), (sw, sh)):
            sx, sy = (1 if ex == 0 else -1), (1 if ey == 0 else -1)
            inset = r + 25 if kind == "orb" else max(r * 0.55, pad)
            score = 2.0
            if o.eco["site"] == "corner_high" and ey == 0:
                score += 1.5
            if o.eco["site"] == "corner_low" and ey == sh:
                score += 1.5
            cands.append((score, ex + sx * inset, ey + sy * inset, (ex, ey)))
        step = 230
        for x in range(step, int(sw) - step + 1, step):
            for ey, sy in ((0, 1), (sh, -1)):
                inset = r + 20 if kind == "orb" else max(r * 0.55, pad)
                cands.append((1.0, x, ey + sy * inset, (x, ey)))
        for y in range(step, int(sh) - step + 1, step):
            for ex, sx in ((0, 1), (sw, -1)):
                inset = r + 20 if kind == "orb" else max(r * 0.55, pad)
                cands.append((1.0, ex + sx * inset, y, (ex, y)))
        for wid, rect in WORLD.windows:        # the angle where a window meets the desktop
            if kind not in ("orb", "tangle", "sheet"):
                break
            for ex, ey, sx, sy in ((rect.left(), rect.top(), -1, -1), (rect.right(), rect.top(), 1, -1),
                                   (rect.left(), rect.bottom(), -1, 1), (rect.right(), rect.bottom(), 1, 1)):
                inset = r + 15 if kind == "orb" else r * 0.55
                cx, cy = ex + sx * inset, ey + sy * inset
                if r < cx < sw - r and r < cy < sh - r:
                    cands.append((2.2, cx, cy, (ex, ey), (wid, QRectF(rect))))
        cands = [c if len(c) == 5 else c + (None,) for c in cands]
        best = None
        for score, cx, cy, anchor, win in cands:
            ok = True
            for w in self.webs:
                d = math.hypot(w.cx - cx, w.cy - cy)
                same = w.species == o.sp["name"] and o.eco["tol"] >= 0.5
                if same and d < (r + w.r) * 2.5:
                    score += 1.5              # cellar spiders & golden orbs cluster
                elif d < (r + w.r) * 0.95:
                    if w.owner is None and w.kind == kind and d < 20:
                        score += 2.5          # take over an abandoned web
                    else:
                        ok = False
                        break
            if ok:
                score += random.uniform(0, 0.8)
                if best is None or score > best[0]:
                    best = (score, cx, cy, anchor, win)
        if best is None:
            return None
        self._site_win = best[4]
        return best[1], best[2], r, best[3]

    def _settle(self, o):
        kind = o.eco["web"]
        if o.colony is not None and o.colony["web"] is not None:
            self._join_colony(o, o.colony)
            return
        if kind in ("none", "burrow") and o.eco["act"] != "SW":
            return                            # wanderers keep no home
        site = self._site(o)
        if site is None:
            return
        cx, cy, r, anchor = site
        if kind in ("none", "burrow"):
            o.home = (cx, cy)
            o._goto(cx, cy, lambda: o._set("hub", 99999))
            return
        old = next((w for w in self.webs if w.owner is None and w.kind == kind
                    and math.hypot(w.cx - cx, w.cy - cy) < 20), None)
        if old is not None:
            w = old
            w.owner = o
        else:
            w = Web(o, kind, cx, cy, r, anchor)
            w.win = getattr(self, "_site_win", None)
            self.webs.append(w)
            self.stats["webs"] += 1
            if o.colony is not None:
                o.colony["web"] = w
                w.colony = o.colony
                self.log("the social spiders began a communal web", "web")
        o.web = w
        o.home = w.hub()

        def arrive():
            o._set("build", 99999)
        o._goto(*w.hub(), arrive)

    # ── per-tick ──

    def step(self):
        now = time.monotonic()
        dt = max(0.0, min(0.25, now - self.last))
        self.last = now
        everyone = self.spiders()
        live = [o for o in everyone if o.state not in DEADISH and not o.gone]

        for o in everyone:
            if o.state == "husk" and now > o.husk_until:
                o.gone = True
            if o.state == "stuck" and now > o.eco_until:
                o.struggle = 0.0
                o.plant_all()
                o._start_flee(*(o.danger or (o.x + 1, o.y)))

        for o in live:
            self._life(o, now, dt)

        due = [fn for t, fn in self.pending if t <= now]
        self.pending = [(t, fn) for t, fn in self.pending if t > now]
        for fn in due:
            fn()

        self._insects(live, now, dt)
        self._cursor(live, now, dt)
        self._klepto(live, now)
        self._webs(live, dt)
        self._sacs(now)
        self._fights(now)
        self._feeding(now)
        self._encounters(live, now)

    def _life(self, o, now, dt):
        tarantula = o.sp["name"] in ("redknee_tarantula", "goliath_birdeater", "gooty_sapphire")
        cold = 0.5 if WORLD.season == "winter" else 1.0
        o.hunger = min(1.0, o.hunger + cold * dt / (60 * (120 if tarantula else 20)))
        free = o.state in FREE and o.interaction is None and o.state != "special"

        # growing old and dying
        o.age_s += dt
        if (o.age_s > o.lifespan_s and o.state not in ("grapple", "mate") and o.interaction is None
                and o.state not in ("descend", "land", "hop", "fall", "roll", "balloon")):
            self._die(o, now)
            return

        # juveniles molt and grow
        if o.scale < 1.0 and now > o.next_molt and free:
            o.state = "molt"
            o.eco_until = now + 20
            o.next_molt = now + 1e9
        if o.state == "molt" and now > o.eco_until:
            self._molt(o)
            return

        # settle into a home / web
        if (o.home is None and o.scale >= 0.6 and now > o.settle_at and free
                and o.state not in ("goto", "hub")):
            self._settle(o)
            o.settle_at = now + 60

        # web owners: build progress, repairs, staying put
        w = o.web
        if w is not None:
            if w.owner is not o:
                o.web = None
            elif o.state == "build":
                fresh = w.progress < 1.0
                w.progress = min(1.0, w.progress + dt / random.uniform(55, 75))
                w.integrity = min(1.0, w.integrity + dt / 60)
                if fresh and w.progress >= 1.0:
                    kind = {"orb": "an orb web", "tangle": "a cobweb", "sheet": "a funnel web",
                            "mat": "a silk retreat"}[w.kind]
                    self.log(f"{o.name} the {common_name(o.sp['name'])} finished {kind}", "web")
                if w.progress >= 1.0 and w.integrity >= 0.95:
                    o._goto(*w.hub(), lambda: o._set("hub", 99999))
            elif o.state == "hub" and w.integrity < 0.55:
                o._set("build", 99999)
            elif o.state in ("walk", "pause", "turn") and o.hunger < 0.8:
                o._goto(*w.hub(), lambda: o._set("hub", 99999))

        # home-bound ambushers / tarantulas: wander when hungry, then go home
        if o.home is not None and o.web is None:
            if o.state == "hub" and o.hunger > 0.55 and random.random() < dt / 30:
                o._start_walk()
                o.home_return_at = now + random.uniform(40, 120)
            elif o.state in ("walk", "pause", "turn") and now > o.home_return_at:
                o._goto(*o.home, lambda: o._set("hub", 99999))

        # gravid females lay an egg sac
        if o.gravid_at and now > o.gravid_at and free:
            o.gravid_at = None
            o.state = "spin"
            o.eco_until = now + 25
        if o.state == "spin" and now > o.eco_until:
            self._lay(o, now)

        # adult males go looking for females of their kind
        drive = {"spring": 2.5, "summer": 1.0, "autumn": 0.5, "winter": 0.0}[WORLD.season]
        if (o.sex == "m" and o.scale >= 1 and free and now > o.mated_until
                and o.state not in ("seek", "hub", "goto") and random.random() < drive * dt / 25):
            mates = [f for f in self.spiders() if f.sex == "f" and f.scale >= 1
                     and f.base_sp is o.base_sp and f.state not in DEADISH
                     and not f.gravid_at and not f.hidden]
            if mates:
                o.target = min(mates, key=lambda f: math.hypot(f.x - o.x, f.y - o.y))
                o._set("seek", 60 * 60)

        # spiderling clusters break up and disperse
        if o.state == "ball" and now > o.eco_until:
            o.ball_c = None
            kin = sum(1 for b in self.spiders() if b.base_sp is o.base_sp
                      and b.state not in DEADISH and b.state != "ball" and b is not o)
            social = o.base_sp["name"] == "social_spider"
            p_bal = 0.8 if WORLD.season == "autumn" else 0.55
            if social and o.colony is not None and len(o.colony["members"]) < SOCIAL_CAP:
                self._join_colony(o, o.colony)
            elif kin >= MAX_PER_SPECIES or random.random() < p_bal:
                # ballooning: climb to an edge, let out silk, drift off
                ex = 0 if o.x < o.sw / 2 else o.sw
                tx = ex + (40 if ex == 0 else -40)
                o._goto(tx, max(30, o.y - 200), lambda: self._balloon(o))
            else:
                o._start_walk()

        # wrong time of day: homeless wanderers tuck away under a window or the screen edge
        if (free and o.home is None and o.web is None and not o.active() and o.scale >= 0.6
                and o.state in ("walk", "pause") and random.random() < dt / 40):
            self._hide(o, random.uniform(40, 120))

    def _die(self, o, now):
        self.stats["deaths"] += 1
        o.state = "husk"
        o.husk_until = now + 360
        o._tuck(0.4)                          # legs curl in under the body
        o.target = o.prey = o.partner = None
        o.carry_sac = False
        if o.web is not None and o.web.owner is o:
            o.web.owner = None
        if o.colony is not None:
            o.colony["members"].discard(o)
        self.log(f"{o.name} the {common_name(o.sp['name'])} died of old age "
                 f"({o.kills} kills, {o.children} young)", "death")

    def _hide(self, o, secs):
        """Slip under the nearest window edge, or half off the screen edge."""
        best = None
        for r in WORLD.hides:
            cx = min(max(o.x, r.left()), r.right())
            cy = min(max(o.y, r.top()), r.bottom())
            d = math.hypot(cx - o.x, cy - o.y)
            if d < 450 and (best is None or d < best[0]):
                # aim just inside the window edge so the spider looks tucked under it
                ix = cx + (o.R * 0.6 if cx == r.left() else -o.R * 0.6 if cx == r.right() else 0)
                iy = cy + (o.R * 0.6 if cy == r.top() else -o.R * 0.6 if cy == r.bottom() else 0)
                best = (d, ix, iy, r)
        if best is None:
            ds = [(o.x, -o.R * 0.5, o.y), (o.sw - o.x, o.sw + o.R * 0.5, o.y),
                  (o.y, o.x, -o.R * 0.5), (o.sh - o.y, o.x, o.sh + o.R * 0.5)]
            d, tx, ty = min(ds)
            if d > 450:
                return
            rect = None
        else:
            _, tx, ty, rect = best

        def tuck():
            o.hide_rect = rect if rect is not None else QRectF(-1e5, -1e5, 1, 1)
            o._set("hide", int(secs * 60))
        # off-screen hides need the clamp lifted while walking there
        o.hide_rect = rect if rect is not None else QRectF(-1e5, -1e5, 1, 1)
        o._goto(tx, ty, tuck)

    def _join_colony(self, o, col):
        col["members"].add(o)
        o.colony = col
        w = col["web"]
        if w is None:
            return
        o.web = w
        a = random.uniform(0, math.tau)
        rr = w.r * random.uniform(0.15, 0.6)
        o.home = (w.cx + math.cos(a) * rr, w.cy + math.sin(a) * rr)
        o._goto(*o.home, lambda: o._set("hub", 99999))

    def _balloon(self, o):
        o.state = "balloon"
        o.thread = [o.x, 0, 0, 1.0, True]
        o.thread[0] = o.x
        self.stats["ballooned"] += 1

    def _molt(self, o):
        """Leave the old skin behind and come out bigger."""
        self.stats["molts"] += 1
        skin = copy.copy(o)
        skin.legs = [copy.copy(L) for L in o.legs]
        skin.state, skin.exuvia = "husk", True
        skin.husk_until = time.monotonic() + 180
        skin.target = skin.prey = skin.web = None
        skin.fx_spit, skin.fx_particles = [], []
        new = Spider(o.base_sp, o.sw, o.sh, sex=o.sex, scale=min(1.0, o.scale + 0.22))
        new.x, new.y, new.angle = o.x + math.cos(o.angle) * o.s, o.y + math.sin(o.angle) * o.s, o.angle
        new.hunger = o.hunger
        for k in ("uid", "name", "gen", "mother_uid", "kills", "children", "meals",
                  "age_s", "lifespan_s", "colony", "home"):
            setattr(new, k, getattr(o, k))
        if o.colony is not None:
            o.colony["members"].discard(o)
            o.colony["members"].add(new)
            new.web = o.colony["web"]
        if new.scale >= 1:
            self.log(f"{o.name} the {common_name(o.sp['name'])} molted into an adult "
                     f"{'female' if o.sex == 'f' else 'male'}", "molt")
        new.immune_until = 0
        new.settle_at = time.monotonic() + 20
        new.soft_until = time.monotonic() + 60
        new.plant_all()
        new._start_pause(60, 120)
        lst = self.world.butterflies
        lst[lst.index(o)] = skin
        lst.append(new)
        o.gone = True
        skin.gone = False

    def _lay(self, o, now):
        self.stats["sacs"] += 1
        hatch = now + random.uniform(300, 480)
        x, y = o._spinneret()
        sac = EggSac(o, x, y, hatch)
        self.sacs.append(sac)
        name = o.sp["name"]
        if name == "wolf_spider":
            o.variant = "eggsac"              # dragged on the spinnerets
        elif sac.carried:
            o.carry_sac = True                # held in the chelicerae
        if o.home is None:
            o.home = (x, y)
        o._start_pause(120, 300)
        self.log(f"{o.name} the {common_name(name)} laid an egg sac", "egg")
        if WORLD.season == "autumn" and LIFESPAN_YEARS.get(o.base_sp["name"], 1) <= 1:
            o.lifespan_s = min(o.lifespan_s, o.age_s + random.uniform(300, 600))

    def _sacs(self, now):
        for sac in self.sacs:
            m = sac.mother
            if sac.carried:
                if m.gone or m.state in DEADISH:
                    sac.carried = False       # dropped when the mother dies
                    m.carry_sac = False
                else:
                    sac.x, sac.y = m._spinneret()
            if now > sac.hatch_at and not sac.gone:
                sac.gone = True
                self._hatch(sac, now)
        self.sacs = [s for s in self.sacs if not s.gone]

    def _hatch(self, sac, now):
        m = sac.mother
        if sac.carried:
            m.carry_sac = False
            if m.sp["name"] == "wolf_spider":
                m.variant = None
        juv = sum(1 for o in self.spiders() if o.scale < 1 and o.state not in DEADISH)
        n = max(0, min(random.randint(8, 14), MAX_JUV - juv))
        self.stats["hatched"] += n
        m.children += n
        if n:
            self.log(f"{n} spiderlings hatched from {m.name}'s egg sac", "hatch")
        for _ in range(n):
            o = Spider(sac.base, m.sw, m.sh, scale=0.32)
            o.x = sac.x + random.uniform(-8, 8)
            o.y = sac.y + random.uniform(-8, 8)
            o.angle = random.uniform(0, math.tau)
            o.plant_all()
            o.state = "ball"
            o.ball_c = (sac.x, sac.y)
            o.eco_until = now + random.uniform(60, 120)
            o.immune_until = now + 20
            o.next_molt = now + random.uniform(150, 300)
            o.mother_uid, o.gen = m.uid, m.gen + 1
            o.colony = m.colony
            self.world.butterflies.append(o)

    def _webs(self, live, dt):
        wins = dict(WORLD.windows)
        for w in self.webs:
            win = getattr(w, "win", None)
            if win is not None and w.integrity > 0:
                wid, rect = win
                now_rect = wins.get(wid)
                if now_rect is None or (abs(now_rect.x() - rect.x()) + abs(now_rect.y() - rect.y())
                                        + abs(now_rect.width() - rect.width())) > 12:
                    w.integrity = 0.0          # the window moved: silk snaps
                    w.win = None
                    o = w.owner
                    if o is not None:
                        o.web, o.home = None, None
                        o.settle_at = time.monotonic() + random.uniform(10, 30)
                        o._start_flee(o.x + 1, o.y)
                        self.log(f"a window moved and tore {o.name}'s web — "
                                 f"the {common_name(o.sp['name'])} runs for cover", "web")
            if w.owner is not None and (w.owner.gone or w.owner.state in DEADISH):
                w.owner = None
                col = getattr(w, "colony", None)
                heirs = [m for m in (col["members"] if col else ()) if m.state not in DEADISH]
                if heirs:
                    w.owner = heirs[0]
            if w.owner is None:
                w.integrity -= dt / 900       # abandoned webs slowly fall apart
            for o in live:                    # big walkers tear through silk
                if (o is not w.owner and o.speed > 0.6 and w.progress > 0.5
                        and w.contains(o.x, o.y) and o.s > (w.owner.s * 0.8 if w.owner else 6)):
                    w.integrity = max(0.0, w.integrity - dt * 0.05)
        self.webs = [w for w in self.webs if w.integrity > 0]

    def _fights(self, now):
        keep = []
        for f in self.fights:
            a, b = f.a, f.b
            broken = (a.interaction is not None or b.interaction is not None
                      or a.gone or b.gone)
            if broken:
                for o in (a, b):
                    if o.state == "grapple":
                        o.plant_all()
                        o._start_flee(o.x - 1, o.y)
                continue
            # tumbling together around a shared centre
            f.phase += random.uniform(-0.08, 0.12)
            sep = (a.s + b.s) * 0.9
            ca, sa = math.cos(f.phase), math.sin(f.phase)
            jit = math.sin(now * 23) * 1.2
            a.x, a.y = f.mx - ca * sep / 2 + jit, f.my - sa * sep / 2
            b.x, b.y = f.mx + ca * sep / 2 - jit, f.my + sa * sep / 2
            a.angle = f.phase + random.uniform(-0.15, 0.15)
            b.angle = f.phase + math.pi + random.uniform(-0.15, 0.15)
            if now < f.end:
                keep.append(f)
                continue
            self._resolve(f)
        self.fights = keep

    def _resolve(self, f):
        a, b = f.a, f.b
        if f.kind == "contest":               # male-male: loser backs off
            win = random.random() < f.p
            loser, winner = (b, a) if win else (a, b)
            for o in (a, b):
                o.plant_all()
            winner._start_pause(60, 160)
            loser._start_flee(winner.x, winner.y)
            return
        if random.random() < f.p:
            self._kill(a, b, f.kind)
        elif random.random() < 0.6 or f.kind == "sexual":
            for o in (a, b):
                o.plant_all()
            b._start_flee(a.x, a.y)
            a._start_pause(60, 160)
        else:                                 # counter-attack
            self.fights.append(Fight(b, a, "kill", self._p_success(b, a), random.uniform(1.5, 3)))

    def _kill(self, a, b, kind):
        self.stats["kills"] += 1
        a.kills += 1
        a.meals += 1
        if kind == "sexual" or a.base_sp is b.base_sp:
            self.stats["cannibal"] += 1
        an, bn = common_name(a.sp["name"]), common_name(b.sp["name"])
        if kind == "sexual":
            self.log(f"{a.name} the {an} ate her mate {b.name}", "cannibal")
        elif b.scale < 0.6:
            self.log(f"{a.name} the {an} ate a young {bn}", "kill")
        else:
            self.log(f"{a.name} the {an} killed and ate {b.name} the {bn}", "kill")
        if b.colony is not None:
            b.colony["members"].discard(b)
        b.state = "dead"
        b.struggle = 0.6
        b.caught_k = 0.45                     # legs curl in death
        b.target = b.prey = b.partner = None
        b.carry_sac = False
        a.prey = b
        a.state = "feed"
        a.plant_all()
        ratio = min(1.0, _ratio(b, a))
        a.eco_until = time.monotonic() + 50 * (1 + 3 * ratio) ** 0.5
        a.hunger = max(0.0, a.hunger - 0.35 - ratio)
        b.wrap = 0.0

    def _feeding(self, now):
        for o in self.spiders():
            c = o.prey
            if c is None:
                continue
            bug = isinstance(c, Insect)
            if o.state in DEADISH or o.gone or o.interaction is not None or c.gone:
                if bug:
                    c.gone = True
                elif c.state == "dead":
                    c.state = "husk"
                    c.husk_until = now + 360
                o.prey = None
                continue
            cx, rx, _ = o.sp["ceph"]
            d = (cx + rx + 0.2) * o.s + c.s * 0.8
            c.x = o.x + math.cos(o.angle) * d
            c.y = o.y + math.sin(o.angle) * d
            c.z = 0.0
            if o.wrap_needed() and c.wrap < 1.0:
                c.wrap = min(1.0, c.wrap + 1 / (60 * 18))
            if o.state == "feed" and now > o.eco_until and bug:
                c.gone = True
                o.prey = None
                if o.web is not None:
                    o._goto(*(o.home or o.web.hub()), lambda o=o: o._set("hub", 99999))
                else:
                    o._start_pause(60, 200)
                continue
            if o.state == "feed" and now > o.eco_until:
                if o.web is not None and math.hypot(o.x - o.web.cx, o.y - o.web.cy) > 30:
                    c.state = "husk"          # orb weavers cut the husk loose
                    c.husk_until = now + 360
                    o.prey = None
                    o._goto(*o.web.hub(), lambda o=o: o._set("hub", 99999))
                else:
                    c.state = "husk"
                    c.husk_until = now + 360
                    o.prey = None
                    if o.web is not None or o.home is not None:
                        o._set("hub", 99999)
                    else:
                        o._start_pause(120, 300)

    # ── insects ──

    def _insects(self, live, now, dt):
        sw, sh = getattr(self.world, "sw", 1920), getattr(self.world, "sh", 1080)
        # supply depends on the season and the time of day
        rate = {"spring": 2.0, "summer": 4.0, "autumn": 2.0, "winter": 0.4}[WORLD.season]
        self.insect_clock += dt * rate / 60
        if self.insect_clock >= 1 and len(self.insects) < 14:
            self.insect_clock = 0
            night = WORLD.night > 0.5
            flowers = any(o.base_sp["name"] == "flower_crab" for o in live)
            kinds = (["moth", "moth", "fruitfly"] if night else
                     ["fly", "fly", "fruitfly"] + (["bee", "bee"] if flowers else []))
            self.insects.append(Insect(random.choice(kinds), sw, sh))
        for b in self.insects:
            b.update()
        # blundering into webs
        for b in self.insects:
            if b.state != "fly":
                continue
            for w in self.webs:
                if (w.progress >= 1 and w.kind != "mat" and w.integrity > 0.3
                        and w.contains(b.x, b.y) and random.random() < 0.03):
                    b.stuck(random.uniform(25, 45))
                    b.web = w
                    w.integrity = max(0.0, w.integrity - 0.03)
                    self._vibration(w, b)
                    break
        # bees drawn to the flower crab's UV lure
        lures = [o for o in live if o.base_sp["name"] == "flower_crab" and o.state in ("hub", "pause")]
        for b in self.insects:
            if b.kind == "bee" and b.state == "fly" and lures:
                o = min(lures, key=lambda o: math.hypot(o.x - b.x, o.y - b.y))
                b.goal = (o.x, o.y)
                if math.hypot(o.x - b.x, o.y - b.y) < o.R * 0.6 + 4 and o.prey is None:
                    o._special("strike", "pause")
                    self._capture(o, b, f"{o.name} the Flower Crab lured in a bee and caught it")
        for o in live:
            if o.state != "special" or o.prey is not None:
                continue
            if o.special == "bolas":           # moths fluttering near the sticky globule
                for b in self.insects:
                    if b.kind == "moth" and b.state == "fly" and math.hypot(b.x - o.x, b.y - o.y) < 80:
                        self._capture(o, b, f"{o.name} the Bolas Spider snagged a moth with its bolas")
                        break
            elif o.special == "holdnet":       # walkers in front of the net
                for b in self.insects:
                    if b.state == "land" and math.hypot(b.x - o.x, b.y - o.y) < o.R * 1.6:
                        self._capture(o, b, f"{o.name} the Net Caster dropped its net on a {b.kind}")
                        break
        # hunters stalk insects that land nearby
        for b in self.insects:
            if b.state not in ("land", "stuck") or b.hunted is not None:
                continue
            for o in live:
                if (o.state in FREE and o.interaction is None and o.prey is None and o.active()
                        and o.web is None and o.hunger > 0.15
                        and math.hypot(o.x - b.x, o.y - b.y) < self._det(o)
                        and random.random() < o.eco["agg"] * o.hunger * 0.05):
                    o.target = b
                    b.hunted = o
                    o._set("hunt", 60 * 8)
                    break
        # contact: grab it
        for o in live:
            t = o.target
            if isinstance(t, Insect) and o.state == "hunt" and t.state in ("fly", "land", "stuck"):
                if math.hypot(t.x - o.x, t.y - o.y) < o.R * 0.45 + t.s + 4:
                    self._capture(o, t, None)
            elif isinstance(t, Insect) and o.state == "hunt" and t.gone:
                o.target = None
        self.insects[:] = [b for b in self.insects if not b.gone]

    def _vibration(self, w, b):
        """Prey thrashing in a web: the owner (or the whole colony) runs to it."""
        col = getattr(w, "colony", None)
        crew = [m for m in (col["members"] if col else ()) if m.state in FREE and m.prey is None]
        if col:
            crew = crew[:6]
        elif w.owner is not None and w.owner.state in FREE and w.owner.prey is None:
            crew = [w.owner]
        for m in crew:
            m.target = b
            m._set("hunt", 60 * 10)
        if col and len(crew) > 2:
            self.log(f"{len(crew)} social spiders swarm a {b.kind} together", "social")

    def _capture(self, o, b, msg):
        if b.state in ("caught", "dead") or b.gone:
            return
        b.state = "caught"
        b.z = 0.0
        o.target = None
        o.prey = b
        o.state = "feed"
        o.plant_all()
        o.eco_until = time.monotonic() + random.uniform(18, 35)
        o.hunger = max(0.0, o.hunger - 0.35)
        o.meals += 1
        self.stats["insects"] += 1
        col = o.colony
        if col:                                # the colony shares the meal
            for m in col["members"]:
                if m is not o and m.target is b:
                    m.target = None
                    m._start_pause(60, 200)
                    m.hunger = max(0.0, m.hunger - 0.2)
        if msg:
            self.log(msg, "insect")

    # ── kleptoparasites: dewdrop spiders raid other spiders' webs ──

    def _klepto(self, live, now):
        for d in live:
            if d.base_sp["name"] != "dewdrop_spider" or d.prey is not None:
                continue
            if d.state in FREE and random.random() < 0.01:
                hosts = [h for h in live if h.state == "feed" and isinstance(h.prey, Insect)
                         and h.web is not None and math.hypot(h.x - d.x, h.y - d.y) < 600]
                if hosts:
                    d.target = min(hosts, key=lambda h: math.hypot(h.x - d.x, h.y - d.y))
                    d._set("seek", 60 * 30)
            h = d.target
            if (d.state == "seek" and isinstance(h, Spider) and h.state == "feed"
                    and isinstance(h.prey, Insect)
                    and math.hypot(h.x - d.x, h.y - d.y) < (h.R + d.R) * 0.4 + 4):
                bug, h.prey = h.prey, None
                h._set("hub", 99999)
                d.target = None
                d.prey = bug
                d.state = "feed"
                d.eco_until = now + random.uniform(20, 30)
                self.stats["thefts"] += 1
                self.log(f"{d.name} the Dewdrop Spider stole a {bug.kind} from {h.name}'s web", "theft")
                if random.random() < 0.35:     # caught in the act
                    h.target = d
                    h._set("hunt", 60 * 5)

    # ── the cursor: a resting cursor draws the curious, a flick scatters everyone ──

    def _cursor(self, live, now, dt):
        cx, cy = WORLD.cursor
        if WORLD.flick > 45:
            for o in live:
                if o.state in FREE and math.hypot(o.x - cx, o.y - cy) < 300:
                    o.startle(cx, cy)
            WORLD.flick = 0
        self.gather_clock += dt
        if WORLD.cursor_still > 8 and self.gather_clock > 2:
            self.gather_clock = 0
            near = [o for o in live if math.hypot(o.x - cx, o.y - cy) < 120]
            if len(near) < 4:
                for o in live:
                    if (o.state in ("walk", "pause") and o.home is None and o.active()
                            and o.eco["act"] in ("AH", "W")
                            and 120 < math.hypot(o.x - cx, o.y - cy) < 420 and random.random() < 0.3):
                        a = random.uniform(0, math.tau)
                        rr = random.uniform(55, 95)
                        o._goto(cx + math.cos(a) * rr, cy + math.sin(a) * rr,
                                lambda o=o: o._start_pause(300, 700))
                        break

    # ── encounters ──

    def _encounters(self, live, now):
        n = len(live)
        for i in range(n):
            a = live[i]
            for j in range(i + 1, n):
                b = live[j]
                dx, dy = b.x - a.x, b.y - a.y
                d = math.hypot(dx, dy)
                # contact: hunters reach their prey, males reach females
                for x, y in ((a, b), (b, a)):
                    if x.target is y and d < (x.R + y.R) * 0.45 + 4:
                        if x.state in ("hunt",):
                            self.fights.append(Fight(x, y, "kill", self._p_success(x, y),
                                                     random.uniform(2.5, 6)))
                            x.target = None
                        elif x.state == "seek" and y.state not in ECO_BUSY - {"hub"}:
                            self._court(x, y, now)
                if d > max(self._det(a), self._det(b)) or a.state in DEADISH or b.state in DEADISH:
                    continue
                key = (id(a), id(b))
                if now - self.seen.get(key, -99) < 15:
                    continue
                self.seen[key] = now
                self._meet(a, b, d, now)
                self._meet(b, a, d, now)
        if len(self.seen) > 4000:
            self.seen = {k: v for k, v in self.seen.items() if now - v < 30}

    def _meet(self, a, b, d, now):
        """a has just noticed b."""
        if (a.state not in FREE or a.interaction is not None or now < a.immune_until
                or now < b.immune_until or b.state not in TARGETABLE or b.hidden):
            return
        if d > self._det(a) * (1 - CRYPTIC.get(b.sp["name"], 0.0)):
            if not (a.web is not None and a.web.contains(b.x, b.y)):
                return
        same = a.base_sp is b.base_sp
        if same and a.scale >= 1 and b.scale >= 1 and a.sex == b.sex == "m":
            if d < (a.R + b.R) * 1.5 and random.random() < 0.5:
                self._contest(a, b)
            return
        if same and a.sex != b.sex and a.scale >= 1 and b.scale >= 1:
            return                            # courtship is started by the male's search
        score = self._attack_score(a, b, same)
        col = a.colony
        if col and col["web"] is not None and col["web"].contains(b.x, b.y) and not same:
            mates = sum(1 for m in col["members"] if math.hypot(m.x - b.x, m.y - b.y) < 200)
            score *= 1 + mates                 # colonies drive intruders off together
        if random.random() < score:
            a.target = b
            a.side_walk = 0
            a._set("hunt", 60 * (8 if a.eco["act"] in ("AH", "W") else 3))
            self._alarm(b, a)
            return
        # otherwise: give way to anything big and dangerous, else ignore
        if _ratio(b, a) > 1.6 and b.eco["agg"] > 0.3 and d < self._det(a) * 0.7:
            self._alarm(a, b)

    def _contest(self, a, b):
        self.fights.append(Fight(a, b, "contest",
                                 0.5 + 0.4 * math.tanh(2 * math.log(max(1e-3, _ratio(a, b)))),
                                 random.uniform(1.5, 3)))

    def _court(self, m, f, now):
        m.target = None
        m.partner = f
        m._set("court", random.randint(360, 840))
        f._start_pause(900, 900)
        f.angle = math.atan2(m.y - f.y, m.x - f.x)
        self.world_after(m.timer_total / 60, lambda: self._court_end(m, f))

    def world_after(self, secs, fn):
        self.pending.append((time.monotonic() + secs, fn))

    def _court_end(self, m, f):
        if (m.state != "court" or f.state in DEADISH or m.gone or f.gone
                or m.interaction is not None or f.interaction is not None):
            m.partner = None
            if m.state == "court":
                m._start_pause()
            return
        if random.random() < f.eco["cann"] * f.hunger * 0.5:   # she attacks instead
            self.fights.append(Fight(f, m, "sexual", 0.85, random.uniform(1.5, 3)))
            return
        # mating: male mounts at her front, palps twitching
        m.state = "mate"
        m.struggle = 0.15
        m.caught_k = 0.9
        cx, rx, _ = f.sp["ceph"]
        d = (cx + rx) * f.s + m.s * 0.6
        m.x, m.y = f.x + math.cos(f.angle) * d, f.y + math.sin(f.angle) * d
        m.angle = f.angle + math.pi
        f._start_pause(900, 900)
        self.world_after(random.uniform(6, 12), lambda: self._mate_end(m, f))

    def _mate_end(self, m, f):
        if m.state != "mate" or f.state in DEADISH or m.gone or f.gone:
            if m.state == "mate":
                m.plant_all()
                m._start_pause()
            return
        self.stats["matings"] += 1
        self.log(f"{m.name} and {f.name} ({common_name(f.sp['name'])}s) mated", "mate")
        m.plant_all()
        f.gravid_at = time.monotonic() + random.uniform(240, 420)
        m.mated_until = time.monotonic() + 300
        p = f.eco["scann"] + 0.2 * f.hunger
        if random.random() < p:               # sexual cannibalism
            self.fights.append(Fight(f, m, "sexual", 0.9, random.uniform(1, 2)))
        else:
            m._start_flee(f.x, f.y)
            f._start_pause(60, 200)


def draw_eco_ground(p, eco):
    for w in eco.webs:
        w.draw(p)
    for s in eco.sacs:
        s.draw(p)


# ── Overlay ─────────────────────────────────────────────

class SpiderOverlay(ButterflyOverlay):

    def __init__(self):
        super().__init__()
        self.eco = Ecology(self)
        self.released = 0
        self.next_immigrant = 0.0
        self.spawn_timer.setInterval(SPAWN_INTERVAL_MS)

    def _tick(self):
        self.butterflies = [b for b in self.butterflies if not getattr(b, "gone", False)]
        super()._tick()
        self.eco.step()

    def _spawn(self):
        """Spiders are released one by one, then only immigrants top it up."""
        now = time.monotonic()
        elapsed = now - self.start_time
        adults = [b for b in self.butterflies if isinstance(b, Spider)
                  and b.scale >= 1 and b.state not in DEADISH]
        present = {b.sp["name"] for b in adults}
        if self.released >= INITIAL_COUNT:
            full = len(adults) >= CAP_ADULTS and len(present) >= MIN_SPECIES
            if now < self.next_immigrant or full or len(adults) >= CAP_ADULTS + 4:
                return
            self.next_immigrant = now + random.uniform(*IMMIGRATION_S)
        available = [sp for sp in SPECIES if elapsed >= RARITY_UNLOCK[sp["rarity"]]]
        weights = [RARITY_WEIGHT[sp["rarity"]] * (1 if sp["name"] in present else 3)
                   for sp in available]
        sp = Spider(random.choices(available, weights=weights, k=1)[0], self.sw, self.sh)
        sp.spawn()
        self.butterflies.append(sp)
        self.released += 1
        if self.released == INITIAL_COUNT:
            self.next_immigrant = now + random.uniform(*IMMIGRATION_S)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        spiders = sorted((b for b in self.butterflies if isinstance(b, Spider)),
                         key=lambda b: (b.state != "husk", b.z))  # husks under, airborne on top
        for b in spiders:
            b.pose()
        draw_eco_ground(p, self.eco)
        for b in spiders:
            if b.sp["ground"]:
                b.sp["ground"](p, b)
        for b in spiders:
            draw_shadow(p, b)
        for b in spiders:
            draw_spider(p, b)
        for b in spiders:
            draw_fx(p, b)
        p.end()


if __name__ == "__main__":
    import arachne                            # app entry: colony, journal, save & resume
    arachne.run_colony(fresh="--fresh" in sys.argv)
