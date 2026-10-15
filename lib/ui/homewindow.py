# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""HomeWindow: RevRivulet's entry screen.

A full-bleed fanart hero for the focused title. The type chips
(Movies, Series, Anime, Other) sit in a pill row under the top bar.
Under that, horizontal rows: Continue (in progress), Library (the
Stremio library), and one poster preview per installed type. Search,
Add-ons and Settings are buttons in a right-aligned grouplist so they
stay on the right edge at any resolution. There is no large card row.
The old Continue card opened `open_my_stuff()` with no band filter, and
that screen's last band is the library, which is why the card showed
saved titles.

Picking a poster opens its page. The menu button (long-press on a
remote) offers Add to Library or Remove from Library. Picking a type
chip opens the catalog hub (`lib.ui.hubwindow`), one poster row per
catalog of that type, loaded as the remote moves down.

Shared helpers this module calls and does not modify:
`lib.ui.mystuff` (`merge_entries`, `library_metas`, `_fetch_library_entries`,
`_enrich`, the resume percent constants), `lib.ui.views.iter_catalog_pages`
and `login`, `lib.ui.detailwindow.open_detail`. The hub calls
`lib.ui.catalogpicker`'s catalog classification the same way.

Login is this addon's own profile (`addon_data/<addon id>/auth.json`
via `compat.addon_profile_dir()`), not the Stremio app's session and
not official Rivulet's.
"""
import xbmcgui

from lib.ui.dependencies import get_store
from lib.ui.uicommon import BaseWindow, UiHeartbeat, gated_input, open_window

BACKGROUND = 30000
STATUS_LABEL = 30005
BROWSE_LIST = 30010  # type chips (Movies, Series, Anime, Other)
TOOLS_LIST = 30011  # right-aligned grouplist: Sign in, Search, Add-ons, Settings
HERO_TITLE = 30020
HERO_META = 30021
HERO_PLOT = 30022  # textbox; setText(), not setLabel()
HERO_LOGO = 30023
CONTINUE_SHELF = 30040
LIBRARY_SHELF = 30041
BTN_SEARCH = 30070
BTN_ADDONS = 30071
BTN_SETTINGS = 30072
BTN_SIGNIN = 30073

#: How many posters a row keeps. `iter_catalog_pages()` is consumed once
#: and then closed, so Home does not walk the rest of the catalog.
SHELF_CAP = 12

#: Set when a hub poster changes the account library. Home has no handle
#: on that window, and its row cache would otherwise keep the old
#: Library row until the auth key changed.
_library_dirty = False

#: (action, panel id, header label id) for the poster rows under the
#: chips. Must match HomeWindow.xml, including each row's
#: `Window.Property(shelf_<action>)` visibility gate.
_SHELVES = (
    ('movies', 30042, 30142),
    ('series', 30043, 30143),
    ('anime', 30044, 30144),
    ('other', 30045, 30145),
)

_CLICKABLE = frozenset(
    (BROWSE_LIST, CONTINUE_SHELF, LIBRARY_SHELF)
    + tuple(list_id for _action, list_id, _label in _SHELVES)
)

_BUTTON_ACTIONS = {
    BTN_SEARCH: 'search',
    BTN_ADDONS: 'addons',
    BTN_SETTINGS: 'settings',
    BTN_SIGNIN: 'signin',
}

#: The content-type rows, in menu order: (action, {Stremio base catalog
#: types} or None, setting id). A catalog's type is reduced to its base
#: - everything before the first '.', lowercased, via `_base_type()` -
#: before matching one of these sets, so `anime.movie`/`anime.series`
#: join Anime and a stray `TV` joins Series the same as `tv`.
#:
#: `series` deliberately carries `tv` alongside it. An addon that
#: publishes live/linear channels types them "tv", and those are episodic
#: listings a viewer thinks of as television. `other` carries `None`
#: instead of a fixed set: it is a catch-all computed live by
#: `_remainder_types()`. Every consumer of `TYPE_ROW_TYPES` must treat
#: `None` as that sentinel, not as "unfiltered".
_TYPE_ROWS = (
    ('movies', frozenset({'movie'}), 'home_show_movies'),
    ('series', frozenset({'series', 'tv'}), 'home_show_series'),
    ('anime', frozenset({'anime'}), 'home_show_anime'),
    ('other', None, 'home_show_other'),
)

TYPE_ROW_TYPES = {action: types for action, types, _ in _TYPE_ROWS}


def _remainder_types(available):
    """The `other` row's type set: every base type in `available` that no
    curated row claims. Computed live rather than declared as a constant,
    because unlike Movies/Series/Anime its membership depends entirely on
    what is installed."""
    claimed = frozenset().union(*(types for _, types, _ in _TYPE_ROWS if types is not None))
    return available - claimed


#: (localized-string id, action). The chips only. Continue and Library
#: are poster rows, and Search / Add-ons / Settings are the top-bar
#: buttons. They are not list items: a Kodi list has one item size, and
#: the large cards that used to live here are what this screen dropped.
_MENU = (
    (30213, 'movies'),
    (30214, 'series'),
    (30215, 'anime'),
    (30227, 'other'),
)

_SUBTITLES = {
    'movies': 30216,
    'series': 30217,
    'anime': 30218,
    'other': 30228,
}

L_FOR_ACTION = {action: string_id for string_id, action in _MENU}


def _available_types(addons):
    """Return the set of base catalog types `addons` actually publish,
    reduced via `lib.stremio.addons._base_type()` - the same rule the
    picker's own `types=` filter applies."""
    from lib.stremio.addons import _base_type, iter_catalogs

    return {_base_type(catalog.get('type')) for _, _, catalog in iter_catalogs(addons)}


