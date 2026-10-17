# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Tests for lib.ui.homewindow: HomeWindow, Rivulet's custom entry-point
screen, exercised against the
shared fake xbmc/xbmcgui stubs in tests/kodistubs (no real Kodi runtime, no
network).

lib.ui.homewindow imports xbmcgui and lib.ui.uicommon at module scope, so
load_homewindow reloads lib.ui.compat/lib.ui.uicommon/lib.ui.router/
lib.ui.homewindow fresh together. HomeWindow.onClick()'s 'discover'/
'search'/'mystuff'/'addons' handlers lazily `from lib.ui.catalogpicker
import open_catalog_picker` / `from lib.ui.searchwindow import
open_search` / `from lib.ui.mystuff import open_my_stuff` / `from
lib.ui.addonswindow import open_addons` at call time, so
lib.ui.catalogpicker/lib.ui.searchwindow/lib.ui.mystuff/
lib.ui.addonswindow are reloaded too (same reason tests/test_views.py
reloads lib.ui.infowindow: to get a handle - `ctx.catalogpicker`/`ctx.
searchwindow`/`ctx.mystuff`/`ctx.addonswindow` - whose functions
this file monkeypatches, and to have install_kodi_stubs clean their
sys.modules entries back up at teardown so no later test file observes
them bound to a dead test's fakes).

HomeWindow.onInit()/onClick()/onAction() are called directly here, never
through a real modal event loop, exactly like tests/test_infowindow.py drives
ShowcaseWindow: the fake WindowXML.doModal() is a no-op counter, and
getControl()/setFocusId() are plain in-memory fakes.

HomeWindow.xml's actual skin rendering is Kodi-skin-engine-only and is NOT,
and cannot be, exercised by this suite.
"""
import contextlib
import os
import threading

import pytest

from tests.kodistubs import install_kodi_stubs

#: The real addon directory, for the few assertions that must check what
#: actually ships rather than what the stubbed path helper returns.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_RELOAD_MODULE_NAMES = (
    'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.router', 'lib.ui.homewindow',
    'lib.ui.catalogpicker', 'lib.ui.searchwindow', 'lib.ui.mystuff', 'lib.ui.addonswindow',
    'lib.ui.gridwindow', 'lib.ui.detailwindow', 'lib.ui.hubwindow',
    'lib.ui.dialogs', 'lib.ui.dependencies', 'lib.ui.libraryaction',
    'lib.ui.player', 'lib.ui.streamswindow', 'lib.ui.views',
)


#: Catalog descriptors covering every type row, for _menu_items()'s
#: auto-hide check (a row whose types nothing publishes is left out).
_ALL_TYPE_ADDONS = [{'transportUrl': 'https://a/manifest.json', 'manifest': {'catalogs': [
    {'type': 'movie', 'id': 'm'}, {'type': 'series', 'id': 's'}, {'type': 'anime', 'id': 'a'},
]}}]


class _FakeStore:
    """Fake `lib.store.Store` for HomeWindow.onInit(): `get_enabled_addons()`
    supplies the catalogs the type rows auto-hide against (defaulting to
    one of every type), and `get_auth()`/`get_progress_entries()`
    (defaulting to logged out with nothing cached) are what the real
    `lib.ui.mystuff.has_content()` reads - tests that care about the My
    Stuff row's gating monkeypatch `has_content()` itself instead of
    populating these."""

    def __init__(self, auth=None, addons=None, progress_entries=None):
        self._auth = auth
        self._addons = _ALL_TYPE_ADDONS if addons is None else addons
        self._progress_entries = [] if progress_entries is None else progress_entries

    def get_auth(self):
        return self._auth

    def get_addons(self):
        return self._addons

    def get_enabled_addons(self):
        return [a for a in self._addons if not (a.get('flags') or {}).get('disabled')]

    def get_progress_entries(self):
        return self._progress_entries


class _FakeVersionStore:
    """Fake `lib.store.Store`: only `get_last_seen_version()`/
    `set_last_seen_version()` matter to `_notify_if_updated()`.
    `raise_on_get` stands in for a Store I/O failure (e.g. a corrupt or
    unwritable `last_version.json`), which `_notify_if_updated()` must
    swallow rather than let take down the home screen."""

    def __init__(self, last_seen=None, raise_on_get=False):
        self._last_seen = last_seen
        self._raise_on_get = raise_on_get
        self.set_calls = []

    def get_last_seen_version(self):
        if self._raise_on_get:
            raise RuntimeError('store unavailable')
        return self._last_seen

    def set_last_seen_version(self, version):
        self.set_calls.append(version)
        self._last_seen = version


@pytest.fixture
def load_homewindow():
    """Factory fixture: `load_homewindow(addon_info=None, localized=None)`
    installs fresh stubs (via tests.kodistubs.install_kodi_stubs) reloading
    lib.ui.compat/lib.ui.uicommon/lib.ui.router/lib.ui.homewindow/
    lib.ui.catalogpicker/lib.ui.searchwindow, and returns a namespace with
    `.homewindow`, `.compat`, `.router`, `.catalogpicker`, `.searchwindow`,
    and `.env`. `localized` overrides FakeAddon's default 'STR<id>' string
    marker - needed for string id 30022 ("Logged in as %s"), which
    HomeWindow's status label formats with `%`, the same shared string
    `lib.ui.views.login()` shows as a post-login notification.
    Every call is torn down automatically, in reverse order, at test end.
    """
    with contextlib.ExitStack() as stack:
        def _load(addon_info=None, localized=None, settings=None):
            return stack.enter_context(install_kodi_stubs(
                reload=_RELOAD_MODULE_NAMES,
                addon_info=addon_info,
                localized=localized,
                settings=settings,
            ))

        yield _load


def _window_with_focused_action(homewindow_mod, action, control_id=None):
    """Build a fresh HomeWindow whose browse list has one focused row
    carrying `action` as its 'action' Property - the shape onClick() reads,
    without needing a real onInit()/Store round-trip."""
    import xbmcgui
    win = homewindow_mod.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('label')
    item.setProperty('action', action)
    control_id = homewindow_mod.BROWSE_LIST if control_id is None else control_id
    win.getControl(control_id).addItems([item])
    return win


def _patch_library(monkeypatch, ctx, entries=None):
    """Home's signed-in paint reads the account library. The real call
    opens a socket the suite forbids; tests pass the records they care
    about and never touch the network."""
    monkeypatch.setattr(
        ctx.mystuff, '_fetch_library_entries', lambda store, _entries=list(entries or []): _entries,
    )
    # A real fetch opens the addon client. These tests assert the row,
    # not Cinemeta. The one that does is explicit about the answer.
    monkeypatch.setattr(ctx.homewindow, '_fetch_library_meta', lambda stype, sid: None)


# ---------------------------------------------------------------------------
# _menu_items()
# ---------------------------------------------------------------------------


def test_menu_items_lists_the_type_chips_with_label_and_icon(load_homewindow):
    """Continue and Library are poster rows. Search, Add-ons and Settings
    are the top-bar buttons. The chip list is only the type rows."""
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(_ALL_TYPE_ADDONS)

    assert [item.getProperty('action') for item in items] == [
        'movies', 'series', 'anime',
    ]
    assert [item.getLabel() for item in items] == [
        'STR30213', 'STR30214', 'STR30215',
    ]
    assert [item.art['icon'] for item in items] == [
        ctx.compat.addon_media_path('movies.png'),
        ctx.compat.addon_media_path('series.png'),
        ctx.compat.addon_media_path('anime.png'),
    ]
    assert [item.getProperty('subtitle') for item in items] == [
        'STR30216', 'STR30217', 'STR30218',
    ]


def test_menu_items_has_no_continue_or_library_card(load_homewindow):
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(_ALL_TYPE_ADDONS)

    actions = [item.getProperty('action') for item in items]
    assert 'mystuff' not in actions
    assert 'watchlater' not in actions
    assert 'search' not in actions


def test_menu_items_hides_a_type_row_its_setting_turns_off(load_homewindow):
    ctx = load_homewindow(settings={'home_show_series': 'false'})

    items = ctx.homewindow._menu_items(_ALL_TYPE_ADDONS)

    actions = [item.getProperty('action') for item in items]
    assert 'series' not in actions
    assert 'movies' in actions and 'anime' in actions


def test_menu_items_hides_a_type_row_nothing_publishes(load_homewindow):
    # Only movie catalogs installed - Series and Anime would open empty.
    addons = [{'transportUrl': 'https://a/manifest.json',
               'manifest': {'catalogs': [{'type': 'movie', 'id': 'm'}]}}]
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(addons)

    assert [item.getProperty('action') for item in items] == [
        'movies',
    ]


def test_menu_items_groups_tv_catalogs_under_the_series_row(load_homewindow):
    # An addon publishing only "tv" catalogs still gets a Series row -
    # linear/live channels are television, not a row of their own.
    addons = [{'transportUrl': 'https://a/manifest.json',
               'manifest': {'catalogs': [{'type': 'tv', 'id': 'ch'}]}}]
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(addons)

    assert [item.getProperty('action') for item in items] == [
        'series',
    ]


def test_menu_items_with_no_addons_shows_no_type_rows(load_homewindow):
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items([])

    assert [item.getProperty('action') for item in items] == []


def test_menu_items_classifies_dotted_anime_subtypes_into_anime_row(load_homewindow):
    # Stremio's dotted-subtype convention: 'anime.movie'/'anime.series'
    # specialize 'anime' and must still join the Anime row, not go unrouted.
    addons = [{'transportUrl': 'https://a/manifest.json',
               'manifest': {'catalogs': [{'type': 'anime.movie', 'id': 'm'},
                                          {'type': 'anime.series', 'id': 's'}]}}]
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(addons)

    assert [item.getProperty('action') for item in items] == [
        'anime',
    ]


def test_menu_items_type_matching_is_case_insensitive(load_homewindow):
    # A capitalized 'TV' must join Series exactly like lowercase 'tv' does.
    addons = [{'transportUrl': 'https://a/manifest.json',
               'manifest': {'catalogs': [{'type': 'TV', 'id': 'ch'}]}}]
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(addons)

    assert [item.getProperty('action') for item in items] == [
        'series',
    ]


def test_menu_items_shows_other_row_for_a_type_no_curated_row_claims(load_homewindow):
    # The real-world case: an addon publishing an arbitrary type like
    # "Porn" has no curated row and must land in the catch-all instead.
    addons = [{'transportUrl': 'https://a/manifest.json',
               'manifest': {'catalogs': [{'type': 'Porn', 'id': 'p'}]}}]
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(addons)

    assert [item.getProperty('action') for item in items] == [
        'other',
    ]
    other = items[0]
    assert other.getLabel() == 'STR30227'
    assert other.getProperty('subtitle') == 'STR30228'


def test_menu_items_omits_other_row_when_only_curated_types_are_installed(load_homewindow):
    # Cinemeta-only (movie/series/anime): the common case must not change -
    # no remainder exists, so 'other' stays out exactly like today.
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(_ALL_TYPE_ADDONS)

    assert [item.getProperty('action') for item in items] == [
        'movies', 'series', 'anime',
    ]


def test_menu_items_hides_other_row_its_setting_turns_off(load_homewindow):
    addons = [{'transportUrl': 'https://a/manifest.json',
               'manifest': {'catalogs': [{'type': 'Porn', 'id': 'p'}]}}]
    ctx = load_homewindow(settings={'home_show_other': 'false'})

    items = ctx.homewindow._menu_items(addons)

    assert [item.getProperty('action') for item in items] == []


# ---------------------------------------------------------------------------
# _status_text()
# ---------------------------------------------------------------------------


def test_status_text_says_signed_in_without_the_address(load_homewindow):
    """#19: Home is a shared TV. The address is not on the screen; it is
    in Settings > Account."""
    ctx = load_homewindow(localized={30488: 'Signed in'})

    text = ctx.homewindow._status_text({'authKey': 'x', 'user': {'email': 'me@example.com', 'name': 'Me'}})

    assert text == '[COLOR FF38BDF8]\u25cf[/COLOR] Signed in'
    assert 'me@example.com' not in text
    assert 'Me' not in text.replace('[COLOR', '')


def test_home_keeps_the_signed_in_address_in_settings(load_homewindow, monkeypatch):
    """The address moves to the read-only Account setting, refreshed on
    each Home paint and cleared when signed out. An unchanged value is not
    written again (Kodi rewrites the whole settings file per write)."""
    ctx = load_homewindow(localized={30488: 'Signed in'})
    _patch_library(monkeypatch, ctx, [])
    auth = {'authKey': 'x', 'user': {'email': 'me@example.com'}}
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=auth))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    writes = []
    real_set = ctx.compat.ADDON.setSetting

    def _set(key, value):
        writes.append((key, value))
        return real_set(key, value)

    monkeypatch.setattr(ctx.compat.ADDON, 'setSetting', _set)
    win.onInit()
    assert ctx.compat.ADDON.getSetting('account_user') == 'me@example.com'
    assert writes.count(('account_user', 'me@example.com')) == 1
    win._build()
    assert writes.count(('account_user', 'me@example.com')) == 1
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    win._build()
    assert ctx.compat.ADDON.getSetting('account_user') == ''


def test_status_text_reports_not_logged_in_when_auth_is_none(load_homewindow):
    ctx = load_homewindow()

    text = ctx.homewindow._status_text(None)

    assert text == '[COLOR 57EEF3F6]\u25cf[/COLOR] STR30190'
    assert 'STR30190' in text


# ---------------------------------------------------------------------------
# HomeWindow.onInit()
# ---------------------------------------------------------------------------


def test_oninit_shows_the_library_row_when_authenticated(load_homewindow, monkeypatch):
    """A signed-in profile with a saved title draws that title on the
    Library row. Continue stays hidden when nothing is in progress, which
    is the case this used to get wrong: the old card opened every band."""
    ctx = load_homewindow(localized={30022: 'Logged in as %s'})
    _patch_library(monkeypatch, ctx, [{
        '_id': 'tt9', 'name': 'Saved', 'type': 'movie', 'poster': 's', 'removed': False,
    }])
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth={'authKey': 'x'}))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert [item.getProperty('sid') for item in win.getControl(ctx.homewindow.LIBRARY_SHELF).items] == ['tt9']
    assert win.getProperty('shelf_continue') == ''
    assert win.getProperty('shelf_library') == '1'
    assert win.getProperty('HomeSignedOut') == ''
    assert [item.getProperty('action') for item in win.getControl(ctx.homewindow.BROWSE_LIST).items] == [
        'movies', 'series', 'anime',
    ]
    # Focus lands on the library poster. There is no backdrop yet, so
    # the hero is that poster, full-bleed, not the addon fanart and not
    # a letterboxed poster on a black plate.
    assert win.getControl(ctx.homewindow.BACKGROUND).image == 's'
    assert win.getProperty('HeroFill') == '1'
    assert win.getControl(ctx.homewindow.HERO_FILL).image == 's'
    assert win.getControl(ctx.homewindow.STATUS_LABEL).label == '[COLOR FF38BDF8]\u25cf[/COLOR] STR30488'
    assert win.getFocusId() == ctx.homewindow.LIBRARY_SHELF


def test_library_focus_fetches_meta_and_paints_the_backdrop(load_homewindow, monkeypatch):
    """The library record is a poster. On focus, Cinemeta (the meta
    addon) supplies the backdrop and the description the other rows
    already show. The fetch does not block the window opening."""
    import time

    ctx = load_homewindow()
    import xbmcgui
    _patch_library(monkeypatch, ctx, [{
        '_id': 'tt9', 'name': 'Saved', 'type': 'movie', 'poster': 's', 'removed': False,
    }])
    started = threading.Event()
    release = threading.Event()

    def _meta(stype, sid):
        assert (stype, sid) == ('movie', 'tt9')
        started.set()
        release.wait(2)
        return {
            'id': 'tt9', 'type': 'movie', 'name': 'Saved',
            'poster': 's', 'background': 'wide.jpg',
            'description': 'A desert planet.', 'year': '2024',
        }

    monkeypatch.setattr(ctx.homewindow, '_fetch_library_meta', _meta)
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth={'authKey': 'x'}))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    opened = time.time()
    win.onInit()
    assert time.time() - opened < 0.5
    assert started.is_set()
    # Still the poster, covering the frame, while the request is in flight.
    assert win.getProperty('HeroFill') == '1'
    assert win.getControl(ctx.homewindow.BACKGROUND).image == 's'
    release.set()
    ctx.homewindow._join_library_meta(win)
    win.onAction(xbmcgui.Action(999))

    assert win.getControl(ctx.homewindow.BACKGROUND).image == 'wide.jpg'
    assert win.getProperty('HeroFill') == ''
    assert win.getControl(ctx.homewindow.HERO_FILL).image == ''
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Saved'
    assert 'desert planet' in win.getControl(ctx.homewindow.HERO_PLOT).text
    assert win.getControl(30026).visible is True
    item = win.getControl(ctx.homewindow.LIBRARY_SHELF).items[0]
    assert item.getProperty('needs_meta') == ''
    assert item.getProperty('fanart') == 'wide.jpg'


def test_library_focus_keeps_a_full_bleed_poster_when_meta_has_no_backdrop(load_homewindow, monkeypatch):
    """No backdrop in the answer: the poster still covers the hero, and
    the description and the ratings show on the bar."""
    ctx = load_homewindow()
    import xbmcgui
    _patch_library(monkeypatch, ctx, [{
        '_id': 'tt9', 'name': 'Saved', 'type': 'movie', 'poster': 's', 'removed': False,
    }])

    def _meta(stype, sid):
        return {
            'id': 'tt9', 'type': 'movie', 'name': 'Saved', 'poster': 's',
            'description': 'Only a poster.', 'year': '2021',
        }

    calls = []

    def _counting(stype, sid):
        calls.append(sid)
        return _meta(stype, sid)

    monkeypatch.setattr(ctx.homewindow, '_fetch_library_meta', _counting)
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth={'authKey': 'x'}))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.onInit()
    ctx.homewindow._join_library_meta(win)
    win.onAction(xbmcgui.Action(999))
    win.onAction(xbmcgui.Action(999))

    assert calls == ['tt9']
    assert win.getProperty('HeroFill') == '1'
    assert win.getControl(ctx.homewindow.HERO_FILL).image == 's'
    assert 'Only a poster' in win.getControl(ctx.homewindow.HERO_PLOT).text


def test_oninit_hides_library_row_when_not_authenticated(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert win.getProperty('HomeSignedOut') == '1'
    actions = [item.getProperty('action') for item in win.getControl(ctx.homewindow.BROWSE_LIST).items]
    assert 'library' not in actions
    assert win.getControl(ctx.homewindow.STATUS_LABEL).label == '[COLOR 57EEF3F6]\u25cf[/COLOR] STR30190'


def test_oninit_status_label_says_signed_in_and_settings_hold_the_email(load_homewindow, monkeypatch):
    ctx = load_homewindow(localized={30488: 'Signed in'})
    auth = {'authKey': 'x', 'user': {'email': 'me@example.com', 'name': 'Me'}}
    _patch_library(monkeypatch, ctx)
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=auth))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert win.getControl(ctx.homewindow.STATUS_LABEL).label == '[COLOR FF38BDF8]\u25cf[/COLOR] Signed in'
    assert ctx.compat.ADDON.getSetting('account_user') == 'me@example.com'


def test_oninit_settings_fall_back_to_the_name_when_email_is_absent(load_homewindow, monkeypatch):
    ctx = load_homewindow(localized={30488: 'Signed in'})
    auth = {'authKey': 'x', 'user': {'name': 'Me'}}
    _patch_library(monkeypatch, ctx)
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=auth))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert win.getControl(ctx.homewindow.STATUS_LABEL).label == '[COLOR FF38BDF8]\u25cf[/COLOR] Signed in'
    assert ctx.compat.ADDON.getSetting('account_user') == 'Me'


def test_oninit_omits_type_row_supplied_only_by_a_disabled_addon(load_homewindow, monkeypatch):
    """A catalog type published only by a disabled add-on must not get a
    row: onInit() must fan out through get_enabled_addons(), not
    get_addons() (which would include it)."""
    ctx = load_homewindow()
    addons = [
        {'transportUrl': 'https://a/manifest.json',
         'manifest': {'catalogs': [{'type': 'movie', 'id': 'm'}]}},
        {'transportUrl': 'https://b/manifest.json', 'flags': {'disabled': True},
         'manifest': {'catalogs': [{'type': 'anime', 'id': 'a'}]}},
    ]
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(addons=addons))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    actions = [
        item.getProperty('action')
        for item in win.getControl(ctx.homewindow.BROWSE_LIST).items
    ]
    assert 'anime' not in actions
    assert 'movies' in actions


# ---------------------------------------------------------------------------
# HomeWindow.onAction()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('action_id', [9, 10, 92], ids=['nav-back', 'previous-menu', 'backspace'])
def test_onaction_back_actions_close_the_window(load_homewindow, action_id):
    ctx = load_homewindow()
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onAction(xbmcgui.Action(action_id))

    assert win.closed is True


def test_onaction_non_back_action_does_not_close(load_homewindow):
    ctx = load_homewindow()
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onAction(xbmcgui.Action(1))

    assert win.closed is False


# ---------------------------------------------------------------------------
# HomeWindow.onClick() - dispatch to one of the module-level _open_*()
# ---------------------------------------------------------------------------


def test_onclick_ignores_control_ids_other_than_list(load_homewindow):
    ctx = load_homewindow()
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onClick(9999)

    assert win.closed is False


def test_onclick_list_with_no_focused_item_does_not_crash(load_homewindow):
    ctx = load_homewindow()
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert win.closed is False


def test_onclick_focused_item_with_unrecognized_action_does_not_crash_or_close(load_homewindow):
    ctx = load_homewindow()
    win = _window_with_focused_action(ctx.homewindow, 'not-a-real-action')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert win.closed is False


def test_onclick_type_row_closes_when_catalog_picker_returns_true(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    calls = []
    monkeypatch.setattr(
        ctx.hubwindow, 'open_hub',
        lambda types=None, heading='', action='': (calls.append((types, heading, action)), True)[1],
    )
    win = _window_with_focused_action(ctx.homewindow, 'movies')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    # The picker is filtered to the row's own types and headed by its label.
    assert calls == [(ctx.homewindow.TYPE_ROW_TYPES['movies'], 'STR30213', 'movies')]
    assert win.closed is True


def test_onclick_type_row_stays_open_when_catalog_picker_returns_false(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.hubwindow, 'open_hub', lambda types=None, heading='', action='': False)
    win = _window_with_focused_action(ctx.homewindow, 'movies')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert win.closed is False


def test_onclick_series_row_passes_its_own_types(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    calls = []
    monkeypatch.setattr(
        ctx.hubwindow, 'open_hub',
        lambda types=None, heading='', action='': (calls.append(types), False)[1],
    )
    win = _window_with_focused_action(ctx.homewindow, 'series')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert calls == [ctx.homewindow.TYPE_ROW_TYPES['series']]
    assert 'tv' in calls[0]


def test_onclick_other_row_passes_only_the_unclaimed_remainder(load_homewindow, monkeypatch):
    # 'other' has no fixed type set - it must be computed live from what's
    # installed, and must NOT also carry movie/series/anime along with it.
    ctx = load_homewindow()
    addons = [{'transportUrl': 'https://a/manifest.json', 'manifest': {'catalogs': [
        {'type': 'movie', 'id': 'm'}, {'type': 'Porn', 'id': 'p'},
    ]}}]
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(addons=addons))
    calls = []
    monkeypatch.setattr(
        ctx.hubwindow, 'open_hub',
        lambda types=None, heading='', action='': (calls.append(types), False)[1],
    )
    win = _window_with_focused_action(ctx.homewindow, 'other')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert calls == [{'porn'}]


def test_onclick_search_closes_when_open_search_returns_true(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.searchwindow, 'open_search', lambda: True)
    win = _window_with_focused_action(ctx.homewindow, 'search')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert win.closed is True


def test_onclick_search_stays_open_when_open_search_returns_false(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.searchwindow, 'open_search', lambda: False)
    win = _window_with_focused_action(ctx.homewindow, 'search')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert win.closed is False


def test_onclick_addons_never_closes_home(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    calls = []
    monkeypatch.setattr(ctx.addonswindow, 'open_addons', lambda: calls.append(1))
    win = _window_with_focused_action(ctx.homewindow, 'addons')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert calls == [1]
    assert win.closed is False


def test_onclick_settings_opens_native_settings_without_closing(load_homewindow):
    ctx = load_homewindow()
    win = _window_with_focused_action(ctx.homewindow, 'settings')

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert ctx.env.opened_settings is True
    assert win.closed is False


def test_onclick_browse_list_opens_its_type_row(load_homewindow, monkeypatch):
    """Movies lives on the browse list after the split. A click there
    must take the same picker path a click on the old single list did."""
    ctx = load_homewindow()
    calls = []
    monkeypatch.setattr(
        ctx.hubwindow, 'open_hub',
        lambda types=None, heading='', action='': (calls.append(types), False)[1],
    )
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('Movies')
    item.setProperty('action', 'movies')
    win.getControl(ctx.homewindow.BROWSE_LIST).addItems([item])

    win.onClick(ctx.homewindow.BROWSE_LIST)

    assert calls == [ctx.homewindow.TYPE_ROW_TYPES['movies']]
    assert win.closed is False


def test_onclick_search_button_opens_search(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.searchwindow, 'open_search', lambda: True)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onClick(ctx.homewindow.BTN_SEARCH)

    assert win.closed is True


def test_oninit_keeps_the_top_bar_when_nothing_publishes_a_type(load_homewindow, monkeypatch):
    """No type chip means the browse list is hidden. Search, Add-ons and
    Settings stay on the top bar instead of moving onto that list."""
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(addons=[]))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert win.getControl(ctx.homewindow.BROWSE_LIST).items == []
    assert win.getProperty('HomeBrowse') == ''
    assert win.getProperty('HomeSignedOut') == '1'
    assert win.getProperty('shelf_library') == '1'


# ---------------------------------------------------------------------------
# _notify_if_updated()
# ---------------------------------------------------------------------------


def test_notify_if_updated_first_run_records_version_and_notifies_nothing(load_homewindow):
    ctx = load_homewindow(addon_info={'version': '1.0.0'})
    store = _FakeVersionStore(last_seen=None)

    ctx.homewindow._notify_if_updated(store)

    assert store.set_calls == ['1.0.0']
    assert ctx.env.notifications == []


def test_notify_if_updated_changed_version_notifies_once_and_records(load_homewindow):
    ctx = load_homewindow(addon_info={'version': '1.1.0'}, localized={30184: 'Updated to version %s'})
    store = _FakeVersionStore(last_seen='1.0.0')

    ctx.homewindow._notify_if_updated(store)

    assert store.set_calls == ['1.1.0']
    assert len(ctx.env.notifications) == 1
    heading, message, icon, time_ms = ctx.env.notifications[0]
    assert message == 'Updated to version 1.1.0'
    # Opening the addon after an update must not play the notification chime.
    assert ctx.env.notification_sounds == [False]


def test_notify_if_updated_unchanged_version_notifies_nothing(load_homewindow):
    ctx = load_homewindow(addon_info={'version': '1.0.0'})
    store = _FakeVersionStore(last_seen='1.0.0')

    ctx.homewindow._notify_if_updated(store)

    assert store.set_calls == []
    assert ctx.env.notifications == []


def test_notify_if_updated_swallows_store_exception(load_homewindow):
    ctx = load_homewindow(addon_info={'version': '1.0.0'})
    store = _FakeVersionStore(last_seen=None, raise_on_get=True)

    ctx.homewindow._notify_if_updated(store)  # must not raise

    assert ctx.env.notifications == []


# ---------------------------------------------------------------------------
# open_home()
# ---------------------------------------------------------------------------


def test_open_home_builds_the_window_against_the_skin_path_and_blocks_on_domodal(
    load_homewindow, monkeypatch,
):
    ctx = load_homewindow(addon_info={'path': '/addon/path'})
    captured = {}

    class RecordingWindow(ctx.homewindow.HomeWindow):
        def __init__(self, *args, **kwargs):
            captured['init_args'] = args
            super().__init__(*args, **kwargs)
            captured['instance'] = self

    monkeypatch.setattr(ctx.homewindow, 'HomeWindow', RecordingWindow)

    ctx.homewindow.open_home()

    assert captured['init_args'] == ('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    assert captured['instance'].modal_calls == 1


def test_open_home_closes_the_window_exactly_once_and_reraises_when_domodal_raises(
    load_homewindow, monkeypatch,
):
    ctx = load_homewindow(addon_info={'path': '/addon/path'})
    captured = {}

    class ExplodingWindow(ctx.homewindow.HomeWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.close_calls = 0
            captured['window'] = self

        def close(self):
            self.close_calls += 1
            super().close()

        def doModal(self):
            # Stands in for a crash inside onInit() while the modal loop is
            # running - self.close() (the window's own, normal-path close)
            # never gets a chance to run.
            raise RuntimeError('onInit blew up')

    monkeypatch.setattr(ctx.homewindow, 'HomeWindow', ExplodingWindow)

    # default.py wraps open_home() itself and falls back to the recovery
    # home directory on ANY exception - that contract requires the
    # exception to keep propagating unchanged, not be swallowed here.
    with pytest.raises(RuntimeError, match='onInit blew up'):
        ctx.homewindow.open_home()

    win = captured['window']
    assert win.close_calls == 1
    assert win.closed is True


def test_open_home_calls_notify_if_updated_with_the_store(load_homewindow, monkeypatch):
    ctx = load_homewindow(addon_info={'path': '/addon/path'})
    store = _FakeVersionStore(last_seen='1.0.0')
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: store)
    calls = []
    monkeypatch.setattr(ctx.homewindow, '_notify_if_updated', calls.append)

    ctx.homewindow.open_home()

    assert calls == [store]


def test_open_home_still_opens_the_window_when_the_store_raises(load_homewindow, monkeypatch):
    ctx = load_homewindow(addon_info={'path': '/addon/path'})
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeVersionStore(raise_on_get=True))
    captured = {}

    class RecordingWindow(ctx.homewindow.HomeWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured['instance'] = self

    monkeypatch.setattr(ctx.homewindow, 'HomeWindow', RecordingWindow)

    ctx.homewindow.open_home()

    assert captured['instance'].modal_calls == 1
    assert ctx.env.notifications == []


def test_open_home_holds_a_ui_heartbeat_for_the_whole_session_and_clears_it_after(
    load_homewindow, monkeypatch,
):
    ctx = load_homewindow(addon_info={'path': '/addon/path'})
    seen = {}

    class RecordingWindow(ctx.homewindow.HomeWindow):
        def doModal(self):
            # While Home is up a second interpreter must see a live owner.
            seen['alive'] = ctx.uicommon.ui_owner_alive()
            seen['threads'] = [t.name for t in threading.enumerate()]
            super().doModal()

    monkeypatch.setattr(ctx.homewindow, 'HomeWindow', RecordingWindow)

    ctx.homewindow.open_home()

    assert seen['alive'] is True
    assert 'rivulet-ui-heartbeat' in seen['threads']
    # Cleared on exit, thread joined: a later launch is a genuine one.
    assert ctx.uicommon.ui_owner_alive() is False
    assert 'rivulet-ui-heartbeat' not in [t.name for t in threading.enumerate()]
    assert ctx.env.window_properties[10000].get('rivulet.ui.heartbeat') is None


def test_open_home_clears_the_heartbeat_when_the_window_raises(load_homewindow, monkeypatch):
    ctx = load_homewindow(addon_info={'path': '/addon/path'})

    class ExplodingWindow(ctx.homewindow.HomeWindow):
        def doModal(self):
            raise RuntimeError('onInit blew up')

    monkeypatch.setattr(ctx.homewindow, 'HomeWindow', ExplodingWindow)

    with pytest.raises(RuntimeError, match='onInit blew up'):
        ctx.homewindow.open_home()

    assert ctx.uicommon.ui_owner_alive() is False
    assert 'rivulet-ui-heartbeat' not in [t.name for t in threading.enumerate()]


def test_every_menu_row_has_an_icon_shipped_for_it(load_homewindow):
    """`_menu_items()` derives each chip's icon from its action name
    (`addon_media_path('%s.png' % action)`), so a chip whose file is
    missing renders with an empty icon slot.

    `settings.png` is not a Home chip. The recovery directory
    (`lib/ui/views.py`) still draws it. Continue and Library are poster
    rows and do not ship a card glyph.
    """
    media = os.path.join(_REPO_ROOT, 'resources', 'media')
    actions = [action for _string_id, action in load_homewindow().homewindow._MENU]
    used = set(actions) | {'settings'}

    missing = [a for a in actions if not os.path.isfile(os.path.join(media, '%s.png' % a))]
    assert not missing, 'Home rows with no resources/media/<action>.png: %s' % missing

    unused = sorted(
        name for name in os.listdir(media)
        if name.endswith('.png') and name[:-len('.png')] not in used
    )
    assert not unused, 'icons in resources/media nothing draws: %s' % unused


# ---------------------------------------------------------------------------
# _menu_items() - "Continue watching" row
# ---------------------------------------------------------------------------


def test_menu_items_starts_with_movies(load_homewindow):
    ctx = load_homewindow()

    items = ctx.homewindow._menu_items(_ALL_TYPE_ADDONS)

    assert items[0].getProperty('action') == 'movies'
    assert items[0].getLabel() == 'STR30213'
    assert 'mystuff' not in [item.getProperty('action') for item in items]


def test_continue_row_is_in_progress_and_library_row_is_the_library(load_homewindow, monkeypatch):
    """Local progress lands on Continue. A saved title with no progress
    lands on Library and not on Continue. That split is what the old
    Continue card did not do: it opened every band, library included."""
    ctx = load_homewindow()
    library = [
        {'_id': 'tt1', 'name': 'Dune', 'type': 'movie', 'poster': 'p', 'removed': False},
        {'_id': 'tt9', 'name': 'Saved', 'type': 'movie', 'poster': 's', 'removed': False},
    ]
    _patch_library(monkeypatch, ctx, library)
    progress = [{
        'type': 'movie', 'id': 'tt1', 'position_ms': 50000, 'duration_ms': 100000,
        'updated_at': '2020-01-02T00:00:00Z',
    }]
    monkeypatch.setattr(
        ctx.homewindow, 'get_store',
        lambda: _FakeStore(auth={'authKey': 'k'}, progress_entries=progress),
    )
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    continue_ids = [item.getProperty('sid') for item in win.getControl(ctx.homewindow.CONTINUE_SHELF).items]
    library_ids = [item.getProperty('sid') for item in win.getControl(ctx.homewindow.LIBRARY_SHELF).items]
    assert continue_ids == ['tt1']
    assert 'tt9' not in continue_ids
    assert library_ids == ['tt1', 'tt9']


def test_library_row_keeps_every_title_past_twelve(load_homewindow, monkeypatch):
    """The ring stopped on the twelfth poster because the row was cut
    there. The panel already scrolls with the items; the account list
    is the whole row."""
    ctx = load_homewindow()
    library = [
        {
            '_id': 'tt%d' % index, 'name': 'Title %d' % index,
            'type': 'movie', 'poster': 'p%d' % index, 'removed': False,
        }
        for index in range(13)
    ]
    _patch_library(monkeypatch, ctx, library)
    monkeypatch.setattr(
        ctx.homewindow, 'get_store', lambda: _FakeStore(auth={'authKey': 'k'}),
    )
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    library_ids = [
        item.getProperty('sid') for item in win.getControl(ctx.homewindow.LIBRARY_SHELF).items
    ]
    assert library_ids == ['tt%d' % index for index in range(13)]


def test_continue_row_includes_in_progress_library_state(load_homewindow, monkeypatch):
    """A title watched in the Stremio app has no local progress.json row.
    Its libraryItem state is still in progress, so it belongs on Continue.
    A removed-and-not-temp tombstone does not."""
    ctx = load_homewindow()
    library = [
        {
            '_id': 'tt3', 'name': 'App', 'type': 'movie', 'poster': 'a',
            'removed': True, 'temp': True,
            'state': {'timeOffset': 40000, 'duration': 100000},
        },
        {
            '_id': 'tt4', 'name': 'Gone', 'type': 'movie', 'poster': 'g',
            'removed': True, 'temp': False,
            'state': {'timeOffset': 40000, 'duration': 100000},
        },
    ]
    _patch_library(monkeypatch, ctx, library)
    monkeypatch.setattr(
        ctx.homewindow, 'get_store', lambda: _FakeStore(auth={'authKey': 'k'}),
    )
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    continue_ids = [item.getProperty('sid') for item in win.getControl(ctx.homewindow.CONTINUE_SHELF).items]
    library_ids = [item.getProperty('sid') for item in win.getControl(ctx.homewindow.LIBRARY_SHELF).items]
    assert continue_ids == ['tt3']
    assert 'tt4' not in continue_ids
    assert 'tt3' not in library_ids
    assert 'tt4' not in library_ids


def test_onclick_continue_poster_opens_detail(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    opened = []
    monkeypatch.setattr(
        ctx.detailwindow, 'open_detail',
        lambda ctype, sid: opened.append((ctype, sid)) or True,
    )
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('Dune')
    item.setProperty('sid', 'tt1')
    item.setProperty('stype', 'movie')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert opened == [('movie', 'tt1')]
    assert win.closed is True


def test_oninit_hides_continue_when_the_setting_is_off(load_homewindow, monkeypatch):
    ctx = load_homewindow(settings={'home_show_mystuff': 'false'})
    library = [{'_id': 'tt1', 'name': 'Dune', 'type': 'movie', 'poster': 'p', 'removed': False}]
    _patch_library(monkeypatch, ctx, library)
    progress = [{
        'type': 'movie', 'id': 'tt1', 'position_ms': 50000, 'duration_ms': 100000,
        'updated_at': '2020-01-02T00:00:00Z',
    }]
    monkeypatch.setattr(
        ctx.homewindow, 'get_store',
        lambda: _FakeStore(auth={'authKey': 'k'}, progress_entries=progress),
    )
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert win.getProperty('shelf_continue') == ''
    assert win.getProperty('shelf_library') == '1'


# ---------------------------------------------------------------------------
# home_show_continue -> home_show_mystuff migration
# ---------------------------------------------------------------------------


def test_a_disabled_continue_row_stays_disabled_after_the_rename(load_homewindow):
    """The merged row took a new setting id, so without this anyone who had
    deliberately turned the old row OFF would silently get the new one back
    on."""
    ctx = load_homewindow(settings={'home_show_continue': 'false'})

    ctx.homewindow._migrate_mystuff_setting()

    assert ctx.compat.ADDON.getSetting('home_show_mystuff') == 'false'
    assert ctx.compat.ADDON.getSetting('home_show_continue') == ''


def test_an_enabled_continue_row_does_not_overwrite_the_new_setting(load_homewindow):
    """A true old value carries nothing across - and must not stomp on a
    newer choice.

    The pre-existing `home_show_mystuff` here is what gives the test teeth:
    without it, a migration that wrongly wrote `'true'` would look
    identical to one that correctly did nothing.
    """
    ctx = load_homewindow(settings={
        'home_show_continue': 'true',      # the old row was left on
        'home_show_mystuff': 'false',      # ...but the new one has since been turned off
    })

    ctx.homewindow._migrate_mystuff_setting()

    assert ctx.compat.ADDON.getSetting('home_show_mystuff') == 'false'
    assert ctx.compat.ADDON.getSetting('home_show_continue') == ''


def test_migration_is_idempotent(load_homewindow):
    """Clearing the old key is what makes a second launch a no-op - it must
    not re-apply an old value over a choice the user has since changed."""
    ctx = load_homewindow(settings={'home_show_continue': 'false'})

    ctx.homewindow._migrate_mystuff_setting()
    ctx.compat.ADDON.setSetting('home_show_mystuff', 'true')   # user turns it back on
    ctx.homewindow._migrate_mystuff_setting()

    assert ctx.compat.ADDON.getSetting('home_show_mystuff') == 'true'


def test_migration_survives_a_broken_settings_write(load_homewindow, monkeypatch):
    """A cosmetic migration must never stop Home from opening."""
    ctx = load_homewindow(settings={'home_show_continue': 'false'})

    def _boom(*_args, **_kwargs):
        raise RuntimeError('settings unwritable')

    monkeypatch.setattr(ctx.compat.ADDON, 'setSetting', _boom)

    ctx.homewindow._migrate_mystuff_setting()   # must not raise


def test_onclick_library_signin_poster_opens_login(load_homewindow, monkeypatch):
    """RevRivulet's auth.json is empty on a fresh profile even when the
    Stremio app is signed in. The Library row's Sign in cell opens the
    existing login dialog."""
    ctx = load_homewindow()
    calls = []
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))

    import lib.ui.views as views
    monkeypatch.setattr(views, 'login', lambda: calls.append('login'))
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('Sign in')
    item.setProperty('action', 'signin')
    win.getControl(ctx.homewindow.LIBRARY_SHELF).addItems([item])

    win.onClick(ctx.homewindow.LIBRARY_SHELF)

    assert calls == ['login']
    assert win.closed is False


def test_oninit_puts_signin_on_the_library_row_when_logged_out(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert win.getProperty('HomeSignedOut') == '1'
    assert win.getProperty('shelf_library') == '1'
    assert win.getControl(ctx.homewindow.LIBRARY_SHELF).items[0].getProperty('action') == 'signin'


def test_onaction_paints_the_hero_from_the_focused_poster(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('Dune')
    item.setProperties({
        'hero_title': 'Dune',
        'hero_meta': '2021',
        'hero_plot': 'A boy and a desert.',
        'fanart': 'https://img/dune.jpg',
        'sid': 'tt1',
        'stype': 'movie',
    })
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])
    win.setFocusId(ctx.homewindow.CONTINUE_SHELF)

    win.onAction(xbmcgui.Action(1))

    assert win.closed is False
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Dune'
    assert win.getControl(ctx.homewindow.HERO_META).text == '2021'
    assert win.getControl(ctx.homewindow.HERO_PLOT).text == 'A boy and a desert.'
    assert win.getControl(ctx.homewindow.BACKGROUND).image == 'https://img/dune.jpg'


def _hero_with_facts(ctx, facts, meta='2021'):
    import json

    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('Shawshank')
    item.setProperties({
        'hero_title': 'Shawshank',
        'hero_meta': meta,
        'hero_plot': 'A man and a wall.',
        'hero_facts': json.dumps(facts),
        'fanart': 'https://img/shawshank.jpg',
        'sid': 'tt0111161',
        'stype': 'movie',
    })
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])
    win.setFocusId(ctx.homewindow.CONTINUE_SHELF)
    return win


def test_cached_ratings_replace_the_hero_panel(load_homewindow, monkeypatch, tmp_path):
    """A key plus a fresh cache rebuilds the right-quarter panel. The
    key itself never lands in the label."""
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    import lib.ui.ratingsched as ratingsched
    from lib.stremio.ratings import RatingsCache

    cache = RatingsCache(str(tmp_path / 'ratings.json'))
    cache.store('tt0111161', {
        'rottenTomatoes': '91%',
        'metascore': '95',
        'imdbRating': '8.8',
    })
    scheduled = []
    monkeypatch.setattr(ratingsched, '_keys', lambda: ('secret-omdb', ''))
    monkeypatch.setattr(ratingsched, '_get_cache', lambda: cache)
    monkeypatch.setattr(ratingsched, '_schedule', lambda *args: scheduled.append(args))
    win = _hero_with_facts(ctx, {'id': 'tt0111161', 'year': 2021})

    import xbmcgui
    win.onAction(xbmcgui.Action(1))

    text = win.getControl(ctx.homewindow.HERO_META).text
    assert text == 'Rotten Tomatoes 91%\nMetascore 95\nIMDb 8.8\n2021'
    assert 'secret-omdb' not in text
    assert scheduled == []


def test_an_empty_ratings_key_keeps_the_catalog_line(load_homewindow, monkeypatch):
    """No key means no fetch. The catalog's IMDb line stays, and the
    missing Rotten Tomatoes and Metascore lines stay hidden."""
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    import lib.ui.ratingsched as ratingsched

    def _forbidden(*_args, **_kwargs):
        raise AssertionError('a fetch was scheduled with no key')

    monkeypatch.setattr(ratingsched, '_schedule', _forbidden)
    win = _hero_with_facts(ctx, {'id': 'tt0111161', 'year': 2021, 'imdbRating': '9.3'})

    import xbmcgui
    win.onAction(xbmcgui.Action(1))

    assert win.getControl(ctx.homewindow.HERO_META).text == '2021'
    logged = ' '.join(msg for msg, _level in ctx.env.log_calls)
    assert 'secret-omdb' not in logged


def test_a_ratings_miss_keeps_the_catalog_line_and_schedules(load_homewindow, monkeypatch, tmp_path):
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    import lib.ui.ratingsched as ratingsched
    from lib.stremio.ratings import RatingsCache

    cache = RatingsCache(str(tmp_path / 'ratings.json'))
    scheduled = []
    monkeypatch.setattr(ratingsched, '_keys', lambda: ('secret-omdb', ''))
    monkeypatch.setattr(ratingsched, '_get_cache', lambda: cache)
    monkeypatch.setattr(ratingsched, '_schedule', lambda *args: scheduled.append(args[0]))
    win = _hero_with_facts(ctx, {'id': 'tt0111161', 'year': 2021})

    import xbmcgui
    win.onAction(xbmcgui.Action(1))

    assert win.getControl(ctx.homewindow.HERO_META).text == '2021'
    assert scheduled == ['tt0111161']
    logged = ' '.join(msg for msg, _level in ctx.env.log_calls)
    assert 'secret-omdb' not in logged


def test_a_blank_focused_item_does_not_clear_the_hero(load_homewindow, monkeypatch):
    """Scrolling past the posters the row actually holds used to hand
    paint_hero a blank item. That cleared the title and the plot, and
    the row looked dead. A blank item keeps the hero that was there."""
    ctx = load_homewindow()
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth=None))
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = xbmcgui.ListItem('Dune')
    item.setProperties({
        'hero_title': 'Dune',
        'hero_meta': '2021',
        'hero_plot': 'A boy and a desert.',
        'fanart': 'https://img/dune.jpg',
        'sid': 'tt1',
    })
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])
    win.setFocusId(ctx.homewindow.CONTINUE_SHELF)
    win.onAction(xbmcgui.Action(1))
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Dune'

    win.getControl(ctx.homewindow.BROWSE_LIST).addItems([xbmcgui.ListItem()])
    win.setFocusId(ctx.homewindow.BROWSE_LIST)
    win.onAction(xbmcgui.Action(1))

    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Dune'
    assert win.getControl(ctx.homewindow.HERO_PLOT).text == 'A boy and a desert.'


def test_right_near_the_end_appends_the_rest_of_the_catalog_page(load_homewindow):
    ctx = load_homewindow()
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    first = xbmcgui.ListItem('One')
    first.setProperty('sid', 'tt1')
    first.setProperty('hero_title', 'One')
    second = xbmcgui.ListItem('Two')
    second.setProperty('sid', 'tt2')
    second.setProperty('hero_title', 'Two')
    more = xbmcgui.ListItem('More')
    more.setProperty('action', 'movies')
    shelf = win.getControl(ctx.homewindow._SHELVES[0][1])
    shelf.addItems([first, second, more])
    shelf.selected_index = 1
    win.setFocusId(ctx.homewindow._SHELVES[0][1])
    win._shelf_more = {
        'movies': {
            'pending': [{'id': 'tt3', 'name': 'Three', 'type': 'movie', 'poster': 'p'}],
            'exhausted': False,
        },
    }

    win.onAction(xbmcgui.Action(2))

    sids = [item.getProperty('sid') for item in shelf.items]
    assert sids == ['tt1', 'tt2', 'tt3', '']
    assert shelf.items[-1].getProperty('action') == 'movies'
    assert shelf.selected_index == 1
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Two'


def test_a_new_catalog_page_is_fetched_off_the_remote_and_appended_on_the_noop(
    load_homewindow, monkeypatch,
):
    """Page two used to be fetched inside onAction, holding the row for
    the addon's timeout. It is fetched on a worker; the noop appends it."""
    ctx = load_homewindow()
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    items = []
    for index in range(1, 4):
        item = xbmcgui.ListItem('T%d' % index)
        item.setProperty('sid', 'tt%d' % index)
        item.setProperty('hero_title', 'T%d' % index)
        items.append(item)
    shelf = win.getControl(ctx.homewindow._SHELVES[0][1])
    shelf.addItems(items)
    shelf.selected_index = 2
    win.setFocusId(ctx.homewindow._SHELVES[0][1])
    win._shelf_more = {'movies': {'pending': [], 'exhausted': False, 'gen': None}}
    calls = []

    def fake_pull(state, room):
        calls.append(room)
        return [{'id': 'tt4', 'name': 'Four', 'type': 'movie', 'poster': 'p'}]

    monkeypatch.setattr(ctx.homewindow, '_pull_more', fake_pull)

    win.onAction(xbmcgui.Action(2))
    ctx.homewindow._join_shelf_extends(win)
    assert [item.getProperty('sid') for item in shelf.items] == ['tt1', 'tt2', 'tt3']
    assert 'Action(noop)' in ctx.env.executed_builtins

    win.onAction(xbmcgui.Action(0))

    assert [item.getProperty('sid') for item in shelf.items] == ['tt1', 'tt2', 'tt3', 'tt4']
    assert shelf.selected_index == 2
    assert len(calls) == 1


def test_resuming_a_row_does_not_fetch_page_one_again(load_homewindow, monkeypatch):
    """The resume used to rebuild the generator and discard its first page."""
    ctx = load_homewindow()
    requested = []

    def fake_fetch(transport, ctype, cid, extra=None):
        requested.append(list(extra or []))
        return [{'id': 'tt3', 'name': 'Three'}, {'id': 'tt1', 'name': 'One again'}]

    monkeypatch.setattr(ctx.views, '_fetch_catalog', fake_fetch)
    state = {
        'transport': 'https://addon.example/manifest.json',
        'manifest': {'id': 'x'},
        'catalog': {'type': 'movie', 'id': 'top', 'extra': [{'name': 'skip'}]},
        'extra': None,
        'metas': [{'id': 'tt1', 'name': 'One'}, {'id': 'tt2', 'name': 'Two'}],
        'pending': [],
        'gen': None,
        'exhausted': False,
    }

    added = ctx.homewindow._pull_more(state, 10)

    assert requested[0] == [('skip', 2)]
    assert [meta['id'] for meta in added] == ['tt3']


def test_focus_ring_sits_on_the_art_and_the_hero_does_not_overlap():
    """The ring used to be a larger plate inside a zoomed group, so it
    sat off the poster. The title band used to share its box with the
    year and the plot."""
    import os
    import xml.etree.ElementTree as ET

    path = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i', 'HomeWindow.xml')
    root = ET.parse(path).getroot()
    for cid, art_w, art_h in (('30040', 392, 220), ('30041', 200, 300)):
        focused = root.find(".//control[@id='%s']/focusedlayout" % cid)
        blob = ET.tostring(focused, encoding='unicode')
        assert 'zoom' not in blob
        images = [el for el in focused.findall('control') if el.get('type') == 'image']
        art = next(el for el in images if '$INFO' in (el.findtext('texture') or ''))
        stroke = next(el for el in images if (el.findtext('texture') or '').strip() == 'focus_stroke.png')
        for tag in ('left', 'top', 'width', 'height'):
            assert (art.findtext(tag) or '').strip() == (stroke.findtext(tag) or '').strip()
        assert (art.findtext('width') or '').strip() == str(art_w)
        assert (art.findtext('height') or '').strip() == str(art_h)
    title = root.find(".//control[@id='30020']")
    meta = root.find(".//control[@id='30021']")
    plot = root.find(".//control[@id='30022']")
    title_bottom = int(title.findtext('top')) + int(title.findtext('height'))
    plot_top = int(plot.findtext('top'))
    assert plot_top >= title_bottom
    assert plot_top <= title_bottom + 16
    assert int(meta.findtext('left')) >= 1440
    assert meta.get('type') == 'textbox'


def test_home_lists_declare_a_visible_focus_and_navigation():
    """Every remote move on Home has to land on a control whose focused
    state is visible, with a direction wired so the press is not a dead end.
    The top bar is a right-aligned grouplist and Settings is its last button."""
    import os
    import xml.etree.ElementTree as ET

    path = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i', 'HomeWindow.xml')
    root = ET.parse(path).getroot()
    assert root.find('defaultcontrol') is not None
    assert root.find(".//control[@id='30002']") is None
    bar = root.find(".//control[@id='30011']")
    assert bar is not None and bar.get('type') == 'grouplist'
    assert (bar.findtext('align') or '').strip() == 'right'
    buttons = [child for child in list(bar) if child.tag == 'control' and child.get('type') == 'button']
    assert [button.get('id') for button in buttons] == ['30073', '30070', '30071', '30072']
    missing = []
    for button in buttons:
        focus = button.find('texturefocus')
        idle = button.find('texturenofocus')
        if focus is None or idle is None:
            missing.append(button.get('id'))
            continue
        if (focus.get('colordiffuse') or '') == (idle.get('colordiffuse') or ''):
            missing.append('%s contrast' % button.get('id'))
        if button.find('ondown') is None:
            missing.append('%s ondown' % button.get('id'))
        if (button.findtext('texturefocus') or '').strip() != 'pill_fill.png':
            missing.append('%s pill' % button.get('id'))
    rows = root.find(".//control[@id='30001']")
    groups = [child for child in list(rows) if child.tag == 'control']
    assert groups and all(child.get('type') == 'group' for child in groups)
    first = [child.get('id') for child in list(groups[0]) if child.tag == 'control']
    assert first[0] == '30140' and first[1] == '30040'
    assert rows.find(".//control[@id='30010']") is None
    pills = root.find(".//control[@id='30010']")
    # One header row (#23): Right off the last pill crosses to the tools,
    # Left off the first tool crosses back, Up from the pills stays put,
    # and Down from either goes to the rows. Settings is where Right stops.
    assert (pills.findtext('onup') or '').strip() == '30010'
    assert (pills.findtext('onright') or '').strip() == '30011'
    assert (pills.findtext('ondown') or '').strip() == '30001'
    assert (bar.findtext('onleft') or '').strip() == '30010'
    assert (bar.findtext('onright') or '').strip() == '30072'
    assert (bar.findtext('ondown') or '').strip() == '30001'
    assert int(bar.findtext('top')) == int(pills.findtext('top')) + 4
    assert int(pills.findtext('left')) + int(pills.findtext('width')) <= int(bar.findtext('left'))
    # Off the top edge (#7).
    assert int(pills.findtext('top')) >= 100
    assert (rows.findtext('onup') or '').strip() == '30010'
    blob = ET.tostring(root, encoding='unicode')
    assert 'mask_poster.png' in blob and 'mask_land.png' in blob
    assert 'round_mask.png' not in blob
    focusable = [
        control for control in root.iter('control')
        if control.get('type') in ('list', 'panel') and control.get('id')
    ]
    assert focusable, 'Home has no focusable lists'
    for control in focusable:
        focused = control.find('focusedlayout')
        blob = ET.tostring(focused, encoding='unicode') if focused is not None else ''
        if 'FFFFFFFF' not in blob:
            missing.append(control.get('id'))
        for direction in ('onleft', 'onright'):
            if control.find(direction) is None:
                missing.append('%s %s' % (control.get('id'), direction))
        if control.get('type') == 'panel':
            for direction in ('onup', 'ondown'):
                if control.find(direction) is None:
                    missing.append('%s %s' % (control.get('id'), direction))
    assert not missing, 'Home focus gaps: %s' % missing


class _LibraryApi:
    def __init__(self, item=None):
        self.item = item
        self.put_calls = []

    def get_library_item(self, auth_key, item_id):
        return self.item

    def put_library_item(self, auth_key, item):
        self.put_calls.append((auth_key, item))


def test_context_menu_adds_a_poster_and_refreshes_library(load_homewindow, monkeypatch):
    """The menu button offers Add, pushes library_add_payload, and the
    Library row picks up the new record."""
    ctx = load_homewindow()
    saved = []

    def _fetch(store, _saved=saved):
        return list(_saved)

    monkeypatch.setattr(ctx.mystuff, '_fetch_library_entries', _fetch)
    store = _FakeStore(auth={'authKey': 'k', 'user': {'email': 'a@b.c'}})
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: store)
    monkeypatch.setattr(ctx.dependencies, 'get_store', lambda: store)
    api = _LibraryApi(item=None)

    def _put(auth_key, item, _saved=saved):
        api.put_calls.append((auth_key, item))
        _saved.append(item)

    api.put_library_item = _put
    monkeypatch.setattr(ctx.dependencies, 'get_api', lambda: api)
    monkeypatch.setattr(ctx.dialogs, 'choose', lambda heading, rows: 0)
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    poster = xbmcgui.ListItem('Dune')
    poster.setProperties({
        'sid': 'tt1', 'stype': 'movie', 'hero_title': 'Dune', 'thumbnail': 'p',
    })
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([poster])
    win.setFocusId(ctx.homewindow.CONTINUE_SHELF)

    win.onAction(xbmcgui.Action(117))

    assert api.put_calls
    assert api.put_calls[0][1]['removed'] is False
    assert api.put_calls[0][1]['_id'] == 'tt1'
    library = win.getControl(ctx.homewindow.LIBRARY_SHELF).items
    assert [item.getProperty('sid') for item in library] == ['tt1']


