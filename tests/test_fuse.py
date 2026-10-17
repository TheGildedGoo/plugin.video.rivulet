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


# --- the hubs and the coverflow in the Fuse files -----------------------------

def test_fuse_hub_paints_the_hero_from_the_opening_card(monkeypatch):
    from tests.test_hubwindow import _RELOAD as hub_reload
    from tests.test_hubwindow import _Store as HubStore

    with install_kodi_stubs(reload=hub_reload + ('lib.ui.fuse',)) as ctx:
        import xbmcgui

        from lib.ui import fuse
        monkeypatch.setattr(ctx.hubwindow, 'get_store', lambda: HubStore(auth=None))
        poster = xbmcgui.ListItem('Dune')
        poster.setProperties({
            'hero_title': 'Dune', 'hero_plot': 'A desert.', 'hero_meta': 'IMDb 8.0\n2021',
            'hero_runtime': '155', 'fanart': 'back.jpg', 'sid': 'tt1', 'stype': 'movie',
        })
        win = ctx.hubwindow.HubWindow('FuseHubWindow.xml', '/addon/path', 'Default', '1080i')
        win._skin_xml = 'FuseHubWindow.xml'
        win.types = frozenset({'movie'})
        win.heading = 'Movies'
        win._descs = [{'heading': 'TOP', 'posters': [poster], 'col': 0}]
        win._episodes = []
        win.getFocusId = lambda: ctx.hubwindow.BTN_SEARCH

        win.onInit()

        assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Dune'
        assert win.getControl(fuse.HERO_STARS).image == 'fuse_stars_08.png'
        assert 'Ends at' in win.getControl(fuse.HERO_SCORES).label


def test_fuse_coverflow_paints_facts_and_scores(monkeypatch):
    from tests.test_infowindow import _RELOAD_MODULE_NAMES as info_reload
    from tests.test_infowindow import _make_meta

    with install_kodi_stubs(reload=info_reload + ('lib.ui.fuse',)) as ctx:
        from lib.ui import fuse
        monkeypatch.setattr(ctx.infowindow.ShowcaseWindow, '_spawn_enrich', lambda self, index, meta: None)
        win = ctx.infowindow.ShowcaseWindow('FuseShowcaseWindow.xml', '/addon/path', 'Default', '1080i')
        win._skin_xml = 'FuseShowcaseWindow.xml'
        win.metas = [_make_meta('tt1', 'One', imdbRating='6.1', runtime='90 min', releaseInfo='2020',
                                description='A plot.')]

        win.onInit()

        assert win.getControl(fuse.HERO_STARS).image == 'fuse_stars_06.png'
        assert win.getControl(fuse.HERO_FACTS).label.endswith('2020  •  90 min')
        assert 'Ends at' in win.getControl(fuse.HERO_SCORES).label


def test_open_showcase_picks_the_fuse_file_when_the_look_is_on(monkeypatch):
    from tests.test_infowindow import _RELOAD_MODULE_NAMES as info_reload

    with install_kodi_stubs(reload=info_reload + ('lib.ui.fuse',), settings={'ui_fuse': 'true'}) as ctx:
        built = []
        monkeypatch.setattr(ctx.infowindow.ShowcaseWindow, 'start',
                            lambda self, metas, **kw: built.append(self._skin_xml))
        ctx.infowindow.open_showcase([{'id': 'tt1', 'name': 'One'}])
        assert built == ['FuseShowcaseWindow.xml']


def test_every_fuse_card_has_a_mirror_image():
    """Each poster and wide card is drawn twice: the art, and the same
    art flipped under it with the fade over it."""
    for name in ('FuseHomeWindow.xml', 'FuseHubWindow.xml', 'FuseShowcaseWindow.xml'):
        with open(os.path.join(_SKIN, name), encoding='utf-8') as handle:
            text = handle.read()
        assert 'flipy="true"' in text, name
        assert text.count('fuse_reflect_fade.png') >= text.count('flipy="true"') // 2, name


# --- the episode page in the Fuse file ------------------------------------------

