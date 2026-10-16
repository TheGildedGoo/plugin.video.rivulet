# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""HubWindow: one horizontal poster row per catalog of a type.

Home's Movies / Series / Anime / Other chips open this. Every reachable
catalog of that type gets a row. Kodi cannot create controls while a
window is open, so the skin has one vertical list and each row is a
list item. Kodi only draws the rows on screen. Poster pages are fetched
for the first screenful, then for the row the remote lands on and the
one after it, so a long catalog list does not fan out on CoreELEC.

The cells are the same posters Home uses (`homewindow._poster_item` /
`_one_catalog_page`). A row wider than the screen slides its own
posters when the remote moves left and right; the list itself scrolls
vertically.

Search-only catalogs are skipped. They cannot draw a poster until the
viewer types a query. A genre-required catalog uses its first declared
genre so the row is not empty. On the Movies hub, a catalog whose
required genre options are all years is decade tiles instead (1960s
through the current decade). Selecting one merges up to four pages per
year and opens the existing coverflow.

The next unloaded row is fetched off this thread. The row stays on the
grey plates until that fetch lands and the UI thread paints it.

Series, and only Series, may pin a New Episodes row. That calls
`catalogpicker._new_episode_items` and `_mark_episode_seen`. The
card image is the episode still those items carry (`poster`), copied
onto `p0`..`p3` with `layout` `land`. HubWindow.xml paints
`$INFO[ListItem.Property(pN)]` through `mask_land.png` for that row
and through `mask_poster.png` for every other row (`p0`..`p7`).
It does not read `ListItem.Art`. A 2:3 slot letterboxed the still.
The hero title is the episode label (`S1E3 · Title`) and the hero
plot is the episode overview. The series clearlogo is left off that
row: the skin hides the title whenever `HeroLogo` is set.

