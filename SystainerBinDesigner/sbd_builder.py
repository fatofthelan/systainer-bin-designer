"""Fusion geometry for Systainer Bin Designer.

Base bin  = parametric features driven by user parameters that use the same
            names as the original template (NumUnitsX, OneUnit, BoxHeight, ...),
            so the bin still responds to Modify > Change Parameters.
Dividers  = one exact union body (a base feature) generated from the layout and
            joined in the last feature. The designer regenerates both on update.

Fusion's internal length unit is the centimetre; this module works in mm and
converts at the API boundary.
"""

import json
import math
import os

import adsk.core
import adsk.fusion

import sbd_layout as L

ATTR_GROUP = 'SystainerBinDesigner'
ATTR_CONFIG = 'config'
BIN_BODY = 'SystainerBin'
TAIL_FEATURES = ('SBD Final Join', 'SBD Dividers')


class BuildError(RuntimeError):
    pass


# ----------------------------------------------------------------- helpers
def _vi(expr):
    return adsk.core.ValueInput.createByString(expr)


def _p(x_mm, y_mm, z_mm=0.0):
    return adsk.core.Point3D.create(x_mm / 10.0, y_mm / 10.0, z_mm / 10.0)


def _coll(items):
    c = adsk.core.ObjectCollection.create()
    for i in items:
        c.add(i)
    return c


def _mm(design, name):
    p = design.userParameters.itemByName(name)
    if p is None:
        raise BuildError('user parameter %s is missing' % name)
    return p.value * 10.0


def _num(design, name):
    p = design.userParameters.itemByName(name)
    if p is None:
        raise BuildError('user parameter %s is missing' % name)
    return p.value


def _inside(body, x, y, z):
    return body.pointContainment(_p(x, y, z)) == adsk.fusion.PointContainment.PointInsidePointContainment


# ------------------------------------------------------------- parameters
def _param_table(cfg):
    f, d = cfg['fit'], cfg['divider']
    mm = lambda v: '%g mm' % v  # noqa: E731
    return [
        ('NumUnitsX', str(cfg['nx']), '', 'Bin width in organizer grid units'),
        ('NumUnitsY', str(cfg['ny']), '', 'Bin depth in organizer grid units'),
        ('OneUnit', mm(f['OneUnit']), 'mm', 'Organizer grid pitch'),
        ('UnitSquarePadding', mm(f['UnitSquarePadding']), 'mm', 'Footprint edge to lower outer wall'),
        ('BaseSquareTrim', mm(f['BaseSquareTrim']), 'mm', 'Extra reduction of each foot square'),
        ('BaseSquareWidth', '( OneUnit - 2 * UnitSquarePadding ) - BaseSquareTrim', 'mm', 'Foot square size'),
        ('UnitNubWidth', mm(f['UnitNubWidth']), 'mm', 'Opening in each foot for the organizer floor nub'),
        ('UnitNubPadding', mm(f['UnitNubPadding']), 'mm', 'Extra clearance per side around the nub'),
        ('BaseWallThickness', '( BaseSquareWidth - ( UnitNubWidth + 2 * UnitNubPadding ) ) / 2', 'mm', 'Foot ring wall'),
        ('BaseClearance', mm(f['BaseClearance']), 'mm', 'Foot height'),
        ('BoxHeight', mm(cfg['height']), 'mm', 'Overall height, foot bottom to rim top'),
        ('BoxWallThickness', mm(f['BoxWallThickness']), 'mm', 'Wall and floor thickness'),
        ('RimHeight', mm(f['RimHeight']), 'mm', 'Height of the wide top rim'),
        ('BoxCornerRadius', mm(f['BoxCornerRadius']), 'mm', 'Outer corner radius of the lower body and feet'),
        ('RimChamferAngle', '%g deg' % f['RimChamferAngle'], 'deg', 'Chamfer under the rim overhang'),
        ('LowerHeight', 'BoxHeight - BaseClearance - RimHeight', 'mm', 'Floor bottom to the start of the rim'),
        ('DividerWallThickness', mm(d['thickness']), 'mm', 'Divider thickness (press Update in the designer after changing)'),
        ('DividerTopGap', mm(d['topGap']), 'mm', 'Dividers stop this far below the rim top (press Update after changing)'),
    ]


def apply_parameters(design, cfg):
    up = design.userParameters
    for name, expr, units, comment in _param_table(cfg):
        p = up.itemByName(name)
        if p is None:
            up.add(name, _vi(expr), units, comment)
        elif p.expression.replace(' ', '') != expr.replace(' ', ''):
            p.expression = expr


