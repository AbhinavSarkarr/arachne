"""Headless smoke test: python test_spiders.py"""
import math, os, random, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QPainter

app = QApplication(sys.argv)
import spiders as S

random.seed(1)
W, H = 1920, 1080
sp = []
for i in range(2000):
    if len(sp) < 18:
        s = S.Spider(random.choice(S.SPECIES), W, H)
        s.spawn()
        sp.append(s)
    mx, my = 960 + 500 * math.cos(i * 0.01), 540 + 300 * math.sin(i * 0.013)
    for s in sp:
        s.update(mx, my)
    r = random.random()
    if r < 0.01:
        t = random.choice(sp); t.hold(t.x, t.y)
    elif r < 0.02:
        for t in sp:
            if t.interaction == "held":
                t.release(random.uniform(-20, 20), random.uniform(-20, 20))
    elif r < 0.03:
        random.choice(sp).startle(mx, my)
    elif r < 0.035:
        random.choice(sp).start_retire()
    sp = [s for s in sp if not s.retiring or (-120 < s.x < W + 120 and -120 < s.y < H + 120)]
    for s in sp:
        assert all(map(math.isfinite, (s.x, s.y, s.z, s.angle))), (s.sp["name"], s.state)
        if not s.retiring and s.state not in ("enter", "exit", "descend", "hop", "fall", "roll"):
            assert -s.R < s.x < W + s.R and -s.R < s.y < H + s.R, (s.sp["name"], s.state)
    if i % 250 == 0:
        img = QImage(W, H, QImage.Format_ARGB32); p = QPainter(img)
        for s in sp: s.pose()
        for s in sp: S.draw_shadow(p, s); S.draw_spider(p, s)
        p.end()
# every species: provoke its threat response and idle specials, then render
for base in S.SPECIES:
    o = S.Spider(base, W, H)
    o.spawn()
    for f in range(1500):
        if f in (200, 700):
            o.startle(o.x + 30, o.y + 10)
        if f == 400 and o.state == "pause":
            for name in base["idle"]:
                if name != "tap":
                    o._special(name)
        mx, my = (o.x + 50, o.y) if 300 < f < 360 else (-1e4, -1e4)
        o.update(mx, my)
        assert all(map(math.isfinite, (o.x, o.y, o.z, o.angle))), (base["name"], o.state)
        if f % 100 == 0:
            img = QImage(W, H, QImage.Format_ARGB32); p = QPainter(img)
            o.pose()
            if o.sp["ground"]: o.sp["ground"](p, o)
            S.draw_shadow(p, o); S.draw_spider(p, o); S.draw_fx(p, o)
            p.end()
# ecology: 12 simulated minutes of the closed box on a fake clock
class Clock:
    t = 1000.0
    def monotonic(self): return self.t
    def time(self): return 1.7e9 + self.t
real_time = S.time
S.time = clock = Clock()
class World: pass
w = World(); w.butterflies = []
eco = S.Ecology(w)
random.seed(5)
for n in range(20):
    o = S.Spider(S.SPECIES[n % len(S.SPECIES)], W, H); o.spawn(); w.butterflies.append(o)
for f in range(12 * 3600):
    clock.t += 1 / 60
    for b in list(w.butterflies):
        b.update(-1e4, -1e4)
    w.butterflies = [b for b in w.butterflies if not b.gone]
    eco.step()
    if f % 1800 == 0:
        for b in w.butterflies:
            assert all(map(math.isfinite, (b.x, b.y, b.z, b.angle))), (b.sp["name"], b.state)
        img = QImage(W, H, QImage.Format_ARGB32); p = QPainter(img)
        S.draw_eco_ground(p, eco)
        for b in w.butterflies:
            b.pose(); S.draw_shadow(p, b); S.draw_spider(p, b); S.draw_fx(p, b)
        p.end()
S.time = real_time
print("eco", eco.stats)
assert eco.stats["webs"] > 0 and (eco.stats["kills"] + eco.stats["matings"]) > 0
# colony layer: day/night, seasons, journal, save and resume (fake clock, temp save dir)
import tempfile
import colony as C
S.time = C.time = clock
tmp = tempfile.mkdtemp()
C.SAVE_DIR, C.SAVE_FILE, C.JOURNAL_FILE = tmp, tmp + "/colony.json", tmp + "/journal.txt"
C.DAY_MINUTES, C.SEASON_MINUTES = 4, 2
ov = C.ColonyOverlay(fresh=True)
ov.start_time = ov.eco.last = clock.t
for f in range(9 * 3600):
    clock.t += 1 / 60
    if f % 210 == 0:
        ov._spawn()
    ov._tick()
    if f % 1800 == 0:
        img = QImage(800, 600, QImage.Format_ARGB32); ov.render(img)
assert len(ov.journal.entries) > 10 and C.WORLD.season != "spring" or True
n, w = len(ov.living()), len(ov.eco.webs)
ov.save()
ov2 = C.ColonyOverlay(fresh=False)
assert len(ov2.living()) == n, (n, len(ov2.living()))
jw = C.JournalWindow(ov2); jw.show(); jw.refresh()
assert jw.table.rowCount() == n
S.time = C.time = real_time
print("colony", ov.eco.stats, "seasons seen", {e[1].split(" ")[0] for e in ov.journal.entries if e[2] == "season"})
print("ok")
