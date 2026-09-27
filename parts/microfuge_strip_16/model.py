"""microfuge strip 16 — derived from microfuge_rack.
Single 1×16 row of 1.5 mL tube positions. Inherits the base build; override numbers in P,
and add or subtract geometry in build() after base_build().
Improvements to the base flow into this part on its next rebuild.
"""
import sys
from build123d import *
from parts.microfuge_rack.model import P as BASE_P, RANGES as BASE_RANGES, build as base_build

P = dict(BASE_P,
    rows=2, cols=16,         # front row = open-window working tubes, back row = closed wells for transfer-to tubes
    row_pitch=22.0,          # 10 mm of deck between the rows so open caps have somewhere to lie
    grip_bite=3.5,
    cone_h=18.0, cone_tip_d=4.0,   # 1.5 mL only: 8 mm straight bore, then a cone that seats the tube's taper
    label_side=0,            # numbers engraved on the deck between the rows (±1 = back/front margin)
    window_y=1.5,            # front row is sliced off this far past its axis at the BOTTOM: open cones you can see into
    window_top=5.0,          # ...and this far at the TOP — the face leans out so the bore wraps the tube further
    window_r=0.6,            # round on the window edges; each 0.1 costs ~3° of wrap at the top, keep ≤ 0.8
    post_w=0.0,              # >0: window stops this short of each end, leaving full-depth posts at the corners
    drain_d=3.0,             # smaller than the base so it doesn't break out through the new front face
    front_num_dx=-5.5,       # position number on the front face: this far left of each cone's axis...
    front_num_up=6.0,        # ...and this far up from the bottom (keeps it in the solid web beside the cone)
)
RANGES = dict(BASE_RANGES, cols=(1, 24, 1),   # base slider tops out at 12
              window_y=(0.5, 8, 0.1), window_top=(0.5, 8, 0.1), window_r=(0, 1.2, 0.1), post_w=(0, 12, 0.5),
              front_num_dx=(-8, 8, 0.5), front_num_up=(2, 12, 0.5))