def _resume_poster(label, **props):
    import xbmcgui
    item = xbmcgui.ListItem(label)
    for key, value in props.items():
        item.setProperty(key, str(value))
    return item


def _click_continue(ctx, choice=None, stream=None, started=True, store_error=False):
    """Click one Continue poster. `choice` is what the dialog returns."""
    captured = {'choose': None, 'play': None, 'streams': None, 'detail': [], 'order': []}

    def fake_choose(heading, rows):
        captured['choose'] = (heading, list(rows))
        return -1 if choice is None else choice

    def fake_play(stream_obj, stype, sid, **kwargs):
        captured['order'].append('play')
        captured['play'] = (stream_obj, stype, sid, kwargs)
        return started

    def fake_wait(*_a, **_k):
        captured['order'].append('wait')
        return True, False

    def fake_end():
        captured['order'].append('end')

    def fake_streams(*args, **kwargs):
        captured['streams'] = (args, kwargs)

    def fake_detail(stype, sid, land_on=None):
        captured['detail'].append((stype, sid))
        captured['land_on'] = land_on
        return True

    class _Store:
        def get_last_stream(self, content_type, content_id, video_id=None):
            if store_error:
                raise OSError('unreadable')
            captured['lookup'] = (content_type, content_id, video_id)
            return stream

    monkeypatch = captured  # placeholder so the name exists; caller patches
    del monkeypatch
    return captured, fake_choose, fake_play, fake_wait, fake_end, fake_streams, fake_detail, _Store


