"""LabCAD Studio — view, annotate, tweak, and talk to Claude about printable parts.
    .venv/bin/uvicorn studio.server:app --host 127.0.0.1 --port 8505

The "Send to Claude" runner is deliberately scoped: acceptEdits inside this repo plus an
allowlist of build.py / render.py. Nothing else gets to run without a human.
Knob previews go through a warm worker (preview_worker.py) and never create versions.
"""
import asyncio, base64, io, json, os, re, shutil, signal, sys, time, uuid, zipfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "parts"
PY = ROOT / ".venv" / "bin" / "python"
CLAUDE = os.environ.get("CLAUDE_PATH") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
IDLE_TIMEOUT = float(os.environ.get("LABCAD_IDLE_TIMEOUT", "600"))
ALLOWED_TOOLS = ["Bash(.venv/bin/python build.py:*)", "Bash(.venv/bin/python render.py:*)",
                 "Bash(ls:*)", "Bash(cat:*)", "Read", "Edit", "Write", "Glob", "Grep",
                 "WebSearch", "WebFetch"]   # read-only web, for labware datasheets
sys.path.insert(0, str(ROOT))
from build import effective_params  # noqa: E402
import printers as pr  # noqa: E402
import knobs as kn  # noqa: E402
from studio import accounts  # noqa: E402

app = FastAPI(title="LabCAD Studio")
app.include_router(accounts.router)
BUILD_LOCK = asyncio.Lock()   # one build/Claude run at a time — they share params.json
DRAW_LOCK = asyncio.Lock()    # drafting only reads a version, so it never waits behind an Claude run


def part_dir(name):
    d = PARTS / name
    if not d.is_dir() or not (d / "model.py").exists():
        raise HTTPException(404, f"no part {name!r}")
    return d


def versions(name):
    return [json.loads(p.read_text()) for p in sorted((PARTS / name / "versions").glob("v[0-9][0-9][0-9].json"))]


