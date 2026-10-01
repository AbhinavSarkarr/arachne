#!/usr/bin/env python3
"""
Arachne — a living spider colony on your desktop.

  arachne              toggle: start the colony (resuming the save), or save & stop it
  arachne --fresh      start a brand-new colony
  arachne --agent      background Ctrl+Shift+B listener (started at login)
  arachne --colony     run the colony itself (used internally)
  arachne --setup      per-user setup: login agent / desktop shortcut (installers call this)
  arachne --unsetup    undo --setup (the saved colony is kept)

Ctrl+Shift+B is owned by the desktop on GNOME (custom shortcut) and by the
login agent everywhere else (Windows RegisterHotKey, macOS Carbon hot key,
X11 key grab). Both just run the toggle.
"""

import os
import sys
import shlex
import platform
import subprocess

APP = "Arachne"
SERVER = "arachne-colony-v1"            # local socket the running colony listens on
AGENT_SERVER = "arachne-agent-v1"
SYSTEM = platform.system()              # "Windows", "Darwin", "Linux"


def data_dir():
    if SYSTEM == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        d = os.path.join(base, APP)
    elif SYSTEM == "Darwin":
        d = os.path.expanduser("~/Library/Application Support/" + APP)
    else:
        d = os.path.expanduser("~/.local/share/arachne")
    os.makedirs(d, exist_ok=True)
    return d