def test_continue_series_back_closes_the_dialog_and_opens_nothing(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=None)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['choose'] == ('Show', ['Resume S1E3 from 12:04', 'Episode list'])
    assert captured['detail'] == []
    assert captured['play'] is None
    assert captured['streams'] is None
    assert win.closed is False


def _arm_continue(ctx, monkeypatch, choice=0, stream=None, started=True, store_error=False):
    captured, fake_choose, fake_play, fake_wait, fake_end, fake_streams, fake_detail, store_cls = (
        _click_continue(ctx, choice=choice, stream=stream, started=started, store_error=store_error)
    )
    monkeypatch.setattr(ctx.dialogs, 'choose', fake_choose)
    monkeypatch.setattr(ctx.player, 'play_direct', fake_play)
    monkeypatch.setattr(ctx.streamswindow, '_wait_for_playback_end', fake_wait)
    monkeypatch.setattr(ctx.uicommon, 'end_player_phase', fake_end)
    monkeypatch.setattr(ctx.streamswindow, 'open_streams', fake_streams)
    monkeypatch.setattr(ctx.detailwindow, 'open_detail', fake_detail)
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: store_cls())

    def fake_fetch(stype, sid, **_kwargs):
        captured['fetch'] = (stype, sid)
        return {
            'id': sid, 'name': 'Show', 'type': stype,
            'videos': [
                {'id': 'tt1:1:3', 'season': 1, 'episode': 3},
                {'id': 'tt1:1:4', 'season': 1, 'episode': 4},
            ],
        }

    monkeypatch.setattr(ctx.views, '_fetch_meta', fake_fetch)
    return captured


