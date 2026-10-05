// LabCAD Studio — the viewer, knobs, print list and Claude chat for one part (or assembly) at a time.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { drawTimeline, drawTimelineVertical, TIMELINE_CSS, TIMELINE_V_CSS } from './timeline.js';
document.head.insertAdjacentHTML('beforeend', `<style>${TIMELINE_CSS}${TIMELINE_V_CSS}</style>`);

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const tagOf = n => `v${String(n).padStart(3, '0')}`;
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const state = {
  part: null, spec: null, version: null, tool: null, pins: [], measures: [], mpts: [], ghostOn: false, wire: false, busy: false,
  knobs: {}, preview: null, previewChanged: null, explode: 0, solo: null, hidden: new Set(), hover: null, pulse: null,
};

// ---------- scene ----------
const stage = $('#stage');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, stencil: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.localClippingEnabled = true; stage.prepend(renderer.domElement);
const labelR = new CSS2DRenderer({ element: $('#labels') });
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 1, 5000); camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.dampingFactor = 0.12;
scene.add(new THREE.HemisphereLight(0xd8e4f2, 0x2a2622, 0.9));
const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(-120, -180, 260); scene.add(key);
const fill = new THREE.DirectionalLight(0xbfd0e6, 0.6); fill.position.set(200, 80, 100); scene.add(fill);
const rim = new THREE.DirectionalLight(0xffb070, 0.35); rim.position.set(60, 220, -40); scene.add(rim);
let grid = null;
const clip = new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e6);
// capped section cut: stencil trick from three's clipping_stencil example — back faces ++, front faces --, cap drawn where stencil != 0
const capMat = new THREE.MeshStandardMaterial({ color: 0x7d9cc2, roughness: 0.7, metalness: 0.02, stencilWrite: true, stencilRef: 0, stencilFunc: THREE.NotEqualStencilFunc, stencilFail: THREE.ReplaceStencilOp, stencilZFail: THREE.ReplaceStencilOp, stencilZPass: THREE.ReplaceStencilOp });
const cap = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), capMat); cap.renderOrder = 1.1; cap.visible = false; cap.onAfterRender = r => r.clearStencil(); scene.add(cap);
function makeStencilGroup(geometry) {
  const g = new THREE.Group();
  for (const [side, op] of [[THREE.BackSide, THREE.IncrementWrapStencilOp], [THREE.FrontSide, THREE.DecrementWrapStencilOp]]) {
    const m = new THREE.MeshBasicMaterial({ depthWrite: false, depthTest: false, colorWrite: false, stencilWrite: true, stencilFunc: THREE.AlwaysStencilFunc, side, clippingPlanes: [clip], stencilFail: op, stencilZFail: op, stencilZPass: op });
    const mesh = new THREE.Mesh(geometry, m); mesh.renderOrder = 1; g.add(mesh);
  }
  return g;
}
function updateCap() {
  if (!cap.visible) return;
  clip.coplanarPoint(cap.position); cap.lookAt(cap.position.x - clip.normal.x, cap.position.y - clip.normal.y, cap.position.z - clip.normal.z);
}
const ghostMat = new THREE.MeshStandardMaterial({ color: 0xff9f43, transparent: true, opacity: 0.22, depthWrite: false, flatShading: true, side: THREE.DoubleSide });
const edgeMat = new THREE.LineBasicMaterial({ color: 0x1d2025, transparent: true, opacity: 0.55 });
const model = new THREE.Group(); scene.add(model);           // one mesh per component
const ghostGroup = new THREE.Group(); scene.add(ghostGroup);
const pinGroup = new THREE.Group(); scene.add(pinGroup);
const measGroup = new THREE.Group(); scene.add(measGroup);

function resize() { const w = stage.clientWidth, h = stage.clientHeight; renderer.setSize(w, h); labelR.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
new ResizeObserver(resize).observe(stage); resize();
function tint() {                                               // hover + "this changed" glow, recomputed every frame
  let pa = 0, names = null;
  if (state.pulse) {
    const t = (performance.now() - state.pulse.t0) / 1700;
    pa = REDUCED ? (t < 1 ? 0.3 : 0) : Math.sin(Math.min(t, 1) * Math.PI) * 0.45; names = state.pulse.names;
    if (t >= 1) state.pulse = null;
  }
  for (const m of model.children) {
    const n = m.userData.comp.name, e = m.material.emissive;
    if (names?.has(n) && pa > 0) e.setRGB(pa, pa * 0.5, pa * 0.12);
    else if (state.hover === n) e.setRGB(0.16, 0.16, 0.16);
    else e.setRGB(0, 0, 0);
  }
}
(function loop() { requestAnimationFrame(loop); controls.update(); tint(); updateCap(); renderer.render(scene, camera); labelR.render(scene, camera); })();

function fitView(box) {
  const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3()), d = s.length();
  camera.position.set(c.x - d * 0.9, c.y - d * 1.05, c.z + d * 0.8); controls.target.copy(c); camera.near = d / 100; camera.far = d * 20; camera.updateProjectionMatrix(); controls.update();
}
function makeGrid(box) {
  if (grid) scene.remove(grid);
  const s = box.getSize(new THREE.Vector3()), span = Math.ceil(Math.max(s.x, s.y) * 1.6 / 50) * 50;
  grid = new THREE.GridHelper(span, span / 10, 0x3c424b, 0x2a2e35); grid.rotation.x = Math.PI / 2;
  const c = box.getCenter(new THREE.Vector3()); grid.position.set(c.x, c.y, box.min.z - 0.05); scene.add(grid);
}