def _fuse_detail(monkeypatch, meta, progress=None):
    from tests.test_detailwindow import _RELOAD_MODULE_NAMES as detail_reload

    stack = install_kodi_stubs(reload=detail_reload + ('lib.ui.fuse',))
    ctx = stack.__enter__()
    win = ctx.detailwindow.DetailWindow('FuseDetailWindow.xml', '/addon/path', 'Default', '1080i')
    win._skin_xml = 'FuseDetailWindow.xml'
    monkeypatch.setattr(ctx.detailwindow.DetailWindow, '_episode_progress',
                        staticmethod(lambda stype, sid, vid: (progress or {}).get(vid)))
    win.start(meta, 'series')
    return stack, ctx, win


_SHOW = {
    'id': 'tt2788316', 'name': 'Shogun', 'logo': 'https://img/logo.png',
    'videos': [
        {'id': 'e1', 'season': 1, 'episode': 1, 'title': 'Anjin', 'released': '2024-02-27T00:00:00.000Z',
         'overview': 'Destinies converge.', 'runtime': '71 min'},
        {'id': 'e2', 'season': 1, 'episode': 2, 'title': 'Servants of Two Masters',
         'released': '2024-02-27T00:00:00.000Z', 'runtime': 60},
    ],
}


def test_fuse_episode_rows_read_like_the_reference(monkeypatch):
    stack, ctx, win = _fuse_detail(monkeypatch, _SHOW, progress={
        'e1': {'position_ms': 95, 'duration_ms': 100}, 'e2': {'position_ms': 30, 'duration_ms': 100},
    })
    try:
        win.onInit()
        first, second = win.getControl(ctx.detailwindow.LIST).items
        assert first.getProperty('ep_title') == '1×01. Anjin'
        assert first.getProperty('runtime') == '1h 11m'
        assert second.getProperty('runtime') == '1h 0m'
        assert first.getProperty('aired') == '27/02/2024'
        assert first.getProperty('plot') == 'Destinies converge.'
        # Watched past 90%: a tick. Part-way: no tick (the bar shows).
        assert first.getProperty('watched') == '1' and second.getProperty('watched') == ''
    finally:
        stack.__exit__(None, None, None)


def test_fuse_episode_page_shows_the_logo_once_kodi_has_it(monkeypatch):
    stack, ctx, win = _fuse_detail(monkeypatch, _SHOW)
    try:
        ctx.env.cached_textures = None  # everything is cached
        win.onInit()
        assert win.getProperty('HeroLogo') == 'https://img/logo.png'
    finally:
        stack.__exit__(None, None, None)


def test_fuse_episode_page_trailer_pill(monkeypatch):
    stack, ctx, win = _fuse_detail(monkeypatch, _SHOW)
    try:
        played = []
        monkeypatch.setattr(win, '_play_trailer', lambda: played.append(True))
        win.onClick(ctx.detailwindow.TRAILER)
        assert played == [True]
    finally:
        stack.__exit__(None, None, None)


@pytest.mark.parametrize('value, text', [('71 min', '1h 11m'), (54, '54m'), ('', ''), (None, ''), ('?', '')])
def test_short_runtime(value, text):
    with install_kodi_stubs(reload=('lib.ui.compat', 'lib.ui.detailwindow')):
        from lib.ui.detailwindow import _short_runtime
        assert _short_runtime(value) == text


def test_an_uncached_logo_is_asked_about_and_shown_once_its_host_answers(load_homewindow, monkeypatch):
    """rev17 showed a logo only when Kodi had already drawn it, so most
    titles showed text. Now the host is asked, and a yes shows the logo."""
    ctx = load_homewindow()
    import lib.ui.logocheck as logocheck

    ctx.env.cached_textures = set()  # Kodi has drawn nothing
    url = 'https://img/logo.png'
    assert ctx.homewindow._logo_known_good(url) is False
    assert url in logocheck.asked

    logocheck.remember(url, True)
    assert ctx.homewindow._logo_known_good(url) is True


# --- Continue reads like every other row ----------------------------------------

