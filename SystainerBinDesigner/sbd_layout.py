"""Layout model for Systainer Bin Designer.

Pure Python with no Fusion imports, so it can be unit-tested anywhere. The
palette's palette/layout.js implements the same rules; tests/test_parity.py
checks that both give identical results.

Coordinates: millimetres, origin at the front-left corner of the bin's grid
footprint, X to the right, Y to the back, Z up (floor bottom at Z = 0).

Walls are stored on a sub-grid (1 or 2 cells per organizer unit):
  walls['v'] = [[i, j], ...]  vertical segment on grid line x = i, spanning cell row j
  walls['h'] = [[i, j], ...]  horizontal segment on grid line y = j, spanning cell column i
"""

import math

SCHEMA_VERSION = 1

# Fit presets. "tuned" is the default: adjusted from the original template
# through test prints (slightly smaller pitch, larger nub opening, lower rim).
FIT_PRESETS = {
    'tuned': {
        'OneUnit': 24.95,
        'UnitSquarePadding': 1.5,
        'BaseSquareTrim': 2.0,
        'UnitNubWidth': 14.9,
        'UnitNubPadding': 0.0,
        'BaseClearance': 5.0,
        'BoxWallThickness': 1.75,
        'RimHeight': 12.0,
        'BoxCornerRadius': 4.0,
        'RimChamferAngle': 60.0,
    },
    'template': {  # values of the original parametric template (Heyus, Printables 208217)
        'OneUnit': 25.0,
        'UnitSquarePadding': 1.5,
        'BaseSquareTrim': 0.0,
        'UnitNubWidth': 14.5,
        'UnitNubPadding': 0.375,
        'BaseClearance': 5.0,
        'BoxWallThickness': 1.75,
        'RimHeight': 14.0,
        'BoxCornerRadius': 4.0,
        'RimChamferAngle': 60.0,
    },
}
DEFAULT_FIT = dict(FIT_PRESETS['tuned'])
DEFAULT_DIVIDER = {'thickness': 1.1, 'topGap': 1.75}
DEFAULT_SIZE = {'nx': 6, 'ny': 4, 'sub': 1, 'height': 68.0}

LIMITS = {
    'units': (1, 20),
    'height': (10.0, 300.0),
    'dividerThickness': (0.4, 10.0),
    'minFootRing': 0.8,      # thinnest printable foot ring wall
    'minDividerHeight': 1.0,  # dividers must stand at least this far above the floor
}


class LayoutError(ValueError):
    """Raised when a configuration cannot be built. .errors lists every problem."""

    def __init__(self, errors):
        super().__init__('; '.join(errors))
        self.errors = list(errors)


def _f(value, name, errors):
    try:
        v = float(value)
    except (TypeError, ValueError):
        errors.append('%s must be a number' % name)
        return None
    if not math.isfinite(v):
        errors.append('%s must be a finite number' % name)
        return None
    return v


def _i(value, name, errors):
    try:
        v = float(value)
    except (TypeError, ValueError):
        errors.append('%s must be a whole number' % name)
        return None
    if not math.isfinite(v) or v != int(v):
        errors.append('%s must be a whole number' % name)
        return None
    return int(v)


def chamfer_height(fit):
    """Vertical leg of the chamfer under the rim overhang."""
    return fit['UnitSquarePadding'] * math.tan(math.radians(fit['RimChamferAngle']))


def min_height(fit):
    """Lowest BoxHeight for which the rim, its chamfer and the floor still fit."""
    return fit['BaseClearance'] + fit['RimHeight'] + fit['BoxWallThickness'] + chamfer_height(fit) + 1.0


def derived(cfg):
    """Frequently used dimensions (mm) of a normalized configuration."""
    f = cfg['fit']
    u = f['OneUnit']
    bsw = u - 2 * f['UnitSquarePadding'] - f['BaseSquareTrim']
    return {
        'unit': u,
        'step': u / cfg['sub'],
        'width': cfg['nx'] * u,
        'depth': cfg['ny'] * u,
        'lowerHeight': cfg['height'] - f['BaseClearance'] - f['RimHeight'],
        'top': cfg['height'] - f['BaseClearance'],
        'innerWall': f['UnitSquarePadding'] + f['BoxWallThickness'],
        'dividerTop': cfg['height'] - f['BaseClearance'] - cfg['divider']['topGap'],
        'footSize': bsw,
        'footRing': (bsw - f['UnitNubWidth'] - 2 * f['UnitNubPadding']) / 2,
    }


