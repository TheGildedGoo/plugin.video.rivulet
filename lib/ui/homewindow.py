# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""HomeWindow: RevRivulet's entry screen. A full-bleed fanart hero for
the focused title, then horizontal rows: Continue and Watch Later as
cards, the catalog types as chips, and poster rows filled from the
first page of each installed catalog.

Picking a card or a poster opens the next screen as a nested modal
(see `lib.ui.uicommon`'s module docstring for the navigation model
this and every other custom screen shares).

Discover/Search/Library each draw a nested modal over Home and only
close it once their own selection chain reaches playback (see
`_open_discover`/`_open_search`/`_open_mystuff`); Add-ons has no
playback path of its own, so Home always stays open behind it (see
`_open_addons`). Settings opens Kodi's own native settings dialog,
which is not worth replacing.

The menu is still three lists, because a Kodi list has one item
size. `LIST` (30002) is the Continue and Watch Later cards,
`BROWSE_LIST` (30010) is the type chips, `TOOLS_LIST` (30011) is
Search, Add-ons and Settings along the top. When no type chip is
installed, the tool chips move onto the browse list: an empty list
would swallow Down before it reached Settings. Poster rows under
those chips are separate panels (`_SHELVES`); an empty one is
hidden with a window property so the remote never lands on it.

Every one of those lists draws a bright frame on the focused item.
A near-black plate on the dark scrim read as "no highlight" from
the sofa even though the navigation sound still played: Up from
Movies lands on the Watch list, and if Continue is hidden that
item is Watch Later.

Login is this addon's own profile (`addon_data/<addon id>/auth.json`
via `compat.addon_profile_dir()`), not the Stremio app's session
and not official Rivulet's. A fresh install has no token, so Home
says it is not logged in until the viewer signs in here once.
`views.login()` is the existing dialog; this module only decides
when to show it and refreshes the hero afterwards. The Stremio
client is not involved in that decision.

Watch Later is not a new collection. The Stremio datastore this
addon speaks has no watch-later record, and nothing under addon
data is a user-curated list either. The row opens the library band
`lib.ui.mystuff` already computes: permanent library items that
have not been started on this device. Adding or removing a title
stays on the detail screen's existing library action.

