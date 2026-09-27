"""Blueprint sheet: third-angle top / front / right views with hidden lines and auto dimensions.

    .venv/bin/python drawing.py microfuge_rack v003            → parts/microfuge_rack/versions/v003_drawing.svg

Old-school drafting look on purpose: bordered sheet with zone ticks, title block, third-angle symbol,
single-stroke lettering. Two themes in the SVG's own CSS (class "blueprint" | "paper").
"""
import json, math, sys, time
from collections import Counter, defaultdict
from pathlib import Path
from build123d import *

ROOT = Path(__file__).resolve().parent
SHEET_W, SHEET_H = 1400, 1000
MARGIN = 34
TITLE_W, TITLE_H = 440, 172
SCALES = [(10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20)]   # sheet px per mm = 4 * a/b  (sheet is "A3 at 4 px/mm")
PX_PER_MM_AT_1_1 = 4.0

VIEWS = {  # name: (viewport_origin, up, (model axes shown as screen x, screen y))
    "top":   ((0, 0, 1e4), (0, 1, 0), ("X", "Y")),
    "front": ((0, -1e4, 0), (0, 0, 1), ("X", "Z")),
    "right": ((1e4, 0, 0), (0, 0, 1), ("Y", "Z")),
}


def tess(edge):
    """Sample an edge into a polyline. OCP raises on degenerate edges, so guard and fall back."""
    try:
        length = edge.length
    except Exception:
        return None
    if not length or length < 1e-6:
        return None
    n = 2 if edge.geom_type == GeomType.LINE else max(8, min(72, int(length / 0.6)))
    try:
        return [(p.X, p.Y) for p in (edge @ (i / (n - 1)) for i in range(n))]
    except Exception:
        try:                                            # endpoints are enough for a short arc
            a, b = edge.start_point(), edge.end_point()
            return [(a.X, a.Y), (b.X, b.Y)]
        except Exception:
            return None


def project(part, view):
    origin, up, _ = VIEWS[view]
    vis, hid = part.project_to_viewport(viewport_origin=origin, viewport_up=up, look_at=(0, 0, 0))
    def safe_len(e):
        try:
            return e.length or 0
        except Exception:
            return 0
    hid = [e for e in hid if safe_len(e) > 2.0]                    # engraved text seen edge-on is noise
    keep = lambda es: [pl for pl in (tess(e) for e in es) if pl]
    return keep(vis), keep(hid)


def holes(part):
    """Circular edges whose axis is Z, grouped by radius → [(radius, [centers (x,y)])], most-numerous first."""
    groups = defaultdict(set)
    for e in part.edges().filter_by(GeomType.CIRCLE):
        try:
            ax = e.arc_center
            n = (e @ 0.2 - ax).cross(e @ 0.6 - ax)
            if n.length < 1e-6:
                continue
        except Exception:
            continue
        if abs(n.normalized().Z) < 0.95:
            continue
        groups[round(e.radius, 2)].add((round(ax.X, 2), round(ax.Y, 2)))
    out = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [(r, sorted(c)) for r, c in out if len(c) >= 2][:2]


def pitch_of(centers):
    xs = sorted({c[0] for c in centers}); ys = sorted({c[1] for c in centers})
    px = min((b - a for a, b in zip(xs, xs[1:]) if b - a > 0.5), default=None)
    py = min((b - a for a, b in zip(ys, ys[1:]) if b - a > 0.5), default=None)
    return px, py


