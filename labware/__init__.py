"""Curated labware dimensions + revolve profiles for digital clones.

Every number carries a source tag, because a rack that's 0.5 mm wrong is a rack that doesn't work:
    standard   — a published standard (ANSI/SLAS, ISO); trust it
    datasheet  — read from a manufacturer datasheet (name it in `ref`); trust it
    measured   — you measured it (say what with); best of all
    recalled   — a datasheet figure from memory; PROBABLY right, verify with calipers before printing
    estimated  — a guess good enough for a first fit-test, not for a final part

Usage in a model:
    from labware import dims, clone
    od = dims("tube_1_5ml")["od"]              # → 10.8
    tube = clone("tube_1_5ml")                 # → build123d Part, bottom at z=0, axis Z

Add entries here as we measure things; keep the tags honest.
"""
from build123d import *


def D(v, src, ref=""):
    return dict(v=v, src=src, ref=ref)


CATALOG = {
    "tube_1_5ml": dict(
        name="1.5 mL microcentrifuge tube (Eppendorf Safe-Lock style)", aliases=["eppendorf", "microfuge tube", "1.5 ml tube"],
        dims=dict(od=D(10.8, "recalled", "Eppendorf 3810X"), length=D(39.0, "recalled", "to rim, cap open"),
                  cyl_len=D(21.0, "estimated", "cylindrical section above the cone"), rim_od=D(12.6, "estimated"),
                  cap_od=D(12.2, "recalled"), hinge_reach=D(17.0, "estimated", "how far the open lid+hinge stick out from the axis")),
        profile=[(0, 0), (0, 1.6), (2.0, 2.4), (18.0, 5.4), (37.5, 5.4), (37.5, 6.3), (39.0, 6.3), (39.0, 0)],
        profile_src="estimated"),
    "tube_2ml": dict(
        name="2.0 mL microcentrifuge tube (round bottom, Safe-Lock style)", aliases=["2 ml tube"],
        dims=dict(od=D(10.8, "recalled", "Eppendorf 3810X"), length=D(39.0, "recalled"), cap_od=D(12.2, "recalled")),
        profile=[(0, 0), (0, 2.0), (4.0, 5.0), (6.0, 5.4), (37.5, 5.4), (37.5, 6.3), (39.0, 6.3), (39.0, 0)],
        profile_src="estimated"),
    "tube_5ml": dict(
        name="5.0 mL microcentrifuge tube (Eppendorf 5.0 mL style)", aliases=["5 ml tube", "5 ml eppendorf"],
        dims=dict(od=D(17.0, "recalled", "Eppendorf 5.0 mL"), length=D(60.0, "recalled"), cyl_len=D(38.0, "estimated"), rim_od=D(19.0, "estimated")),
        profile=[(0, 0), (0, 2.5), (3.0, 3.6), (22.0, 8.5), (58.0, 8.5), (58.0, 9.5), (60.0, 9.5), (60.0, 0)],
        profile_src="estimated"),
    "tube_pcr_0_2ml": dict(
        name="0.2 mL PCR tube", aliases=["pcr tube"],
        dims=dict(od=D(6.0, "estimated"), rim_od=D(7.0, "estimated"), length=D(20.8, "recalled")),
        profile=[(0, 0), (0, 0.8), (6.0, 2.6), (19.5, 3.0), (19.5, 3.5), (20.8, 3.5), (20.8, 0)], profile_src="estimated"),
    "cryovial_2ml": dict(
        name="2 mL cryovial (external thread)", aliases=["cryo tube", "cryovial"],
        dims=dict(od=D(12.5, "estimated"), length=D(48.0, "estimated"), cap_od=D(13.5, "estimated"))),
    "falcon_15ml": dict(
        name="15 mL conical centrifuge tube", aliases=["falcon 15", "15 ml conical"],
        dims=dict(od=D(17.0, "recalled", "Corning 430791"), length=D(120.0, "recalled"), cap_od=D(20.0, "estimated"), cone_len=D(22.0, "estimated")),
        profile=[(0, 0), (0, 2.0), (22.0, 8.5), (120.0, 8.5), (120.0, 0)], profile_src="estimated"),
    "falcon_50ml": dict(
        name="50 mL conical centrifuge tube", aliases=["falcon 50", "50 ml conical"],
        dims=dict(od=D(30.0, "recalled", "Corning 430829"), length=D(115.0, "recalled"), cap_od=D(34.5, "estimated"), cone_len=D(20.0, "estimated")),
        profile=[(0, 0), (0, 3.0), (20.0, 15.0), (115.0, 15.0), (115.0, 0)], profile_src="estimated"),
    "scint_vial_20ml": dict(
        name="20 mL scintillation vial", aliases=["scint vial"],
        dims=dict(od=D(28.0, "estimated"), length=D(61.0, "estimated"), cap_od=D(29.0, "estimated"))),
    "bottle_duran_100ml": dict(name="100 mL GL45 media bottle", aliases=["duran 100", "media bottle 100"],
        dims=dict(od=D(56.0, "recalled", "DWK Duran"), height=D(105.0, "recalled"), cap_od=D(54.0, "estimated", "GL45 cap"))),
    "bottle_duran_250ml": dict(name="250 mL GL45 media bottle", aliases=["duran 250"],
        dims=dict(od=D(70.0, "recalled", "DWK Duran"), height=D(143.0, "recalled"), cap_od=D(54.0, "estimated", "GL45 cap"))),
    "bottle_duran_500ml": dict(name="500 mL GL45 media bottle", aliases=["duran 500"],
        dims=dict(od=D(86.0, "recalled", "DWK Duran"), height=D(181.0, "recalled"), cap_od=D(54.0, "estimated", "GL45 cap"))),
    "bottle_duran_1000ml": dict(name="1000 mL GL45 media bottle", aliases=["duran 1000", "1 l bottle"],
        dims=dict(od=D(101.0, "recalled", "DWK Duran"), height=D(230.0, "recalled"), cap_od=D(54.0, "estimated", "GL45 cap"))),
    "microplate_slas": dict(
        name="Microplate footprint (ANSI/SLAS 1-2004)", aliases=["96 well plate", "384 well plate", "plate footprint"],
        dims=dict(length=D(127.76, "standard", "ANSI/SLAS 1-2004"), width=D(85.48, "standard", "ANSI/SLAS 1-2004"),
                  height=D(14.35, "standard", "ANSI/SLAS 2-2004 standard-height plate"), corner_r=D(3.18, "standard", "ANSI/SLAS 1-2004"))),
    "slide_75x25": dict(name="Microscope slide", aliases=["glass slide"],
        dims=dict(length=D(75.0, "standard", "ISO 8037-1"), width=D(25.0, "standard", "ISO 8037-1"), thickness=D(1.0, "standard", "ISO 8037-1 (0.9–1.1)"))),
    "tip_1000ul": dict(name="1000 µL pipette tip (universal)", aliases=["blue tip", "1 ml tip"],
        dims=dict(top_od=D(8.0, "estimated"), length=D(72.0, "estimated"))),
    "tip_200ul": dict(name="200 µL pipette tip (universal)", aliases=["yellow tip"],
        dims=dict(top_od=D(5.8, "estimated"), length=D(52.0, "estimated"))),
    "marker_sharpie_fine": dict(name="Sharpie fine point marker", aliases=["sharpie", "lab marker"],
        dims=dict(od=D(12.7, "estimated"), length=D(140.0, "estimated"))),
}


