
import sys
import math
import random
import time
import platform

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QPen,
    QBrush,
    QLinearGradient,
)


# =========================================================
# CONFIGURATION
# =========================================================

DURATION_SECONDS = 60
BUTTERFLY_COUNT = 45
FPS = 60

MIN_SIZE = 22
MAX_SIZE = 48

CLICK_THROUGH = True

MOUSE_REPEL_RADIUS = 150
MOUSE_REPEL_STRENGTH = 1.8

# Available butterfly colours
BUTTERFLY_COLORS = [
    QColor("#ff4f91"),  # Pink
    QColor("#a855f7"),  # Purple
    QColor("#20cfff"),  # Cyan
    QColor("#ffad32"),  # Orange
    QColor("#ff5267"),  # Red
    QColor("#eaff32"),  # Yellow
    QColor("#48edab"),  # Green
]


# =========================================================
# BUTTERFLY
# =========================================================

class Butterfly:

    def __init__(self, width, height):

        self.x = random.uniform(0, width)
        self.y = random.uniform(0, height)

        self.size = random.uniform(MIN_SIZE, MAX_SIZE)

        self.vx = random.uniform(-1.5, 1.5)
        self.vy = random.uniform(-1.5, 1.5)

        self.angle = random.uniform(0, 360)

        # Every butterfly has its own wing rhythm
        self.phase = random.uniform(0, math.tau)
        self.flap_speed = random.uniform(0.12, 0.22)

        self.color = QColor(random.choice(BUTTERFLY_COLORS))

        self.turn = random.uniform(-1, 1)

        self.wander_time = 0
        self.wander_angle = random.uniform(0, math.tau)

    # -----------------------------------------------------
    # NATURAL FLIGHT
    # -----------------------------------------------------

    def update(self, width, height, mouse_x, mouse_y):

        self.phase += self.flap_speed

        self.wander_time += 1

        # Smooth random wandering, rather than jittering
        if self.wander_time > random.randint(30, 100):

            self.wander_angle += random.uniform(-1.2, 1.2)
            self.wander_time = 0

        target_vx = math.cos(self.wander_angle) * 1.5
        target_vy = math.sin(self.wander_angle) * 1.2

        # Smooth acceleration
        self.vx += (target_vx - self.vx) * 0.015
        self.vy += (target_vy - self.vy) * 0.015

        # Gentle natural movement
        self.vx += random.uniform(-0.025, 0.025)
        self.vy += random.uniform(-0.025, 0.025)

        # Mouse interaction: flutter away from the cursor
        dx = self.x - mouse_x
        dy = self.y - mouse_y

        distance = math.hypot(dx, dy)

        if 1 < distance < MOUSE_REPEL_RADIUS:

            force = (
                1 - distance / MOUSE_REPEL_RADIUS
            ) * MOUSE_REPEL_STRENGTH

            self.vx += dx / distance * force * 0.08
            self.vy += dy / distance * force * 0.08

        # Limit speed
        speed = math.hypot(self.vx, self.vy)

        max_speed = 2.8

        if speed > max_speed:
            self.vx *= max_speed / speed
            self.vy *= max_speed / speed

        # Move
        self.x += self.vx
        self.y += self.vy

        # Turn in the direction of flight
        target_angle = math.degrees(
            math.atan2(self.vy, self.vx)
        )

        # Smoothly rotate toward the flight direction
        difference = (
            target_angle - self.angle + 180
        ) % 360 - 180

        self.angle += difference * 0.035

        # Wrap around edges
        margin = self.size * 2

        if self.x < -margin:
            self.x = width + margin

        elif self.x > width + margin:
            self.x = -margin

        if self.y < -margin:
            self.y = height + margin

        elif self.y > height + margin:
            self.y = -margin


# =========================================================
# BUTTERFLY DRAWING
# =========================================================

def make_wing_path(size, upper=True):

    """
    Make a curved wing with a rounded outer edge.

    The path starts at the butterfly body and travels
    outward, around the wing, and back to the body.
    """

    s = size

    path = QPainterPath()
    path.moveTo(0, 0)

    if upper:

        # Large upper wing
        path.cubicTo(
            -s * 0.15, -s * 0.42,
            -s * 0.65, -s * 1.00,
            -s * 1.15, -s * 0.83
        )

        path.cubicTo(
            -s * 1.55, -s * 0.68,
            -s * 1.48, -s * 0.10,
            -s * 0.90, s * 0.05
        )

        path.cubicTo(
            -s * 0.48, s * 0.15,
            -s * 0.20, s * 0.12,
            0, 0
        )

    else:

        # Smaller lower wing
        path.cubicTo(
            -s * 0.25, s * 0.12,
            -s * 0.90, s * 0.18,
            -s * 1.15, s * 0.48
        )

        path.cubicTo(
            -s * 1.35, s * 0.82,
            -s * 0.80, s * 1.05,
            -s * 0.48, s * 0.77
        )

        path.cubicTo(
            -s * 0.18, s * 0.55,
            -s * 0.12, s * 0.30,
            0, 0
        )

    path.closeSubpath()

    return path


