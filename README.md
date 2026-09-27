# LabCAD

Code-CAD for printable lab parts. Describe a part in plain language; Claude writes it as a parametric
[build123d](https://github.com/gumyr/build123d) model; you look at it in the **Studio** (a local web app),
drop pins on what's wrong, and it comes back rebuilt. Every build is a numbered version with its params,
STL, STEP, and a rendered preview.

**Setting up with an AI assistant?** Point Claude Code at this repo and say *"set up LabCAD — follow SETUP.md."*
That file is written for the assistant: it installs, smoke-tests, and starts the Studio, and checks in with
you on the few choices that are yours.

## What's in the Studio
- **Viewer**: orbit, pins (P), measure (M), section cut (S), ghost a previous version (G), edges (E), blueprint drawing (B)
- **Knobs**: every dimension in the model as a slider; rebuilds directly, no AI involved
- **Talk**: "Send to Claude" with your pins, a screenshot of your view, and any photos you paste in; it edits the model and rebuilds
- **New**: start a part from a one- or two-sentence brief
- **Fork**: *derive* a variant (inherits the base's geometry) or *copy* it; the Family tab shows the tree
- **Library**, **Printers** (your machines' bed size, hole shrink, clearances, all fed to Claude), **Materials** (filament × lab-solvent compatibility)

## By hand
- Build: `.venv/bin/python build.py <part> -m "why" [--set k=v]`
- Render: `.venv/bin/python render.py part.stl`
- Drawing: `.venv/bin/python drawing.py <part> v001`
- Parts live in `parts/<name>/model.py` (`P` dict of dimensions + `RANGES` + `build(P)`); live knob values in `params.json`.

## Example parts
`microfuge_rack` (4×6 rack for 1.5 mL tubes), `microfuge_strip_16` (a derived fork of it),
`falcon_50_rack` (6 × 50 mL tubes), `tube_1_5ml_clone` (a digital tube from the `labware` catalog, for fit tests).
Tube dimensions in `labware/` are tagged by source. Many are `recalled`/`estimated`, so check them with calipers
before a print you care about.

`CLAUDE.md` is the working contract for Claude inside this repo (the Studio spawns headless `claude -p` sessions that read it).
