# Arachne 🕷️

A living spider colony on your desktop. 31 researched species crawl over your
screen with real gaits and shadows, spin webs in the corners, hunt flies and each
other, court, lay egg sacs, raise spiderlings that balloon away or grow up — and
the colony carries on from where you left it.

## Download

Get the installer for your system from the
**[latest release](https://github.com/AbhinavSarkarr/arachne/releases/latest)**:

| System | File |
|---|---|
| Windows 10/11 | `Arachne-Windows-Setup.exe` |
| macOS (Apple Silicon) | `Arachne-macOS.pkg` (right-click → Open the first time) |
| Linux (Ubuntu/Debian) | `Arachne-Linux.deb` → `sudo apt install ./Arachne-Linux.deb` |

## Use

- **Ctrl+Shift+B** starts the colony (resuming the save); press again to save & stop.
- **Ctrl+Shift+F** drops a fly at your cursor — watch who gets it.
- Click a spider to see its name, age, kills and family; drag to pick it up.
- Tray icon → **Colony Journal** (log, population graph, family tree, ★ favourites,
  **Spider-dex** of every species and behaviour you've witnessed), **photo**,
  **10-second clip** (animated PNG), **sound**, real-clock / real-calendar modes.

## What happens in the box

Spiders are drawn from anatomy: tapered jointed legs with spines and hair, an abdomen
that swings on its waist and breathes, moving palps, eyes that glint toward the light
(and shine back at night when your cursor comes close), glossy or furry or iridescent
cuticles. Orb webs are spun step by step — bridge, frame, radials, temporary spiral,
sticky spiral — and eaten and rebuilt each night; webs sway in the wind, tremble with
caught prey, tear, and glitter after rain.

Day/night (nocturnal hunters vs. daytime jumpers), four seasons, insects that get
caught in webs, web owners that rush to the vibration, cellar spiders that pluck
other spiders' webs to lure them out, spitting spiders, dewdrop spiders that steal
prey, social cobweb spiders that hunt together, courtship dances and sexual
cannibalism, egg sacs, spiderlings, molting, old age — tuned from arachnology
research. Also: rain and wind, ant trails, mosquitoes and dragonflies, a tarantula hawk
wasp that hunts big spiders (golden wheels cartwheel away), wolf mothers carrying their
young, nursery-web males courting with a silk-wrapped gift, trapdoor trip-lines, crab
spiders ambushing bees on flowers, personalities, memory and old age.

## Run from source

```bash
python3 -m venv venv && venv/bin/pip install PyQt5 numpy python-xlib
venv/bin/python arachne.py            # toggle
venv/bin/python arachne.py --fresh    # brand-new colony
./install-arachne.sh                  # Linux: menu entry + Ctrl+Shift+B
```

Built on [Papillon](https://github.com/shivvamm/papillion) by shivvamm.
