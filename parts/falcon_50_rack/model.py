"""Falcon 50 rack — 6 × 50 mL conical tubes in one row, low profile, one-hand pickup.
Every dimension you'd ever want to argue with is in P.
Build:  .venv/bin/python build.py falcon_50_rack -m "why"

Tube numbers come from labware["falcon_50ml"]: od 30.0 (recalled, Corning 430829), cone_len 20 (ESTIMATED).
The tip sits in the drain hole, the cone rides a 45° funnel, and the well wall captures the first
`height - floor - cone_len` mm of cylindrical body — that's what stops a lone tube leaning.
Prints flat, no supports: funnels face up, grooves are shallow arcs, everything else is vertical.
"""
from build123d import *
from labware import dims

TUBE = dims("falcon_50ml")

P = dict(
    tubes=6, pitch=38.0,          # single row; 38 leaves ~3.5 mm between 34.5 mm caps
    well_d=TUBE["od"] + 0.6,      # 30.0 body + FDM slip clearance
    height=37.0,                  # floor + 20 cone + 15 mm body captured; label panel stays clear
    floor=2.0,                    # under the drain funnel — one print, no supports
    drain_d=7.0,                  # tip locator + drain; the tube tip (~6 mm) nests in it
    width=50.0,                   # footprint across the row — the anti-tip knob
    end_margin=6.0,               # last well edge → end face
    corner_r=8.0,                 # vertical corner fillet
    top_chamfer=1.5,              # perimeter bevel on top
    bottom_chamfer=0.8,           # elephant-foot killer
    well_chamfer=1.5,             # lead-in so a tube drops in one-handed
    grip_r=9.0, grip_bite=3.0,    # pinch grooves along both long faces, mid-height
    label_size=5.0, label_depth=0.5,  # engraved 1–6 on the front margin
)

RANGES = dict(tubes=(1, 12, 1), pitch=(32, 50, 0.5), well_d=(29, 33, 0.1), height=(24, 60, 1),
              floor=(1, 4, 0.2), drain_d=(0, 12, 0.5), width=(36, 80, 1), end_margin=(3, 15, 0.5),
              corner_r=(1, 20, 0.5), top_chamfer=(0, 3, 0.1), bottom_chamfer=(0, 2, 0.1),
              well_chamfer=(0, 3, 0.1), grip_r=(4, 14, 0.5), grip_bite=(0, 5, 0.25),
              label_size=(3, 7, 0.5), label_depth=(0, 1.5, 0.1))


def build(P):
    n, pitch = P["tubes"], P["pitch"]
    rw, rd = P["well_d"] / 2, max(P["drain_d"], 0) / 2
    L = (n - 1) * pitch + P["well_d"] + 2 * P["end_margin"]
    W, H = P["width"], P["height"]
    z_floor = -H / 2 + P["floor"]
    funnel_h = rw - rd                      # 45° funnel: self-centres the tip, drains, prints face-up

    blk = Box(L, W, H)
    blk = fillet(blk.edges().filter_by(Axis.Z), P["corner_r"])
    blk = chamfer(blk.edges().group_by(Axis.Z)[-1], P["top_chamfer"])
    blk = chamfer(blk.edges().group_by(Axis.Z)[0], P["bottom_chamfer"])

    # pinch grooves: thumb one side, fingers the other, lifts one-handed
    if P["grip_bite"] > 0:
        for s in (+1, -1):
            blk -= Pos(0, s * (W / 2 + P["grip_r"] - P["grip_bite"]), 0) * Cylinder(P["grip_r"], L + 2, rotation=(0, 90, 0))

    # wells: one revolved profile each — through drain, funnel, cylindrical body
    if rd > 0:
        prof = [(0, -H / 2 - 1), (rd, -H / 2 - 1), (rd, z_floor), (rw, z_floor + funnel_h), (rw, H / 2 + 1), (0, H / 2 + 1)]
    else:
        prof = [(0, z_floor), (rw, z_floor + funnel_h), (rw, H / 2 + 1), (0, H / 2 + 1)]
    well = revolve(Plane.XZ * Polygon(*prof, align=None), Axis.Z)
    xs = [(-(n - 1) / 2 + i) * pitch for i in range(n)]
    blk -= [Pos(x, 0, 0) * well for x in xs]

    # lead-in chamfer on every mouth (select by radius so the top-corner fillet arcs stay untouched)
    if P["well_chamfer"] > 0:
        mouths = [e for e in blk.edges().filter_by(GeomType.CIRCLE)
                  if abs(e.radius - rw) < 0.01 and e.center().Z > H / 2 - 0.01]
        blk = chamfer(mouths, P["well_chamfer"])

    # engraved 1..n along the front margin
    if P["label_depth"] > 0:
        ly = -(W / 2 - P["top_chamfer"] + rw + P["well_chamfer"]) / 2
        for i, x in enumerate(xs):
            blk -= extrude(Pos(x, ly, H / 2) * Text(str(i + 1), font_size=P["label_size"]), amount=-P["label_depth"])
    return blk