def build(P):
    # The base is built with straight 8 mm bores on a thick floor (no cones, no mouth lead-ins):
    # the window outline is then a clean loop of a few dozen edges that OCCT will round; the
    # cones, drains and the back row's lead-ins are cut afterwards. Same H, same footprint.
    cone_h = min(P["cone_h"], P["hole_depth"] - 1)
    cyl_h = P["hole_depth"] - cone_h
    part = base_build(dict(P, hole_depth=cyl_h, floor=P["floor"] + cone_h, cone_h=0, hole_chamfer=0, drain_d=0))
    L, W, H = part.bounding_box().size

    # --- pipetting window: slice everything in front of a plane that passes window_y past the
    # front row's axis at the floor and window_top past it at the deck, i.e. it leans outward.
    # Past the axis the remaining arc is > 180°, so the tube is captured; more overlap at the top
    # (where the straight bore is) is what actually stops a tube tipping forward.
    y_front = -(P["rows"]-1)/2 * (P["row_pitch"] or P["pitch"])
    y_bot, y_top = y_front - P["window_y"], y_front - P["window_top"]
    s = (y_top - y_bot) / H                      # y drift per mm of height
    cut = Polygon((-60, -H/2-1), (y_bot - s, -H/2-1), (y_top + s, H/2+1), (-60, H/2+1), align=None)
    part -= extrude(Plane.YZ * cut, amount=(L/2 - P["post_w"]) if P["post_w"] > 0 else L/2 + 1, both=True)
    xs = [(-(P["cols"]-1)/2 + c)*P["pitch"] for c in range(P["cols"])]

    # dress the new front face: its whole outline — top edge, bore lips, bore floors, bottom edge —
    # rounded in one go (one closed loop blends far more reliably than lips alone), which also
    # covers elephant foot on that edge. Front mouths join the round if OCCT lets them.
    def front(): return part.faces().filter_by(GeomType.PLANE).sort_by(Axis.Y)[0]
    def front_mouths(): return [e for e in part.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1] if e.center().Y < 0]
    rounded = None
    for r in (P["window_r"], P["window_r"]*0.75, P["window_r"]*0.5):
        if r <= 0: break
        for what, op, sel in (("outline+mouths", fillet, lambda: front().edges() + front_mouths()),
                              ("outline", fillet, lambda: front().edges()),
                              ("outline bevel", chamfer, lambda: front().edges())):
            try:
                rounded = op(sel(), r); break
            except Exception:
                print(f"window_r={r:.2f} {what} failed", file=sys.stderr)
        if rounded is not None:
            print(f"window_r={r:.2f} {what} ok", file=sys.stderr); break
    if rounded is not None:
        part = rounded
    else:
        part = chamfer(front().edges().filter_by(Axis.X).group_by(Axis.Z)[0], P["bottom_chamfer"])
        part = chamfer(front().edges().filter_by(Axis.X).group_by(Axis.Z)[-1], P["hole_chamfer"])

    # lead-in on the back row's mouths (bore-sized circles on the deck, y > 0; the deck's engraved
    # labels contribute arcs up there too, so match on radius) — while the topology is still simple
    mouths = [e for e in part.edges().filter_by(GeomType.CIRCLE).group_by(Axis.Z)[-1]
              if e.center().Y > 0 and abs(e.radius - P["hole_d"]/2) < 0.01]
    part = chamfer(mouths, P["hole_chamfer"])
    try:   # front row's mouth arcs end on the rounded horns; OCCT may or may not bevel them
        part = chamfer(front_mouths(), P["hole_chamfer"])
    except Exception:
        print("front mouth lead-in skipped", file=sys.stderr)

    # now the cones under every bore, and the drains through the real floor
    z_bore = H/2 - cyl_h
    ys = [(-(P["rows"]-1)/2 + r)*(P["row_pitch"] or P["pitch"]) for r in range(P["rows"])]
    part -= [Pos(x, y, z_bore) * Cone(P["cone_tip_d"]/2, P["hole_d"]/2, cone_h, align=(Align.CENTER, Align.CENTER, Align.MAX))
             for y in ys for x in xs]
    part -= [Pos(x, y, 0) * Cylinder(P["drain_d"]/2, H + 2) for y in ys for x in xs]
    # front-row drains would end up a knife-edge from the face: open them into it as a slot instead.
    # The slot runs from the floor up into the cone, so its walls meet the cone's breakout where the
    # breakout is exactly drain_d wide — no ledge, the cone just narrows into the slot.
    slot_h = P["floor"] + cone_h/2
    part -= [Pos(x, y_front - 30, -H/2 + slot_h/2) * Box(P["drain_d"], 60, slot_h) for x in xs]
    # and round the cone lips + slot walls too, if OCCT will have it (they're less acute than the horns)
    if rounded is not None:
        lips = lambda: [e for e in front().edges() if e.center().Z < z_bore and
                        (e.geom_type != GeomType.LINE or abs(e.tangent_at(0).X) < 0.1)]
        for r in (P["window_r"], P["window_r"]*0.5):
            try:
                part = fillet(lips(), r); print(f"cone lips r={r:.2f} ok", file=sys.stderr); break
            except Exception:
                print(f"cone lips r={r:.2f} failed", file=sys.stderr)

    # position numbers engraved on the front face, low and to the left of each open cone
    z = -H/2 + P["front_num_up"]
    yz = y_bot + s * (z + H/2)                   # where the leaning face is at that height
    n = Vector(0, -H, y_top - y_bot).normalized()  # outward normal of the leaning face
    front_plane = lambda x: Plane(origin=(x, yz, z), x_dir=(1, 0, 0), z_dir=n)   # reads upright from the front
    for c, x in enumerate(xs):
        part -= extrude(front_plane(x + P["front_num_dx"]) * Text(str(c+1), font_size=P["label_size"]),
                        amount=P["label_depth"], dir=-n)
    return part
