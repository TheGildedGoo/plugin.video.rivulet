"""The Fuse look (lib/ui/fuse.py): a second skin set for the same windows.

The rule that keeps it safe: a Fuse file declares every control id its
classic file does, so the window class can drive either. The rest pins
the hero lines (stars, facts, scores, "Ends at"), the stack that moves
them, the setting that picks the file, and Home reopening itself when
that setting changes.
"""
import contextlib
import os
import time
import xml.etree.ElementTree as ET

import pytest

from lib.ui.playbackmeta import fuse_hero_parts
from tests.kodistubs import install_kodi_stubs
from tests.test_homewindow import (
    _RELOAD_MODULE_NAMES,
    _THREE,
    _built_home,
    _FakeStore,
    _patch_library,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIN = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i')
_MEDIA = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', 'media')


@pytest.fixture
def load_homewindow():
    """`load_homewindow(settings=None)`: fresh Kodi stubs, lib.ui.fuse included."""
    with contextlib.ExitStack() as stack:
        def _load(settings=None, localized=None):
            return stack.enter_context(install_kodi_stubs(
                reload=_RELOAD_MODULE_NAMES + ('lib.ui.fuse',),
                settings=settings,
                localized=localized,
            ))

        yield _load


def _ids(name):
    root = ET.parse(os.path.join(_SKIN, name)).getroot()
    return {int(c.get('id')) for c in root.iter('control') if c.get('id')}


# --- the files ---------------------------------------------------------------

def test_every_fuse_file_declares_every_classic_control():
    from lib.ui.fuse import FUSE_SKINS

    assert FUSE_SKINS
    for name in FUSE_SKINS:
        missing = _ids(name) - _ids('Fuse' + name)
        assert not missing, (name, sorted(missing))


def test_fuse_home_has_its_own_hero_controls():
    from lib.ui import fuse

    assert {fuse.HERO_FACTS, fuse.HERO_SCORES, fuse.HERO_STARS} <= _ids('FuseHomeWindow.xml')


def test_every_texture_the_fuse_skin_names_is_shipped():
    from lib.ui.fuse import FUSE_SKINS

    for name in FUSE_SKINS:
        root = ET.parse(os.path.join(_SKIN, 'Fuse' + name)).getroot()
        for texture in root.iter():
            if texture.tag not in ('texture', 'texturefocus', 'texturenofocus'):
                continue
            value = (texture.text or '').strip()
            if value and not value.startswith('$'):
                assert os.path.isfile(os.path.join(_MEDIA, value)), value
    for half in range(11):
        assert os.path.isfile(os.path.join(_MEDIA, 'fuse_stars_%02d.png' % half))


def test_the_fuse_hero_has_no_bar():
    with open(os.path.join(_SKIN, 'FuseHomeWindow.xml'), encoding='utf-8') as handle:
        text = handle.read()
    assert 'hero_bar.png' not in text
    assert 'fuse_fade_left.png' in text and 'fuse_fade_bottom.png' in text


# --- picking the file --------------------------------------------------------

def test_skin_for_picks_fuse_only_for_drawn_screens():
    from lib.ui.fuse import skin_for

    assert skin_for('HomeWindow.xml', use_fuse=True) == 'FuseHomeWindow.xml'
    assert skin_for('HomeWindow.xml', use_fuse=False) == 'HomeWindow.xml'
    assert skin_for('StreamsWindow.xml', use_fuse=True) == 'StreamsWindow.xml'
    assert skin_for('FuseHomeWindow.xml', use_fuse=True) == 'FuseHomeWindow.xml'
    assert skin_for('', use_fuse=True) == ''


def test_open_window_uses_the_setting_and_remembers_the_file(load_homewindow):
    ctx = load_homewindow(settings={'ui_fuse': 'true'})
    from lib.ui.uicommon import open_window

    win = open_window(ctx.homewindow.HomeWindow, 'HomeWindow.xml')
    assert win._skin_xml == 'FuseHomeWindow.xml'

    ctx = load_homewindow()
    from lib.ui.uicommon import open_window as classic_open

    assert classic_open(ctx.homewindow.HomeWindow, 'HomeWindow.xml')._skin_xml == 'HomeWindow.xml'


# --- the hero lines ----------------------------------------------------------

def test_hero_parts_split_scores_from_facts():
    text = 'Rotten Tomatoes 94%\nMetascore 71\nIMDb 7.4\n2025\n1h 52m\nThriller, Mystery'
    stars, facts, scores = fuse_hero_parts(text)
    assert stars == 7  # 7.4 of 10 is three and a half stars
    assert facts == ['2025', '1h 52m', 'Thriller, Mystery']
    assert scores == [('IMDb', '7.4'), ('RT', '94%'), ('MC', '71')]


@pytest.mark.parametrize('text, stars', [
    ('2025', None), ('IMDb n/a\n2025', None), ('IMDb 10', 10), ('IMDb 0.2', 0), ('IMDb 8.75/10', 9),
])
def test_hero_parts_stars(text, stars):
    assert fuse_hero_parts(text)[0] == stars


def test_hero_parts_keep_an_unknown_line_as_a_fact():
    assert fuse_hero_parts('Ended\n\n2019')[1] == ['Ended', '2019']


def test_hero_lines_join_facts_and_end_scores_with_the_end_time(load_homewindow, monkeypatch):
    load_homewindow()
    from lib.ui import fuse

    monkeypatch.setattr(fuse, '_clock_format', lambda: '%H:%M')
    now = time.mktime((2026, 10, 17, 20, 36, 0, 0, 0, -1))
    stars, facts, scores = fuse.hero_lines('IMDb 7.4\nRotten Tomatoes 88%\n2025\n1h 52m', '112', now=now)
    assert stars == 'fuse_stars_07.png'
    assert facts == '2025  •  1h 52m'
    assert scores.startswith('[COLOR B3EDEDED]IMDb[/COLOR] 7.4')
    assert 'RT[/COLOR] 88%' in scores
    assert scores.endswith('Ends at 22:28')


def test_no_runtime_no_end_time(load_homewindow):
    load_homewindow()
    from lib.ui import fuse

    assert fuse.ends_at('') == '' and fuse.ends_at(None) == '' and fuse.ends_at('0') == ''
    assert 'Ends at' not in fuse.hero_lines('IMDb 7', '')[2]


def test_twelve_hour_clock_drops_the_leading_zero(load_homewindow, monkeypatch):
    load_homewindow()
    from lib.ui import fuse

    monkeypatch.setattr(fuse, '_clock_format', lambda: '%I:%M %p')
    now = time.mktime((2026, 10, 17, 20, 0, 0, 0, 0, -1))
    assert fuse.ends_at('65', now=now) == '9:05 PM'


# --- Home in the Fuse file ---------------------------------------------------

def _fuse_hero(ctx, meta, plot='A storm-chaser returns.', runtime='112', logo=''):
    import xbmcgui
    win = ctx.homewindow.HomeWindow('FuseHomeWindow.xml', '/addon/path', 'Default', '1080i')
    win._skin_xml = 'FuseHomeWindow.xml'
    item = xbmcgui.ListItem('Hollow Tide')
    item.setProperties({
        'hero_title': 'Hollow Tide', 'hero_meta': meta, 'hero_plot': plot,
        'hero_runtime': runtime, 'fanart': 'https://img/b.jpg', 'sid': 'tt1', 'stype': 'movie',
        'hero_logo': logo,
    })
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])
    win.setFocusId(ctx.homewindow.CONTINUE_SHELF)
    return win