def heuristic_range(k, v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return [max(0, v // 2), max(v * 2, v + 4), 1]
    if isinstance(v, float):
        if v == 0:
            return [0, 5, 0.1]
        return [round(v * 0.25, 2), round(v * 2.5, 2), 0.1 if v < 5 else 0.5]
    return None


def lineage(name):
    f = PARTS / name / "lineage.json"
    return json.loads(f.read_text()) if f.exists() else None


def printed(name):
    f = PARTS / name / "printed.json"
    return json.loads(f.read_text()) if f.exists() else {}


def spec(name):
    mod, P = effective_params(name)
    return dict(name=name, doc=(mod.__doc__ or "").strip(), params=P, knobs=kn.resolve(mod, P), lineage=lineage(name),
                printer=pr.prof(name), printed=printed(name))


def log_chat(name, entry):
    with open(PARTS / name / "chat.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


@app.get("/api/parts")
def list_parts():
    out = []
    for d in sorted(PARTS.iterdir()):
        if (d / "model.py").exists():
            vs = versions(d.name)
            out.append(dict(name=d.name, versions=len(vs), latest=vs[-1] if vs else None, lineage=lineage(d.name)))
    return out


@app.get("/api/family")
def family():
    """Every part as a node (with its versions); edges from parent → fork with the version it was forked at."""
    parts = list_parts()
    for p in parts:
        p["versions_list"] = [dict(version=v["version"], tag=v["tag"], ts=v["ts"], message=v["message"], mass_g_pla=v.get("mass_g_pla"))
                              for v in versions(p["name"])]
        p["thumb"] = f"/api/parts/{p['name']}/thumb?{int((PARTS / p['name'] / 'thumb.jpg').stat().st_mtime) if (PARTS / p['name'] / 'thumb.jpg').exists() else 0}"
        p["posed"] = (PARTS / p["name"] / "thumb.jpg").exists()
    return dict(nodes=parts, edges=[dict(parent=p["lineage"]["parent"], child=p["name"], at=p["lineage"]["from_version"],
                                         mode=p["lineage"]["mode"]) for p in parts if p.get("lineage")])


# ---------- thumbnails (you pose the view, that view becomes the card) ----------
class ThumbReq(BaseModel):
    image: str
    pose: dict | None = None


@app.post("/api/parts/{name}/thumbnail")
def set_thumb(name, req: ThumbReq):
    d = part_dir(name)
    head, _, b64 = req.image.partition(",")
    (d / "thumb.jpg").write_bytes(base64.b64decode(b64))
    if req.pose:
        (d / "pose.json").write_text(json.dumps(req.pose))
    return dict(ok=True)


@app.get("/api/parts/{name}/thumb")
def get_thumb(name):
    d = part_dir(name)
    if (d / "thumb.jpg").exists():
        return FileResponse(d / "thumb.jpg")
    vs = versions(name)
    for v in reversed(vs):
        for suffix in ("_thumb.png", ".png"):
            f = d / "versions" / f"{v['tag']}{suffix}"
            if f.exists():
                return FileResponse(f)
    raise HTTPException(404)


@app.get("/api/parts/{name}/versions/{tag}/drawing")
async def drawing(name, tag, c: str | None = None):
    """Blueprint sheet for a version (or one component of it); drafted on first request, cached beside the version."""
    d = part_dir(name)
    if tag == "latest":
        vs = versions(name)
        if not vs:
            raise HTTPException(404)
        tag = vs[-1]["tag"]
    comp = Path(c).name if c else None
    f = d / "versions" / (f"{tag}_{comp}_drawing.svg" if comp else f"{tag}_drawing.svg")
    if not f.exists():
        src = d / "versions" / tag / f"{comp}.step" if comp else d / "versions" / f"{tag}.step"
        if not src.exists():
            raise HTTPException(404)
        async with DRAW_LOCK:
            proc = await asyncio.create_subprocess_exec(str(PY), str(ROOT / "drawing.py"), name, tag, *([comp] if comp else []), cwd=ROOT,
                                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
        if proc.returncode != 0:
            return JSONResponse(status_code=500, content=dict(error=err.decode(errors="replace")[-1500:]))
    return FileResponse(f, media_type="image/svg+xml", filename=f"{name}_{tag}_drawing.svg" if False else None)


class RenameReq(BaseModel):
    new_name: str


@app.post("/api/parts/{name}/rename")
def rename_part(name, req: RenameReq):
    """Rename the folder id and fix every reference: version records, children's lineage, derived imports."""
    d = part_dir(name)
    new = req.new_name.strip().lower().replace(" ", "_").replace("-", "_")
    if new == name:
        return dict(name=name)
    if not SAFE.match(new):
        raise HTTPException(400, "Name must be letters, digits and underscores, starting with a letter.")
    if (PARTS / new).exists():
        raise HTTPException(409, f"A part called {new!r} already exists.")
    shutil.move(str(d), str(PARTS / new))
    nd = PARTS / new
    for vj in (nd / "versions").glob("v*.json"):
        info = json.loads(vj.read_text()); info["part"] = new; vj.write_text(json.dumps(info, indent=2))
    for f in (nd / "versions").glob("*_drawing.svg"):
        f.unlink()                                                     # title block names the part; redraft on demand
    pat = re.compile(rf"\bparts\.{re.escape(name)}\.")
    for other in PARTS.iterdir():
        if not (other / "model.py").exists():
            continue
        for py in [other / "model.py", *other.glob("base_*.py"), *(other / "versions").glob("v*.py")]:
            src = py.read_text()
            if pat.search(src):
                py.write_text(pat.sub(f"parts.{new}.", src))
        lf = other / "lineage.json"
        if lf.exists():
            lin = json.loads(lf.read_text())
            if lin.get("parent") == name:
                lin["parent"] = new; lf.write_text(json.dumps(lin, indent=2))
    log_chat(new, dict(role="build", text=f"renamed from {name} to {new}", version=None, ts=time.strftime("%Y-%m-%dT%H:%M:%S"), params_changed={}))
    return dict(name=new)


class RelabelReq(BaseModel):
    message: str


@app.patch("/api/parts/{name}/versions/{tag}")
def relabel_version(name, tag, req: RelabelReq):
    vj = part_dir(name) / "versions" / f"{tag}.json"
    if not vj.exists():
        raise HTTPException(404)
    info = json.loads(vj.read_text()); info["message"] = req.message.strip(); vj.write_text(json.dumps(info, indent=2))
    f = vj.with_name(f"{tag}_drawing.svg")
    if f.exists():
        f.unlink()
    return info


@app.get("/api/printers")
def get_printers():
    return pr.load()


class PrinterReq(BaseModel):
    profile: dict


@app.put("/api/printers/{key}")
def put_printer(key, req: PrinterReq):
    k = key.strip().lower().replace(" ", "_").replace("-", "_")
    if not SAFE.match(k):
        raise HTTPException(400, "Id must be letters, digits and underscores, starting with a letter.")
    d = pr.load()
    prof = dict(pr.FIELDS, **{f: v for f, v in req.profile.items() if f in pr.FIELDS})
    if not str(prof.get("name", "")).strip():
        raise HTTPException(400, "Give it a name.")
    try:
        prof["bed"] = [float(v) for v in prof["bed"]][:3]
        for f in ("nozzle", "layer", "hole_shrink", "xy_tolerance", "clearance_slip", "clearance_press",
                  "min_wall", "min_feature", "max_overhang"):
            prof[f] = None if prof[f] in (None, "") else float(prof[f])
    except (TypeError, ValueError):
        raise HTTPException(400, "Those numbers don't parse — check the numeric fields.")
    if len(prof["bed"]) != 3 or any(v <= 0 for v in prof["bed"]):
        raise HTTPException(400, "Bed needs three positive numbers (X, Y, Z in mm).")
    if isinstance(prof["materials"], str):
        prof["materials"] = [m.strip() for m in prof["materials"].split(",") if m.strip()]
    d["printers"][k] = prof
    d.setdefault("default", k)
    pr.save(d)
    return dict(key=k, profile=prof, default=d["default"])


@app.delete("/api/printers/{key}")
def del_printer(key):
    d = pr.load()
    if key not in d["printers"]:
        raise HTTPException(404)
    if len(d["printers"]) == 1:
        raise HTTPException(409, "That's the only printer — add another before removing this one.")
    used = [p.name for p in PARTS.iterdir() if (p / "printer.json").exists()
            and json.loads((p / "printer.json").read_text()).get("printer") == key]
    del d["printers"][key]
    if d.get("default") == key:
        d["default"] = next(iter(d["printers"]))
    pr.save(d)
    for name in used:
        (PARTS / name / "printer.json").unlink()          # those parts fall back to the default
    return dict(ok=True, freed=used, default=d["default"])


@app.post("/api/printers/{key}/default")
def set_default_printer(key):
    d = pr.load()
    if key not in d["printers"]:
        raise HTTPException(404)
    d["default"] = key
    pr.save(d)
    return dict(default=key)


class PartPrinterReq(BaseModel):
    printer: str | None = None


@app.post("/api/parts/{name}/printer")
def set_part_printer(name, req: PartPrinterReq):
    part_dir(name)
    f = PARTS / name / "printer.json"
    if not req.printer:
        if f.exists():
            f.unlink()
    else:
        if req.printer not in pr.load()["printers"]:
            raise HTTPException(404, "no such printer")
        pr.set_target(name, req.printer)
    return dict(printer=pr.prof(name), fit=part_fit(name))


FIT_ORDER = ["fits", "rotate", "diagonal", "unknown", "too_big"]


def part_fit(name, key=None, version=None):
    """Bed fit for every component of a version (the assembly envelope is irrelevant — you print the pieces).
    Top-level fields describe the worst component, so single-part callers read it unchanged."""
    vs = versions(name)
    if not vs:
        return None
    v = next((x for x in vs if x["version"] == version), vs[-1]) if version else vs[-1]
    comps = v.get("components") or [dict(name="part", label=name, envelope=v["envelope"])]
    fits = [dict(pr.fit_check(c["envelope"], part=name, key=key), name=c["name"], label=c.get("label", c["name"])) for c in comps]
    worst = max(fits, key=lambda f: FIT_ORDER.index(f["status"]) if f["status"] in FIT_ORDER else 0)
    return dict(worst, components=fits, worst=worst["name"] if len(fits) > 1 else None)


@app.get("/api/parts/{name}/fit")
def get_fit(name, printer: str | None = None, version: int | None = None):
    part_dir(name)
    return part_fit(name, printer, version) or dict(status="unknown")


# ---------- what's been physically printed (so the Print tab can say what needs reprinting) ----------
class PrintedReq(BaseModel):
    component: str
    version: int | None = None       # None = forget it


@app.post("/api/parts/{name}/printed")
def set_printed(name, req: PrintedReq):
    d = part_dir(name)
    rec = printed(name)
    if req.version is None:
        rec.pop(req.component, None)
    else:
        v = next((x for x in versions(name) if x["version"] == req.version), None)
        if not v:
            raise HTTPException(404, "no such version")
        c = next((c for c in v.get("components") or [] if c["name"] == req.component), None)
        rec[req.component] = dict(version=req.version, tag=v["tag"], ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
                                  fingerprint=c["fingerprint"] if c else None)
    (d / "printed.json").write_text(json.dumps(rec, indent=2))
    return rec


# ---------- live knob preview: a warm worker builds into a scratch dir; nothing is versioned ----------
class PreviewWorker:
    def __init__(self):
        self.proc, self.lock = None, asyncio.Lock()

    async def _start(self):
        log = open(ROOT / "studio" / "preview_worker.log", "ab")
        self.proc = await asyncio.create_subprocess_exec(
            str(PY), str(ROOT / "preview_worker.py"), cwd=ROOT, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=log, limit=16 * 1024 * 1024)

    async def run(self, req, timeout=90):
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                await self._start()
            self.proc.stdin.write((json.dumps(req) + "\n").encode())
            await self.proc.stdin.drain()
            try:
                line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
            except asyncio.TimeoutError:
                self.proc.kill(); self.proc = None
                return dict(ok=False, error=f"Preview took longer than {timeout} s and was stopped.")
            if not line:
                self.proc = None
                return dict(ok=False, error="The preview worker crashed (see studio/preview_worker.log); try again.")
            return json.loads(line)


PREVIEW = PreviewWorker()


class PreviewReq(BaseModel):
    params: dict = {}


@app.post("/api/parts/{name}/preview")
async def preview(name, req: PreviewReq):
    d = part_dir(name)
    pid = time.strftime("%H%M%S") + uuid.uuid4().hex[:6]
    root = d / ".preview"
    res = await PREVIEW.run(dict(id=pid, part=name, params=req.params, out=str(root / pid)))
    for old in sorted(root.glob("*"))[:-4] if root.exists() else []:   # keep the last few, drop the rest
        shutil.rmtree(old, ignore_errors=True)
    if not res.get("ok"):
        return JSONResponse(status_code=422, content=dict(error=res.get("error", "preview failed")))
    for c in res["components"]:
        c["url"] = f"/api/parts/{name}/preview/{pid}/{c['name']}.stl"
    return res


@app.get("/api/parts/{name}/preview/{pid}/{fn}")
def preview_file(name, pid, fn):
    f = part_dir(name) / ".preview" / Path(pid).name / Path(fn).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/api/parts/{name}/pose")
def get_pose(name):
    f = part_dir(name) / "pose.json"
    return json.loads(f.read_text()) if f.exists() else None


# ---------- trash: nothing is ever hard-deleted from the Studio ----------
TRASH = PARTS / "_trash"


def children_of(name):
    return [p["name"] for p in list_parts() if p.get("lineage") and p["lineage"]["parent"] == name]


@app.post("/api/parts/{name}/detach")
def detach(name):
    """Turn a derived variant into an independent copy: snapshot the base's model next to it and repoint the import."""
    d = part_dir(name)
    lin = lineage(name)
    if not lin or lin["mode"] != "derive":
        raise HTTPException(400, "Only derived variants can be detached.")
    base = lin["parent"]
    base_src = PARTS / base / "model.py"
    if not base_src.exists():
        raise HTTPException(404, f"base {base!r} is gone; nothing to snapshot")
    snap_name = f"base_{base}"
    shutil.copy(base_src, d / f"{snap_name}.py")
    src = (d / "model.py").read_text().replace(f"from parts.{base}.model import", f"from parts.{name}.{snap_name} import")
    (d / "model.py").write_text(src)
    lin.update(mode="copy", note=(lin.get("note", "") + f" (detached from {base} {time.strftime('%Y-%m-%d')})").strip())
    (d / "lineage.json").write_text(json.dumps(lin, indent=2))
    log_chat(name, dict(role="build", text=f"detached from {base}: now an independent copy", version=None, ts=time.strftime("%Y-%m-%dT%H:%M:%S"), params_changed={}))
    return dict(ok=True, lineage=lin)


@app.delete("/api/parts/{name}")
def delete_part(name, detach_children: bool = False):
    d = part_dir(name)
    kids = [k for k in children_of(name) if lineage(k)["mode"] == "derive"]
    if kids and not detach_children:
        raise HTTPException(409, f"{', '.join(kids)} derive from this part. Detach them first (or delete with detach_children=1).")
    for k in kids:
        detach(k)
    TRASH.mkdir(exist_ok=True)
    tid = f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(d), str(TRASH / tid))
    (TRASH / tid / "_trash.json").write_text(json.dumps(dict(kind="part", name=name, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))))
    return dict(ok=True, trash_id=tid, detached=kids)


@app.delete("/api/parts/{name}/versions/{tag}")
def delete_version(name, tag):
    d = part_dir(name)
    vs = versions(name)
    if len(vs) <= 1:
        raise HTTPException(409, "That's the only version; delete the part instead.")
    if not (d / "versions" / f"{tag}.json").exists():
        raise HTTPException(404)
    was_latest = vs[-1]["tag"] == tag
    TRASH.mkdir(exist_ok=True)
    tid = f"{name}-{tag}-{time.strftime('%Y%m%d-%H%M%S')}"
    td = TRASH / tid
    td.mkdir()
    snap_was = (d / "versions" / f"{tag}.py").read_text() if (d / "versions" / f"{tag}.py").exists() else None
    for f in [*(d / "versions").glob(f"{tag}.*"), *(d / "versions").glob(f"{tag}_*"), d / "versions" / tag]:
        if f.exists():
            shutil.move(str(f), str(td / f.name))
    (td / "_trash.json").write_text(json.dumps(dict(kind="version", name=name, tag=tag, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))))
    rolled = None
    if was_latest:
        # The working state came from the version just deleted; put it back to the new latest, or the next
        # knob tweak / Claude run would silently build on top of the experiment that was thrown away.
        prev = versions(name)[-1]
        (d / "params.json").write_text(json.dumps(prev["params"], indent=2))
        snap = d / "versions" / f"{prev['tag']}.py"
        if snap.exists() and snap_was is not None and (d / "model.py").read_text() == snap_was:
            shutil.copy(snap, d / "model.py")
        rolled = prev["tag"]
    return dict(ok=True, trash_id=tid, rolled_back_to=rolled)


@app.get("/api/trash")
def list_trash():
    if not TRASH.exists():
        return []
    out = []
    for d in sorted(TRASH.iterdir()):
        m = d / "_trash.json"
        if m.exists():
            out.append(dict(id=d.name, **json.loads(m.read_text())))
    return out


@app.post("/api/trash/{tid}/restore")
def restore_trash(tid):
    td = TRASH / Path(tid).name
    if not td.exists():
        raise HTTPException(404)
    m = json.loads((td / "_trash.json").read_text())
    if m["kind"] == "part":
        dest = PARTS / m["name"]
        if dest.exists():
            raise HTTPException(409, f"a part called {m['name']!r} exists again; rename it first")
        (td / "_trash.json").unlink()
        shutil.move(str(td), str(dest))
    else:
        dest = PARTS / m["name"] / "versions"
        if not dest.exists():
            raise HTTPException(409, f"part {m['name']!r} is gone; restore it first")
        for f in [*td.glob(f"{m['tag']}.*"), *td.glob(f"{m['tag']}_*"), td / m["tag"]]:
            if f.exists():
                shutil.move(str(f), str(dest / f.name))
        shutil.rmtree(td)
    return dict(ok=True, **m)


@app.delete("/api/trash/{tid}")
def purge_trash(tid):
    td = TRASH / Path(tid).name
    if not td.exists():
        raise HTTPException(404)
    shutil.rmtree(td)
    return dict(ok=True)


@app.delete("/api/trash")
def empty_trash():
    if TRASH.exists():
        shutil.rmtree(TRASH)
    return dict(ok=True)


DERIVE_TEMPLATE = '''"""{title} — derived from {base} (v{at}).
Inherits the base build; override numbers in P, and add or subtract geometry in build() after base_build().
Improvements to the base flow into this part on its next rebuild.
"""
from build123d import *
from parts.{base}.model import P as BASE_P, RANGES as BASE_RANGES, build as base_build

P = dict(BASE_P,
    # override base numbers here, e.g. pitch=17.0
)
RANGES = dict(BASE_RANGES)

def build(P):
    part = base_build(P)
    # --- bespoke features go here, e.g.:
    # part -= Pos(0, 0, 10) * Box(20, 5, 30)
    return part
'''

SAFE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class ForkReq(BaseModel):
    new_name: str
    from_version: int | None = None
    mode: str = "derive"       # derive = imports the base; copy = independent snapshot
    note: str = ""


@app.post("/api/parts/{name}/fork")
async def fork(name, req: ForkReq):
    part_dir(name)
    new = req.new_name.strip().lower().replace(" ", "_").replace("-", "_")
    if not SAFE.match(new):
        raise HTTPException(400, "Name must be letters, digits and underscores, starting with a letter.")
    if (PARTS / new).exists():
        raise HTTPException(409, f"A part called {new!r} already exists.")
    vs = versions(name)
    if not vs:
        raise HTTPException(400, "Build the base at least once before forking it.")
    at = req.from_version or vs[-1]["version"]
    src = next((v for v in vs if v["version"] == at), None)
    if not src:
        raise HTTPException(404, f"no v{at:03d}")
    d = PARTS / new
    d.mkdir()
    (d / "__init__.py").touch()
    (d / "versions").mkdir()
    snap = PARTS / name / "versions" / f"{src['tag']}.py"
    if req.mode == "copy":
        shutil.copy(snap if snap.exists() else PARTS / name / "model.py", d / "model.py")
        (d / "params.json").write_text(json.dumps(src["params"], indent=2))
    else:
        base_defaults = load_defaults(name)
        overrides = {k: v for k, v in src["params"].items() if base_defaults.get(k) != v}
        body = DERIVE_TEMPLATE.format(title=new.replace("_", " "), base=name, at=at)
        if overrides:
            body = body.replace("    # override base numbers here, e.g. pitch=17.0\n",
                                "".join(f"    {k}={v!r},\n" for k, v in overrides.items()))
        (d / "model.py").write_text(body)
        (d / "params.json").write_text(json.dumps(src["params"], indent=2))
    (d / "lineage.json").write_text(json.dumps(dict(parent=name, from_version=at, mode=req.mode, note=req.note,
                                                    ts=time.strftime("%Y-%m-%dT%H:%M:%S")), indent=2))
    # build once so the fork opens with a v001 identical to its fork point
    async with BUILD_LOCK:
        proc = await asyncio.create_subprocess_exec(str(PY), str(ROOT / "build.py"), new, "-m",
                                                    f"forked from {name} v{at:03d} ({req.mode})" + (f" — {req.note}" if req.note else ""),
                                                    cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
    if proc.returncode != 0:
        shutil.rmtree(d)
        return JSONResponse(status_code=500, content=dict(error=err.decode(errors="replace")[-2000:]))
    return dict(name=new, first=json.loads(out.decode().strip().splitlines()[-1]))


def load_defaults(name):
    from build import load_model
    return dict(load_model(name).P)


@app.post("/api/parts/{name}/restore/{tag}")
async def restore(name, tag):
    """Make an old version the working state (model.py + params.json), then rebuild as a new version."""
    d = part_dir(name)
    vj = d / "versions" / f"{tag}.json"
    if not vj.exists():
        raise HTTPException(404)
    info = json.loads(vj.read_text())
    snap = d / "versions" / f"{tag}.py"
    if snap.exists():
        shutil.copy(snap, d / "model.py")
    (d / "params.json").write_text(json.dumps(info["params"], indent=2))
    async with BUILD_LOCK:
        proc = await asyncio.create_subprocess_exec(str(PY), str(ROOT / "build.py"), name, "-m", f"restored {tag}",
                                                    cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
    if proc.returncode != 0:
        return JSONResponse(status_code=500, content=dict(error=err.decode(errors="replace")[-2000:]))
    new = json.loads(out.decode().strip().splitlines()[-1])
    log_chat(name, dict(role="build", text=f"restored {tag}", version=new["version"], ts=new["ts"], params_changed={}))
    return new


@app.get("/api/parts/{name}")
def get_part(name):
    part_dir(name)
    s = spec(name)
    s["versions"] = versions(name)
    chat = PARTS / name / "chat.jsonl"
    s["chat"] = [json.loads(l) for l in chat.read_text().splitlines() if l.strip()] if chat.exists() else []
    return s


def resolve_tag(name, tag):
    if tag == "latest":
        vs = versions(name)
        if not vs:
            raise HTTPException(404)
        return vs[-1]["tag"]
    return Path(tag).name


@app.get("/api/parts/{name}/versions/{tag}/c/{fn}")
def get_component_file(name, tag, fn):
    """One component's print-ready file (frame.stl, door.step, plate.3mf)."""
    tag = resolve_tag(name, tag)
    f = part_dir(name) / "versions" / tag / Path(fn).name
    if not f.exists() or f.suffix not in (".stl", ".step", ".3mf"):
        raise HTTPException(404)
    return FileResponse(f, filename=f"{name}_{tag}_{f.name}")


@app.get("/api/parts/{name}/versions/{tag}/{ext}")
def get_file(name, tag, ext):
    tag = resolve_tag(name, tag)
    vdir = part_dir(name) / "versions"
    if ext == "zip":                                   # every print in one download
        cdir = vdir / tag
        if not cdir.is_dir():
            raise HTTPException(404, "this version predates components; download its STL instead")
        info = json.loads((vdir / f"{tag}.json").read_text())
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for c in info.get("components") or []:
                for sfx in ("stl", "step"):
                    f = cdir / f"{c['name']}.{sfx}"
                    if f.exists():
                        z.write(f, f"{name}_{tag}/{c['name']}{'' if c.get('qty', 1) == 1 else '_x' + str(c['qty'])}.{sfx}")
            if (cdir / "plate.3mf").exists():
                z.write(cdir / "plate.3mf", f"{name}_{tag}/plate.3mf")
        return StreamingResponse(iter([buf.getvalue()]), media_type="application/zip",
                                 headers={"content-disposition": f'attachment; filename="{name}_{tag}.zip"'})
    f = vdir / f"{tag}.{ext}"
    if not f.exists() or ext not in ("stl", "step", "png", "json"):
        raise HTTPException(404)
    return FileResponse(f, filename=f"{name}_{tag}.{ext}" if ext in ("stl", "step") else None)


class BuildReq(BaseModel):
    params: dict = {}
    message: str = ""


@app.post("/api/parts/{name}/build")
async def build_part(name, req: BuildReq):
    part_dir(name)
    async with BUILD_LOCK:
        proc = await asyncio.create_subprocess_exec(
            str(PY), str(ROOT / "build.py"), name, "-m", req.message or "knob tweak", "--params", json.dumps(req.params),
            cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
    if proc.returncode != 0:
        return JSONResponse(status_code=500, content=dict(error=err.decode(errors="replace")[-2000:]))
    info = json.loads(out.decode().strip().splitlines()[-1])
    log_chat(name, dict(role="build", text=req.message or "knob tweak", version=info["version"], ts=info["ts"], params_changed=req.params))
    return info


class Pin(BaseModel):
    n: int
    x: float
    y: float
    z: float
    note: str = ""
    component: str | None = None


class FeedbackReq(BaseModel):
    text: str
    pins: list[Pin] = []
    version: int | None = None
    measures: list[dict] = []
    shot: str | None = None          # data-URL jpeg of the viewport, pins drawn in
    attachments: list[str] = []      # data-URL images the user pasted/dropped
    scope: str | None = None         # a component name, or None = the whole assembly


def save_data_url(name, data_url, stem):
    """Write a data: URL image into parts/<name>/shots/, return the filename."""
    head, _, b64 = data_url.partition(",")
    ext = "png" if "png" in head else "jpg"
    d = PARTS / name / "shots"
    d.mkdir(exist_ok=True)
    fn = f"{stem}.{ext}"
    (d / fn).write_bytes(base64.b64decode(b64))
    return fn


@app.get("/api/parts/{name}/shots/{fn}")
def get_shot(name, fn):
    f = part_dir(name) / "shots" / Path(fn).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


def status_line(evt):
    """Pick a one-line human status out of a stream-json event."""
    if evt.get("type") != "assistant":
        return None
    for block in evt.get("message", {}).get("content", []):
        if block.get("type") == "tool_use":
            inp = block.get("input", {})
            nm = block.get("name")
            if nm == "Bash":
                return "$ " + str(inp.get("command", ""))[:140]
            if nm in ("Edit", "Write", "Read"):
                return f"{nm.lower()} {Path(str(inp.get('file_path', ''))).name}"
            return nm
        if block.get("type") == "text" and block["text"].strip():
            return block["text"].strip()[:160]
    return None


def compose_prompt(name, req: FeedbackReq, P, latest, shots):
    lines = [f'[LabCAD Studio — feedback on part "{name}", the user is looking at v{req.version or latest}]', "",
             "The user says:", req.text.strip() or "(no text — see pins)", ""]
    if shots:
        lines.append("Images (Read each one before deciding anything):")
        lines += [f"  parts/{name}/shots/{fn} — {'The user\'s viewport right now, their pins numbered on it' if fn.endswith('_view.jpg') else 'a photo the user attached'}" for fn in shots]
        lines.append("")
    vs = versions(name)
    cur = next((v for v in vs if v["version"] == (req.version or latest)), vs[-1] if vs else None)
    comps = (cur or {}).get("components") or []
    if len(comps) > 1:
        lines.append(f"This part is an ASSEMBLY of {len(comps)} components (see 'Assemblies' in CLAUDE.md):")
        for c in comps:
            lines.append(f"  {c['name']:>12} — {c['label']}: prints {'×'.join(str(round(e)) for e in c['envelope'])} mm, "
                         f"{c['mass_g_pla']} g{' ×' + str(c['qty']) if c.get('qty', 1) > 1 else ''}"
                         + (f"; {c['note']}" if c.get("note") else ""))
        if req.scope:
            lab = next((c["label"] for c in comps if c["name"] == req.scope), req.scope)
            lines.append(f"The user scoped this message to the **{lab}** ({req.scope}). Change that component; touch the others "
                         "only where a mating feature has to follow, and say so.")
        else:
            lines.append("The user scoped this message to the WHOLE ASSEMBLY. Make the change wherever it belongs and keep every "
                         "mating feature consistent; the version record will list which components changed.")
        lines.append("")
    if req.pins:
        lines.append("Pins the user placed on the surface (assembly coordinates, mm, Z up; the component each pin landed on is named):")
        lines += [f"  {p.n}. ({p.x:.1f}, {p.y:.1f}, {p.z:.1f})" + (f" on {p.component}" if p.component else "")
                  + f" — {p.note or 'no note'}" for p in req.pins]
        lines.append("")
    if req.measures:
        lines += ["Measurements the user took:"] + [f"  {m.get('label', '')}: {m.get('mm', 0):.2f} mm" for m in req.measures] + [""]
    lin = lineage(name)
    if lin:
        lines += [f"Lineage: this part is a {lin['mode']} fork of \"{lin['parent']}\" at v{lin['from_version']:03d}"
                  + (" — its model.py imports the base's build(); put bespoke geometry after base_build(), and only edit the base if the change belongs to every variant." if lin["mode"] == "derive" else " — an independent copy.")
                  + (f" Fork note: {lin['note']}" if lin.get("note") else ""), ""]
    lines += ["Target printer for this part (design to it; if a number here blocks what the user asked for, say so):",
              pr.describe(part=name), "",
              "Current params.json:", json.dumps(P), "",
              f"Make the change (edit parts/{name}/model.py and/or parts/{name}/params.json), rebuild with",
              f'  .venv/bin/python build.py {name} -m "<short what-changed>"',
              "and reply in at most 4 short sentences — the reply is shown in the Studio chat next to the new version."
              + (" For an assembly, name which components changed (= which the user has to reprint)." if len(comps) > 1 else ""),
              "If the request is genuinely ambiguous, don't guess: ask one question and skip the rebuild."]
    return "\n".join(lines)


@app.post("/api/parts/{name}/feedback")
async def feedback(name, req: FeedbackReq, request: Request):
    part_dir(name)
    try:
        email, token = accounts.need_token(request)
    except HTTPException as e:
        return StreamingResponse(iter([json.dumps(dict(type="error", text=e.detail)) + "\n"]), media_type="application/x-ndjson")
    sess_file = PARTS / name / "session.json"
    session_id = json.loads(sess_file.read_text()).get("session_id") if sess_file.exists() else None
    _, P = effective_params(name)
    before = {v["version"] for v in versions(name)}
    latest = max(before) if before else 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shots = []
    if req.shot:
        shots.append(save_data_url(name, req.shot, f"{stamp}_view"))
    for i, a in enumerate(req.attachments[:6], 1):
        shots.append(save_data_url(name, a, f"{stamp}_photo{i}"))
    prompt = compose_prompt(name, req, P, latest, shots)
    log_chat(name, dict(role="user", text=req.text, pins=[p.model_dump() for p in req.pins], shots=shots, scope=req.scope,
                        version=req.version or latest, user=email, ts=time.strftime("%Y-%m-%dT%H:%M:%S")))

    return StreamingResponse(run_claude(name, prompt, session_id, before, latest, token), media_type="application/x-ndjson")


def run_claude(name, prompt, session_id, before, latest, token):
    sess_file = PARTS / name / "session.json"

    async def gen():
        async with BUILD_LOCK:
            cmd = [CLAUDE, "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS,
                   "--model", "opus", "--output-format", "stream-json", "--verbose"]
            if session_id:
                cmd += ["--resume", session_id]
            cmd += ["-p", prompt]
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=8 * 1024 * 1024, start_new_session=True,
                env={**os.environ, **({"CLAUDE_CODE_OAUTH_TOKEN": token} if token else {})})   # the asker's own account (studio/accounts.py)
            yield json.dumps(dict(type="status", text="Claude is looking…")) + "\n"
            final, new_sid, last = None, session_id, time.time()
            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                except asyncio.TimeoutError:
                    if time.time() - last > IDLE_TIMEOUT:
                        os.killpg(proc.pid, signal.SIGKILL)
                        yield json.dumps(dict(type="error", text="Claude went quiet for too long; stopped.")) + "\n"
                        break
                    yield json.dumps(dict(type="ping")) + "\n"
                    continue
                if not line:
                    break
                last = time.time()
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") == "system" and evt.get("subtype") == "init":
                    new_sid = evt.get("session_id") or new_sid
                elif evt.get("type") == "result":
                    final = (evt.get("result") or "").strip()
                    new_sid = evt.get("session_id") or new_sid
                    if evt.get("is_error"):
                        yield json.dumps(dict(type="error", text=final or "Claude hit an error.")) + "\n"
                        final = None
                else:
                    s = status_line(evt)
                    if s:
                        yield json.dumps(dict(type="status", text=s)) + "\n"
            await proc.wait()
            if proc.returncode not in (0, None) and final is None:
                err = (await proc.stderr.read()).decode(errors="replace")[-1500:]
                yield json.dumps(dict(type="error", text=f"claude exited {proc.returncode}: {err}")) + "\n"
            if new_sid:
                sess_file.write_text(json.dumps(dict(session_id=new_sid)))
            after = versions(name)
            new = [v for v in after if v["version"] not in before]
            if final is not None:
                log_chat(name, dict(role="assistant", text=final, version=(new[-1]["version"] if new else latest),
                                    ts=time.strftime("%Y-%m-%dT%H:%M:%S")))
                yield json.dumps(dict(type="final", text=final, new_versions=new)) + "\n"
    return gen()


STUB_MODEL = (chr(34) * 3) + """{title}
{brief}
""" + (chr(34) * 3) + """
from build123d import *

P = dict(length=40.0, width=40.0, height=20.0)
RANGES = dict(length=(5, 300, 1), width=(5, 300, 1), height=(2, 200, 1))

def build(P):
    # placeholder until Claude writes the real model from the brief
    return Box(P["length"], P["width"], P["height"])
"""


class NewPartReq(BaseModel):
    name: str
    brief: str
    attachments: list[str] = []


@app.post("/api/parts/new")
async def new_part(req: NewPartReq, request: Request):
    """Start a part from a plain-language brief: stub it so it's a valid part, then hand the brief to Claude."""
    email, token = accounts.need_token(request)
    new = req.name.strip().lower().replace(" ", "_").replace("-", "_")
    if not SAFE.match(new):
        raise HTTPException(400, "Name must be letters, digits and underscores, starting with a letter.")
    if (PARTS / new).exists():
        raise HTTPException(409, f"A part called {new!r} already exists.")
    if not req.brief.strip():
        raise HTTPException(400, "Say what it is — one or two sentences is enough.")
    d = PARTS / new
    d.mkdir()
    (d / "__init__.py").touch()
    (d / "versions").mkdir()
    (d / "model.py").write_text(STUB_MODEL.format(title=new.replace("_", " "), brief=req.brief.strip().replace(chr(34) * 3, chr(39) * 3)))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shots = [save_data_url(new, a, f"{stamp}_photo{i}") for i, a in enumerate(req.attachments[:6], 1)]
    log_chat(new, dict(role="user", text=req.brief, pins=[], shots=shots, version=None, user=email, ts=time.strftime("%Y-%m-%dT%H:%M:%S")))
    prompt = "\n".join([
        f'[LabCAD Studio — NEW part "{new}". The user\'s brief:]', "", req.brief.strip(), "",
        *(["Photos the user attached (Read each one first):"] + [f"  parts/{new}/shots/{fn}" for fn in shots] + [""] if shots else []),
        "Target printer for this part (design to it — bed size, hole shrink, clearances, min wall):",
        pr.describe(part=new), "",
        f"parts/{new}/model.py is a placeholder box. Replace it with the real parametric model: `P` with every dimension",
        "that matters, `RANGES` for the sliders, `build(P)` in build123d algebra mode, origin at the part centre, Z up, mm,",
        "designed to print flat without supports. Use `labware` for any standard item it holds and say which numbers are",
        "recalled/estimated. Bake in the usability details that make a part pleasant to use (lead-in chamfers, top/bottom bevels, corner fillets,",
        "finger access, engraved labels where they help).",
        "If it should print as more than one piece, make it an ASSEMBLY (see 'Assemblies' in CLAUDE.md): build() returns",
        "{name: Comp(part, at=...)} with each piece built in its print orientation, plus COMPONENTS labels. Never use a",
        "`show` knob to switch between pieces. Always write KNOBS with a plain-English label + one-line help for every knob.",
        f'Then build it: .venv/bin/python build.py {new} -m "v1 — <one line>"  — look at the PNG, fix anything ugly, rebuild.',
        "Check the envelope against that bed before replying; if it doesn't fit, say so and offer the split or the smaller pitch.",
        "Reply in ≤5 sentences: what you built, the key dimensions, and the one or two assumptions the user should check.",
        "If the brief is missing something you truly can't guess (a critical dimension, which of two very different things),",
        "ask that one question instead and still build your best guess so there's something to look at.",
    ])
    return StreamingResponse(run_claude(new, prompt, None, set(), 0, token), media_type="application/x-ndjson")


@app.post("/api/parts/{name}/reset-session")
def reset_session(name):
    f = part_dir(name) / "session.json"
    if f.exists():
        f.unlink()
    return dict(ok=True)


app.mount("/", StaticFiles(directory=ROOT / "studio" / "static", html=True), name="static")
