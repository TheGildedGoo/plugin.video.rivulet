# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""HubWindow: one horizontal poster row per catalog of a type.

Home's Movies / Series / Anime / Other chips open this instead of the
vertical catalog list. The rows are the same poster cells Home uses
(`homewindow._poster_item` / `_one_catalog_page`). The skin has a fixed
number of row slots (`HUB_ROWS`); catalogs past that are logged and
left off the screen. Kodi cannot create controls while the window is
open, and this skin has no includes file to clone a row from.

Search-only catalogs are skipped. They cannot draw a poster until the
viewer types a query, and that prompt still lives on the old picker.
A genre-required catalog (Cinemeta's year lists) uses its first declared
genre so the row is not empty.

Series, and only Series, may pin a New Episodes row. That calls
`catalogpicker._new_episode_items` and `_mark_episode_seen` and does
not change them.

This module does not change playback, the player, or the Stremio client.
"""
from lib.ui.dependencies import get_store
from lib.ui.homewindow import (
    BACKGROUND,
    BTN_ADDONS,
    BTN_SEARCH,
    BTN_SETTINGS,
    BTN_SIGNIN,
    SHELF_CAP,
    STATUS_LABEL,
    paint_hero,
)
from lib.ui.uicommon import BaseWindow, gated_input, open_window

#: Eight rows is the skin cap. Past that, a further catalog is dropped
#: with a log line rather than inventing controls at runtime.
HUB_ROWS = tuple(
    (31010 + index, 31110 + index) for index in range(8)
)

_BUTTON_ACTIONS = {
    BTN_SEARCH: 'search',
    BTN_ADDONS: 'addons',
    BTN_SETTINGS: 'settings',
    BTN_SIGNIN: 'signin',
}


def _heading_for(catalog):
    name = catalog.get('name') or catalog.get('id') or ''
    return str(name)


def _row_for_catalog(transport, manifest, catalog):
    """One `(heading, items)` pair, or None when the catalog cannot be
    a poster row. Search-only catalogs are the None case: opening them
    needs a query, and this screen does not prompt."""
    from lib.stremio.addons import catalog_extra_options
    from lib.ui.catalogpicker import _classify_catalog
    from lib.ui.homewindow import _one_catalog_page, _poster_item

    kind = _classify_catalog(catalog)
    if kind == 'search':
        return None
    extra = None
    if kind == 'genre':
        options = catalog_extra_options(catalog, 'genre')
        if not options:
            return None
        extra = [('genre', options[0])]
    metas = _one_catalog_page(transport, manifest, catalog, extra=extra)
    if not metas:
        return None
    items = [_poster_item(meta) for meta in metas[:SHELF_CAP]]
    return _heading_for(catalog), items


def _catalog_rows(addons, types, limit):
    """Reachable, non-search catalogs of `types`, in addon order, capped
    at `limit` rows."""
    import xbmc

    from lib.stremio.addons import _base_type, iter_catalogs
    from lib.ui.catalogpicker import _classify_catalog, _reachable_catalogs
    from lib.ui.compat import log

    wanted = {_base_type(t) for t in types}
    catalogs = [
        entry for entry in iter_catalogs(addons)
        if _base_type(entry[2].get('type')) in wanted
    ]
    catalogs = _reachable_catalogs(catalogs)
    rows = []
    skipped_search = 0
    dropped = 0
    for transport, manifest, catalog in catalogs:
        if _classify_catalog(catalog) == 'search':
            skipped_search += 1
            continue
        if len(rows) >= limit:
            dropped += 1
            continue
        row = _row_for_catalog(transport, manifest, catalog)
        if row is None:
            continue
        rows.append(row)
    if skipped_search:
        log('hub: skipped %d search-only catalogs' % skipped_search, xbmc.LOGINFO)
    if dropped:
        log('hub: %d catalogs past the %d row cap were not shown' % (dropped, limit), xbmc.LOGINFO)
    return rows


def _new_episode_row(store, types):
    """The Series hub's first row, or None. Calls the picker's existing
    helper; a failure there already returns [] and must not blank the hub.
    """
    from lib.ui.catalogpicker import _SERIES_SCREEN_TYPES, _new_episode_items
    from lib.ui.compat import L, setting_bool
    from lib.ui.homewindow import _poster_item

    if frozenset(types) != _SERIES_SCREEN_TYPES:
        return None
    if not setting_bool('home_show_new_episodes', True):
        return None
    episodes = _new_episode_items(store) or []
    if not episodes:
        return None
    items = []
    kept = []
    for index, episode in enumerate(episodes[:SHELF_CAP]):
        item = _poster_item({
            'name': episode.get('name'),
            'type': episode.get('type'),
            'id': episode.get('id'),
            'poster': episode.get('poster'),
            'background': episode.get('background'),
        })
        item.setProperty('episode_index', str(index))
        items.append(item)
        kept.append(episode)
    if not items:
        return None
    return L(30313).upper(), items, kept


def _build_rows(store, addons, types):
    """New Episodes first on Series, then one row per catalog."""
    rows = []
    episodes = []
    pinned = _new_episode_row(store, types)
    if pinned is not None:
        heading, items, episodes = pinned
        rows.append((heading, items))
    rows.extend(_catalog_rows(addons, types, len(HUB_ROWS) - len(rows)))
    return rows, episodes


def _paint_rows(window, rows):
    from lib.ui.homewindow import _set_shelf

    for index, (list_id, label_id) in enumerate(HUB_ROWS):
        if index < len(rows):
            heading, items = rows[index]
            _set_shelf(window, list_id, label_id, 'hub_%d' % index, heading.upper(), items)
        else:
            _set_shelf(window, list_id, label_id, 'hub_%d' % index, '', [])


def _focus_first(window, rows):
    if rows:
        window.setFocusId(HUB_ROWS[0][0])
        return
    window.setFocusId(BTN_SETTINGS)


class HubWindow(BaseWindow):
    """See module docstring. Built/run via `open_hub()`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.types = frozenset()
        self.heading = ''
        self.should_close_caller = False
        self._rows = None
        self._episodes = []

    def start(self, types, heading):
        """doModal() over the catalogs of `types`. Returns True when
        playback started and the caller (Home) should close too."""
        self.types = frozenset(types or [])
        self.heading = heading or ''
        self.should_close_caller = False
        self._rows = None
        self._episodes = []
        self.doModal()
        return self.should_close_caller

    def onInit(self):
        from lib.ui.compat import L, addon_fanart
        from lib.ui.uicommon import CANCELLED, run_cancellable

        store = get_store()
        auth = store.get_auth()
        self.getControl(BACKGROUND).setImage(addon_fanart())
        self.getControl(STATUS_LABEL).setLabel((self.heading or '').upper())
        self.setProperty('HomeSignedOut', '' if auth else '1')
        if self._rows is None:
            loaded = run_cancellable(
                lambda: _build_rows(store, store.get_enabled_addons(), self.types),
                L(30033),
            )
            if loaded is CANCELLED or not isinstance(loaded, tuple):
                self._rows = []
                self._episodes = []
                self.close()
                return
            self._rows, self._episodes = loaded
            if not self._rows:
                from lib.ui.compat import notify
                notify(L(30030))
                self.close()
                return
        _paint_rows(self, self._rows)
        _focus_first(self, self._rows)
        paint_hero(self)

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

        if action.getId() in BACK_ACTIONS:
            self.close()
            return
        paint_hero(self)

    @gated_input
    def onClick(self, control_id):
        if control_id in _BUTTON_ACTIONS:
            _button(self, _BUTTON_ACTIONS[control_id])
            return
        list_ids = {list_id for list_id, _label in HUB_ROWS}
        if control_id not in list_ids:
            return
        item = self.getControl(control_id).getSelectedItem()
        _activate(self, item)


def _button(window, action):
    if action == 'search':
        from lib.ui.searchwindow import open_search
        if open_search():
            window.should_close_caller = True
            window.close()
        return
    if action == 'addons':
        from lib.ui.addonswindow import open_addons
        open_addons()
        return
    if action == 'settings':
        from lib.ui.compat import ADDON
        ADDON.openSettings()
        return
    if action == 'signin':
        from lib.ui.views import login
        login()
        window._rows = None
        window.onInit()


def _activate(window, item):
    if item is None:
        return
    index = item.getProperty('episode_index')
    # "0" is a real index. An empty property is a normal poster.
    if index != '':
        _open_episode(window, item, index)
        return
    sid = item.getProperty('sid')
    if not sid:
        return
    from lib.ui.detailwindow import open_detail
    if open_detail(item.getProperty('stype'), sid):
        window.should_close_caller = True
        window.close()


def _open_episode(window, item, index):
    """Mark the episode seen, then open its page. `_mark_episode_seen`
    is the picker's existing write; this does not change that rule."""
    from lib.ui.catalogpicker import _mark_episode_seen
    from lib.ui.detailwindow import open_detail

    try:
        episode = window._episodes[int(index)]
    except (ValueError, IndexError):
        episode = None
    if episode is not None:
        _mark_episode_seen(episode)
    if open_detail(item.getProperty('stype'), item.getProperty('sid')):
        window.should_close_caller = True
        window.close()


def open_hub(types, heading, action=''):
    """Open the hub for `types`. `action` is accepted so Home can pass
    the chip name; the heading is what the screen shows. Returns True
    when the caller should close (playback started)."""
    import xbmc

    from lib.ui.compat import L, log, notify

    if not types:
        notify(L(30030))
        return False
    log('hub: opening HubWindow %s (%s)' % (action, heading or ''), xbmc.LOGINFO)
    win = None
    try:
        win = open_window(HubWindow, 'HubWindow.xml')
        return win.start(types, heading)
    except Exception as exc:
        log('hub: window failed to open: %r' % (exc,), xbmc.LOGERROR)
        notify(L(30032))
        return False
    finally:
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
