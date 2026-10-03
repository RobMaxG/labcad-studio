"""Sliding viewport door + retaining frame — light-tight cover for a window cut in an incubator's black film.

Three components, each built the way it prints (flat, no supports) and placed into the assembly:
  frame — VHB'd flat-back-down onto the film round the cutout. A 3-sided 45° dovetail slot holds the door;
          the 4th (parking) end is open so the door slides in, then the key closes it.
  door  — slides along the cutout's SHORT axis (Y) so the frame fits a 235 mm bed. Its back overlaps the
          window by `overlap` on every side: light has to get round a 45° slanted gap and then run
          `overlap` mm along a 0.35 mm gap to get in. Print it in black.
  key   — short dovetail plug pressed into the open end as the door stop (drop of CA = permanent).
Frame coordinates: z = 0 on the glass, cutout centred on (0, 0), slot closed at −Y.
No labware here; every number is from the user's brief or the printer profile.
"""
from math import sqrt
from build123d import *
from assembly import Comp

FRAME_LABEL = "KEEP CLOSED"
DOOR_LABEL = "OPEN"

COMPONENTS = dict(
    frame=dict(label="Frame", color="#8fb4dc", note="Prints glass-face down. VHB it onto the film round the cutout."),
    door=dict(label="Sliding door", color="#e8a0a8", filament="black PLA+",
              note="Print in black — it is the light seal. Bevels face up, no supports."),
    key=dict(label="End key", color="#d9c38f",
             note="Press into the open end of the slot after the door is in; a drop of CA makes it permanent."),
)

P = dict(
    cut_w=160.0, cut_h=90.0,     # the hole in the film: X across, Y = slide axis
    window_inset=1.0,            # frame window this much smaller per side — hides a ragged knife cut
    overlap=8.0,                 # door back overlaps the cutout by this on every side (the light seal)
    door_t=3.0,                  # black PLA+ at 3 mm is opaque; engraving leaves 2.4
    land=0.6,                    # vertical strip under the door's 45° bevels — no knife edge to elephant-foot
    clear=0.35,                  # sliding gap, normal to every running face
    base_t=2.4,                  # frame floor between door and glass
    lip_t=2.0,                   # lip material above the slot
    rail_w=8.0,                  # solid frame outboard of the slot (sides + closed end)
    open_margin=2.0,             # door's leading edge clears the window by this when fully open
    key_len=10.0, key_fit=0.1,   # end plug length; its per-side gap (snug — CA it if loose)
    park_window=1,               # hollow the floor under the parked door; it rides on the side strips
    corner_r=6.0,                # vertical outer corners
    top_chamfer=1.0,             # outer top bevel
    bottom_chamfer=0.6,          # elephant-foot killer on the glass face
    lip_chamfer=0.5,             # breaks the slot's top edges
    grip_len=50.0, grip_w=7.0, grip_h=6.0,  # raised pull bar on the door
    grip_from_edge=16.0,         # bar centre → door's leading edge (reachable open or shut)
    label_size=6.0, label_depth=0.6,   # font em; caps come out ~4.3 mm
    door_pos=0.0,                # viewer only: 0 shut → 1 fully open
)

RANGES = dict(cut_w=(40, 200, 1), cut_h=(30, 120, 1), window_inset=(0, 5, 0.5), overlap=(4, 15, 0.5),
              door_t=(2, 5, 0.2), land=(0.3, 1.5, 0.1), clear=(0.15, 0.8, 0.05), base_t=(1.6, 4, 0.2),
              lip_t=(1.2, 4, 0.2), rail_w=(4, 15, 0.5), open_margin=(0, 10, 0.5), key_len=(6, 20, 1),
              key_fit=(-0.1, 0.3, 0.05), park_window=(0, 1, 1), corner_r=(1, 12, 0.5),
              top_chamfer=(0, 2, 0.1), bottom_chamfer=(0, 1.2, 0.1), lip_chamfer=(0, 1, 0.1),
              grip_len=(15, 100, 1), grip_w=(4, 12, 0.5), grip_h=(2, 12, 0.5), grip_from_edge=(8, 60, 1),
              label_size=(0, 8, 0.5), label_depth=(0, 1.2, 0.1), door_pos=(0, 1, 0.05))

