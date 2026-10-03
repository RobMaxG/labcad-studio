# Setting up LabCAD — instructions for the AI assistant

You're an AI coding assistant (Claude Code or similar) and your user wants LabCAD running. Work through
these steps in order, run the commands yourself, and check each result before moving on. Stop and ask the
user only where a step says **Ask**. When you're done, give them the short summary described in step 8.

Tested on Linux (Ubuntu/Pop!_OS, NVIDIA GPU) with Python 3.12. macOS and machines without a GPU should work
with the rendering fallback in step 3, but haven't been tested; tell the user if you hit something new.

## 1. Check prerequisites

- **Python 3.10–3.13** (`python3 --version`). build123d doesn't support 3.14 yet.
- **Claude Code CLI** on `PATH` and logged in (`claude --version`). The Studio's "Send to Claude" and "New"
  buttons start headless `claude -p` sessions. If `claude` lives somewhere odd, set `CLAUDE_PATH` to it
  (in the shell, or as an `Environment=` line in the systemd unit from step 5).
- **git**. Optional: **systemd** (Linux) if the user wants the Studio to start on boot.

## 2. Create the virtualenv and install

From the repo root:

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

build123d pulls in OpenCascade (`cadquery-ocp`), a big wheel. Give it a few minutes.

## 3. Check rendering works

Every build renders a 4-view PNG headlessly with pyrender. The default backend is EGL (GPU):

```bash
PYOPENGL_PLATFORM=egl .venv/bin/python -c "import pyrender; r = pyrender.OffscreenRenderer(64, 64); r.delete(); print('egl ok')"
```

If that fails (no GPU, no EGL, macOS, or a VM), try OSMesa (software rendering):

```bash
# Debian/Ubuntu: sudo apt install libosmesa6   (Ask the user before running sudo)
PYOPENGL_PLATFORM=osmesa .venv/bin/python -c "import pyrender; r = pyrender.OffscreenRenderer(64, 64); r.delete(); print('osmesa ok')"
```

Remember whichever one worked. From here on, run everything with `PYOPENGL_PLATFORM=<that>` in the
environment, and put the same value in the systemd unit in step 5.

## 4. Build the example parts (smoke test)

The repo ships five example parts with no build history. Build each one once to make v001. Do
`microfuge_rack` first, because `microfuge_strip_16` is a *derived* fork of it (it imports the rack's `build()`):

```bash
for p in microfuge_rack microfuge_strip_16 falcon_50_rack tube_1_5ml_clone sliding_viewport_w_retaining_frame; do
  .venv/bin/python build.py $p -m "v1 — example"
done
```

Each prints one JSON line (envelope, volume, mass, and a `components` list). The strip takes ~15 s and the others
a few seconds. **Open one of the PNGs** (`parts/microfuge_rack/versions/v001.png`) and look at it: you should see a
4×6 tube rack from four angles. A blank or black image means the rendering backend is wrong; go back to step 3.

`sliding_viewport_w_retaining_frame` is an **assembly**: its PNG shows three pieces in three colours, and
`parts/sliding_viewport_w_retaining_frame/versions/v001/` should hold `frame`, `door` and `key` STL + STEP files
plus `plate.3mf`. If `plate.3mf` is missing, the build printed why on stderr; the per-piece files are what matter.

This also creates `printers.json` with two placeholder printer profiles.

## 5. Start the Studio

Quick start, in the foreground:

```bash
PYOPENGL_PLATFORM=egl .venv/bin/uvicorn studio.server:app --host 127.0.0.1 --port 8505
```

Then open http://localhost:8505. If 8505 is taken, pick another port and tell the user.

To keep it running across reboots (Linux + systemd), install the template unit (it fills in this checkout's path):

```bash
mkdir -p ~/.config/systemd/user
sed "s|__LABCAD_DIR__|$PWD|g" deploy/labcad-studio.service > ~/.config/systemd/user/labcad-studio.service
# edit the PYOPENGL_PLATFORM line if step 3 needed osmesa; add Environment=CLAUDE_PATH=... if needed
systemctl --user daemon-reload && systemctl --user enable --now labcad-studio
loginctl enable-linger "$USER"   # keeps user services running when they're logged out; skip if they'd rather not
```

**Ask** the user whether they want the systemd service or will start the Studio by hand.

### About network access

The Studio listens on **127.0.0.1 only**, and that's deliberate. Anyone who can reach the page can make
Claude edit files in this repo and browse the web (the spawned sessions run with `acceptEdits` and a
tool allowlist; see `ALLOWED_TOOLS` in `studio/server.py`). If the user wants to open it from their phone
or another machine, **Ask** them first. The safe options are a private VPN such as Tailscale
(`tailscale serve --bg 8505` proxies it over HTTPS to their tailnet only) or an SSH tunnel. Don't bind to `0.0.0.0` on a
network you don't trust, and never port-forward it to the internet.

## 6. Verify the Studio end to end

1. `curl -s localhost:8505/api/parts` should list the five parts with `"versions":1`.
   Then check the live knob preview (it builds into a scratch folder and creates no version):
   `curl -s -X POST localhost:8505/api/parts/microfuge_rack/preview -H 'content-type: application/json' -d '{"params":{"pitch":19}}'`
   should return a `components` list within a few seconds (the first one is slower: it starts a warm worker).
2. Open the Studio in a browser (or have the user open it). The part should load in the 3D viewer. The
   viewer pulls three.js from a CDN, so it needs internet access.
3. Test the AI loop once: in the **Talk** tab on `microfuge_rack`, send something small like
   *"make the drain holes 5 mm"*. The status line should show the headless Claude working, and v002
   should appear. If it fails with `claude exited …`, the CLI isn't found or isn't logged in (step 1).

## 7. Set up their printer

The placeholder profiles are generic and marked `verified: false`. **Ask** the user which printer(s) they
have: model, nozzle size, and bed size if they know it. Then either fill them in on the **Printers** page
(`/printers.html`) together, or edit `printers.json` directly and set their main printer as `"default"`.
If they don't know their hole shrink, suggest they print a small test coupon with a few holes, measure it
with calipers, and enter the result. Until then, fits are educated guesses.

## 8. Hand it over

Tell the user, briefly:
- where the Studio is (URL) and how it starts (service or command);
- the three ways to begin a part: **New** (describe it in a sentence or two), **Fork** an existing part, or
  ask you to write a `model.py` directly;
- that pins (P) plus a message in **Talk** is how they ask for changes, and pasted photos help a lot; for an
  assembly they can aim a message at one piece with the **About** picker;
- that **Knobs** preview live and only save when they press *Save as version*, and the **Print** tab has every
  piece's files plus a 3MF plate, and tracks which pieces need reprinting;
- that tube and labware dimensions tagged `recalled`/`estimated` should be checked with calipers before a
  print that matters.

From then on, `CLAUDE.md` is your working contract in this repo. Read it before editing any part.

## Housekeeping notes

- `.claude/settings.json` sets `worktree.bgIsolation: none`, because the Studio serves this checkout live and
  edits made in a separate worktree would never show up. Keep it.
- Generated models (STL, STEP, 3MF) are gitignored: they're large and regenerable from `versions/vNNN.py`.
  The small version records (`vNNN.json`, `vNNN.py`, renders) can be committed; whether to is the user's call.
- Knob previews build into `parts/*/.preview/` and log to `studio/preview_worker.log`; both are scratch and ignored.
