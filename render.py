"""Render a part to a shaded PNG (iso / top / front / end) via headless EGL, plus an iso _thumb.png.
usage: .venv/bin/python render.py part.stl [out.png]
       .venv/bin/python render.py --version parts/x/versions/v011.json [out.png]   (each component in its colour)
"""
import json, os, sys; os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
from pathlib import Path
import numpy as np, trimesh, pyrender
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

DEFAULT_RGB = (0.58, 0.72, 0.88)

def look_at(eye, target, up=(0, 0, 1)):
    eye, target, up = map(np.asarray, (eye, target, up)); f = target - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s); u = np.cross(s, f)
    M = np.eye(4); M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = s, u, -f, eye; return M

def hex_rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

def shot(meshes, direction, size=(1400, 1000)):
    """meshes: [(trimesh, rgb)] already in assembly position."""
    lo = np.min([m.bounds[0] for m, _ in meshes], axis=0); hi = np.max([m.bounds[1] for m, _ in meshes], axis=0)
    c = (lo + hi) / 2; r = np.linalg.norm(hi - lo) / 2
    d = np.asarray(direction, float); d /= np.linalg.norm(d)
    sc = pyrender.Scene(bg_color=[1, 1, 1, 1], ambient_light=[0.35]*3)
    for m, rgb in meshes:
        mat = pyrender.MetallicRoughnessMaterial(baseColorFactor=[*rgb, 1], metallicFactor=0.05, roughnessFactor=0.6)
        sc.add(pyrender.Mesh.from_trimesh(m, material=mat, smooth=False))
    cam = pyrender.OrthographicCamera(xmag=r*1.05, ymag=r*1.05*size[1]/size[0], znear=0.1, zfar=r*10)
    up = (0, 1, 0) if abs(d[2]) > 0.99 else (0, 0, 1)
    sc.add(cam, pose=look_at(c + d*r*4, c, up))
    for ld in ([0.4, -0.7, 0.9], [-0.8, 0.3, 0.5], [0.2, 0.9, -0.2]):
        sc.add(pyrender.DirectionalLight(intensity=2.2), pose=look_at(c + np.asarray(ld)*r*4, c, up))
    ren = pyrender.OffscreenRenderer(*size); rgb, _ = ren.render(sc); ren.delete(); return rgb

def load_version(vjson):
    """Each component's print-orientation STL, moved into the assembly by its matrix, in its colour."""
    info = json.loads(Path(vjson).read_text()); vdir = Path(vjson).parent; tag = info["tag"]
    if not info.get("components"):
        return [(trimesh.load(vdir / f"{tag}.stl", force="mesh"), DEFAULT_RGB)], info
    out = []
    for c in info["components"]:
        m = trimesh.load(vdir / tag / f"{c['name']}.stl", force="mesh")
        m.apply_transform(np.asarray(c["matrix"], float).reshape(4, 4))
        rgb = hex_rgb(c["color"]) if len(info["components"]) > 1 else DEFAULT_RGB
        out.append((m, rgb))
    return out, info

VIEWS = {"iso": (-1, -1.2, 0.9), "top": (0, 0, 1), "front": (0, -1, 0.05), "end": (1, 0, 0.05)}
def main(meshes, title, out):
    fig, axs = plt.subplots(2, 2, figsize=(14, 10), dpi=110)
    for ax, (name, dirn) in zip(axs.flat, VIEWS.items()):
        ax.imshow(shot(meshes, dirn)); ax.set_axis_off(); ax.set_title(name, fontsize=11)
    lo = np.min([m.bounds[0] for m, _ in meshes], axis=0); hi = np.max([m.bounds[1] for m, _ in meshes], axis=0)
    e = hi - lo; vol = sum(m.volume for m, _ in meshes)
    fig.suptitle(f"{title}   {e[0]:.1f} × {e[1]:.1f} × {e[2]:.1f} mm   {vol/1000:.0f} cm³  (~{vol/1000*1.24:.0f} g PLA @100%)", fontsize=12)
    fig.tight_layout(); fig.savefig(out); print("wrote", out)
    import PIL.Image as I                                    # single iso view for cards/thumbnails
    I.fromarray(shot(meshes, VIEWS["iso"], size=(960, 720))).save(str(out).rsplit(".", 1)[0] + "_thumb.png")

if __name__ == "__main__":
    if sys.argv[1] == "--version":
        meshes, info = load_version(sys.argv[2])
        n = len(info.get("components") or [])
        title = f"{info['part']} {info['tag']}" + (f" · {n} components" if n > 1 else "")
        out = sys.argv[3] if len(sys.argv) > 3 else sys.argv[2].rsplit(".", 1)[0] + ".png"
    else:
        stl = sys.argv[1]; meshes = [(trimesh.load(stl, force="mesh"), DEFAULT_RGB)]; title = stl
        out = sys.argv[2] if len(sys.argv) > 2 else stl.rsplit(".", 1)[0] + ".png"
    main(meshes, title, out)
