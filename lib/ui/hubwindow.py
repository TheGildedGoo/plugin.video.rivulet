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
genre so the row is not empty.

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
    episodes = _new_episode_items(store) or []
    if not episodes:
        return None
    posters = []
    kept = []
    for index, episode in enumerate(episodes[:SHELF_CAP]):
        # `name` is what `_poster_item` writes into `hero_title`. For
        # this row that has to be the episode (`S1E3 · Title`), not the
        # series. The series name moves to `hero_meta`, under the title.
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
        item.setProperty('episode_index', str(index))
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
    # Slot inside the visible window, not a pixel left. The skin has one
    # stroke per slot at that poster's own rectangle; a computed left
    # landed in window coordinates and the ring missed the card.
    row_item.setProperty('focusslot', str(col - start))
    if count:
        poster = posters[col]
        row_item.setProperty('hero_title', poster.getProperty('hero_title'))
        row_item.setProperty('hero_meta', poster.getProperty('hero_meta'))
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


def _move_col(window, delta):
    index = window.getControl(HUB_LIST).getSelectedPosition()
    if index < 0 or index >= len(window._descs):
        return
    desc = window._descs[index]
    posters = desc.get('posters') or []
    if not posters:
        return
    # Load before clamping, so a right at the end of this screen moves
    # onto the poster that just arrived instead of sticking.
    if delta > 0 and (desc.get('col') or 0) >= len(posters) - 3:
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
    index = window.getControl(HUB_LIST).getSelectedPosition()
    before = len(window._descs)
    index = _ensure_loaded(window._descs, index)
    if len(window._descs) != before:
        _paint_list(window, select=index)
        if window._descs:
            window.setFocusId(HUB_LIST)
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
                notify(L(30030))
                self.close()
                return
        _paint_list(self, select=self.getControl(HUB_LIST).getSelectedPosition())
        self.setFocusId(HUB_LIST)
        paint_hero(self)

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

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
