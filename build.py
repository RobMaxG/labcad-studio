"""Build one part → a new numbered version.

    .venv/bin/python build.py microfuge_rack -m "wells +0.2 for the Bambu"
    .venv/bin/python build.py microfuge_rack --set pitch=17 --set grip_bite=3.5
    .venv/bin/python build.py microfuge_rack --params '{"pitch": 17}'

Params resolve as  model.P  ←  parts/<name>/params.json  ←  --set/--params,
and the merged result is written back to params.json (the live knob state).

Writes, for version vNNN:
  versions/vNNN.json           what was built: params, components, which components changed, fit
  versions/vNNN.py             model.py snapshot — every version is reproducible
  versions/vNNN.stl / .step    the whole assembly (STEP is labelled + coloured per component)
  versions/vNNN/<comp>.stl/.step  each component in print orientation
  versions/vNNN/plate.3mf      every print, qty copies, one file for the slicer
  versions/vNNN.png, _thumb.png  renders
Prints one JSON line describing the new version on success.
"""
import argparse, importlib.util, json, re, shutil, subprocess, sys, time
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

def version_files(name):
    return sorted((PARTS / name / "versions").glob("v[0-9][0-9][0-9].json"))

def next_version(name):
    """One past the highest number ever issued — never reuse a deleted version's number, or chat links
    and trash restores would point at the wrong build."""
    d = PARTS / name
    seen = [int(p.stem[1:]) for p in version_files(name)]
    mark = d / "versions" / ".last"
    if mark.exists() and mark.read_text().strip().isdigit():
        seen.append(int(mark.read_text().strip()))
    trash = PARTS / "_trash"
    if trash.exists():
        seen += [int(m.group(1)) for t in trash.iterdir() if (m := re.match(rf"{re.escape(name)}-v(\d{{3}})-", t.name))]
    chat = d / "chat.jsonl"
    if chat.exists():
        for line in chat.read_text().splitlines():
            try:
                v = json.loads(line).get("version")
            except ValueError:
                continue
            if isinstance(v, int):
                seen.append(v)
    return max(seen, default=0) + 1

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("part"); ap.add_argument("-m", "--message", default="")
    ap.add_argument("--set", action="append", default=[], metavar="k=v"); ap.add_argument("--params", default=None)
    a = ap.parse_args()
    ov = dict(s.split("=", 1) for s in a.set)
    if a.params: ov.update(json.loads(a.params))
    mod, P = effective_params(a.part, ov)

    from build123d import export_stl, export_step
    from assembly import realize, write_plate, changes
    vdir = PARTS / a.part / "versions"; vdir.mkdir(exist_ok=True)
    v = next_version(a.part); tag = f"v{v:03d}"
    res = realize(mod, P, vdir / tag, part_name=a.part, fine=True, step=True)
    export_stl(res["assembly"], str(vdir / f"{tag}.stl"), tolerance=0.02, angular_tolerance=0.1)
    export_step(res["assembly"], str(vdir / f"{tag}.step"))
    try:
        write_plate(res["_parts"], vdir / tag / "plate.3mf")
    except Exception as e:                                            # a plate is a convenience, not the build
        print(f"plate.3mf skipped: {e}", file=sys.stderr)
    (PARTS / a.part / "params.json").write_text(json.dumps(P, indent=2))
    shutil.copy(PARTS / a.part / "model.py", vdir / f"{tag}.py")   # source snapshot — every version is reproducible
    prev_files = version_files(a.part)
    prev = json.loads(prev_files[-1].read_text()) if prev_files else None
    lin = PARTS / a.part / "lineage.json"
    info = dict(version=v, tag=tag, part=a.part, message=a.message, ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
                lineage=json.loads(lin.read_text()) if lin.exists() else None,
                params=P, kind=res["kind"], envelope=res["envelope"], bbox=res["bbox"],
                volume_cm3=res["volume_cm3"], mass_g_pla=res["mass_g_pla"], build_s=res["build_s"],
                components=res["components"], changes=changes(prev, res["components"]))
    (vdir / f"{tag}.json").write_text(json.dumps(info, indent=2))
    (vdir / ".last").write_text(str(v))
    subprocess.run([sys.executable, str(ROOT / "render.py"), "--version", str(vdir / f"{tag}.json"), str(vdir / f"{tag}.png")],
                   check=True, capture_output=True)
    print(json.dumps(info))

if __name__ == "__main__":
    main()
