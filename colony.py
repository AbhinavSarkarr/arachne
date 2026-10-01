#!/usr/bin/env python3
"""
Arachne colony layer: day/night and seasons, the Colony Journal, save & resume,
awareness of real desktop windows, and click-to-inspect spiders.

Run:  venv/bin/python spiders.py            (resumes the saved colony)
      venv/bin/python spiders.py --fresh    (start a new colony)
Keys: Ctrl+Shift+J  journal      Ctrl+Shift+B  start / save & stop (via arachne-toggle)
"""

import sys
import os
import json
import time
import math
import random
import signal

from PyQt5.QtWidgets import (
    QApplication, QWidget, QTabWidget, QVBoxLayout, QLabel, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QSystemTrayIcon, QMenu, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt5.QtGui import (QPainter, QColor, QPen, QCursor, QRegion, QFont, QPainterPath,
                         QPixmap, QIcon)
from PyQt5.QtNetwork import QLocalServer

import arachne

import papillon
import spiders as S
from spiders import WORLD, Spider, Web, EggSac, SPECIES, common_name


# ── Configuration ───────────────────────────────────────

DAY_MINUTES = 24          # one compressed day/night cycle; 0 = follow the real clock
SEASON_MINUTES = 30       # spring → summer → autumn → winter, then a new year
NIGHT_TINT = 26           # strength of the night tint (0 turns it off)
AUTOSAVE_S = 60
SAVE_DIR = arachne.data_dir()
SAVE_FILE = os.path.join(SAVE_DIR, "colony.json")
JOURNAL_FILE = os.path.join(SAVE_DIR, "journal.txt")
SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_NOTES = {
    "spring": "Spring — males start wandering in search of mates",
    "summer": "Summer — insects swarm and egg sacs appear",
    "autumn": "Autumn — spiderlings take to the air; the annual species grow old",
    "winter": "Winter — insects vanish and the colony slows down",
}
ICONS = {"kill": "✗", "cannibal": "✗", "mate": "♥", "egg": "●", "hatch": "✦", "web": "✳",
         "death": "†", "molt": "↻", "theft": "✋", "insect": "•", "lure": "♪", "social": "☘",
         "arrive": "→", "season": "☀", "night": "☾", "info": "·"}


class Clock:
    """Colony time: survives restarts through the save file."""

    def __init__(self, age=0.0):
        self.age = age
        self.last = time.monotonic()

    def tick(self):
        now = time.monotonic()
        self.age += min(1.0, now - self.last)
        self.last = now

    def phase(self):                          # 0 = midnight, 0.5 = noon
        if DAY_MINUTES:
            return (self.age / (DAY_MINUTES * 60) + 0.3) % 1.0
        t = time.localtime()
        return (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec) / 86400

    def night(self):
        sun = math.sin(math.tau * (self.phase() - 0.25))
        return max(0.0, min(1.0, 0.5 - sun * 1.6))

    def day(self):
        return int(self.age / (DAY_MINUTES * 60)) + 1 if DAY_MINUTES else 1

    def season(self):
        return SEASONS[int(self.age / (SEASON_MINUTES * 60)) % 4]

    def year(self):
        return int(self.age / (SEASON_MINUTES * 60 * 4)) + 1

    def hhmm(self):
        m = int(self.phase() * 24 * 60)
        return f"{m // 60:02d}:{m % 60:02d}"

    def label(self):
        return f"Year {self.year()} · Day {self.day()} · {self.season().title()} · {self.hhmm()}"


# ── Journal ─────────────────────────────────────────────

class Journal:
    def __init__(self, clock):
        self.clock = clock
        self.entries = []                     # (stamp, text, kind)
        self.listeners = []
        os.makedirs(SAVE_DIR, exist_ok=True)

    def add(self, text, kind="info"):
        stamp = f"D{self.clock.day()} {self.clock.hhmm()}"
        e = (stamp, text, kind)
        self.entries.append(e)
        del self.entries[:-600]
        try:
            with open(JOURNAL_FILE, "a") as f:
                f.write(f"{self.clock.label()}  {text}\n")
        except OSError:
            pass
        for fn in self.listeners:
            fn(e)


class PopulationGraph(QWidget):
    def __init__(self, colony):
        super().__init__()
        self.colony = colony
        self.setMinimumHeight(260)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1e2127"))
        hist = self.colony.history
        if len(hist) < 2:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "the graph fills in as time passes…")
            return
        peak = {}
        for _, counts in hist:
            for k, v in counts.items():
                peak[k] = max(peak.get(k, 0), v)
        names = sorted(peak, key=lambda k: -peak[k])[:10]
        top = max(1, max(sum(c.values()) for _, c in hist))
        w, h = self.width() - 150, self.height() - 30
        colors = {sp["name"]: QColor(sp["abd_col"]) for sp in SPECIES}
        base = [0.0] * len(hist)
        for name in names + ["other"]:
            vals = [(c.get(name, 0) if name != "other" else
                     sum(v for k, v in c.items() if k not in names)) for _, c in hist]
            path = QPainterPath()
            xs = [10 + w * i / (len(hist) - 1) for i in range(len(hist))]
            path.moveTo(xs[0], 10 + h - base[0] / top * h)
            for x, b, v in zip(xs, base, vals):
                path.lineTo(x, 10 + h - (b + v) / top * h)
            for x, b in reversed(list(zip(xs, base))):
                path.lineTo(x, 10 + h - b / top * h)
            c = QColor(colors.get(name, QColor("#777")))
            c.setAlpha(200)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawPath(path)
            base = [b + v for b, v in zip(base, vals)]
        p.setFont(QFont("Sans", 8))
        for i, name in enumerate(names + ["other"]):
            c = colors.get(name, QColor("#777"))
            p.setBrush(c)
            p.drawRect(QRectF(w + 22, 12 + i * 18, 10, 10))
            p.setPen(QColor("#ddd"))
            p.drawText(QPointF(w + 38, 21 + i * 18), common_name(name))
            p.setPen(Qt.NoPen)
        p.setPen(QColor("#888"))
        p.drawText(QPointF(10, self.height() - 6), f"population over {len(hist) // 2} min (max {top})")