KNOBS = dict(
    cut_w=dict(label="Cutout width", group="Cutout", help="The hole cut in the black film, side to side."),
    cut_h=dict(label="Cutout height", group="Cutout", help="The hole in the film along the direction the door slides."),
    window_inset=dict(label="Window inset", group="Cutout", advanced=True,
                      help="The frame's window is this much smaller on each side, to hide a ragged knife cut."),
    overlap=dict(label="Light-seal overlap", group="Fit & seal",
                 help="How far the door covers past the cutout on every side. Light has to travel this far through a hair-thin gap."),
    clear=dict(label="Sliding gap", group="Fit & seal",
               help="Clearance on every running face. Smaller seals better and slides stiffer."),
    door_t=dict(label="Door thickness", group="Door", help="3 mm of black PLA+ is opaque; the engraving leaves 2.4 mm."),
    open_margin=dict(label="Open clearance", group="Door", help="When fully open, the door's edge clears the window by this much."),
    land=dict(label="Bevel land", group="Door", advanced=True,
              help="A short vertical strip under the door's 45° bevels, so there is no knife edge to squash on the bed."),
    base_t=dict(label="Floor thickness", group="Frame", help="Frame floor between the door and the glass."),
    lip_t=dict(label="Lip thickness", group="Frame", help="Plastic above the slot that holds the door down."),
    rail_w=dict(label="Rail width", group="Frame", help="Solid frame beside the slot, on the sides and the closed end."),
    park_window=dict(label="Hollow under the parked door", group="Frame",
                     help="Removes the floor where the open door rests, to save plastic. The door rides on the side strips."),
    key_len=dict(label="Key length", group="End key"),
    key_fit=dict(label="Key fit", group="End key", help="Gap on each side of the key. 0.1 is snug; below 0 is a press fit."),
    grip_len=dict(label="Pull bar length", group="Pull bar"),
    grip_w=dict(label="Pull bar width", group="Pull bar"),
    grip_h=dict(label="Pull bar height", group="Pull bar"),
    grip_from_edge=dict(label="Pull bar position", group="Pull bar", help="Distance from the bar's centre to the door's leading edge."),
    label_size=dict(label="Label size", group="Labels", help="Font size; capitals come out about 0.7× this. 0 turns the labels off."),
    label_depth=dict(label="Engrave depth", group="Labels"),
    corner_r=dict(label="Corner radius", group="Finish"),
    top_chamfer=dict(label="Top bevel", group="Finish"),
    bottom_chamfer=dict(label="Bed-side chamfer", group="Finish", help="Takes off the first-layer bulge (elephant's foot) on the glass face."),
    lip_chamfer=dict(label="Slot edge break", group="Finish", advanced=True),
    door_pos=dict(label="Door position", group="View", view=True, unit="", help="Slide the door: 0 shut, 1 fully open. Only moves it on screen."),
)


def _sweep_y(pts, y0, y1):
    """X–Z polygon swept along Y from y0 to y1."""
    return Pos(0, (y0 + y1) / 2, 0) * extrude(Plane.XZ * Polygon(*pts, align=None), amount=(y1 - y0) / 2, both=True)


def _sweep_x(pts, x0, x1):
    """Y–Z polygon swept along X from x0 to x1."""
    return Pos((x0 + x1) / 2, 0, 0) * extrude(Plane.YZ * Polygon(*pts, align=None), amount=(x1 - x0) / 2, both=True)


def _engrave(body, txt, x, y, z, size, depth):
    return body - extrude(Pos(x, y, z) * Text(txt, font_size=size), amount=-depth)


def _geom(P):
    g = dict(Wd=P["cut_w"] + 2 * P["overlap"], Ld=P["cut_h"] + 2 * P["overlap"], t=P["door_t"], c=P["clear"])
    g["zf"] = P["base_t"]
    g["zt"] = g["zf"] + g["t"] + g["c"]                    # slot ceiling
    g["H"] = g["zt"] + P["lip_t"]
    g["xb"] = g["Wd"] / 2 + g["c"]                          # slot half-width at the floor
    g["lv"] = P["land"] + g["c"] * (sqrt(2) - 1)            # slot's vertical land (keeps the 45° gap = clear)
    g["run"] = g["zt"] - g["zf"] - g["lv"]                  # horizontal reach of each 45° lip
    g["xt"] = g["xb"] - g["run"]                            # half-width of the opening through the lips
    g["T"] = P["cut_h"] + P["overlap"] + P["open_margin"]   # door travel
    g["yb"] = -g["Ld"] / 2 - g["c"]                         # closed end of the slot (floor level)
    g["yk"] = g["Ld"] / 2 + g["T"] + g["c"]                 # open door stops here = key's inner face
    g["ye"] = g["yk"] + P["key_len"]                        # frame's open end
    g["X"] = g["xb"] + P["rail_w"]
    g["Y0"] = g["yb"] - P["rail_w"]
    return g