The "New Episodes" row that used to live here moved to
`lib.ui.catalogpicker`'s Series screen as a pinned entry: it is
series-specific, so it belongs where shows live rather than as a
permanent top-level row (see `catalogpicker.open_catalog_picker()` and
`CatalogPickerWindow._open_new_episodes()`).
"""
import xbmcgui

from lib.ui.dependencies import get_store
from lib.ui.uicommon import BaseWindow, UiHeartbeat, gated_input, open_window

BACKGROUND = 30000
LIST = 30002  # Watch cards: Continue, Watch Later.
STATUS_LABEL = 30005  # plain text label; set at runtime via setLabel(), not a skin <label>
BROWSE_LIST = 30010  # type chips (Movies, Series, Anime, Other)
TOOLS_LIST = 30011  # Search, Add-ons, Settings, and Sign in when logged out
HERO_TITLE = 30020
HERO_META = 30021
HERO_PLOT = 30022  # textbox; setText(), not setLabel()
CONTINUE_SHELF = 30040
WATCHLATER_SHELF = 30041

#: How many posters a home row keeps from the first catalog page.
#: `iter_catalog_pages()` is consumed once and then closed, so Home
#: does not walk the rest of the catalog.
SHELF_CAP = 12

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
    (LIST, BROWSE_LIST, TOOLS_LIST, CONTINUE_SHELF, WATCHLATER_SHELF)
    + tuple(list_id for _action, list_id, _label in _SHELVES)
)

#: The content-type rows that replaced the single "Discover" entry, in
#: menu order: (action, {Stremio base catalog types} or None, setting id).
#: A catalog's type is reduced to its base - everything before the first
#: '.', lowercased, via `_base_type()` - before matching one of these
#: sets, so `anime.movie`/`anime.series` (the Stremio dotted-subtype
#: convention) join Anime and a stray `TV` joins Series the same as `tv`.
#:
#: `series` deliberately carries `tv` alongside it. An addon that
#: publishes live/linear channels types them "tv", and those are episodic
#: listings a viewer thinks of as television - grouping them under Series
#: keeps them reachable without a row of their own that would sit empty
#: for nearly everyone. "anime" is the one type common enough to earn its
#: own row: it is what the large anime catalog addons (and AIOStreams)
#: actually publish, and its audience wants it separated from film.
#:
#: `other` carries `None` instead of a fixed set: it is a catch-all for
#: whatever an addon publishes that the three curated rows do not claim
#: (Stremio lets an addon declare any string as a type), so its actual
#: type set cannot be a constant - it is computed live from installed
#: addons by `_remainder_types()`. Every consumer of `TYPE_ROW_TYPES`
#: must treat `None` as that sentinel, not as "unfiltered".
_TYPE_ROWS = (
    ('movies', frozenset({'movie'}), 'home_show_movies'),
    ('series', frozenset({'series', 'tv'}), 'home_show_series'),
    ('anime', frozenset({'anime'}), 'home_show_anime'),
    ('other', None, 'home_show_other'),
)

#: action -> the set of catalog types its picker is filtered to, or
#: `None` for `other`'s "compute the remainder" sentinel (see
#: `_TYPE_ROWS`).
TYPE_ROW_TYPES = {action: types for action, types, _ in _TYPE_ROWS}


def _remainder_types(available):
    """The `other` row's type set: every base type in `available` that no
    curated row (a non-`None` entry in `_TYPE_ROWS`) claims. Computed
    live rather than declared as a constant, because unlike Movies/
    Series/Anime its membership depends entirely on what is installed."""
    claimed = frozenset().union(*(types for _, types, _ in _TYPE_ROWS if types is not None))
    return available - claimed


#: (localized-string id, action) - the authoritative definition of Home's menu rows.
#:
#: The `mystuff` row (labelled "Continue", 30241) replaces what used to
#: be two separate rows, "Continue watching" and "Library" (30002): both
#: built a list of metas and handed it to the same coverflow, and they
#: overlap heavily in practice (a title you are part-way through is
#: usually also in your library), so splitting them made the viewer guess
#: which one held the thing they wanted. See `lib.ui.mystuff` for the
#: merge and its bands. The action/module keep the `mystuff` name: the
#: row's LABEL is what changed, and the screen still shows the saved
#: library alongside the resumable titles.
_MENU = (
    (30241, 'mystuff'),
    (30422, 'watchlater'),
    (30213, 'movies'),
    (30214, 'series'),
    (30215, 'anime'),
    (30227, 'other'),
    (30001, 'search'),
    (30003, 'addons'),
    (30004, 'settings'),
)


#: (action -> localized-string id) for HomeWindow.xml's dimmer second
#: label per row - localized via L(), not plain literals, so it follows
#: Kodi's language setting the same as every other row's main label.
_SUBTITLES = {
    'mystuff': 30232,
    'watchlater': 30423,
    'movies': 30216,
    'series': 30217,
    'anime': 30218,
    'other': 30228,
    'search': 30149,
    'addons': 30151,
    'settings': 30152,
}

#: action -> which of the three Home lists draws it. Watch Later sits
#: with Continue because both are "your titles", not a catalog. The
#: tool rows are not type rows, so they are not gated by `_TYPE_ROWS`.
_GROUP = {
    'mystuff': 'watch',
    'watchlater': 'watch',
    'movies': 'browse',
    'series': 'browse',
    'anime': 'browse',
    'other': 'browse',
    'search': 'tools',
    'addons': 'tools',
    'settings': 'tools',
}


def _available_types(addons):
    """Return the set of base catalog types `addons` actually publish,
    reduced via `lib.stremio.addons._base_type()` - the same rule the
    picker's own `types=` filter applies - so a dotted subtype like
    `anime.movie` is counted under `anime` and a stray `TV` under `tv`.

    Drives the auto-hide half of a type row's visibility: a row whose
    types nothing installed publishes would open an empty picker, so it
    is left out entirely rather than offered and then disappointing.
    """
    from lib.stremio.addons import _base_type, iter_catalogs

    return {_base_type(catalog.get('type')) for _, _, catalog in iter_catalogs(addons)}


def _type_row_enabled(action, available):
    """Whether the type row `action` should appear: its setting must be
    on (all four default True) AND something installed must publish a
    catalog of one of its types - for `other`, "its types" is whatever
    `_remainder_types()` computes, not a fixed set."""
    from lib.ui.compat import setting_bool

    types = TYPE_ROW_TYPES.get(action)
    if types is None:
        types = _remainder_types(available)
    if not types & available:
        return False
    setting_id = next(sid for act, _, sid in _TYPE_ROWS if act == action)
    return setting_bool(setting_id, True)


def _menu_items(show_mystuff, addons=None):
    from lib.ui.compat import L, addon_media_path

    available = _available_types(addons or [])
    items = []
    for string_id, action in _MENU:
        if action == 'mystuff' and not show_mystuff:
            continue
        if action in TYPE_ROW_TYPES and not _type_row_enabled(action, available):
            continue
        item = xbmcgui.ListItem(L(string_id))
        # One setProperties() call instead of several setProperty() calls.
        # setArt() stays separate, a distinct Kodi API that
        # setProperties() cannot batch into. hero_* is what the backdrop
        # reads when this card has focus, before any poster row is filled.
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


def _place_menu(items):
    """Split `_menu_items()` across the three Home lists.

    Returns `(watch, browse, tools, show_tools)`. `show_tools` is false
    when browse would be empty: the tool rows are moved onto the browse
    list so Down from Watch still reaches Search, Add-ons and Settings.
    The skin hides the separate More strip unless `show_tools` is true
    (`Window.Property(HomeTools)`).
    """
    grouped = {'watch': [], 'browse': [], 'tools': []}
    for item in items:
        grouped[_GROUP[item.getProperty('action')]].append(item)
    if grouped['browse']:
        return grouped['watch'], grouped['browse'], grouped['tools'], True
    return grouped['watch'], grouped['tools'], [], False


def _signin_item():
    """The top-menu chip shown only while this profile has no auth.json.

    Official Rivulet and the Stremio app keep their own sessions. This
    chip is the one-time prompt that writes RevRivulet's. The icon is
    the settings glyph already shipped for the menu: a new file would
    fail the unused-icon check unless the action joined `_MENU`, and
    Sign in is not a permanent row.
    """
    from lib.ui.compat import L, addon_media_path

    title = L(30427)
    detail = L(30428)
    item = xbmcgui.ListItem(title)
    item.setProperties({
        'action': 'signin',
        'subtitle': detail,
        'hero_title': title,
        'hero_plot': detail,
    })
    item.setArt({'icon': addon_media_path('settings.png')})
    return item


def _apply_signed_out_copy(items, auth):
    """Point the Watch Later card at the one-time sign-in explanation.

    The card's label stays "Watch Later" (that is the row). The line
    under it, and the hero plot, say why the library is empty.
    """
    if auth:
        return
    from lib.ui.compat import L

    detail = L(30428)
    for item in items:
        if item.getProperty('action') != 'watchlater':
            continue
        item.setProperty('subtitle', detail)
        item.setProperty('hero_plot', detail)


def _truncate(text, limit):
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '\u2026'


def _poster_item(meta, action=''):
    """One shelf cell. `action` set means the click opens that menu
    action (Sign in, More) instead of the title's page."""
    from lib.ui.uicommon import escape_label

    name = meta.get('name') or ''
    bits = []
    year = meta.get('year') or meta.get('releaseInfo') or ''
    if year:
        bits.append(str(year))
    rating = meta.get('imdbRating') or ''
    if rating:
        bits.append(str(rating))
    item = xbmcgui.ListItem(escape_label(name))
    item.setProperties({
        'thumbnail': meta.get('poster') or '',
        'fanart': meta.get('background') or meta.get('poster') or '',
        'hero_title': escape_label(name),
        'hero_meta': escape_label(' \u00b7 '.join(bits)),
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


def _first_catalog_page(addons, types):
    """The first page of the first installed catalog of `types`.

    Uses `iter_catalogs()` and `iter_catalog_pages()` unchanged. The
    generator is advanced once and then closed, so Home never pages
    and never calls `fetch_catalog_pages()`. A failed addon yields an
    empty row rather than taking Home down with it.
    """
    from lib.stremio.addons import _base_type, iter_catalogs
    from lib.ui.views import iter_catalog_pages

    for transport, manifest, catalog in iter_catalogs(addons):
        if _base_type(catalog.get('type')) not in types:
            continue
        try:
            page = next(iter_catalog_pages(
                transport, catalog.get('type'), catalog.get('id'),
                catalog=catalog, manifest=manifest,
            ))
        except Exception:
            return []
        metas = [meta for meta in (page or []) if isinstance(meta, dict)]
        return metas[:SHELF_CAP]
    return []


def _set_shelf(window, list_id, label_id, prop, heading, items):
    control = window.getControl(list_id)
    control.reset()
    if items:
        control.addItems(items)
    window.getControl(label_id).setLabel(heading if items else '')
    window.setProperty(prop, '1' if items else '')


def _continue_posters(store, library_entries):
    """Played titles that already carry a name or poster.

    `merge_entries()` is local and wants the datastore shape, which is
    what `_fetch_library_entries()` returns. A miss leaves the row
    hidden and the Continue card still opens the full grid.
    """
    from lib.ui.mystuff import BAND_LIBRARY, merge_entries

    try:
        merged = merge_entries(store.get_progress_entries(), library_entries)
    except Exception:
        return []
    cards = []
    for entry in merged:
        if entry.get('band') == BAND_LIBRARY:
            continue
        if not (entry.get('name') or entry.get('poster')):
            continue
        cards.append(_poster_item(entry))
        if len(cards) >= SHELF_CAP:
            break
    return cards


def _watchlater_posters(auth, metas):
    from lib.ui.compat import L

    if not auth:
        return [_poster_item({'name': L(30427), 'description': L(30428)}, action='signin')]
    return [_poster_item(meta) for meta in metas[:SHELF_CAP]] + [_more_item('watchlater')]


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


def _fill_shelves(window, store, addons, auth):
    """Poster rows under the chips.

    Catalog rows use `iter_catalog_pages()` (first page only), under
    the same cancellable spinner the rest of the addon uses, and the
    pages stay on the window so backing out of Search does not fetch
    them again. Continue and Watch Later do not call the account API
    from here: that fetch already runs when the card opens the grid.
    Signed out, the Watch Later row is the sign-in card. Signed in,
    it is a More card that opens the library band.
    """
    from lib.ui.compat import L
    from lib.ui.uicommon import CANCELLED, run_cancellable

    _set_shelf(
        window, CONTINUE_SHELF, 30140, 'shelf_continue',
        L(30241).upper(), _continue_posters(store, []),
    )
    _set_shelf(
        window, WATCHLATER_SHELF, 30141, 'shelf_watchlater',
        L(30422).upper(), _watchlater_posters(auth, []),
    )
    enabled = _enabled_shelf_types(addons)
    if getattr(window, '_catalog_pages', None) is None:
        loaded = run_cancellable(lambda: _catalog_pages(addons, enabled), L(30033))
        if loaded is CANCELLED or not isinstance(loaded, dict):
            loaded = {}
        window._catalog_pages = loaded
    pages = window._catalog_pages
    for action, list_id, label_id in _SHELVES:
        items = []
        if action in enabled:
            items = [_poster_item(meta) for meta in pages.get(action, [])]
            items.append(_more_item(action))
        _set_shelf(
            window, list_id, label_id, 'shelf_%s' % action,
            L(L_FOR_ACTION[action]).upper(), items,
        )


def _status_text(auth):
    """Render HomeWindow's top status line from the same `get_auth()`
    result onInit() already fetched for `show_library`: uses the shared
    "Logged in as <email/name/?>" string (30022), the same one
    `lib.ui.views.login()` shows as a post-login notification; the
    logged-out case uses its own string id (30190). Both states are
    prefixed with a `[COLOR]`-tinted `●` indicator dot per the design's
    status pill (font10 is NotoSans and covers U+25CF; Mono26 does not)."""
    from lib.ui.compat import L

    if not auth:
        return '[COLOR 57EEF3F6]\u25cf[/COLOR] %s' % L(30190)
    user = auth.get('user') or {}
    text = L(30022) % (user.get('email') or user.get('name') or '?')
    return '[COLOR FF38BDF8]\u25cf[/COLOR] %s' % text


class HomeWindow(BaseWindow):
    """See module docstring. Built/run via `open_home()`."""

    def onInit(self):
        # Recomputed every onInit(): onInit() re-runs on every resume from
        # a nested modal, so a sign-in or a newly installed catalog shows
        # up on the way back here without restarting the addon. `_build`
        # is the same path Settings and Sign in call when they return,
        # because those dialogs do not resume the window by themselves.
        self._build()

    def _build(self):
        from lib.ui.compat import addon_fanart, setting_bool
        from lib.ui.mystuff import has_content

        store = get_store()
        auth = store.get_auth()
        show_mystuff = setting_bool('home_show_mystuff', True) and has_content(store)
        self.getControl(BACKGROUND).setImage(addon_fanart())
        # reset() before addItems(): onInit() runs again when
        # uicommon.ModalStackWindow reopens a screen force-closed for
        # playback, and re-adding onto a retained list would double every
        # item. All three menu lists are rebuilt together: a type chip
        # appearing must move Search back onto the top strip, and the
        # other way around when the last type chip disappears.
        addons = store.get_enabled_addons()
        watch, browse, tools, show_tools = _place_menu(_menu_items(show_mystuff, addons))
        _apply_signed_out_copy(watch, auth)
        if not auth:
            (tools if show_tools else browse).append(_signin_item())
        for control_id, rows in ((LIST, watch), (BROWSE_LIST, browse), (TOOLS_LIST, tools)):
            control = self.getControl(control_id)
            control.reset()
            control.addItems(rows)
        self.setProperty('HomeTools', '1' if show_tools else '')
        self.getControl(STATUS_LABEL).setLabel(_status_text(auth))
        _fill_shelves(self, store, addons, auth)
        self.setFocusId(LIST)
        self._update_hero()

    def _update_hero(self):
        """Paint the backdrop from the focused card or poster.

        A poster carries its own fanart. A menu card does not, and the
        addon's fanart stays up so the hero never goes blank. Failures
        here must not eat the key that moved the focus.
        """
        from lib.ui.compat import addon_fanart

        item = None
        try:
            focus_id = self.getFocusId()
            if focus_id:
                item = self.getControl(focus_id).getSelectedItem()
        except Exception:
            item = None
        title = meta = plot = fanart = ''
        if item is not None:
            title = item.getProperty('hero_title') or item.getLabel() or ''
            meta = item.getProperty('hero_meta') or ''
            plot = item.getProperty('hero_plot') or item.getProperty('subtitle') or ''
            fanart = item.getProperty('fanart') or ''
        try:
            self.getControl(HERO_TITLE).setLabel(title)
            self.getControl(HERO_META).setLabel(meta)
            self.getControl(HERO_PLOT).setText(plot)
            self.getControl(BACKGROUND).setImage(fanart or addon_fanart())
        except Exception:
            pass

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

        if action.getId() in BACK_ACTIONS:
            self.close()
            return
        self._update_hero()

    @gated_input
    def onClick(self, control_id):
        if control_id not in _CLICKABLE:
            return
        focused = self.getControl(control_id).getSelectedItem()
        _activate(self, focused)


def _open_mystuff(window):
    from lib.ui.mystuff import open_my_stuff
    if open_my_stuff():
        window.close()


def _open_signin(window):
    """The existing email/password dialog, then a refresh of this window.

    `views.login()` writes auth.json in this addon's profile and is
    also what Settings > Account runs. Home calls it directly so the
    status line and the Watch Later row update before the dialog's
    RunPlugin directory finish returns.
    """
    from lib.ui.views import login
    login()
    window._build()


def _open_watchlater(window):
    """Open only the saved, never-started library band.

    `open_my_stuff()` with no argument is Continue (every band). Passing
    `BAND_LIBRARY` does not fetch a different collection - see that
    function. Playback still closes Home, the same as Continue.

    With no auth in this profile the library call would only notify
    "not logged in". Ask for the one-time sign-in first, and open the
    band only after it lands.
    """
    if not get_store().get_auth():
        _open_signin(window)
        if not get_store().get_auth():
            return
    from lib.ui.mystuff import BAND_LIBRARY, open_my_stuff
    if open_my_stuff(bands=(BAND_LIBRARY,)):
        window.close()


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
    # Nested modal: the picker draws over Home, so Home stays open -
    # backing all the way out returns here rather than exiting the addon.
    from lib.ui.catalogpicker import open_catalog_picker
    from lib.ui.compat import L
    types = TYPE_ROW_TYPES[action]
    if types is None:  # 'other': not a fixed set - compute the remainder live
        types = _remainder_types(_available_types(get_store().get_enabled_addons()))
    if open_catalog_picker(types=types, heading=L(L_FOR_ACTION[action])):
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
    # Account > Login returns here without re-running onInit. Rebuild
    # so the status line leaves "Not logged in" in the same visit.
    try:
        window._build()
    except Exception:
        pass


#: action -> the localized-string id its picker uses as a heading, so the
#: filtered screen names the row the user came in through ("MOVIES")
#: rather than the generic catalog-picker title.
L_FOR_ACTION = {action: string_id for string_id, action in _MENU}


_ACTIONS = {
    'mystuff': _open_mystuff,
    'watchlater': _open_watchlater,
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
    version `store` last recorded - the "tell them on next launch" approach
    (as opposed to a boot-time service notification, which is easy to miss
    behind Kodi's splash/home screen). A brand-new install has nothing
    recorded yet, so that first call only seeds the current version and
    stays silent; only version numbers that actually change are ever
    announced.

    Best-effort: `store` I/O failing here must never stop the home screen
    from opening, so any exception is logged and swallowed, same as other
    non-critical HomeWindow paths."""
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
    only logs it for diagnostics and
    guarantees the window is closed (it may not have had a chance to
    self-close, e.g. if onInit() or doModal() itself raised) before
    re-raising.

    The whole session runs under `uicommon.UiHeartbeat`, the liveness marker
    `default.py` consults before opening another Home (see `uicommon`'s
    "UI phases" notes)."""
    import xbmc

    from lib.ui.compat import log

    log('homewindow: opening HomeWindow', xbmc.LOGINFO)
    # Runs here, not in HomeWindow.onInit(): onInit() re-fires every time
    # Home is resumed after a nested modal (Discover/Search/...) closes,
    # which would re-show the toast on every back-navigation. open_home()
    # runs exactly once per addon launch. get_store() itself is guarded
    # here too (not just inside _notify_if_updated): a cosmetic toast must
    # never stop Home from opening, even if Store construction itself
    # fails (e.g. an unwritable profile directory).
    _migrate_mystuff_setting()
    with UiHeartbeat():
        # Everything below runs under the heartbeat, so a second interpreter
        # (Kodi re-running the plugin root after playback - see
        # uicommon's phase notes) can tell a live UI is already up and
        # `default.py` does not open another HomeWindow over it. The
        # heartbeat is cleared and its thread joined on every exit path.
        try:
            _notify_if_updated(get_store())
        except Exception as exc:
            log('homewindow: update-notification store unavailable: %r' % (exc,), xbmc.LOGWARNING)
        win = open_window(HomeWindow, 'HomeWindow.xml')
        try:
            win.doModal()
        except Exception as exc:  # default.py's caller falls back to the recovery directory
            log('homewindow: HomeWindow failed: %r' % (exc,), xbmc.LOGERROR)
            raise
        finally:
            # A normal return means HomeWindow already closed itself; close()
            # again here is a safe no-op. Only a raised exception makes this
            # the window's one chance to close.
            try:
                win.close()
            except Exception:
                pass
    log('homewindow: HomeWindow closed', xbmc.LOGINFO)