class JournalWindow(QWidget):
    COLS = ("Name", "Species", "Sex", "Stage", "Age (days)", "Kills", "Young", "Gen", "Doing")

    def __init__(self, colony):
        super().__init__(None, Qt.Window)
        self.colony = colony
        self.setWindowTitle("Colony Journal")
        self.resize(640, 640)
        self.setStyleSheet("QWidget { background:#262a31; color:#e6e6e6; }"
                           "QTabBar::tab { padding:6px 14px; } "
                           "QHeaderView::section { background:#30353d; color:#ddd; }")
        lay = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setFont(QFont("Sans", 11, QFont.Bold))
        lay.addWidget(self.header)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        tabs.addTab(self.log, "Log")
        self.graph = PopulationGraph(colony)
        tabs.addTab(self.graph, "Population")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Family", "Species", "Fate"])
        tabs.addTab(self.tree, "Family")
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._renamed)
        self.table.itemSelectionChanged.connect(self._picked)
        tabs.addTab(self.table, "Spiders")
        for e in colony.journal.entries:
            self._append(e)
        colony.journal.listeners.append(self._append)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self._filling = False

    def _append(self, e):
        stamp, text, kind = e
        self.log.appendPlainText(f"{stamp}  {ICONS.get(kind, '·')}  {text}")

    def refresh(self):
        if not self.isVisible():
            return
        c = self.colony
        live = c.living()
        self.header.setText(f"{c.clock.label()}   ·   {len(live)} spiders, "
                            f"{len({o.base_sp['name'] for o in live})} species   ·   "
                            f"{len(c.eco.webs)} webs")
        self.graph.update()
        if self.table.state() != QAbstractItemView.EditingState:
            self._fill_table(live)
        self._fill_tree()

    def _fill_table(self, live):
        self._filling = True
        self.table.setRowCount(len(live))
        for r, o in enumerate(sorted(live, key=lambda o: (o.base_sp["name"], o.name))):
            stage = ("old" if o.old() else "adult" if o.scale >= 1 else
                     "juvenile" if o.scale > 0.5 else "spiderling")
            vals = (o.name, common_name(o.base_sp["name"]), "♀" if o.sex == "f" else "♂", stage,
                    f"{o.age_s / (DAY_MINUTES * 60 or 86400):.1f}", o.kills, o.children, o.gen,
                    doing(o))
            for col, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setData(Qt.UserRole, o.uid)
                if col:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, col, it)
        self._filling = False

    def _fill_tree(self):
        reg = self.colony.registry
        self.tree.clear()
        items = {}
        for uid, rec in sorted(reg.items()):
            it = QTreeWidgetItem([f"{rec['name']} {'♀' if rec['sex'] == 'f' else '♂'}",
                                  common_name(rec["species"]), rec.get("fate", "alive")])
            items[uid] = it
        for uid, rec in sorted(reg.items()):
            parent = items.get(rec.get("mother"))
            (parent.addChild if parent else self.tree.addTopLevelItem)(items[uid])
        self.tree.expandToDepth(1)

    def _renamed(self, item):
        if self._filling or item.column() != 0:
            return
        o = self.colony.by_uid(item.data(Qt.UserRole))
        if o and item.text().strip():
            o.name = item.text().strip()[:20]
            self.colony.registry.setdefault(o.uid, {})["name"] = o.name

    def _picked(self):
        rows = self.table.selectedItems()
        if rows:
            self.colony.selected = rows[0].data(Qt.UserRole)


