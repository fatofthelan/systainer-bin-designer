/* Systainer Bin Designer: layout rules (browser + Node).
 * Mirrors sbd_layout.py exactly; tests/test_parity.py runs both and compares.
 * Units: mm. Origin: front-left corner of the grid footprint, X right, Y back.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SBDLayout = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const FIT_PRESETS = {
    tuned: {
      OneUnit: 24.95, UnitSquarePadding: 1.5, BaseSquareTrim: 2.0, UnitNubWidth: 14.9, UnitNubPadding: 0.0,
      BaseClearance: 5.0, BoxWallThickness: 1.75, RimHeight: 12.0, BoxCornerRadius: 4.0, RimChamferAngle: 60.0
    },
    template: {
      OneUnit: 25.0, UnitSquarePadding: 1.5, BaseSquareTrim: 0.0, UnitNubWidth: 14.5, UnitNubPadding: 0.375,
      BaseClearance: 5.0, BoxWallThickness: 1.75, RimHeight: 14.0, BoxCornerRadius: 4.0, RimChamferAngle: 60.0
    }
  };
  const DEFAULT_FIT = Object.assign({}, FIT_PRESETS.tuned);
  const DEFAULT_DIVIDER = { thickness: 1.1, topGap: 1.75 };
  const DEFAULT_SIZE = { nx: 6, ny: 4, sub: 1, height: 68.0 };
  const LIMITS = { units: [1, 20], height: [10.0, 300.0], dividerThickness: [0.4, 10.0], minFootRing: 0.8, minDividerHeight: 1.0 };

  const key = (a, b) => a + ',' + b;
  const g3 = v => String(Number(v.toPrecision(6)));   // like Python's %g for the values used here

  function chamferHeight(fit) { return fit.UnitSquarePadding * Math.tan(fit.RimChamferAngle * Math.PI / 180); }
  function minHeight(fit) { return fit.BaseClearance + fit.RimHeight + fit.BoxWallThickness + chamferHeight(fit) + 1.0; }

  function derived(cfg) {
    const f = cfg.fit, u = f.OneUnit, bsw = u - 2 * f.UnitSquarePadding - f.BaseSquareTrim;
    return {
      unit: u, step: u / cfg.sub, width: cfg.nx * u, depth: cfg.ny * u,
      lowerHeight: cfg.height - f.BaseClearance - f.RimHeight,
      top: cfg.height - f.BaseClearance,
      innerWall: f.UnitSquarePadding + f.BoxWallThickness,
      dividerTop: cfg.height - f.BaseClearance - cfg.divider.topGap,
      footSize: bsw,
      footRing: (bsw - f.UnitNubWidth - 2 * f.UnitNubPadding) / 2
    };
  }

  function validate(cfg) {
    const errors = [], f = cfg.fit, d = cfg.divider;
    for (const k of ['OneUnit', 'UnitNubWidth', 'BaseClearance', 'BoxWallThickness', 'RimHeight', 'UnitSquarePadding'])
      if (!(f[k] > 0)) errors.push(`${k} must be greater than 0`);
    for (const k of ['UnitNubPadding', 'BaseSquareTrim', 'BoxCornerRadius'])
      if (f[k] < 0) errors.push(`${k} cannot be negative`);
    if (!(f.RimChamferAngle >= 15 && f.RimChamferAngle <= 75)) errors.push('RimChamferAngle must be between 15 and 75 degrees');
    if (errors.length) return errors;
    const g = derived(cfg);
    if (g.footSize <= 0) errors.push('Foot squares have no size: reduce UnitSquarePadding or BaseSquareTrim');
    else if (g.footRing < LIMITS.minFootRing)
      errors.push(`Foot ring wall is ${g.footRing.toFixed(2)} mm; it must be at least ${LIMITS.minFootRing.toFixed(1)} mm (reduce UnitNubWidth/UnitNubPadding)`);
    if (f.BoxCornerRadius * 2 >= g.footSize && g.footSize > 0) errors.push('BoxCornerRadius is too large for the foot squares');
    if (f.BoxWallThickness * 2 >= g.unit - 2 * f.UnitSquarePadding) errors.push('BoxWallThickness is too large for a single unit');
    const [hlo, hhi] = LIMITS.height;
    if (!(cfg.height >= hlo && cfg.height <= hhi)) errors.push(`Height must be between ${g3(hlo)} and ${g3(hhi)} mm`);
    const mh = minHeight(f);
    if (cfg.height < mh) errors.push(`Height ${cfg.height.toFixed(1)} mm is too low; the minimum is ${mh.toFixed(1)} mm with these fit values`);
    const [tlo, thi] = LIMITS.dividerThickness;
    if (!(d.thickness >= tlo && d.thickness <= thi)) errors.push(`Divider thickness must be between ${g3(tlo)} and ${g3(thi)} mm`);
    if (d.topGap < 0) errors.push('Divider top gap cannot be negative');
    if (g.dividerTop - f.BoxWallThickness < LIMITS.minDividerHeight) errors.push('Dividers would not reach above the floor: reduce the divider top gap');
    if (d.thickness >= g.step - 1.0) errors.push('Dividers are too thick for the selected grid');
    return errors;
  }

  // drop out-of-range segments and duplicates; same ordering as Python
  function cleanWalls(cfg) {
    const gx = cfg.nx * cfg.sub, gy = cfg.ny * cfg.sub, v = new Map(), h = new Map();
    for (const [i, j] of cfg.walls.v || []) if (Number.isInteger(i) && Number.isInteger(j) && i > 0 && i < gx && j >= 0 && j < gy) v.set(key(i, j), [i, j]);
    for (const [i, j] of cfg.walls.h || []) if (Number.isInteger(i) && Number.isInteger(j) && j > 0 && j < gy && i >= 0 && i < gx) h.set(key(i, j), [i, j]);
    return {
      v: [...v.values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]),
      h: [...h.values()].sort((a, b) => a[1] - b[1] || a[0] - b[0])
    };
  }

  function dividerRuns(cfg) {
    const out = [];
    for (const axis of ['v', 'h']) {
      const lines = new Map();
      for (const [i, j] of cfg.walls[axis]) {
        const line = axis === 'v' ? i : j, pos = axis === 'v' ? j : i;
        if (!lines.has(line)) lines.set(line, new Set());
        lines.get(line).add(pos);
      }
      for (const line of [...lines.keys()].sort((a, b) => a - b)) {
        const cells = [...lines.get(line)].sort((a, b) => a - b);
        let start = cells[0], prev = cells[0];
        for (let n = 1; n <= cells.length; n++) {
          const c = cells[n];
          if (c !== undefined && c === prev + 1) { prev = c; continue; }
          out.push([axis, line, start, prev + 1]);
          if (c !== undefined) { start = prev = c; }
        }
      }
    }
    return out;
  }

  function dividerBoxes(cfg) {
    const pad = cfg.fit.UnitSquarePadding, t = cfg.divider.thickness, g = derived(cfg), step = g.step;
    const nmax = { v: cfg.ny * cfg.sub, h: cfg.nx * cfg.sub }, full = { v: g.depth, h: g.width };
    return dividerRuns(cfg).map(([axis, line, a, b]) => {
      const c = line * step;
      const lo = a === 0 ? pad : a * step - t / 2;
      const hi = b === nmax[axis] ? full[axis] - pad : b * step + t / 2;
      return axis === 'v' ? [c - t / 2, lo, c + t / 2, hi] : [lo, c - t / 2, hi, c + t / 2];
    });
  }

  const r3 = x => Math.round(x * 1000) / 1000;

  function compartments(cfg) {
    const sub = cfg.sub, gx = cfg.nx * sub, gy = cfg.ny * sub, g = derived(cfg), step = g.step, t = cfg.divider.thickness;
    const v = new Set(cfg.walls.v.map(a => key(a[0], a[1]))), h = new Set(cfg.walls.h.map(a => key(a[0], a[1])));
    const seen = new Set(), out = [];
    for (let i0 = 0; i0 < gx; i0++) for (let j0 = 0; j0 < gy; j0++) {
      if (seen.has(key(i0, j0))) continue;
      const stack = [[i0, j0]], cells = [];
      seen.add(key(i0, j0));
      while (stack.length) {
        const [i, j] = stack.pop();
        cells.push([i, j]);
        const nb = [
          [[i - 1, j], i === 0 || v.has(key(i, j))],
          [[i + 1, j], i === gx - 1 || v.has(key(i + 1, j))],
          [[i, j - 1], j === 0 || h.has(key(i, j))],
          [[i, j + 1], j === gy - 1 || h.has(key(i, j + 1))]
        ];
        for (const [n, blocked] of nb) if (!blocked && !seen.has(key(n[0], n[1]))) { seen.add(key(n[0], n[1])); stack.push(n); }
      }
      cells.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      const xs = cells.map(c => c[0]), ys = cells.map(c => c[1]);
      const b = [Math.min(...xs), Math.min(...ys), Math.max(...xs) + 1, Math.max(...ys) + 1];
      const isRect = (b[2] - b[0]) * (b[3] - b[1]) === cells.length;
      const [ci, cj] = cells[0];
      const x0 = b[0] === 0 ? g.innerWall : b[0] * step + t / 2;
      const x1 = b[2] === gx ? g.width - g.innerWall : b[2] * step - t / 2;
      const y0 = b[1] === 0 ? g.innerWall : b[1] * step + t / 2;
      const y1 = b[3] === gy ? g.depth - g.innerWall : b[3] * step - t / 2;
      out.push({
        cells, bounds: b, isRect,
        probe: [(ci + 0.5) * step + 0.37, (cj + 0.5) * step + 0.29],
        size: [r3(x1 - x0), r3(y1 - y0), r3(g.dividerTop - cfg.fit.BoxWallThickness)]
      });
    }
    return out;
  }

  // even columns x rows, snapped to the grid; returns walls
  function quickSplit(cfg, cols, rows) {
    const gx = cfg.nx * cfg.sub, gy = cfg.ny * cfg.sub;
    cols = Math.max(1, Math.min(gx, cols | 0)); rows = Math.max(1, Math.min(gy, rows | 0));
    const xs = new Set(), ys = new Set(), v = [], h = [];
    for (let k = 1; k < cols; k++) xs.add(Math.round(k * gx / cols));
    for (let k = 1; k < rows; k++) ys.add(Math.round(k * gy / rows));
    xs.forEach(i => { for (let j = 0; j < gy; j++) v.push([i, j]); });
    ys.forEach(j => { for (let i = 0; i < gx; i++) h.push([i, j]); });
    return cleanWalls({ ...cfg, walls: { v, h } });
  }

  return { FIT_PRESETS, DEFAULT_FIT, DEFAULT_DIVIDER, DEFAULT_SIZE, LIMITS, chamferHeight, minHeight, derived, validate,
           cleanWalls, dividerRuns, dividerBoxes, compartments, quickSplit };
});