def _series_resume_item():
    return _resume_poster(
        'Show', sid='tt1', stype='series', band='resume', video_id='tt1:1:3',
        position_ms='724000', duration_ms='3600000', hero_title='Show',
        thumbnail='http://poster', fanart='http://fanart',
    )


def test_continue_series_episode_list_opens_detail_and_does_not_play(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=1)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['detail'] == [('series', 'tt1')]
    # The page opens on the episode the card is for, not season 1.
    assert captured['land_on'] == 'tt1:1:3'
    assert captured['play'] is None
    assert captured['streams'] is None
    assert win.closed is True


def test_continue_resume_replays_the_saved_stream_and_waits_out_playback(load_homewindow, monkeypatch):
    """Resume seeks to the saved offset, closes Home for the player, and
    does not return until playback has ended. That wait is what keeps
    stop-return from reopening Home on top of the picture."""
    ctx = load_homewindow()
    saved = {'url': 'https://cdn.example/ep.mp4', 'behaviorHints': {'filename': 'ep.mkv'}}
    captured = _arm_continue(ctx, monkeypatch, choice=0, stream=saved, started=True)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    stream, stype, sid, kwargs = captured['play']
    assert stream == saved
    assert (stype, sid) == ('series', 'tt1:1:3')
    assert kwargs['video_id'] == 'tt1:1:3'
    assert kwargs['resume_offset_ms'] == 724000
    assert kwargs['on_ready'] is ctx.uicommon.close_windows_for_playback
    assert kwargs['item_meta']['meta']['id'] == 'tt1'
    assert kwargs['item_meta']['meta']['videos'][1]['id'] == 'tt1:1:4'
    assert kwargs['item_meta']['art']['poster'] == 'http://poster'
    assert captured['fetch'] == ('series', 'tt1')
    assert captured['lookup'] == ('series', 'tt1', 'tt1:1:3')
    assert captured['order'] == ['play', 'wait', 'end']
    assert captured['streams'] is None
    assert captured['detail'] == []
    assert win.closed is False