def doing(o):
    st = o.state
    return {"hub": "resting at home", "build": "spinning silk", "hunt": "hunting",
            "feed": "feeding", "court": "courting", "mate": "mating", "seek": "looking for a mate",
            "grapple": "fighting!", "flee": "fleeing", "hide": "hiding", "molt": "molting",
            "spin": "spinning an egg sac", "ball": "huddled with siblings", "goto": "on the move",
            "walk": "wandering", "pause": "keeping still", "special": "showing off",
            "stuck": "tangled in silk", "burrow": "in its burrow"}.get(st, st)


# ── Desktop windows (X11 / XWayland apps only) ──────────

class Desktop:
    def __init__(self, overlay):
        self.ov = overlay
        self.d = None
        try:
            from Xlib import display, X
            self.X = X
            self.d = display.Display()
            self.root = self.d.screen().root
            self.atom = {n: self.d.intern_atom(n) for n in (
                "_NET_CLIENT_LIST", "_NET_WM_STATE", "_NET_WM_STATE_HIDDEN", "_NET_WM_PID",
                "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_DESKTOP")}
        except Exception:
            self.d = None

    def scan(self):
        if self.d is None:
            return
        try:
            prop = self.root.get_full_property(self.atom["_NET_CLIENT_LIST"], self.X.AnyPropertyType)
            origin = self.ov.mapToGlobal(self.ov.rect().topLeft())
            wins = []
            for wid in (prop.value if prop else []):
                w = self.d.create_resource_object("window", wid)
                pid = w.get_full_property(self.atom["_NET_WM_PID"], self.X.AnyPropertyType)
                if pid and pid.value and pid.value[0] == os.getpid():
                    continue
                st = w.get_full_property(self.atom["_NET_WM_STATE"], self.X.AnyPropertyType)
                if st and self.atom["_NET_WM_STATE_HIDDEN"] in st.value:
                    continue
                ty = w.get_full_property(self.atom["_NET_WM_WINDOW_TYPE"], self.X.AnyPropertyType)
                if ty and (self.atom["_NET_WM_WINDOW_TYPE_DOCK"] in ty.value or
                           self.atom["_NET_WM_WINDOW_TYPE_DESKTOP"] in ty.value):
                    continue
                g = w.get_geometry()
                t = self.root.translate_coords(w, 0, 0)
                if g.width < 80 or g.height < 60:
                    continue
                wins.append((wid, QRectF(t.x - origin.x(), t.y - origin.y(), g.width, g.height)))
            WORLD.windows = wins
            WORLD.hides = [r for _, r in wins]
        except Exception:
            pass


# ── The colony overlay ──────────────────────────────────