def _type_row_enabled(action, available):
    """Whether the type row `action` should appear: its setting must be
    on (all four default True) AND something installed must publish a
    catalog of one of its types."""
    from lib.ui.compat import setting_bool

    types = TYPE_ROW_TYPES.get(action)
    if types is None:
        types = _remainder_types(available)
    if not types & available:
        return False
    setting_id = next(sid for act, _, sid in _TYPE_ROWS if act == action)
    return setting_bool(setting_id, True)


def _menu_items(addons=None):
    from lib.ui.compat import L, addon_media_path

    available = _available_types(addons or [])
    items = []
    for string_id, action in _MENU:
        if action in TYPE_ROW_TYPES and not _type_row_enabled(action, available):
            continue
        item = xbmcgui.ListItem(L(string_id))
        subtitle = L(_SUBTITLES[action])
        item.setProperties({
            'action': action,
            'subtitle': subtitle,
            'hero_title': L(string_id),
            'hero_plot': subtitle,
        })
        item.setArt({'icon': addon_media_path('%s.png' % action)})
        items.append(item)
    return items


def _truncate(text, limit):
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '\u2026'


def _runtime_text(meta):
    """A count-neutral runtime. Stremio sometimes already sends a string
    ("155 min"); a number is formatted with `#30429` so the unit is
    translated without picking a plural form."""
    from lib.ui.compat import L

    runtime = meta.get('runtime')
    if isinstance(runtime, str):
        return runtime.strip()
    if isinstance(runtime, bool) or not isinstance(runtime, (int, float)):
        return ''
    if runtime <= 0:
        return ''
    return L(30429) % int(runtime)


def _hero_meta_text(meta):
    """Year, rating, runtime, genres. The middle dot is in NotoSans."""
    bits = []
    year = meta.get('year') or meta.get('releaseInfo') or ''
    if year:
        bits.append(str(year))
    rating = meta.get('imdbRating') or ''
    if rating:
        bits.append(str(rating))
    runtime = _runtime_text(meta)
    if runtime:
        bits.append(runtime)
    genres = meta.get('genres') or []
    if isinstance(genres, list):
        names = [str(genre) for genre in genres if genre][:3]
        if names:
            bits.append(', '.join(names))
    return ' \u00b7 '.join(bits)


def _poster_item(meta, action=''):
    """One shelf cell. `action` set means the click opens that menu
    action (Sign in) instead of the title's page."""
    from lib.ui.uicommon import escape_label

    name = meta.get('name') or ''
    item = xbmcgui.ListItem(escape_label(name))
    item.setProperties({
        'thumbnail': meta.get('poster') or '',
        'fanart': meta.get('background') or meta.get('poster') or '',
        'hero_logo': meta.get('logo') or '',
        'hero_title': escape_label(name),
        'hero_meta': escape_label(_hero_meta_text(meta)),
        'hero_plot': escape_label(_truncate(meta.get('description') or '', 280)),
        'action': action,
        'stype': str(meta.get('type') or ''),
        'sid': str(meta.get('id') or ''),
    })
    return item


