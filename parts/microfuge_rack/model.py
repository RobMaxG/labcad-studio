"""Microfuge tube rack (1.5 / 2.0 mL) — parametric, FDM-friendly.
Every dimension you'd ever want to argue with is in P.
Build:  .venv/bin/python build.py microfuge_rack -m "why"
"""
from build123d import *

P = dict(
    rows=4, cols=6,          # grid
    pitch=18.0,              # centre-to-centre (18 leaves room to flip lids open)
    row_pitch=0.0,           # centre-to-centre between rows; 0 = same as pitch
    hole_d=11.8,             # Eppendorf 1.5 mL body OD 10.8; FDM holes print ~0.3 small
    hole_depth=26.0,         # ~8 mm of the cylindrical body captured, ~13 mm proud
    floor=2.0,               # below the hole — keeps it a single print, no supports
    drain_d=4.0,             # through-hole in every floor: water/ice/autoclave drains out
    margin=8.0,              # hole edge → outer face
    corner_r=6.0,            # vertical corner fillet
    top_chamfer=1.5,         # perimeter bevel on top — the "machined" look
    bottom_chamfer=0.8,      # kills elephant-foot on the first layer
    hole_chamfer=1.2,        # lead-in so tubes drop in one-handed
    cone_h=0.0, cone_tip_d=4.0,  # conical well bottom (0 = straight well); 1.5 mL tube cone is ~16–18 mm tall
    grip_r=7.0, grip_bite=2.5,   # finger groove along both long sides, mid-height
    label_size=4.0, label_depth=0.5,  # engraved A–D / 1–6
    label_side=-1,           # column numbers on the front (-1) or back (+1) margin
)

# slider ranges for the Studio knobs: (min, max, step) — anything not listed gets a heuristic range
RANGES = dict(rows=(1, 8, 1), cols=(1, 12, 1), pitch=(13, 26, 0.5), row_pitch=(0, 40, 0.5), hole_d=(10.5, 13.5, 0.1),
              hole_depth=(12, 40, 1), floor=(1, 4, 0.2), drain_d=(0, 8, 0.5), margin=(4, 16, 0.5),
              corner_r=(0.5, 12, 0.5), top_chamfer=(0, 3, 0.1), bottom_chamfer=(0, 2, 0.1),
              hole_chamfer=(0, 3, 0.1), cone_h=(0, 30, 1), cone_tip_d=(2, 10, 0.5),
              grip_r=(3, 12, 0.5), grip_bite=(0, 5, 0.25),
              label_size=(2, 7, 0.5), label_depth=(0, 1.5, 0.1), label_side=(-1, 1, 1))

def build(P):
    rp = P["row_pitch"] or P["pitch"]
    L = (P["cols"]-1)*P["pitch"] + P["hole_d"] + 2*P["margin"]
    W = (P["rows"]-1)*rp + P["hole_d"] + 2*P["margin"]
    H = P["hole_depth"] + P["floor"]

    blk = Box(L, W, H)
    blk = fillet(blk.edges().filter_by(Axis.Z), P["corner_r"])
    blk = chamfer(blk.edges().group_by(Axis.Z)[-1], P["top_chamfer"])
    blk = chamfer(blk.edges().group_by(Axis.Z)[0],  P["bottom_chamfer"])

    # finger grooves along the long sides
    for s in (+1, -1):
        g = Pos(0, s*(W/2 + P["grip_r"] - P["grip_bite"]), 0) * Cylinder(P["grip_r"], L+2, rotation=(0, 90, 0))
        blk -= g

    # tube wells + drains
    locs = GridLocations(P["pitch"], rp, P["cols"], P["rows"])
    # well = straight bore, optionally ending in a cone that cradles the tube's taper
    cone_h = min(P["cone_h"], P["hole_depth"] - 1)
    cyl_h = P["hole_depth"] - cone_h
    def well():
        w = Pos(0, 0, H/2) * Cylinder(P["hole_d"]/2, cyl_h, align=(Align.CENTER, Align.CENTER, Align.MAX))
        if cone_h > 0:
            w += Pos(0, 0, H/2 - cyl_h) * Cone(P["cone_tip_d"]/2, P["hole_d"]/2, cone_h, align=(Align.CENTER, Align.CENTER, Align.MAX))
        return w
    blk -= [l * well() for l in locs]
    if P["drain_d"] > 0:
        blk -= [l * Cylinder(P["drain_d"]/2, H+2) for l in locs]
    # lead-in chamfer on every well mouth
    if P["hole_chamfer"] > 0:
        mouths = blk.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1]
        blk = chamfer(mouths, P["hole_chamfer"])

    # engraved labels: rows A.. down the left margin, columns 1.. along the front margin
    xs = [(-(P["cols"]-1)/2 + c)*P["pitch"] for c in range(P["cols"])]
    ys = [(-(P["rows"]-1)/2 + r)*rp for r in range(P["rows"])]
    lx = -L/2 + P["margin"]/2 + P["top_chamfer"]/2
    ly = P["label_side"] * (W/2 - P["margin"]/2 - P["top_chamfer"]/2)
    for r, y in enumerate(reversed(ys)):
        blk -= extrude(Pos(lx, y, H/2) * Text(chr(65+r), font_size=P["label_size"]), amount=-P["label_depth"])
    for c, x in enumerate(xs):
        blk -= extrude(Pos(x, ly, H/2) * Text(str(c+1), font_size=P["label_size"]), amount=-P["label_depth"])
    return blk