class ColonyOverlay(S.SpiderOverlay):

    def __init__(self, fresh=False):
        self.clock = Clock()
        self.journal = Journal(self.clock)
        WORLD.log = self.journal.add
        WORLD.year_s = SEASON_MINUTES * 60 * 4
        self.history = []
        self.registry = {}
        self.selected = None
        self.last_season = None
        self.last_night = None
        self.still_t = time.monotonic()
        self.press = None
        super().__init__()
        self.desktop = Desktop(self)
        self.journal_win = None
        restored = (not fresh) and self.restore()
        if not restored:
            self.journal.add("A new colony begins: spiders are being released into the box", "info")
        for t, ms, fn in ((None, AUTOSAVE_S * 1000, self.save), (None, 1000, self.desktop.scan),
                          (None, 30000, self._sample)):
            tm = QTimer(self)
            tm.timeout.connect(fn)
            tm.start(ms)
        self._sample()

    # ── helpers ──

    def living(self):
        return [o for o in self.butterflies if isinstance(o, Spider)
                and o.state not in S.DEADISH and not o.gone and not o.exuvia]

    def by_uid(self, uid):
        return next((o for o in self.living() if o.uid == uid), None)

    def _sample(self):
        counts = {}
        for o in self.living():
            counts[o.base_sp["name"]] = counts.get(o.base_sp["name"], 0) + 1
        self.history.append((self.clock.age, counts))
        del self.history[:-1500]

    def _track(self):
        seen = set()
        for o in self.butterflies:
            if not isinstance(o, Spider) or o.exuvia:
                continue
            rec = self.registry.setdefault(o.uid, {})
            rec.update(name=o.name, species=o.base_sp["name"], sex=o.sex, gen=o.gen,
                       mother=o.mother_uid)
            if o.state in S.DEADISH:
                rec["fate"] = "died"
            elif o.state == "balloon":
                rec["fate"] = "ballooned away"
            else:
                rec["fate"] = "alive"
                seen.add(o.uid)
        for uid, rec in self.registry.items():
            if rec.get("fate") == "alive" and uid not in seen:
                rec["fate"] = "gone"

    # ── spawning: releases, immigrants, social colonies arrive as a group ──

    def _spawn(self):
        before = len(self.butterflies)
        super()._spawn()
        new = self.butterflies[before:]
        for o in new:
            if o.base_sp["name"] == "social_spider":
                col = {"members": {o}, "web": None}
                o.colony = col
                for _ in range(random.randint(5, 8)):
                    m = Spider(o.base_sp, self.sw, self.sh)
                    m.x, m.y = o.x + random.uniform(-40, 40), o.y + random.uniform(-40, 40)
                    m.angle = o.angle
                    m._set("enter", 9999)
                    m.walk_speed = o.walk_speed
                    m.plant_all()
                    m.colony = col
                    col["members"].add(m)
                    self.butterflies.append(m)
                self.journal.add("a colony of social cobweb spiders moved in together", "arrive")
            else:
                self.journal.add(f"a {common_name(o.base_sp['name'])} "
                                 f"({'female' if o.sex == 'f' else 'male'}) wandered in", "arrive")

    # ── main loop ──

    def _tick(self):
        g = self.mapFromGlobal(QCursor.pos())        # overlay may not sit at (0, 0)
        mx, my = g.x(), g.y()
        speed = math.hypot(mx - self.mouse_x, my - self.mouse_y)
        WORLD.flick = speed if speed < 1500 else 0.0
        now = time.monotonic()
        if speed > 1.5:
            self.still_t = now
        WORLD.cursor_still = now - self.still_t
        self.mouse_x, self.mouse_y = mx, my
        WORLD.cursor = (mx, my)

        self.clock.tick()
        WORLD.night = self.clock.night()
        season = self.clock.season()
        if season != WORLD.season or self.last_season is None:
            if self.last_season is not None:
                self.journal.add(SEASON_NOTES[season], "season")
            WORLD.season = self.last_season = season
        is_night = WORLD.night > 0.5
        if is_night != self.last_night:
            if self.last_night is not None:
                self.journal.add("Night falls — the nocturnal hunters come out" if is_night
                                 else "Dawn — dew glitters on the webs", "night")
            self.last_night = is_night

        m = 150
        self.butterflies = [b for b in self.butterflies if not getattr(b, "gone", False)
                            and (not b.retiring or b is self._dragging
                                 or (-m < b.x < self.sw + m and -m < b.y < self.sh + m))]
        elapsed = now - self.start_time
        steps = min(4, int(elapsed * papillon.FPS) - self.physics_steps)
        self.physics_steps += steps
        for _ in range(steps):
            for b in self.butterflies:
                b.update(mx, my)
        self.eco.step()
        self._track()
        self.update()
        self._update_input_region()

    # ── click-through: Linux uses an X input shape (base class); Windows and
    #    macOS flip the whole window between "transparent" and "clickable"
    #    depending on whether the cursor is over a spider ──

    def _update_input_region(self):
        if arachne.SYSTEM == "Linux":
            return super()._update_input_region()
        x, y = self.mouse_x, self.mouse_y
        over = self._dragging is not None or any(
            b.bbox[0] <= x <= b.bbox[2] and b.bbox[1] <= y <= b.bbox[3]
            for b in self.butterflies if isinstance(b, Spider) and b.state not in S.DEADISH)
        if over == getattr(self, "_clickable", None):
            return
        self._clickable = over
        try:
            import ctypes
            if arachne.SYSTEM == "Windows":
                u = ctypes.windll.user32
                hwnd = int(self.winId())
                style = u.GetWindowLongW(hwnd, -20)
                style |= 0x00080000 | 0x00000080                   # layered, tool window
                style = (style & ~0x20) if over else (style | 0x20)   # WS_EX_TRANSPARENT
                u.SetWindowLongW(hwnd, -20, style)
            elif arachne.SYSTEM == "Darwin":
                objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
                objc.sel_registerName.restype = ctypes.c_void_p
                get = ctypes.CDLL("/usr/lib/libobjc.A.dylib").objc_msgSend
                get.restype, get.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]
                put = ctypes.CDLL("/usr/lib/libobjc.A.dylib").objc_msgSend
                put.restype = None
                put.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
                win = get(int(self.winId()), objc.sel_registerName(b"window"))
                put(win, objc.sel_registerName(b"setIgnoresMouseEvents:"), not over)
        except Exception:
            pass

    def _enable_click_through(self):
        if arachne.SYSTEM != "Linux":
            self._update_input_region()       # start out transparent
            return
        self._linux_hotkeys()

    # ── input: click = inspect, drag = pick up ──

    def mousePressEvent(self, event):
        self.press = (event.x(), event.y(), time.monotonic())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        b = self._dragging
        if (b is not None and self.press and event.button() == Qt.LeftButton
                and math.hypot(event.x() - self.press[0], event.y() - self.press[1]) < 6
                and time.monotonic() - self.press[2] < 0.35):
            b.interaction = None              # it was a click: put it back down
            b.z = 0.0
            b.plant_all()
            self._dragging = None
            self.releaseMouse()
            self.selected = None if self.selected == b.uid else b.uid
            return
        super().mouseReleaseEvent(event)

    # ── hotkeys: Ctrl+Shift+J journal, Ctrl+Shift+B quit ──

    def _linux_hotkeys(self):
        S.SpiderOverlay._enable_click_through(self)
        try:
            from Xlib import X, XK
            root = self.xdisplay.screen().root
            root.ungrab_key(self._hotkey_code, X.AnyModifier)   # Ctrl+Shift+B is the desktop's
            self._journal_code = self.xdisplay.keysym_to_keycode(XK.string_to_keysym("j"))
            for extra in (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask):
                root.grab_key(self._journal_code, X.ControlMask | X.ShiftMask | extra,
                              True, X.GrabModeAsync, X.GrabModeAsync)
            self.xdisplay.sync()
        except Exception as e:
            print("journal hotkey unavailable:", e)

    def _check_hotkey(self):
        try:
            from Xlib import X
            while self.xdisplay.pending_events():
                ev = self.xdisplay.next_event()
                if ev.type == X.KeyPress and ev.detail == getattr(self, "_journal_code", None):
                    self.toggle_journal()
        except Exception:
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_J:
            self.toggle_journal()
        else:
            super().keyPressEvent(event)

    def _tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(make_icon(64)), self)
        self.tray.setToolTip("Arachne — spider colony")
        menu = QMenu()
        menu.addAction("Colony Journal", self.toggle_journal)
        menu.addSeparator()
        menu.addAction("Start a new colony…", self._new_colony)
        menu.addAction("Save && stop  (Ctrl+Shift+B)", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.toggle_journal()
                                    if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _new_colony(self):
        if QMessageBox.question(None, "Arachne", "Release a brand-new colony?\n"
                                "The current one (and its save) will be lost.") != QMessageBox.Yes:
            return
        try:
            os.remove(SAVE_FILE)
        except OSError:
            pass
        self._nosave = True
        self._quit()
        arachne.spawn("--colony", "--fresh")

    def toggle_journal(self):
        if self.journal_win is None:
            self.journal_win = JournalWindow(self)
        if self.journal_win.isVisible():
            self.journal_win.hide()
        else:
            self.journal_win.show()
            self.journal_win.raise_()
            self.journal_win.refresh()

    def _quit(self):
        if getattr(self, "_quitting", False):
            return
        self._quitting = True
        if not getattr(self, "_nosave", False):
            self.save()
        if self.journal_win:
            self.journal_win.close()
        super()._quit()

    # ── drawing ──

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if NIGHT_TINT and WORLD.night > 0.02:
            p.fillRect(self.rect(), QColor(8, 16, 48, int(NIGHT_TINT * WORLD.night)))
        spiders = sorted((b for b in self.butterflies if isinstance(b, Spider)),
                         key=lambda b: (b.state != "husk", b.z))
        for b in spiders:
            b.pose()
        S.draw_eco_ground(p, self.eco)
        self._dew(p)
        low = [b for b in WORLD.insects if b.z < 3]
        high = [b for b in WORLD.insects if b.z >= 3]
        for b in WORLD.insects:
            S.draw_insect(p, b, True)
        for b in low:
            S.draw_insect(p, b, False)
        for b in spiders:
            if b.sp["ground"]:
                b.sp["ground"](p, b)
        screen = QRegion(self.rect())
        for layer in (S.draw_shadow, S.draw_spider):
            for b in spiders:
                r = b.hide_rect
                if r is not None and r.intersects(QRectF(self.rect())) and b.state in ("hide", "goto"):
                    p.save()                  # tucked under a window edge
                    p.setClipRegion(screen.subtracted(QRegion(r.toRect())))
                    layer(p, b)
                    p.restore()
                else:
                    layer(p, b)
        for b in spiders:
            S.draw_fx(p, b)
        for b in high:
            S.draw_insect(p, b, False)
        self._card(p)
        p.end()

    def _dew(self, p):
        ph = self.clock.phase()
        dawn = max(0.0, 1 - abs(ph - 0.27) / 0.06)       # dew only around sunrise
        if dawn <= 0:
            return
        p.setPen(Qt.NoPen)
        for w in self.eco.webs:
            if w.progress < 1 or w.integrity < 0.4:
                continue
            if not hasattr(w, "dew"):
                pts = ([(q.x(), q.y()) for q in w.spiral[::7]] if w.kind == "orb" else
                       [((x0 + x1) / 2, (y0 + y1) / 2) for x0, y0, x1, y1 in w.lines[::2]])
                w.dew = pts
            for k, (x, y) in enumerate(w.dew):
                tw = 0.6 + 0.4 * math.sin(k * 1.7 + time.monotonic() * 2)
                p.setBrush(QColor(255, 255, 255, int(200 * dawn * tw * w.integrity)))
                p.drawEllipse(QPointF(x, y), 1.3, 1.3)

    def _card(self, p):
        o = self.by_uid(self.selected) if self.selected else None
        if o is None:
            return
        p.setPen(QPen(QColor(255, 220, 120, 200), 1.2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(o.x, o.y), o.R * 0.8 + 6, o.R * 0.8 + 6)
        stage = ("old" if o.old() else "adult" if o.scale >= 1 else
                 "juvenile" if o.scale > 0.5 else "spiderling")
        lines = [f"{o.name} {'♀' if o.sex == 'f' else '♂'}  ·  {common_name(o.base_sp['name'])}",
                 f"{stage} · {o.age_s / (DAY_MINUTES * 60 or 86400):.1f} days old · gen {o.gen}",
                 f"kills {o.kills} · young {o.children} · meals {o.meals}",
                 f"{doing(o)}" + ("  ·  carrying eggs" if o.gravid_at or o.carry_sac else "")]
        x = min(o.x + o.R + 14, self.width() - 250)
        y = max(10, o.y - 50)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 22, 28, 215))
        p.drawRoundedRect(QRectF(x, y, 240, 88), 8, 8)
        p.setBrush(QColor(200, 80, 60))
        p.drawRoundedRect(QRectF(x + 10, y + 74, 220 * o.hunger, 5), 2, 2)
        p.setPen(QColor("#f0f0f0"))
        p.setFont(QFont("Sans", 9))
        for i, t in enumerate(lines):
            p.drawText(QPointF(x + 10, y + 18 + i * 15), t)

    # ── save & resume ──

    def save(self):
        try:
            data = snapshot(self)
            os.makedirs(SAVE_DIR, exist_ok=True)
            tmp = SAVE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, SAVE_FILE)
        except Exception as e:
            print("save failed:", e)

    def restore(self):
        try:
            with open(SAVE_FILE) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        try:
            rebuild(self, data)
        except Exception as e:
            print("could not restore colony, starting fresh:", e)
            self.butterflies = []
            self.eco.webs, self.eco.sacs = [], []
            return False
        self.journal.add(f"The colony wakes up again: {len(self.living())} spiders, "
                         f"{len(self.eco.webs)} webs", "info")
        return True