def _more_item(action):
    from lib.ui.compat import L

    item = xbmcgui.ListItem(L(30425))
    item.setProperties({
        'action': action,
        'hero_title': L(L_FOR_ACTION[action]),
        'hero_plot': L(_SUBTITLES[action]),
    })
    return item


def _one_catalog_page(transport, manifest, catalog, extra=None):
    """The first page of one catalog. The generator is advanced once and
    closed, so a row never pages and never calls `fetch_catalog_pages()`.
    A failed addon yields an empty row rather than taking the screen down.
    """
    from lib.ui.views import iter_catalog_pages

    try:
        page = next(iter_catalog_pages(
            transport, catalog.get('type'), catalog.get('id'),
            extra=extra, catalog=catalog, manifest=manifest,
        ))
    except StopIteration:
        return []
    except Exception:
        return []
    metas = [meta for meta in (page or []) if isinstance(meta, dict)]
    return metas[:SHELF_CAP]


def _first_catalog_page(addons, types):
    """The first page of the first installed catalog of `types`."""
    from lib.stremio.addons import _base_type, iter_catalogs

    for transport, manifest, catalog in iter_catalogs(addons):
        if _base_type(catalog.get('type')) not in types:
            continue
        return _one_catalog_page(transport, manifest, catalog)
    return []


def _set_shelf(window, list_id, label_id, prop, heading, items):
    control = window.getControl(list_id)
    control.reset()
    if items:
        control.addItems(items)
    window.getControl(label_id).setLabel(heading if items else '')
    window.setProperty(prop, '1' if items else '')


def _state_percent(entry):
    """Percent of a libraryItem's own `state`, or None when the record
    has no usable duration. Same fields `lib.library.merge_playback()`
    writes (`timeOffset`, `duration`); this only reads them."""
    if not isinstance(entry, dict):
        return None
    state = entry.get('state')
    if not isinstance(state, dict):
        return None
    duration = state.get('duration') or 0
    offset = state.get('timeOffset') or 0
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return None
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        return None
    if duration <= 0:
        return None
    return (float(offset) / float(duration)) * 100.0


def _library_continue_metas(entries):
    """In-progress titles recorded on the account.

    Local `progress.json` only knows what this device played. A title
    watched in the Stremio app is a libraryItem whose `state` still sits
    in the resume window. An explicit removal is `removed` without
    `temp` (`library_remove_payload`); those stay off Continue. An
    implicit watch record is both flags true, which is how Stremio
    stores "played, not added", and those do belong here.
    """
    from lib.ui.mystuff import RESUME_MAX_PERCENT, RESUME_MIN_PERCENT

    metas = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if entry.get('removed') and not entry.get('temp'):
            continue
        percent = _state_percent(entry)
        if percent is None or percent < RESUME_MIN_PERCENT or percent >= RESUME_MAX_PERCENT:
            continue
        if not entry.get('_id'):
            continue
        if not (entry.get('name') or entry.get('poster')):
            continue
        metas.append({
            'id': entry.get('_id'),
            'name': entry.get('name'),
            'type': entry.get('type'),
            'poster': entry.get('poster'),
            'background': entry.get('background'),
        })
    return metas


def _played_posters(store, library_entries):
    """Resume, next-up and recently finished. Never the library band.

    `merge_entries()` is what copies a saved title's name and poster onto
    a local progress row. `_enrich()` runs only for rows that still have
    neither, so a home paint does not fan out a meta fetch for every
    series just to learn the next episode code.
    """
    from lib.ui.mystuff import BAND_LIBRARY, _enrich, merge_entries

    try:
        merged = merge_entries(store.get_progress_entries(), library_entries)
    except Exception:
        merged = []
    played = [entry for entry in merged if entry.get('band') != BAND_LIBRARY]
    missing = [entry for entry in played if not (entry.get('name') or entry.get('poster'))]
    if missing:
        try:
            _enrich(missing)
        except Exception:
            pass
    posters = []
    seen = set()
    for entry in played:
        if not (entry.get('name') or entry.get('poster')):
            continue
        key = (entry.get('type'), entry.get('id'))
        seen.add(key)
        posters.append(_poster_item(entry))
        if len(posters) >= SHELF_CAP:
            return posters
    for meta in _library_continue_metas(library_entries):
        key = (meta.get('type'), meta.get('id'))
        if key in seen:
            continue
        seen.add(key)
        posters.append(_poster_item(meta))
        if len(posters) >= SHELF_CAP:
            break
    return posters