def test_continue_cards_fetch_their_meta_and_fill_the_hero(load_homewindow):
    ctx = load_homewindow()
    hw = ctx.homewindow
    import xbmcgui

    item = hw._continue_item({'id': 'tt1', 'type': 'movie', 'name': 'Dune', 'poster': 'p.jpg'})
    assert item.getProperty('needs_meta') == '1'
    win = hw.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(hw.CONTINUE_SHELF).addItems([item])
    win.getControl(hw.LIBRARY_SHELF).addItems([xbmcgui.ListItem('other')])
    win._library_meta_ready = [('movie', 'tt1', {
        'id': 'tt1', 'type': 'movie', 'name': 'Dune: Part One', 'description': 'A desert.',
        'background': 'https://img/b.jpg',
    })]

    hw._apply_library_meta(win)

    assert item.getProperty('hero_plot') == 'A desert.'
    assert item.getProperty('land') == 'https://img/b.jpg'
    assert item.getLabel() == 'Dune'  # the card keeps the name it was started as
    assert item.getProperty('meta_state') == 'done'


def test_a_continue_episode_takes_the_shows_hero_not_its_still(load_homewindow):
    ctx = load_homewindow()
    hw = ctx.homewindow
    import xbmcgui

    from lib.ui.urlutil import sized_image

    item = hw._continue_item({
        'id': 'tt0944947', 'type': 'series', 'name': 'Game of Thrones',
        'poster': 'https://img/still.jpg', 'description': 'already here',
        'video_id': 'tt0944947:1:3',
    })
    # An episode always asks for the show, and does not blow its
    # record's picture up to the hero while it waits.
    assert item.getProperty('needs_meta') == '1'
    assert item.getProperty('fanart') == ''
    assert item.getProperty('hero_fill') == ''
    assert 'tt0944947/1/3' in item.getProperty('land')  # the card keeps the still

    win = hw.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(hw.CONTINUE_SHELF).addItems([item])
    win.getControl(hw.LIBRARY_SHELF).addItems([xbmcgui.ListItem('other')])
    win._library_meta_ready = [('series', 'tt0944947', {
        'id': 'tt0944947', 'type': 'series', 'name': 'Game of Thrones',
        'description': 'Nine noble families.', 'background': 'https://img/got_bg.jpg',
        'logo': 'https://img/got_logo.png', 'releaseInfo': '2011-2019',
        'videos': [{'id': 'tt0944947:1:3', 'season': 1, 'episode': 3,
                    'title': 'Lord Snow', 'overview': 'Jon impresses Tyrion.'}],
    })]
    hw._apply_library_meta(win)

    assert item.getProperty('fanart') == sized_image('https://img/got_bg.jpg', 'backdrop')
    assert item.getProperty('hero_fill') == ''
    assert item.getProperty('hero_logo') == 'https://img/got_logo.png'
    assert item.getProperty('hero_title') == 'Game of Thrones'
    lines = item.getProperty('hero_meta').split('\n')
    assert lines[0] == 'S1E3 \u00b7 Lord Snow'
    assert '2011' in item.getProperty('hero_meta')
    assert item.getProperty('hero_plot') == 'Jon impresses Tyrion.'
    assert 'tt0944947/1/3' in item.getProperty('land')


def test_episode_label_for_reads_the_show_videos(load_homewindow):
    hw = load_homewindow().homewindow
    meta = {'videos': [{'id': 'tt1:2:5', 'name': 'Five', 'description': 'Plot.'}]}
    assert hw.episode_label_for(meta, 'tt1:2:5') == ('S2E5 \u00b7 Five', 'Plot.')
    assert hw.episode_label_for(meta, 'tt1:2:6') == ('S2E6', '')
    assert hw.episode_label_for(meta, 'tt1') == ('', '')
    assert hw.episode_label_for(meta, None) == ('', '')


def test_a_failed_meta_fetch_is_tried_again_later(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    hw = ctx.homewindow
    item = hw._poster_item({'id': 'tt1', 'type': 'movie', 'name': 'Dune'}, sparse=True)
    win = hw.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(hw.LIBRARY_SHELF).addItems([item])
    win._library_meta_ready = [('movie', 'tt1', None)]
    hw._apply_library_meta(win)
    assert item.getProperty('meta_state').startswith('failed:')

    started = []
    monkeypatch.setattr(hw.threading, 'Thread', lambda **kw: type('T', (), {'start': lambda self: started.append(1)})())
    hw._schedule_library_meta(win, item)
    assert started == []  # too soon
    import time as _time
    item.setProperty('meta_state', 'failed:%d' % int(_time.time() - 60))
    hw._schedule_library_meta(win, item)
    assert started == [1]
