"""Check that palette/layout.js and sbd_layout.py agree on every rule.

Needs Node.js; the test is skipped when `node` is not on PATH.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'SystainerBinDesigner'))

import sbd_layout as L  # noqa: E402

NODE_SCRIPT = r"""
const LY = require(process.argv[process.argv.length - 1]);
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(c => ({
  derived: LY.derived(c), validate: LY.validate(c), runs: LY.dividerRuns(c),
  boxes: LY.dividerBoxes(c), compartments: LY.compartments(c), minHeight: LY.minHeight(c.fit),
  clean: LY.cleanWalls(c)
}));
process.stdout.write(JSON.stringify(out));
"""


def random_cases(n, seed=1234):
    rng = random.Random(seed)
    cases = []
    for k in range(n):
        nx, ny, sub = rng.randint(1, 9), rng.randint(1, 7), rng.choice((1, 2))
        gx, gy = nx * sub, ny * sub
        density = rng.random()
        v = [[i, j] for i in range(1, gx) for j in range(gy) if rng.random() < density * 0.6]
        h = [[i, j] for j in range(1, gy) for i in range(gx) if rng.random() < density * 0.6]
        fit = dict(rng.choice(list(L.FIT_PRESETS.values())))
        if k % 5 == 0:
            fit['UnitNubWidth'] += rng.uniform(-1, 4)   # sometimes invalid on purpose
        height = rng.choice((22.0, 36.8, 50.0, 68.0, 120.0))
        div = {'thickness': rng.choice((0.3, 0.8, 1.1, 1.6, 2.4)), 'topGap': rng.choice((0.0, 1.75, 5.0, 40.0))}
        cases.append(L.normalize({'nx': nx, 'ny': ny, 'sub': sub, 'height': height,
                                  'walls': {'v': v, 'h': h}, 'fit': fit, 'divider': div}, check=False))
    return cases


def close(a, b, path=''):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            raise AssertionError('%s: length %d != %d' % (path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            close(x, y, '%s[%d]' % (path, i))
    elif isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            raise AssertionError('%s: keys %s != %s' % (path, sorted(a), sorted(b)))
        for k in a:
            close(a[k], b[k], '%s.%s' % (path, k))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > 1e-6:
            raise AssertionError('%s: %r != %r' % (path, a, b))
    elif a != b:
        raise AssertionError('%s: %r != %r' % (path, a, b))


@unittest.skipIf(shutil.which('node') is None, 'node is not installed')
class ParityTests(unittest.TestCase):
    def test_python_and_javascript_agree(self):
        cases = random_cases(300)
        js_path = os.path.join(ROOT, 'SystainerBinDesigner', 'palette', 'layout.js')
        res = subprocess.run(['node', '-e', NODE_SCRIPT, js_path], input=json.dumps(cases),
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        js = json.loads(res.stdout)
        self.assertEqual(len(js), len(cases))
        n_invalid = 0
        for idx, (c, j) in enumerate(zip(cases, js)):
            py = {
                'derived': L.derived(c), 'validate': L.validate(c), 'runs': [list(r) for r in L.divider_runs(c)],
                'boxes': [list(b) for b in L.divider_boxes(c)], 'minHeight': L.min_height(c['fit']),
                'compartments': [{'cells': [list(x) for x in comp['cells']], 'bounds': list(comp['bounds']),
                                  'isRect': comp['isRect'], 'probe': list(comp['probe']), 'size': list(comp['size'])}
                                 for comp in L.compartments(c)],
                'clean': c['walls'],
            }
            n_invalid += bool(py['validate'])
            try:
                close(py, j)
            except AssertionError as e:
                self.fail('case %d differs: %s\nconfig: %s' % (idx, e, json.dumps(c)))
        self.assertGreater(n_invalid, 10, 'the random cases should include invalid configurations')


if __name__ == '__main__':
    unittest.main()