def _library_posters(auth, library_entries):
    """Every non-removed libraryItem, as posters. Signed out, one Sign in
    cell. Signed in and empty, the existing empty-library notice."""
    from lib.ui.compat import L
    from lib.ui.mystuff import library_metas

    if not auth:
        return [_poster_item(
            {'name': L(30427), 'description': L(30428)}, action='signin',
        )]
    try:
        metas = library_metas(library_entries)
    except Exception:
        metas = []
    posters = [_poster_item(meta) for meta in metas[:SHELF_CAP]]
    if posters:
        return posters
    return [_poster_item({'name': L(30426), 'description': L(30423)})]


def _fetch_library(store, auth):
    """The account library, or [] when signed out or the call fails.

    `_fetch_library_entries()` already returns [] on `ApiError`. Anything
    else it lets out (a store miss, a bug) must not take Home down: the
    rows just render empty.
    """
    if not auth:
        return []
    from lib.ui.mystuff import _fetch_library_entries

    try:
        fetched = _fetch_library_entries(store)
    except Exception:
        return []
    if not isinstance(fetched, list):
        return []
    return fetched


def _enabled_shelf_types(addons):
    """`{action: type set}` for the poster rows that should exist.

    Local: settings and the installed manifests. No HTTP.
    """
    available = _available_types(addons)
    enabled = {}
    for action, _list_id, _label_id in _SHELVES:
        if not _type_row_enabled(action, available):
            continue
        types = TYPE_ROW_TYPES[action]
        if types is None:
            types = _remainder_types(available)
        enabled[action] = types
    return enabled


def _catalog_pages(addons, enabled):
    """First page per enabled shelf. `iter_catalog_pages()` once each."""
    return {
        action: _first_catalog_page(addons, types)
        for action, types in enabled.items()
    }


def _load_rows(window, store, addons, auth):
    """Continue, Library, and the catalog previews.

    One cancellable spinner covers the account read and the catalog
    pages. The result stays on the window so backing out of Search does
    not fetch it again; a different auth key (the sign-in dialog) does.
    """
    from lib.ui.compat import L
    from lib.ui.uicommon import CANCELLED, run_cancellable

    global _library_dirty

    enabled = _enabled_shelf_types(addons)
    key = (auth or {}).get('authKey')
    cached = getattr(window, '_row_key', None) == key and getattr(window, '_catalog_pages', None) is not None
    if cached and not _library_dirty:
        return window._continue_items, window._library_items, window._catalog_pages, enabled
    if cached and _library_dirty:
        _library_dirty = False
        _refill_saved_rows(window, store, auth)
        return window._continue_items, window._library_items, window._catalog_pages, enabled

    def _load():
        library_entries = _fetch_library(store, auth)
        return (
            _played_posters(store, library_entries),
            _library_posters(auth, library_entries),
            _catalog_pages(addons, enabled),
        )

    loaded = run_cancellable(_load, L(30033))
    if loaded is CANCELLED or not isinstance(loaded, tuple) or len(loaded) != 3:
        return [], [], {}, enabled
    continue_items, library_items, pages = loaded
    window._row_key = key
    window._continue_items = continue_items
    window._library_items = library_items
    window._catalog_pages = pages
    return continue_items, library_items, pages, enabled