This module does not change playback, the player, or the Stremio client.
"""
import threading

import xbmcgui

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
from lib.ui.uicommon import BaseWindow, escape_label, gated_input, open_window

#: The vertical list of catalog rows. One control, any number of rows.
HUB_LIST = 31000

#: Posters drawn inside one catalog row. The rest slide in when the
#: remote moves right. 8 * 220px fits the 1800px row. The focus stroke
#: is one fixed control per slot (see HubWindow.xml): a `$INFO` left
#: position is resolved against the window, so the ring sat a
#: list-margin away from the poster it was meant to circle.
VISIBLE_SLOTS = 8

#: New Episodes cards are the Continue landscape, 392x220. Four of
#: those fill the same row. A 2:3 poster slot letterboxed the still.
LAND_SLOTS = 4
_STRIDE = 220

#: How many non-empty rows to fill before the first paint. Two fit on
#: screen; the third is ready for the next Down.
_INITIAL_ROWS = 3

_ACTION_LEFT = 1
_ACTION_RIGHT = 2
_ACTION_UP = 3
_ACTION_DOWN = 4
_ACTION_CONTEXT = 117

_BUTTON_ACTIONS = {
    BTN_SEARCH: 'search',
    BTN_ADDONS: 'addons',
    BTN_SETTINGS: 'settings',
    BTN_SIGNIN: 'signin',
}


def _heading_for(catalog):
    name = catalog.get('name') or catalog.get('id') or ''
    return str(name)


def _descriptors(addons, types):
    """Every non-search catalog of `types`, in addon order. No HTTP.

    `posters is None` means the page has not been fetched. An empty list
    means it was fetched and had nothing to draw.
    """
    import xbmc

    from lib.stremio.addons import _base_type, catalog_extra_options, iter_catalogs
    from lib.ui.catalogpicker import _classify_catalog, _reachable_catalogs
    from lib.ui.compat import log

    wanted = {_base_type(t) for t in types}
    catalogs = [
        entry for entry in iter_catalogs(addons)
        if _base_type(entry[2].get('type')) in wanted
    ]
    catalogs = _reachable_catalogs(catalogs)
    descs = []
    skipped_search = 0
    for transport, manifest, catalog in catalogs:
        kind = _classify_catalog(catalog)
        if kind == 'search':
            skipped_search += 1
            continue
        extra = None
        if kind == 'genre':
            options = catalog_extra_options(catalog, 'genre')
            if not options:
                continue
            # Movies only. A series year catalog keeps the first option,
            # which is what that row has always drawn.
            if wanted == {'movie'}:
                from lib.stremio.decades import decade_tiles, is_year_catalog

                if is_year_catalog(catalog):
                    tiles = decade_tiles(options)
                    if not tiles:
                        continue
                    descs.append({
                        'heading': _heading_for(catalog),
                        'kind': 'decade',
                        'layout': 'decade',
                        'transport': transport,
                        'manifest': manifest,
                        'catalog': catalog,
                        'extra': None,
                        'tiles': tiles,
                        'posters': _decade_posters(tiles),
                        'col': 0,
                    })
                    continue
            extra = [('genre', options[0])]
        descs.append({
            'heading': _heading_for(catalog),
            'kind': 'catalog',
            'transport': transport,
            'manifest': manifest,
            'catalog': catalog,
            'extra': extra,
            'posters': None,
            'col': 0,
        })
    if skipped_search:
        log('hub: skipped %d search-only catalogs' % skipped_search, xbmc.LOGINFO)
    return descs


def _episode_number(value):
    """A season or episode field, or 0 when the addon sent none."""
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _episode_code(episode):
    """``S:1 E:2``. Empty when the video has neither number."""
    season = _episode_number(episode.get('season'))
    number = _episode_number(episode.get('episode'))
    if season <= 0 and number <= 0:
        return ''
    return 'S:%d E:%d' % (season, number)


def _contiguous_shows(episodes):
    """Episodes of one show in one run. Show order is first appearance.

    The row is still a single horizontal strip. Grouping only decides
    which cards sit next to each other, so the divider between shows
    has one place to land.
    """
    order = []
    buckets = {}
    for episode in episodes:
        key = str(episode.get('id') or episode.get('name') or '')
        group = buckets.get(key)
        if group is None:
            group = []
            buckets[key] = group
            order.append(key)
        group.append(episode)
    grouped = []
    for key in order:
        grouped.extend(buckets[key])
    return grouped


def _episode_descriptor(store, types):
    """The Series hub's first row, or None. The posters are already
    known: this does not fetch a catalog page."""
    from lib.ui.catalogpicker import _SERIES_SCREEN_TYPES, _new_episode_items
    from lib.ui.compat import L, setting_bool
    from lib.ui.homewindow import _poster_item

    if frozenset(types) != _SERIES_SCREEN_TYPES:
        return None
    if not setting_bool('home_show_new_episodes', True):
        return None
    episodes = _contiguous_shows(_new_episode_items(store) or [])
    if not episodes:
        return None
    posters = []
    kept = []
    for index, episode in enumerate(episodes[:SHELF_CAP]):
        # `name` is what `_poster_item` writes into `hero_title`. For
        # this row that has to be the episode (`S1E3 · Title`), not the
        # series. The series name moves to `hero_meta`, the right-quarter panel.
        # No logo: HubWindow.xml hides the title while HeroLogo is set,
        # and the series clearlogo would put the show's name back.
        item = _poster_item({
            'name': episode.get('label') or episode.get('name'),
            'type': episode.get('type'),
            'id': episode.get('id'),
            'poster': episode.get('poster'),
            'background': episode.get('background') or episode.get('poster'),
            'description': episode.get('overview') or '',
        })
        show = episode.get('name') or ''
        if show and episode.get('label'):
            item.setProperty('hero_meta', escape_label(show))
            # The panel is the series name, not the show's ratings.
            item.setProperty('hero_facts', '')
        item.setProperty('episode_index', str(index))
        # The card overlay, not the hero. The hero still reads the
        # episode label and the show name the way it always has.
        item.setProperty('card_show', escape_label(show))
        item.setProperty('card_code', _episode_code(episode))
        item.setProperty('show_key', str(episode.get('id') or show))
        posters.append(item)
        kept.append(episode)
    if not posters:
        return None
    return {
        'heading': L(30313).upper(),
        'kind': 'episodes',
        # Wide cards. HubWindow.xml draws mask_land.png for this and
        # mask_poster.png for every other row.
        'layout': 'land',
        'posters': posters,
        'col': 0,
        'episodes': kept,
    }


def _decade_posters(tiles):
    """Grey-plate tiles. No catalog request: the years are on the manifest.

    ``n0``..``n7`` are what the skin centers on the plate. ``decade`` is
    what a click reads so it does not open the tile as a title.
    """
    posters = []
    for tile in tiles:
        item = xbmcgui.ListItem(tile.get('label') or '')
        item.setProperty('decade', str(tile.get('start')))
        item.setProperty('decade_years', ','.join(tile.get('years') or []))
        item.setProperty('hero_title', tile.get('label') or '')
        item.setProperty('stype', 'movie')
        posters.append(item)
    return posters


def _load_posters(desc):
    """The row's first screen. The rest of that page waits on `pending`
    and the pages after it are fetched when the remote nears the end
    (`_extend_row`). A catalog page is not thrown away at 12."""
    if desc.get('posters') is not None:
        return desc['posters']
    from lib.ui.homewindow import _ROW_INITIAL, _one_catalog_page, _poster_item

    metas = _one_catalog_page(
        desc.get('transport'), desc.get('manifest'), desc.get('catalog'),
        extra=desc.get('extra'),
    )
    desc['pending'] = metas[_ROW_INITIAL:]
    desc['gen'] = None
    desc['exhausted'] = False
    desc['posters'] = [_poster_item(meta) for meta in metas[:_ROW_INITIAL]]
    return desc['posters']


def _extend_row(desc):
    """Append posters once the cursor is near the ones already drawn.

    Without this, right past the first screen had nowhere to go. The
    list item under the cursor went blank, and the hero title with it.
    """
    posters = desc.get('posters') or []
    if desc.get('exhausted'):
        return posters
    from lib.ui.homewindow import _ROW_LIMIT, _poster_item, _pull_more

    room = _ROW_LIMIT - len(posters)
    if room <= 0:
        desc['exhausted'] = True
        return posters
    added = _pull_more(desc, room)
    if not added:
        return posters
    posters.extend(_poster_item(meta) for meta in added)
    desc['posters'] = posters
    return posters


def _fill_prefix(descs, limit):
    """Fetch from the front until `limit` rows have posters, dropping
    empty catalogs. Later rows stay unloaded."""
    index = 0
    filled = 0
    while index < len(descs) and filled < limit:
        if not _load_posters(descs[index]):
            del descs[index]
            continue
        filled += 1
        index += 1
    return descs


def _ensure_loaded(descs, index):
    """Fetch the focused row and the next one. An empty focused row is
    removed so Down does not land on a blank header."""
    if index < 0:
        return 0
    if index < len(descs) and not _load_posters(descs[index]):
        del descs[index]
    nxt = index + 1
    if nxt < len(descs) and descs[nxt].get('posters') is None:
        if not _load_posters(descs[nxt]):
            del descs[nxt]
    if index >= len(descs):
        return max(0, len(descs) - 1)
    return index


def _apply_posters(row_item, posters, col, layout=''):
    """Copy the visible slice of `posters` onto the row, and the focused
    poster's hero fields so `paint_hero` can read the list item.

    `layout` `land` is the New Episodes row: four 16:9 slots. Anything
    else is eight posters. Properties past the slot count are cleared
    so a wide row does not leave a portrait image in `p4`.
    """
    slots = LAND_SLOTS if layout == 'land' else VISIBLE_SLOTS
    row_item.setProperty('layout', layout or '')
    count = len(posters)
    if not count:
        col = 0
        start = 0
    else:
        col = max(0, min(col, count - 1))
        start = 0 if col < slots else col - slots + 1
    for slot in range(VISIBLE_SLOTS):
        src = start + slot
        if slot < slots and src < count:
            poster = posters[src]
            row_item.setProperty('p%d' % slot, poster.getProperty('thumbnail'))
            row_item.setProperty('n%d' % slot, poster.getLabel())
        else:
            row_item.setProperty('p%d' % slot, '')
            row_item.setProperty('n%d' % slot, '')
    # Episode captions exist only on the Series landscape row. A poster
    # row clears them so a recycled list item cannot keep a show name.
    prev_show = ''
    for slot in range(LAND_SLOTS):
        src = start + slot
        show = ''
        code = ''
        key = ''
        if layout == 'land' and slot < slots and src < count:
            poster = posters[src]
            show = poster.getProperty('card_show')
            code = poster.getProperty('card_code')
            key = poster.getProperty('show_key')
        row_item.setProperty('show%d' % slot, show)
        row_item.setProperty('code%d' % slot, code)
        if slot:
            split = bool(layout == 'land' and key and prev_show and key != prev_show)
            row_item.setProperty('div%d' % slot, '1' if split else '')
        if key:
            prev_show = key
    # Slot inside the visible window, not a pixel left. The skin has one
    # stroke per slot at that poster's own rectangle; a computed left
    # landed in window coordinates and the ring missed the card.
    row_item.setProperty('focusslot', str(col - start))
    if count:
        poster = posters[col]
        row_item.setProperty('hero_title', poster.getProperty('hero_title'))
        row_item.setProperty('hero_meta', poster.getProperty('hero_meta'))
        row_item.setProperty('hero_facts', poster.getProperty('hero_facts'))
        row_item.setProperty('hero_plot', poster.getProperty('hero_plot'))
        row_item.setProperty('hero_logo', poster.getProperty('hero_logo'))
        row_item.setProperty('fanart', poster.getProperty('fanart'))
        row_item.setProperty('sid', poster.getProperty('sid'))
        row_item.setProperty('stype', poster.getProperty('stype'))
        row_item.setProperty('thumbnail', poster.getProperty('thumbnail'))
        row_item.setProperty('episode_index', poster.getProperty('episode_index'))
    row_item.setProperty('col', str(col))


def _paint_list(window, select=None):
    items = []
    for desc in window._descs:
        item = xbmcgui.ListItem(desc.get('heading') or '')
        item.setProperty('heading', desc.get('heading') or '')
        posters = desc.get('posters') or []
        if posters:
            _apply_posters(item, posters, desc.get('col') or 0, desc.get('layout') or '')
        items.append(item)
    control = window.getControl(HUB_LIST)
    control.reset()
    if not items:
        return
    control.addItems(items)
    if select is None:
        select = 0
    control.selectItem(max(0, min(select, len(items) - 1)))


def _current_poster(window):
    index = window.getControl(HUB_LIST).getSelectedPosition()
    if index < 0 or index >= len(window._descs):
        return None
    desc = window._descs[index]
    posters = desc.get('posters') or []
    if not posters:
        return None
    col = min(desc.get('col') or 0, len(posters) - 1)
    return posters[col]


def _row_lock(window):
    lock = getattr(window, '_row_lock', None)
    if lock is None:
        lock = threading.Lock()
        window._row_lock = lock
    return lock


def _extend_needs_network(desc):
    """True when the next posters are not already in memory.

    A ``pending`` page was fetched with the first screen. Extending from
    it is a list slice, and the keypress can land on the new poster.
    An empty pending list means the next page is a request, which must
    not block Up/Down/Right on a 15s timeout.
    """
    if not desc or desc.get('exhausted') or desc.get('kind') == 'decade':
        return False
    if desc.get('pending'):
        return False
    return True


def _schedule_row_fetch(window, indexes):
    """Fetch ``indexes`` off the GUI thread. The plates stay grey until
    ``_apply_fetched_rows`` runs on the next action.
    """
    inflight = getattr(window, '_row_fetch_inflight', None)
    if inflight is None:
        window._row_fetch_inflight = set()
        window._row_fetch_threads = []
    todo = []
    for index in indexes:
        if index in window._row_fetch_inflight:
            continue
        if index < 0 or index >= len(window._descs):
            continue
        if window._descs[index].get('posters') is not None:
            continue
        todo.append(index)
    if not todo:
        return
    window._row_fetch_inflight.update(todo)

    def _work(indexes_to_load):
        loaded = []
        for index in indexes_to_load:
            try:
                if index < len(window._descs) and window._descs[index].get('posters') is None:
                    _load_posters(window._descs[index])
            except Exception:
                pass
            loaded.append(index)
        with _row_lock(window):
            ready = getattr(window, '_row_fetch_ready', None)
            if ready is None:
                window._row_fetch_ready = loaded
            else:
                ready.extend(loaded)
            for index in indexes_to_load:
                window._row_fetch_inflight.discard(index)
        try:
            import xbmc
            xbmc.executebuiltin('Action(noop)')
        except Exception:
            pass

    thread = threading.Thread(
        target=_work, args=(list(todo),), name='rivulet-hub-row', daemon=True,
    )
    window._row_fetch_threads.append(thread)
    thread.start()


def _join_row_fetches(window):
    """Test hook. Production paints on the noop action the worker wakes."""
    for thread in list(getattr(window, '_row_fetch_threads', []) or []):
        thread.join(timeout=2)


def _apply_fetched_rows(window):
    """Paint rows the worker has finished. UI thread only."""
    with _row_lock(window):
        ready = list(getattr(window, '_row_fetch_ready', None) or [])
        window._row_fetch_ready = []
    if not ready or not window._descs:
        return
    index = window.getControl(HUB_LIST).getSelectedPosition()
    removed = False
    for row in sorted(set(ready), reverse=True):
        if row < len(window._descs) and window._descs[row].get('posters') == []:
            del window._descs[row]
            removed = True
    if removed:
        if not window._descs:
            return
        _paint_list(window, select=max(0, min(index, len(window._descs) - 1)))
        window.setFocusId(HUB_LIST)
        return
    for row in ready:
        _refresh_row(window, row)


def _schedule_extend(window, index):
    """The next page of one row, off the GUI thread."""
    inflight = getattr(window, '_extend_inflight', None)
    if inflight is None:
        window._extend_inflight = set()
    if index in window._extend_inflight:
        return
    window._extend_inflight.add(index)

    def _work():
        try:
            if index < len(window._descs):
                _extend_row(window._descs[index])
        except Exception:
            pass
        with _row_lock(window):
            ready = getattr(window, '_row_fetch_ready', None)
            if ready is None:
                window._row_fetch_ready = [index]
            else:
                ready.append(index)
            window._extend_inflight.discard(index)
        try:
            import xbmc
            xbmc.executebuiltin('Action(noop)')
        except Exception:
            pass

    thread = threading.Thread(target=_work, name='rivulet-hub-extend', daemon=True)
    threads = getattr(window, '_row_fetch_threads', None)
    if threads is None:
        window._row_fetch_threads = [thread]
    else:
        threads.append(thread)
    thread.start()


def _move_col(window, delta):
    index = window.getControl(HUB_LIST).getSelectedPosition()
    if index < 0 or index >= len(window._descs):
        return
    desc = window._descs[index]
    posters = desc.get('posters') or []
    if not posters:
        return
    # Load before clamping, so a right at the end of this screen moves
    # onto the poster that just arrived instead of sticking. A page that
    # is already in memory stays on this turn. A page that still has to
    # be requested does not block the remote.
    if delta > 0 and (desc.get('col') or 0) >= len(posters) - 3:
        if _extend_needs_network(desc):
            _schedule_extend(window, index)
        else:
            posters = _extend_row(desc)
    col = max(0, min((desc.get('col') or 0) + delta, len(posters) - 1))
    desc['col'] = col
    item = window.getControl(HUB_LIST).getSelectedItem()
    if item is not None:
        _apply_posters(item, posters, col, desc.get('layout') or '')


def _refresh_row(window, index):
    """Write one row's posters onto the list item already on screen.
    Rebuilding the whole list would cancel Kodi's row scroll."""
    if index < 0 or index >= len(window._descs):
        return
    control = window.getControl(HUB_LIST)
    if index >= control.size():
        return
    desc = window._descs[index]
    item = control.getListItem(index)
    item.setProperty('heading', desc.get('heading') or '')
    posters = desc.get('posters') or []
    if posters:
        _apply_posters(item, posters, desc.get('col') or 0, desc.get('layout') or '')