def validate(cfg):
    """Return a list of human-readable problems for a normalized config (empty = OK)."""
    errors = []
    f, d = cfg['fit'], cfg['divider']
    positive = ('OneUnit', 'UnitNubWidth', 'BaseClearance', 'BoxWallThickness', 'RimHeight', 'UnitSquarePadding')
    for k in positive:
        if f[k] <= 0:
            errors.append('%s must be greater than 0' % k)
    for k in ('UnitNubPadding', 'BaseSquareTrim', 'BoxCornerRadius'):
        if f[k] < 0:
            errors.append('%s cannot be negative' % k)
    if not 15 <= f['RimChamferAngle'] <= 75:
        errors.append('RimChamferAngle must be between 15 and 75 degrees')
    if errors:
        return errors
    g = derived(cfg)
    if g['footSize'] <= 0:
        errors.append('Foot squares have no size: reduce UnitSquarePadding or BaseSquareTrim')
    elif g['footRing'] < LIMITS['minFootRing']:
        errors.append('Foot ring wall is %.2f mm; it must be at least %.1f mm (reduce UnitNubWidth/UnitNubPadding)'
                      % (g['footRing'], LIMITS['minFootRing']))
    if f['BoxCornerRadius'] * 2 >= g['footSize'] > 0:
        errors.append('BoxCornerRadius is too large for the foot squares')
    if f['BoxWallThickness'] * 2 >= g['unit'] - 2 * f['UnitSquarePadding']:
        errors.append('BoxWallThickness is too large for a single unit')
    lo, hi = LIMITS['height']
    if not lo <= cfg['height'] <= hi:
        errors.append('Height must be between %g and %g mm' % (lo, hi))
    mh = min_height(f)
    if cfg['height'] < mh:
        errors.append('Height %.1f mm is too low; the minimum is %.1f mm with these fit values' % (cfg['height'], mh))
    lo, hi = LIMITS['dividerThickness']
    if not lo <= d['thickness'] <= hi:
        errors.append('Divider thickness must be between %g and %g mm' % (lo, hi))
    if d['topGap'] < 0:
        errors.append('Divider top gap cannot be negative')
    if g['dividerTop'] - f['BoxWallThickness'] < LIMITS['minDividerHeight']:
        errors.append('Dividers would not reach above the floor: reduce the divider top gap')
    if d['thickness'] >= g['step'] - 1.0:
        errors.append('Dividers are too thick for the selected grid')
    return errors


