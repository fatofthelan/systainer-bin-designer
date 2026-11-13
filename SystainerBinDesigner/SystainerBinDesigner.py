"""Systainer Bin Designer: Fusion add-in entry point.

Adds "Systainer Bin Designer" to SOLID > CREATE. The command opens a palette
(palette/index.html) where you size a Tanos/Festool Systainer organizer insert,
draw its compartments, and build, update and export the bin.

Geometry: sbd_builder.py. Layout rules: sbd_layout.py.
"""

import importlib
import json
import os
import sys
import traceback

import adsk.core
import adsk.fusion

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sbd_layout as L  # noqa: E402
import sbd_builder as B  # noqa: E402

APP_NAME = 'Systainer Bin Designer'
VERSION = '1.0.0'
CMD_SHOW = 'sbdShowPalette'
CMD_UPDATE = 'sbdUpdateBin'
PALETTE_ID = 'sbdPalette'
PANEL_ID = 'SolidCreatePanel'
WORKSPACE_ID = 'FusionSolidEnvironment'
HTML = os.path.join(HERE, 'palette', 'index.html')

_app = None
_ui = None
_handlers = []          # keep event handlers alive
_app_events = []        # (event, handler) pairs registered on the Application
_pending = {}


# ------------------------------------------------------------ user data
def data_dir():
    """Per-user folder for saved layouts and settings (outside the add-in folder)."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    else:
        base = os.path.expanduser('~/Library/Application Support')
    path = os.path.join(base, 'SystainerBinDesigner')
    os.makedirs(path, exist_ok=True)
    return path


def _read_json(name, default):
    path = os.path.join(data_dir(), name)
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(name, value):
    path = os.path.join(data_dir(), name)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(value, f, indent=1)
    os.replace(tmp, path)


def default_export_dir():
    last = _read_json('settings.json', {}).get('lastExportDir')
    if last and os.path.isdir(last):
        return last
    docs = os.path.expanduser('~/Documents')
    return docs if os.path.isdir(docs) else os.path.expanduser('~')


# ----------------------------------------------------------------- utils
def _palette():
    return _ui.palettes.itemById(PALETTE_ID) if _ui else None


def _send(action, payload):
    pal = _palette()
    if pal:
        pal.sendInfoToHTML(action, json.dumps(payload))


def _active_design():
    prod = _app.activeProduct
    return adsk.fusion.Design.cast(prod) if prod else None


def active_info():
    design = _active_design()
    doc = _app.activeDocument
    info = {'name': doc.name if doc else None, 'isDesign': design is not None, 'isBin': False, 'config': None, 'fit': None}
    if design is None:
        return info
    info['isBin'] = B.is_designer_bin(design)
    info['config'] = B.load_config(design) if info['isBin'] else None
    try:
        info['fit'] = B.read_fit_from_design(design)
    except Exception:
        info['fit'] = None
    return info


def _error_payload(e):
    if isinstance(e, L.LayoutError):
        return {'ok': False, 'error': 'Please fix: ' + '; '.join(e.errors), 'errors': e.errors}
    if isinstance(e, B.BuildError):
        return {'ok': False, 'error': str(e)}
    return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e), 'trace': traceback.format_exc()}


# --------------------------------------------------------------- actions
def _export(fmt):
    design = _active_design()
    if not B.is_designer_bin(design):
        raise B.BuildError('Activate a bin made by this tool first (Create new bin).')
    cfg = L.normalize(B.load_config(design), check=False)
    ext = {'stl': 'stl', '3mf': '3mf', 'step': 'step'}[fmt]
    folder = default_export_dir()
    suggested = B.next_version_path(folder, L.file_stem(cfg), ext)
    dlg = _ui.createFileDialog()
    dlg.title = 'Export Systainer bin as %s' % ext.upper()
    dlg.filter = '%s files (*.%s)' % (ext.upper(), ext)
    dlg.initialDirectory = folder
    dlg.initialFilename = os.path.basename(suggested)
    if dlg.showSave() != adsk.core.DialogResults.DialogOK:
        return {'message': 'Export cancelled.'}
    path = dlg.filename
    if not path.lower().endswith('.' + ext):
        path += '.' + ext
    path, size = B.export_body(design, path, fmt)
    settings = _read_json('settings.json', {})
    settings['lastExportDir'] = os.path.dirname(path)
    _write_json('settings.json', settings)
    return {'message': 'Exported %s (%.0f kB).' % (path, size / 1024.0), 'path': path}


def dispatch(action, data):
    """Handle one request from the palette. Returns a dict merged into the JSON reply."""
    if action == 'init':
        return {'version': VERSION, 'active': active_info(), 'layouts': _read_json('layouts.json', []),
                'settings': _read_json('settings.json', {})}
    if action == 'readActive':
        return {'active': active_info()}
    if action == 'saveLayouts':
        layouts = data.get('layouts', [])
        if not isinstance(layouts, list):
            raise ValueError('layouts must be a list')
        _write_json('layouts.json', layouts)
        return {}
    if action == 'saveSettings':
        settings = _read_json('settings.json', {})
        settings.update({k: v for k, v in (data.get('settings') or {}).items() if k in ('bedSize', 'autoUpdate')})
        _write_json('settings.json', settings)
        return {}
    if action == 'create':
        cfg = L.normalize(data.get('cfg'))
        _doc, report = B.create_bin(_app, cfg)
        vp = _app.activeViewport
        cam = vp.camera
        cam.viewOrientation = adsk.core.ViewOrientations.IsoTopRightViewOrientation
        cam.isFitView = True
        vp.camera = cam
        return {'message': 'Created %s in a new, unsaved document.' % L.label(cfg), 'summary': report, 'active': active_info()}
    if action == 'update':
        L.normalize(data.get('cfg'))  # validate before queuing
        if not B.is_designer_bin(_active_design()):
            raise B.BuildError('The active document is not a bin made by this tool. Use "Create new bin".')
        _pending['cfg'] = data['cfg']  # run as a command so the update is a single undo step
        _ui.commandDefinitions.itemById(CMD_UPDATE).execute()
        return {'queued': True}
    if action == 'export':
        return _export(data.get('fmt', 'stl'))
    raise ValueError('unknown action: %s' % action)


# ----------------------------------------------------------------- events
class PaletteHTMLHandler(adsk.core.HTMLEventHandler):
    def notify(self, args):
        html = adsk.core.HTMLEventArgs.cast(args)
        if html.action == 'response':
            return
        try:
            data = json.loads(html.data) if html.data else {}
            out = dict(dispatch(html.action, data) or {})
            out['ok'] = True
            html.returnData = json.dumps(out)
        except Exception as e:
            html.returnData = json.dumps(_error_payload(e))


class ShowExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            pal = _palette()
            if pal is None:
                pal = _ui.palettes.add(PALETTE_ID, APP_NAME, HTML, True, True, True, 1150, 800, True)
                pal.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateFloating
                pal.setMinimumSize(760, 520)
                h = PaletteHTMLHandler()
                pal.incomingFromHTML.add(h)
                _handlers.append(h)
            else:
                pal.isVisible = True
                _send('activeChanged', active_info())
        except Exception:
            _ui.messageBox('%s could not open its window:\n%s' % (APP_NAME, traceback.format_exc()))


class ShowCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        h = ShowExecuteHandler()
        args.command.execute.add(h)
        _handlers.append(h)


class UpdateExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        cfg = _pending.pop('cfg', None)
        if cfg is None:
            return
        try:
            report = B.update_bin(_active_design(), cfg)
            _send('result', {'ok': True, 'message': 'Updated %s.' % _app.activeDocument.name,
                             'summary': report, 'active': active_info()})
        except Exception as e:
            args.executeFailed = True
            args.executeFailedMessage = str(e)
            _send('result', _error_payload(e))


class UpdateCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        cmd = args.command
        cmd.isRepeatable = False
        h = UpdateExecuteHandler()
        cmd.execute.add(h)
        _handlers.append(h)


class DocActivatedHandler(adsk.core.DocumentEventHandler):
    def notify(self, args):
        try:
            pal = _palette()
            if pal and pal.isVisible:
                _send('activeChanged', active_info())
        except Exception:
            pass


# ------------------------------------------------------------ lifecycle
def run(context):
    global _app, _ui
    try:
        # pick up edited helper modules when the add-in is restarted without restarting Fusion
        importlib.reload(L)
        importlib.reload(B)
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        icons = os.path.join(HERE, 'resources', 'icon')

        cd = _ui.commandDefinitions.itemById(CMD_SHOW) or _ui.commandDefinitions.addButtonDefinition(
            CMD_SHOW, APP_NAME,
            'Design Tanos/Festool Systainer organizer bins with custom compartments, then build, update and export them.',
            icons)
        h = ShowCreatedHandler()
        cd.commandCreated.add(h)
        _handlers.append(h)

        ud = _ui.commandDefinitions.itemById(CMD_UPDATE) or _ui.commandDefinitions.addButtonDefinition(
            CMD_UPDATE, 'Update Systainer bin', 'Rebuild the active bin from the designer layout', '')
        h = UpdateCreatedHandler()
        ud.commandCreated.add(h)
        _handlers.append(h)

        panel = _ui.workspaces.itemById(WORKSPACE_ID).toolbarPanels.itemById(PANEL_ID)
        if panel.controls.itemById(CMD_SHOW) is None:
            panel.controls.addCommand(cd)

        h = DocActivatedHandler()
        _app.documentActivated.add(h)
        _app_events.append((_app.documentActivated, h))
    except Exception:
        if _ui:
            _ui.messageBox('%s failed to start:\n%s' % (APP_NAME, traceback.format_exc()))


def stop(context):
    try:
        for event, handler in _app_events:
            event.remove(handler)
        _app_events.clear()
        pal = _palette()
        if pal:
            pal.deleteMe()
        panel = _ui.workspaces.itemById(WORKSPACE_ID).toolbarPanels.itemById(PANEL_ID)
        ctrl = panel.controls.itemById(CMD_SHOW)
        if ctrl:
            ctrl.deleteMe()
        for cid in (CMD_SHOW, CMD_UPDATE):
            cd = _ui.commandDefinitions.itemById(cid)
            if cd:
                cd.deleteMe()
        _handlers.clear()
    except Exception:
        if _ui:
            _ui.messageBox('%s failed to stop cleanly:\n%s' % (APP_NAME, traceback.format_exc()))