def test_continue_resume_natural_end_rolls_into_up_next(load_homewindow, monkeypatch):
    """A Continue resume that plays through does not go straight Home.
    It joins the same Up next chain as a picker play. A user stop does
    not, which is the test above."""
    ctx = load_homewindow()
    saved = {'url': 'https://cdn.example/ep.mp4', 'behaviorHints': {}}
    captured = _arm_continue(ctx, monkeypatch, choice=0, stream=saved, started=True)

    def fake_wait(*_args, **_kwargs):
        captured['order'].append('wait')
        return True, True

    def fake_binge(*args, **kwargs):
        captured['order'].append('binge')
        captured['binge'] = (args, kwargs)
        return None

    monkeypatch.setattr(ctx.streamswindow, '_wait_for_playback_end', fake_wait)
    monkeypatch.setattr(ctx.streamswindow, '_try_binge_watch', fake_binge)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    # Home ends the phase when it comes back. The card's own phase
    # change is inside streamswindow and is not this test's fake.
    assert captured['order'] == ['play', 'wait', 'binge', 'end']
    assert captured['binge'][0][0] == 'series'
    assert captured['binge'][0][4] == 'tt1:1:3'
    assert captured['binge'][0][1]['videos'][1]['id'] == 'tt1:1:4'
    assert captured['streams'] is None
    assert win.closed is False