def launch_cmd(*args):
    """How to start ourselves: the frozen binary, or python + this script."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    exe = sys.executable
    if SYSTEM == "Windows" and exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"     # no console window
    return [exe, os.path.abspath(__file__), *args]


def spawn(*args):
    log = open(os.path.join(data_dir(), "arachne.log"), "a")
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # child must unpack its own copy, not ours
    kw = dict(stdout=log, stderr=log, stdin=subprocess.DEVNULL, close_fds=True, env=env)
    if SYSTEM == "Windows":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
    else:
        kw["start_new_session"] = True
    subprocess.Popen(launch_cmd(*args), **kw)


def _core_app():
    from PyQt5.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication(sys.argv[:1])


def send(server, message):
    """Send one line to a running Arachne process; False if nobody is listening."""
    from PyQt5.QtNetwork import QLocalSocket
    _core_app()
    s = QLocalSocket()
    s.connectToServer(server)
    if not s.waitForConnected(500):
        return False
    s.write((message + "\n").encode())
    s.flush()
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def toggle(extra=()):
    if send(SERVER, "quit"):
        return "stopped"
    spawn("--colony", *extra)
    return "started"


# ── per-user setup ──────────────────────────────────────

GNOME_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/arachne/"


def _gsettings(*args):
    try:
        return subprocess.run(["gsettings", *args], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def gnome_available():
    return SYSTEM == "Linux" and _gsettings("get", GNOME_SCHEMA, "custom-keybindings") is not None \
        and _gsettings("get", GNOME_SCHEMA, "custom-keybindings") != ""


def gnome_bound():
    cur = _gsettings("get", GNOME_SCHEMA, "custom-keybindings") or ""
    return GNOME_PATH in cur


def _shell(cmd):
    return " ".join(shlex.quote(c) for c in cmd)


def setup():
    toggle_cmd = launch_cmd()
    if SYSTEM == "Windows":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Arachne Agent", 0, winreg.REG_SZ,
                              subprocess.list2cmdline(launch_cmd("--agent")))
        spawn("--agent")
    elif SYSTEM == "Darwin":
        plist = os.path.expanduser("~/Library/LaunchAgents/com.arachne.agent.plist")
        os.makedirs(os.path.dirname(plist), exist_ok=True)
        args = "".join(f"<string>{a}</string>" for a in launch_cmd("--agent"))
        with open(plist, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>'
                    '<key>Label</key><string>com.arachne.agent</string>'
                    f'<key>ProgramArguments</key><array>{args}</array>'
                    '<key>RunAtLoad</key><true/></dict></plist>\n')
        subprocess.run(["launchctl", "unload", plist], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", plist], capture_output=True)
    else:
        apps = os.path.expanduser("~/.local/share/applications")
        auto = os.path.expanduser("~/.config/autostart")
        os.makedirs(apps, exist_ok=True)
        os.makedirs(auto, exist_ok=True)
        user_entry = os.path.join(apps, "arachne.desktop")
        if os.path.exists("/usr/share/applications/arachne.desktop"):
            if os.path.exists(user_entry):
                os.remove(user_entry)         # the installed package provides it
        else:
            with open(os.path.join(apps, "arachne.desktop"), "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=Arachne\nGenericName=Spider Colony\n"
                        "Comment=A living spider colony on your desktop (Ctrl+Shift+B)\n"
                        f"Exec={_shell(toggle_cmd)}\nIcon=applications-science\nTerminal=false\n"
                        "Categories=Amusement;Simulation;\nStartupNotify=false\n")
        if gnome_available():                 # GNOME owns the key and runs the toggle itself
            cur = _gsettings("get", GNOME_SCHEMA, "custom-keybindings") or "@as []"
            if GNOME_PATH not in cur:
                new = (f"['{GNOME_PATH}']" if cur in ("@as []", "[]")
                       else cur[:-1] + f", '{GNOME_PATH}']")
                _gsettings("set", GNOME_SCHEMA, "custom-keybindings", new)
            key = f"{GNOME_SCHEMA}.custom-keybinding:{GNOME_PATH}"
            _gsettings("set", key, "name", "Arachne spider colony")
            _gsettings("set", key, "command", _shell(toggle_cmd))
            _gsettings("set", key, "binding", "<Control><Shift>b")
        elif not os.path.exists("/etc/xdg/autostart/arachne-agent.desktop"):
            with open(os.path.join(auto, "arachne-agent.desktop"), "w") as f:
                f.write("[Desktop Entry]\nType=Application\nName=Arachne hotkey\n"
                        f"Exec={_shell(launch_cmd('--agent'))}\nNoDisplay=true\n"
                        "X-GNOME-Autostart-enabled=true\n")
            spawn("--agent")
    print("Arachne is set up: press Ctrl+Shift+B to start or stop the colony.")


def unsetup():
    send(SERVER, "quit")                      # save & stop a running colony
    send(AGENT_SERVER, "quit")
    if SYSTEM == "Windows":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "Arachne Agent")
        except OSError:
            pass
    elif SYSTEM == "Darwin":
        plist = os.path.expanduser("~/Library/LaunchAgents/com.arachne.agent.plist")
        subprocess.run(["launchctl", "unload", plist], capture_output=True)
        if os.path.exists(plist):
            os.remove(plist)
    else:
        for p in ("~/.local/share/applications/arachne.desktop",
                  "~/.config/autostart/arachne-agent.desktop"):
            p = os.path.expanduser(p)
            if os.path.exists(p):
                os.remove(p)
        cur = _gsettings("get", GNOME_SCHEMA, "custom-keybindings")
        if cur and GNOME_PATH in cur:
            items = [x.strip().strip("'") for x in cur.strip("[]@as ").split(",") if x.strip()]
            items = [x for x in items if x != GNOME_PATH]
            _gsettings("set", GNOME_SCHEMA, "custom-keybindings",
                       "[" + ", ".join(f"'{x}'" for x in items) + "]" if items else "@as []")
            _gsettings("reset-recursively", f"{GNOME_SCHEMA}.custom-keybinding:{GNOME_PATH}")
    print("Arachne shortcut removed (your colony save is kept).")


# ── login agent: owns Ctrl+Shift+B where the desktop can't ─────────

def agent():
    from PyQt5.QtWidgets import QApplication, QWidget
    from PyQt5.QtNetwork import QLocalServer
    from PyQt5.QtCore import QTimer

    if send(AGENT_SERVER, "ping"):
        return                                 # already running
    if SYSTEM == "Linux" and gnome_available():
        setup()                                # GNOME handles the key; make sure it's bound
        return
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    server = QLocalServer()
    QLocalServer.removeServer(AGENT_SERVER)
    server.listen(AGENT_SERVER)

    def on_conn():
        c = server.nextPendingConnection()
        c.waitForReadyRead(300)
        if bytes(c.readAll()).strip() == b"quit":
            app.quit()
    server.newConnection.connect(on_conn)

    def pressed():
        toggle()

    keep = []
    if SYSTEM == "Windows":
        import ctypes
        from ctypes import wintypes

        class HotkeyWindow(QWidget):
            def nativeEvent(self, kind, message):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312:      # WM_HOTKEY
                    pressed()
                    return True, 0
                return False, 0
        w = HotkeyWindow()
        hwnd = int(w.winId())
        if not ctypes.windll.user32.RegisterHotKey(hwnd, 1, 0x0002 | 0x0004 | 0x4000, 0x42):
            print("Ctrl+Shift+B is already taken by another program")
        keep.append(w)
    elif SYSTEM == "Darwin":
        keep.append(_mac_hotkey(pressed))
    else:
        keep.append(_x11_hotkey(pressed))
    app.exec_()


def _mac_hotkey(pressed):
    """Carbon RegisterEventHotKey: global, and needs no accessibility permission."""
    import ctypes
    from ctypes import c_uint32, c_void_p, c_int32, byref, Structure, CFUNCTYPE

    carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

    def fourcc(s):
        return int.from_bytes(s.encode(), "big")

    class EventTypeSpec(Structure):
        _fields_ = [("eventClass", c_uint32), ("eventKind", c_uint32)]

    class EventHotKeyID(Structure):
        _fields_ = [("signature", c_uint32), ("id", c_uint32)]

    HANDLER = CFUNCTYPE(c_int32, c_void_p, c_void_p, c_void_p)
    cb = HANDLER(lambda _next, _event, _data: (pressed(), 0)[1])
    carbon.GetApplicationEventTarget.restype = c_void_p
    target = carbon.GetApplicationEventTarget()
    spec = EventTypeSpec(fourcc("keyb"), 5)    # kEventClassKeyboard / kEventHotKeyPressed
    carbon.InstallEventHandler(c_void_p(target), cb, 1, byref(spec), None, None)
    ref = c_void_p()
    # kVK_ANSI_B = 11; controlKey = 1<<12, shiftKey = 1<<9
    carbon.RegisterEventHotKey(11, (1 << 12) | (1 << 9), EventHotKeyID(fourcc("arac"), 1),
                               c_void_p(target), 0, byref(ref))
    return (cb, spec, ref)


def _x11_hotkey(pressed):
    from PyQt5.QtCore import QTimer
    try:
        from Xlib import display, X, XK
    except ImportError:
        return None
    d = display.Display()
    root = d.screen().root
    code = d.keysym_to_keycode(XK.string_to_keysym("b"))
    for extra in (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask):
        root.grab_key(code, X.ControlMask | X.ShiftMask | extra, True,
                      X.GrabModeAsync, X.GrabModeAsync)
    d.sync()

    def poll():
        while d.pending_events():
            ev = d.next_event()
            if ev.type == X.KeyPress and ev.detail == code:
                pressed()
    t = QTimer()
    t.timeout.connect(poll)
    t.start(100)
    return (d, t)


# ── entry point ─────────────────────────────────────────

def run_colony(fresh=False):
    import colony
    colony.main(fresh=fresh)


def main():
    args = sys.argv[1:]
    if "--agent" in args:
        agent()
    elif "--colony" in args:
        run_colony(fresh="--fresh" in args)
    elif "--setup" in args:
        setup()
    elif "--unsetup" in args:
        unsetup()
    else:
        print(f"Arachne colony {toggle(['--fresh'] if '--fresh' in args else [])}.")


if __name__ == "__main__":
    main()