def _door(P, g):
    """Back face at z = 0, leading (shut-end) edge at y = −Ld/2; 45° bevels on the sides and leading edge."""
    Wd, Ld, t, ld = g["Wd"], g["Ld"], g["t"], P["land"]
    b = t - ld
    sides = _sweep_y([(-Wd / 2, 0), (Wd / 2, 0), (Wd / 2, ld), (Wd / 2 - b, t), (-Wd / 2 + b, t), (-Wd / 2, ld)],
                     -Ld / 2 - 1, Ld / 2 + 1)
    ends = _sweep_x([(-Ld / 2, 0), (Ld / 2, 0), (Ld / 2, t), (-Ld / 2 + b, t), (-Ld / 2, ld)],
                    -Wd / 2 - 1, Wd / 2 + 1)
    door = sides & ends

    gy = -Ld / 2 + P["grip_from_edge"]
    bar = Box(P["grip_len"], P["grip_w"], P["grip_h"] + 0.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    bar = fillet(bar.edges().filter_by(Axis.Z), P["grip_w"] / 2 * 0.98)
    bar = fillet(bar.edges().group_by(Axis.Z)[-1], min(2.0, P["grip_w"] / 2 - 0.6, P["grip_h"] - 0.3))
    door += Pos(0, gy, t - 0.5) * bar

    if P["label_size"] > 0 and P["label_depth"] > 0:
        s, dpt = P["label_size"], min(P["label_depth"], t - 1.2)
        ty = gy + P["grip_w"] / 2 + 3 + s / 2
        door = _engrave(door, DOOR_LABEL, 0, ty, t, s, dpt)
        ay = ty + s / 2 + 2                                 # ▲ pointing the way it opens
        arrow = Pos(0, ay, t) * Polygon((-s * 0.7, 0), (s * 0.7, 0), (0, s * 0.9), align=None)
        door -= extrude(arrow, amount=-dpt)
    return door


def _key(P, g):
    """Dovetail plug, inner face at y = 0, sits on the slot floor (z = 0) and finishes flush with the frame top."""
    kf, r2 = P["key_fit"], sqrt(2) - 1
    xb, xt = g["xb"] - kf, g["xt"] - kf
    z1, z2, hk = g["lv"] - kf * r2, g["zt"] - g["zf"] - kf * r2, g["H"] - g["zf"]
    key = _sweep_y([(-xb, 0), (xb, 0), (xb, z1), (xt, z2), (xt, hk), (-xt, hk), (-xt, z2), (-xb, z1)],
                   0, P["key_len"])
    key = chamfer(key.edges().filter_by(Axis.Y).group_by(Axis.Z)[0], min(0.3, z1 / 2))   # its own elephant foot
    if P["top_chamfer"] > 0:                                # matches the frame's bevel on the exposed end
        key = chamfer(key.edges().group_by(Axis.Y)[-1].group_by(Axis.Z)[-1], min(P["top_chamfer"], P["lip_t"] / 2))
    return key


def _frame(P, g):
    zf, zt, H, xb, xt, lv, run = g["zf"], g["zt"], g["H"], g["xb"], g["xt"], g["lv"], g["run"]
    yb, yk, ye, X, Y0 = g["yb"], g["yk"], g["ye"], g["X"], g["Y0"]

    f = Pos(0, (Y0 + ye) / 2, H / 2) * Box(2 * X, ye - Y0, H)
    f = fillet(f.edges().filter_by(Axis.Z), P["corner_r"])
    if P["top_chamfer"] > 0:
        f = chamfer(f.edges().group_by(Axis.Z)[-1], P["top_chamfer"])
    if P["bottom_chamfer"] > 0:
        f = chamfer(f.edges().group_by(Axis.Z)[0], P["bottom_chamfer"])

    # dovetail slot: side profile ∩ end profile = 45° lips on both sides and the shut end, open at +Y
    top, far = H + 1, ye + 5
    sides = _sweep_y([(-xb, zf), (xb, zf), (xb, zf + lv), (xt, zt), (xt, top), (-xt, top), (-xt, zt), (-xb, zf + lv)],
                     yb - 5, far)
    end = _sweep_x([(yb, zf), (far, zf), (far, top), (yb + run, top), (yb + run, zt), (yb, zf + lv)], -X - 5, X + 5)
    f -= sides & end

    if P["lip_chamfer"] > 0:
        lips = [e for e in f.edges().filter_by_position(Axis.Z, H - 1e-3, H + 1e-3)
                if abs(abs(e.center().X) - xt) < 1e-3 or abs(e.center().Y - (yb + run)) < 1e-3]
        f = chamfer(lips, min(P["lip_chamfer"], P["lip_t"] / 2))

    # viewing window through the floor
    ww, wh = P["cut_w"] - 2 * P["window_inset"], P["cut_h"] - 2 * P["window_inset"]
    win = Pos(0, 0, zf / 2) * Box(ww, wh, zf + 2)
    f -= fillet(win.edges().filter_by(Axis.Z), 2.0)

    # lightening window under the parked door: starts past the shut door's trailing edge so that seal
    # band stays solid, stops `overlap` short of the key so the parked door's tail lands on floor
    if P["park_window"]:
        y0, y1 = g["Ld"] / 2 + g["c"] + 3, yk - P["overlap"]
        if y1 - y0 > 10:
            pw = Pos(0, (y0 + y1) / 2, zf / 2) * Box(ww, y1 - y0, zf + 2)
            f -= fillet(pw.edges().filter_by(Axis.Z), 2.0)

    if P["label_size"] > 0 and P["label_depth"] > 0:
        ly = (Y0 + P["top_chamfer"] + yb + run) / 2
        f = _engrave(f, FRAME_LABEL, 0, ly, H, P["label_size"], min(P["label_depth"], P["lip_t"] - 0.8))
    return f


def build(P):
    g = _geom(P)
    dy = max(0.0, min(1.0, P["door_pos"])) * g["T"]
    return dict(
        frame=Comp(_frame(P, g)),
        door=Comp(_door(P, g), at=Pos(0, dy, g["zf"])),
        key=Comp(_key(P, g), at=Pos(0, g["yk"], g["zf"])),
    )