def test_continue_resume_opens_the_picker_when_the_stream_is_gone(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=0, stream=None)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['play'] is None
    args, kwargs = captured['streams']
    assert args[:2] == ('series', 'tt1:1:3')
    assert kwargs['video_id'] == 'tt1:1:3'
    assert kwargs['resume_offset_ms'] == 724000
    assert kwargs['meta']['id'] == 'tt1'
    assert captured['detail'] == []
    assert captured['order'] == []


def test_continue_resume_opens_the_picker_when_the_stream_fails(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    saved = {'url': 'https://cdn.example/gone.mp4'}
    captured = _arm_continue(ctx, monkeypatch, choice=0, stream=saved, started=False)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['order'] == ['play']
    assert captured['streams'][1]['resume_offset_ms'] == 724000
    assert captured['streams'][0][1] == 'tt1:1:3'


def test_continue_resume_stops_when_the_title_fetch_is_cancelled(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=0, stream={'url': 'https://cdn.example/ep.mp4'})
    monkeypatch.setattr(ctx.uicommon, 'run_cancellable', lambda *_a, **_k: ctx.uicommon.CANCELLED)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['play'] is None
    assert captured['streams'] is None
    assert captured['detail'] == []
    assert win.closed is False


def test_continue_resume_opens_the_picker_when_the_store_cannot_be_read(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=0, store_error=True)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([_series_resume_item()])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['play'] is None
    assert captured['streams'][1]['resume_offset_ms'] == 724000


def test_continue_movie_offers_resume_or_details(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=1)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = _resume_poster(
        'Dune', sid='tt1', stype='movie', band='resume',
        position_ms='50000', duration_ms='100000', hero_title='Dune',
    )
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['choose'] == ('Dune', ['Resume from 0:50', 'Details'])
    assert captured['detail'] == [('movie', 'tt1')]
    assert captured['play'] is None


def test_continue_next_up_still_opens_the_episode_list(load_homewindow, monkeypatch):
    """Finished episodes sit on the same row. They are not a resume."""
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=0)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = _resume_poster(
        'Show', sid='tt1', stype='series', band='next_up', video_id='tt1:1:3',
        position_ms='3500000', duration_ms='3600000',
    )
    win.getControl(ctx.homewindow.CONTINUE_SHELF).addItems([item])

    win.onClick(ctx.homewindow.CONTINUE_SHELF)

    assert captured['choose'] is None
    assert captured['detail'] == [('series', 'tt1')]
    assert captured['land_on'] == 'tt1:1:3'
    assert captured['play'] is None


