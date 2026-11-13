"""Fusion integration test for Systainer Bin Designer.

Run inside Fusion: UTILITIES > Scripts and Add-Ins > "+" (add this script),
or with any tool that executes a Fusion Python script. It builds bins in new
documents, checks them against reference geometry, prints a report and
closes only the documents it created (without saving).

Reference values come from the original parametric template rebuilt with the
"tuned" fit preset at 6 x 5 units, 36.8 mm: 86.0756 cm3, 889.1813 cm2, 584 faces.
"""

import importlib
import os
import sys
import traceback

import adsk.core
import adsk.fusion

HERE = os.path.dirname(os.path.realpath(__file__))
ADDIN = os.path.join(HERE, '..', 'SystainerBinDesigner')
if os.path.isdir(ADDIN) and ADDIN not in sys.path:
    sys.path.insert(0, ADDIN)

REF_BASE = {'volume': 86.0756, 'area': 889.1813, 'faces': 584}
REF_DIVIDERS = 12.6297
TOL = 1e-3


def _check(results, name, ok, detail=''):
    results.append((name, bool(ok), detail))


def run_tests(app):
    import sbd_layout as L
    import sbd_builder as B
    importlib.reload(L)
    importlib.reload(B)
    results, created = [], []
    try:
        # 1. base bin vs the template reference
        cfg = L.normalize({'nx': 6, 'ny': 5, 'height': 36.8, 'walls': {'v': [], 'h': []}})
        doc, rep = B.create_bin(app, cfg)
        created.append(doc)
        body = adsk.fusion.Design.cast(app.activeProduct).rootComponent.bRepBodies.item(0)
        _check(results, 'base: no verification problems', not rep['problems'], rep['problems'])
        _check(results, 'base: volume %.4f cm3' % body.volume, abs(body.volume - REF_BASE['volume']) < TOL)
        _check(results, 'base: area %.4f cm2' % body.area, abs(body.area - REF_BASE['area']) < TOL)
        _check(results, 'base: %d faces' % body.faces.count, body.faces.count == REF_BASE['faces'])

        # 2. in-place update with T, L, cross and dangling dividers
        design = adsk.fusion.Design.cast(app.activeProduct)
        walls = {'v': [[2, j] for j in range(5)] + [[4, j] for j in range(3)] + [[5, 4]],
                 'h': [[i, 3] for i in range(6)] + [[2, 1], [3, 1]]}
        rep = B.update_bin(design, dict(cfg, walls=walls))
        _check(results, 'dividers: no verification problems', not rep['problems'], rep['problems'])
        added = rep['volume_cm3'] - REF_BASE['volume']
        _check(results, 'dividers: added volume %.4f cm3' % added, abs(added - REF_DIVIDERS) < TOL)
        _check(results, 'dividers: 6 compartments', rep['compartments'] == 6)

        # 3. resize + half grid + different divider settings, in place
        walls2 = {'v': [[4, j] for j in range(6)] + [[2, j] for j in range(3)] + [[6, j] for j in range(3, 6)],
                  'h': [[i, 3] for i in range(4)] + [[i, 2] for i in range(4, 8)]}
        rep = B.update_bin(design, {'nx': 4, 'ny': 3, 'sub': 2, 'height': 68, 'walls': walls2,
                                    'divider': {'thickness': 1.2, 'topGap': 3}})
        _check(results, 'resize: no verification problems', not rep['problems'], rep['problems'])
        _check(results, 'resize: size %s' % rep.get('size_mm'), rep.get('size_mm') == [99.8, 74.85, 68.0])

        # 4. template preset, 1 x 1, no dividers
        doc2, rep = B.create_bin(app, {'nx': 1, 'ny': 1, 'height': 68, 'fit': L.FIT_PRESETS['template']})
        created.append(doc2)
        _check(results, 'template 1x1: no verification problems', not rep['problems'], rep['problems'])
        _check(results, 'template 1x1: size %s' % rep.get('size_mm'), rep.get('size_mm') == [25.0, 25.0, 68.0])

        # 5. invalid input is rejected before anything is built
        try:
            B.create_bin(app, {'height': 15})
            _check(results, 'invalid height rejected', False, 'no error raised')
        except L.LayoutError as e:
            _check(results, 'invalid height rejected', True, e.errors[0])
    except Exception:
        _check(results, 'unexpected exception', False, traceback.format_exc())
    finally:
        for d in created:
            try:
                d.close(False)
            except Exception:
                pass
    return results


def run(context):
    app = adsk.core.Application.get()
    results = run_tests(app)
    lines = ['%s  %s%s' % ('PASS' if ok else 'FAIL', name, ('  ' + str(detail)) if (detail and not ok) else '')
             for name, ok, detail in results]
    failed = sum(1 for _, ok, _ in results if not ok)
    report = '\n'.join(lines + ['', '%d checks, %d failed' % (len(results), failed)])
    print(report)
    app.userInterface.messageBox(report, 'Systainer Bin Designer tests')
