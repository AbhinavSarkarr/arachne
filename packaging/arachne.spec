# PyInstaller spec for Arachne.   Build:  pyinstaller packaging/arachne.spec
# Windows/Linux: one self-contained executable.  macOS: Arachne.app (no Dock icon).
import os
import sys

root = os.path.abspath(os.path.join(SPECPATH, ".."))
art = os.path.join(SPECPATH, "build")
icon = {"win32": "arachne.ico", "darwin": "arachne.icns"}.get(sys.platform)
icon = os.path.join(art, icon) if icon and os.path.exists(os.path.join(art, icon)) else None
linux = sys.platform.startswith("linux")
version = os.environ.get("ARACHNE_VERSION", "2.0.0")

a = Analysis(
    [os.path.join(root, "arachne.py")],
    pathex=[root],
    hiddenimports=["colony", "spiders", "papillon", "dex", "PyQt5.QtMultimedia", "PyQt5.sip", "PyQt5.QtCore", "PyQt5.QtGui",
                   "PyQt5.QtWidgets", "PyQt5.QtNetwork", "numpy"]
    + (["Xlib", "Xlib.ext.shape", "Xlib.display"] if linux else []),
    excludes=["tkinter", "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore", "PyQt5.QtQml",
              "PyQt5.QtQuick", "PyQt5.QtBluetooth", "PyQt5.QtSql"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Arachne", console=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, name="Arachne")
    app = BUNDLE(coll, name="Arachne.app", icon=icon, bundle_identifier="com.arachne.colony",
                 info_plist={"LSUIElement": True, "CFBundleShortVersionString": version,
                             "NSHighResolutionCapable": True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="Arachne" if sys.platform == "win32" else "arachne",
              console=False, icon=icon, upx=False)
