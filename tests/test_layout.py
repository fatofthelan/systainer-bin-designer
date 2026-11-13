"""Unit tests for the layout rules (no Fusion needed).

Run from the repository root:  python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'SystainerBinDesigner'))

import sbd_layout as L  # noqa: E402


def cfg(**kw):
    base = {'nx': 6, 'ny': 5, 'sub': 1, 'height': 36.8, 'walls': {'v': [], 'h': []}}
    base.update(kw)
    return L.normalize(base)


def union_area(rects):
    xs = sorted({r[0] for r in rects} | {r[2] for r in rects})
    ys = sorted({r[1] for r in rects} | {r[3] for r in rects})
    area = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rects):
                area += (x1 - x0) * (y1 - y0)
    return area


class NormalizeTests(unittest.TestCase):
    def test_defaults(self):
        c = L.normalize({})
        self.assertEqual((c['nx'], c['ny'], c['sub'], c['height']), (6, 4, 1, 68.0))
        self.assertEqual(c['fit'], L.FIT_PRESETS['tuned'])
        self.assertEqual(c['schema'], L.SCHEMA_VERSION)

    def test_out_of_range_and_duplicate_walls_are_dropped(self):
        c = cfg(walls={'v': [[0, 0], [6, 0], [3, 5], [3, 1], [3, 1], ['x', 2]], 'h': [[0, 0], [0, 5], [6, 2], [2, 2]]})
        self.assertEqual(c['walls'], {'v': [[3, 1]], 'h': [[2, 2]]})

    def test_type_errors_are_collected(self):
        with self.assertRaises(L.LayoutError) as ctx:
            L.normalize({'nx': 'abc', 'ny': 2.5, 'height': 'tall', 'fit': {'OneUnit': 'x'}})
        msgs = ' | '.join(ctx.exception.errors)
        for word in ('Width', 'Depth', 'Height', 'OneUnit'):
            self.assertIn(word, msgs)

    def test_unit_limits(self):
        with self.assertRaises(L.LayoutError):
            L.normalize({'nx': 0})
        with self.assertRaises(L.LayoutError):
            L.normalize({'ny': 21})

    def test_name_is_truncated(self):
        self.assertEqual(len(cfg(name='x' * 500)['name']), 120)


class ValidateTests(unittest.TestCase):
    def test_tuned_and_template_presets_are_valid(self):
        for preset in L.FIT_PRESETS.values():
            self.assertEqual(L.validate(L.normalize({'fit': preset}, check=False)), [])

    def test_too_low(self):
        c = L.normalize({'height': 20}, check=False)
        self.assertTrue(any('too low' in e for e in L.validate(c)))

    def test_min_height_formula(self):
        f = L.FIT_PRESETS['tuned']
        self.assertAlmostEqual(L.min_height(f), 5 + 12 + 1.75 + 1.5 * 3 ** 0.5 + 1, places=9)

    def test_thin_foot_ring(self):
        c = L.normalize({'fit': {'UnitNubWidth': 19.0}}, check=False)
        self.assertTrue(any('Foot ring' in e for e in L.validate(c)))

    def test_divider_limits(self):
        self.assertTrue(L.validate(L.normalize({'divider': {'thickness': 0.2}}, check=False)))
        self.assertTrue(L.validate(L.normalize({'divider': {'topGap': -1}}, check=False)))
        self.assertTrue(L.validate(L.normalize({'height': 36.8, 'divider': {'topGap': 30}}, check=False)))

    def test_bad_angle(self):
        self.assertTrue(L.validate(L.normalize({'fit': {'RimChamferAngle': 89}}, check=False)))

    def test_normalize_raises_with_all_problems(self):
        with self.assertRaises(L.LayoutError) as ctx:
            L.normalize({'height': 15, 'divider': {'thickness': 0.1}})
        self.assertGreaterEqual(len(ctx.exception.errors), 2)


class GeometryTests(unittest.TestCase):
    def test_derived_matches_reference_bin(self):
        g = L.derived(cfg())
        self.assertAlmostEqual(g['width'], 149.7)
        self.assertAlmostEqual(g['depth'], 124.75)
        self.assertAlmostEqual(g['lowerHeight'], 19.8)
        self.assertAlmostEqual(g['footSize'], 19.95)
        self.assertAlmostEqual(g['footRing'], 2.525)
        self.assertAlmostEqual(g['dividerTop'], 30.05)

    def test_runs_merge_collinear_segments(self):
        c = cfg(walls={'v': [[2, 0], [2, 1], [2, 3], [4, 4]], 'h': [[0, 3], [1, 3], [2, 3], [5, 1]]})
        self.assertEqual(L.divider_runs(c), [('v', 2, 0, 2), ('v', 2, 3, 4), ('v', 4, 4, 5), ('h', 1, 5, 6), ('h', 3, 0, 3)])

    def test_boxes_reach_into_walls_and_extend_at_junctions(self):
        c = cfg(walls={'v': [[2, j] for j in range(5)], 'h': [[0, 2], [1, 2]]})
        (vx0, vy0, vx1, vy1), (hx0, hy0, hx1, hy1) = L.divider_boxes(c)
        self.assertAlmostEqual(vx1 - vx0, 1.1)
        self.assertAlmostEqual(vy0, 1.5)              # stops at the lower wall's outer face
        self.assertAlmostEqual(vy1, 124.75 - 1.5)
        self.assertAlmostEqual(hx0, 1.5)
        self.assertAlmostEqual(hx1, 2 * 24.95 + 0.55)  # half a thickness into the vertical divider

    def test_reference_divider_volume(self):
        """Same layout as the Fusion check: the added volume must be 12.6297 cm3."""
        c = cfg(walls={'v': [[2, j] for j in range(5)] + [[4, j] for j in range(3)] + [[5, 4]],
                       'h': [[i, 3] for i in range(6)] + [[2, 1], [3, 1]]})
        g, f = L.derived(c), c['fit']
        boxes = L.divider_boxes(c)

        def clip(b):
            out = []
            for r in boxes:
                q = (max(r[0], b[0]), max(r[1], b[1]), min(r[2], b[2]), min(r[3], b[3]))
                if q[0] < q[2] and q[1] < q[3]:
                    out.append(q)
            return out
        iw, w = g['innerWall'], f['BoxWallThickness']
        low = union_area(clip((iw, iw, g['width'] - iw, g['depth'] - iw))) * (g['lowerHeight'] - w)
        up = union_area(clip((w, w, g['width'] - w, g['depth'] - w))) * (g['dividerTop'] - g['lowerHeight'])
        self.assertAlmostEqual((low + up) / 1000, 12.6297, places=4)


class CompartmentTests(unittest.TestCase):
    def test_empty_bin_is_one_compartment(self):
        comps = L.compartments(cfg())
        self.assertEqual(len(comps), 1)
        self.assertTrue(comps[0]['isRect'])
        self.assertAlmostEqual(comps[0]['size'][0], 149.7 - 2 * 3.25)

    def test_three_by_two(self):
        c = cfg(walls={'v': [[2, j] for j in range(5)] + [[4, j] for j in range(5)], 'h': [[i, 3] for i in range(6)]})
        comps = L.compartments(c)
        self.assertEqual(len(comps), 6)
        sizes = sorted(round(x['size'][0], 2) for x in comps)
        self.assertEqual(sizes, [46.1, 46.1, 46.1, 46.1, 48.8, 48.8])

    def test_dangling_wall_does_not_split(self):
        c = cfg(walls={'v': [[3, 0], [3, 1]], 'h': []})
        comps = L.compartments(c)
        self.assertEqual(len(comps), 1)
        self.assertFalse(comps[0]['isRect'] is False and len(comps[0]['cells']) != 30)

    def test_enclosed_pocket(self):
        c = cfg(walls={'v': [[2, 2], [3, 2]], 'h': [[2, 2], [2, 3]]})
        comps = L.compartments(c)
        self.assertEqual(len(comps), 2)
        self.assertEqual(sorted(len(x['cells']) for x in comps), [1, 29])
        self.assertTrue(any(not x['isRect'] for x in comps))

    def test_half_grid_probe_is_inside_cell(self):
        c = cfg(sub=2, walls={'v': [[3, j] for j in range(10)], 'h': []})
        step = L.derived(c)['step']
        for comp in L.compartments(c):
            x, y = comp['probe']
            i, j = comp['cells'][0]
            self.assertTrue(i * step < x < (i + 1) * step and j * step < y < (j + 1) * step)


class NamingTests(unittest.TestCase):
    def test_file_stem(self):
        self.assertEqual(L.file_stem(cfg(name='M3 Screws / short!')), 'systainer-bin-6x5-h36.8-m3-screws-short')
        self.assertEqual(L.file_stem(cfg()), 'systainer-bin-6x5-h36.8')


if __name__ == '__main__':
    unittest.main()