def _fill_shelves(window, store, addons, auth, show_continue):
    from lib.ui.compat import L

    continue_items, library_items, pages, enabled = _load_rows(window, store, addons, auth)
    if not show_continue:
        continue_items = []
    _set_shelf(
        window, CONTINUE_SHELF, 30140, 'shelf_continue',
        L(30241).upper(), continue_items,
    )
    _set_shelf(
        window, LIBRARY_SHELF, 30141, 'shelf_library',
        L(30422).upper(), library_items,
    )
    for action, list_id, label_id in _SHELVES:
        items = []
        if action in enabled:
            items = [_poster_item(meta) for meta in pages.get(action, [])]
            if items:
                items.append(_more_item(action))
        _set_shelf(
            window, list_id, label_id, 'shelf_%s' % action,
            L(L_FOR_ACTION[action]).upper(), items,
        )


def _refill_saved_rows(window, store, auth):
    """Continue and Library from a fresh account read. Catalog pages stay
    as they were: a library write does not change what a catalog returns."""
    from lib.ui.compat import setting_bool

    entries = _fetch_library(store, auth)
    show_continue = setting_bool('home_show_mystuff', True)
    continue_items = _played_posters(store, entries) if show_continue else []
    library_items = _library_posters(auth, entries)
    window._continue_items = continue_items
    window._library_items = library_items


def mark_library_dirty():
    """The next Home paint re-reads the account library."""
    global _library_dirty
    _library_dirty = True


def refresh_library_row(window):
    """Re-read the account library into Home's Continue and Library rows.

    A hub has no Library row. It marks the cache dirty and Home refills
    when the hub closes (`onInit` runs again). The read is the same
    `_fetch_library` Home already uses, not a new API method.
    """
    global _library_dirty

    try:
        window.getControl(LIBRARY_SHELF)
    except Exception:
        _library_dirty = True
        return
    from lib.ui.compat import L
    from lib.ui.uicommon import CANCELLED, run_cancellable

    def _read():
        store = get_store()
        auth = store.get_auth()
        return store, auth

    loaded = run_cancellable(_read, L(30033))
    if loaded is CANCELLED or not isinstance(loaded, tuple):
        _library_dirty = True
        return
    store, auth = loaded
    _refill_saved_rows(window, store, auth)
    _set_shelf(
        window, CONTINUE_SHELF, 30140, 'shelf_continue',
        L(30241).upper(), window._continue_items,
    )
    _set_shelf(
        window, LIBRARY_SHELF, 30141, 'shelf_library',
        L(30422).upper(), window._library_items,
    )
    _library_dirty = False


def _offer_library(window, item):
    """Menu button on a poster. A chip or a notice has nothing to save."""
    from lib.ui.libraryaction import meta_from_item, offer

    meta = meta_from_item(item)
    if meta is None:
        return
    if offer(meta):
        refresh_library_row(window)


def _focus_first(window):
    """Land on the first row that actually has posters, else the chips,
    else Settings. An empty hidden row must not take the remote."""
    for control_id, prop in (
        (CONTINUE_SHELF, 'shelf_continue'),
        (LIBRARY_SHELF, 'shelf_library'),
    ):
        if window.getProperty(prop):
            window.setFocusId(control_id)
            return
    if window.getControl(BROWSE_LIST).size():
        window.setFocusId(BROWSE_LIST)
        return
    for _action, list_id, _label in _SHELVES:
        if window.getProperty('shelf_%s' % _action):
            window.setFocusId(list_id)
            return
    window.setFocusId(BTN_SETTINGS)


def _status_text(auth):
    """Home's top status line. Both states are prefixed with a
    `[COLOR]`-tinted dot (font12 is NotoSans and covers U+25CF)."""
    from lib.ui.compat import L

    if not auth:
        return '[COLOR 57EEF3F6]\u25cf[/COLOR] %s' % L(30190)
    user = auth.get('user') or {}
    text = L(30022) % (user.get('email') or user.get('name') or '?')
    return '[COLOR FF38BDF8]\u25cf[/COLOR] %s' % text