# ── persistence ─────────────────────────────────────────

def snapshot(ov):
    eco = ov.eco
    now = time.monotonic()
    live = [o for o in ov.living() if o.state not in ("balloon",)]
    webs = [w for w in eco.webs if w.integrity > 0.05]
    widx = {id(w): i for i, w in enumerate(webs)}
    cols, cidx = [], {}
    for o in live:
        if o.colony is not None and id(o.colony) not in cidx:
            cidx[id(o.colony)] = len(cols)
            cols.append({"web": widx.get(id(o.colony["web"]))})
    spiders = []
    for o in live:
        spiders.append(dict(
            uid=o.uid, species=o.base_sp["name"], sex=o.sex, scale=o.scale, size=o.size_roll,
            x=o.x, y=o.y, angle=o.angle, hunger=o.hunger, age=o.age_s, life=o.lifespan_s,
            name=o.name, gen=o.gen, mother=o.mother_uid, kills=o.kills, children=o.children,
            meals=o.meals, gravid=(o.gravid_at - now) if o.gravid_at else None,
            variant=o.variant, carry=o.carry_sac, web=widx.get(id(o.web)), home=o.home,
            colony=cidx.get(id(o.colony)), burrow=getattr(o, "burrow", None)
            if o.base_sp["spawn"] == "burrow" else None))
    return dict(
        version=1, saved=time.time(), age=ov.clock.age, released=ov.released,
        stats=eco.stats, journal=ov.journal.entries[-400:], history=ov.history[-1500:],
        registry={str(k): v for k, v in ov.registry.items()}, spiders=spiders, colonies=cols,
        webs=[dict(kind=w.kind, cx=w.cx, cy=w.cy, r=w.r, corner=w.corner, progress=w.progress,
                   integrity=w.integrity, species=w.species) for w in webs],
        sacs=[dict(mother=s.mother.uid, species=s.base["name"], x=s.x, y=s.y,
                   hatch=s.hatch_at - now, carried=s.carried) for s in eco.sacs])