// ---------- components: what the viewer shows ----------
const loader = new STLLoader(), geoCache = new Map();
function loadGeo(url) {
  if (!geoCache.has(url)) geoCache.set(url, loader.loadAsync(url).then(g => { g.computeVertexNormals(); g.computeBoundingBox(); return g; }).catch(e => { geoCache.delete(url); throw e; }));
  return geoCache.get(url);
}
/** A version (or preview result) → component descriptors the viewer can load. Old versions are one mesh. */
function compsOf(v, part = state.part) {
  if (v?.components?.length) return v.components.map(c => ({ ...c, url: c.url || `/api/parts/${part}/versions/${v.tag}/c/${c.name}.stl` }));
  return [{ name: 'part', label: part.replace(/_/g, ' '), color: '#9fc0e8', qty: 1, matrix: null, legacy: true, url: `/api/parts/${part}/versions/${v.tag}/stl` }];
}
const isAssembly = () => model.children.length > 1;
function clearModel() { for (const m of [...model.children]) { m.material.dispose(); model.remove(m); } model.userData.box = null; renderLegend(); }
async function setComponents(descs, { fit = false } = {}) {
  const geos = await Promise.all(descs.map(d => loadGeo(d.url)));   // swap in one go — never half an assembly on screen
  clearModel();
  descs.forEach((d, i) => {
    const color = new THREE.Color(descs.length > 1 ? d.color : 0x9fc0e8);
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.04, flatShading: true, side: THREE.DoubleSide, clippingPlanes: [clip] });
    const m = new THREE.Mesh(geos[i], mat); m.renderOrder = 2; m.matrixAutoUpdate = false;
    const base = new THREE.Matrix4(); if (d.matrix) base.set(...d.matrix);
    const st = makeStencilGroup(geos[i]); st.visible = false; m.add(st);
    m.userData = { comp: d, base, dir: new THREE.Vector3(), stencil: st, edges: null };
    model.add(m);
  });
  if (state.solo && !descs.some(d => d.name === state.solo)) state.solo = null;
  const box = new THREE.Box3();
  for (const m of model.children) box.union(m.geometry.boundingBox.clone().applyMatrix4(m.userData.base));
  model.userData.box = box; makeGrid(box); computeExplodeDirs(box); applyLayout();
  const dd = box.getSize(new THREE.Vector3()).length() * 1.5; cap.geometry.dispose(); cap.geometry = new THREE.PlaneGeometry(dd, dd);
  if (state.wire) showEdges();
  if (fit) {
    if (state.pose?.position) { camera.position.fromArray(state.pose.position); controls.target.fromArray(state.pose.target); const d = box.getSize(new THREE.Vector3()).length(); camera.near = d / 100; camera.far = d * 20; camera.updateProjectionMatrix(); controls.update(); }
    else fitView(box);
  }
  setClipRange(); renderLegend();
}
function computeExplodeDirs(box) {
  const ms = model.children; if (ms.length < 2) return;
  const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3()), big = Math.max(size.x, size.y, size.z);
  const thin = ['x', 'y', 'z'].reduce((a, b) => size[a] <= size[b] ? a : b);
  const centers = ms.map(m => m.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(m.userData.base));
  const vols = ms.map(m => { const s = m.geometry.boundingBox.getSize(new THREE.Vector3()); return s.x * s.y * s.z; });
  const anchor = vols.indexOf(Math.max(...vols));                        // the biggest piece stays put
  if (size[thin] < 0.35 * big) {                                         // flat assembly: lift pieces apart along the thin axis
    const order = ms.map((_, i) => i).sort((a, b) => centers[a][thin] - centers[b][thin]);
    const rank = []; order.forEach((idx, r) => rank[idx] = r);
    ms.forEach((m, i) => { m.userData.dir.set(0, 0, 0); m.userData.dir[thin] = (rank[i] - rank[anchor]) * big * 0.3; });
  } else {
    ms.forEach((m, i) => {
      const d = centers[i].clone().sub(c);
      if (i === anchor) d.set(0, 0, 0); else if (d.length() < big * 0.05) d.set(0, 0, 1);
      m.userData.dir.copy(d.lengthSq() ? d.normalize().multiplyScalar(big * 0.45) : d);
    });
  }
}
function applyLayout() {
  const k = state.explode, t = new THREE.Matrix4();
  for (const m of model.children) {
    m.matrix.copy(m.userData.base);
    if (k) m.matrix.premultiply(t.makeTranslation(m.userData.dir.x * k, m.userData.dir.y * k, m.userData.dir.z * k));
    m.matrixWorldNeedsUpdate = true;
    const n = m.userData.comp.name;
    m.visible = state.solo ? state.solo === n : !state.hidden.has(n);
  }
}
function renderLegend() {
  const el = $('#legend'), ms = model.children;
  if (ms.length < 2) { el.hidden = true; return; }
  el.hidden = false;
  const changed = state.previewChanged || new Set();
  el.innerHTML = `<div class="lg-h">Parts <span>${ms.length}</span></div>` + ms.map(m => {
    const c = m.userData.comp, off = state.solo ? state.solo !== c.name : state.hidden.has(c.name);
    return `<div class="lg-row ${off ? 'off' : ''} ${state.solo === c.name ? 'solo' : ''}" data-c="${esc(c.name)}">
      <button class="sw" style="--c:${esc(c.color)}" title="${off ? 'Show' : 'Hide'} ${esc(c.label)}" aria-pressed="${!off}"></button>
      <button class="nm" title="${state.solo === c.name ? 'Show everything again' : 'Show only this, and talk about it'}">${esc(c.label)}${c.qty > 1 ? ` <span>×${c.qty}</span>` : ''}</button>
      ${changed.has(c.name) ? '<span class="chg" title="This piece changes shape in the preview">changed</span>' : ''}</div>`;
  }).join('') + `<label class="lg-x"><span>Explode</span><input type="range" id="explode" min="0" max="1" step="0.01" value="${state.explode}" aria-label="Explode the assembly"></label>`;
  el.querySelectorAll('.lg-row').forEach(row => {
    const n = row.dataset.c;
    row.onmouseenter = () => state.hover = n; row.onmouseleave = () => state.hover = null;
    row.querySelector('.sw').onclick = () => { if (state.solo) state.solo = null; state.hidden.has(n) ? state.hidden.delete(n) : state.hidden.add(n); applyLayout(); renderLegend(); };
    row.querySelector('.nm').onclick = () => { state.solo = state.solo === n ? null : n; applyLayout(); renderLegend(); setScope(state.solo || ''); };
  });
  $('#explode').oninput = e => { state.explode = Number(e.target.value); applyLayout(); };
}
async function loadVersionView(v, fit) { await setComponents(compsOf(v), { fit }); await loadGhost(); }
async function loadGhost() {
  ghostGroup.clear();
  let src = null;
  try { src = await ghostSource(); } catch { src = null; }
  if (src) {
    const geos = await Promise.all(src.map(d => loadGeo(d.url)));
    src.forEach((d, i) => { const m = new THREE.Mesh(geos[i], ghostMat); m.matrixAutoUpdate = false; if (d.matrix) m.matrix.set(...d.matrix); ghostGroup.add(m); });
  }
  ghostGroup.visible = state.ghostOn;
}
async function ghostSource() {
  const sel = $('#ghost-sel').value || 'prev', vs = state.spec?.versions || [], cur = state.version, lin = state.spec?.lineage;
  if (sel === 'prev') {
    if (state.preview && cur) return compsOf(cur);                     // previewing: compare against what's saved
    const i = vs.findIndex(x => x.version === cur?.version); return i > 0 ? compsOf(vs[i - 1]) : null;
  }
  if (sel === 'parent' || sel === 'parent-at') {
    if (!lin) return null;
    const r = await fetch(`/api/parts/${lin.parent}/versions/${sel === 'parent' ? 'latest' : tagOf(lin.from_version)}/json`);
    return r.ok ? compsOf(await r.json(), lin.parent) : null;
  }
  const v = vs.find(x => x.tag === sel); return v ? compsOf(v) : null;
}
function renderGhostOptions() {
  const lin = state.spec?.lineage, vs = state.spec?.versions || [];
  $('#ghost-sel').innerHTML = `<option value="prev">previous version</option>` + (lin ? `<option value="parent">${lin.parent.replace(/_/g, ' ')} · latest</option><option value="parent-at">${lin.parent.replace(/_/g, ' ')} · ${tagOf(lin.from_version)} (fork point)</option>` : '') + vs.map(v => `<option value="${v.tag}">${v.tag} — ${esc(v.message).slice(0, 40)}</option>`).join('');
}
$('#ghost-sel').onchange = loadGhost;
function showEdges() { for (const m of model.children) { if (m.userData.edges) m.remove(m.userData.edges); const e = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 25), edgeMat); m.add(e); m.userData.edges = e; } }
function hideEdges() { for (const m of model.children) if (m.userData.edges) { m.remove(m.userData.edges); m.userData.edges.geometry.dispose(); m.userData.edges = null; } }

// ---------- section ----------
function setClipRange() {
  const box = model.userData.box; if (!box) return;
  const ax = $('#sec-axis').value, t = $('#sec-pos').value / 1000, on = $('#t-section').getAttribute('aria-pressed') === 'true', flip = state.secFlip, solid = $('#sec-solid').checked;
  const n = new THREE.Vector3(); n[ax] = flip ? 1 : -1;
  const lo = box.min[ax], hi = box.max[ax], pos = lo + (hi - lo) * t;
  clip.normal.copy(n); clip.constant = on ? (flip ? -pos : pos) : 1e6;
  $('#sec-val').textContent = on ? `${ax} = ${pos.toFixed(1)} mm` : 'off';
  $('#sec-flip').textContent = flip ? 'keep above' : 'keep below';
  cap.visible = on && solid;
  for (const m of model.children) { m.userData.stencil.visible = on && solid; m.material.side = on && solid ? THREE.FrontSide : THREE.DoubleSide; m.material.needsUpdate = true; }
}
$('#sec-axis').oninput = $('#sec-pos').oninput = $('#sec-solid').onchange = setClipRange;
$('#sec-flip').onclick = () => { state.secFlip = !state.secFlip; setClipRange(); };

// ---------- tools ----------
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
function hint(t, ms) { $('#hint').textContent = t || ''; $('#hint').classList.toggle('on', !!t); if (ms) setTimeout(() => { if ($('#hint').textContent === t) hint(''); }, ms); }
function setTool(t) {
  state.tool = state.tool === t ? null : t; state.mpts = [];
  for (const k of ['pin', 'measure']) $(`#t-${k}`).setAttribute('aria-pressed', String(state.tool === k));
  renderer.domElement.style.cursor = state.tool ? 'crosshair' : '';
  hint(state.tool === 'pin' ? 'Click the surface to drop a pin' : state.tool === 'measure' ? 'Click two points' : '');
}
$('#t-pin').onclick = () => setTool('pin'); $('#t-measure').onclick = () => setTool('measure');
$('#t-home').onclick = () => { if (!model.userData.box) return; state.pose = null; fitView(model.userData.box); };
$('#t-clear').onclick = () => { clearPins(); clearMeasures(); };
$('#t-section').onclick = e => { const on = e.currentTarget.getAttribute('aria-pressed') !== 'true'; e.currentTarget.setAttribute('aria-pressed', String(on)); $('#section').classList.toggle('on', on); setClipRange(); };
$('#t-ghost').onclick = e => { state.ghostOn = !state.ghostOn; e.currentTarget.setAttribute('aria-pressed', String(state.ghostOn)); $('#ghostsrc').classList.toggle('on', state.ghostOn); ghostGroup.visible = state.ghostOn; if (state.ghostOn && !ghostGroup.children.length) hint('Nothing to ghost yet — pick a source', 2500); };