class Sheet:
    def __init__(self):
        self.parts = []

    def add(self, s):
        self.parts.append(s)

    def polylines(self, lines, cls, tf):
        for pl in lines:
            pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in map(tf, pl))
            self.add(f'<polyline class="{cls}" points="{pts}"/>')

    def text(self, x, y, s, cls="lbl", anchor="middle", rot=0):
        t = f' transform="rotate({rot} {x:.1f} {y:.1f})"' if rot else ""
        self.add(f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{t}>{s}</text>')

    def dim_h(self, x1, x2, y, y_from, label):
        """Horizontal dimension at sheet y; extension lines rise/fall from y_from."""
        ext = 6 if y > y_from else -6
        self.add(f'<line class="ext" x1="{x1:.1f}" y1="{y_from:.1f}" x2="{x1:.1f}" y2="{y + ext:.1f}"/>')
        self.add(f'<line class="ext" x1="{x2:.1f}" y1="{y_from:.1f}" x2="{x2:.1f}" y2="{y + ext:.1f}"/>')
        self.add(f'<line class="dim" x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" marker-start="url(#ah)" marker-end="url(#ah)"/>')
        self.text((x1 + x2) / 2, y - 5, label, "dimtxt")

    def dim_v(self, y1, y2, x, x_from, label):
        ext = 6 if x > x_from else -6
        self.add(f'<line class="ext" x1="{x_from:.1f}" y1="{y1:.1f}" x2="{x + ext:.1f}" y2="{y1:.1f}"/>')
        self.add(f'<line class="ext" x1="{x_from:.1f}" y1="{y2:.1f}" x2="{x + ext:.1f}" y2="{y2:.1f}"/>')
        self.add(f'<line class="dim" x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" marker-start="url(#ah)" marker-end="url(#ah)"/>')
        self.text(x - 5, (y1 + y2) / 2, label, "dimtxt", rot=-90)

    def leader(self, x, y, dx, dy, label):
        self.add(f'<line class="dim" x1="{x:.1f}" y1="{y:.1f}" x2="{x + dx:.1f}" y2="{y + dy:.1f}" marker-start="url(#dot)"/>')
        self.add(f'<line class="dim" x1="{x + dx:.1f}" y1="{y + dy:.1f}" x2="{x + dx + (28 if dx > 0 else -28):.1f}" y2="{y + dy:.1f}"/>')
        self.text(x + dx + (30 if dx > 0 else -30), y + dy - 4, label, "dimtxt", "start" if dx > 0 else "end")

    def centermark(self, x, y, r):
        s = min(max(r * 0.35, 4), 10)
        self.add(f'<path class="cl" d="M{x - r - s:.1f},{y:.1f} H{x + r + s:.1f} M{x:.1f},{y - r - s:.1f} V{y + r + s:.1f}"/>')


def fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 0.04 else f"{round(v)}"


def make_drawing(part, meta, out):
    bb = part.bounding_box()
    L, W, H = bb.size.X, bb.size.Y, bb.size.Z
    gap_mm = max(L, W, H) * 0.3 + 12
    draw_w_mm, draw_h_mm = L + gap_mm + W, H + gap_mm + W
    area_w = SHEET_W - 2 * MARGIN - 150       # room for dimension text around the views
    area_h = SHEET_H - 2 * MARGIN - TITLE_H - 150
    for a, b in SCALES:
        s = PX_PER_MM_AT_1_1 * a / b
        if draw_w_mm * s <= area_w and draw_h_mm * s <= area_h:
            scale_txt, S = f"{a}:{b}", s
            break
    else:
        S = min(area_w / draw_w_mm, area_h / draw_h_mm); scale_txt = f"1:{1 / (S / PX_PER_MM_AT_1_1):.1f}"
    # anchor: front view bottom-left; top view above; right view to the right (third angle)
    ox = MARGIN + 95 + (area_w - draw_w_mm * S) / 2
    oy = MARGIN + 40 + (area_h - draw_h_mm * S) / 2
    sh = Sheet()
    frames = {}
    # views: (sheet origin x of left edge, sheet y of TOP edge, model xmin, model ymax) in each view's own 2D coords
    lay = {
        "front": (ox, oy + W * S + gap_mm * S, bb.min.X, bb.max.Z, L, H),
        "top":   (ox, oy, bb.min.X, bb.max.Y, L, W),
        "right": (ox + L * S + gap_mm * S, oy + W * S + gap_mm * S, bb.min.Y, bb.max.Z, W, H),
    }
    for view, (vx, vy, xmin, ymax, w_mm, h_mm) in lay.items():
        tf = lambda p, vx=vx, vy=vy, xmin=xmin, ymax=ymax: (vx + (p[0] - xmin) * S, vy + (ymax - p[1]) * S)
        vis, hid = project(part, view)
        sh.polylines(hid, "hid", tf)
        sh.polylines(vis, "vis", tf)
        frames[view] = (vx, vy, vx + w_mm * S, vy + h_mm * S, tf)
        sh.text(vx + w_mm * S / 2, vy + h_mm * S + 74, {"top": "TOP VIEW", "front": "FRONT VIEW", "right": "RIGHT SIDE VIEW"}[view], "vlbl")
    # envelope dimensions
    fx0, fy0, fx1, fy1, ftf = frames["front"]
    sh.dim_h(fx0, fx1, fy1 + 34, fy1, fmt(L))
    sh.dim_v(fy0, fy1, fx0 - 40, fx0, fmt(H))
    rx0, ry0, rx1, ry1, rtf = frames["right"]
    sh.dim_h(rx0, rx1, ry1 + 34, ry1, fmt(W))
    # holes: centre marks, pitch, Ø callouts (top view)
    tx0, ty0, tx1, ty1, ttf = frames["top"]
    hs = holes(part)
    for gi, (r, centers) in enumerate(hs):
        for cx, cy in centers:
            sx, sy = ttf((cx, cy)); sh.centermark(sx, sy, r * S)
        top_row = [c for c in centers if abs(c[1] - max(centers)[1]) < 0.5]
        cx, cy = sorted(top_row)[-1 - min(gi, len(top_row) - 1)]                # corner hole, then the one beside it
        sx, sy = ttf((cx, cy))
        sh.leader(sx + r * S * 0.7071, sy - r * S * 0.7071, 34, -34 - gi * 10, f"⌀{fmt(2 * r)} ×{len(centers)}")
        if gi == 0:
            px, py = pitch_of(centers)
            if px:
                a = min(centers); b = next((c for c in centers if abs(c[1] - a[1]) < 0.5 and c[0] > a[0] + 0.5), None)
                if b:
                    ax_, ay_ = ttf(a); bx_, _ = ttf(b)
                    sh.dim_h(ax_, bx_, ty1 + 34, ay_, fmt(px))
            if py:
                a = min(centers); b = next((c for c in centers if abs(c[0] - a[0]) < 0.5 and c[1] > a[1] + 0.5), None)
                if b:
                    ax_, ay_ = ttf(a); _, by_ = ttf(b)
                    sh.dim_v(by_, ay_, tx0 - 40, ax_, fmt(py))
    # sheet chrome: border with zone ticks, title block, third-angle symbol
    chrome = []
    chrome.append(f'<rect class="border" x="{MARGIN - 14}" y="{MARGIN - 14}" width="{SHEET_W - 2 * MARGIN + 28}" height="{SHEET_H - 2 * MARGIN + 28}"/>')
    chrome.append(f'<rect class="border thin" x="{MARGIN}" y="{MARGIN}" width="{SHEET_W - 2 * MARGIN}" height="{SHEET_H - 2 * MARGIN}"/>')
    for i in range(1, 8):
        x = MARGIN + (SHEET_W - 2 * MARGIN) * i / 8
        chrome.append(f'<line class="border thin" x1="{x:.0f}" y1="{MARGIN - 14}" x2="{x:.0f}" y2="{MARGIN}"/><line class="border thin" x1="{x:.0f}" y1="{SHEET_H - MARGIN}" x2="{x:.0f}" y2="{SHEET_H - MARGIN + 14}"/>')
        chrome.append(f'<text class="zone" x="{x - (SHEET_W - 2 * MARGIN) / 16:.0f}" y="{MARGIN - 4}" text-anchor="middle">{i}</text>')
    for i, z in enumerate("ABCDEF"):
        y = MARGIN + (SHEET_H - 2 * MARGIN) * (i + 1) / 6
        if i < 5:
            chrome.append(f'<line class="border thin" x1="{MARGIN - 14}" y1="{y:.0f}" x2="{MARGIN}" y2="{y:.0f}"/><line class="border thin" x1="{SHEET_W - MARGIN}" y1="{y:.0f}" x2="{SHEET_W - MARGIN + 14}" y2="{y:.0f}"/>')
        chrome.append(f'<text class="zone" x="{MARGIN - 7}" y="{y - (SHEET_H - 2 * MARGIN) / 12 + 4:.0f}" text-anchor="middle">{z}</text>')
    tx, ty = SHEET_W - MARGIN - TITLE_W, SHEET_H - MARGIN - TITLE_H
    try:
        import printers as _pr
        prf = _pr.prof(meta["part"])
        fit = _pr.fit_check(meta["envelope"], part=meta["part"])
        tol = prf.get("xy_tolerance") or 0.2
        mat = (prf.get("materials") or ["PLA"])[0]
        pr_txt = prf["name"].upper() + ("" if fit["status"] in ("fits", "unknown") else f" · {fit['status'].replace('_', ' ').upper()}")
    except Exception:
        tol, mat, pr_txt = 0.2, "PLA", "—"
    rows = [("TITLE", meta["part"].replace("_", " ").upper()), ("DWG NO", f"{meta['part']}_{meta['tag']}"),
            ("SCALE", scale_txt), ("UNITS", f"MM · TOLERANCE ±{tol} UNLESS NOTED"),
            ("MATERIAL", f"{mat} · {meta.get('mass_g_pla', '?')} g SOLID"), ("PRINTER", pr_txt),
            ("DRAWN", f"CLAUDE · {meta['ts'][:10]}"), ("SHEET", "1 OF 1")]
    chrome.append(f'<rect class="border" x="{tx}" y="{ty}" width="{TITLE_W}" height="{TITLE_H}"/>')
    rh = TITLE_H / len(rows)
    for i, (k, v) in enumerate(rows):
        y = ty + rh * i
        if i:
            chrome.append(f'<line class="border thin" x1="{tx}" y1="{y:.1f}" x2="{tx + TITLE_W}" y2="{y:.1f}"/>')
        chrome.append(f'<text class="tk" x="{tx + 8}" y="{y + rh * 0.68:.1f}">{k}</text>')
        chrome.append(f'<text class="{"tv big" if i == 0 else "tv"}" x="{tx + 92}" y="{y + rh * (0.76 if i == 0 else 0.68):.1f}">{v}</text>')
    chrome.append(f'<line class="border thin" x1="{tx + 84}" y1="{ty}" x2="{tx + 84}" y2="{ty + TITLE_H}"/>')
    # third-angle projection symbol (truncated cone: side view + end view)
    px, py = tx - 120, ty + TITLE_H - 46
    chrome.append(f'<g class="sym"><path d="M{px},{py - 14} L{px + 34},{py - 22} L{px + 34},{py + 22} L{px},{py + 14} Z"/>'
                  f'<circle cx="{px + 62}" cy="{py}" r="22"/><circle cx="{px + 62}" cy="{py}" r="14"/>'
                  f'<path class="cl" d="M{px - 8},{py} H{px + 92} M{px + 62},{py - 30} V{py + 30}"/></g>')
    chrome.append(f'<text class="zone" x="{px + 42}" y="{py + 40}" text-anchor="middle">THIRD ANGLE PROJECTION</text>')
    chrome.append(f'<text class="zone" x="{MARGIN + 8}" y="{SHEET_H - MARGIN - 8}">LABCAD STUDIO · {meta["part"]} {meta["tag"]} · {meta.get("message", "")[:80].upper()}</text>')
    css = """
  .sheet.blueprint{--paper:#173563;--ink:#eaf0f8;--ink2:rgba(234,240,248,.62);--grid:rgba(234,240,248,.07)}
  .sheet.paper{--paper:#f3eee2;--ink:#1c1c1c;--ink2:rgba(28,28,28,.6);--grid:rgba(28,28,28,.07)}
  .bg{fill:var(--paper)} .grid{fill:url(#grid)}
  text{font-family:"Saira Semi Condensed","Barlow Semi Condensed","Instrument Sans",system-ui,sans-serif;fill:var(--ink);letter-spacing:.06em}
  .vis{fill:none;stroke:var(--ink);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
  .hid{fill:none;stroke:var(--ink2);stroke-width:1;stroke-dasharray:6 4;stroke-linejoin:round}
  .dim,.ext{fill:none;stroke:var(--ink);stroke-width:.8}
  .ext{stroke:var(--ink2)}
  .cl{fill:none;stroke:var(--ink2);stroke-width:.7;stroke-dasharray:14 3 3 3}
  .dimtxt{font-size:16px} .lbl{font-size:13px} .vlbl{font-size:15px;letter-spacing:.14em} .zone{font-size:11px;fill:var(--ink2)}
  .border{fill:none;stroke:var(--ink);stroke-width:1.6} .border.thin{stroke-width:.8}
  .tk{font-size:11px;fill:var(--ink2);letter-spacing:.12em} .tv{font-size:15px} .tv.big{font-size:19px;letter-spacing:.12em}
  .sym path,.sym circle{fill:none;stroke:var(--ink);stroke-width:1.2}
  #ah path{fill:var(--ink)} #dot circle{fill:var(--ink)}
"""
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W} {SHEET_H}" class="sheet blueprint" font-family="Saira Semi Condensed">',
           f'<style>{css}</style>',
           '<defs><pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="var(--grid)" stroke-width="1"/></pattern>'
           '<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,1 L10,5 L0,9 z"/></marker>'
           '<marker id="dot" viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5"><circle cx="3" cy="3" r="2.6"/></marker></defs>',
           f'<rect class="bg" width="{SHEET_W}" height="{SHEET_H}"/><rect class="grid" x="{MARGIN}" y="{MARGIN}" width="{SHEET_W - 2 * MARGIN}" height="{SHEET_H - 2 * MARGIN}"/>',
           *sh.parts, *chrome, '</svg>']
    Path(out).write_text("\n".join(svg))
    return dict(scale=scale_txt, holes=[(2 * r, len(c)) for r, c in hs])


if __name__ == "__main__":
    name, tag = sys.argv[1], sys.argv[2]
    vdir = ROOT / "parts" / name / "versions"
    meta = json.loads((vdir / f"{tag}.json").read_text())
    t = time.time()
    part = import_step(str(vdir / f"{tag}.step"))
    info = make_drawing(part, meta, vdir / f"{tag}_drawing.svg")
    print(json.dumps(dict(out=str(vdir / f"{tag}_drawing.svg"), seconds=round(time.time() - t, 1), **info)))
