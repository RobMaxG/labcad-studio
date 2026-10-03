"""Assemblies: a model's build() may return several components instead of one solid.

    from assembly import Comp
    COMPONENTS = dict(frame=dict(label="Frame"), door=dict(label="Sliding door", note="print in black"))

    def build(P):
        return dict(
            frame=Comp(frame),                         # prints as built, sits as built
            door=Comp(door, at=Pos(0, 40, 2.4)),       # built the way it PRINTS; `at` puts it in the assembly
        )

Build each component in its print orientation (the face that goes on the bed at z = 0) and let `at`
place it. One build is one assembly version: every component gets its own print-ready STL/STEP, the
whole thing gets a labelled STEP + a 3MF plate, and the version records which components changed.

A build() that returns a single solid is still fine — it becomes a one-component part called "part".
"""
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from build123d import Color, Compound, Location, Pos, export_step, export_stl

PALETTE = ["#8fb4dc", "#9fcf9a", "#e39aa8", "#b8a6e6", "#d9c38f", "#7cc8c2", "#c9a07a", "#a3acb9"]
PLA = 1.24          # g/cm³, for the mass estimate


@dataclass
class Comp:
    part: object
    at: Location = field(default_factory=Location)


def _hex_color(h):
    h = h.lstrip("#")
    return Color(int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def matrix(loc):
    """Row-major 4×4 of a Location (three.js Matrix4.set takes row-major)."""
    t = loc.wrapped.Transformation()
    rows = [[t.Value(r, c) for c in range(1, 5)] for r in range(1, 4)]
    return [round(v, 6) for row in rows for v in row] + [0, 0, 0, 1]


def fingerprint(part):
    """Same geometry → same print. Cheap invariants, rounded so float noise can't fake a change."""
    bb = part.bounding_box()
    key = (f"{part.volume:.1f}|{part.area:.1f}|{bb.size.X:.2f}|{bb.size.Y:.2f}|{bb.size.Z:.2f}"
           f"|{len(part.faces())}|{len(part.edges())}")
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def normalize(result, mod):
    """build() result → (kind, [component dicts]). Each part is moved to print position (centred, z ≥ 0);
    `at` is adjusted so at * part still lands where the model put it."""
    meta_all = getattr(mod, "COMPONENTS", None) or {}
    if isinstance(result, dict):
        kind, items = "assembly", list(result.items())
    else:
        kind, items = "part", [("part", result)]
    out = []
    for i, (name, v) in enumerate(items):
        if isinstance(v, Comp):
            part, at = v.part, v.at
        elif isinstance(v, tuple):
            part, at = v[0], v[1]
        else:
            part, at = v, Location()
        bb = part.bounding_box()
        c = bb.center()
        shift = Pos(-c.X, -c.Y, -bb.min.Z)
        meta = meta_all.get(name, {})
        out.append(dict(
            name=name,
            label=meta.get("label") or name.replace("_", " ").capitalize(),
            color=meta.get("color") or PALETTE[i % len(PALETTE)],
            qty=int(meta.get("qty", 1)),
            note=meta.get("note", ""),
            filament=meta.get("filament", ""),
            part=shift * part,
            at=at * shift.inverse(),
        ))
    return kind, out


def realize(mod, P, outdir, part_name=None, fine=True, step=True):
    """Build → per-component files in `outdir` + a description of what was built. Shared by real builds
    and knob previews, so a preview can never disagree with the version it becomes."""
    import printers
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    kind, comps = normalize(mod.build(P), mod)
    t_build = time.time() - t0
    tol, ang = (0.02, 0.1) if fine else (0.05, 0.2)
    recs, placed = [], []
    for c in comps:
        p = c["part"]
        export_stl(p, str(outdir / f"{c['name']}.stl"), tolerance=tol, angular_tolerance=ang)
        if step:
            export_step(p, str(outdir / f"{c['name']}.step"))
        bb = p.bounding_box()
        env = [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)]
        fit = printers.fit_check(env, part=part_name) if part_name else None
        recs.append(dict(name=c["name"], label=c["label"], color=c["color"], qty=c["qty"], note=c["note"],
                         filament=c["filament"], matrix=matrix(c["at"]), envelope=env,
                         volume_cm3=round(p.volume / 1000, 2), mass_g_pla=round(p.volume / 1000 * PLA, 1),
                         fingerprint=fingerprint(p), fit=fit))
        q = c["at"] * p
        q.label = c["label"]
        q.color = _hex_color(c["color"])
        placed.append(q)
    asm = Compound(children=placed) if len(placed) > 1 else placed[0]
    bb = asm.bounding_box()
    vol = sum(r["volume_cm3"] * r["qty"] for r in recs)
    return dict(kind=kind, components=recs, assembly=asm,
                envelope=[round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)],
                bbox=[[round(bb.min.X, 2), round(bb.min.Y, 2), round(bb.min.Z, 2)],
                      [round(bb.max.X, 2), round(bb.max.Y, 2), round(bb.max.Z, 2)]],
                volume_cm3=round(vol, 1), mass_g_pla=round(vol * PLA, 1), build_s=round(t_build, 2),
                _parts=comps)


def write_plate(comps, path, gap=10.0):
    """One 3MF with every print (qty copies) in a row — slicers open it as separate objects."""
    from build123d import Mesher
    m, x = Mesher(), 0.0
    for c in comps:
        p = c["part"]
        bb = p.bounding_box()
        for k in range(c["qty"]):
            m.add_shape(Pos(x - bb.min.X, -bb.center().Y, 0) * p, part_number=f"{c['name']}{'' if c['qty'] == 1 else k + 1}")
            x += bb.size.X + gap
    m.write(str(path))


def changes(prev, cur):
    """Per-component status vs the previous version: new / changed / same / removed."""
    if not prev or not prev.get("components"):
        return {c["name"]: "new" for c in cur}
    before = {c["name"]: c["fingerprint"] for c in prev["components"]}
    out = {c["name"]: ("new" if c["name"] not in before else
                       "same" if before[c["name"]] == c["fingerprint"] else "changed") for c in cur}
    for n in before:
        if n not in out:
            out[n] = "removed"
    return out