def normalize(cfg, check=True):
    """Fill defaults, coerce types, drop out-of-range wall segments.

    Raises LayoutError with all problems when check is True and the result is not buildable.
    """
    cfg = dict(cfg or {})
    errors = []
    fit = dict(DEFAULT_FIT)
    for k, v in (cfg.get('fit') or {}).items():
        if k in DEFAULT_FIT:
            val = _f(v, k, errors)
            if val is not None:
                fit[k] = val
    div = dict(DEFAULT_DIVIDER)
    for k, v in (cfg.get('divider') or {}).items():
        if k in DEFAULT_DIVIDER:
            val = _f(v, 'divider ' + k, errors)
            if val is not None:
                div[k] = val
    lo, hi = LIMITS['units']
    nx = _i(cfg.get('nx', DEFAULT_SIZE['nx']), 'Width (units)', errors)
    ny = _i(cfg.get('ny', DEFAULT_SIZE['ny']), 'Depth (units)', errors)
    for name, v in (('Width (units)', nx), ('Depth (units)', ny)):
        if v is not None and not lo <= v <= hi:
            errors.append('%s must be between %d and %d' % (name, lo, hi))
    sub = _i(cfg.get('sub', 1), 'Grid subdivision', errors)
    if sub not in (1, 2):
        errors.append('Grid subdivision must be 1 or 2')
    height = _f(cfg.get('height', DEFAULT_SIZE['height']), 'Height', errors)
    if errors:
        raise LayoutError(errors)
    assert nx is not None and ny is not None and sub is not None and height is not None

    walls = cfg.get('walls') or {}
    gx, gy = nx * sub, ny * sub

    def segs(items, ok):
        out = set()
        for item in items or []:
            try:
                i, j = int(item[0]), int(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if ok(i, j):
                out.add((i, j))
        return out

    v = segs(walls.get('v'), lambda i, j: 0 < i < gx and 0 <= j < gy)
    h = segs(walls.get('h'), lambda i, j: 0 < j < gy and 0 <= i < gx)
    out = {
        'schema': SCHEMA_VERSION,
        'nx': nx, 'ny': ny, 'sub': sub, 'height': height,
        'walls': {'v': [list(a) for a in sorted(v)], 'h': [list(a) for a in sorted(h, key=lambda a: (a[1], a[0]))]},
        'fit': fit, 'divider': div,
        'name': str(cfg.get('name', '') or '')[:120],
    }
    if check:
        problems = validate(out)
        if problems:
            raise LayoutError(problems)
    return out


def divider_runs(cfg):
    """Merge wall segments into straight runs: (axis, line, start_cell, end_cell) in sub-grid steps."""
    runs = []
    for axis in ('v', 'h'):
        lines = {}
        for i, j in cfg['walls'][axis]:
            line, pos = (i, j) if axis == 'v' else (j, i)
            lines.setdefault(line, []).append(pos)
        for line in sorted(lines):
            cells = sorted(set(lines[line]))
            start = prev = cells[0]
            for c in cells[1:] + [None]:
                if c is not None and c == prev + 1:
                    prev = c
                    continue
                runs.append((axis, line, start, prev + 1))
                if c is not None:
                    start = prev = c
    return runs


def divider_boxes(cfg):
    """Divider footprints (x0, y0, x1, y1) in mm.

    Runs that reach the bin edge stop at the outer face of the lower wall
    (UnitSquarePadding), so they fuse into both the lower wall and the wider rim.
    Interior ends are extended by half a thickness so T and L junctions are solid.
    """
    f = cfg['fit']
    pad, t = f['UnitSquarePadding'], cfg['divider']['thickness']
    g = derived(cfg)
    step = g['step']
    nmax = {'v': cfg['ny'] * cfg['sub'], 'h': cfg['nx'] * cfg['sub']}
    full = {'v': g['depth'], 'h': g['width']}
    out = []
    for axis, line, a, b in divider_runs(cfg):
        c = line * step
        lo = pad if a == 0 else a * step - t / 2
        hi = full[axis] - pad if b == nmax[axis] else b * step + t / 2
        out.append((c - t / 2, lo, c + t / 2, hi) if axis == 'v' else (lo, c - t / 2, hi, c + t / 2))
    return out


def compartments(cfg):
    """Connected groups of sub-grid cells separated by walls.

    Returns dicts: cells, bounds (i0, j0, i1, j1), isRect, probe (an interior point in mm),
    and size (w, d, h) in mm for rectangular compartments.
    """
    sub = cfg['sub']
    gx, gy = cfg['nx'] * sub, cfg['ny'] * sub
    g = derived(cfg)
    step, t = g['step'], cfg['divider']['thickness']
    v = {tuple(a) for a in cfg['walls']['v']}
    h = {tuple(a) for a in cfg['walls']['h']}
    seen, out = set(), []
    for i0 in range(gx):
        for j0 in range(gy):
            if (i0, j0) in seen:
                continue
            stack, cells = [(i0, j0)], []
            seen.add((i0, j0))
            while stack:
                i, j = stack.pop()
                cells.append((i, j))
                for n, blocked in (((i - 1, j), i == 0 or (i, j) in v),
                                   ((i + 1, j), i == gx - 1 or (i + 1, j) in v),
                                   ((i, j - 1), j == 0 or (i, j) in h),
                                   ((i, j + 1), j == gy - 1 or (i, j + 1) in h)):
                    if not blocked and n not in seen:
                        seen.add(n)
                        stack.append(n)
            cells.sort()
            xs, ys = [c[0] for c in cells], [c[1] for c in cells]
            b = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
            is_rect = (b[2] - b[0]) * (b[3] - b[1]) == len(cells)
            ci, cj = cells[0]
            comp = {
                'cells': cells, 'bounds': b, 'isRect': is_rect,
                # centre of a member cell, nudged off any grid line
                'probe': ((ci + 0.5) * step + 0.37, (cj + 0.5) * step + 0.29),
            }
            x0 = g['innerWall'] if b[0] == 0 else b[0] * step + t / 2
            x1 = g['width'] - g['innerWall'] if b[2] == gx else b[2] * step - t / 2
            y0 = g['innerWall'] if b[1] == 0 else b[1] * step + t / 2
            y1 = g['depth'] - g['innerWall'] if b[3] == gy else b[3] * step - t / 2
            comp['size'] = (round(x1 - x0, 3), round(y1 - y0, 3), round(g['dividerTop'] - cfg['fit']['BoxWallThickness'], 3))
            out.append(comp)
    return out


def label(cfg):
    return 'Systainer bin %dx%d h%g' % (cfg['nx'], cfg['ny'], cfg['height'])


def file_stem(cfg):
    stem = 'systainer-bin-%dx%d-h%g' % (cfg['nx'], cfg['ny'], cfg['height'])
    name = ''.join(ch if ch.isalnum() else '-' for ch in (cfg.get('name') or '').lower())
    while '--' in name:
        name = name.replace('--', '-')
    name = name.strip('-')[:40]
    return stem + ('-' + name if name else '')