// ---------- blueprint ----------
state.bpTheme = localStorage.getItem('labcad.bpTheme') || 'blueprint';
async function openBlueprint(comp) {
  if (!state.version) return;
  const comps = state.version.components || [];
  $('#bp-comp').hidden = comps.length < 2;
  if (comps.length > 1) {
    const keep = comp !== undefined ? comp : $('#bp-comp').value;
    $('#bp-comp').innerHTML = `<option value="">Whole assembly</option>` + comps.map(c => `<option value="${esc(c.name)}">${esc(c.label)}</option>`).join('');
    $('#bp-comp').value = comps.some(c => c.name === keep) ? keep : '';
  }
  const c = comps.length > 1 ? $('#bp-comp').value : '';
  const bp = $('#blueprint'); bp.hidden = false; $('#t-blue').setAttribute('aria-pressed', 'true');
  const lab = c ? comps.find(x => x.name === c)?.label : '';
  $('#bp-title').textContent = `${state.part.replace(/_/g, ' ')}${lab ? ' · ' + lab : ''} · ${state.version.tag}`;
  $('#bp-sheet').innerHTML = '<div id="bp-wait">Drafting…</div>';
  const url = `/api/parts/${state.part}/versions/${state.version.tag}/drawing${c ? `?c=${encodeURIComponent(c)}` : ''}`;
  $('#bp-dl').href = url; $('#bp-dl').download = `${state.part}_${state.version.tag}${c ? '_' + c : ''}_drawing.svg`;
  const r = await fetch(url);
  if (!r.ok) { let m = r.status; try { m = (await r.json()).error || m; } catch { } $('#bp-sheet').innerHTML = `<div id="bp-wait" class="err">Couldn't draft this one: ${esc(m)}</div>`; return; }
  $('#bp-sheet').innerHTML = await r.text(); applyBpTheme();
}
function applyBpTheme() { const svg = $('#bp-sheet svg'); if (svg) svg.setAttribute('class', `sheet ${state.bpTheme}`); $('#bp-theme').textContent = state.bpTheme === 'blueprint' ? 'Paper' : 'Blueprint'; }
function closeBlueprint() { $('#blueprint').hidden = true; $('#t-blue').setAttribute('aria-pressed', 'false'); }
$('#t-blue').onclick = () => $('#blueprint').hidden ? openBlueprint() : closeBlueprint();
$('#bp-comp').onchange = () => openBlueprint();
$('#bp-close').onclick = closeBlueprint;
$('#bp-theme').onclick = () => { state.bpTheme = state.bpTheme === 'blueprint' ? 'paper' : 'blueprint'; localStorage.setItem('labcad.bpTheme', state.bpTheme); applyBpTheme(); };
$('#t-thumb').onclick = async () => {
  const img = snapshot(960); if (!img) return;
  const pose = { position: camera.position.toArray(), target: controls.target.toArray() };
  const r = await fetch(`/api/parts/${state.part}/thumbnail`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ image: img, pose }) });
  state.pose = pose; hint(r.ok ? 'Saved — this view is the thumbnail and the home view' : 'Could not save thumbnail', 2500);
};
$('#t-wire').onclick = e => { state.wire = !state.wire; e.currentTarget.setAttribute('aria-pressed', String(state.wire)); state.wire ? showEdges() : hideEdges(); };
document.addEventListener('keydown', e => {
  if (e.target.matches('input,textarea,select')) return;
  const k = e.key.toLowerCase();
  if (k === 'p') setTool('pin'); else if (k === 'm') setTool('measure'); else if (k === 'escape') { if (!$('#blueprint').hidden) closeBlueprint(); else if (state.tool) setTool(state.tool); else if (state.solo) { state.solo = null; applyLayout(); renderLegend(); setScope(''); } }
  else if (k === 'h') $('#t-home').click(); else if (k === 't') $('#t-thumb').click(); else if (k === 'b') $('#t-blue').click(); else if (k === 'g') $('#t-ghost').click(); else if (k === 's') $('#t-section').click(); else if (k === 'e') $('#t-wire').click();
  else if (k === 'x' && isAssembly()) { state.explode = state.explode > 0 ? 0 : 0.6; applyLayout(); renderLegend(); }
});
let down = null;
renderer.domElement.addEventListener('pointerdown', e => down = [e.clientX, e.clientY]);
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || !state.tool || !model.children.length) return;
  const r = renderer.domElement.getBoundingClientRect(); ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ptr, camera); const hit = ray.intersectObjects(model.children.filter(m => m.visible), false)[0]; if (!hit) return;
  if (state.tool === 'pin') addPin(hit.point, hit.object); else addMeasurePoint(hit.point);
});
function dropLabels(o) { o.traverse(x => { if (x.isCSS2DObject) x.element.remove(); }); }
function markerSize() { return model.userData.box ? model.userData.box.getSize(new THREE.Vector3()).length() * 0.007 : 1; }
function addPin(p, obj) {
  const n = state.pins.length + 1; const s = new THREE.Mesh(new THREE.SphereGeometry(markerSize(), 16, 12), new THREE.MeshBasicMaterial({ color: 0xff9f43 })); s.position.copy(p);
  const el = document.createElement('div'); el.className = 'pin-label'; el.textContent = n; s.add(new CSS2DObject(el)); pinGroup.add(s);
  const c = obj.userData.comp, asm = p.clone().sub(obj.userData.dir.clone().multiplyScalar(state.explode));   // record where it is in the assembled part
  state.pins.push({ n, x: asm.x, y: asm.y, z: asm.z, note: '', obj: s, component: isAssembly() ? c.name : null, clabel: c.label, ccolor: c.color });
  renderDraftPins(); setTool('pin'); setTool('pin');
  setTimeout(() => $(`#dp-${n}`)?.focus(), 0);
}
function clearPins() { for (const p of state.pins) { dropLabels(p.obj); pinGroup.remove(p.obj); } state.pins = []; renderDraftPins(); }
function renderDraftPins() {
  $('#draftpins').innerHTML = state.pins.map(p => `<div class="dp"><span class="n">${p.n}</span>${p.component ? `<span class="pc" style="--c:${esc(p.ccolor)}">${esc(p.clabel)}</span>` : ''}<input id="dp-${p.n}" placeholder="what about this spot?" value="${esc(p.note)}"><span class="xyz">${p.x.toFixed(0)}, ${p.y.toFixed(0)}, ${p.z.toFixed(0)}</span><button title="Remove pin" data-n="${p.n}">×</button></div>`).join('')
    + state.measures.map((m, i) => `<div class="dp"><span class="n" style="background:var(--panel);color:var(--marker);border:1px solid var(--marker)">↔</span><span style="flex:1">${m.label}</span><span class="xyz">${m.mm.toFixed(2)} mm</span><button title="Remove" data-m="${i}">×</button></div>`).join('');
  $('#draftpins').querySelectorAll('input').forEach(i => { i.oninput = () => { state.pins.find(p => `dp-${p.n}` === i.id).note = i.value; }; i.onkeydown = e => { if (e.key === 'Escape') { i.blur(); state.tool && setTool(state.tool); } if (e.key === 'Enter') i.blur(); }; });
  $('#draftpins').querySelectorAll('button[data-n]').forEach(b => b.onclick = () => { const p = state.pins.find(p => p.n == b.dataset.n); dropLabels(p.obj); pinGroup.remove(p.obj); state.pins = state.pins.filter(x => x !== p); state.pins.forEach((p, i) => { p.n = i + 1; p.obj.children[0].element.textContent = p.n; }); renderDraftPins(); });
  $('#draftpins').querySelectorAll('button[data-m]').forEach(b => b.onclick = () => { const m = state.measures[b.dataset.m]; dropLabels(m.obj); measGroup.remove(m.obj); state.measures.splice(b.dataset.m, 1); renderDraftPins(); });
}
function addMeasurePoint(p) {
  state.mpts.push(p.clone());
  const dot = new THREE.Mesh(new THREE.SphereGeometry(markerSize() * 0.6, 12, 8), new THREE.MeshBasicMaterial({ color: 0xff9f43 })); dot.position.copy(p); measGroup.add(dot);
  if (state.mpts.length < 2) { hint('Now the second point'); return; }
  const [a, b] = state.mpts; const mm = a.distanceTo(b);
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0xff9f43 }));
  const el = document.createElement('div'); el.className = 'dim-label'; el.textContent = `${mm.toFixed(2)} mm`; const lab = new CSS2DObject(el); lab.position.copy(a).lerp(b, 0.5);
  const g = new THREE.Group(); g.add(line, lab); measGroup.add(g);
  const d = new THREE.Vector3().subVectors(b, a); const ax = ['x', 'y', 'z'][[Math.abs(d.x), Math.abs(d.y), Math.abs(d.z)].indexOf(Math.max(Math.abs(d.x), Math.abs(d.y), Math.abs(d.z)))];
  state.measures.push({ label: `${ax}-ish, ${a.x.toFixed(0)},${a.y.toFixed(0)},${a.z.toFixed(0)} → ${b.x.toFixed(0)},${b.y.toFixed(0)},${b.z.toFixed(0)}`, mm, obj: g });
  state.mpts = []; hint('Click two points'); renderDraftPins();
}
function clearMeasures() { dropLabels(measGroup); measGroup.clear(); state.measures = []; state.mpts = []; renderDraftPins(); }