class _Stub:
    def __init__(self, name):
        self.sp = {"name": name}


def rebuild(ov, d):
    eco = ov.eco
    now = time.monotonic()
    by_name = {sp["name"]: sp for sp in SPECIES}
    ov.clock.age = d["age"]
    ov.released = max(S.INITIAL_COUNT, d.get("released", 0))
    ov.next_immigrant = now + 60
    eco.stats.update(d.get("stats", {}))
    ov.journal.entries = [tuple(e) for e in d.get("journal", [])]
    ov.history = [(a, c) for a, c in d.get("history", [])]
    ov.registry = {int(k): v for k, v in d.get("registry", {}).items()}
    webs = []
    for w in d.get("webs", []):
        web = Web(_Stub(w["species"]), w["kind"], w["cx"], w["cy"], w["r"], tuple(w["corner"]))
        web.owner = None
        web.progress, web.integrity = w["progress"], w["integrity"]
        webs.append(web)
    eco.webs = webs
    cols = [{"members": set(), "web": webs[c["web"]] if c["web"] is not None else None}
            for c in d.get("colonies", [])]
    for c in cols:
        if c["web"] is not None:
            c["web"].colony = c
    by_uid = {}
    for r in d.get("spiders", []):
        base = by_name.get(r["species"])
        if base is None:
            continue
        o = Spider(base, ov.sw, ov.sh, sex=r["sex"], scale=r["scale"], size_roll=r["size"])
        for k_src, k_dst in (("uid", "uid"), ("hunger", "hunger"), ("age", "age_s"),
                             ("life", "lifespan_s"), ("name", "name"), ("gen", "gen"),
                             ("mother", "mother_uid"), ("kills", "kills"), ("children", "children"),
                             ("meals", "meals"), ("variant", "variant"), ("carry", "carry_sac")):
            setattr(o, k_dst, r[k_src])
        o.x, o.y, o.angle = r["x"], r["y"], r["angle"]
        o.gravid_at = now + r["gravid"] if r["gravid"] is not None else None
        o.immune_until = now + 10
        o.settle_at = now + random.uniform(5, 20)
        o.home = tuple(r["home"]) if r["home"] else None
        if r["colony"] is not None and r["colony"] < len(cols):
            o.colony = cols[r["colony"]]
            o.colony["members"].add(o)
        if r["web"] is not None and r["web"] < len(webs):
            o.web = webs[r["web"]]
            if o.web.owner is None:
                o.web.owner = o
        o.plant_all()
        if base["spawn"] == "burrow" and r.get("burrow"):
            o.burrow = tuple(r["burrow"])
            o.x, o.y = o.burrow
            o.lid_angle = o.angle
            o.hidden = True
            o._set("burrow", 99999)
        elif o.web is not None or o.home is not None:
            o._set("hub", 99999)
        else:
            o._start_pause(30, 200)
        ov.butterflies.append(o)
        by_uid[o.uid] = o
    S._uid[0] = max([S._uid[0]] + list(by_uid) + list(ov.registry))
    for s in d.get("sacs", []):
        m = by_uid.get(s["mother"])
        if m is None:
            continue
        sac = EggSac(m, s["x"], s["y"], now + s["hatch"])
        sac.carried = s["carried"]
        eco.sacs.append(sac)


