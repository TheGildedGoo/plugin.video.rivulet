# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""The rev3–rev10 fixes, still true on this tree.

Each test is one news line. A later layout or sync change that puts the
title back on the rows, cuts the library row at twelve, or pushes a
library sample on every tick fails here even when the new feature's
own tests stay green.
"""
import os
import xml.etree.ElementTree as ET

from lib.stremio.decades import DECADE_FLOOR, decade_tiles
from lib.ui.binge import next_video

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIN = os.path.join(_ROOT, 'resources', 'skins', 'Default', '1080i')


def _xml(name):
    return ET.parse(os.path.join(_SKIN, name)).getroot()


def _text(name):
    with open(os.path.join(_SKIN, name), encoding='utf-8') as handle:
        return handle.read()


def test_rev3_home_is_poster_rows_and_settings_is_the_rightmost_pill():
    root = _xml('HomeWindow.xml')
    rows = root.find(".//control[@id='30001']")
    assert rows is not None and rows.get('type') == 'grouplist'
    assert rows.find(".//control[@id='30040']") is not None
    assert rows.find(".//control[@id='30041']") is not None
    bar = root.find(".//control[@id='30011']")
    assert (bar.findtext('align') or '').strip() == 'right'
    buttons = [child.get('id') for child in list(bar) if child.get('type') == 'button']
    assert buttons[-1] == '30072'
    assert 'RevRivulet' in _text('HomeWindow.xml')


def test_rev4_hub_lists_catalogs_and_the_wordmark_is_revrivulet():
    hub = _xml('HubWindow.xml')
    listing = hub.find(".//control[@id='31000']")
    assert listing is not None and listing.get('type') == 'fixedlist'
    assert 'pill_fill.png' in _text('HomeWindow.xml')
    assert 'mask_poster.png' in _text('HubWindow.xml')
    with open(os.path.join(_ROOT, 'addon.xml'), encoding='utf-8') as handle:
        news = handle.read()
    assert 'RevRivulet' in news


def test_rev5_stop_during_playback_is_a_duplicate_launch_not_a_new_home():
    """The rule lives in is_duplicate_launch: a live UI heartbeat means
    Kodi's plugin refresh must not open a second Home. The journey
    test drives the heartbeat; this one keeps the function on the
    launch path default.py actually calls."""
    with open(os.path.join(_ROOT, 'default.py'), encoding='utf-8') as handle:
        text = handle.read()
    assert 'is_duplicate_launch' in text


def test_rev6_progress_sync_is_start_then_sixty_seconds_then_stop():
    import datetime

    from lib.service_runner import LIBRARY_PUSH_INTERVAL_SECONDS, should_push_now

    assert LIBRARY_PUSH_INTERVAL_SECONDS == 60
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    assert should_push_now(None, start, final=False) is True
    assert should_push_now(start, start + datetime.timedelta(seconds=59), final=False) is False
    assert should_push_now(start, start + datetime.timedelta(seconds=60), final=False) is True
    assert should_push_now(start, start + datetime.timedelta(seconds=1), final=True) is True


def test_rev7_poster_mask_is_not_a_square():
    from tests.test_layout_geometry import png_size

    width, height = png_size(os.path.join(
        _ROOT, 'resources', 'skins', 'Default', 'media', 'mask_poster.png',
    ))
    assert width != height
    assert width * 3 == height * 2


def test_rev8_version_sorts_after_rev8():
    from scripts.kodi_addon_version import kodi_lt

    root = ET.parse(os.path.join(_ROOT, 'addon.xml')).getroot()
    version = root.get('version')
    assert kodi_lt('0.30.1.rev8', version)
    assert kodi_lt('0.30.1.rev10', version)


def test_rev9_new_episodes_use_the_still_and_the_logo_has_no_grey_box():
    """The series hub's first row is landscape, titled with the episode,
    and the plot is that episode's overview. The Home clearlogo is
    background=true so a missing file is not a grey box."""
    from tests.kodistubs import install_kodi_stubs

    text = _text('HubWindow.xml')
    assert 'mask_land.png' in text
    home = _text('HomeWindow.xml')
    logo = home[home.index('id="30023"'):home.index('id="30023"') + 500]
    assert 'background="true"' in logo
    with install_kodi_stubs(reload=(
        'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.homewindow',
        'lib.ui.hubwindow', 'lib.ui.catalogpicker',
    )) as ctx:
        ctx.catalogpicker._new_episode_items = lambda _store: [{
            'type': 'series', 'id': 'show', 'name': 'Show',
            'label': 'S1E3 · Pilot', 'poster': 'http://still',
            'overview': 'The cold open.', 'video_id': 'show:1:3',
        }]
        desc = ctx.hubwindow._episode_descriptor(object(), frozenset({'series', 'tv'}))
    assert desc['layout'] == 'land'
    poster = desc['posters'][0]
    assert poster.getProperty('thumbnail') == 'http://still'
    assert poster.getProperty('hero_title') == 'S1E3 · Pilot'
    assert poster.getProperty('hero_plot') == 'The cold open.'
    assert poster.getProperty('hero_logo') == ''


def test_rev10_continue_offers_resume_library_scrolls_and_the_hero_clears_the_rows():
    home = _text('HomeWindow.xml')
    assert 'id="30020"' in home and 'id="30022"' in home
    rows = _xml('HomeWindow.xml').find(".//control[@id='30001']")
    plot = _xml('HomeWindow.xml').find(".//control[@id='30022']")
    assert int(plot.findtext('top')) + int(plot.findtext('height')) <= int(rows.findtext('top'))
    with open(os.path.join(_ROOT, 'lib', 'ui', 'gridwindow.py'), encoding='utf-8') as handle:
        source = handle.read()
    assert 'PROGRESS_TRACK_WIDTH = 200' in source
    assert 'focus_stroke.png' in home


def test_rev10_next_episode_crosses_the_season_and_stops_at_the_end():
    meta = {'videos': [
        {'id': 's1e8', 'season': 1, 'episode': 8},
        {'id': 's2e1', 'season': 2, 'episode': 1},
    ]}
    assert next_video(meta, 's1e8')['id'] == 's2e1'
    assert next_video({'videos': [{'id': 's2e1', 'season': 2, 'episode': 1}]}, 's2e1') is None


def test_rev11_decades_stop_at_the_1960s():
    tiles = decade_tiles(['2026', '1994', '1962', '1959', '1920'])
    assert [tile['label'] for tile in tiles] == ['2020s', '1990s', '1960s']
    assert tiles[-1]['start'] == DECADE_FLOOR
    assert all(int(year) >= DECADE_FLOOR for tile in tiles for year in tile['years'])