def test_fuse_home_paints_stars_facts_and_scores(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    import lib.ui.heroscrim as heroscrim
    from lib.ui import fuse
    bars = []
    monkeypatch.setattr(heroscrim, 'place_hero_bar', lambda *a, **k: bars.append(a))

    win = _fuse_hero(ctx, 'IMDb 7.4\n2025\n1h 52m\nThriller')
    ctx.homewindow.paint_hero(win)

    assert win.getControl(fuse.HERO_STARS).image == 'fuse_stars_07.png'
    assert win.getControl(fuse.HERO_FACTS).label == '•  2025  •  1h 52m  •  Thriller'
    assert 'IMDb[/COLOR] 7.4' in win.getControl(fuse.HERO_SCORES).label
    assert 'Ends at' in win.getControl(fuse.HERO_SCORES).label
    # The classic bar is never measured or shown in this look.
    assert bars == []


def test_fuse_stack_ends_on_the_same_line_above_the_row(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    from lib.ui import fuse

    long_plot = 'word ' * 120
    win = _fuse_hero(ctx, 'IMDb 7.4\n2025', plot=long_plot)
    ctx.homewindow.paint_hero(win)
    scores = win.getControl(fuse.HERO_SCORES)
    assert scores.y + scores.height == fuse._STACK['bottom']
    plot = win.getControl(ctx.homewindow.HERO_PLOT)
    assert plot.height <= 3 * 30 + 20  # three lines at most
    tall_logo_top = win.getControl(ctx.homewindow.HERO_LOGO).y

    short = _fuse_hero(ctx, 'IMDb 7.4\n2025', plot='Short.')
    ctx.homewindow.paint_hero(short)
    # A short plot moves the title down instead of leaving a gap.
    assert short.getControl(ctx.homewindow.HERO_LOGO).y > tall_logo_top


def test_fuse_facts_start_at_the_margin_without_stars(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    from lib.ui import fuse

    win = _fuse_hero(ctx, '2025\n1h 52m', runtime='')
    ctx.homewindow.paint_hero(win)
    assert win.getControl(fuse.HERO_STARS).image == ''
    facts = win.getControl(fuse.HERO_FACTS)
    assert facts.label == '2025  •  1h 52m' and facts.x == fuse._STACK['left']
    assert win.getControl(fuse.HERO_SCORES).label == ''


def test_classic_home_still_uses_the_bar(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    import lib.ui.heroscrim as heroscrim
    placed = []
    monkeypatch.setattr(heroscrim, 'place_hero_bar', lambda *a, **k: placed.append(a[1]))
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('X')
    item.setProperties({'hero_title': 'X', 'hero_meta': 'IMDb 7', 'sid': 'tt1'})
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])
    win.setFocusId(ctx.homewindow.CONTINUE_SHELF)
    ctx.homewindow.paint_hero(win)
    assert placed == ['home']


def test_poster_items_carry_the_runtime_in_minutes(load_homewindow):
    ctx = load_homewindow()
    item = ctx.homewindow._poster_item({'id': 'tt1', 'type': 'movie', 'name': 'X', 'runtime': '112 min'})
    assert item.getProperty('hero_runtime') == '112'
    assert ctx.homewindow._poster_item({'id': 'tt2', 'name': 'Y'}).getProperty('hero_runtime') == ''


def test_fuse_home_builds_its_rows(load_homewindow, monkeypatch):
    """The whole build runs against the Fuse file: every control Home
    touches exists there (the fake raises on an unknown id)."""
    ctx = load_homewindow()
    store = _FakeStore(auth={'authKey': 'k', 'user': {'email': 'a@b.c'}})
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: store)
    monkeypatch.setattr(ctx.homewindow, '_catalog_pages', lambda addons, enabled: ({}, {}))
    _patch_library(monkeypatch, ctx, _THREE)
    win = ctx.homewindow.HomeWindow('FuseHomeWindow.xml', '/addon/path', 'Default', '1080i')
    win._skin_xml = 'FuseHomeWindow.xml'
    win.onInit()
    sids = [i.getProperty('sid') for i in win.getControl(ctx.homewindow.LIBRARY_SHELF).items]
    assert sids[:3] == ['tt1', 'tt2', 'tt3']


# --- switching looks ---------------------------------------------------------

def test_switching_the_setting_closes_home_to_reopen_it(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, _store = _built_home(ctx, monkeypatch, _THREE)
    win._skin_xml = 'HomeWindow.xml'
    import lib.ui.fuse as fuse
    monkeypatch.setattr(fuse, 'enabled', lambda: True)

    ctx.homewindow._after_child(win)

    assert win.closed is True and win._restyle is True


def test_an_unchanged_setting_keeps_home_open(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, _store = _built_home(ctx, monkeypatch, _THREE)
    win._skin_xml = 'HomeWindow.xml'

    ctx.homewindow._after_child(win)

    assert win.closed is False and not getattr(win, '_restyle', False)


def test_open_home_reopens_once_in_the_new_look(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    opened = []

    class _Win:
        def __init__(self, restyle):
            self._restyle = restyle

        def doModal(self):
            pass

        def close(self):
            pass

    wins = [_Win(True), _Win(False)]
    monkeypatch.setattr(ctx.homewindow, 'open_window', lambda cls, name: opened.append(name) or wins.pop(0))
    monkeypatch.setattr(ctx.homewindow, '_notify_if_updated', lambda store: None)
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))

    ctx.homewindow.open_home()

    assert opened == ['HomeWindow.xml', 'HomeWindow.xml']
