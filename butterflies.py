import sys
import math
import random
import time
import platform

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QRadialGradient,
)


# =====================================================
# CONFIGURATION
# =====================================================

DURATION_SECONDS = 60       # Animation duration
BUTTERFLY_COUNT = 45        # Number of butterflies
FPS = 60                    # Animation speed

MIN_SIZE = 18
MAX_SIZE = 55

MOUSE_REPEL_RADIUS = 130
MOUSE_REPEL_STRENGTH = 4.0

# Set True to enable click-through desktop interaction.
CLICK_THROUGH = True


# =====================================================
# BUTTERFLY CLASS
# =====================================================

class Butterfly:

    def __init__(self, width, height):

        self.x = random.uniform(0, width)
        self.y = random.uniform(0, height)

        self.size = random.uniform(MIN_SIZE, MAX_SIZE)

        self.speed_x = random.uniform(-2.0, 2.0)
        self.speed_y = random.uniform(-1.5, 1.5)

        self.angle = random.uniform(0, 360)

        self.wing_phase = random.uniform(0, math.pi * 2)
        self.wing_speed = random.uniform(0.15, 0.35)

        self.color = random.choice([
            QColor(255, 100, 180),
            QColor(180, 100, 255),
            QColor(80, 200, 255),
            QColor(255, 180, 50),
            QColor(255, 80, 100),
            QColor(120, 255, 180),
            QColor(255, 255, 100),
        ])

        self.alpha = random.randint(190, 255)

        self.turn_speed = random.uniform(-1.5, 1.5)

    def update(self, width, height, mouse_x, mouse_y):

        self.wing_phase += self.wing_speed

        # Random natural movement
        self.speed_x += random.uniform(-0.05, 0.05)
        self.speed_y += random.uniform(-0.04, 0.04)

        # Keep speed under control
        self.speed_x = max(-3.0, min(3.0, self.speed_x))
        self.speed_y = max(-2.5, min(2.5, self.speed_y))

        # Mouse interaction: butterflies fly away from cursor
        dx = self.x - mouse_x
        dy = self.y - mouse_y

        distance = math.sqrt(dx * dx + dy * dy)

        if 0 < distance < MOUSE_REPEL_RADIUS:

            force = (
                1 - distance / MOUSE_REPEL_RADIUS
            ) * MOUSE_REPEL_STRENGTH

            self.speed_x += (dx / distance) * force * 0.1
            self.speed_y += (dy / distance) * force * 0.1

        # Move butterfly
        self.x += self.speed_x
        self.y += self.speed_y

        # Rotate in the direction of movement
        if abs(self.speed_x) > 0.1:
            self.angle = math.degrees(
                math.atan2(self.speed_y, self.speed_x)
            )

        # Wrap around screen edges
        if self.x < -self.size:
            self.x = width + self.size

        if self.x > width + self.size:
            self.x = -self.size

        if self.y < -self.size:
            self.y = height + self.size

        if self.y > height + self.size:
            self.y = -self.size


# =====================================================
# BUTTERFLY OVERLAY WINDOW
# =====================================================

