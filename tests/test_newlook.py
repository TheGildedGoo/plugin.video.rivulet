"""Hero rendering and shared Home helpers for the single Home."""
import contextlib
import os
import time
import xml.etree.ElementTree as ET

import pytest

from lib.ui.playbackmeta import new_look_hero_parts
from tests.kodistubs import install_kodi_stubs
from tests.test_newhome import (
    _RELOAD_MODULE_NAMES,
    _THREE,
    _FakeStore,
    _patch_library,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIN = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i')
_MEDIA = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', 'media')


@pytest.fixture
def load_homewindow():
    """`load_homewindow(settings=None)`: fresh Kodi stubs, lib.ui.newlook included."""
    with contextlib.ExitStack() as stack:
        def _load(settings=None, localized=None):
            ctx = stack.enter_context(install_kodi_stubs(
                reload=_RELOAD_MODULE_NAMES,
                settings=settings,
                localized=localized,
            ))
            ctx.homewindow = ctx.newhome
            return ctx

        yield _load


def _ids(name):
    root = ET.parse(os.path.join(_SKIN, name)).getroot()
    return {int(c.get('id')) for c in root.iter('control') if c.get('id')}


# --- the files ---------------------------------------------------------------


def test_new_home_declares_every_control_the_window_code_uses(load_homewindow):
    """The fake window raises on an unknown id, and so does Kodi: every
    control id lib/ui/newhome.py and lib/ui/newlook.py name is in the file."""
    ctx = load_homewindow()
    newhome = ctx.newhome
    newlook = ctx.newlook
    from lib.ui.posterwarm import WARM_SLOTS

    declared = _ids('NewHomeWindow.xml')
    used = {
        newhome.BACKGROUND, newhome.STATUS_LABEL, newhome.BROWSE_LIST, newhome.TOOLS_LIST,
        newhome.HERO_TITLE, newhome.HERO_META, newhome.HERO_PLOT, newhome.HERO_LOGO,
        newhome.HERO_FILL, newhome.CONTINUE_SHELF, newhome.LIBRARY_SHELF,
        newhome.BTN_SEARCH, newhome.BTN_ADDONS, newhome.BTN_SETTINGS, newhome.BTN_SIGNIN,
        newlook.HERO_FACTS, newlook.HERO_SCORES, newlook.HERO_STARS,
    }
    used |= {list_id for _action, list_id, _label in newhome._SHELVES}
    used |= {label_id for _action, _list_id, label_id in newhome._SHELVES}
    used |= {counter for _list_id, _prop, counter in newhome._ROW_COUNTERS}
    used |= set(newhome.LOGO_WARM_SLOTS) | set(WARM_SLOTS)
    assert not used - declared, sorted(used - declared)


def test_every_texture_the_new_home_names_is_shipped():
    for name in ('NewHomeWindow.xml',):
        root = ET.parse(os.path.join(_SKIN, name)).getroot()
        for texture in root.iter():
            if texture.tag not in ('texture', 'texturefocus', 'texturenofocus'):
                continue
            value = (texture.text or '').strip()
            if value and not value.startswith('$'):
                assert os.path.isfile(os.path.join(_MEDIA, value)), value
    for half in range(11):
        assert os.path.isfile(os.path.join(_MEDIA, 'newlook_stars_%02d.png' % half))


def test_the_newlook_hero_has_no_bar():
    with open(os.path.join(_SKIN, 'NewHomeWindow.xml'), encoding='utf-8') as handle:
        text = handle.read()
    assert 'hero_bar.png' not in text
    assert 'newlook_fade_left.png' in text and 'newlook_fade_bottom.png' in text


# --- picking the file --------------------------------------------------------


# --- the hero lines ----------------------------------------------------------

def test_hero_parts_split_scores_from_facts():
    text = 'Rotten Tomatoes 94%\nMetascore 71\nIMDb 7.4\n2025\n1h 52m\nThriller, Mystery'
    stars, facts, scores = new_look_hero_parts(text)
    assert stars == 7  # 7.4 of 10 is three and a half stars
    assert facts == ['2025', '1h 52m', 'Thriller, Mystery']
    assert scores == [('IMDb', '7.4'), ('RT', '94%'), ('MC', '71')]


@pytest.mark.parametrize('text, stars', [
    ('2025', None), ('IMDb n/a\n2025', None), ('IMDb 10', 10), ('IMDb 0.2', 0), ('IMDb 8.75/10', 9),
])
def test_hero_parts_stars(text, stars):
    assert new_look_hero_parts(text)[0] == stars


def test_hero_parts_keep_an_unknown_line_as_a_fact():
    assert new_look_hero_parts('Ended\n\n2019')[1] == ['Ended', '2019']


def test_hero_lines_join_facts_and_end_scores_with_the_end_time(load_homewindow, monkeypatch):
    load_homewindow()
    from lib.ui import newlook

    monkeypatch.setattr(newlook, '_clock_format', lambda: '%H:%M')
    now = time.mktime((2026, 10, 17, 20, 36, 0, 0, 0, -1))
    stars, facts, scores = newlook.hero_lines('IMDb 7.4\nRotten Tomatoes 88%\n2025\n1h 52m', '112', now=now)
    assert stars == 'newlook_stars_07.png'
    assert facts == '2025  •  1h 52m'
    assert scores == [('IMDb', '7.4'), ('RT', '88%'), ('Ends at', 'Ends at 22:28')]


def test_no_runtime_no_end_time(load_homewindow):
    load_homewindow()
    from lib.ui import newlook

    assert newlook.ends_at('') == '' and newlook.ends_at(None) == '' and newlook.ends_at('0') == ''
    assert all(kind != 'Ends at' for kind, _value in newlook.hero_lines('IMDb 7', '')[2])


def test_twelve_hour_clock_drops_the_leading_zero(load_homewindow, monkeypatch):
    load_homewindow()
    from lib.ui import newlook

    monkeypatch.setattr(newlook, '_clock_format', lambda: '%I:%M %p')
    now = time.mktime((2026, 10, 17, 20, 0, 0, 0, 0, -1))
    assert newlook.ends_at('65', now=now) == '9:05 PM'


# --- Home in the new-look file ---------------------------------------------------

def _newlook_hero(ctx, meta, plot='A storm-chaser returns.', runtime='112', logo=''):
    import xbmcgui
    win = ctx.homewindow.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('Hollow Tide')
    item.setProperties({
        'hero_title': 'Hollow Tide', 'hero_meta': meta, 'hero_plot': plot,
        'hero_runtime': runtime, 'fanart': 'https://img/b.jpg', 'sid': 'tt1', 'stype': 'movie',
        'hero_logo': logo,
    })
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])
    win.setFocusId(ctx.homewindow.CONTINUE_SHELF)
    return win


