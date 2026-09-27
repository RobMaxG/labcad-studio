"""Build one part → a new numbered version (stl + step + png + json).

    .venv/bin/python build.py microfuge_rack -m "wells +0.2 for the Bambu"
    .venv/bin/python build.py microfuge_rack --set pitch=17 --set grip_bite=3.5
    .venv/bin/python build.py microfuge_rack --params '{"pitch": 17}'

Params resolve as  model.P  ←  parts/<name>/params.json  ←  --set/--params,
and the merged result is written back to params.json (the live knob state).
Prints one JSON line describing the new version on success.
"""
import argparse, importlib.util, json, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = ROOT / "parts"

def load_model(name, path=None):
    """Import parts/<name>/model.py (or a version snapshot). `parts` is importable so derived
    parts can `from parts.<base>.model import P as BASE_P, build as base_build`."""
    if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(f"parts.{name}.model", path or PARTS / name / "model.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def coerce(v, like):
    if isinstance(like, bool): return str(v).lower() in ("1", "true", "yes")
    if isinstance(like, int) and not isinstance(like, bool): return int(round(float(v)))
    if isinstance(like, float): return float(v)
    return v

def effective_params(name, overrides=None):
    mod = load_model(name); P = dict(mod.P)
    pj = PARTS / name / "params.json"
    if pj.exists():
        for k, v in json.loads(pj.read_text()).items():
            if k in P: P[k] = coerce(v, P[k])
    for k, v in (overrides or {}).items():
        if k not in P: raise SystemExit(f"unknown param {k!r}; known: {sorted(P)}")
        P[k] = coerce(v, P[k])
    return mod, P

def next_version(name):
    vs = sorted((PARTS / name / "versions").glob("v*.json"))
    return (int(vs[-1].stem[1:]) + 1) if vs else 1

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("part"); ap.add_argument("-m", "--message", default="")
    ap.add_argument("--set", action="append", default=[], metavar="k=v"); ap.add_argument("--params", default=None)
    a = ap.parse_args()
    ov = dict(s.split("=", 1) for s in a.set)
    if a.params: ov.update(json.loads(a.params))
    mod, P = effective_params(a.part, ov)

    from build123d import export_stl, export_step
    t0 = time.time(); part = mod.build(P); t_build = time.time() - t0
    bb = part.bounding_box(); ext = bb.size
    vdir = PARTS / a.part / "versions"; vdir.mkdir(exist_ok=True)
    v = next_version(a.part); tag = f"v{v:03d}"
    export_stl(part, str(vdir / f"{tag}.stl"), tolerance=0.02, angular_tolerance=0.1)
    export_step(part, str(vdir / f"{tag}.step"))
    subprocess.run([sys.executable, str(ROOT / "render.py"), str(vdir / f"{tag}.stl"), str(vdir / f"{tag}.png")],
                   check=True, capture_output=True)
    (PARTS / a.part / "params.json").write_text(json.dumps(P, indent=2))
    shutil.copy(PARTS / a.part / "model.py", vdir / f"{tag}.py")   # source snapshot — every version is reproducible
    lin = PARTS / a.part / "lineage.json"
    info = dict(version=v, tag=tag, part=a.part, message=a.message, ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
                lineage=json.loads(lin.read_text()) if lin.exists() else None,
                params=P, envelope=[round(ext.X, 2), round(ext.Y, 2), round(ext.Z, 2)],
                bbox=[[round(bb.min.X, 2), round(bb.min.Y, 2), round(bb.min.Z, 2)], [round(bb.max.X, 2), round(bb.max.Y, 2), round(bb.max.Z, 2)]],
                volume_cm3=round(part.volume / 1000, 1), mass_g_pla=round(part.volume / 1000 * 1.24, 1),
                build_s=round(t_build, 2))
    (vdir / f"{tag}.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info))

if __name__ == "__main__":
    main()