def make_icon(size):
    """A house spider on transparent background, for the tray / app icon."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    base = next(sp for sp in SPECIES if sp["name"] == "redknee_tarantula")
    o = Spider(base, size, size, sex="f", size_roll=base["size"][0])
    k = size * 0.16 / max(1.0, o.s)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(size / 2, size / 2)
    p.scale(k, k)
    o.x = o.y = 0.0
    o.angle = -math.pi / 2
    o.plant_all()
    o.pose()
    S.draw_shadow(p, o)
    S.draw_spider(p, o)
    p.end()
    return pm


def main(fresh=None):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    fresh = ("--fresh" in sys.argv) if fresh is None else fresh
    print("Arachne colony — Ctrl+Shift+J journal, Ctrl+Shift+B save & stop"
          + ("  (fresh start)" if fresh else ""))
    overlay = ColonyOverlay(fresh=fresh)
    overlay._tray()
    server = QLocalServer()                   # arachne's toggle talks to us here
    QLocalServer.removeServer(arachne.SERVER)
    server.listen(arachne.SERVER)

    def on_conn():
        c = server.nextPendingConnection()
        c.waitForReadyRead(300)
        cmd = bytes(c.readAll()).strip()
        if cmd == b"quit":
            overlay._quit()
        elif cmd == b"journal":
            overlay.toggle_journal()
    server.newConnection.connect(on_conn)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *a: overlay._quit())
    keep = QTimer()                           # lets Python notice signals while Qt runs
    keep.timeout.connect(lambda: None)
    keep.start(300)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