// ---------- data ----------
async function loadPartsList() {
  const parts = await (await fetch('/api/parts')).json();
  const cur = $('#parts').value;
  $('#parts').innerHTML = parts.map(p => `<option value="${p.name}">${p.lineage ? '↳ ' : ''}${p.name.replace(/_/g, ' ')}${(p.latest?.components?.length || 0) > 1 ? ` (${p.latest.components.length} parts)` : ''}</option>`).join('');
  if (cur) $('#parts').value = cur;
  return parts;
}
async function loadParts() {
  const parts = await loadPartsList();
  const want = new URLSearchParams(location.search).get('part') || localStorage.getItem('labcad.part') || parts[0]?.name;
  if (want && parts.some(p => p.name === want)) $('#parts').value = want;
  if (parts.length) await selectPart($('#parts').value); else $('#chat').innerHTML = '<div id="empty">No parts yet. Add parts/&lt;name&gt;/model.py and build it once.</div>';
}
$('#parts').onchange = () => selectPart($('#parts').value);
async function selectPart(name) {
  state.part = name; localStorage.setItem('labcad.part', name); history.replaceState(null, '', `?part=${name}`);
  clearPins(); clearMeasures(); state.version = null; state.preview = null; state.previewChanged = null;
  state.solo = null; state.hidden = new Set(); state.explode = 0; geoCache.clear(); hidePvBar(); setScope('');
  state.pose = await (await fetch(`/api/parts/${name}/pose`)).json();
  await refresh(true);
  $('#text').value = localStorage.getItem(`labcad.draft.${name}`) || '';
  const wantV = Number(new URLSearchParams(location.search).get('v')); if (wantV) { const v = state.spec.versions.find(x => x.version === wantV); if (v) await showVersion(v); }
}
async function refresh(showLatest) {
  state.spec = await (await fetch(`/api/parts/${state.part}`)).json();
  renderChat(); renderVersions(); renderKnobs(); renderGhostOptions(); renderLineage(); renderFamily(); renderPrinter();
  const vs = state.spec.versions;
  if (!vs.length) { clearModel(); renderPrint(); return; }
  if (showLatest || !state.version) await showVersion(vs[vs.length - 1]);
  else { state.version = vs.find(v => v.version === state.version.version) || vs.at(-1); renderPrint(); }
}
async function showVersion(v) {
  if (state.preview) { state.preview = null; state.previewChanged = null; hidePvBar(); renderKnobs(); }
  const vs = state.spec.versions, fit = !state.version || state.version.part !== v.part; state.version = v; if (!$('#blueprint').hidden) openBlueprint();
  await loadVersionView(v, fit);
  titleBlock(v, false);
  renderVersions(); renderScope(); renderPrint(); if ($('#pane-family').classList.contains('on')) renderFamily();
}
function titleBlock(v, isPreview) {
  const vs = state.spec.versions, n = (v.components || []).length;
  $('#tb-part').textContent = state.part.replace(/_/g, ' ');
  $('#tb-ver').innerHTML = isPreview ? `<span class="pv-tag">preview</span> of ${state.version.tag} — not saved` : `${v.tag}${v.version === vs.at(-1)?.version ? ' · latest' : ''} · ${vs.length} saved`;
  $('#tb-env').textContent = v.envelope.map(x => x.toFixed(1)).join(' × ') + ' mm' + (n > 1 ? ' assembled' : '');
  $('#tb-vol').textContent = `${v.volume_cm3} cm³ · ${v.mass_g_pla} g PLA solid${n > 1 ? ` · ${n} pieces` : ''}`;
  $('#tb-ts').textContent = isPreview ? '—' : v.ts.replace('T', ' ');
  $('#tb-msg').textContent = isPreview ? describeDiff(changedKnobs()) : (v.message || '—');
}
const compLabel = (v, n) => (v.components || []).find(c => c.name === n)?.label || n;
const compColor = (v, n) => (v.components || []).find(c => c.name === n)?.color || '#9fc0e8';
function changeChips(v) {
  if (!v.changes || (v.components || []).length < 2) return '';
  const moved = Object.entries(v.changes).filter(([, s]) => s !== 'same');
  if (!moved.length) return `<span class="chips"><i class="none">no piece changed shape</i></span>`;
  return `<span class="chips">${moved.map(([n, s]) => `<i style="--c:${esc(compColor(v, n))}">${esc(compLabel(v, n))} <b>${s}</b></i>`).join('')}</span>`;
}
function renderVersions() {
  const vs = [...state.spec.versions].reverse();
  $('#versions').innerHTML = vs.length ? vs.map(v => `<div class="ver ${state.version?.version === v.version ? 'on' : ''}" data-v="${v.version}">
    <span class="tag">${v.tag}</span><span>${v.mass_g_pla} g · ${v.envelope.map(n => n.toFixed(0)).join('×')}</span><span style="color:var(--ink-3);font-size:12px">${v.ts.slice(5, 16).replace('T', ' ')}</span>
    <span class="msg2">${esc(v.message) || '<i style="color:var(--ink-3)">no message</i>'}</span>${changeChips(v)}
    <span class="dl">${(v.components || []).length > 1 ? `<a href="/api/parts/${state.part}/versions/${v.tag}/zip">All prints (zip)</a>` : `<a href="/api/parts/${state.part}/versions/${v.tag}/stl">STL</a><a href="/api/parts/${state.part}/versions/${v.tag}/step">STEP</a>`}<a href="/api/parts/${state.part}/versions/${v.tag}/png" target="_blank">render</a></span>
    <span class="act">${v.version !== state.spec.versions.at(-1).version ? `<button data-restore="${v.tag}">Make this current</button><button data-forkv="${v.version}">Fork from here</button>` : ''}<button class="ren" data-relabel="${v.tag}">Relabel</button>${state.spec.versions.length > 1 ? `<button data-delv="${v.tag}" style="color:var(--ink-3)">Delete</button>` : ''}</span></div>`).join('') : '<div id="empty">No versions yet.</div>';
  $('#versions').querySelectorAll('.ver').forEach(el => el.onclick = e => { if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON') return; showVersion(state.spec.versions.find(v => v.version == el.dataset.v)); });
  $('#versions').querySelectorAll('button[data-restore]').forEach(b => b.onclick = async () => { b.textContent = 'Restoring…'; const r = await fetch(`/api/parts/${state.part}/restore/${b.dataset.restore}`, { method: 'POST' }); if (r.ok) await refresh(true); else b.textContent = 'Restore failed'; });
  $('#versions').querySelectorAll('button[data-forkv]').forEach(b => b.onclick = () => openFork(Number(b.dataset.forkv)));
  $('#versions').querySelectorAll('button[data-relabel]').forEach(b => b.onclick = async () => { const v = state.spec.versions.find(x => x.tag === b.dataset.relabel); const m = await ask(`Relabel ${v.tag}`, v.message); if (m == null || m === v.message) return; await fetch(`/api/parts/${state.part}/versions/${v.tag}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ message: m }) }); await refresh(false); if (state.version?.tag === v.tag) showVersion(state.spec.versions.find(x => x.tag === v.tag)); });
  $('#versions').querySelectorAll('button[data-delv]').forEach(b => b.onclick = async () => {
    if (!confirm(`Move ${b.dataset.delv} to the trash? Restore it from the Library if you change your mind.`)) return;
    const r = await fetch(`/api/parts/${state.part}/versions/${b.dataset.delv}`, { method: 'DELETE' });
    if (!r.ok) { hint((await r.json()).detail || 'Delete failed', 3000); return; }
    const res = await r.json(); if (state.version?.tag === b.dataset.delv) state.version = null;
    await refresh(!state.version);
    if (res.rolled_back_to) hint(`Knobs went back to ${res.rolled_back_to} — that was the newest version`, 3500);
  });
}
function renderChat() {
  const c = $('#chat'), v = state.spec.versions.at(-1) || {};
  c.innerHTML = state.spec.chat.length ? state.spec.chat.map(m => {
    const vv = m.version ? `<span class="v" data-v="${m.version}">${tagOf(m.version)}</span>` : '';
    if (m.role === 'build') return `<div class="msg build"><div class="body">${vv} ${m.params_changed && Object.keys(m.params_changed).length ? 'saved from knobs: ' + esc(m.text) : esc(m.text)}</div></div>`;
    const pins = m.pins?.length ? `<ul class="pins">${m.pins.map(p => `<li data-n="${p.n}">${p.component ? `<b style="color:${esc(compColor(v, p.component))}">${esc(compLabel(v, p.component))}</b> ` : ''}${esc(p.note) || '(no note)'} <span style="color:var(--ink-3)">${p.x.toFixed(0)},${p.y.toFixed(0)},${p.z.toFixed(0)}</span></li>`).join('')}</ul>` : '';
    const shots = m.shots?.length ? `<div class="shots">${m.shots.map(f => `<a href="/api/parts/${state.part}/shots/${f}" target="_blank"><img src="/api/parts/${state.part}/shots/${f}" alt=""></a>`).join('')}</div>` : '';
    const scope = m.role === 'user' && m.scope ? ` · about <b>${esc(compLabel(v, m.scope))}</b>` : (m.role === 'user' && 'scope' in m && (v.components || []).length > 1 ? ' · about the whole assembly' : '');
    return `<div class="msg ${m.role}"><div class="who"><b>${m.role === 'assistant' ? 'Claude' : 'You'}</b> ${m.ts.slice(5, 16).replace('T', ' ')} ${vv}${scope}</div><div class="body">${esc(m.text).replace(/\n/g, '<br>')}${pins}${shots}</div></div>`;
  }).join('') : '<div id="empty">Nothing said yet. Drop a pin, tell Claude what bugs you.</div>';
  c.querySelectorAll('.v').forEach(el => el.onclick = () => { const v = state.spec.versions.find(v => v.version == el.dataset.v); if (v) showVersion(v); });
  c.scrollTop = c.scrollHeight;
}

// ---------- knobs: labelled, grouped, previewed live; a version only when you save ----------
const knobMeta = k => state.spec.knobs.find(x => x.key === k);
const fmtVal = (k, v) => { const m = knobMeta(k); if (!m) return String(v); if (m.kind === 'toggle') return Number(v) ? 'on' : 'off'; if (m.kind === 'choice') return m.choices?.[String(v)] ?? String(v); return `${v}${m.unit ? ' ' + m.unit : ''}`; };
function changedKnobs() { return Object.fromEntries(Object.entries(state.knobs).filter(([k, v]) => v !== state.spec.params[k])); }
function designChanges() { return Object.fromEntries(Object.entries(changedKnobs()).filter(([k]) => !knobMeta(k)?.view)); }
function describeDiff(diff) { return Object.entries(diff).map(([k, v]) => `${knobMeta(k)?.label || k} ${fmtVal(k, state.spec.params[k])} → ${fmtVal(k, v)}`).join(', ') || '—'; }
function renderKnobs() { state.knobs = { ...state.spec.params }; drawKnobs(); }
function knobHTML(k) {
  const v = state.knobs[k.key], saved = state.spec.params[k.key], ch = v !== saved, id = `k-${k.key}`;
  const was = ch ? `was ${esc(fmtVal(k.key, saved))}` : '';
  const help = k.help ? `<div class="kh">${esc(k.help)}</div>` : '';
  const title = `${esc(k.key)}${k.help ? ' — ' + esc(k.help) : ''}`;
  if (k.kind === 'toggle') return `<div class="knob tog ${ch ? 'changed' : ''}" data-k="${k.key}" title="${title}"><div class="kl"><label for="${id}" class="kn">${esc(k.label)}</label><span class="was">${was}</span><button class="switch" id="${id}" role="switch" aria-checked="${Number(v) ? 'true' : 'false'}"></button></div>${help}</div>`;
  if (k.kind === 'choice') return `<div class="knob ${ch ? 'changed' : ''}" data-k="${k.key}" title="${title}"><div class="kl"><label for="${id}" class="kn">${esc(k.label)}</label><span class="was">${was}</span><select id="${id}">${Object.entries(k.choices).map(([a, b]) => `<option value="${esc(a)}" ${String(v) === a ? 'selected' : ''}>${esc(b)}</option>`).join('')}</select></div>${help}</div>`;
  if (k.kind === 'fixed' || !k.range) return `<div class="knob fixed" data-k="${k.key}" title="${title}"><div class="kl"><span class="kn">${esc(k.label)}</span><span class="kv">${esc(String(v))}</span></div>${help}</div>`;
  const [lo, hi, st] = k.range;
  return `<div class="knob ${ch ? 'changed' : ''}" data-k="${k.key}" title="${title}"><div class="kl"><label for="${id}" class="kn">${esc(k.label)}</label><span class="was">${was}</span><span class="kv"><input type="number" id="${id}-n" min="${lo}" max="${hi}" step="${st}" value="${v}" aria-label="${esc(k.label)}"><span class="u">${esc(k.unit)}</span></span></div><input type="range" id="${id}" min="${lo}" max="${hi}" step="${st}" value="${v}">${help}</div>`;
}
function drawKnobs() {
  const knobs = state.spec.knobs, adv = $('#knobadv').checked, q = $('#knobfilter').value.trim().toLowerCase();
  const ordered = [...knobs.filter(k => k.view), ...knobs.filter(k => !k.view)], groups = [], by = {};
  for (const k of ordered) { if (!by[k.group]) { by[k.group] = []; groups.push(k.group); } by[k.group].push(k); }
  const match = k => !q || [k.label, k.key, k.help, k.group].some(s => String(s || '').toLowerCase().includes(q));
  const show = k => (adv || !k.advanced || state.knobs[k.key] !== state.spec.params[k.key]) && match(k);
  const nAdv = knobs.filter(k => k.advanced).length, guessed = knobs.filter(k => !k.described).length;
  $('#knobadv-l').hidden = !nAdv; $('#knobadv-n').textContent = `fine-tuning (${nAdv})`;
  $('#knobs').innerHTML = (state.spec.doc && !q ? `<p class="kdoc">${esc(state.spec.doc.split('\n')[0])}</p>` : '') + groups.map(g => {
    const items = by[g].filter(show); if (!items.length) return '';
    const isView = by[g].every(k => k.view);
    return `<details class="kg" open><summary>${esc(g)}${isView ? '<span class="kg-v">moves it on screen · never saved</span>' : ''}</summary>${items.map(knobHTML).join('')}</details>`;
  }).join('') + (q && !knobs.some(k => show(k)) ? `<div id="empty">No knob matches “${esc(q)}”.</div>` : '')
    + (guessed > knobs.length / 2 && !q ? `<div class="kguess">Most of these names are guessed from the code. <button id="ask-labels">Ask Claude to label them</button></div>` : '');
  $('#knobs').querySelectorAll('.knob[data-k]').forEach(el => {
    const k = el.dataset.k, meta = knobMeta(k);
    const set = (v, delay) => {
      state.knobs[k] = meta.kind === 'choice' && isNaN(Number(v)) ? v : Number(v);
      const ch = state.knobs[k] !== state.spec.params[k];
      el.classList.toggle('changed', ch); el.querySelector('.was').textContent = ch ? `was ${fmtVal(k, state.spec.params[k])}` : '';
      knobState(); schedulePreview(delay);
    };
    const r = el.querySelector('input[type=range]'), n = el.querySelector('input[type=number]'), sw = el.querySelector('.switch'), sel = el.querySelector('select');
    if (r) { r.oninput = () => { n.value = r.value; set(r.value, 260); }; r.onchange = () => set(r.value, 0); n.onchange = () => { r.value = n.value; set(n.value, 0); }; }
    if (sw) sw.onclick = () => { const on = sw.getAttribute('aria-checked') !== 'true'; sw.setAttribute('aria-checked', String(on)); set(on ? 1 : 0, 0); };
    if (sel) sel.onchange = () => set(sel.value, 0);
  });
  $('#ask-labels')?.addEventListener('click', () => {
    $('#text').value = 'Please write KNOBS for this model: a plain-English label, a group and a one-line help for every knob (mark fiddly ones advanced). Labels only — no geometry change, so no rebuild needed.';
    setScope(''); document.querySelector('#tabs button[data-pane=talk]').click(); $('#text').focus();
  });
  knobState();
}
$('#knobfilter').oninput = drawKnobs; $('#knobadv').onchange = drawKnobs;
function knobState() {
  const all = changedKnobs(), design = designChanges(), n = Object.keys(design).length, nv = Object.keys(all).length - n;
  $('#knobstate').textContent = n ? `${n} change${n > 1 ? 's' : ''} previewing — save to keep ${n > 1 ? 'them' : 'it'}` : nv ? 'Only the view changed — nothing to save' : 'Drag a knob to preview it live. Nothing is saved until you say so.';
  $('#rebuild').disabled = !n || state.busy; $('#knobreset').disabled = !Object.keys(all).length;
}
$('#knobreset').onclick = () => discardPreview();
$('#rebuild').onclick = () => savePreview();

// ---------- preview ----------
let pvTimer = null, pvInFlight = false, pvAgain = false, pvSeq = 0;
function schedulePreview(delay) { clearTimeout(pvTimer); pvTimer = setTimeout(requestPreview, delay); }
async function requestPreview() {
  const diff = changedKnobs();
  if (!Object.keys(diff).length) { discardPreview(); return; }
  if (pvInFlight) { pvAgain = true; return; }
  pvInFlight = true; const seq = ++pvSeq, part = state.part;
  showPvBar('busy');
  let res = null, err = null;
  try {
    const r = await fetch(`/api/parts/${part}/preview`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ params: diff }) });
    res = await r.json(); if (!r.ok) err = res.error || `preview failed (${r.status})`;
  } catch (e) { err = 'Could not reach the Studio server.'; }
  pvInFlight = false;
  if (state.part !== part || seq !== pvSeq) return;
  if (err) showPvBar('error', err);
  else if (Object.keys(changedKnobs()).length) await showPreview(res);          // show it even if knobs moved again — it's progress
  if (pvAgain) { pvAgain = false; requestPreview(); }
}
async function showPreview(res) {
  const ref = state.version, refFp = Object.fromEntries((ref?.components || []).map(c => [c.name, c.fingerprint]));
  const changed = (ref?.components?.length ? res.components.filter(c => refFp[c.name] !== c.fingerprint) : (Object.keys(designChanges()).length ? res.components : [])).map(c => c.name);
  const first = !state.preview;
  state.preview = res; state.previewChanged = new Set(changed);
  await setComponents(res.components);
  if (changed.length) state.pulse = { names: new Set(changed), t0: performance.now() };
  titleBlock(res, true); showPvBar('ok'); showFit(res.components.map(c => ({ ...c.fit, label: c.label, name: c.name })), true);
  if (first && state.ghostOn) loadGhost();
}
function showPvBar(mode, err) {
  const bar = $('#pvbar'); bar.hidden = false; bar.dataset.mode = mode;
  const design = designChanges(), nd = Object.keys(design).length;
  if (mode === 'busy') { $('#pv-text').innerHTML = `<b>Building preview…</b>`; }
  else if (mode === 'error') { $('#pv-text').innerHTML = `<b class="err">This combination doesn't build.</b> <span class="pv-sub">${esc(String(err).split('\n').filter(Boolean).pop() || '')}</span>`; }
  else {
    const res = state.preview, ch = [...(state.previewChanged || [])];
    const labs = ch.map(n => res.components.find(c => c.name === n)?.label || n);
    const big = res.components.filter(c => c.fit?.status === 'too_big').map(c => c.label);
    const pieces = res.components.length > 1 ? (labs.length ? `reshapes ${labs.join(', ')}` : 'no piece changes shape') : '';
    $('#pv-text').innerHTML = `<b>Preview — not saved.</b> <span class="pv-sub">${esc(describeDiff(changedKnobs()))}${pieces ? ' · ' + esc(pieces) : ''}</span>`
      + (big.length ? ` <span class="pv-warn">${esc(big.join(', '))} no longer fit${big.length === 1 ? 's' : ''} the bed</span>` : '');
  }
  $('#pv-save').disabled = !nd || state.busy || mode !== 'ok';
  $('#pv-save').textContent = nd ? 'Save as version' : 'View only — nothing to save';
}
function hidePvBar() { $('#pvbar').hidden = true; }
async function discardPreview() {
  clearTimeout(pvTimer); pvSeq++;
  const had = !!state.preview; state.preview = null; state.previewChanged = null; hidePvBar();
  if (state.spec) renderKnobs();
  if (had && state.version) { await loadVersionView(state.version, false); titleBlock(state.version, false); renderPrinter(); }
}
async function savePreview() {
  const diff = designChanges(); if (!Object.keys(diff).length || state.busy) return;
  const msg = await ask('Name this version', describeDiff(diff)); if (msg == null) return;
  setBusy(true); showPvBar('busy'); $('#pv-text').innerHTML = '<b>Saving a new version…</b>';
  const r = await fetch(`/api/parts/${state.part}/build`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ params: diff, message: msg || describeDiff(diff) }) });
  setBusy(false);
  if (!r.ok) { showPvBar('error', (await r.json()).error || 'build failed'); return; }
  state.preview = null; state.previewChanged = null; hidePvBar();
  await refresh(true); hint('Saved — the Print tab shows which pieces changed', 3000);
}
$('#pv-discard').onclick = () => discardPreview();
$('#pv-save').onclick = () => savePreview();
function setBusy(b) { state.busy = b; $('#send').disabled = b; knobState(); $('#live').classList.toggle('busy', b); }

// ---------- print: every piece, its files, its fit, and whether your print is still current ----------
function unchangedSince(c) {
  const vs = state.spec.versions, i = vs.findIndex(x => x.version === state.version.version); let tag = state.version.tag;
  for (let j = i - 1; j >= 0; j--) { const pc = (vs[j].components || []).find(x => x.name === c.name); if (pc && pc.fingerprint === c.fingerprint) tag = vs[j].tag; else break; }
  return tag;
}
async function renderPrint() {
  const el = $('#print'), v = state.version;
  if (!v) { el.innerHTML = '<div id="empty">Nothing built yet.</div>'; return; }
  if (!v.components?.length) {
    el.innerHTML = `<div class="pr-legacy"><p>${v.tag} was built before LabCAD tracked separate pieces, so it has one file.</p><p><a class="btn" href="/api/parts/${state.part}/versions/${v.tag}/stl">STL</a> <a class="btn" href="/api/parts/${state.part}/versions/${v.tag}/step">STEP</a></p><p class="pr-sub">Save any knob change (or ask Claude for anything) and the next version gets per-piece print files.</p></div>`;
    return;
  }
  const fit = await (await fetch(`/api/parts/${state.part}/fit?version=${v.version}`)).json();
  if (state.version !== v) return;
  const fitBy = Object.fromEntries((fit.components || []).map(f => [f.name, f])), rec = state.spec.printed || {};
  const n = v.components.reduce((a, c) => a + (c.qty || 1), 0), multi = v.components.length > 1, base = `/api/parts/${state.part}/versions/${v.tag}`;
  const FL = { fits: 'fits', rotate: 'fits turned 90°', diagonal: 'fits diagonally', too_big: 'too big for the bed', unknown: '—' };
  el.innerHTML = `<div class="pr-head"><div><b>${v.tag}</b> · ${n} print${n > 1 ? 's' : ''} · ${v.mass_g_pla} g PLA solid<div class="pr-sub">on ${esc(state.spec.printer?.name || 'the default printer')}</div></div>
      <div class="pr-dl"><a class="btn primary" href="${base}/c/plate.3mf" title="Every piece in one file — your slicer opens them as separate objects">Plate (3MF)</a><a class="btn" href="${base}/zip">All files</a></div></div>`
    + (state.preview ? `<p class="pr-note">You're previewing unsaved knob changes. These are the files for ${v.tag}, the saved version.</p>` : '')
    + v.components.map(c => {
      const f = fitBy[c.name] || {}, p = rec[c.name], st = v.changes?.[c.name];
      const since = unchangedSince(c);
      const chg = st === 'changed' ? `<span class="pc-chg">changed in ${v.tag}</span>` : st === 'new' ? `<span class="pc-new">new in ${v.tag}</span>` : `<span class="pc-same">same since ${since}</span>`;
      let ps;
      if (!p) ps = `<button class="pbtn" data-printed="${esc(c.name)}">I printed this</button>`;
      else if (p.fingerprint === c.fingerprint) ps = `<span class="pr-ok">✓ your print from ${esc(p.tag)} is current</span><button class="plink" data-forget="${esc(c.name)}">forget</button>`;
      else ps = `<span class="pr-re">changed since your print (${esc(p.tag)}) — reprint</span><button class="pbtn" data-printed="${esc(c.name)}">I reprinted it</button>`;
      return `<div class="pcard" style="--c:${esc(c.color)}">
        <div class="pc-top">${multi ? '<span class="pc-sw"></span>' : ''}<b>${esc(multi ? c.label : state.part.replace(/_/g, ' '))}</b>${c.qty > 1 ? `<span class="pc-q">×${c.qty}</span>` : ''}${multi ? chg : ''}</div>
        <div class="pc-meta">${c.envelope.map(x => x.toFixed(1)).join(' × ')} mm as printed · ${c.mass_g_pla} g <span class="fit ${esc(f.status || 'unknown')}" title="${esc([f.how, f.over?.some(o => o > 0) ? 'over by ' + f.over.filter(o => o > 0).join(', ') + ' mm' : ''].filter(Boolean).join(' · '))}">${FL[f.status] || '—'}</span></div>
        ${c.filament ? `<div class="pc-fil">Filament: <b>${esc(c.filament)}</b></div>` : ''}
        ${c.note ? `<div class="pc-note">${esc(c.note)}</div>` : ''}
        <div class="pc-act"><a href="${base}/c/${encodeURIComponent(c.name)}.stl">STL</a><a href="${base}/c/${encodeURIComponent(c.name)}.step">STEP</a><button class="plink" data-bp="${esc(c.name)}">Blueprint</button>${multi ? `<button class="plink" data-solo="${esc(c.name)}">Show only this</button>` : ''}<span class="grow"></span>${ps}</div></div>`;
    }).join('');
  el.querySelectorAll('[data-printed]').forEach(b => b.onclick = async () => { await fetch(`/api/parts/${state.part}/printed`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ component: b.dataset.printed, version: v.version }) }); state.spec.printed = (await (await fetch(`/api/parts/${state.part}`)).json()).printed; renderPrint(); });
  el.querySelectorAll('[data-forget]').forEach(b => b.onclick = async () => { await fetch(`/api/parts/${state.part}/printed`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ component: b.dataset.forget, version: null }) }); state.spec.printed = (await (await fetch(`/api/parts/${state.part}`)).json()).printed; renderPrint(); });
  el.querySelectorAll('[data-bp]').forEach(b => b.onclick = () => openBlueprint(multi ? b.dataset.bp : ''));
  el.querySelectorAll('[data-solo]').forEach(b => b.onclick = () => { state.solo = b.dataset.solo; applyLayout(); renderLegend(); setScope(state.solo); });
}