def test_newlook_home_paints_stars_facts_and_scores(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    from lib.ui import newlook

    win = _newlook_hero(ctx, 'IMDb 7.4\n2025\n1h 52m\nThriller')
    ctx.homewindow.paint_hero(win)

    assert win.getControl(newlook.HERO_STARS).image == 'newlook_stars_07.png'
    assert win.getControl(newlook.HERO_FACTS).label == '•  2025  •  1h 52m  •  Thriller'
    assert win.getControl(newlook.HERO_IMDB).label == '[COLOR B3EDEDED]IMDb[/COLOR] 7.4'
    assert 'Ends at' in win.getControl(newlook.HERO_END).label


def test_newlook_stack_ends_on_the_same_line_above_the_row(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    from lib.ui import newlook

    long_plot = 'word ' * 120
    win = _newlook_hero(ctx, 'IMDb 7.4\n2025', plot=long_plot)
    ctx.homewindow.paint_hero(win)
    scores = win.getControl(newlook.HERO_SCORES)
    assert scores.y + scores.height == newlook._STACK['bottom']
    plot = win.getControl(ctx.homewindow.HERO_PLOT)
    assert plot.height <= 3 * 30 + 20  # three lines at most
    tall_logo_top = win.getControl(ctx.homewindow.HERO_LOGO).y

    short = _newlook_hero(ctx, 'IMDb 7.4\n2025', plot='Short.')
    ctx.homewindow.paint_hero(short)
    # A short plot moves the title down instead of leaving a gap.
    assert short.getControl(ctx.homewindow.HERO_LOGO).y > tall_logo_top


def test_newlook_facts_start_at_the_margin_without_stars(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    from lib.ui import newlook

    win = _newlook_hero(ctx, '2025\n1h 52m', runtime='')
    ctx.homewindow.paint_hero(win)
    assert win.getControl(newlook.HERO_STARS).image == ''
    facts = win.getControl(newlook.HERO_FACTS)
    assert facts.label == '2025  •  1h 52m' and facts.x == newlook._STACK['left']
    assert win.getControl(newlook.HERO_SCORES).visible is False


def test_poster_items_carry_the_runtime_in_minutes(load_homewindow):
    ctx = load_homewindow()
    item = ctx.homewindow._poster_item({'id': 'tt1', 'type': 'movie', 'name': 'X', 'runtime': '112 min'})
    assert item.getProperty('hero_runtime') == '112'
    assert ctx.homewindow._poster_item({'id': 'tt2', 'name': 'Y'}).getProperty('hero_runtime') == ''


def test_newlook_home_builds_its_rows(load_homewindow, monkeypatch):
    """The whole build runs against the new-look file: every control Home
    touches exists there (the fake raises on an unknown id)."""
    ctx = load_homewindow()
    store = _FakeStore(auth={'authKey': 'k', 'user': {'email': 'a@b.c'}})
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: store)
    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', lambda *args: [])
    _patch_library(monkeypatch, ctx, _THREE)
    win = ctx.homewindow.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.onInit()
    ctx.homewindow._switch_tab(win, 'mystuff')
    sids = [i.getProperty('sid') for i in win.getControl(ctx.homewindow.LIBRARY_SHELF).items]
    assert sids[:3] == ['tt1', 'tt2', 'tt3']


# --- switching looks ---------------------------------------------------------





def test_every_new_home_card_has_a_mirror_image():
    """Each poster and wide card is drawn twice: the art, and the same
    art flipped under it with the fade over it."""
    for name in ('NewHomeWindow.xml',):
        with open(os.path.join(_SKIN, name), encoding='utf-8') as handle:
            text = handle.read()
        assert 'flipy="true"' in text, name
        assert text.count('newlook_reflect_fade.png') >= text.count('flipy="true"') // 2, name




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
    win = hw.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
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

    win = hw.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
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
    win = hw.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
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


def _home_menu(ctx, monkeypatch, pick):
    import lib.ui.dependencies as dependencies
    import lib.ui.dialogs as dialogs

    class _Store:
        def get_auth(self):
            return None

    shown = []
    opened = []
    monkeypatch.setattr(dependencies, 'get_store', lambda: _Store())
    monkeypatch.setattr(dialogs, 'choose', lambda heading, rows: shown.append(rows) or pick)
    monkeypatch.setattr(ctx.homewindow, '_open_child', lambda window, opener: opened.append(opener) or False)
    return shown, opened


def test_a_series_card_on_continue_offers_go_to_series(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    hw = ctx.homewindow
    shown, opened = _home_menu(ctx, monkeypatch, 0)
    item = hw._continue_item({'id': 'tt9253284', 'type': 'series', 'name': 'Andor', 'video_id': 'tt9253284:1:3'})
    win = hw.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
    hw._offer_library(win, item, hw.CONTINUE_SHELF)
    assert shown == [['STR30514', 'STR30517', 'STR30499']]
    assert len(opened) == 1

    import lib.ui.detailwindow as detailwindow
    pages = []
    monkeypatch.setattr(detailwindow, 'open_detail', lambda stype, sid, **kw: pages.append((stype, sid, kw)) or False)
    opened[0]()
    # The show's page, without landing on the episode the card resumes.
    assert pages == [('series', 'tt9253284', {})]


def test_a_movie_on_continue_or_a_series_elsewhere_has_no_go_to_series(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    hw = ctx.homewindow
    shown, opened = _home_menu(ctx, monkeypatch, -1)
    win = hw.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
    movie = hw._continue_item({'id': 'tt1', 'type': 'movie', 'name': 'Dune'})
    hw._offer_library(win, movie, hw.CONTINUE_SHELF)
    series = hw._poster_item({'id': 'tt2', 'type': 'series', 'name': 'Andor'})
    hw._offer_library(win, series, hw.LIBRARY_SHELF)
    assert shown == [['STR30517', 'STR30499'], ['STR30499']]
    assert opened == []
