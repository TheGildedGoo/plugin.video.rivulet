"""Dark dialogs are the single dialog style."""
import contextlib
import os
import re
import xml.etree.ElementTree as ET

import pytest

from tests.kodistubs import install_kodi_stubs

_SKIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'skins', 'Default', '1080i')


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


@pytest.mark.parametrize('name, required', [
    ('Busy', {30320, 30321, 30322}),
    ('Progress', {30300, 30301, 30302, 30303, 30304, 30305, 30306}),
    ('Countdown', {30310, 30311, 30312, 30313}),
    ('Confirm', {30330, 30331, 30332, 30333}),
    ('OptionList', {30340, 30341, 30342, 30343, 30344, 30345, 30346}),
])
def test_dark_dialog_controls_and_style(name, required):
    dark = _read('Dark' + name + 'Dialog.xml')
    assert required <= {int(cid) for cid in re.findall(r'<control type="\w+" id="(\d+)"', dark)}
    assert 'dlg_panel.png' in dark and 'dlg_stroke.png' in dark
    assert '38BDF8' not in dark and 'FF12161A' not in dark


def test_the_menu_fits_its_rows(load):
    ctx = load()
    dialogs = ctx.dialogs
    win = ctx.uicommon.open_window(dialogs._OptionListWindow, 'DarkOptionListDialog.xml')
    win.heading = 'Title'
    win.rows = ['One', 'Two', 'Three']
    win.onInit()
    top, height, list_h = dialogs.option_list_geometry(3)
    panel = win.getControl(dialogs.OPTIONLIST_PANEL)
    assert (panel.y, panel.height) == (top, height)
    assert win.getControl(dialogs.OPTIONLIST_LIST).height == list_h
    # The scrollbar rides inside a wrapper group: Kodi's Python API cannot
    # wrap a `scrollbar`, so the group is what gets moved with the list.
    scroll = win.getControl(dialogs.OPTIONLIST_SCROLL_GROUP)
    assert scroll.y == top + dialogs._OPTION_HEAD_H


def test_checked_rows_use_the_shipped_checkmark_in_both_layouts():
    root = ET.fromstring(_read('DarkOptionListDialog.xml'))
    control = next(c for c in root.iter('control') if c.get('id') == '30341')
    for layout in ('itemlayout', 'focusedlayout'):
        checks = [image for image in control.find(layout).findall("control[@type='image']")
                  if image.findtext('texture') == 'newlook_check.png']
        assert len(checks) == 1
        assert checks[0].findtext('visible') == '!String.IsEmpty(ListItem.Property(checked))'
        assert checks[0].findtext('width') == '20'


def test_the_option_list_never_asks_python_for_the_scrollbar(load):
    """Asking for the `scrollbar` raised "Unknown control type for python"
    and was logged as a warning on every open of the menu."""
    ctx = load()
    dialogs = ctx.dialogs
    win = ctx.uicommon.open_window(dialogs._OptionListWindow, 'DarkOptionListDialog.xml')
    win.heading = 'Title'
    win.rows = ['One'] * 9
    win.onInit()
    failures = [msg for msg, _level in ctx.env.log_calls if 'getControl' in msg and 'failed' in msg]
    assert failures == []


def test_option_rows_fit_two_lines_under_the_focus_plate(load):
    """Dylan's report: on two-line rows ("Home" / "Lists: 13") the focus
    plate covered only the top line and the sublabel spilled into the
    next row. Rows match `_OPTION_ROW_H`, the plate fills the whole row,
    every label is vertically centred inside the row, and a one-line row
    centres its label in the full row height."""
    dialogs = load().dialogs
    row_h = dialogs._OPTION_ROW_H
    root = ET.fromstring(_read('DarkOptionListDialog.xml'))
    control = next(c for c in root.iter('control') if c.get('id') == '30341')
    for tag in ('itemlayout', 'focusedlayout'):
        layout = control.find(tag)
        assert int(layout.get('height')) == row_h
        labels = layout.findall("control[@type='label']")
        for label in labels:
            assert label.findtext('aligny') == 'center'
            top, height = int(label.findtext('top')), int(label.findtext('height'))
            assert 0 <= top and top + height <= row_h
        single = [lb for lb in labels if lb.findtext('visible') == 'String.IsEmpty(ListItem.Label2)']
        assert len(single) == 1
        assert (int(single[0].findtext('top')), int(single[0].findtext('height'))) == (0, row_h)
    plate = next(i for i in control.find('focusedlayout').findall("control[@type='image']")
                 if i.findtext('texture') == 'dlg_row.png')
    assert (int(plate.findtext('top')), int(plate.findtext('height'))) == (0, row_h)
    assert int(control.findtext('height')) == row_h * dialogs._OPTION_MAX_ROWS
