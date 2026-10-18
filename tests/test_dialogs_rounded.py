"""rev21: the option list's plate is sized to its rows (lib/ui/dialogs.py)."""
import pytest

from tests.kodistubs import install_kodi_stubs


@pytest.fixture
def dialogs():
    with install_kodi_stubs(reload=('lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.dialogs')) as ctx:
        import lib.ui.dialogs as module
        ctx.dialogs = module
        yield ctx


def test_three_rows_get_a_short_plate_centred_on_the_screen(dialogs):
    top, height, list_h = dialogs.dialogs.option_list_geometry(3)
    assert list_h == 3 * 72
    assert height == 110 + 216 + 28
    assert top == (1080 - height) // 2


def test_a_long_menu_stops_at_seven_rows_and_scrolls(dialogs):
    assert dialogs.dialogs.option_list_geometry(30)[2] == 7 * 72
    assert dialogs.dialogs.option_list_geometry(0)[2] == 72


def test_the_window_moves_its_plate_and_list_to_fit(dialogs):
    win = dialogs.dialogs._OptionListWindow('OptionListDialog.xml', '/addon/path', 'Default', '1080i')
    win.heading = 'Andor'
    win.rows = ['Go to series', 'Add to library', 'Trailer']
    win.onInit()
    top, height, list_h = dialogs.dialogs.option_list_geometry(3)
    panel = win.getControl(dialogs.dialogs.OPTIONLIST_PANEL)
    listing = win.getControl(dialogs.dialogs.OPTIONLIST_LIST)
    assert (panel.y, panel.height) == (top, height)
    assert (listing.y, listing.height) == (top + 110, list_h)