def _on_vertical(window):
    """The focused row and the one after it. Unloaded rows are fetched
    off this thread so Down is not a catalog timeout.
    """
    _apply_fetched_rows(window)
    if not window._descs:
        return
    index = window.getControl(HUB_LIST).getSelectedPosition()
    if index < 0:
        return
    pending = []
    for row in (index, index + 1):
        if row < len(window._descs) and window._descs[row].get('posters') is None:
            pending.append(row)
    if pending:
        _schedule_row_fetch(window, pending)
        return
    _refresh_row(window, index)
    _refresh_row(window, index + 1)


class HubWindow(BaseWindow):
    """See module docstring. Built/run via `open_hub()`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.types = frozenset()
        self.heading = ''
        self.should_close_caller = False
        self._descs = None
        self._episodes = []

    def start(self, types, heading):
        """doModal() over the catalogs of `types`. Returns True when
        playback started and the caller (Home) should close too."""
        self.types = frozenset(types or [])
        self.heading = heading or ''
        self.should_close_caller = False
        self._descs = None
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
        if self._descs is None:
            loaded = run_cancellable(
                lambda: _build(store, store.get_enabled_addons(), self.types),
                L(30033),
            )
            if loaded is CANCELLED or not isinstance(loaded, tuple):
                self._descs = []
                self._episodes = []
                self.close()
                return
            self._descs, self._episodes = loaded
            if not self._descs:
                from lib.ui.compat import notify
                # The category opened onto nothing. Keep the message.
                # Kodi's notification chime is what fired on Movies,
                # Series, and Other, so this toast does not play it.
                notify(L(30030), sound=False)
                self.close()
                return
        _paint_list(self, select=self.getControl(HUB_LIST).getSelectedPosition())
        self.setFocusId(HUB_LIST)
        paint_hero(self)
        from lib.ui.posterwarm import collect_poster_urls, request_warm

        groups = []
        for desc in (self._descs or [])[:_INITIAL_ROWS]:
            if desc.get('kind') == 'decade':
                groups.append([])
                continue
            groups.append(desc.get('posters') or [])
        request_warm(collect_poster_urls(groups))

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

        _apply_fetched_rows(self)
        action_id = action.getId()
        if action_id in BACK_ACTIONS:
            self.close()
            return
        if action_id == _ACTION_CONTEXT:
            _offer_library(self)
            return
        if action_id == _ACTION_LEFT:
            _move_col(self, -1)
        elif action_id == _ACTION_RIGHT:
            _move_col(self, 1)
        elif action_id in (_ACTION_UP, _ACTION_DOWN):
            _on_vertical(self)
        paint_hero(self)

    @gated_input
    def onClick(self, control_id):
        if control_id in _BUTTON_ACTIONS:
            _button(self, _BUTTON_ACTIONS[control_id])
            return
        if control_id != HUB_LIST:
            return
        _activate(self, _current_poster(self))


def _build(store, addons, types):
    """Descriptors plus the first screenful of posters, and the episode
    list the New Episodes row indexes into."""
    descs = _descriptors(addons, types)
    episode = _episode_descriptor(store, types)
    episodes = []
    if episode is not None:
        episodes = episode.pop('episodes')
        descs.insert(0, episode)
    _fill_prefix(descs, _INITIAL_ROWS)
    return descs, episodes


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
        from lib.ui.rev2 import is_rev2
        if is_rev2():
            from lib.ui.rev2.settings import open_settings as open_rev2_settings
            open_rev2_settings()
            return
        from lib.ui.compat import ADDON
        ADDON.openSettings()
        return
    if action == 'signin':
        from lib.ui.views import login
        login()
        window._descs = None
        window.onInit()


def _offer_library(window):
    from lib.ui.homewindow import refresh_library_row
    from lib.ui.libraryaction import meta_from_item, offer

    meta = meta_from_item(_current_poster(window))
    if meta is None:
        return
    if offer(meta):
        refresh_library_row(window)


def _activate(window, item):
    if item is None:
        return
    if item.getProperty('decade') != '':
        _open_decade(window, item)
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


def _decade_cache_key(desc, label):
    from lib.stremio.pagecache import cache_key

    catalog = desc.get('catalog') or {}
    return cache_key(
        desc.get('transport'), catalog.get('type'), catalog.get('id'),
        [('decade', label)],
    )


def _fetch_decade(desc, years, label):
    """Merged metas for one decade, from the page cache when it is fresh.

    A stale hit is returned immediately. The pages themselves are what
    carry ``cacheMaxAge`` (Cinemeta sends four hours); the merged list
    is stored under that hint so the second open does not repeat the
    requests.
    """
    from lib.stremio.addons import AddonError, addon_error_detail, safe_url_for_log
    from lib.stremio.decades import merge_decade_pages
    from lib.ui.catalogpages import get_page_cache
    from lib.ui.compat import log
    from lib.ui.dependencies import get_client

    cache = get_page_cache()
    key = _decade_cache_key(desc, label)
    if cache is not None:
        state, cached = cache.lookup(key)
        if state in ('fresh', 'stale') and cached:
            from lib.ui.regiondialog import apply_region_filter

            return apply_region_filter(cached)
    catalog = desc.get('catalog') or {}
    client = get_client()
    hints = {}
    transport = desc.get('transport')

    def fetch(year, skip):
        import xbmc

        extra = [('genre', str(year))]
        if skip:
            extra.append(('skip', str(skip)))
        try:
            metas, page_hints = client.catalog_with_hints(
                transport, catalog.get('type'), catalog.get('id'), extra=extra,
            )
        except AddonError as exc:
            log(
                'hub: decade %s year %s failed: %s' % (
                    label, year, addon_error_detail(exc),
                ),
                xbmc.LOGWARNING,
            )
            raise
        if page_hints:
            hints.update(page_hints)
        return metas, page_hints.get('hasMore') if isinstance(page_hints, dict) else None

    try:
        metas = merge_decade_pages(years, fetch)
    except Exception as exc:
        log('hub: decade %s failed: %r (%s)' % (label, exc, safe_url_for_log(transport)))
        return []
    from lib.stremio.contentrating import filter_metas
    from lib.ui.views import _adult_filtering_enabled

    if _adult_filtering_enabled():
        metas = filter_metas(metas)
    if cache is not None and metas:
        cache.store(key, metas, hints)
        cache.save()
    from lib.ui.regiondialog import apply_region_filter

    return apply_region_filter(metas)


def _open_decade(window, item):
    """Spinner, then the existing coverflow. A picked title still opens
    its page. Back on the spinner cancels the merge.
    """
    from lib.ui.compat import L, notify
    from lib.ui.uicommon import CANCELLED, run_cancellable

    years = [year for year in (item.getProperty('decade_years') or '').split(',') if year]
    label = item.getLabel() or item.getProperty('hero_title') or ''
    index = window.getControl(HUB_LIST).getSelectedPosition()
    if index < 0 or index >= len(window._descs):
        return
    desc = window._descs[index]

    def _load():
        return _fetch_decade(desc, years, label)

    loaded = run_cancellable(_load, L(30033))
    if loaded is CANCELLED:
        return
    if not loaded:
        notify(L(30030), sound=False)
        return
    from lib.ui.detailwindow import open_detail
    from lib.ui.infowindow import open_showcase

    try:
        selected = open_showcase(loaded, catalog_title=desc.get('heading') or label)
    except Exception as exc:
        import xbmc

        from lib.ui.compat import log

        log('hub: decade coverflow failed: %r' % (exc,), xbmc.LOGERROR)
        notify(L(30032), sound=False)
        return
    if not selected:
        return
    if open_detail(selected.get('type') or 'movie', selected.get('id')):
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
    video_id = None
    if episode is not None:
        _mark_episode_seen(episode)
        video_id = episode.get('video_id')
    if open_detail(item.getProperty('stype'), item.getProperty('sid'), video_id=video_id):
        window.should_close_caller = True
        window.close()


def open_hub(types, heading, action=''):
    """Open the hub for `types`. `action` is accepted so Home can pass
    the chip name; the heading is what the screen shows. Returns True
    when the caller should close (playback started)."""
    import xbmc

    from lib.ui.compat import L, log, notify

    if not types:
        notify(L(30030), sound=False)
        return False
    log('hub: opening HubWindow %s (%s)' % (action, heading or ''), xbmc.LOGINFO)
    win = None
    try:
        win = open_window(HubWindow, 'HubWindow.xml')
        return win.start(types, heading)
    except Exception as exc:
        log('hub: window failed to open: %r' % (exc,), xbmc.LOGERROR)
        notify(L(30032), sound=False)
        return False
    finally:
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