// ---------- screenshots & attachments ----------
function snapshot(maxW = 1400) {
  if (!model.children.length) return null;
  controls.update(); updateCap(); renderer.render(scene, camera);           // fresh frame, same task, so the buffer is still there
  const src = renderer.domElement, k = Math.min(1, maxW / src.width);
  const c = document.createElement('canvas'); c.width = Math.round(src.width * k); c.height = Math.round(src.height * k);
  const ctx = c.getContext('2d'); ctx.fillStyle = '#1d2025'; ctx.fillRect(0, 0, c.width, c.height); ctx.drawImage(src, 0, 0, c.width, c.height);
  const dot = (p, txt, r) => { const v = p.clone().project(camera); if (v.z > 1) return; const x = (v.x + 1) / 2 * c.width, y = (1 - v.y) / 2 * c.height;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = '#ff9f43'; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = '#2a1a06'; ctx.stroke();
    ctx.fillStyle = '#2a1a06'; ctx.font = `bold ${Math.round(r * 1.2)}px sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(txt, x, y + 1); };
  for (const p of state.pins) dot(p.obj.position, String(p.n), 12 * k + 4);
  for (const m of state.measures) { const [l] = m.obj.children; const a = new THREE.Vector3().fromBufferAttribute(l.geometry.attributes.position, 0), b = new THREE.Vector3().fromBufferAttribute(l.geometry.attributes.position, 1);
    const va = a.clone().project(camera), vb = b.clone().project(camera); ctx.beginPath(); ctx.moveTo((va.x + 1) / 2 * c.width, (1 - va.y) / 2 * c.height); ctx.lineTo((vb.x + 1) / 2 * c.width, (1 - vb.y) / 2 * c.height); ctx.strokeStyle = '#ff9f43'; ctx.lineWidth = 2; ctx.stroke();
    dot(a.clone().lerp(b, 0.5), `${m.mm.toFixed(1)}`, 16 * k + 4); }
  return c.toDataURL('image/jpeg', 0.85);
}
state.attachments = [];
function addAttachment(file) {
  if (!file || !file.type.startsWith('image/')) return;
  const rd = new FileReader(); rd.onload = () => {
    const img = new Image(); img.onload = () => {                         // downscale big phone photos before upload
      const k = Math.min(1, 1600 / Math.max(img.width, img.height)); const c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); state.attachments.push(c.toDataURL('image/jpeg', 0.88)); renderAttachments(); };
    img.src = rd.result; };
  rd.readAsDataURL(file);
}
function renderAttachments() {
  $('#attach').innerHTML = state.attachments.map((a, i) => `<div class="a"><img src="${a}" alt=""><button data-i="${i}" title="Remove">×</button></div>`).join('');
  $('#attach').querySelectorAll('button').forEach(b => b.onclick = () => { state.attachments.splice(b.dataset.i, 1); renderAttachments(); });
}
$('#text').addEventListener('paste', e => { for (const it of e.clipboardData.items) if (it.type.startsWith('image/')) { addAttachment(it.getAsFile()); e.preventDefault(); } });
for (const ev of ['dragenter', 'dragover']) $('#compose').addEventListener(ev, e => { e.preventDefault(); $('#compose').classList.add('drop'); });
for (const ev of ['dragleave', 'drop']) $('#compose').addEventListener(ev, e => { e.preventDefault(); $('#compose').classList.remove('drop'); });
$('#compose').addEventListener('drop', e => { for (const f of e.dataTransfer.files) addAttachment(f); });

// ---------- send to Claude (scoped to the assembly or one piece) ----------
function renderScope() {
  const comps = state.version?.components || [];
  $('#scope').hidden = comps.length < 2; if (comps.length < 2) return;
  const cur = $('#scope-sel').value;
  $('#scope-sel').innerHTML = `<option value="">the whole assembly</option>` + comps.map(c => `<option value="${esc(c.name)}">${esc(c.label)}</option>`).join('');
  $('#scope-sel').value = comps.some(c => c.name === cur) ? cur : '';
}
function setScope(name) { if ([...$('#scope-sel').options].some(o => o.value === name)) $('#scope-sel').value = name; }
$('#text').oninput = () => localStorage.setItem(`labcad.draft.${state.part}`, $('#text').value);
$('#text').onkeydown = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('#send').click(); };
$('#send').onclick = async () => {
  const text = $('#text').value.trim(); if (!text && !state.pins.length) { hint('Say something, or drop a pin', 2000); return; }
  if (state.preview) await discardPreview();
  setBusy(true); $('#live').textContent = 'Sending…';
  const body = { text, model: $('#ov-model').value || null, effort: $('#ov-effort').value || null, version: state.version?.version, scope: $('#scope').hidden ? null : ($('#scope-sel').value || null),
    pins: state.pins.map(({ n, x, y, z, note, component }) => ({ n, x, y, z, note, component })), measures: state.measures.map(({ label, mm }) => ({ label, mm })), shot: snapshot(), attachments: state.attachments };
  state.attachments = []; renderAttachments(); resetOverride();
  $('#text').value = ''; localStorage.removeItem(`labcad.draft.${state.part}`);
  let res; try { res = await fetch(`/api/parts/${state.part}/feedback`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }); } catch (e) { $('#live').innerHTML = `<span class="err">Couldn't reach the Studio server.</span>`; setBusy(false); return; }
  await refresh(false);
  const rd = res.body.getReader(), dec = new TextDecoder(); let buf = '', newest = null;
  while (true) {
    const { value, done } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true });
    let i; while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1); if (!line.trim()) continue; const ev = JSON.parse(line);
      if (ev.type === 'status') $('#live').textContent = ev.text;
      else if (ev.type === 'error') $('#live').innerHTML = `<span class="err">${esc(ev.text)}</span>`;
      else if (ev.type === 'final') { newest = ev.new_versions?.at(-1) || null; $('#live').textContent = ''; }
    }
  }
  setBusy(false); clearPins(); clearMeasures();
  await refresh(!!newest);
  if (newest) { const v = state.version, ch = Object.entries(v?.changes || {}).filter(([, s]) => s !== 'same').map(([n]) => n); if (ch.length && (v.components || []).length > 1) state.pulse = { names: new Set(ch), t0: performance.now() }; }
};