def draw_wing(painter, size, color, upper, flap):

    path = make_wing_path(size, upper)

    painter.save()

    # Upper and lower wings have different flap angles
    if upper:
        angle = -flap * 24
    else:
        angle = flap * 15 + 12

    painter.rotate(angle)

    # Wing gradient
    gradient = QLinearGradient(
        0, -size, -size * 1.3, size
    )

    lighter = QColor(color).lighter(155)
    darker = QColor(color).darker(135)

    gradient.setColorAt(0, lighter)
    gradient.setColorAt(0.45, color)
    gradient.setColorAt(1, darker)

    painter.setBrush(QBrush(gradient))

    painter.setPen(
        QPen(
            QColor(
                darker.red(),
                darker.green(),
                darker.blue(),
                220
            ),
            max(0.7, size * 0.025)
        )
    )

    painter.drawPath(path)

    # Draw natural wing veins
    painter.setBrush(Qt.NoBrush)

    vein_pen = QPen(
        QColor(65, 35, 45, 125),
        max(0.5, size * 0.012)
    )

    painter.setPen(vein_pen)

    if upper:

        endpoints = [
            (-size * 1.25, -size * 0.65),
            (-size * 1.35, -size * 0.35),
            (-size * 1.30, -size * 0.08),
            (-size * 0.95, -size * 0.70),
            (-size * 0.70, -size * 0.85),
        ]

    else:

        endpoints = [
            (-size * 1.18, size * 0.52),
            (-size * 1.05, size * 0.72),
            (-size * 0.80, size * 0.90),
        ]

    for ex, ey in endpoints:

        vein = QPainterPath()

        vein.moveTo(-size * 0.10, size * 0.04)

        vein.cubicTo(
            -size * 0.40, ey * 0.15,
            ex * 0.60, ey * 0.75,
            ex, ey
        )

        painter.drawPath(vein)

    # Fine outer wing outline
    painter.setPen(
        QPen(
            QColor(60, 30, 45, 180),
            max(0.7, size * 0.018)
        )
    )

    painter.setBrush(Qt.NoBrush)

    painter.drawPath(path)

    painter.restore()


def draw_butterfly(painter, butterfly):

    painter.save()

    painter.translate(butterfly.x, butterfly.y)

    painter.rotate(butterfly.angle)

    size = butterfly.size
    color = butterfly.color

    # Wings fold and open with a smooth natural rhythm
    flap = math.sin(butterfly.phase)

    # Flap controls wing rotation and apparent spread
    spread = 0.48 + abs(flap) * 0.52

    # Draw all four wings around the body
    for side in (-1, 1):

        painter.save()

        painter.scale(side * spread, 1)

        # Upper wing
        draw_wing(
            painter,
            size,
            color,
            upper=True,
            flap=flap
        )

        # Lower wing
        draw_wing(
            painter,
            size * 0.83,
            color,
            upper=False,
            flap=flap
        )

        painter.restore()

    # -----------------------------------------------------
    # BODY
    # -----------------------------------------------------

    painter.setPen(
        QPen(QColor("#33242c"), size * 0.10)
    )

    painter.drawLine(
        QPointF(0, -size * 0.28),
        QPointF(0, size * 0.50)
    )

    painter.setPen(
        QPen(QColor("#211922"), size * 0.035)
    )

    # Antennae
    painter.drawLine(
        QPointF(0, -size * 0.25),
        QPointF(-size * 0.20, -size * 0.70)
    )

    painter.drawLine(
        QPointF(0, -size * 0.25),
        QPointF(size * 0.20, -size * 0.70)
    )

    # Head
    painter.setPen(Qt.NoPen)

    painter.setBrush(QColor("#211922"))

    painter.drawEllipse(
        QPointF(0, -size * 0.30),
        size * 0.12,
        size * 0.12
    )

    painter.restore()


# =========================================================
# TRANSPARENT OVERLAY
# =========================================================

class ButterflyOverlay(QWidget):

    def __init__(self):

        super().__init__()

        self.screen = QApplication.primaryScreen().geometry()

        self.width = self.screen.width()
        self.height = self.screen.height()

        self.setGeometry(self.screen)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        if CLICK_THROUGH:
            self.setAttribute(
                Qt.WA_TransparentForMouseEvents
            )

        self.mouse_x = -10000
        self.mouse_y = -10000

        self.butterflies = [
            Butterfly(self.width, self.height)
            for _ in range(BUTTERFLY_COUNT)
        ]

        self.start_time = time.monotonic()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(int(1000 / FPS))

        self.showFullScreen()

        if CLICK_THROUGH:
            QTimer.singleShot(
                300, self.enable_click_through
            )

    # -----------------------------------------------------
    # CLICK-THROUGH SUPPORT
    # -----------------------------------------------------

    def enable_click_through(self):

        if platform.system() == "Windows":

            import ctypes

            hwnd = int(self.winId())

            GWL_EXSTYLE = -20

            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080

            user32 = ctypes.windll.user32

            style = user32.GetWindowLongW(
                hwnd, GWL_EXSTYLE
            )

            style |= (
                WS_EX_LAYERED
                | WS_EX_TRANSPARENT
                | WS_EX_TOOLWINDOW
            )

            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style
            )

        elif platform.system() == "Linux":

            try:

                from Xlib import display
                from Xlib.ext import shape
                from Xlib import X

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
                    []
                )

                self.xdisplay.sync()

            except Exception as e:

                print("X11 click-through error:", e)

    # -----------------------------------------------------
    # ANIMATE
    # -----------------------------------------------------

    def animate(self):

        elapsed = time.monotonic() - self.start_time

        if elapsed >= DURATION_SECONDS:

            self.timer.stop()
            self.close()
            QApplication.quit()
            return

        for butterfly in self.butterflies:

            butterfly.update(
                self.width,
                self.height,
                self.mouse_x,
                self.mouse_y
            )

        self.update()

    # -----------------------------------------------------
    # DRAW
    # -----------------------------------------------------

    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        painter.setRenderHint(
            QPainter.SmoothPixmapTransform
        )

        for butterfly in self.butterflies:

            draw_butterfly(
                painter, butterfly
            )

        painter.end()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    app = QApplication(sys.argv)

    overlay = ButterflyOverlay()

    sys.exit(app.exec_())
