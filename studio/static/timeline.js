// Branching timeline for a part family: one lane per part, a dot per version, a curve where a fork leaves its parent.
// drawTimeline(el, family, { current: {part, version}, onPick(part, version) })
export function drawTimeline(el, fam, opts = {}) {
  const byName = Object.fromEntries(fam.nodes.map(n => [n.name, n]));
  const kids = {}; fam.edges.forEach(e => (kids[e.parent] ||= []).push(e));
  const edgeOf = Object.fromEntries(fam.edges.map(e => [e.child, e]));
  const lanes = [];                                   // tree order: parent, then its children (depth-first)
  const walk = (n, depth) => { lanes.push({ n, depth }); (kids[n.name] || []).sort((a, b) => a.at - b.at).forEach(e => byName[e.child] && walk(byName[e.child], depth + 1)); };
  (opts.roots || fam.nodes.filter(n => !n.lineage)).forEach(r => walk(r, 0));
  const LABEL = 170, STEP = 46, ROW = 40, R = 6, PAD = 24;
  const col = {};                                     // col[part][version] = column index
  let maxCol = 0;
  for (const { n } of lanes) {
    const e = edgeOf[n.name]; let start = 0;
    if (e && col[e.parent]) { const pc = col[e.parent][e.at]; start = (pc ?? 0) + 1; }
    col[n.name] = {}; n.versions_list.forEach((v, i) => { col[n.name][v.version] = start + i; maxCol = Math.max(maxCol, start + i); });
  }
  const W = LABEL + PAD + (maxCol + 1) * STEP + PAD, H = lanes.length * ROW + PAD;
  const X = c => LABEL + PAD + c * STEP, Y = i => PAD / 2 + i * ROW + ROW / 2;
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  let svg = `<svg class="tl" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="family timeline">`;
  lanes.forEach(({ n, depth }, i) => {
    const vs = n.versions_list; if (!vs.length) return;
    const x0 = X(col[n.name][vs[0].version]), x1 = X(col[n.name][vs.at(-1).version]);
    svg += `<line class="lane" x1="${x0}" y1="${Y(i)}" x2="${x1}" y2="${Y(i)}"/>`;
    const e = edgeOf[n.name];
    if (e && col[e.parent] && col[e.parent][e.at] != null) {
      const pi = lanes.findIndex(l => l.n.name === e.parent), px = X(col[e.parent][e.at]), py = Y(pi);
      svg += `<path class="fork ${e.mode}" d="M${px},${py} C${px + STEP * 0.6},${py} ${x0 - STEP * 0.6},${Y(i)} ${x0},${Y(i)}"/>`;
    }
    svg += `<text class="name ${n.name === opts.current?.part ? 'on' : ''}" x="${8 + depth * 14}" y="${Y(i) + 4}" data-p="${n.name}">${esc(n.name.replace(/_/g, ' '))}</text>`;
    vs.forEach(v => {
      const cur = opts.current && opts.current.part === n.name && opts.current.version === v.version;
      svg += `<g class="dot ${cur ? 'on' : ''}" data-p="${n.name}" data-v="${v.version}" tabindex="0"><title>${esc(n.name)} ${v.tag} — ${esc(v.message)} (${v.ts.slice(0, 16).replace('T', ' ')})</title>
        <circle cx="${X(col[n.name][v.version])}" cy="${Y(i)}" r="${R}"/><text x="${X(col[n.name][v.version])}" y="${Y(i) + R + 12}" text-anchor="middle">${v.version}</text></g>`;
    });
  });
  svg += '</svg>';
  el.innerHTML = svg;
  el.querySelectorAll('.dot').forEach(g => { const pick = () => opts.onPick?.(g.dataset.p, Number(g.dataset.v)); g.onclick = pick; g.onkeydown = e => { if (e.key === 'Enter') pick(); }; });
  el.querySelectorAll('text.name').forEach(t => t.onclick = () => opts.onPick?.(t.dataset.p, null));
  return lanes.map(l => l.n.name);
}
export const TIMELINE_CSS = `
  .tl{display:block;font:12px "Instrument Sans",system-ui,sans-serif}
  .tl .lane{stroke:#3c424b;stroke-width:2}
  .tl .fork{fill:none;stroke:#ff9f43;stroke-width:1.6;opacity:.8}
  .tl .fork.copy{stroke-dasharray:4 3}
  .tl .name{fill:#a9aeb6;cursor:pointer;font-weight:600}
  .tl .name.on{fill:#e8e3da}
  .tl .dot circle{fill:#9fc0e8;stroke:#1d2025;stroke-width:2;cursor:pointer}
  .tl .dot text{fill:#6f757f}
  .tl .dot.on circle{fill:#ff9f43}
  .tl .dot:hover circle,.tl .dot:focus circle{stroke:#ff9f43;outline:none}
`;

