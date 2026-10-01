"""Render the app icon (a red-knee tarantula) to packaging/build/arachne.{png,ico,icns}."""
import os
import shutil
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root)
from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
import colony  # noqa: E402

out = os.path.join(os.path.dirname(__file__), "build")
os.makedirs(out, exist_ok=True)
img = colony.make_icon(512).toImage()
img.save(os.path.join(out, "arachne.png"))
img.scaled(256, 256).save(os.path.join(out, "arachne.ico"))
if not img.save(os.path.join(out, "arachne.icns")) and shutil.which("iconutil"):
    iconset = os.path.join(out, "arachne.iconset")
    os.makedirs(iconset, exist_ok=True)
    for s in (16, 32, 64, 128, 256, 512):
        img.scaled(s, s).save(os.path.join(iconset, f"icon_{s}x{s}.png"))
        img.scaled(s * 2, s * 2).save(os.path.join(iconset, f"icon_{s}x{s}@2x.png"))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(out, "arachne.icns")])
print("icons written to", out)
