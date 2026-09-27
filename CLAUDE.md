# LabCAD — code-CAD for printable lab parts

This is a parametric-CAD workshop. The user describes a part; you own the geometry, written as build123d Python.
Favor machining/ergonomic features (chamfers, lead-ins, fillets, finger grooves, engraved labels) over sculptural
forms. Be brief, and be honest when a request would make a worse part.

First time in this repo, or the Studio isn't running yet? Follow `SETUP.md`.

## Layout
- `parts/<name>/model.py` — `P = dict(...)` of every dimension + `RANGES` (slider min/max/step) + `def build(P) -> Part` (build123d, algebra mode). Origin = part centre, Z up, mm.
- `parts/<name>/params.json` — the *live* knob values (override `model.P`). The Studio sliders write here.
- `parts/<name>/versions/vNNN.{stl,step,png,json}` — every build, numbered. Never edit or delete.
- `parts/<name>/chat.jsonl` — Studio conversation. `session.json` — your resumed session id.
- `build.py <part> -m "msg" [--set k=v]` — build + export + render → next version. Prints a JSON line.
- `render.py part.stl` — 4-view PNG (pyrender/EGL) + `_thumb.png` iso.
- `drawing.py <part> <tag>` — blueprint SVG (third-angle top/front/right, HLR hidden lines, envelope + auto hole Ø/pitch dims, title block). Studio drafts it on demand (rail button / B).
- `studio/` — the web dash (FastAPI + three.js) on :8505 (see SETUP.md).

## Families (forks)
- `parts/<name>/lineage.json` = `{parent, from_version, mode}`; `versions/vNNN.py` snapshots model.py so every version is reproducible; "Make this current" restores one.
- **derive** fork: its model.py does `from parts.<base>.model import P as BASE_P, build as base_build` and adds bespoke geometry after `base_build(P)`. Base *geometry* changes flow to derived parts on their next rebuild; base *numbers* don't (each variant pins its own params.json). If a fix belongs to every variant, edit the base's build(); if it's one variant's, edit the variant.
- **copy** fork: independent snapshot, edit freely.
- Renaming is safe from the UI (`POST /api/parts/x/rename` rewrites lineage + derived imports + version records); **never rename by hand**. Deleting moves a part to `parts/_trash/`; a base with derived children is detached first.

## Printers — `printers.py` + the Printers page
- Every part targets a printer profile (`parts/<name>/printer.json`, else the default). The feedback/new-part prompt already includes `printers.describe(part=...)` — **design to those numbers**, don't reach for the generic FDM rules below when a profile says otherwise.
- `hole_for(od, "slip"|"press", part)` gives the diameter to model (adds clearance + that printer's hole shrink). Prefer it over hard-coding a magic 0.3.
- `fit_check(envelope, part=...)` → fits / rotate / diagonal / too_big with the overage. **Check it before replying on any part that grew**; if it no longer fits, say so and offer the fix (smaller pitch, split into two, or a printer with a bigger bed).
- A profile flagged `verified: false` was seeded by LabCAD, not measured. If a design leans on one of its numbers, say which and suggest a test print.
- Services (kind `service`) have no nozzle, ignore overhangs, and carry a lead time/cost — for those, flag anything that would be expensive to iterate on, because the user can't just reprint it in an hour.

## When a Studio feedback arrives
1. Resolve pins to features yourself: coordinates are in model space, and you know the geometry (top face at z = H/2, grooves at z = 0 on y = ±W/2, etc.).
2. Number changes → edit `params.json` (or `P` defaults if it's the new normal). Geometry changes → edit `model.py`.
3. Rebuild: `.venv/bin/python build.py <part> -m "<what changed, ≤60 chars>"`. If it fails, fix and rebuild; don't reply with a broken build.
4. Look at the PNG it wrote before replying if the change is geometric.
5. Reply in ≤4 sentences. It's shown in the chat next to the new version; say what changed and any consequence the user should know (mass, clearance, print risk). Don't paste code.
6. Ambiguous → ask one question, skip the rebuild.

## FDM rules of thumb (0.4 mm nozzle unless params say otherwise)
Holes print ~0.3 mm undersize; add 0.4–0.6 mm clearance for a slip fit. First-layer chamfer 0.6–1 mm kills elephant foot. Overhangs ≤ 45° need no support; bridges ≤ 20 mm are fine. Engraving ≥ 0.4 mm deep, text ≥ 4 mm tall to read. Keep walls ≥ 2.4 mm (3 perimeters).

## Labware catalog — `labware/__init__.py`
- `dims("tube_1_5ml")` → numbers; `describe(key)` → numbers WITH source tags; `clone(key)` → revolved digital clone (bottom z=0) for fit-tests.
- Every number is tagged standard / datasheet / measured / recalled / estimated. **Never state a labware dimension as fact unless it's tagged standard/datasheet/measured, or the user gave it.** When a design hinges on a `recalled`/`estimated` number, say so in the reply and suggest calipers.
- Something's not in the catalog? WebSearch/WebFetch the manufacturer datasheet, ADD the entry with `datasheet` + ref, then use it. If you can't find one, add it as `estimated` and say so.
- The user may attach photos (side profile + a known dimension). Read them; for a new clone, derive a (z, r) profile and add it with `profile_src="from photo"`.

## Images in feedback
Every Studio message comes with `parts/<name>/shots/<stamp>_view.jpg` (their viewport, pins numbered) and maybe `_photoN.jpg`. **Read them first** — the screenshot resolves what "this edge" means far better than coordinates do.