// ---------- lineage, family, fork ----------
function renderLineage() {
  const lin = state.spec.lineage; if (!lin) { $('#lineage').textContent = ''; return; }
  $('#lineage').innerHTML = `${lin.mode === 'derive' ? 'derives from' : 'copied from'} <b data-p="${lin.parent}">${lin.parent.replace(/_/g, ' ')}</b> ${tagOf(lin.from_version)}`;
  $('#lineage b').onclick = () => { $('#parts').value = lin.parent; selectPart(lin.parent); };
}
async function renderFamily() {
  const fam = await (await fetch('/api/family')).json();
  const byN = Object.fromEntries(fam.nodes.map(n => [n.name, n]));
  let root = byN[state.part]; while (root?.lineage && byN[root.lineage.parent]) root = byN[root.lineage.parent];
  const inFam = new Set(); const kidsOf = {}; fam.edges.forEach(e => (kidsOf[e.parent] ||= []).push(e.child));
  const walk = n => { inFam.add(n); (kidsOf[n] || []).forEach(walk); }; if (root) walk(root.name);
  const wrap = $('#family'); wrap.innerHTML = `<div class="tlwrap"></div><div class="famlist"></div>`;
  if (root) drawTimelineVertical(wrap.querySelector('.tlwrap'), { nodes: fam.nodes.filter(n => inFam.has(n.name)), edges: fam.edges.filter(e => inFam.has(e.child)) },
    { roots: [root], current: { part: state.part, version: state.version?.version }, onPick: async (p, v) => { if (p !== state.part) { $('#parts').value = p; await selectPart(p); } if (v) { const vv = state.spec.versions.find(x => x.version === v); if (vv) await showVersion(vv); } } });
  await renderFamilyList(fam, wrap.querySelector('.famlist'), inFam);
}
async function renderFamilyList(fam, into, inFam) {
  const kids = {}; fam.edges.forEach(e => (kids[e.parent] ||= []).push(e));
  const byName = Object.fromEntries(fam.nodes.map(n => [n.name, n]));
  const roots = fam.nodes.filter(n => !n.lineage);
  const node = (n, edge) => `<li><div class="node ${n.name === state.part ? 'on' : ''}" data-p="${n.name}"><span class="nm">${n.name.replace(/_/g, ' ')}</span><span class="ct">${n.versions} version${n.versions === 1 ? '' : 's'}</span>
      <span class="why">${edge ? `${edge.mode === 'derive' ? 'derives from' : 'copied from'} ${tagOf(edge.at)}${n.lineage?.note ? ' — ' + esc(n.lineage.note) : ''}` : (n.latest ? esc(n.latest.message) : 'not built yet')}</span></div>
      ${(kids[n.name] || []).length ? `<ul>${kids[n.name].map(e => byName[e.child] ? node(byName[e.child], e) : '').join('')}</ul>` : ''}</li>`;
  const others = roots.filter(r => !inFam.has(r.name));
  into.innerHTML = (others.length ? `<p style="color:var(--ink-3);font-size:12.5px;margin:14px 0 6px">Other families</p><ul class="fam">${others.map(r => node(r, null)).join('')}</ul>` : '') + `<p style="margin:14px 0 0"><a href="/library.html" style="color:var(--ink-2)">Open the Library</a> to pose thumbnails, delete, or restore.</p>`;
  into.querySelectorAll('.node').forEach(el => el.onclick = () => { $('#parts').value = el.dataset.p; selectPart(el.dataset.p); });
}
function openFork(fromVersion) {
  const v = fromVersion || state.version?.version; if (!v) return;
  $('#forkdlg').dataset.from = v; $('#fork-from').textContent = `${state.part.replace(/_/g, ' ')} ${tagOf(v)}`;
  $('#fork-name').value = ''; $('#fork-note').value = ''; $('#forkdlg').classList.add('on'); $('#fork-name').focus();
}
$('#forkbtn').onclick = () => openFork();

