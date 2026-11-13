/* Systainer Bin Designer: palette UI (2D layout editor, 3D preview, Fusion bridge). */
(function () {
  'use strict';
  const LY = window.SBDLayout;
  const $ = id => document.getElementById(id);
  const key = (a, b) => a + ',' + b;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clone = o => JSON.parse(JSON.stringify(o));

  const FIT_META = [
    ['OneUnit', 'Grid pitch', 'mm'], ['UnitNubWidth', 'Nub opening in feet', 'mm'],
    ['UnitNubPadding', 'Extra nub clearance / side', 'mm'], ['BaseSquareTrim', 'Foot square trim', 'mm'],
    ['UnitSquarePadding', 'Edge to lower wall', 'mm'], ['BaseClearance', 'Foot height', 'mm'],
    ['BoxWallThickness', 'Wall and floor', 'mm'], ['RimHeight', 'Rim height', 'mm'],
    ['BoxCornerRadius', 'Corner radius', 'mm'], ['RimChamferAngle', 'Rim chamfer angle', '°']
  ];
  const HEIGHT_PRESETS = [[68, '68 mm (full height)'], [36.8, '36.8 mm (low)']];

  // ---------------------------------------------------------------- state
  const S = {
    nx: LY.DEFAULT_SIZE.nx, ny: LY.DEFAULT_SIZE.ny, sub: LY.DEFAULT_SIZE.sub, height: LY.DEFAULT_SIZE.height,
    walls: { v: [], h: [] }, fit: { ...LY.DEFAULT_FIT }, divider: { ...LY.DEFAULT_DIVIDER }, name: ''
  };
  S.walls = LY.quickSplit(S, 3, 2);
  const settings = { bedSize: 256, autoUpdate: false };
  const undoStack = [], redoStack = [];
  let errors = [];

  const cfg = () => ({ nx: S.nx, ny: S.ny, sub: S.sub, height: S.height, walls: S.walls, fit: S.fit, divider: S.divider, name: S.name });
  function snapshot() { return JSON.stringify(cfg()); }
  function pushUndo() { undoStack.push(snapshot()); if (undoStack.length > 200) undoStack.shift(); redoStack.length = 0; }
  function restore(json) { Object.assign(S, JSON.parse(json)); syncInputs(); changed(false); }

  // --------------------------------------------------------------- inputs
  function syncInputs() {
    $('nx').value = S.nx; $('ny').value = S.ny; $('height').value = S.height;
    $('dThick').value = S.divider.thickness; $('dGap').value = S.divider.topGap;
    document.querySelectorAll('[data-sub]').forEach(b => b.classList.toggle('on', Number(b.dataset.sub) === S.sub));
    $('heightChips').innerHTML = HEIGHT_PRESETS.map(([h, l]) =>
      `<button class="chip${Math.abs(S.height - h) < 1e-6 ? ' on' : ''}" data-h="${h}">${l}</button>`).join('');
    const preset = Object.keys(LY.FIT_PRESETS).find(p => FIT_META.every(([k]) => Math.abs(LY.FIT_PRESETS[p][k] - S.fit[k]) < 1e-9));
    document.querySelectorAll('[data-preset]').forEach(b => b.classList.toggle('on', b.dataset.preset === preset));
    $('fitRows').innerHTML = FIT_META.map(([k, label, u]) =>
      `<div class="row"><label for="fit_${k}">${label} (${u}) <span class="note">[${LY.FIT_PRESETS.template[k]}]</span></label>` +
      `<input id="fit_${k}" type="number" step="0.05" data-fit="${k}" value="${S.fit[k]}"></div>`).join('');
    $('layoutName').value = S.name || '';
    $('bedSize').value = settings.bedSize; $('autoSync').checked = !!settings.autoUpdate;
  }

  function changed(record = true) {
    S.walls = LY.cleanWalls(S);
    errors = LY.validate(S);
    drawEditor(); updateInfo(); rebuildMesh(); updateButtons();
    if (record) scheduleAutoSync();
  }

  function num(v, fallback) { const n = Number(v); return Number.isFinite(n) ? n : fallback; }

  function setSub(sub) {
    if (sub === S.sub) return;
    pushUndo();
    if (sub === 2) {
      const v = [], h = [];
      S.walls.v.forEach(([i, j]) => { v.push([2 * i, 2 * j], [2 * i, 2 * j + 1]); });
      S.walls.h.forEach(([i, j]) => { h.push([2 * i, 2 * j], [2 * i + 1, 2 * j]); });
      S.walls = { v, h };
    } else {
      const v = new Map(), h = new Map(); let dropped = 0;
      S.walls.v.forEach(([i, j]) => { if (i % 2 === 0) v.set(key(i / 2, j >> 1), [i / 2, j >> 1]); else dropped++; });
      S.walls.h.forEach(([i, j]) => { if (j % 2 === 0) h.set(key(i >> 1, j / 2), [i >> 1, j / 2]); else dropped++; });
      S.walls = { v: [...v.values()], h: [...h.values()] };
      if (dropped) status(`Removed ${dropped} half-unit wall segment(s) that are not on a full unit line.`);
    }
    S.sub = sub; syncInputs(); changed();
  }

  function resize(nx, ny) {
    nx = Math.max(1, Math.min(20, Math.round(num(nx, S.nx)))); ny = Math.max(1, Math.min(20, Math.round(num(ny, S.ny))));
    if (nx === S.nx && ny === S.ny) { syncInputs(); return; }
    pushUndo(); S.nx = nx; S.ny = ny; syncInputs(); changed();
  }

  function everyUnit() {
    pushUndo();
    const gx = S.nx * S.sub, gy = S.ny * S.sub, v = [], h = [];
    for (let i = S.sub; i < gx; i += S.sub) for (let j = 0; j < gy; j++) v.push([i, j]);
    for (let j = S.sub; j < gy; j += S.sub) for (let i = 0; i < gx; i++) h.push([i, j]);
    S.walls = { v, h }; changed();
  }

  function updateInfo() {
    const ok = !errors.length;
    $('errors').className = ok ? '' : 'show';
    $('errors').innerHTML = ok ? '' : `<b>Can't build this bin yet:</b><ul>${errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`;
    const g = LY.derived(S);
    const inW = g.width - 2 * g.innerWall, inD = g.depth - 2 * g.innerWall, depth = g.top - S.fit.BoxWallThickness;
    const bed = num(settings.bedSize, 256);
    const bedWarn = (g.width > bed || g.depth > bed) ? `<br><span class="warn">Larger than your ${bed} mm print bed.</span>` : '';
    $('sizeInfo').innerHTML = `Outside ${g.width.toFixed(2)} × ${g.depth.toFixed(2)} × ${S.height} mm<br>` +
      `Inside at the floor ${inW.toFixed(1)} × ${inD.toFixed(1)} mm, ${depth.toFixed(1)} mm deep${bedWarn}`;
    const t = S.divider.thickness;
    $('dividerInfo').innerHTML = `Dividers stand ${(g.dividerTop - S.fit.BoxWallThickness).toFixed(1)} mm above the floor. ` +
      `${t.toFixed(2)} mm is about ${(t / 0.42).toFixed(1)} extrusion lines at 0.42 mm.` +
      (t < 0.8 ? ' <span class="warn">That is below the usual 0.8 mm minimum for a 0.4 mm nozzle.</span>' : '');
    const comps = LY.compartments(S), nRuns = LY.dividerRuns(S).length;
    $('compList').innerHTML = comps.map((c, n) =>
      `<div><span>#${n + 1}</span><span>${c.isRect ? `${c.size[0].toFixed(1)} × ${c.size[1].toFixed(1)}` : `Irregular, ${c.cells.length} cells`} × ${c.size[2].toFixed(1)} mm</span></div>`).join('');
    $('editorStats').textContent = `${comps.length} compartment${comps.length === 1 ? '' : 's'} · ${nRuns} divider run${nRuns === 1 ? '' : 's'}`;
    $('undo').disabled = !undoStack.length; $('redo').disabled = !redoStack.length;
  }

  // ------------------------------------------------------------ 2D editor
  const ed = $('editor'), ectx = ed.getContext('2d');
  let v2 = { s: 1, ox: 0, oy: 0, dpr: 1 }, hover = null, drag = null;
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function fitEditor() {
    const r = ed.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    ed.width = Math.max(10, Math.round(r.width * dpr)); ed.height = Math.max(10, Math.round(r.height * dpr));
    const g = LY.derived(S), m = 36;
    const s = Math.max(0.1, Math.min((r.width - 2 * m) / g.width, (r.height - 2 * m) / g.depth));
    v2 = { s, ox: (r.width - g.width * s) / 2, oy: (r.height - g.depth * s) / 2, dpr };
  }
  const sx = x => v2.ox + x * v2.s;
  const sy = y => v2.oy + (LY.derived(S).depth - y) * v2.s;

  function roundRect(c, x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  }

  function drawEditor() {
    fitEditor();
    const c = ectx, g = LY.derived(S), gx = S.nx * S.sub, gy = S.ny * S.sub, w = S.fit.BoxWallThickness, pad = S.fit.UnitSquarePadding;
    c.setTransform(v2.dpr, 0, 0, v2.dpr, 0, 0);
    c.clearRect(0, 0, ed.width, ed.height);
    c.fillStyle = css('--bin');
    roundRect(c, sx(0), sy(g.depth), g.width * v2.s, g.depth * v2.s, (S.fit.BoxCornerRadius + pad) * v2.s); c.fill();
    c.fillStyle = css('--cell');
    roundRect(c, sx(w), sy(g.depth - w), (g.width - 2 * w) * v2.s, (g.depth - 2 * w) * v2.s, Math.max(0, S.fit.BoxCornerRadius + pad - w) * v2.s); c.fill();
    const comps = LY.compartments(S);
    comps.forEach((cp, n) => {
      c.fillStyle = n % 2 ? css('--cell-alt') : css('--cell');
      cp.cells.forEach(([i, j]) => {
        const x0 = Math.max(i * g.step, w), x1 = Math.min((i + 1) * g.step, g.width - w);
        const y0 = Math.max(j * g.step, w), y1 = Math.min((j + 1) * g.step, g.depth - w);
        c.fillRect(sx(x0), sy(y1), (x1 - x0) * v2.s, (y1 - y0) * v2.s);
      });
    });
    const gridLine = (major, x0, y0, x1, y1) => {
      c.strokeStyle = major ? 'rgba(120,130,150,.45)' : 'rgba(120,130,150,.2)'; c.lineWidth = 1; c.setLineDash(major ? [] : [3, 3]);
      c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
    };
    for (let i = 1; i < gx; i++) gridLine(i % S.sub === 0, sx(i * g.step), sy(w), sx(i * g.step), sy(g.depth - w));
    for (let j = 1; j < gy; j++) gridLine(j % S.sub === 0, sx(w), sy(j * g.step), sx(g.width - w), sy(j * g.step));
    c.setLineDash([]);
    c.fillStyle = css('--wall');
    LY.dividerBoxes(S).forEach(([x0, y0, x1, y1]) => {
      const bw = Math.max((x1 - x0) * v2.s, 3), bh = Math.max((y1 - y0) * v2.s, 3);
      c.fillRect(sx((x0 + x1) / 2) - bw / 2, sy((y0 + y1) / 2) - bh / 2, bw, bh);
    });
    if (hover) {
      const [axis, i, j] = hover;
      c.strokeStyle = css('--wall-hover'); c.lineWidth = 5; c.lineCap = 'round'; c.beginPath();
      if (axis === 'v') { c.moveTo(sx(i * g.step), sy(j * g.step)); c.lineTo(sx(i * g.step), sy((j + 1) * g.step)); }
      else { c.moveTo(sx(i * g.step), sy(j * g.step)); c.lineTo(sx((i + 1) * g.step), sy(j * g.step)); }
      c.stroke(); c.lineCap = 'butt';
    }
    c.fillStyle = css('--ink'); c.textAlign = 'center'; c.textBaseline = 'middle';
    comps.forEach(cp => {
      const b = cp.bounds;
      const [ci, cj] = cp.isRect ? [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] : [cp.cells[0][0] + 0.5, cp.cells[0][1] + 0.5];
      const minDim = (cp.isRect ? Math.min(b[2] - b[0], b[3] - b[1]) : 1) * g.step * v2.s;
      if (minDim < 26) return;
      c.font = `${minDim > 60 ? 12 : 10}px -apple-system, sans-serif`;
      c.fillText(cp.isRect ? `${cp.size[0].toFixed(1)} × ${cp.size[1].toFixed(1)}` : `${cp.cells.length} cells`, sx(ci * g.step), sy(cj * g.step));
    });
    c.fillStyle = css('--muted'); c.font = '11px -apple-system, sans-serif';
    c.fillText(`${g.width.toFixed(2)} mm (${S.nx} unit${S.nx === 1 ? '' : 's'})`, sx(g.width / 2), sy(0) + 16);
    c.save(); c.translate(sx(0) - 16, sy(g.depth / 2)); c.rotate(-Math.PI / 2);
    c.fillText(`${g.depth.toFixed(2)} mm (${S.ny} unit${S.ny === 1 ? '' : 's'})`, 0, 0); c.restore();
  }

  function pickSegment(px, py) {
    const g = LY.derived(S), gx = S.nx * S.sub, gy = S.ny * S.sub;
    const x = (px - v2.ox) / v2.s, y = g.depth - (py - v2.oy) / v2.s;
    const tol = Math.max(10 / v2.s, g.step * 0.18);
    let best = null, bd = Infinity;
    const i = Math.round(x / g.step), j = Math.floor(y / g.step);
    if (i > 0 && i < gx && j >= 0 && j < gy) { const d = Math.abs(x - i * g.step); if (d < tol && d < bd) { bd = d; best = ['v', i, j]; } }
    const j2 = Math.round(y / g.step), i2 = Math.floor(x / g.step);
    if (j2 > 0 && j2 < gy && i2 >= 0 && i2 < gx) { const d = Math.abs(y - j2 * g.step); if (d < tol && d < bd) { bd = d; best = ['h', i2, j2]; } }
    return best;
  }
  const hasWall = seg => S.walls[seg[0]].some(a => a[0] === seg[1] && a[1] === seg[2]);
  function setWall(seg, on) {
    const list = S.walls[seg[0]], idx = list.findIndex(a => a[0] === seg[1] && a[1] === seg[2]);
    if (on && idx < 0) list.push([seg[1], seg[2]]);
    if (!on && idx >= 0) list.splice(idx, 1);
  }
  const evPos = e => { const r = ed.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  ed.addEventListener('pointerdown', e => {
    const seg = pickSegment(...evPos(e)); if (!seg) return;
    pushUndo(); drag = { on: !hasWall(seg) }; setWall(seg, drag.on); ed.setPointerCapture(e.pointerId); changed();
  });
  ed.addEventListener('pointermove', e => {
    const seg = pickSegment(...evPos(e)), same = hover && seg && hover.join() === seg.join();
    hover = seg;
    if (drag && seg && hasWall(seg) !== drag.on) { setWall(seg, drag.on); changed(); }
    else if (!same) drawEditor();
    const g = LY.derived(S);
    $('hoverInfo').textContent = seg ? (seg[0] === 'v' ? `Line at x = ${(seg[1] * g.step).toFixed(2)} mm` : `Line at y = ${(seg[2] * g.step).toFixed(2)} mm`) : '';
  });
  const endDrag = () => { drag = null; };
  ed.addEventListener('pointerup', endDrag); ed.addEventListener('pointercancel', endDrag);
  ed.addEventListener('pointerleave', () => { if (!drag) { hover = null; drawEditor(); $('hoverInfo').textContent = ''; } });

  // ----------------------------------------------------------- 3D preview
  const cv = $('view'), gl = cv.getContext('webgl', { antialias: true });
  const cam = { yaw: -0.65, pitch: 0.62, dist: 1, tx: 0, ty: 0, tz: 0, userZoom: false };
  let mesh = null, prog = null;
  if (gl) {
    const VS = 'attribute vec3 p; attribute vec3 n; attribute vec3 c; uniform mat4 mvp; varying vec3 vn; varying vec3 vc;' +
      'void main(){ gl_Position = mvp * vec4(p,1.0); vn = n; vc = c; }';
    const FS = 'precision mediump float; varying vec3 vn; varying vec3 vc;' +
      'void main(){ vec3 l = normalize(vec3(0.45,-0.6,0.9)); vec3 l2 = normalize(vec3(-0.6,0.5,0.3));' +
      'vec3 nn = normalize(vn); float d = 0.38 + 0.55*abs(dot(nn,l)) + 0.18*max(dot(nn,l2),0.0); gl_FragColor = vec4(vc*d,1.0); }';
    const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); return o; };
    prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
  } else {
    $('viewHint').textContent = 'WebGL is not available, so the 3D preview is off. The Fusion viewport still shows the real model.';
  }

  function tri(arr, a, b, c, n, col) { for (const p of [a, b, c]) arr.push(p[0], p[1], p[2], n[0], n[1], n[2], col[0], col[1], col[2]); }
  function box(arr, x0, y0, z0, x1, y1, z1, col) {
    if (x1 <= x0 || y1 <= y0 || z1 <= z0) return;
    const P = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]];
    const F = [[0, 3, 2, 1, [0, 0, -1]], [4, 5, 6, 7, [0, 0, 1]], [0, 1, 5, 4, [0, -1, 0]], [2, 3, 7, 6, [0, 1, 0]], [1, 2, 6, 5, [1, 0, 0]], [3, 0, 4, 7, [-1, 0, 0]]];
    for (const [a, b, c, d, n] of F) { tri(arr, P[a], P[b], P[c], n, col); tri(arr, P[a], P[c], P[d], n, col); }
  }
  function rrect(x0, y0, x1, y1, r, seg) {   // rounded-rectangle outline, counter-clockwise
    r = Math.max(0, Math.min(r, (x1 - x0) / 2, (y1 - y0) / 2));
    const corners = [[x1 - r, y0 + r, -Math.PI / 2], [x1 - r, y1 - r, 0], [x0 + r, y1 - r, Math.PI / 2], [x0 + r, y0 + r, Math.PI]], pts = [];
    for (const [cx, cy, a0] of corners) for (let k = 0; k <= seg; k++) { const a = a0 + (Math.PI / 2) * k / seg; pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); }
    return pts;
  }
  function walls3d(arr, pts, z0, z1, outward, col) {
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], b = pts[(i + 1) % pts.length], l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      const s = outward ? 1 : -1, n = [s * (b[1] - a[1]) / l, -s * (b[0] - a[0]) / l, 0];
      tri(arr, [a[0], a[1], z0], [b[0], b[1], z0], [b[0], b[1], z1], n, col);
      tri(arr, [a[0], a[1], z0], [b[0], b[1], z1], [a[0], a[1], z1], n, col);
    }
  }
  function capRing(arr, outer, inner, z, up, col) {
    const n = [0, 0, up ? 1 : -1];
    for (let i = 0; i < outer.length; i++) {
      const j = (i + 1) % outer.length;
      tri(arr, [...outer[i], z], [...outer[j], z], [...inner[j], z], n, col);
      tri(arr, [...outer[i], z], [...inner[j], z], [...inner[i], z], n, col);
    }
  }
  function capFill(arr, pts, z, up, col) {
    const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
    for (let i = 0; i < pts.length; i++) tri(arr, [cx, cy, z], [...pts[i], z], [...pts[(i + 1) % pts.length], z], [0, 0, up ? 1 : -1], col);
  }
  function tube(arr, outer, inner, z0, z1, col) {
    walls3d(arr, outer, z0, z1, true, col); walls3d(arr, inner, z0, z1, false, col);
    capRing(arr, outer, inner, z1, true, col); capRing(arr, outer, inner, z0, false, col);
  }

  function rebuildMesh() {
    if (!gl) return;
    const g = LY.derived(S), f = S.fit, arr = [], SEG = 6;
    const body = [0.80, 0.84, 0.90], divc = [0.30, 0.52, 0.92], footc = [0.62, 0.67, 0.75];
    const p = f.UnitSquarePadding, w = f.BoxWallThickness, W = g.width, D = g.depth, R = f.BoxCornerRadius;
    if (!errors.length) {
      const lo = rrect(p, p, W - p, D - p, R, SEG), li = rrect(p + w, p + w, W - p - w, D - p - w, R - w, SEG);
      tube(arr, lo, li, w, g.lowerHeight, body);
      walls3d(arr, lo, 0, w, true, body); capFill(arr, lo, 0, false, body); capFill(arr, li, w, true, body);
      const ro = rrect(0, 0, W, D, R + p, SEG), ri = rrect(w, w, W - w, D - w, R + p - w, SEG);
      const r0 = g.lowerHeight - w, chH = LY.chamferHeight(f);
      tube(arr, ro, ri, r0, g.top, body);
      for (let i = 0; i < ro.length; i++) {        // chamfer skirt under the rim overhang
        const j = (i + 1) % ro.length, l = Math.hypot(ro[j][1] - ro[i][1], ro[j][0] - ro[i][0]) || 1;
        const n = [0.87 * (ro[j][1] - ro[i][1]) / l, -0.87 * (ro[j][0] - ro[i][0]) / l, -0.5];
        tri(arr, [...ro[i], r0], [...ro[j], r0], [...lo[j], r0 - chH], n, body);
        tri(arr, [...ro[i], r0], [...lo[j], r0 - chH], [...lo[i], r0 - chH], n, body);
      }
      const bsw = g.footSize, ring = g.footRing;
      for (let i = 0; i < S.nx; i++) for (let j = 0; j < S.ny; j++) {
        const x0 = i * g.unit + (g.unit - bsw) / 2, y0 = j * g.unit + (g.unit - bsw) / 2;
        tube(arr, rrect(x0, y0, x0 + bsw, y0 + bsw, R, SEG),
             rrect(x0 + ring, y0 + ring, x0 + bsw - ring, y0 + bsw - ring, R - ring, SEG), -f.BaseClearance, 0, footc);
      }
      LY.dividerBoxes(S).forEach(([x0, y0, x1, y1]) => {
        box(arr, Math.max(x0, g.innerWall), Math.max(y0, g.innerWall), w, Math.min(x1, W - g.innerWall), Math.min(y1, D - g.innerWall), Math.min(g.dividerTop, g.lowerHeight), divc);
        if (g.dividerTop > g.lowerHeight) box(arr, Math.max(x0, w), Math.max(y0, w), g.lowerHeight, Math.min(x1, W - w), Math.min(y1, D - w), g.dividerTop, divc);
      });
    }
    if (!mesh) mesh = { buf: gl.createBuffer(), count: 0 };
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(arr), gl.STATIC_DRAW);
    mesh.count = arr.length / 9;
    cam.tx = W / 2; cam.ty = D / 2; cam.tz = S.height / 2 - f.BaseClearance;
    if (!cam.userZoom) cam.dist = 1.35 * Math.hypot(W, D, S.height);
    render3d();
  }
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  function mul(a, b) { const o = new Float32Array(16); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; o[i * 4 + j] = s; } return o; }
  function perspective(fov, asp, n, f) { const t = 1 / Math.tan(fov / 2); return new Float32Array([t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, 2 * f * n / (n - f), 0]); }
  function lookAt(e, c, u) {
    const z = norm([e[0] - c[0], e[1] - c[1], e[2] - c[2]]), x = norm(cross(u, z)), y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, e), -dot(y, e), -dot(z, e), 1]);
  }
  function render3d() {
    if (!gl || !mesh) return;
    const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    cv.width = Math.max(10, Math.round(r.width * dpr)); cv.height = Math.max(10, Math.round(r.height * dpr));
    gl.viewport(0, 0, cv.width, cv.height);
    const bg = (getComputedStyle(document.body).backgroundColor.match(/\d+/g) || [240, 240, 240]).map(Number);
    gl.clearColor(bg[0] / 255, bg[1] / 255, bg[2] / 255, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!mesh.count) return;
    gl.enable(gl.DEPTH_TEST); gl.useProgram(prog);
    const e = [cam.tx + cam.dist * Math.cos(cam.pitch) * Math.sin(cam.yaw), cam.ty - cam.dist * Math.cos(cam.pitch) * Math.cos(cam.yaw), cam.tz + cam.dist * Math.sin(cam.pitch)];
    const mvp = mul(perspective(0.6, cv.width / cv.height, cam.dist * 0.05, cam.dist * 4), lookAt(e, [cam.tx, cam.ty, cam.tz], [0, 0, 1]));
    gl.uniformMatrix4fv(gl.getUniformLocation(prog, 'mvp'), false, mvp);
    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.buf);
    [['p', 0], ['n', 12], ['c', 24]].forEach(([nm, off]) => { const l = gl.getAttribLocation(prog, nm); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 3, gl.FLOAT, false, 36, off); });
    gl.drawArrays(gl.TRIANGLES, 0, mesh.count);
  }
  let orbit = null;
  cv.addEventListener('pointerdown', e => { orbit = [e.clientX, e.clientY, cam.yaw, cam.pitch]; cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing'; });
  cv.addEventListener('pointermove', e => {
    if (!orbit) return;
    cam.yaw = orbit[2] + (e.clientX - orbit[0]) * 0.01;
    cam.pitch = Math.max(-1.45, Math.min(1.5, orbit[3] + (e.clientY - orbit[1]) * 0.01)); render3d();
  });
  const endOrbit = () => { orbit = null; cv.style.cursor = 'grab'; };
  cv.addEventListener('pointerup', endOrbit); cv.addEventListener('pointercancel', endOrbit);
  cv.addEventListener('wheel', e => { e.preventDefault(); cam.userZoom = true; cam.dist *= Math.exp(e.deltaY * 0.0012); render3d(); }, { passive: false });
  cv.addEventListener('dblclick', () => { cam.yaw = -0.65; cam.pitch = 0.62; cam.userZoom = false; rebuildMesh(); });

  // -------------------------------------------------------- Fusion bridge
  const bridgeReady = () => typeof adsk !== 'undefined' && adsk && typeof adsk.fusionSendData === 'function';
  let connected = false, activeInfo = null, busyFlag = false;
  function send(action, payload) {
    if (!bridgeReady()) return Promise.resolve({ ok: false, error: 'Not connected to Fusion (preview mode).' });
    return Promise.resolve(adsk.fusionSendData(action, JSON.stringify(payload || {})))
      .then(r => { try { return r ? JSON.parse(r) : { ok: false, error: 'Fusion sent an empty reply.' }; } catch (e) { return { ok: false, error: String(r) }; } });
  }
  window.fusionJavaScriptHandler = {
    handle(action, data) {
      try {
        const d = data ? JSON.parse(data) : {};
        if (action === 'result') showResult(d);
        else if (action === 'activeChanged') applyActiveInfo(d);
      } catch (e) { status('Unexpected message from Fusion: ' + e, 'err'); }
      return 'OK';
    }
  };
  function status(msg, cls) { const s = $('status'); s.textContent = msg; s.className = cls || ''; }
  function updateButtons() {
    const isBin = !!(activeInfo && activeInfo.isBin), valid = !errors.length;
    $('btnCreate').disabled = busyFlag || !valid || !connected;
    $('btnUpdate').disabled = busyFlag || !valid || !isBin;
    ['btnStl', 'btn3mf', 'btnStep'].forEach(id => { $(id).disabled = busyFlag || !isBin; });
    $('btnCreate').title = connected ? '' : 'Open this window from Fusion to build bins';
    $('btnUpdate').title = isBin ? `Rebuild ${activeInfo.name}` : 'The active document is not a bin made by this tool';
    $('loadActive').disabled = !isBin;
    $('fitFromActive').disabled = !(activeInfo && activeInfo.fit && activeInfo.fit.found && activeInfo.fit.found.length);
  }
  function busy(on) { busyFlag = on; updateButtons(); }
  function showResult(r) {
    busy(false);
    if (r.active) applyActiveInfo(r.active);
    if (!r.ok) { status('Error: ' + r.error, 'err'); return; }
    if (r.summary) {
      const s = r.summary, probs = s.problems || [];
      status(`${r.message || 'Done.'}\n${s.size_mm ? s.size_mm.join(' × ') + ' mm, ' : ''}${s.volume_cm3} cm³ (about ${s.mass_g_pla} g of PLA), ` +
        `${s.compartments} compartment${s.compartments === 1 ? '' : 's'}.` +
        (probs.length ? '\nCheck failed: ' + probs.join('; ') : '\nAll checks passed.'), probs.length ? 'err' : 'ok');
    } else status(r.message || 'Done.', 'ok');
  }
  function run(action, extra) {
    if (errors.length && action !== 'export') { status('Fix the problems listed at the top first.', 'err'); return Promise.resolve(); }
    busy(true); status('Working in Fusion…');
    return send(action, Object.assign({ cfg: cfg() }, extra || {}))
      .then(r => { if (!r.queued) showResult(r); return r; })
      .catch(e => { busy(false); status('Error: ' + e, 'err'); });
  }
  function applyActiveInfo(a) { activeInfo = a || null; updateButtons(); }
  function loadConfig(c, msg) {
    if (!c) return;
    pushUndo();
    S.nx = c.nx; S.ny = c.ny; S.sub = c.sub || 1; S.height = c.height;
    S.walls = c.walls ? clone(c.walls) : { v: [], h: [] };
    S.fit = { ...LY.DEFAULT_FIT, ...(c.fit || {}) }; S.divider = { ...LY.DEFAULT_DIVIDER, ...(c.divider || {}) }; S.name = c.name || '';
    syncInputs(); changed(false); if (msg) status(msg, 'ok');
  }
  let syncTimer = null;
  function scheduleAutoSync() {
    clearTimeout(syncTimer);
    if (!settings.autoUpdate || !(activeInfo && activeInfo.isBin) || errors.length) return;
    syncTimer = setTimeout(() => { if (!busyFlag) run('update'); }, 1200);
  }

  // ------------------------------------------------- layouts & settings
  let layouts = [];
  function drawLayouts() {
    $('layoutList').innerHTML = layouts.length ? layouts.map((l, n) =>
      `<div><span title="${esc(l.name)}">${esc(l.name)} <span class="note">${l.cfg.nx}×${l.cfg.ny}, ${l.cfg.height} mm</span></span>` +
      `<button class="link" data-load="${n}">load</button><button class="link del" data-del="${n}">delete</button></div>`).join('')
      : '<p class="note">No saved layouts yet.</p>';
  }
  function persist(kind) {
    const payload = kind === 'layouts' ? { layouts } : { settings };
    const local = () => { try { localStorage.setItem('sbd.' + kind, JSON.stringify(kind === 'layouts' ? layouts : settings)); } catch (e) { /* storage unavailable */ } };
    if (!connected) return local();
    send(kind === 'layouts' ? 'saveLayouts' : 'saveSettings', payload).then(r => { if (!r.ok) { local(); status('Could not save ' + kind + ': ' + r.error, 'err'); } });
  }

  // --------------------------------------------------------------- wiring
  document.addEventListener('click', e => {
    const t = e.target.closest('button'); if (!t) return;
    if (t.dataset.step) { const [k, d] = t.dataset.step.split(':'); resize(k === 'nx' ? S.nx + Number(d) : S.nx, k === 'ny' ? S.ny + Number(d) : S.ny); }
    else if (t.dataset.sub) setSub(Number(t.dataset.sub));
    else if (t.dataset.h) { pushUndo(); S.height = Number(t.dataset.h); syncInputs(); changed(); }
    else if (t.dataset.preset) { pushUndo(); S.fit = { ...LY.FIT_PRESETS[t.dataset.preset] }; syncInputs(); changed(); status(`Fit values set to the ${t.dataset.preset} preset.`); }
    else if (t.dataset.load) { const l = layouts[Number(t.dataset.load)]; loadConfig(l.cfg, `Loaded "${l.name}".`); }
    else if (t.dataset.del) { const l = layouts.splice(Number(t.dataset.del), 1)[0]; drawLayouts(); persist('layouts'); status(`Deleted "${l.name}".`); }
  });
  $('nx').addEventListener('change', e => resize(e.target.value, S.ny));
  $('ny').addEventListener('change', e => resize(S.nx, e.target.value));
  $('height').addEventListener('change', e => { pushUndo(); S.height = num(e.target.value, S.height); syncInputs(); changed(); });
  $('dThick').addEventListener('change', e => { pushUndo(); S.divider.thickness = num(e.target.value, S.divider.thickness); syncInputs(); changed(); });
  $('dGap').addEventListener('change', e => { pushUndo(); S.divider.topGap = num(e.target.value, S.divider.topGap); syncInputs(); changed(); });
  $('fitRows').addEventListener('change', e => {
    const k = e.target.dataset.fit; if (!k) return;
    pushUndo(); S.fit[k] = num(e.target.value, S.fit[k]); syncInputs(); changed();
  });
  $('fitFromActive').addEventListener('click', () => send('readActive').then(r => {
    if (!r.ok) return status('Error: ' + r.error, 'err');
    const a = r.active; applyActiveInfo(a);
    if (!a.fit || !a.fit.found || !a.fit.found.length) return status(`No bin parameters found in ${a.name || 'the active document'}.`, 'err');
    pushUndo(); Object.assign(S.fit, a.fit.fit);
    if (a.fit.dividerThickness) S.divider.thickness = a.fit.dividerThickness;
    syncInputs(); changed(); status(`Loaded ${a.fit.found.length} fit values from ${a.name}.`, 'ok');
  }));
  $('qApply').addEventListener('click', () => { pushUndo(); S.walls = LY.quickSplit(S, num($('qCols').value, 1), num($('qRows').value, 1)); changed(); });
  $('clearWalls').addEventListener('click', () => { pushUndo(); S.walls = { v: [], h: [] }; changed(); });
  $('everyUnit').addEventListener('click', everyUnit);
  $('undo').addEventListener('click', () => { if (undoStack.length) { redoStack.push(snapshot()); restore(undoStack.pop()); } });
  $('redo').addEventListener('click', () => { if (redoStack.length) { undoStack.push(snapshot()); restore(redoStack.pop()); } });
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT') return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); $(e.shiftKey ? 'redo' : 'undo').click(); }
  });
  $('layoutName').addEventListener('change', e => { S.name = e.target.value.trim(); });
  $('layoutSave').addEventListener('click', () => {
    const name = ($('layoutName').value || '').trim() || `${S.nx}×${S.ny} layout`;
    S.name = name;
    const entry = { name, cfg: clone(cfg()) }, i = layouts.findIndex(l => l.name === name);
    if (i >= 0) layouts[i] = entry; else layouts.push(entry);
    drawLayouts(); persist('layouts'); status(`Saved layout "${name}".`, 'ok');
  });
  $('loadActive').addEventListener('click', () => send('readActive').then(r => {
    if (!r.ok) return status('Error: ' + r.error, 'err');
    applyActiveInfo(r.active);
    if (!r.active.config) return status(`${r.active.name || 'The active document'} has no saved layout.`, 'err');
    loadConfig(r.active.config, `Loaded the layout from ${r.active.name}.`);
  }));
  $('bedSize').addEventListener('change', e => { settings.bedSize = Math.max(50, num(e.target.value, 256)); syncInputs(); updateInfo(); persist('settings'); });
  $('autoSync').addEventListener('change', e => { settings.autoUpdate = e.target.checked; persist('settings'); scheduleAutoSync(); });
  $('btnCreate').addEventListener('click', () => run('create'));
  $('btnUpdate').addEventListener('click', () => run('update'));
  $('btnStl').addEventListener('click', () => run('export', { fmt: 'stl' }));
  $('btn3mf').addEventListener('click', () => run('export', { fmt: '3mf' }));
  $('btnStep').addEventListener('click', () => run('export', { fmt: 'step' }));
  let resizeTimer = null;
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { drawEditor(); render3d(); }, 50); });

  // ----------------------------------------------------------------- init
  function init() {
    syncInputs(); changed(false); drawLayouts();
    let tries = 0;
    (function connect() {
      if (bridgeReady()) {
        connected = true;
        send('init').then(r => {
          if (!r.ok) return status('Error: ' + r.error, 'err');
          $('ver').textContent = r.version ? 'v' + r.version : '';
          layouts = Array.isArray(r.layouts) ? r.layouts : []; drawLayouts();
          Object.assign(settings, r.settings || {}); syncInputs(); updateInfo();
          applyActiveInfo(r.active);
          status(r.active && r.active.isBin
            ? `Connected. "${r.active.name}" is a designer bin: use "Load from active bin" to edit its layout.`
            : 'Connected to Fusion.', 'ok');
        });
      } else if (tries++ < 50) setTimeout(connect, 100);
      else {
        try { layouts = JSON.parse(localStorage.getItem('sbd.layouts') || '[]'); } catch (e) { layouts = []; }
        try { Object.assign(settings, JSON.parse(localStorage.getItem('sbd.settings') || '{}')); } catch (e) { /* ignore */ }
        syncInputs(); drawLayouts(); updateInfo(); updateButtons();
        status('Preview mode: not running inside Fusion. You can still edit layouts and use the 3D preview.');
      }
    })();
  }
  init();
})();