class ButterflyOverlay(QWidget):

    def __init__(self):

        super().__init__()

        self.screen = QApplication.primaryScreen().geometry()

        self.screen_width = self.screen.width()
        self.screen_height = self.screen.height()

        # Window configuration
        self.setGeometry(self.screen)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        # Transparent background
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        if CLICK_THROUGH:
            self.setAttribute(
                Qt.WA_TransparentForMouseEvents
            )

        # Track mouse position
        self.mouse_x = -1000
        self.mouse_y = -1000

        # Create butterflies
        self.butterflies = [
            Butterfly(self.screen_width, self.screen_height)
            for _ in range(BUTTERFLY_COUNT)
        ]

        # Timer
        self.start_time = time.monotonic()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(int(1000 / FPS))

        self.showFullScreen()

        # Enable operating system-level click-through
        if CLICK_THROUGH:
            QTimer.singleShot(300, self.enable_click_through)

    # -------------------------------------------------
    # Make the overlay click-through at OS level
    # -------------------------------------------------

    def enable_click_through(self):

        system = platform.system()

        if system == "Windows":

            import ctypes

            hwnd = int(self.winId())

            GWL_EXSTYLE = -20

            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080

            get_window_long = ctypes.windll.user32.GetWindowLongW
            set_window_long = ctypes.windll.user32.SetWindowLongW

            style = get_window_long(hwnd, GWL_EXSTYLE)

            style |= (
                WS_EX_LAYERED
                | WS_EX_TRANSPARENT
                | WS_EX_TOOLWINDOW
            )

            set_window_long(hwnd, GWL_EXSTYLE, style)

        elif system == "Linux":

            # X11 only. Install python-xlib:
            # pip install python-xlib

            try:

                from Xlib import display
                from Xlib.ext import shape
                from Xlib import X

                d = display.Display()
                window_id = int(self.winId())

                window = d.create_resource_object(
                    "window", window_id
                )

                # Empty input region means all mouse and
                # keyboard events pass through the overlay.
                window.shape_rectangles(
                    shape.SO.Set,
                    shape.SK.Input,
                    X.Unsorted,
                    0,
                    0,
                    []
                )

                d.sync()

                self.xdisplay = d

            except Exception as e:
                print("X11 click-through error:", e)
                print(
                    "Install python-xlib and use an Xorg session."
                )

    # -------------------------------------------------
    # Animation update
    # -------------------------------------------------

    def animate(self):

        elapsed = time.monotonic() - self.start_time

        # Stop after configured duration
        if elapsed >= DURATION_SECONDS:
            self.close()
            QApplication.quit()
            return

        for butterfly in self.butterflies:

            butterfly.update(
                self.screen_width,
                self.screen_height,
                self.mouse_x,
                self.mouse_y
            )

        self.update()

    # -------------------------------------------------
    # Draw butterfly wings
    # -------------------------------------------------

    def draw_butterfly(self, painter, butterfly):

        painter.save()

        painter.translate(
            butterfly.x,
            butterfly.y
        )

        painter.rotate(butterfly.angle)

        size = butterfly.size

        # Wing flapping animation
        flap = math.sin(
            butterfly.wing_phase
        )

        wing_width = size * 0.65

        wing_height = size * (
            0.35 + abs(flap) * 0.45
        )

        color = QColor(butterfly.color)
        color.setAlpha(butterfly.alpha)

        # Wing gradient
        gradient = QRadialGradient(
            0, 0, size
        )

        gradient.setColorAt(
            0, QColor(255, 255, 255, 230)
        )

        gradient.setColorAt(
            0.35, color
        )

        gradient.setColorAt(
            1, QColor(
                color.red(),
                color.green(),
                color.blue(),
                40
            )
        )

        painter.setBrush(QBrush(gradient))

        painter.setPen(
            QPen(
                QColor(255, 255, 255, 150),
                1.2
            )
        )

        # Left wing
        painter.save()

        painter.scale(
            1,
            max(0.08, abs(flap))
        )

        painter.drawEllipse(
            QPointF(-wing_width * 0.5, -wing_height * 0.4),
            wing_width,
            wing_height
        )

        painter.restore()

        # Right wing
        painter.save()

        painter.scale(
            1,
            max(0.08, abs(flap))
        )

        painter.drawEllipse(
            QPointF(wing_width * 0.5, -wing_height * 0.4),
            wing_width,
            wing_height
        )

        painter.restore()

        # Butterfly body
        painter.setPen(
            QPen(QColor(40, 30, 40), 2)
        )

        painter.setBrush(
            QBrush(QColor(40, 30, 40))
        )

        painter.drawEllipse(
            QPointF(0, 0),
            size * 0.055,
            size * 0.4
        )

        # Antennae
        painter.setPen(
            QPen(QColor(30, 30, 30), 1)
        )

        painter.drawLine(
            QPointF(0, -size * 0.2),
            QPointF(-size * 0.18, -size * 0.5)
        )

        painter.drawLine(
            QPointF(0, -size * 0.2),
            QPointF(size * 0.18, -size * 0.5)
        )

        painter.restore()

    # -------------------------------------------------
    # Paint everything
    # -------------------------------------------------

    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        painter.setRenderHint(
            QPainter.SmoothPixmapTransform
        )

        # Draw butterflies
        for butterfly in self.butterflies:

            self.draw_butterfly(
                painter,
                butterfly
            )

        painter.end()

    # -------------------------------------------------
    # Escape key closes app when keyboard events
    # reach the overlay
    # -------------------------------------------------

    def keyPressEvent(self, event):

        if event.key() == Qt.Key_Escape:
            self.timer.stop()
            self.close()
            QApplication.quit()


# =====================================================
# RUN APPLICATION
# =====================================================

if __name__ == "__main__":

    app = QApplication(sys.argv)

    overlay = ButterflyOverlay()

    sys.exit(app.exec_())