// Vertical, git-log style: one row per version (newest first), lane columns in a narrow gutter, text to the right.
export function drawTimelineVertical(el, fam, opts = {}) {
  const byName = Object.fromEntries(fam.nodes.map(n => [n.name, n]));
  const kids = {}; fam.edges.forEach(e => (kids[e.parent] ||= []).push(e));
  const edgeOf = Object.fromEntries(fam.edges.map(e => [e.child, e]));
  const lanes = []; const walk = n => { lanes.push(n.name); (kids[n.name] || []).sort((a, b) => a.at - b.at).forEach(e => byName[e.child] && walk(byName[e.child])); };
  (opts.roots || fam.nodes.filter(n => !n.lineage)).forEach(walk);
  const lane = Object.fromEntries(lanes.map((n, i) => [n, i]));
  const rows = fam.nodes.filter(n => lane[n.name] != null).flatMap(n => n.versions_list.map(v => ({ part: n.name, ...v }))).sort((a, b) => b.ts.localeCompare(a.ts) || b.version - a.version);
  const rowOf = {}; rows.forEach((r, i) => (rowOf[r.part] ||= {})[r.version] = i);
  const GX = 12, GS = 16, ROW = 34, TX = GX + lanes.length * GS + 6, R = 5;
  const X = l => GX + l * GS, Y = i => 17 + i * ROW;
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const H = rows.length * ROW + 6;
  let svg = `<svg class="tl tlv" viewBox="0 0 ${TX + 4} ${H}" width="${TX + 4}" height="${H}">`;
  for (const n of lanes) {
    const vs = byName[n].versions_list; if (!vs.length) continue;
    const ys = vs.map(v => Y(rowOf[n][v.version]));
    svg += `<line class="lane" x1="${X(lane[n])}" y1="${Math.min(...ys)}" x2="${X(lane[n])}" y2="${Math.max(...ys)}"/>`;
    const e = edgeOf[n];
    if (e && rowOf[e.parent]?.[e.at] != null) {
      const px = X(lane[e.parent]), py = Y(rowOf[e.parent][e.at]), cx = X(lane[n]), cy = Math.max(...ys);   // child's first (oldest) version
      svg += `<path class="fork ${e.mode}" d="M${px},${py} C${px},${py - (py - cy) / 2} ${cx},${cy + (py - cy) / 2} ${cx},${cy}"/>`;
    }
  }
  rows.forEach((r, i) => {
    const cur = opts.current && opts.current.part === r.part && opts.current.version === r.version;
    svg += `<g class="dot ${cur ? 'on' : ''}" data-p="${r.part}" data-v="${r.version}" tabindex="0"><title>${esc(r.part)} ${r.tag} — ${esc(r.message)}</title><circle cx="${X(lane[r.part])}" cy="${Y(i)}" r="${R}"/></g>`;
  });
  svg += '</svg>';
  const list = rows.map((r, i) => `<div class="tlrow ${opts.current && opts.current.part === r.part && opts.current.version === r.version ? 'on' : ''}" data-p="${r.part}" data-v="${r.version}" style="height:${ROW}px"><span class="tag">${r.tag}</span><span class="pn">${esc(r.part.replace(/_/g, ' '))}</span><span class="m" title="${esc(r.message)}">${esc(r.message)}</span></div>`).join('');
  el.innerHTML = `<div class="tlv-wrap">${svg}<div class="tlv-list" style="padding-top:${17 - ROW / 2}px">${list}</div></div>`;
  el.querySelectorAll('.dot, .tlrow').forEach(g => { const pick = () => opts.onPick?.(g.dataset.p, Number(g.dataset.v)); g.onclick = pick; g.onkeydown = e => { if (e.key === 'Enter') pick(); }; });
}
export const TIMELINE_V_CSS = `
  .tlv-wrap{display:flex;align-items:flex-start}
  .tlv-list{flex:1;min-width:0}
  .tlrow{display:grid;grid-template-columns:auto 1fr;grid-template-rows:auto auto;column-gap:8px;align-content:center;padding:0 8px 0 4px;border-radius:6px;cursor:pointer;font-size:12.5px;line-height:1.25}
  .tlrow:hover{background:#1d2025}
  .tlrow.on{box-shadow:inset 2px 0 0 #ff9f43}
  .tlrow .tag{font-weight:700;color:#e8e3da}
  .tlrow .pn{color:#6f757f;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .tlrow .m{grid-column:1/3;color:#a9aeb6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
`;
