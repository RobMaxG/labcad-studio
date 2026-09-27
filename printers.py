"""Printer profiles — where a part will actually be made, and the numbers that follow from it.

A profile owns the fabrication numbers a model needs, so no model hard-codes "0.3 mm undersize"
again. Pull them instead:

    from printers import hole_for, prof
    hole_for(10.8, "slip")        # tube OD → well diameter on the part's target printer
    prof()["min_wall"]            # thinnest wall that printer can actually do

`verified` is False on anything LabCAD seeded. The Printers page shows those as unverified until
you edit them, because a tolerance nobody measured is a guess wearing a number's clothes.

Store: printers.json at the repo root. Per-part target: parts/<name>/printer.json.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STORE = ROOT / "printers.json"

# Fields every profile carries. Services leave the FDM-only ones at None.
FIELDS = dict(
    name="", kind="fdm", where="", process="",
    bed=[250.0, 210.0, 220.0],          # usable x, y, z in mm
    nozzle=0.4, layer=0.2,
    hole_shrink=0.3,                    # holes come out this much undersize
    xy_tolerance=0.2,                   # ± on an outside dimension
    clearance_slip=0.4,                 # add for a part that must drop in
    clearance_press=0.1,                # add for a part that must stay put
    min_wall=1.2, min_feature=0.8, max_overhang=45.0,
    materials=["PLA"], lead_time="", cost_note="", notes="",
    verified=False,
)

SEED = {
    "default": "generic_fdm",
    "printers": {
        "generic_fdm": dict(FIELDS, name="Generic FDM 0.4 mm", kind="fdm", where="placeholder",
                            materials=["PLA", "PETG"],
                            notes="LabCAD's starting point, not a real machine. Replace it with your own printers — "
                                  "bed size and hole shrink are the two numbers that change parts the most."),
        "service_sls": dict(FIELDS, name="Send-off · SLS nylon", kind="service", where="vendor", process="SLS PA12",
                            bed=[330.0, 330.0, 600.0], nozzle=None, layer=0.1, hole_shrink=0.1,
                            xy_tolerance=0.3, clearance_slip=0.3, clearance_press=0.05,
                            min_wall=0.8, min_feature=0.5, max_overhang=90.0, materials=["PA12"],
                            lead_time="7–10 days", cost_note="quote per part",
                            notes="Example vendor profile. SLS needs no supports and ignores overhangs, but powder "
                                  "in blind holes matters — give deep pockets an escape hole. Replace with a real quote."),
    },
}


def load():
    if not STORE.exists():
        STORE.write_text(json.dumps(SEED, indent=2))
        return json.loads(json.dumps(SEED))
    d = json.loads(STORE.read_text())
    for k, p in d.get("printers", {}).items():
        for f, v in FIELDS.items():
            p.setdefault(f, v)
    return d


def save(d):
    STORE.write_text(json.dumps(d, indent=2))
    return d


def target(part=None):
    """Which profile key applies: the part's own choice, else the default."""
    d = load()
    if part:
        f = ROOT / "parts" / part / "printer.json"
        if f.exists():
            k = json.loads(f.read_text()).get("printer")
            if k in d["printers"]:
                return k
    return d.get("default") or next(iter(d["printers"]), None)


def prof(part=None):
    d = load()
    k = target(part)
    return dict(d["printers"][k], key=k) if k else dict(FIELDS, key=None)


def set_target(part, key):
    (ROOT / "parts" / part / "printer.json").write_text(json.dumps(dict(printer=key)))


def hole_for(fits_od, fit="slip", part=None):
    """Diameter to model so `fits_od` actually fits after the printer shrinks the hole."""
    p = prof(part)
    extra = p["clearance_press"] if fit == "press" else p["clearance_slip"]
    return round(fits_od + (extra or 0) + (p["hole_shrink"] or 0), 2)


def fit_check(size, part=None, key=None):
    """Does an (x, y, z) envelope fit the bed? Tries a 90° turn, then the diagonal."""
    p = dict(load()["printers"][key], key=key) if key else prof(part)
    bed = p.get("bed") or [0, 0, 0]
    if not all(bed):
        return dict(status="unknown", printer=p.get("name", "?"), bed=bed)
    x, y, z = size
    bx, by, bz = bed
    tall = z > bz
    out = dict(printer=p.get("name"), key=p.get("key"), bed=bed, size=[round(v, 1) for v in size], tall=tall)
    if x <= bx and y <= by and not tall:
        return dict(out, status="fits", how="as modelled")
    if x <= by and y <= bx and not tall:
        return dict(out, status="rotate", how="turned 90° on the bed")
    # diagonal placement: a rotated L×W rectangle needs L·cosθ + W·sinθ across and L·sinθ + W·cosθ deep
    import math
    if not tall:
        for deg in range(1, 90):
            t = math.radians(deg)
            c, si = math.cos(t), math.sin(t)
            if x * c + y * si <= bx and x * si + y * c <= by:
                return dict(out, status="diagonal", how=f"turned {deg}° on the bed")
    over = [round(v - b, 1) for v, b in zip((x, y, z), bed)]
    return dict(out, status="too_big", how="", over=[o if o > 0 else 0 for o in over])


def describe(key=None, part=None):
    p = dict(load()["printers"][key], key=key) if key else prof(part)
    bits = [f"{p['name']} ({p['kind']}{', ' + p['process'] if p.get('process') else ''}"
            + (f", {p['where']}" if p.get("where") else "") + ")",
            f"  bed {'×'.join(str(int(v)) for v in p['bed'])} mm"
            + (f" · nozzle {p['nozzle']} mm" if p.get("nozzle") else "") + f" · layer {p['layer']} mm",
            f"  hole shrink {p['hole_shrink']} mm · slip +{p['clearance_slip']} · press +{p['clearance_press']} · tolerance ±{p['xy_tolerance']} mm",
            f"  min wall {p['min_wall']} mm · min feature {p['min_feature']} mm · max overhang {p['max_overhang']}°",
            f"  materials: {', '.join(p['materials']) or '—'}"]
    if p.get("lead_time") or p.get("cost_note"):
        bits.append(f"  lead time {p['lead_time'] or '?'} · {p['cost_note'] or ''}".rstrip())
    if p.get("notes"):
        bits.append(f"  note: {p['notes']}")
    if not p.get("verified"):
        bits.append("  [UNVERIFIED — seeded by LabCAD, not measured; say so if a design leans on these numbers]")
    return "\n".join(bits)


if __name__ == "__main__":
    import sys
    d = load()
    for k in (sys.argv[1:] or d["printers"]):
        print(f"[{k}]{'  ← default' if k == d.get('default') else ''}")
        print(describe(k))