def paint_hero(window):
    """Paint the backdrop from the focused poster.

    A button has no selected item. Leaving the labels alone in that case
    keeps the last title on screen while the remote is on the top bar,
    which is the reading order of this layout. A poster with no fanart
    falls back to the addon fanart so the hero never goes blank.
    """
    from lib.ui.compat import addon_fanart

    item = None
    try:
        focus_id = window.getFocusId()
        if focus_id:
            item = window.getControl(focus_id).getSelectedItem()
    except Exception:
        item = None
    if item is None:
        return
    title = item.getProperty('hero_title') or item.getLabel() or ''
    meta = item.getProperty('hero_meta') or ''
    plot = item.getProperty('hero_plot') or item.getProperty('subtitle') or ''
    fanart = item.getProperty('fanart') or ''
    logo = item.getProperty('hero_logo') or ''
    try:
        window.setProperty('HeroLogo', logo)
        window.getControl(HERO_LOGO).setImage(logo)
        window.getControl(HERO_TITLE).setLabel(title)
        window.getControl(HERO_META).setLabel(meta)
        window.getControl(HERO_PLOT).setText(plot)
        window.getControl(BACKGROUND).setImage(fanart or addon_fanart())
    except Exception:
        pass


class HomeWindow(BaseWindow):
    """See module docstring. Built/run via `open_home()`."""

    def onInit(self):
        # Recomputed every onInit(): onInit() re-runs on every resume from
        # a nested modal, so a sign-in or a newly installed catalog shows
        # up on the way back here without restarting the addon.
        self._build()

    def _build(self):
        from lib.ui.compat import addon_fanart, setting_bool

        store = get_store()
        auth = store.get_auth()
        self.getControl(BACKGROUND).setImage(addon_fanart())
        addons = store.get_enabled_addons()
        browse = _menu_items(addons)
        chips = self.getControl(BROWSE_LIST)
        chips.reset()
        chips.addItems(browse)
        self.setProperty('HomeBrowse', '1' if browse else '')
        self.setProperty('HomeSignedOut', '' if auth else '1')
        self.getControl(STATUS_LABEL).setLabel(_status_text(auth))
        show_continue = setting_bool('home_show_mystuff', True)
        _fill_shelves(self, store, addons, auth, show_continue)
        _focus_first(self)
        paint_hero(self)

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

        action_id = action.getId()
        if action_id in BACK_ACTIONS:
            self.close()
            return
        if action_id == 117:
            focus = self.getFocusId()
            if focus in _CLICKABLE and focus != BROWSE_LIST:
                _offer_library(self, self.getControl(focus).getSelectedItem())
            return
        # The pills are the Down target of the top bar. With no types
        # installed that list is hidden, and a hidden target does not
        # take focus, so Down would stick on Settings.
        if action_id == 4 and not self.getControl(BROWSE_LIST).size():
            if self.getFocusId() in _BUTTON_ACTIONS or self.getFocusId() == TOOLS_LIST:
                _focus_first(self)
        paint_hero(self)

    @gated_input
    def onClick(self, control_id):
        if control_id in _BUTTON_ACTIONS:
            handler = _ACTIONS.get(_BUTTON_ACTIONS[control_id])
            if handler:
                handler(self)
            return
        if control_id not in _CLICKABLE:
            return
        focused = self.getControl(control_id).getSelectedItem()
        _activate(self, focused)


def _open_signin(window):
    """The existing email/password dialog, then a refresh of this window.

    `views.login()` writes auth.json in this addon's profile. Home calls
    it directly so the status line and the Library row update before the
    dialog's RunPlugin directory finish returns. The cached rows are
    dropped first: they were built for the signed-out key.
    """
    from lib.ui.views import login

    login()
    window._row_key = None
    window._catalog_pages = None
    window._build()


def _activate(window, item):
    """A shelf poster with an id opens its page. Anything else is a
    menu action (including More, which carries the row's action and
    no id)."""
    if item is None:
        return
    action = item.getProperty('action')
    sid = item.getProperty('sid')
    if sid and not action:
        from lib.ui.detailwindow import open_detail
        if open_detail(item.getProperty('stype'), sid):
            window.close()
        return
    handler = _ACTIONS.get(action)
    if handler:
        handler(window)


def _open_type_row(window, action):
    """The catalog hub, over Home. Back returns here. Playback closes both."""
    from lib.ui.compat import L
    from lib.ui.hubwindow import open_hub

    types = TYPE_ROW_TYPES[action]
    if types is None:
        types = _remainder_types(_available_types(get_store().get_enabled_addons()))
    if open_hub(types, L(L_FOR_ACTION[action]), action):
        window.close()


def _open_search(window):
    from lib.ui.searchwindow import open_search
    if open_search():
        window.close()


def _open_addons(window):
    from lib.ui.addonswindow import open_addons
    open_addons()


