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
                         QPixmap, QIcon, QPolygonF, QRadialGradient, QImage)
from PyQt5.QtNetwork import QLocalServer

import arachne
import dex
import struct
import zlib
import tempfile
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice

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


SETTINGS_FILE = os.path.join(SAVE_DIR, "settings.json")
SETTINGS = {"clock": "compressed", "seasons": "compressed", "sound": False, "favourites": [],
            "dex_species": {}, "dex_behaviours": {}}
try:
    with open(SETTINGS_FILE) as _f:
        SETTINGS.update(json.load(_f))
except (OSError, ValueError):
    pass


def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(SETTINGS, f)
    except OSError:
        pass


def _png_bytes(img):
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _chunks(png):
    i, out = 8, []
    while i < len(png):
        n = struct.unpack(">I", png[i:i + 4])[0]
        out.append((png[i + 4:i + 8], png[i + 8:i + 8 + n]))
        i += 12 + n
    return out


def write_apng(path, frames, fps):
    """Animated PNG from QImages — plays in any browser, needs no ffmpeg."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    first = _chunks(_png_bytes(frames[0]))
    ihdr = next(d for k, d in first if k == b"IHDR")
    w, h = struct.unpack(">II", ihdr[:8])
    out = [b"\x89PNG\r\n\x1a\n", chunk(b"IHDR", ihdr),
           chunk(b"acTL", struct.pack(">II", len(frames), 0))]
    seq = 0
    for n, img in enumerate(frames):
        out.append(chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, w, h, 0, 0, 1, fps, 0, 0)))
        seq += 1
        for kind, data in _chunks(_png_bytes(img)):
            if kind != b"IDAT":
                continue
            if n == 0:
                out.append(chunk(b"IDAT", data))
            else:
                out.append(chunk(b"fdAT", struct.pack(">I", seq) + data))
                seq += 1
    out.append(chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(b"".join(out))


def pictures_dir():
    d = os.path.join(os.path.expanduser("~"), "Pictures", "Arachne")
    os.makedirs(d, exist_ok=True)
    return d


# ── synthesized sounds (no audio files shipped) ──

def _wav(path, samples, rate=22050):
    data = b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 30000)) for s in samples)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
                struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) +
                b"data" + struct.pack("<I", len(data)) + data)


def make_sounds():
    d = os.path.join(SAVE_DIR, "sounds")
    os.makedirs(d, exist_ok=True)
    rng = random.Random(7)
    r = 22050
    specs = {
        "hiss": [rng.uniform(-1, 1) * 0.5 * math.sin(math.pi * i / (r * 0.7)) for i in range(int(r * 0.7))],
        "buzz": [0.25 * (((i * 210 / r) % 1) * 2 - 1) * (0.6 + 0.4 * math.sin(i / r * 40))
                 * math.sin(math.pi * i / (r * 0.6)) for i in range(int(r * 0.6))],
        "tick": [math.exp(-i / 90) * math.sin(i * 0.9) * 0.8 for i in range(int(r * 0.05))],
        "rain": [rng.uniform(-1, 1) * 0.18 * (0.7 + 0.3 * math.sin(i / r * 3)) for i in range(r * 2)],
    }
    out = {}
    for name, s in specs.items():
        p = os.path.join(d, name + ".wav")
        if not os.path.exists(p):
            _wav(p, s, r)
        out[name] = p
    return out


def _southern():
    try:
        zone = os.path.realpath("/etc/localtime")
    except OSError:
        zone = ""
    zone = os.environ.get("TZ", zone)
    return any(k in zone for k in ("Australia/", "Pacific/Auckland", "America/Argentina",
                                    "America/Santiago", "America/Sao_Paulo", "America/Montevideo",
                                    "Africa/Johannesburg", "Africa/Maputo", "Antarctica/"))


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
        if DAY_MINUTES and SETTINGS["clock"] != "real":
            return (self.age / (DAY_MINUTES * 60) + 0.3) % 1.0
        t = time.localtime()
        return (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec) / 86400

    def night(self):
        sun = math.sin(math.tau * (self.phase() - 0.25))
        return max(0.0, min(1.0, 0.5 - sun * 1.6))

    def day(self):
        return int(self.age / (DAY_MINUTES * 60)) + 1 if DAY_MINUTES else 1

    def season(self):
        if SETTINGS["seasons"] == "real":         # from the calendar (and hemisphere)
            m = time.localtime().tm_mon
            s = ("winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer",
                 "autumn", "autumn", "autumn", "winter")[m - 1]
            if _southern():
                s = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}[s]
            return s
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
    COLS = ("★", "Name", "Species", "Sex", "Stage", "Age (days)", "Kills", "Young", "Gen", "Doing")

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
        self.table.cellClicked.connect(self._star)
        tabs.addTab(self.table, "Spiders")
        self.dex = QTreeWidget()
        self.dex.setHeaderLabels(["Spider-dex", "Rarity", "Seen"])
        self.dex.setWordWrap(True)
        tabs.addTab(self.dex, "Spider-dex")
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
        self._fill_dex()

    def _fill_table(self, live):
        self._filling = True
        self.table.setRowCount(len(live))
        for r, o in enumerate(sorted(live, key=lambda o: (o.base_sp["name"], o.name))):
            stage = ("old" if o.old() else "adult" if o.scale >= 1 else
                     "juvenile" if o.scale > 0.5 else "spiderling")
            vals = ("★" if o.uid in self.colony.favs else "☆", o.name, common_name(o.base_sp["name"]),
                    "♀" if o.sex == "f" else "♂", stage,
                    f"{o.age_s / (DAY_MINUTES * 60 or 86400):.1f}", o.kills, o.children, o.gen,
                    doing(o))
            for col, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setData(Qt.UserRole, o.uid)
                if col != 1:
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
        if self._filling or item.column() != 1:
            return
        o = self.colony.by_uid(item.data(Qt.UserRole))
        if o and item.text().strip():
            o.name = item.text().strip()[:20]
            self.colony.registry.setdefault(o.uid, {})["name"] = o.name

    def _picked(self):
        rows = self.table.selectedItems()
        if rows:
            uid = rows[0].data(Qt.UserRole)
            self.colony.selected = uid
            if rows[0].column() == 0 or any(r.column() == 0 for r in rows[:1]):
                pass

    def _star(self, row, col):
        if col != 0:
            return
        uid = self.table.item(row, 0).data(Qt.UserRole)
        favs = self.colony.favs
        favs.symmetric_difference_update({uid})
        self.refresh()

    def _fill_dex(self):
        seen_sp = SETTINGS["dex_species"]
        seen_b = SETTINGS["dex_behaviours"]
        self.dex.clear()
        tiers = ("Common", "Uncommon", "Rare", "Ultra-rare")
        n_sp = sum(1 for sp in SPECIES if sp["name"] in seen_sp)
        n_b = sum(1 for b in dex.BEHAVIOURS if b[0] in seen_b)
        top = QTreeWidgetItem([f"Species  ({n_sp}/{len(SPECIES)})", "", ""])
        self.dex.addTopLevelItem(top)
        for sp in sorted(SPECIES, key=lambda s: (s["rarity"], s["name"])):
            got = sp["name"] in seen_sp
            it = QTreeWidgetItem([common_name(sp["name"]) if got else "? ? ?",
                                  tiers[sp["rarity"]], "✓ " + seen_sp[sp["name"]] if got else ""])
            if got:
                fact = QTreeWidgetItem([dex.FACTS.get(sp["name"], ""), "", ""])
                it.addChild(fact)
            top.addChild(it)
        btop = QTreeWidgetItem([f"Behaviours witnessed  ({n_b}/{len(dex.BEHAVIOURS)})", "", ""])
        self.dex.addTopLevelItem(btop)
        for bid, label, _ in dex.BEHAVIOURS:
            btop.addChild(QTreeWidgetItem([label if bid in seen_b else "? ? ?", "",
                                           "✓ " + seen_b[bid] if bid in seen_b else ""]))
        top.setExpanded(True)
        btop.setExpanded(True)


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
        self.streaks, self.glass = [], []
        self.favs = set()
        self.sounds = None
        self.sfx = {}
        self.clip = None
        self.last_states = {}
        self.selected = None
        self.last_season = None
        self.last_night = None
        self.still_t = time.monotonic()
        self.press = None
        super().__init__()
        self.desktop = Desktop(self)
        self.journal_win = None
        self.journal.listeners.append(self._noticed)
        restored = (not fresh) and self.restore()
        if not restored:
            self.journal.add("A new colony begins: spiders are being released into the box", "info")
        S.WORLD.ambient_full = None
        self._sample_screen()
        for t, ms, fn in ((None, 3000, self._sample_screen),
                          (None, AUTOSAVE_S * 1000, self.save), (None, 1000, self.desktop.scan),
                          (None, 30000, self._sample)):
            tm = QTimer(self)
            tm.timeout.connect(fn)
            tm.start(ms)
        self._sample()

    # ── discoveries, favourites ──

    def _toast(self, title, text):
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.showMessage(title, text, QIcon(make_icon(64)), 6000)

    def _noticed(self, e):
        stamp, text, kind = e
        for bid, label, words in dex.BEHAVIOURS:
            if bid not in SETTINGS["dex_behaviours"] and any(w in text for w in words):
                SETTINGS["dex_behaviours"][bid] = self.clock.label()
                save_settings()
                self._toast("Spider-dex: new behaviour!", f"{label} — {text}")
        for o in self.living():                   # favourites: tell me when something happens
            if o.uid in self.favs and o.name in text:
                self._toast(f"★ {o.name}", text)
                break

    def _discover(self):
        for o in self.living():
            name = o.base_sp["name"]
            if name not in SETTINGS["dex_species"]:
                SETTINGS["dex_species"][name] = self.clock.label()
                save_settings()
                self._toast("Spider-dex: new species!",
                            f"{common_name(name)} — {dex.FACTS.get(name, '')}")

    def feed(self):
        """Drop a fly at the cursor."""
        b = S.Insect("fly", self.sw, self.sh)
        b.x, b.y = self.mouse_x + random.uniform(-15, 15), self.mouse_y + random.uniform(-15, 15)
        b.z, b.state, b.timer = 18.0, "land", random.randint(300, 600)
        S.WORLD.insects.append(b)
        self.journal.add("you dropped a fly into the box", "insect")

    def _frame_image(self):
        """The colony composited over the desktop (or a dark backdrop if it can't be seen)."""
        img = QImage(self.width(), self.height(), QImage.Format_ARGB32_Premultiplied)
        bg = S.WORLD.ambient_full
        if bg is not None:
            p = QPainter(img)
            p.drawImage(self.rect(), bg)
            p.end()
        else:
            img.fill(QColor("#2b2f36"))
        self.render(img)
        return img

    def photo(self):
        path = os.path.join(pictures_dir(), time.strftime("arachne-%Y%m%d-%H%M%S.png"))
        self._frame_image().save(path)
        self.journal.add(f"photo saved: {path}", "info")
        self._toast("Photo saved", path)

    def record_clip(self, secs=10, fps=12):
        if self.clip is not None:
            return
        self.clip = []
        self._toast("Recording", f"{secs}-second clip…")

        def grab():
            img = self._frame_image().scaled(self.width() // 2, self.height() // 2,
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.clip.append(img)
            if len(self.clip) >= secs * fps:
                t.stop()
                path = os.path.join(pictures_dir(), time.strftime("arachne-%Y%m%d-%H%M%S.apng"))
                write_apng(path, self.clip, fps)
                self.clip = None
                self.journal.add(f"clip saved: {path}", "info")
                self._toast("Clip saved", path + "  (open it in a web browser)")
        t = QTimer(self)
        t.timeout.connect(grab)
        t.start(int(1000 / fps))
        self._clip_timer = t

    def _sound(self):
        if not SETTINGS["sound"]:
            if self.sfx.get("rain") is not None and self.sfx["rain"].isPlaying():
                self.sfx["rain"].stop()
            return
        if self.sounds is None:
            try:
                from PyQt5.QtMultimedia import QSoundEffect
                from PyQt5.QtCore import QUrl
                self.sounds = make_sounds()
                for k, path in self.sounds.items():
                    e = QSoundEffect(self)
                    e.setSource(QUrl.fromLocalFile(path))
                    e.setVolume(0.35)
                    self.sfx[k] = e
                self.sfx["rain"].setLoopCount(-2)       # QSoundEffect.Infinite
            except Exception:
                SETTINGS["sound"] = False
                return
        rain = self.sfx.get("rain")
        if rain is not None:
            if S.WORLD.rain > 0.2 and not rain.isPlaying():
                rain.play()
            elif S.WORLD.rain < 0.1 and rain.isPlaying():
                rain.stop()
            rain.setVolume(0.25 * S.WORLD.rain)
        for o in self.living():
            prev = self.last_states.get(o.uid)
            st = (o.state, o.special)
            if prev != st:
                if st == ("special", "hiss") or st == ("special", "threat"):
                    self.sfx["hiss"].play()
                elif prev and prev[0] == "hop" and o.state != "hop":
                    self.sfx["tick"].play()
                self.last_states[o.uid] = st
        mx, my = self.mouse_x, self.mouse_y
        if random.random() < 0.004 and any(b.state == "fly" and math.hypot(b.x - mx, b.y - my) < 120
                                           for b in S.WORLD.insects):
            self.sfx["buzz"].play()

    # ── helpers ──

    def living(self):
        return [o for o in self.butterflies if isinstance(o, Spider)
                and o.state not in S.DEADISH and not o.gone and not o.exuvia]

    def by_uid(self, uid):
        return next((o for o in self.living() if o.uid == uid), None)

    def _sample_screen(self):
        """What's behind us, for light & shadow colour. Wayland returns black: then stay off."""
        if getattr(self, "_no_screen", False):
            return
        try:
            scr = QApplication.primaryScreen()
            shot = scr.grabWindow(0).toImage() if scr is not None else QImage()
            if shot.isNull():
                self._no_screen = True
                return
            small = shot.scaled(64, 36, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            lum = sum(QColor(small.pixel(x, y)).lightness() for x in range(0, 64, 8)
                      for y in range(0, 36, 6))
            if shot.isNull() or lum == 0:
                self._no_screen = True
                S.WORLD.ambient = S.WORLD.ambient_full = None
                return
            S.WORLD.ambient = small
            S.WORLD.ambient_size = (self.sw, self.sh)
            S.WORLD.ambient_full = shot
        except Exception:
            self._no_screen = True

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
        if self.physics_steps % 30 == 0:
            self._discover()
            self._sound()
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
        menu.addAction("Drop a fly  (Ctrl+Shift+F)", self.feed)
        menu.addAction("Take a photo", self.photo)
        menu.addAction("Record a 10-second clip", self.record_clip)
        snd = menu.addAction("Sound")
        snd.setCheckable(True)
        snd.setChecked(SETTINGS["sound"])
        snd.toggled.connect(lambda on: (SETTINGS.update(sound=on), save_settings()))
        menu.addSeparator()
        real_clock = menu.addAction("Day/night follows my clock")
        real_clock.setCheckable(True)
        real_clock.setChecked(SETTINGS["clock"] == "real")
        real_clock.toggled.connect(lambda on: (SETTINGS.update(clock="real" if on else "compressed"),
                                                save_settings()))
        real_seasons = menu.addAction("Seasons follow the calendar")
        real_seasons.setCheckable(True)
        real_seasons.setChecked(SETTINGS["seasons"] == "real")
        real_seasons.toggled.connect(lambda on: (SETTINGS.update(seasons="real" if on else "compressed"),
                                                  save_settings()))
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
        for w in self.eco.wasps:
            S.draw_wasp(p, w, True)
            S.draw_wasp(p, w, False)
        for t in self.eco.trails:
            S.draw_ants(p, t, True)
            S.draw_ants(p, t, False)
        self._rain(p)
        self._card(p)
        p.end()

    def _dew(self, p):
        ph = self.clock.phase()
        dawn = max(0.0, 1 - abs(ph - 0.27) / 0.06)       # dew around sunrise, drops after rain
        p.setPen(Qt.NoPen)
        for w in self.eco.webs:
            wet = max(dawn, w.wet)
            if w.progress < 1 or w.integrity < 0.4 or wet <= 0.02:
                continue
            if not hasattr(w, "dew"):
                pts = ([(q.x(), q.y()) for q in w.spiral[::7]] if w.kind == "orb" else
                       [((x0 + x1) / 2, (y0 + y1) / 2) for x0, y0, x1, y1 in w.lines[::2]])
                w.dew = pts
            for k, (x, y) in enumerate(w.dew):
                tw = 0.6 + 0.4 * math.sin(k * 1.7 + time.monotonic() * 2)
                rr = 1.3 + 0.6 * w.wet
                p.setPen(QPen(QColor(60, 70, 90, int(90 * wet * w.integrity)), 0.5))
                p.setBrush(QColor(255, 255, 255, int(200 * wet * tw * w.integrity)))
                p.drawEllipse(QPointF(x, y), rr, rr)     # a lens of water: dark rim, bright body
                p.setPen(Qt.NoPen)
                if w.wet > 0.3:                   # light caught in each drop
                    p.setBrush(QColor(255, 255, 255, int(230 * w.wet)))
                    p.drawEllipse(QPointF(x - 0.5, y - 0.5), 0.5, 0.5)

    def _rain(self, p):
        r = S.WORLD.rain
        if r < 0.02 and not self.glass:
            self.streaks = []
            return
        want = int(170 * r)                     # falling streaks
        while len(self.streaks) < want:
            self.streaks.append([random.uniform(0, self.sw), random.uniform(-self.sh, 0),
                                 random.uniform(14, 22), random.uniform(10, 24)])
        del self.streaks[want:]
        lean = S.WORLD.wind * 0.35
        for d in self.streaks:
            d[1] += d[2]
            d[0] += d[2] * lean
            if d[1] > self.sh:
                d[0], d[1] = random.uniform(0, self.sw), random.uniform(-80, 0)
        for pen, off in ((QPen(QColor(40, 50, 70, int(45 * r)), 1.4), 1.0),
                         (QPen(QColor(215, 228, 245, int(110 * r)), 1.0), 0.0)):
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)                       # dark edge reads on white, light on dark
            for d in self.streaks:
                p.drawLine(QPointF(d[0] + off, d[1] + off),
                           QPointF(d[0] - d[3] * lean + off, d[1] - d[3] + off))
        if r > 0.3 and len(self.glass) < 26 and random.random() < 0.1:
            self.glass.append([random.uniform(0, self.sw), random.uniform(0, self.sh * 0.6),
                               random.uniform(2.5, 5), 0.0, []])
        keep = []
        for g in self.glass:                    # drops sliding down the screen, leaving trails
            g[3] = g[3] + 0.02 if random.random() < 0.7 else 0
            g[1] += g[3] * g[2] * 0.6
            g[0] += math.sin(g[1] * 0.05) * 0.2
            g[4].append((g[0], g[1]))
            del g[4][:-60]
            if len(g[4]) > 2:
                p.setPen(QPen(QColor(220, 230, 245, 50), g[2] * 0.5, Qt.SolidLine, Qt.RoundCap))
                p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in g[4]]))
            grad = QRadialGradient(QPointF(g[0] - g[2] * 0.3, g[1] - g[2] * 0.3), g[2] * 1.3)
            grad.setColorAt(0, QColor(255, 255, 255, 170))
            grad.setColorAt(1, QColor(150, 170, 200, 60))
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QPointF(g[0], g[1]), g[2], g[2] * 1.15)
            if g[1] < self.sh + 10 and (r > 0.05 or random.random() > 0.003):
                keep.append(g)
        self.glass = keep

    def _card(self, p):
        o = self.by_uid(self.selected) if self.selected else None
        if o is None:
            return
        p.setPen(QPen(QColor(255, 220, 120, 200), 1.2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(o.x, o.y), o.R * 0.8 + 6, o.R * 0.8 + 6)
        stage = ("old" if o.old() else "adult" if o.scale >= 1 else
                 "juvenile" if o.scale > 0.5 else "spiderling")
        lines = [f"{'★ ' if o.uid in self.favs else ''}{o.name} {'♀' if o.sex == 'f' else '♂'}  ·  "
                 f"{common_name(o.base_sp['name'])}",
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
        favs=sorted(ov.favs),
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
    ov.favs = set(d.get("favs", []))
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
        elif cmd == b"feed":
            overlay.feed()
        elif cmd == b"photo":
            overlay.photo()
        elif cmd == b"clip":
            overlay.record_clip()
    server.newConnection.connect(on_conn)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *a: overlay._quit())
    keep = QTimer()                           # lets Python notice signals while Qt runs
    keep.timeout.connect(lambda: None)
    keep.start(300)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