// ---------- target printer ----------
const FITLBL = { fits: 'fits the bed', rotate: 'fits turned 90°', diagonal: 'fits diagonally', too_big: 'too big for the bed', unknown: '—' };
async function renderPrinter() {
  const d = await (await fetch('/api/printers')).json();
  const cur = state.spec?.printer || {};
  $('#prsel').innerHTML = Object.entries(d.printers).map(([k, p]) =>
    `<option value="${k}" ${k === cur.key ? 'selected' : ''}>${esc(p.name)}${k === d.default ? ' (default)' : ''}</option>`).join('');
  if (state.preview) { showFit(state.preview.components.map(c => ({ ...c.fit, label: c.label, name: c.name })), true); return; }
  const fit = state.spec?.versions?.length ? await (await fetch(`/api/parts/${state.part}/fit`)).json() : { status: 'unknown' };
  showFit(fit.components || [fit], false);
}
const FIT_ORDER = ['fits', 'rotate', 'diagonal', 'unknown', 'too_big'];
/** Bed-fit chip + title-block row for a list of per-piece fits (saved version, or the live preview). */
function showFit(comps, isPreview) {
  const el = $('#prfit'), cur = state.spec?.printer || {};
  const worst = comps.reduce((a, c) => (FIT_ORDER.indexOf(c.status) > FIT_ORDER.indexOf(a?.status) ? c : a), comps[0] || { status: 'unknown' });
  const st = worst?.status || 'unknown';
  el.className = st;
  el.textContent = (isPreview ? 'preview: ' : '') + (comps.length > 1 ? (st === 'fits' ? `all ${comps.length} pieces fit` : `${worst.label} ${st === 'too_big' ? 'is too big for the bed' : FITLBL[st]}`) : (FITLBL[st] || '—'));
  el.title = comps.length > 1 ? comps.map(c => `${c.label}: ${FITLBL[c.status] || '—'}`).join('\n')
    : [worst.how, worst.over?.some(v => v > 0) ? `over by ${worst.over.filter(v => v > 0).map(v => v + ' mm').join(', ')}` : '', worst.bed ? `bed ${worst.bed.map(Math.round).join('×')} mm` : ''].filter(Boolean).join(' · ');
  $('#tb-pr').textContent = `${cur.name || '—'}${st !== 'unknown' ? ' · ' + el.textContent : ''}`;
}
$('#prsel').onchange = async () => {
  await fetch(`/api/parts/${state.part}/printer`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ printer: $('#prsel').value }) });
  state.spec = await (await fetch(`/api/parts/${state.part}`)).json();
  await renderPrinter(); renderPrint();
  hint('Target printer set — Claude designs to it from here on', 2600);
};
// ---------- tiny prompt dialog ----------
function ask(title, value = '') {
  return new Promise(res => {
    const d = $('#askdlg'); $('#ask-title').textContent = title; $('#ask-in').value = value; d.classList.add('on'); $('#ask-in').focus(); $('#ask-in').select();
    const done = v => { d.classList.remove('on'); $('#ask-ok').onclick = $('#ask-cancel').onclick = null; $('#ask-in').onkeydown = null; res(v); };
    $('#ask-ok').onclick = () => done($('#ask-in').value.trim()); $('#ask-cancel').onclick = () => done(null);
    $('#ask-in').onkeydown = e => { if (e.key === 'Enter') $('#ask-ok').click(); if (e.key === 'Escape') $('#ask-cancel').click(); };
  });
}
$('#renbtn').onclick = async () => {
  const v = await ask(`Rename "${state.part.replace(/_/g, ' ')}" — letters, digits, underscores`, state.part); if (!v || v === state.part) return;
  const r = await fetch(`/api/parts/${state.part}/rename`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ new_name: v }) });
  if (!r.ok) { hint((await r.json()).detail || 'Rename failed', 4000); return; }
  const { name } = await r.json(); await loadPartsList(); $('#parts').value = name; await selectPart(name);
};
// ---------- new part from a brief ----------
state.newAttach = [];
function renderNewAttach() { $('#new-attach').innerHTML = state.newAttach.map(a => `<div class="a"><img src="${a}" alt=""></div>`).join(''); }
$('#newbtn').onclick = () => { $('#newdlg').classList.add('on'); $('#forkdlg').classList.remove('on'); $('#new-name').focus(); };
$('#new-cancel').onclick = () => $('#newdlg').classList.remove('on');
$('#new-name').onkeydown = e => { if (e.key === 'Escape') $('#new-cancel').click(); };
$('#new-brief').addEventListener('paste', e => { for (const it of e.clipboardData.items) if (it.type.startsWith('image/')) { const f = it.getAsFile(); const rd = new FileReader(); rd.onload = () => { state.newAttach.push(rd.result); renderNewAttach(); }; rd.readAsDataURL(f); e.preventDefault(); } });
$('#new-go').onclick = async () => {
  const name = $('#new-name').value.trim(), brief = $('#new-brief').value.trim();
  if (!name) { $('#new-name').focus(); return; } if (!brief) { $('#new-brief').focus(); return; }
  $('#new-go').disabled = true; $('#new-go').textContent = 'Starting…';
  const res = await fetch('/api/parts/new', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name, brief, attachments: state.newAttach }) });
  if (!res.ok) { const e = await res.json(); hint(e.detail || 'Could not start', 4000); $('#new-go').disabled = false; $('#new-go').textContent = 'Ask Claude to build it'; return; }
  $('#newdlg').classList.remove('on'); $('#new-go').disabled = false; $('#new-go').textContent = 'Ask Claude to build it'; state.newAttach = []; renderNewAttach();
  const created = name.toLowerCase().replace(/[ -]/g, '_');
  await loadPartsList(); $('#parts').value = created; state.part = created; localStorage.setItem('labcad.part', created); history.replaceState(null, '', `?part=${created}`);
  clearPins(); clearMeasures(); state.version = null; clearModel();
  state.spec = { name: created, doc: '', params: {}, knobs: [], versions: [], chat: [{ role: 'user', text: brief, ts: new Date().toISOString(), pins: [] }], lineage: null, printed: {} };
  renderChat(); renderVersions(); renderKnobs(); renderPrint(); document.querySelector('#tabs button[data-pane=talk]').click();
  setBusy(true); $('#live').textContent = 'Claude is designing it…';
  const rd = res.body.getReader(), dec = new TextDecoder(); let buf = '';
  while (true) {
    const { value, done } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true });
    let i; while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1); if (!line.trim()) continue; const ev = JSON.parse(line);
      if (ev.type === 'status') $('#live').textContent = ev.text;
      else if (ev.type === 'error') $('#live').innerHTML = `<span class="err">${esc(ev.text)}</span>`;
      else if (ev.type === 'final') $('#live').textContent = '';
    }
  }
  setBusy(false); await refresh(true);
};
$('#fork-cancel').onclick = () => $('#forkdlg').classList.remove('on');
$('#fork-name').onkeydown = e => { if (e.key === 'Enter') $('#fork-go').click(); if (e.key === 'Escape') $('#fork-cancel').click(); };
$('#fork-go').onclick = async () => {
  const name = $('#fork-name').value.trim(); if (!name) { $('#fork-name').focus(); return; }
  $('#fork-go').disabled = true; $('#fork-go').textContent = 'Creating…';
  const r = await fetch(`/api/parts/${state.part}/fork`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ new_name: name, from_version: Number($('#forkdlg').dataset.from), mode: document.querySelector('input[name=fmode]:checked').value, note: $('#fork-note').value.trim() }) });
  $('#fork-go').disabled = false; $('#fork-go').textContent = 'Create variant';
  if (!r.ok) { const e = await r.json(); hint(e.detail || e.error?.split('\n').filter(Boolean).pop() || 'Fork failed', 4000); return; }
  const { name: created } = await r.json(); $('#forkdlg').classList.remove('on');
  await loadPartsList(); $('#parts').value = created; await selectPart(created);
};