# ---------------------------------------------------------------- sketches
def _param_rect(sketch, x0, y0, x1, y1, x0_expr, y0_expr, w_expr, h_expr, name):
    """Fully constrained rectangle: H/V constraints plus expression-driven dimensions.
    x0_expr/y0_expr None puts the first corner on the sketch origin."""
    sketch.name = name
    gc = sketch.geometricConstraints
    before = gc.count
    lines = sketch.sketchCurves.sketchLines.addTwoPointRectangle(_p(x0, y0), _p(x1, y1))
    if gc.count == before:  # some Fusion builds add no constraints to the rectangle
        for i in range(lines.count):
            ln = lines.item(i)
            a, b = ln.startSketchPoint.geometry, ln.endSketchPoint.geometry
            (gc.addHorizontal if abs(a.y - b.y) < 1e-7 else gc.addVertical)(ln)
    p00 = p11 = None
    for i in range(lines.count):
        ln = lines.item(i)
        for sp in (ln.startSketchPoint, ln.endSketchPoint):
            g = sp.geometry
            if abs(g.x - x0 / 10) < 1e-6 and abs(g.y - y0 / 10) < 1e-6:
                p00 = sp
            if abs(g.x - x1 / 10) < 1e-6 and abs(g.y - y1 / 10) < 1e-6:
                p11 = sp
    if p00 is None or p11 is None:
        raise BuildError('rectangle corners not found in ' + name)
    sd = sketch.sketchDimensions
    hor = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
    ver = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
    if x0_expr is None:
        gc.addCoincident(p00, sketch.originPoint)
    else:
        sd.addDistanceDimension(sketch.originPoint, p00, hor, _p(x0 / 2, y0 - 6)).parameter.expression = x0_expr
        sd.addDistanceDimension(sketch.originPoint, p00, ver, _p(x0 - 6, y0 / 2)).parameter.expression = y0_expr
    sd.addDistanceDimension(p00, p11, hor, _p((x0 + x1) / 2, y0 - 10)).parameter.expression = w_expr
    sd.addDistanceDimension(p00, p11, ver, _p(x0 - 10, (y0 + y1) / 2)).parameter.expression = h_expr
    if not sketch.isFullyConstrained:
        raise BuildError('sketch not fully constrained: ' + name)
    return sketch


def _single_profile(sketch):
    if sketch.profiles.count != 1:
        raise BuildError('%s: expected 1 profile, got %d' % (sketch.name, sketch.profiles.count))
    return sketch.profiles.item(0)


def _extrude(comp, profile, dist_expr, name, negative=False, start_offset=None):
    ext = comp.features.extrudeFeatures
    inp = ext.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    direction = (adsk.fusion.ExtentDirections.NegativeExtentDirection if negative
                 else adsk.fusion.ExtentDirections.PositiveExtentDirection)
    inp.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(_vi(dist_expr)), direction)
    if start_offset:
        inp.startExtent = adsk.fusion.OffsetStartDefinition.create(_vi(start_offset))
    f = ext.add(inp)
    f.name = name
    return f


def _vertical_edges(body):
    out = []
    for e in body.edges:
        if isinstance(e.geometry, adsk.core.Line3D):
            a, b = e.startVertex.geometry, e.endVertex.geometry
            if abs(a.x - b.x) < 1e-7 and abs(a.y - b.y) < 1e-7:
                out.append(e)
    return out


def _fillet(comp, edges, radius_expr, name):
    fil = comp.features.filletFeatures
    inp = fil.createInput()
    inp.edgeSetInputs.addConstantRadiusEdgeSet(_coll(edges), _vi(radius_expr), False)
    f = fil.add(inp)
    f.name = name
    return f


def _flat_faces_at(body, z_mm):
    out = []
    for f in body.faces:
        g = f.geometry
        if isinstance(g, adsk.core.Plane) and abs(abs(g.normal.z) - 1) < 1e-7 and abs(f.pointOnFace.z * 10 - z_mm) < 1e-4:
            out.append(f)
    return out


def _shell(comp, faces, thick_expr, name):
    sh = comp.features.shellFeatures
    inp = sh.createInput(_coll(faces), False)
    inp.insideThickness = _vi(thick_expr)
    f = sh.add(inp)
    f.name = name
    return f


def _chamfer_ok(design, body, zc, depth):
    """Probe just above / below the expected chamfer face under the rim."""
    pad = _mm(design, 'UnitSquarePadding')
    hc = pad * math.tan(_num(design, 'RimChamferAngle'))  # angle parameter values are in radians

    def face_z(x):
        return zc - hc * (x / pad)
    for x in (0.25 * pad, 0.8 * pad):
        if not _inside(body, x, depth / 2, face_z(x) + 0.25) or _inside(body, x, depth / 2, face_z(x) - 0.25):
            return False
    return True


