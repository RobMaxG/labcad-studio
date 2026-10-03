"""Warm build worker for knob previews.

One JSON request per stdin line → one JSON reply per stdout line:
    {"id": "...", "part": "name", "params": {...}, "out": "parts/name/.preview/<id>"}
Keeps build123d imported so a preview costs the geometry (~0.5 s), not the 1 s import. Model code is
re-imported fresh every request, so edits to model.py show up without restarting anything.
Previews never touch params.json or versions/ — they only write into `out`.
"""
import contextlib, json, sys, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import build123d  # noqa: F401  — the expensive import, paid once
import build as B
from assembly import realize

for line in sys.stdin:
    if not line.strip():
        continue
    req = json.loads(line)
    try:
        with contextlib.redirect_stdout(sys.stderr):           # a stray print() in a model can't corrupt the protocol
            for m in [m for m in sys.modules if m == "parts" or m.startswith("parts.")]:
                del sys.modules[m]
            mod, P = B.effective_params(req["part"], req.get("params") or {})
            res = realize(mod, P, Path(req["out"]), part_name=req["part"], fine=False, step=False)
        res.pop("assembly"); res.pop("_parts")
        reply = dict(id=req["id"], ok=True, params=P, **res)
    except BaseException:                                       # SystemExit from a bad param name included
        reply = dict(id=req["id"], ok=False, error=traceback.format_exc()[-1800:])
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