document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => { document.querySelectorAll('#tabs button').forEach(x => x.setAttribute('aria-selected', String(x === b))); document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === `pane-${b.dataset.pane}`)); if (b.dataset.pane === 'family') renderFamily(); });
loadParts().then(() => { if (new URLSearchParams(location.search).get('new')) $('#newbtn').click(); });

// One-message model / effort override in the Talk tab; blank = the user's saved choice (Account page)
const capw = s => s === 'xhigh' ? 'Extra high' : s[0].toUpperCase() + s.slice(1);
function resetOverride() { for (const id of ['#ov-model', '#ov-effort']) { $(id).value = ''; $(id).classList.remove('set'); } }
function loadOverride() {
  fetch('/api/account').then(r => r.json()).then(a => {
    if (!a.enabled) $('#acctbtn').hidden = true;
    const p = a.prefs || {};
    $('#ov-model').innerHTML = `<option value="">${capw(p.model || 'opus')} (yours)</option>` + a.models.filter(m => m !== p.model).map(m => `<option value="${m}">${capw(m)}</option>`).join('');
    $('#ov-effort').innerHTML = `<option value="">${p.effort ? capw(p.effort) : 'Default'} effort (yours)</option>` + a.efforts.filter(e => e !== p.effort).map(e => `<option value="${e}">${capw(e)} effort</option>`).join('');
    resetOverride();
  }).catch(() => {});
}
for (const id of ['#ov-model', '#ov-effort']) $(id).onchange = () => $(id).classList.toggle('set', !!$(id).value);
loadOverride();
