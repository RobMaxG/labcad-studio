"""Render an STL to a shaded PNG (iso / top / front / end) via headless EGL.
usage: .venv/bin/python render.py part.stl [out.png]
"""
import os, sys; os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
import numpy as np, trimesh, pyrender
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

def look_at(eye, target, up=(0, 0, 1)):
    eye, target, up = map(np.asarray, (eye, target, up)); f = target - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s); u = np.cross(s, f)
    M = np.eye(4); M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = s, u, -f, eye; return M

def shot(mesh, direction, size=(1400, 1000)):
    lo, hi = mesh.bounds; c = (lo + hi) / 2; r = np.linalg.norm(hi - lo) / 2
    d = np.asarray(direction, float); d /= np.linalg.norm(d)
    sc = pyrender.Scene(bg_color=[1, 1, 1, 1], ambient_light=[0.35]*3)
    mat = pyrender.MetallicRoughnessMaterial(baseColorFactor=[0.58, 0.72, 0.88, 1], metallicFactor=0.05, roughnessFactor=0.6)
    sc.add(pyrender.Mesh.from_trimesh(mesh, material=mat, smooth=False))
    cam = pyrender.OrthographicCamera(xmag=r*1.05, ymag=r*1.05*size[1]/size[0], znear=0.1, zfar=r*10)
    up = (0, 1, 0) if abs(d[2]) > 0.99 else (0, 0, 1)
    sc.add(cam, pose=look_at(c + d*r*4, c, up))
    for ld in ([0.4, -0.7, 0.9], [-0.8, 0.3, 0.5], [0.2, 0.9, -0.2]):
        sc.add(pyrender.DirectionalLight(intensity=2.2), pose=look_at(c + np.asarray(ld)*r*4, c, up))
    ren = pyrender.OffscreenRenderer(*size); rgb, _ = ren.render(sc); ren.delete(); return rgb

VIEWS = {"iso": (-1, -1.2, 0.9), "top": (0, 0, 1), "front": (0, -1, 0.05), "end": (1, 0, 0.05)}
def main(stl, out):
    m = trimesh.load(stl, force="mesh")
    fig, axs = plt.subplots(2, 2, figsize=(14, 10), dpi=110)
    for ax, (name, dirn) in zip(axs.flat, VIEWS.items()):
        ax.imshow(shot(m, dirn)); ax.set_axis_off(); ax.set_title(name, fontsize=11)
    e = m.bounds[1] - m.bounds[0]
    fig.suptitle(f"{stl}   {e[0]:.1f} × {e[1]:.1f} × {e[2]:.1f} mm   {m.volume/1000:.0f} cm³  (~{m.volume/1000*1.24:.0f} g PLA @100%)", fontsize=12)
    fig.tight_layout(); fig.savefig(out); print("wrote", out)
    # single iso view for cards/thumbnails
    import PIL.Image as I
    I.fromarray(shot(m, VIEWS["iso"], size=(960, 720))).save(out.rsplit(".", 1)[0] + "_thumb.png")

if __name__ == "__main__":
    stl = sys.argv[1]; out = sys.argv[2] if len(sys.argv) > 2 else stl.rsplit(".", 1)[0] + ".png"
    main(stl, out)