# ---------------------------------------------------------------- base bin
def build_base(design):
    """Parametric bin without dividers. Returns the bin body."""
    root = design.rootComponent
    xy = root.xYConstructionPlane
    u = _mm(design, 'OneUnit')
    nx, ny = int(round(_num(design, 'NumUnitsX'))), int(round(_num(design, 'NumUnitsY')))
    pad = _mm(design, 'UnitSquarePadding')
    width, depth = nx * u, ny * u
    lower = _mm(design, 'LowerHeight')
    wall = _mm(design, 'BoxWallThickness')
    bsw = _mm(design, 'BaseSquareWidth')

    # 1. lower body: rounded box shelled open at the top
    sk = _param_rect(root.sketches.add(xy), pad, pad, width - pad, depth - pad,
                     'UnitSquarePadding', 'UnitSquarePadding',
                     'NumUnitsX * OneUnit - 2 * UnitSquarePadding', 'NumUnitsY * OneUnit - 2 * UnitSquarePadding',
                     'SBD Body Outline')
    body = _extrude(root, _single_profile(sk), 'LowerHeight', 'SBD Body').bodies.item(0)
    body.name = BIN_BODY
    _fillet(root, _vertical_edges(body), 'BoxCornerRadius', 'SBD Body Corners')
    _shell(root, _flat_faces_at(body, lower), 'BoxWallThickness', 'SBD Body Shell')

    # 2. rim: full-footprint tube from (LowerHeight - wall) to the top
    sk = _param_rect(root.sketches.add(xy), 0, 0, width, depth, None, None,
                     'NumUnitsX * OneUnit', 'NumUnitsY * OneUnit', 'SBD Rim Outline')
    rim = _extrude(root, _single_profile(sk), 'RimHeight + BoxWallThickness', 'SBD Rim',
                   start_offset='LowerHeight - BoxWallThickness').bodies.item(0)
    rim.name = 'Rim'
    _fillet(root, _vertical_edges(rim), 'BoxCornerRadius + UnitSquarePadding', 'SBD Rim Corners')
    _shell(root, _flat_faces_at(rim, lower - wall) + _flat_faces_at(rim, lower + _mm(design, 'RimHeight')),
           'BoxWallThickness', 'SBD Rim Shell')
    cmb = root.features.combineFeatures
    ci = cmb.createInput(body, _coll([rim]))
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    cmb.add(ci).name = 'SBD Join Rim'

    # 3. chamfer under the rim overhang: the concave edge loop where rim meets the lower wall
    zc = lower - wall
    edges = []
    for e in body.edges:
        a, b = e.startVertex.geometry, e.endVertex.geometry
        if abs(a.z * 10 - zc) > 1e-4 or abs(b.z * 10 - zc) > 1e-4:
            continue
        bb = e.boundingBox
        if (bb.minPoint.x * 10 > pad - 1e-3 and bb.maxPoint.x * 10 < width - pad + 1e-3 and
                bb.minPoint.y * 10 > pad - 1e-3 and bb.maxPoint.y * 10 < depth - pad + 1e-3):
            edges.append(e)
    if len(edges) != 8:
        raise BuildError('rim chamfer: expected 8 edges, found %d' % len(edges))
    ch = root.features.chamferFeatures
    chf = None
    for flipped in (True, False):
        inp = ch.createInput2()
        inp.chamferEdgeSets.addDistanceAndAngleChamferEdgeSet(_coll(edges), _vi('UnitSquarePadding'),
                                                              _vi('RimChamferAngle'), flipped, True)
        try:
            chf = ch.add(inp)
        except RuntimeError:
            chf = None
            continue
        chf.name = 'SBD Rim Chamfer'
        if _chamfer_ok(design, body, zc, depth):
            break
        chf.deleteMe()
        chf = None
    if chf is None:
        raise BuildError('the rim chamfer could not be created with the expected shape')

    # 4. one foot ring, patterned over the grid along the construction axes
    off = (u - bsw) / 2
    sk = _param_rect(root.sketches.add(xy), off, off, off + bsw, off + bsw,
                     '( OneUnit - BaseSquareWidth ) / 2', '( OneUnit - BaseSquareWidth ) / 2',
                     'BaseSquareWidth', 'BaseSquareWidth', 'SBD Foot Outline')
    foot = _extrude(root, _single_profile(sk), 'BaseClearance', 'SBD Foot', negative=True).bodies.item(0)
    foot.name = 'Foot'
    _fillet(root, _vertical_edges(foot), 'BoxCornerRadius', 'SBD Foot Corners')
    bc = _mm(design, 'BaseClearance')
    _shell(root, _flat_faces_at(foot, 0.0) + _flat_faces_at(foot, -bc), 'BaseWallThickness', 'SBD Foot Shell')
    rp = root.features.rectangularPatternFeatures
    pin = rp.createInput(_coll([foot]), root.xConstructionAxis, _vi('NumUnitsX'), _vi('OneUnit'),
                         adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
    pin.setDirectionTwo(root.yConstructionAxis, _vi('NumUnitsY'), _vi('OneUnit'))
    rp.add(pin).name = 'SBD Foot Pattern'
    return body


# ---------------------------------------------------------------- dividers
def build_dividers(design, cfg):
    """Exact union of the divider boxes as one base-feature body. Returns the body or None."""
    boxes = L.divider_boxes(cfg)
    if not boxes:
        return None
    root = design.rootComponent
    tbm = adsk.fusion.TemporaryBRepManager.get()
    z0, z1 = 0.0, L.derived(cfg)['dividerTop']
    union = None
    for x0, y0, x1, y1 in boxes:
        obb = adsk.core.OrientedBoundingBox3D.create(
            _p((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
            adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0),
            (x1 - x0) / 10, (y1 - y0) / 10, (z1 - z0) / 10)
        b = tbm.createBox(obb)
        if union is None:
            union = b
        elif not tbm.booleanOperation(union, b, adsk.fusion.BooleanTypes.UnionBooleanType):
            raise BuildError('divider union failed')
    bf = root.features.baseFeatures.add()
    bf.name = 'SBD Dividers'
    bf.startEdit()
    root.bRepBodies.add(union, bf)
    bf.finishEdit()
    body = bf.bodies.item(0)
    body.name = 'Dividers'
    return body


def _timeline_entity(design, name):
    tl = design.timeline
    for i in range(tl.count):
        if tl.item(i).name == name:
            return tl.item(i).entity
    return None


def remove_tail(design):
    for name in TAIL_FEATURES:
        e = _timeline_entity(design, name)
        if e is not None:
            e.deleteMe()


def final_join(design):
    root = design.rootComponent
    target, tools = None, []
    for b in root.bRepBodies:
        if b.name == BIN_BODY:
            target = b
        elif b.name.startswith('Foot') or b.name.startswith('Dividers'):
            tools.append(b)
    if target is None:
        raise BuildError('the %s body was not found' % BIN_BODY)
    cmb = root.features.combineFeatures
    ci = cmb.createInput(target, _coll(tools))
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    cmb.add(ci).name = 'SBD Final Join'
    return target


# ----------------------------------------------------------- persistence
def save_config(design, cfg):
    design.attributes.add(ATTR_GROUP, ATTR_CONFIG, json.dumps(cfg))


def load_config(design):
    a = design.attributes.itemByName(ATTR_GROUP, ATTR_CONFIG)
    if a is None:
        return None
    try:
        return json.loads(a.value)
    except ValueError:
        return None


def is_designer_bin(design):
    return (design is not None and load_config(design) is not None and
            any(b.name == BIN_BODY for b in design.rootComponent.bRepBodies))


def read_fit_from_design(design):
    """Fit values from any open bin that uses the template parameter names."""
    fit, found = {}, []
    for k in L.DEFAULT_FIT:
        p = design.userParameters.itemByName(k)
        if p is not None:
            fit[k] = round(math.degrees(p.value), 4) if k == 'RimChamferAngle' else round(p.value * 10, 4)
            found.append(k)
    out = {'fit': fit, 'found': found}
    p = design.userParameters.itemByName('BaseSquareWidth')
    if p is not None and 'BaseSquareTrim' not in fit:
        u, pad = fit.get('OneUnit'), fit.get('UnitSquarePadding')
        if u is not None and pad is not None:  # derive the trim from the evaluated value
            fit['BaseSquareTrim'] = round(u - 2 * pad - p.value * 10, 4)
            found.append('BaseSquareTrim')
    for k, key in (('NumUnitsX', 'nx'), ('NumUnitsY', 'ny')):
        p = design.userParameters.itemByName(k)
        if p is not None:
            out[key] = int(round(p.value))
    p = design.userParameters.itemByName('BoxHeight')
    if p is not None:
        out['height'] = round(p.value * 10, 3)
    p = design.allParameters.itemByName('DividerWallThickness')
    if p is not None:
        out['dividerThickness'] = round(p.value * 10, 4)
    return out


# ------------------------------------------------------------ public API
def create_bin(app, cfg):
    """Build a complete bin in a new document. Returns (document, report)."""
    cfg = L.normalize(cfg)
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    apply_parameters(design, cfg)
    build_base(design)
    build_dividers(design, cfg)
    final_join(design)
    save_config(design, cfg)
    return doc, verify(design, cfg)


def update_bin(design, cfg):
    """Re-size and re-layout a designer bin in place."""
    cfg = L.normalize(cfg)
    if not is_designer_bin(design):
        raise BuildError('The active document is not a bin made by Systainer Bin Designer. Use "Create new bin".')
    remove_tail(design)
    apply_parameters(design, cfg)
    build_dividers(design, cfg)
    final_join(design)
    save_config(design, cfg)
    return verify(design, cfg)


def verify(design, cfg):
    """Read-back checks on the finished body: one solid, size, dividers, compartments and feet."""
    root = design.rootComponent
    bodies = list(root.bRepBodies)
    main = next((b for b in bodies if b.name == BIN_BODY), None)
    tl = design.timeline
    report = {
        'bodies': [b.name for b in bodies],
        'unhealthy': [tl.item(i).name for i in range(tl.count)
                      if tl.item(i).healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState],
        'compartments': len(L.compartments(cfg)),
        'problems': [],
    }
    problems = report['problems']
    if main is None:
        problems.append('bin body missing')
        return report
    bb = main.boundingBox
    report['size_mm'] = [round((bb.maxPoint.x - bb.minPoint.x) * 10, 3), round((bb.maxPoint.y - bb.minPoint.y) * 10, 3),
                         round((bb.maxPoint.z - bb.minPoint.z) * 10, 3)]
    report['volume_cm3'] = round(main.volume, 4)
    report['mass_g_pla'] = round(main.volume * 1.24, 1)
    report['lumps'] = main.lumps.count
    g = L.derived(cfg)
    expected = [round(g['width'], 3), round(g['depth'], 3), round(cfg['height'], 3)]
    if any(abs(a - b) > 0.01 for a, b in zip(report['size_mm'], expected)):
        problems.append('size %s mm differs from the expected %s mm' % (report['size_mm'], expected))
    if len(bodies) != 1 or main.lumps.count != 1:
        problems.append('expected one single-piece body, found %s' % report['bodies'])
    if report['unhealthy']:
        problems.append('features with errors or warnings: %s' % ', '.join(report['unhealthy']))
    zmid = g['dividerTop'] / 2 + 1
    for x0, y0, x1, y1 in L.divider_boxes(cfg):
        if not _inside(main, (x0 + x1) / 2, (y0 + y1) / 2, zmid):
            problems.append('divider missing at (%.1f, %.1f)' % ((x0 + x1) / 2, (y0 + y1) / 2))
    bc = cfg['fit']['BaseClearance']
    u, bsw, ring = g['unit'], g['footSize'], g['footRing']
    for i in range(cfg['nx']):
        for j in range(cfg['ny']):
            cx, cy = (i + 0.5) * u, (j + 0.5) * u
            if not _inside(main, cx - bsw / 2 + ring / 2, cy, -bc / 2):
                problems.append('foot missing at unit (%d, %d)' % (i, j))
            if _inside(main, cx, cy, -bc / 2):
                problems.append('foot not hollow at unit (%d, %d)' % (i, j))
    for c in L.compartments(cfg):
        x, y = c['probe']
        if _inside(main, x, y, zmid):
            problems.append('compartment not empty at (%.1f, %.1f)' % (x, y))
    return report


def next_version_path(folder, stem, ext):
    n = 1
    while True:
        p = os.path.join(folder, '%s-v%d.%s' % (stem, n, ext))
        if not os.path.exists(p):
            return p
        n += 1


def export_body(design, path, fmt):
    root = design.rootComponent
    body = next((b for b in root.bRepBodies if b.name == BIN_BODY), None)
    if body is None:
        raise BuildError('the %s body was not found' % BIN_BODY)
    was_visible = body.isLightBulbOn
    body.isLightBulbOn = True  # hidden bodies export as empty files
    try:
        em = design.exportManager
        if fmt == 'stl':
            opt = em.createSTLExportOptions(body, path)
            opt.isBinaryFormat = True
            opt.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
        elif fmt == '3mf':
            opt = em.createC3MFExportOptions(body, path)
        elif fmt == 'step':
            opt = em.createSTEPExportOptions(path, root)
        else:
            raise BuildError('unknown export format ' + fmt)
        ok = em.execute(opt)
    finally:
        body.isLightBulbOn = was_visible
    if not ok or not os.path.exists(path) or os.path.getsize(path) == 0:
        raise BuildError('export failed: ' + path)
    return path, os.path.getsize(path)
