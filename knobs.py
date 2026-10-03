"""Knob metadata: what the Studio shows next to each slider.

A model can say exactly what it wants:

    KNOBS = dict(
        cut_w=dict(label="Cutout width", group="Cutout", help="The hole in the black film, side to side"),
        door_pos=dict(label="Door position", group="View", view=True, unit="", help="0 shut → 1 open"),
        clear=dict(label="Sliding gap", group="Fit", advanced=True),
        mode=dict(choices={0: "solid", 1: "hollow"}),
    )

Anything it leaves out is inferred: the label from the key ("door_t" → "Door thickness"), the help
from the comment on that key's line in `P = dict(...)`, the group from keys sharing a prefix or suffix.
`view=True` knobs only change how the assembly is shown (a door's position, say) — previewing them never
asks for a new version.
"""
import re
import sys
from pathlib import Path

ABBR = {"w": "width", "h": "height", "d": "diameter", "r": "radius", "t": "thickness", "len": "length",
        "dx": "x offset", "dy": "y offset", "dz": "z offset", "n": "count", "pos": "position", "num": "number",
        "dia": "diameter", "thk": "thickness", "ht": "height", "sz": "size", "pct": "percent", "deg": "angle",
        "x": "X", "y": "Y", "z": "Z", "od": "outer diameter", "id": "inner diameter", "ext": "extension",
        "min": "minimum", "max": "maximum", "cnt": "count", "rad": "radius", "off": "offset", "cols": "columns", "qty": "quantity"}
NO_UNIT_WORDS = {"pos", "frac", "count", "rows", "cols", "n", "num", "qty", "ratio", "scale", "side", "mode", "factor"}


def humanize(key):
    words = [ABBR.get(w, w) for w in key.split("_") if w]
    s = " ".join(words)
    return s[:1].upper() + s[1:]


def _comment_map(path):
    """key → trailing comment on its line inside `P = dict(` … `)`."""
    out = {}
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return out
    inside, depth = False, 0
    for ln in lines:
        if not inside and re.match(r"^\s*P\s*=\s*dict\(", ln):
            inside, depth = True, 0
        if not inside:
            continue
        code, _, comment = ln.partition("#")
        for k in re.findall(r"(?:^|[(,\s])([A-Za-z_]\w*)\s*=(?!=)", code):
            if k not in ("P", "dict") and comment.strip():
                out.setdefault(k, comment.strip())
        depth += code.count("(") - code.count(")")
        if depth <= 0 and ")" in code:
            inside = False
    return out


def _source_files(mod):
    """The model file plus any parts.* modules it pulled names from (derived parts inherit comments)."""
    files = [getattr(mod, "__file__", None)]
    for v in vars(mod).values():
        m = getattr(v, "__module__", None)
        if m and m.startswith("parts.") and m in sys.modules:
            files.append(getattr(sys.modules[m], "__file__", None))
    return [f for f in dict.fromkeys(files) if f]


def _auto_groups(keys):
    pre, suf = {}, {}
    for k in keys:
        bits = k.split("_")
        if len(bits) > 1:
            pre.setdefault(bits[0], []).append(k)
            suf.setdefault(bits[-1], []).append(k)
    g = {}
    for k in keys:
        bits = k.split("_")
        if len(bits) > 1 and len(pre.get(bits[0], [])) >= 2:
            g[k] = humanize(bits[0])
        elif len(bits) > 1 and len(suf.get(bits[-1], [])) >= 2:
            g[k] = humanize(bits[-1]) + "s"
        else:
            g[k] = "General"
    return g


def _range(k, v, ranges):
    if k in ranges:
        return list(ranges[k])
    if isinstance(v, bool):
        return [0, 1, 1]
    if isinstance(v, int):
        return [max(0, v // 2), max(v * 2, v + 4), 1]
    if isinstance(v, float):
        if v == 0:
            return [0, 5, 0.1]
        return [round(v * 0.25, 2), round(v * 2.5, 2), 0.1 if v < 5 else 0.5]
    return None


def _sentence(t):
    t = t.strip()
    return (t[:1].upper() + t[1:]) if t else t


def resolve(mod, P):
    meta = getattr(mod, "KNOBS", None) or {}
    ranges = getattr(mod, "RANGES", None) or {}
    comments = {}
    for f in reversed(_source_files(mod)):          # the model's own comments win over its base's
        comments.update(_comment_map(f))
    groups = _auto_groups(list(P))
    out = []
    for k, v in P.items():
        m = meta.get(k, {})
        rng = _range(k, v, ranges)
        if m.get("choices"):
            kind = "choice"
        elif isinstance(v, bool) or (rng and list(rng[:3]) == [0, 1, 1]):
            kind = "toggle"
        elif isinstance(v, (int, float)) and rng:
            kind = "int" if isinstance(v, int) and not isinstance(v, bool) else "float"
        else:
            kind = "fixed"
        if "unit" in m:
            unit = m["unit"]
        elif kind in ("toggle", "choice", "fixed") or isinstance(v, int):
            unit = ""
        elif "angle" in k or k.endswith("_deg"):
            unit = "°"
        elif NO_UNIT_WORDS & set(k.split("_")):
            unit = ""
        else:
            unit = "mm"
        out.append(dict(
            key=k, value=v, range=rng, kind=kind, unit=unit,
            label=m.get("label") or humanize(k),
            help=m.get("help") or _sentence(comments.get(k, "")),
            group=m.get("group") or groups[k],
            view=bool(m.get("view", False)),
            advanced=bool(m.get("advanced", False)),
            choices={str(a): b for a, b in m["choices"].items()} if m.get("choices") else None,
            described=bool(m),
        ))
    return out