def _open_settings(window):
    from lib.ui.compat import ADDON
    ADDON.openSettings()
    # Account > Login returns here without re-running onInit. Drop the
    # row cache so a sign-in done in that dialog shows up on the Library
    # row in the same visit.
    try:
        window._row_key = None
        window._catalog_pages = None
        window._build()
    except Exception:
        pass


_ACTIONS = {
    'signin': _open_signin,
    'movies': lambda window: _open_type_row(window, 'movies'),
    'series': lambda window: _open_type_row(window, 'series'),
    'anime': lambda window: _open_type_row(window, 'anime'),
    'other': lambda window: _open_type_row(window, 'other'),
    'search': _open_search,
    'addons': _open_addons,
    'settings': _open_settings,
}


def _migrate_mystuff_setting():
    """Carry a `home_show_continue` value over to `home_show_mystuff` once.

    The merged row replaced two rows and took a new setting id with it, so
    anyone who had deliberately turned the old "Continue watching" row OFF
    would silently get the new row switched back on. This copies that
    decision across the rename exactly once.

    Only a `false` needs carrying: the new setting already defaults to
    True, so an unset or true old value is already correct. The old key is
    cleared afterwards, which is also what makes this idempotent - a
    second launch finds nothing to migrate and cannot re-apply the value
    over a choice the user has since changed.

    Best-effort: a settings read/write failing here must never stop Home
    from opening, so any exception is logged and swallowed.
    """
    import xbmc

    from lib.ui.compat import ADDON, log, setting_bool

    try:
        raw = (ADDON.getSetting('home_show_continue') or '').strip()
        if not raw:
            return
        if not setting_bool('home_show_continue', True):
            ADDON.setSetting('home_show_mystuff', 'false')
            log('homewindow: carried home_show_continue=false to home_show_mystuff', xbmc.LOGINFO)
        ADDON.setSetting('home_show_continue', '')
    except Exception as exc:
        log('homewindow: home_show_mystuff migration failed: %r' % (exc,), xbmc.LOGWARNING)


def _notify_if_updated(store):
    """Toast the user once when the running addon version differs from the
    version `store` last recorded. A brand-new install has nothing
    recorded yet, so that first call only seeds the current version and
    stays silent.

    Best-effort: `store` I/O failing here must never stop the home screen
    from opening.
    """
    import xbmc

    from lib.ui.compat import log
    try:
        from lib.ui.compat import ADDON, L, notify

        current = ADDON.getAddonInfo('version')
        last_seen = store.get_last_seen_version()
        if last_seen == current:
            return
        store.set_last_seen_version(current)
        if last_seen is not None:
            notify(L(30184) % current)
    except Exception as exc:
        log('homewindow: update-notification check failed: %r' % (exc,), xbmc.LOGWARNING)


def open_home():
    """Build and run the HomeWindow modal; blocks until the user exits.

    default.py wraps this call in its own try/except and falls back to
    the minimal recovery directory (Settings row) on ANY exception, so
    an exception raised here must keep propagating unchanged - this
    only logs it for diagnostics and guarantees the window is closed
    before re-raising.

    The whole session runs under `uicommon.UiHeartbeat`, the liveness marker
    `default.py` consults before opening another Home.
    """
    import xbmc

    from lib.ui.compat import log

    log('homewindow: opening HomeWindow', xbmc.LOGINFO)
    # Runs here, not in HomeWindow.onInit(): onInit() re-fires every time
    # Home is resumed after a nested modal closes, which would re-show the
    # toast on every back-navigation. open_home() runs exactly once per
    # addon launch.
    _migrate_mystuff_setting()
    with UiHeartbeat():
        try:
            _notify_if_updated(get_store())
        except Exception as exc:
            log('homewindow: update-notification store unavailable: %r' % (exc,), xbmc.LOGWARNING)
        win = open_window(HomeWindow, 'HomeWindow.xml')
        try:
            win.doModal()
        except Exception as exc:
            log('homewindow: HomeWindow failed: %r' % (exc,), xbmc.LOGERROR)
            raise
        finally:
            try:
                win.close()
            except Exception:
                pass
    log('homewindow: HomeWindow closed', xbmc.LOGINFO)
