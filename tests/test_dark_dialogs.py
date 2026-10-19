"""Settings > Home screen > Dark dialogs (off by default)."""
import contextlib
import os
import re

import pytest

from tests.kodistubs import install_kodi_stubs

_SKIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'skins', 'Default', '1080i')
_DIALOGS = ('BusyDialog.xml', 'ProgressDialog.xml', 'CountdownDialog.xml', 'ConfirmDialog.xml', 'OptionListDialog.xml')


@pytest.fixture
def load():
    with contextlib.ExitStack() as stack:
        def _load(settings=None):
            return stack.enter_context(install_kodi_stubs(
                reload=('lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.dialogs'), settings=settings))
        yield _load


def _read(name):
    with open(os.path.join(_SKIN, name), encoding='utf-8') as handle:
        return handle.read()


def test_the_setting_is_off_by_default():
    import xml.etree.ElementTree as ET

    root = ET.parse(os.path.join(os.path.dirname(_SKIN), '..', '..', 'settings.xml')).getroot()
    assert root.find(".//setting[@id='ui_dark_dialogs']").findtext('default') == 'false'


def test_off_loads_the_classic_dialogs(load):
    ctx = load()
    for name in _DIALOGS:
        assert ctx.uicommon.skin_name(name) == name


def test_on_loads_the_dark_variants_and_leaves_windows_alone(load):
    ctx = load(settings={'ui_dark_dialogs': 'true'})
    for name in _DIALOGS:
        assert ctx.uicommon.skin_name(name) == 'Dark' + name
    assert ctx.uicommon.skin_name('HomeWindow.xml') == 'HomeWindow.xml'


@pytest.mark.parametrize('name', _DIALOGS)
def test_a_dark_variant_keeps_every_control_of_the_classic_one(name):
    ids = set(re.findall(r'<control type="\w+" id="(\d+)"', _read(name)))
    dark = _read('Dark' + name)
    assert ids <= set(re.findall(r'<control type="\w+" id="(\d+)"', dark))
    assert 'dlg_panel.png' in dark and 'dlg_stroke.png' in dark
    assert '38BDF8' not in dark and 'FF12161A' not in dark


def test_the_dark_menu_fits_its_rows_and_the_classic_one_does_not_move(load):
    ctx = load(settings={'ui_dark_dialogs': 'true'})
    dialogs = ctx.dialogs
    win = ctx.uicommon.open_window(dialogs._OptionListWindow, 'OptionListDialog.xml')
    win.heading = 'Title'
    win.rows = ['One', 'Two', 'Three']
    win.onInit()
    top, height, list_h = dialogs.option_list_geometry(3)
    panel = win.getControl(dialogs.OPTIONLIST_PANEL)
    assert (panel.y, panel.height) == (top, height)
    assert win.getControl(dialogs.OPTIONLIST_LIST).height == list_h


def test_the_classic_menu_is_not_resized(load):
    ctx = load()
    dialogs = ctx.dialogs
    win = ctx.uicommon.open_window(dialogs._OptionListWindow, 'OptionListDialog.xml')
    win.heading = 'Title'
    win.rows = ['One']
    win.onInit()
    assert getattr(win.getControl(dialogs.OPTIONLIST_LIST), 'height', None) is None