def test_library_poster_does_not_ask_to_resume(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    captured = _arm_continue(ctx, monkeypatch, choice=0)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    item = _resume_poster(
        'Dune', sid='tt1', stype='movie', band='resume',
        position_ms='50000', duration_ms='100000',
    )
    win.getControl(ctx.homewindow.LIBRARY_SHELF).addItems([item])

    win.onClick(ctx.homewindow.LIBRARY_SHELF)

    assert captured['choose'] is None
    assert captured['detail'] == [('movie', 'tt1')]


def test_continue_row_carries_the_episode_and_the_offset(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    progress = [{
        'type': 'series', 'id': 'tt1', 'video_id': 'tt1:1:3', 'name': 'Show',
        'poster': 'p', 'position_ms': 724000, 'duration_ms': 3600000,
        'updated_at': '2020-01-02T00:00:00Z',
    }]
    monkeypatch.setattr(
        ctx.homewindow, 'get_store', lambda: _FakeStore(progress_entries=progress),
    )
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    item = win.getControl(ctx.homewindow.CONTINUE_SHELF).items[0]
    assert item.getProperty('sid') == 'tt1'
    assert item.getProperty('video_id') == 'tt1:1:3'
    assert item.getProperty('band') == 'resume'
    assert item.getProperty('position_ms') == '724000'
    assert item.getProperty('duration_ms') == '3600000'


# ---------------------------------------------------------------------------
# Coming back to Home: refresh what changed, keep the remote's place
# ---------------------------------------------------------------------------


def _built_home(ctx, monkeypatch, library, auth=None, progress=None):
    store = _FakeStore(auth=auth or {'authKey': 'k', 'user': {'email': 'a@b.c'}},
                       progress_entries=progress or [])
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: store)
    monkeypatch.setattr(ctx.homewindow, '_catalog_pages', lambda addons, enabled: ({}, {}))
    _patch_library(monkeypatch, ctx, library)
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.onInit()
    return win, store


_THREE = [
    {'_id': 'tt%d' % index, 'name': 'T%d' % index, 'type': 'movie', 'poster': 'p', 'removed': False}
    for index in (1, 2, 3)
]


def test_reopen_after_playback_keeps_the_poster_the_remote_was_on(load_homewindow, monkeypatch):
    """The reopen used to rebuild every row and land on Continue's first poster."""
    ctx = load_homewindow()
    win, _store = _built_home(ctx, monkeypatch, _THREE)
    library = win.getControl(ctx.homewindow.LIBRARY_SHELF)
    library.selectItem(2)
    win.setFocusId(ctx.homewindow.LIBRARY_SHELF)
    picked = library.getSelectedItem().getProperty('sid')

    win.onInit()

    assert win.getFocusId() == ctx.homewindow.LIBRARY_SHELF
    assert library.getSelectedItem().getProperty('sid') == picked


def test_a_settings_visit_that_changes_nothing_leaves_the_rows_alone(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, _store = _built_home(ctx, monkeypatch, _THREE)
    library = win.getControl(ctx.homewindow.LIBRARY_SHELF)
    library.selectItem(1)
    win.setFocusId(ctx.homewindow.LIBRARY_SHELF)
    loads = []
    monkeypatch.setattr(ctx.homewindow, '_load_rows', lambda *a, **k: loads.append(1))

    ctx.homewindow._open_settings(win)

    assert ctx.env.opened_settings is True
    assert loads == []
    assert library.getSelectedPosition() == 1
    assert win.getFocusId() == ctx.homewindow.LIBRARY_SHELF


def test_a_library_change_in_a_hub_shows_on_home_after_back(load_homewindow, monkeypatch):
    """The hub marks Home dirty. Home used to wait for an onInit that
    only playback brought."""
    ctx = load_homewindow()
    entries = list(_THREE[:2])
    win, _store = _built_home(ctx, monkeypatch, entries)
    monkeypatch.setattr(
        ctx.mystuff, '_fetch_library_entries', lambda store, _entries=entries: list(_entries),
    )

    def fake_hub(types, heading, action=''):
        entries.insert(0, dict(_THREE[2]))
        ctx.homewindow.mark_library_dirty()
        return False

    monkeypatch.setattr(ctx.hubwindow, 'open_hub', fake_hub)

    ctx.homewindow._open_type_row(win, 'movies')

    sids = [item.getProperty('sid') for item in win.getControl(ctx.homewindow.LIBRARY_SHELF).items]
    assert 'tt3' in sids
    assert win.closed is False


def test_a_sign_in_rebuilds_the_rows_for_the_new_account(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, store = _built_home(ctx, monkeypatch, _THREE)
    builds = []
    real_build = win._build
    monkeypatch.setattr(win, '_build', lambda place=None: (builds.append(place), real_build(place=place)))
    import lib.ui.views as views

    def fake_login():
        store._auth = {'authKey': 'other', 'user': {'email': 'x@y.z'}}

    monkeypatch.setattr(views, 'login', fake_login)

    ctx.homewindow._open_signin(win)

    assert len(builds) == 1 and builds[0] is not None


def test_tmdb_original_art_is_asked_for_at_the_drawn_size(load_homewindow):
    """#18: a 200px card and the 1920px hero do not need TMDB `original`."""
    ctx = load_homewindow()
    item = ctx.homewindow._poster_item({
        'id': 'tt1', 'type': 'movie', 'name': 'Dune',
        'poster': 'https://image.tmdb.org/t/p/original/p.jpg',
        'background': 'https://image.tmdb.org/t/p/original/b.jpg',
    })
    assert item.getProperty('thumbnail') == 'https://image.tmdb.org/t/p/w342/p.jpg'
    assert item.getProperty('fanart') == 'https://image.tmdb.org/t/p/w1280/b.jpg'
    # No backdrop: the poster stands in for the hero and is scaled to the
    # screen, so it is fetched larger than the card.
    bare = ctx.homewindow._poster_item({
        'id': 'tt2', 'type': 'movie', 'name': 'Arrival',
        'poster': 'https://image.tmdb.org/t/p/original/a.jpg',
    })
    assert bare.getProperty('thumbnail') == 'https://image.tmdb.org/t/p/w342/a.jpg'
    assert bare.getProperty('fanart') == 'https://image.tmdb.org/t/p/w780/a.jpg'



def test_up_from_the_first_row_reaches_the_tools_when_there_are_no_pills(load_homewindow, monkeypatch):
    """#23: a row's Up lands on the type pills. With no types installed
    they are hidden, so Kodi leaves the remote where it was; Home sends
    that dead-end Up to the tools. An Up that did move is left alone."""
    ctx = load_homewindow()
    import xbmcgui
    _patch_library(monkeypatch, ctx, [{
        '_id': 'tt9', 'name': 'Saved', 'type': 'movie', 'poster': 's', 'removed': False,
    }])
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth={'authKey': 'x'}, addons=[]))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.onInit()
    assert win.getControl(ctx.homewindow.BROWSE_LIST).size() == 0
    assert win.getFocusId() == ctx.homewindow.LIBRARY_SHELF

    win.onAction(xbmcgui.Action(3))

    assert win.getFocusId() == ctx.homewindow.TOOLS_LIST


def test_each_visible_row_shows_its_place_in_the_list(load_homewindow, monkeypatch):
    """#20: one row is on screen at a time, so each heading carries
    "row / rows". Hidden rows are not counted; a lone row shows none."""
    ctx = load_homewindow()
    _patch_library(monkeypatch, ctx, [{
        '_id': 'tt9', 'name': 'Saved', 'type': 'movie', 'poster': 's', 'removed': False,
    }])
    pages = {
        'movies': [{'id': 'tt1', 'type': 'movie', 'name': 'One', 'poster': 'p1'}],
        'series': [{'id': 'tt2', 'type': 'series', 'name': 'Two', 'poster': 'p2'}],
    }
    monkeypatch.setattr(ctx.homewindow, '_catalog_pages', lambda addons, enabled: (pages, {}))
    monkeypatch.setattr(ctx.homewindow, 'get_store', lambda: _FakeStore(auth={'authKey': 'x'}))
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

    win.onInit()

    assert win.getProperty('shelf_continue') == ''
    assert win.getControl(30150).label == ''
    assert win.getControl(30151).label == '1 / 3'
    assert win.getControl(30152).label == '2 / 3'
    assert win.getControl(30153).label == '3 / 3'
    assert win.getControl(30154).label == ''


def test_down_on_the_last_row_stays_there_and_hubs_count_rows_in_the_skin():
    """#20: Down from the last Home row used to wrap to Continue. The hub
    counts its rows from the container, and names itself in the header."""
    import os
    import xml.etree.ElementTree as ET

    skin = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i')
    home = ET.parse(os.path.join(skin, 'HomeWindow.xml')).getroot()
    last = home.find(".//control[@id='30045']")
    assert (last.findtext('ondown') or '').strip() == '30045'
    for counter in range(30150, 30156):
        label = home.find(".//control[@id='%d']" % counter)
        assert label is not None and (label.findtext('align') or '').strip() == 'right'
    hub = ET.parse(os.path.join(skin, 'HubWindow.xml')).getroot()
    labels = [el.findtext('label') or '' for el in hub.iter('control') if el.get('type') == 'label']
    assert any('Container(31000).CurrentItem' in text and 'Container(31000).NumItems' in text for text in labels)
    title = hub.find(".//control[@id='30005']")
    tools = hub.find(".//control[@id='30011']")
    assert int(title.findtext('top')) == int(tools.findtext('top'))
    assert (title.findtext('font') or '').strip() == 'font13'


def _hero_with_logo(ctx, logo, next_logo=''):
    import xbmcgui
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    items = []
    for name, sid, art in (('Dune', 'tt1', logo), ('Arrival', 'tt2', next_logo)):
        item = xbmcgui.ListItem(name)
        item.setProperties({
            'hero_title': name, 'hero_plot': 'Plot.', 'hero_logo': art,
            'fanart': 'https://img/%s.jpg' % sid, 'sid': sid, 'stype': 'movie',
        })
        items.append(item)
    win.getControl(ctx.homewindow.LIBRARY_SHELF).addItems(items)
    win.setFocusId(ctx.homewindow.LIBRARY_SHELF)
    return win


def test_a_logo_kodi_has_not_loaded_keeps_the_text_title(load_homewindow, monkeypatch):
    """#10: the skin hides the title whenever a logo is set, so a logo URL
    that 404s left the title area blank. A logo replaces the title only
    once Kodi's texture cache holds it; until then it is warmed."""
    ctx = load_homewindow()
    import xbmcgui
    ctx.env.cached_textures = set()
    win = _hero_with_logo(ctx, 'https://img/logo1.png', 'https://img/logo2.png')

    win.onAction(xbmcgui.Action(1))

    assert win.getProperty('HeroLogo') == ''
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Dune'
    assert win.getControl(ctx.homewindow.HERO_LOGO).image == ''
    # The focused logo and the next one load in the two 1x1 slots.
    assert win.getControl(30098).image == 'https://img/logo1.png'
    assert win.getControl(30099).image == 'https://img/logo2.png'

    # Once Kodi has it (and the short re-check window has passed), it shows.
    ctx.env.cached_textures = {'https://img/logo1.png'}
    ctx.homewindow._LOGO_STATE.clear()
    win.onAction(xbmcgui.Action(1))

    assert win.getProperty('HeroLogo') == 'https://img/logo1.png'
    assert win.getControl(ctx.homewindow.HERO_LOGO).image == 'https://img/logo1.png'


def test_a_cached_logo_shows_at_once_and_is_not_asked_for_again(load_homewindow):
    ctx = load_homewindow()
    import xbmcgui
    win = _hero_with_logo(ctx, 'https://img/logo1.png')

    win.onAction(xbmcgui.Action(1))
    win.onAction(xbmcgui.Action(1))

    assert win.getProperty('HeroLogo') == 'https://img/logo1.png'
    lookups = [call for call in ctx.env.jsonrpc_calls if 'logo1.png' in call]
    assert len(lookups) == 1


def test_a_card_without_art_shows_its_title_on_the_plate():
    """#10: a title with no poster drew an empty plate (and, on a hub, a
    focus ring around nothing). The plate now carries the title, which is
    also how the More card and the Sign in card read since the captions
    under the posters went away (#7)."""
    import os
    import xml.etree.ElementTree as ET

    skin = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i')
    home = ET.parse(os.path.join(skin, 'HomeWindow.xml')).getroot()
    for panel_id in ('30040', '30041', '30042', '30043', '30044', '30045'):
        panel = home.find(".//control[@id='%s']" % panel_id)
        for layout in ('itemlayout', 'focusedlayout'):
            labels = [
                el for el in panel.find(layout).findall('control')
                if el.get('type') == 'label' and 'ListItem.Label' in (el.findtext('label') or '')
                and any('String.IsEmpty(ListItem.Property(thumbnail))' in (v.text or '') for v in el.findall('visible'))
            ]
            assert len(labels) == 1, (panel_id, layout)
    hub = ET.parse(os.path.join(skin, 'HubWindow.xml')).getroot()
    rows = hub.find(".//control[@id='31000']")
    for layout in ('itemlayout', 'focusedlayout'):
        controls = rows.find(layout).findall('control')
        for slot in range(8):
            plates = [
                el for el in controls
                if (el.findtext('texture') or '').strip() == 'mask_poster.png'
                and any('Property(n%d)' % slot in (v.text or '') for v in el.findall('visible'))
                and not any('String.IsEqual(ListItem.Property(layout),decade)' == (v.text or '') for v in el.findall('visible'))
            ]
            assert len(plates) == 1, (layout, slot)
            titles = [
                el for el in controls
                if el.get('type') == 'label' and 'Property(n%d)' % slot in (el.findtext('label') or '')
                and any('String.IsEmpty(ListItem.Property(p%d))' % slot == (v.text or '') for v in el.findall('visible'))
            ]
            assert len(titles) >= 1, (layout, slot)


def test_continue_cards_are_wide_art_with_the_show_and_episode(load_homewindow):
    """#9: a Continue card is 16:9. The poster scaled into it was a slice
    through the middle. It now uses the episode still (Cinemeta ids) or
    the backdrop, and writes the show and S:1 E:2 bottom-left."""
    ctx = load_homewindow()
    episode = ctx.homewindow._continue_item({
        'id': 'tt0944947', 'type': 'series', 'name': 'Game of Thrones',
        'poster': 'p.jpg', 'background': 'b.jpg', 'video_id': 'tt0944947:2:5',
    })
    assert episode.getProperty('land') == 'https://episodes.metahub.space/tt0944947/2/5/w780.jpg'
    assert episode.getProperty('card_show') == 'Game of Thrones'
    assert episode.getProperty('card_code') == 'S:2 E:5'
    assert episode.getProperty('video_id') == 'tt0944947:2:5'

    movie = ctx.homewindow._continue_item({
        'id': 'tt1', 'type': 'movie', 'name': 'Dune', 'poster': 'p.jpg',
        'background': 'https://image.tmdb.org/t/p/original/b.jpg',
    })
    assert movie.getProperty('land') == 'https://image.tmdb.org/t/p/w1280/b.jpg'
    assert movie.getProperty('card_code') == ''
    assert movie.getProperty('card_show') == 'Dune'

    bare = ctx.homewindow._continue_item({
        'id': 'kitsu:1', 'type': 'series', 'name': 'Show', 'poster': 'p.jpg', 'video_id': 'kitsu:1:4',
    })
    # No Cinemeta still for a non-imdb id and no backdrop: the skin shows
    # the poster whole on the plate.
    assert bare.getProperty('land') == ''


def test_continue_card_skin_layers_the_poster_under_the_wide_art():
    import os
    import xml.etree.ElementTree as ET

    path = os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i', 'HomeWindow.xml')
    panel = ET.parse(path).getroot().find(".//control[@id='30040']")
    for layout in ('itemlayout', 'focusedlayout'):
        controls = panel.find(layout).findall('control')
        textures = [(el.findtext('texture') or '').strip() for el in controls]
        poster = textures.index('$INFO[ListItem.Property(thumbnail)]')
        land = textures.index('$INFO[ListItem.Property(land)]')
        assert poster < land
        assert (controls[poster].findtext('aspectratio') or '').strip() == 'keep'
        assert (controls[land].findtext('aspectratio') or '').strip() == 'scale'
        labels = [el.findtext('label') or '' for el in controls if el.get('type') == 'label']
        assert any('card_show' in text for text in labels)
        assert any('card_code' in text for text in labels)
        # Nothing hangs under the card any more.
        assert not [el for el in controls if el.get('type') == 'label' and (el.findtext('top') or '') == '232']


def test_any_poster_only_title_fills_the_hero_on_home_and_the_hubs(load_homewindow):
    """#21: only library records used to get the full-bleed poster; a
    catalog title without a backdrop sat as a pillarbox. Hubs carry the
    same scale plate now."""
    ctx = load_homewindow()
    import xbmcgui
    item = ctx.homewindow._poster_item({'id': 'tt5', 'type': 'movie', 'name': 'Five', 'poster': 'p5.jpg'})
    assert item.getProperty('hero_fill') == '1'
    win = ctx.homewindow.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')
    win.getControl(30042).addItems([item])
    win.setFocusId(30042)
    win.onAction(xbmcgui.Action(1))
    assert win.getProperty('HeroFill') == '1'
    assert win.getControl(ctx.homewindow.HERO_FILL).image == 'p5.jpg'

    import os
    import xml.etree.ElementTree as ET
    hub = ET.parse(os.path.join(_REPO_ROOT, 'resources', 'skins', 'Default', '1080i', 'HubWindow.xml')).getroot()
    fill = hub.find(".//control[@id='30028']")
    assert fill is not None and (fill.findtext('aspectratio') or '').strip() == 'scale'