def find(query):
    """Loose lookup: key, name fragment, or alias."""
    q = query.lower().strip()
    if q in CATALOG:
        return q
    for k, it in CATALOG.items():
        if q in it["name"].lower() or any(q == a or q in a for a in it.get("aliases", [])):
            return k
    raise KeyError(f"no labware matching {query!r}; known: {sorted(CATALOG)}")


def dims(key):
    """Plain numbers for a model. Sources are still in CATALOG[key]['dims'] — quote them when it matters."""
    return {k: d["v"] for k, d in CATALOG[find(key)]["dims"].items()}


def describe(key):
    k = find(key)
    it = CATALOG[k]
    lines = [f"{k}: {it['name']}"]
    for n, d in it["dims"].items():
        lines.append(f"  {n} = {d['v']} mm  [{d['src']}{(' ' + d['ref']) if d['ref'] else ''}]")
    if it.get("profile"):
        lines.append(f"  profile: {len(it['profile'])} pts, revolve-able  [{it.get('profile_src', '?')}]")
    return "\n".join(lines)


def clone(key):
    """Digital clone: revolve the (z, r) profile about Z. Bottom at z = 0. For fit-testing in racks and holders."""
    it = CATALOG[find(key)]
    if not it.get("profile"):
        raise ValueError(f"{key} has dims but no profile yet — add one to CATALOG (list of (z, r), closed on the axis)")
    pts = [(r, z) for z, r in it["profile"]]          # build123d revolve: sketch in XZ, X = radius
    sk = Plane.XZ * Polygon(*pts, align=None)
    return revolve(sk, Axis.Z)


def worst_source(key):
    order = ["standard", "measured", "datasheet", "recalled", "estimated"]
    it = CATALOG[find(key)]
    return max((d["src"] for d in it["dims"].values()), key=order.index)


if __name__ == "__main__":
    import sys
    for k in (sys.argv[1:] or CATALOG):
        print(describe(k))
