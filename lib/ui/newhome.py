# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""NewHomeWindow: Rivulet's Home, drawn by NewHomeWindow.xml.

Opened by `homewindow.open_home()`.

A full-bleed backdrop for the focused title, drawn whole rather than
cropped, fading to black toward the left and the bottom. The clearlogo
(or the name), one line of facts, three lines of plot and the scores sit
on the left (`newlook.paint_hero`). One row is visible, pinned to the
bottom of the screen. Down moves to the next row and Up moves back; the
hero follows the focused poster. The type chips (Movies, Series, Anime,
Other) sit in a pill row under the clock, and Search, Add-ons and
Settings are icon buttons in a right-aligned grouplist so they stay on
the right edge at any resolution. Under that, horizontal rows: Continue
(in progress), Library (the Stremio library), and one poster preview per
installed type.

Picking a poster opens its page, except a Continue poster that is
actually mid-playback: that one asks Resume or Episode list (Details,
for a movie). The menu button (long-press on a remote) offers Add to
Library or Remove from Library, and Trailer. Picking a type chip opens
that type's catalog picker, the same screen the stock Home's row opens.

Shared helpers this module calls and does not modify:
`lib.ui.mystuff` (`merge_entries`, `library_metas`, `_fetch_library_entries`,
`_enrich`, the resume percent constants), `lib.ui.views.iter_catalog_pages`
and `lib.ui.detailwindow.open_detail`.
"""
import json
import queue
import threading

import xbmcgui

from lib.ui.dependencies import get_store
from lib.ui.uicommon import BaseWindow, gated_input

BACKGROUND = 30000
STATUS_LABEL = 30005
BROWSE_LIST = 30010  # type chips (Movies, Series, Anime, Other)
TOOLS_LIST = 30011  # right-aligned grouplist: Sign in, Search, Add-ons, Settings
HERO_TITLE = 30020
HERO_META = 30021  # textbox in the right quarter; setText(), not setLabel()
HERO_PLOT = 30022  # textbox; setText(), not setLabel()
HERO_LOGO = 30023
#: Full-bleed poster when a library title has no backdrop. The keep
#: image (``BACKGROUND``) letterboxes a poster; this one scales to cover.
HERO_FILL = 30028
CONTINUE_SHELF = 30040
LIBRARY_SHELF = 30041
BTN_SEARCH = 30070
BTN_ADDONS = 30071
BTN_SETTINGS = 30072
BTN_SIGNIN = 30073

#: How many Continue posters a row keeps. The Library row is the whole
#: account library: cutting it here stopped the focus ring at item 12
#: while the list itself went on. Catalog rows are separate: they show
#: `_ROW_INITIAL` from the first page and append the rest as the remote
#: approaches the end (`_maybe_extend_focused_shelf`).
SHELF_CAP = 12

#: First paint of a catalog row, and the most it will grow to. The first
#: page is often longer than the screen; cutting it at 12 is what made
#: the row stop, drop the hero, and ignore the remote once the visible
#: window was past.
_ROW_INITIAL = 24
_ROW_LIMIT = 80

#: Set when a hub poster changes the account library. Home has no handle
#: on that window, and its row cache would otherwise keep the old
#: Library row until the auth key changed.
_library_dirty = False

#: (action, panel id, header label id) for the poster rows under the
#: chips. Must match NewHomeWindow.xml, including each row's
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

#: Every poster row, in screen order.
_SHELF_IDS = (CONTINUE_SHELF, LIBRARY_SHELF) + tuple(
    list_id for _action, list_id, _label in _SHELVES
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
    """Ratings, year, runtime and genres, one per line.

    The skin draws this in the right quarter. Whatever the meta does
    not carry is left out, so a sparse title never shows a bare label.
    """
    from lib.ui.compat import L
    from lib.ui.playbackmeta import hero_panel_text

    return hero_panel_text(meta, runtime_text=_runtime_text(meta), now_word=L(30234))


def _runtime_minutes(meta):
    """The meta's runtime in whole minutes as a string, or ``''``."""
    from lib.ui.playbackmeta import parse_duration_seconds

    seconds = parse_duration_seconds(meta.get('runtime')) if isinstance(meta, dict) else None
    return str(int(seconds // 60)) if seconds else ''


def _poster_item(meta, action='', sparse=False):
    """One shelf cell. `action` set means the click opens that menu
    action (Sign in) instead of the title's page.

    `sparse` is a library record: a name and a poster, and sometimes a
    backdrop, with no description. The hero for that cell is filled in
    on focus (`_schedule_library_meta`). Until that answer arrives, a
    poster with no backdrop is drawn full-bleed (`hero_fill`) instead
    of letterboxed on the black plate.
    """
    from lib.stremio.ratings import panel_facts
    from lib.ui.uicommon import escape_label
    from lib.ui.urlutil import sized_image

    name = meta.get('name') or ''
    background = meta.get('background') or ''
    poster = meta.get('poster') or ''
    from lib.ui import previews

    previews.remember(meta)
    item = xbmcgui.ListItem(escape_label(name))
    item.setProperties({
        # TMDB `original` art is megabytes for a 200px card (#18).
        'thumbnail': sized_image(poster, 'poster'),
        'fanart': sized_image(background, 'backdrop') if background else sized_image(poster, 'fill'),
        'hero_logo': meta.get('logo') or '',
        'hero_title': escape_label(name),
        'hero_meta': escape_label(_hero_meta_text(meta)),
        'hero_plot': escape_label(_truncate(meta.get('description') or '', 280)),
        'hero_facts': json.dumps(panel_facts(meta), ensure_ascii=False, separators=(',', ':')),
        # Minutes, for the hero's "Ends at" (lib/ui/newlook.py).
        'hero_runtime': _runtime_minutes(meta),
        # No backdrop: the poster fills the hero (scaled to cover) instead
        # of standing as a narrow pillarbox in the middle (#21). Library
        # records used to be the only ones; any catalog title can lack one.
        'hero_fill': '1' if not background and poster else '',
        'needs_meta': '1' if sparse and meta.get('id') and meta.get('type') and not action else '',
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


class CatalogUnavailable(Exception):
    """A catalog's first page failed (timeout, HTTP error, addon error).

    Not the same as an empty catalog: a hub row keeps a Try again card
    for it instead of disappearing (#16). Already logged when raised.
    """


def _one_catalog_page(transport, manifest, catalog, extra=None):
    """The first page of one catalog, uncut.

    Callers keep `_ROW_INITIAL` for the first paint and hold the rest
    back. The generator is not walked here: the following pages are
    fetched only when the remote nears the end of what is on screen
    (`_pull_more`), so opening Home does not pull a whole catalog.

    A failure is logged with the addon's own detail and raised as
    `CatalogUnavailable`; it used to be swallowed into an empty list,
    with no log line, so a broken addon's row just vanished (#16).
    """
    import xbmc

    from lib.stremio.addons import AddonError, addon_error_detail, safe_url_for_log
    from lib.ui.catalogpages import cached_first_page
    from lib.ui.compat import log

    name = (catalog or {}).get('id') if isinstance(catalog, dict) else ''
    try:
        return cached_first_page(transport, manifest, catalog, extra)
    except AddonError as exc:
        log('home: catalog %s failed: %s (%s)' % (
            name, addon_error_detail(exc), safe_url_for_log(transport or ''),
        ), xbmc.LOGWARNING)
        raise CatalogUnavailable(name)
    except Exception as exc:
        log('home: catalog %s failed: %s' % (name, addon_error_detail(exc)), xbmc.LOGWARNING)
        raise CatalogUnavailable(name)


def _shelf_page_gen(state):
    """The catalog generator positioned on page 2.

    Page 1 is already on the row (and in `state['pending']` when it did
    not fit). The generator starts at `skip` = page one's length, with
    page one's ids already seen, so page one is not fetched again.
    """
    if not state or not state.get('transport') or not state.get('catalog'):
        return None
    gen = state.get('gen')
    if gen is not None:
        return gen
    from lib.ui.views import iter_catalog_pages_after

    catalog = state['catalog']
    first = [meta for meta in (state.get('metas') or []) if isinstance(meta, dict)]
    gen = iter_catalog_pages_after(
        state['transport'], catalog.get('type'), catalog.get('id'),
        len(first), [meta.get('id') for meta in first],
        extra=state.get('extra'), catalog=catalog, manifest=state.get('manifest'),
    )
    state['gen'] = gen
    return gen


def _pull_more(state, room):
    """Up to `room` more metas for a row that is about to run out.

    Leftover metas from the page already fetched come first, so reaching
    the end of the first screen does not hit the network. A later page
    is fetched only once that leftover is on screen. An empty answer
    marks the row finished; the hero stays on the last real poster.
    """
    if not state or room <= 0 or state.get('exhausted'):
        return []
    pending = list(state.get('pending') or [])
    if pending:
        state['pending'] = pending[room:]
        return pending[:room]
    gen = _shelf_page_gen(state)
    if gen is None:
        state['exhausted'] = True
        return []
    try:
        page = next(gen)
    except StopIteration:
        state['exhausted'] = True
        return []
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
        from lib.stremio.addons import addon_error_detail
        from lib.ui.compat import log
        log('home: next catalog page failed: %s' % addon_error_detail(exc))
        state['exhausted'] = True
        return []
    batch = [meta for meta in (page or []) if isinstance(meta, dict)]
    if not batch:
        state['exhausted'] = True
        return []
    state['pending'] = batch
    return _pull_more(state, room)


def _open_shelf(addons, types):
    """The first catalog of `types`, plus the leftover metas past the
    first screen. None when nothing of that type is installed."""
    from lib.stremio.addons import _base_type, iter_catalogs

    for transport, manifest, catalog in iter_catalogs(addons):
        if _base_type(catalog.get('type')) not in types:
            continue
        try:
            metas = _one_catalog_page(transport, manifest, catalog)
        except CatalogUnavailable:
            # Logged already. Home's preview row stays hidden, as before.
            metas = []
        return {
            'metas': metas,
            'transport': transport,
            'manifest': manifest,
            'catalog': catalog,
            'extra': None,
            'pending': metas[_ROW_INITIAL:],
            'gen': None,
            'exhausted': False,
        }
    return None


def _set_shelf(window, list_id, label_id, prop, heading, items):
    control = window.getControl(list_id)
    control.reset()
    if items:
        control.addItems(items)
    # Bold and brighter than before (#11): with one row on screen the
    # heading is the only wayfinding, and font12 at 60% white read faint.
    window.getControl(label_id).setLabel('[B]%s[/B]' % heading if items and heading else '')
    window.setProperty(prop, '1' if items else '')


#: Row panel -> its "row / rows" label at the right end of the heading
#: (NewHomeWindow.xml). Only one row is on screen at a time, so the count is
#: the only cue to how far down the list you are (#20).
_ROW_COUNTERS = (
    (CONTINUE_SHELF, 'shelf_continue', 30150),
    (LIBRARY_SHELF, 'shelf_library', 30151),
) + tuple(
    (list_id, 'shelf_%s' % action, 30152 + index)
    for index, (action, list_id, _label) in enumerate(_SHELVES)
)


def _number_rows(window):
    """Write "row / rows" on every visible row, in screen order.

    Run after any shelf is filled or emptied: Continue appearing after a
    first playback shifts every count below it. Count-neutral digits, no
    word to translate. A window without the labels skips.
    """
    visible = [(prop, counter) for _list_id, prop, counter in _ROW_COUNTERS if window.getProperty(prop)]
    total = len(visible)
    shown = {counter: index + 1 for index, (_prop, counter) in enumerate(visible)}
    for _list_id, _prop, counter in _ROW_COUNTERS:
        try:
            label = window.getControl(counter)
        except Exception:
            continue
        index = shown.get(counter)
        label.setLabel('%d / %d' % (index, total) if index and total > 1 else '')


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
    from lib.ui.mystuff import BAND_RESUME, RESUME_MAX_PERCENT, RESUME_MIN_PERCENT

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
        state = entry.get('state') if isinstance(entry.get('state'), dict) else {}
        metas.append({
            'id': entry.get('_id'),
            'name': entry.get('name'),
            'type': entry.get('type'),
            'poster': entry.get('poster'),
            'background': entry.get('background'),
            'band': BAND_RESUME,
            'video_id': state.get('video_id') or None,
            'position_ms': state.get('timeOffset'),
            'duration_ms': state.get('duration'),
        })
    return metas


def _merge_played(progress_entries, library_entries):
    """`mystuff.merge_entries()` plus each played row's position and
    duration, which a Continue poster's Resume needs
    (`_continue_offset_ms`). The rows are the merge's own; the two
    fields are copied from the same latest-per-title progress entry the
    merge banded."""
    from lib.ui.mystuff import latest_by_title, merge_entries

    merged = merge_entries(progress_entries, library_entries)
    latest = {
        (entry.get('type'), entry.get('id')): entry
        for entry in latest_by_title(progress_entries)
    }
    for entry in merged:
        source = latest.get((entry.get('type'), entry.get('id')))
        if source is None:
            continue
        for key in ('position_ms', 'duration_ms'):
            if entry.get(key) is None:
                entry[key] = source.get(key)
    return merged


def _newest_first(entries):
    """Library records newest `_ctime` (the added time) first. A row with
    no `_ctime` falls back to `_mtime`, then stays in the order it
    arrived. The Library row reads in this order."""
    kept = [entry for entry in entries or [] if isinstance(entry, dict)]
    return sorted(kept, key=lambda entry: entry.get('_ctime') or entry.get('_mtime') or '', reverse=True)


def _played_posters(store, library_entries):
    """Resume, next-up and recently finished. Never the library band.

    `merge_entries()` is what copies a saved title's name and poster onto
    a local progress row. `_enrich()` runs only for rows that still have
    neither, so a home paint does not fan out a meta fetch for every
    series just to learn the next episode code.
    """
    from lib.ui.mystuff import BAND_LIBRARY, _enrich

    try:
        merged = _merge_played(store.get_progress_entries(), library_entries)
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
        posters.append(_continue_item(entry))
        if len(posters) >= SHELF_CAP:
            return posters
    for meta in _library_continue_metas(library_entries):
        key = (meta.get('type'), meta.get('id'))
        if key in seen:
            continue
        seen.add(key)
        posters.append(_continue_item(meta))
        if len(posters) >= SHELF_CAP:
            break
    return posters


def _library_posters(auth, library_entries, more=None):
    """Every non-removed libraryItem, as posters. Signed out, one Sign in
    cell. Signed in and empty, the existing empty-library notice.

    Build the same first slice as catalog rows. The rest stay as metas
    until focus nears the end; the library keeps its whole order and has
    no More tile or terminal catalog cap.
    """
    from lib.ui.compat import L
    from lib.ui.mystuff import library_metas

    if more is not None:
        more.pop('library', None)
    if not auth:
        return [_poster_item(
            {'name': L(30427), 'description': L(30428)}, action='signin',
        )]
    try:
        metas = library_metas(_newest_first(library_entries))
    except Exception:
        metas = []
    if more is not None:
        more['library'] = {'pending': metas[_ROW_INITIAL:], 'exhausted': not metas}
    posters = [_poster_item(meta, sparse=True) for meta in metas[:_ROW_INITIAL]]
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
    from lib.ui.mystuff import _fetch_library_entries, apply_library_writes

    try:
        # A write this session already pushed (`libraryaction`) shows
        # before the account echoes it.
        fetched = apply_library_writes(_fetch_library_entries(store))
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


#: Home's own bound on its first-screen fetches (the library read plus
#: one page per row). Every fan-out point bounds its own pool on these
#: low-power boxes; see AGENTS.md before sharing it with another one.
_MAX_HOME_WORKERS = 4


def _catalog_pages(addons, enabled):
    """First screen per enabled shelf, and the state that appends the rest.

    `pages` is what the row draws now. `more` is what `_pull_more` walks
    when the remote nears the end. One request per shelf at open, all at
    once (#13): the rows used to be fetched one after another, so opening
    Home cost the sum of every addon's answer instead of the slowest one.
    """
    pages = {}
    more = {}
    actions = list(enabled.items())
    work = queue.Queue()
    results = queue.Queue()
    for index, (action, types) in enumerate(actions):
        work.put((index, action, types))

    def _worker():
        while True:
            try:
                index, action, types = work.get_nowait()
            except queue.Empty:
                return
            try:
                shelf = _open_shelf(addons, types)
            except Exception as exc:
                from lib.stremio.addons import addon_error_detail
                from lib.ui.compat import log

                log('home: row %s failed: %s' % (action, addon_error_detail(exc)))
                shelf = None
            results.put((index, action, shelf))

    # Reserve one of Home's slots for the account library read. Raw daemons
    # have no executor atexit join: Back can abandon a slow addon at exit.
    for _ in range(min(len(actions), _MAX_HOME_WORKERS - 1)):
        threading.Thread(target=_worker, name='rivulet-home-load', daemon=True).start()
    finished = {}
    for _ in actions:
        index, action, shelf = results.get()
        finished[index] = (action, shelf)
    shelves = [finished[index] for index in range(len(actions))]
    for action, shelf in shelves:
        if shelf is None:
            pages[action] = []
            more[action] = None
            continue
        pages[action] = shelf['metas'][:_ROW_INITIAL]
        more[action] = shelf
    return pages, more


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
        # The library read and every row's first page run together, and
        # catalog_pages.json is written once at the end (#13).
        from lib.ui.catalogpages import deferred_saves

        library = queue.Queue()

        def _read_library():
            try:
                entries = _fetch_library(store, auth)
            except Exception as exc:
                from lib.stremio.addons import addon_error_detail
                from lib.ui.compat import log

                log('home: library read failed: %s' % addon_error_detail(exc))
                entries = []
            library.put(entries)

        with deferred_saves():
            threading.Thread(target=_read_library, name='rivulet-home-library', daemon=True).start()
            pages, more = _catalog_pages(addons, enabled)
            library_entries = library.get()
        return (
            _played_posters(store, library_entries),
            _library_posters(auth, library_entries, more),
            pages,
            more,
        )

    loaded = run_cancellable(_load, L(30033))
    if loaded is CANCELLED or not isinstance(loaded, tuple) or len(loaded) != 4:
        return [], [], {}, enabled
    continue_items, library_items, pages, more = loaded
    window._row_key = key
    window._continue_items = continue_items
    window._library_items = library_items
    window._catalog_pages = pages
    window._shelf_more = more
    return continue_items, library_items, pages, enabled


def _warm_shelf_posters(window, pages):
    """Poster textures for the first catalog rows, after they are on screen.

    Continue and Library are not catalog pages. Backgrounds and logos
    are not warmed. The worker waits on ``waitForAbort``.
    """
    from lib.ui.posterwarm import collect_poster_urls, request_warm

    groups = []
    for action, _list_id, _label_id in _SHELVES:
        groups.append(pages.get(action) or [])
    request_warm(window, collect_poster_urls(groups))


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
    _number_rows(window)
    _warm_shelf_posters(window, pages)


def _refill_saved_rows(window, store, auth, entries=None):
    """Continue and Library from a fresh account read. Catalog pages stay
    as they were: a library write does not change what a catalog returns."""
    from lib.ui.compat import setting_bool

    if entries is None:
        entries = _fetch_library(store, auth)
    show_continue = setting_bool('home_show_mystuff', True)
    continue_items = _played_posters(store, entries) if show_continue else []
    more = getattr(window, '_shelf_more', None)
    if more is None:
        more = {}
        window._shelf_more = more
    library_items = _library_posters(auth, entries, more)
    window._continue_items = continue_items
    window._library_items = library_items


def mark_library_dirty():
    """The next Home paint re-reads the account library."""
    global _library_dirty
    _library_dirty = True


def refresh_library_row(window):
    """Re-read the account library into Home's Continue and Library rows.

    A hub has no Library row. It marks the cache dirty, and Home refills
    when the hub closes (`_after_child`). The read is the same
    `_fetch_library` Home already uses, not a new API method. The row
    keeps the poster the remote was on.
    """
    global _library_dirty

    try:
        window.getControl(LIBRARY_SHELF)
    except Exception:
        _library_dirty = True
        return
    _refresh_saved_rows(window)


def _refresh_saved_rows(window, store=None):
    """Continue and Library from a fresh account read, in place.

    The read runs under the cancellable spinner. Back on it keeps the
    rows that were there, still marked dirty. Each row then re-selects
    the title it was on, so the remote does not jump to the first poster.
    """
    global _library_dirty

    from lib.ui.compat import L
    from lib.ui.uicommon import CANCELLED, run_cancellable

    store = store or get_store()

    def _read():
        auth = store.get_auth()
        return auth, _fetch_library(store, auth)

    loaded = run_cancellable(_read, L(30033))
    if loaded is CANCELLED or not isinstance(loaded, tuple):
        _library_dirty = True
        return
    auth, entries = loaded
    place = _remember_place(window)
    _refill_saved_rows(window, store, auth, entries=entries)
    _set_shelf(
        window, CONTINUE_SHELF, 30140, 'shelf_continue',
        L(30241).upper(), window._continue_items,
    )
    _set_shelf(
        window, LIBRARY_SHELF, 30141, 'shelf_library',
        L(30422).upper(), window._library_items,
    )
    _number_rows(window)
    _library_dirty = False
    _restore_place(window, place)


#: Settings a Home row is built from. A Settings visit that changes none
#: of them (and no sign-in, no addon change) leaves the rows, and the
#: remote's place on them, alone.
_ROW_SETTINGS = (
    'home_show_mystuff', 'home_show_movies', 'home_show_series',
    'home_show_anime', 'home_show_other', 'home_hide_adult',
    # Settings > Refresh cached data bumps this (lib/ui/cacherefresh.py).
    'cache_generation',
)


def _home_signature(store):
    """What the rows were built from. Equal signature, same rows."""
    from lib.ui.compat import ADDON

    auth = store.get_auth() or {}
    addons = store.get_enabled_addons() or []
    ids = []
    for descriptor in addons:
        if isinstance(descriptor, dict):
            manifest = descriptor.get('manifest') or {}
            ids.append(str(descriptor.get('transportUrl') or manifest.get('id') or ''))
    settings = []
    for key in _ROW_SETTINGS:
        try:
            settings.append(ADDON.getSetting(key))
        except Exception:
            settings.append('')
    return (auth.get('authKey') if isinstance(auth, dict) else None, tuple(sorted(ids)), tuple(settings))


#: Lists whose selection survives a refresh. The chips list is matched
#: by its `action`, a poster by its `sid`.
def _place_lists():
    return (BROWSE_LIST, CONTINUE_SHELF, LIBRARY_SHELF) + tuple(
        list_id for _action, list_id, _label in _SHELVES
    )


def _item_key(item):
    if item is None:
        return ''
    return item.getProperty('sid') or item.getProperty('action') or item.getLabel() or ''


def _remember_place(window):
    """The focused control and, for every list, the title it is on."""
    try:
        focus = window.getFocusId()
    except Exception:
        focus = 0
    rows = {}
    for list_id in _place_lists():
        try:
            control = window.getControl(list_id)
            rows[list_id] = (_item_key(control.getSelectedItem()), control.getSelectedPosition())
        except Exception:
            continue
    return focus, rows


def _focusable(window, control_id):
    if not control_id:
        return False
    if control_id == BROWSE_LIST:
        try:
            return window.getControl(BROWSE_LIST).size() > 0
        except Exception:
            return False
    if control_id == BTN_SIGNIN:
        return bool(window.getProperty('HomeSignedOut'))
    if control_id in _BUTTON_ACTIONS or control_id == TOOLS_LIST:
        return True
    for prop, list_id in (('shelf_continue', CONTINUE_SHELF), ('shelf_library', LIBRARY_SHELF)):
        if control_id == list_id:
            return bool(window.getProperty(prop))
    for action, list_id, _label in _SHELVES:
        if control_id == list_id:
            return bool(window.getProperty('shelf_%s' % action))
    return False


def _restore_library_slice(window, key, position):
    """Materialize a saved selection before restoring it after a refresh.

    Only posters are lazy; keeping the old focus must not clamp it to the
    first slice when playback or an account write refreshes the library.
    """
    state = (getattr(window, '_shelf_more', None) or {}).get('library')
    if not state or not state.get('pending'):
        return
    control = window.getControl(LIBRARY_SHELF)
    if any(_item_key(control.getListItem(i)) == key for i in range(control.size())):
        return
    pending = state['pending']
    needed = max(0, (position if isinstance(position, int) else 0) + 1 - control.size())
    for index, meta in enumerate(pending):
        if meta.get('id') == key:
            needed = index + 1
            break
    _append_to_shelf(window, LIBRARY_SHELF, _pull_more(state, needed), sparse=True)


def _restore_place(window, place):
    """Put every list back on the title it was on, then the focus."""
    focus, rows = place
    for list_id, (key, position) in rows.items():
        if list_id == LIBRARY_SHELF:
            _restore_library_slice(window, key, position)
        try:
            control = window.getControl(list_id)
            size = control.size()
        except Exception:
            continue
        if size <= 0:
            continue
        target = None
        if key:
            for index in range(size):
                if _item_key(control.getListItem(index)) == key:
                    target = index
                    break
        if target is None:
            target = max(0, min(position if isinstance(position, int) else 0, size - 1))
        control.selectItem(target)
    if _focusable(window, focus):
        window.setFocusId(focus)
        _note_focus(window)
    else:
        _focus_first(window)




def _drop_memory_if_refreshed(window):
    """Settings > Refresh cached data ran in another interpreter: drop
    this one's copies too before the rows are built again."""
    from lib.ui.compat import ADDON

    try:
        generation = ADDON.getSetting('cache_generation') or ''
    except Exception:
        return
    seen = getattr(window, '_cache_generation', None)
    window._cache_generation = generation
    if seen is not None and generation != seen:
        from lib.ui.cacherefresh import clear_memory

        clear_memory()


def _after_child(window, played=False):
    """Bring Home up to date once a screen on top of it has closed.

    Kodi re-runs a dialog's onInit only when the dialog is opened again
    (here, the reopen after playback), not when a dialog above it closes.
    Home used to rely on onInit for both, so a library change or a new
    addon waited for playback, and a reopen rebuilt every row and dropped
    the remote on the first Continue poster. Now: a changed sign-in,
    addon list, or row setting rebuilds the rows and puts the remote back
    where it was; a library change, or coming back from playback,
    re-reads Continue and Library in place; anything else just repaints.
    """
    window._child_refreshed = True
    try:
        store = get_store()
        signature = _home_signature(store)
    except Exception:
        return
    if signature != getattr(window, '_signature', None) or getattr(window, '_catalog_pages', None) is None:
        _drop_memory_if_refreshed(window)
        place = _remember_place(window)
        window._row_key = None
        window._catalog_pages = None
        window._build(place=place)
        return
    if played or _library_dirty:
        _refresh_saved_rows(window, store)
    paint_hero(window)


def _open_child(window, opener):
    """Run a screen over Home. True when Home closed for playback.

    A child that returns True started playback; Home closes with it. A
    plain Back refreshes Home (`_after_child`), unless Home was closed
    for playback underneath, in which case its reopen does that.
    """
    window._child_refreshed = False
    if opener():
        window.close()
        return True
    if getattr(window, '_closed_for_playback', False) or getattr(window, '_child_refreshed', False):
        return False
    _after_child(window)
    return False


def _offer_library(window, item, control_id=None):
    """Menu button on a poster. A chip or a notice has nothing to save.

    A series card on Continue also offers Go to series: the show's page,
    where OK on the card asks to resume the episode instead."""
    from lib.ui.libraryaction import meta_from_item, poster_menu

    meta = meta_from_item(item)
    if meta is None:
        return
    extra = []
    if control_id == CONTINUE_SHELF and item.getProperty('stype') == 'series':
        from lib.ui.compat import L

        extra.append((L(30514), lambda: _open_child(window, lambda: _open_detail_for(item))))
    if poster_menu(meta, extra):
        refresh_library_row(window)


def _note_focus(window):
    """Remember where the remote is, so the next Up can tell a dead end
    from a move (`HomeWindow.onAction`)."""
    try:
        window._last_focus = window.getFocusId()
    except Exception:
        window._last_focus = None


def _focus_first(window):
    """Land on the first row that actually has posters, else the chips,
    else Settings. An empty hidden row must not take the remote."""
    try:
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
    finally:
        _note_focus(window)


def _status_text(auth):
    """Home's top status line. Both states are prefixed with a
    `[COLOR]`-tinted dot (font12 is NotoSans and covers U+25CF).

    Signed in reads "Signed in", not the account's address: Home is on a
    shared TV, often with guests on the sofa (#19). The address stays in
    Settings > Account (`account_user`, kept current by `_build`).
    """
    from lib.ui.compat import L

    if not auth:
        return '[COLOR 57EEF3F6]\u25cf[/COLOR] %s' % L(30190)
    return '[COLOR FFD6D6D6]\u25cf[/COLOR] %s' % L(30488)


def _fit_hero_title(text):
    """One line for the title band. The label does not wrap, and a long
    name used to run through the metadata under it."""
    text = text or ''
    if len(text) <= 48:
        return text
    return text[:47].rstrip() + '\u2026'


def _append_to_shelf(window, list_id, metas, sparse=False):
    """Add `metas` to a shelf, keeping the poster the remote is on.

    `addItems` sends the cursor back to the first cell. The saved
    position is put back so a page landing under the thumb does not
    jump the row, which is the same snap the coverflow already avoids.
    The More cell, when the row has one, stays last.
    """
    if not metas:
        return
    control = window.getControl(list_id)
    pos = control.getSelectedPosition()
    if pos < 0:
        pos = 0
    items = [control.getListItem(index) for index in range(control.size())]
    more = None
    if items and items[-1].getProperty('action') and not items[-1].getProperty('sid'):
        more = items.pop()
    items.extend(_poster_item(meta, sparse=sparse) for meta in metas)
    if more is not None:
        items.append(more)
    control.reset()
    control.addItems(items)
    if items:
        control.selectItem(min(pos, len(items) - 1))
    if list_id == LIBRARY_SHELF:
        window._library_items = items


def _shelf_lock(window):
    lock = getattr(window, '_shelf_lock', None)
    if lock is None:
        lock = threading.Lock()
        window._shelf_lock = lock
    return lock


def _schedule_shelf_extend(window, action, room):
    """The next catalog page for one Home row, off the GUI thread.

    Page two used to be fetched inside onAction: the hero froze, Right
    presses queued, and a slow addon held the row for its whole timeout.
    The answer lands in `_shelf_ready` and is appended on the noop this
    worker posts. One fetch per row at a time.
    """
    inflight = getattr(window, '_shelf_inflight', None)
    if inflight is None:
        inflight = {}
        window._shelf_inflight = inflight
    if action in inflight:
        return
    state = (getattr(window, '_shelf_more', None) or {}).get(action)
    if not state:
        return
    inflight[action] = state

    def _work():
        metas = []
        try:
            metas = _pull_more(state, room)
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            metas = []
        with _shelf_lock(window):
            if (getattr(window, '_shelf_more', None) or {}).get(action) is not state:
                return
            ready = getattr(window, '_shelf_ready', None)
            if ready is None:
                window._shelf_ready = [(action, state, metas)]
            else:
                ready.append((action, state, metas))
            if inflight.get(action) is state:
                inflight.pop(action, None)
        try:
            import xbmc
            xbmc.executebuiltin('Action(noop)')
        except Exception:
            pass

    thread = threading.Thread(target=_work, name='rivulet-home-shelf', daemon=True)
    threads = getattr(window, '_shelf_threads', None)
    if threads is None:
        window._shelf_threads = [thread]
    else:
        threads[:] = [worker for worker in threads if worker.is_alive()]
        threads.append(thread)
    thread.start()


def _join_shelf_extends(window):
    """Test hook. Production appends on the noop the worker posts."""
    for thread in list(getattr(window, '_shelf_threads', []) or []):
        thread.join(timeout=2)


def _apply_shelf_extends(window):
    """Append what the row workers fetched. UI thread only."""
    with _shelf_lock(window):
        ready = list(getattr(window, '_shelf_ready', None) or [])
        window._shelf_ready = []
    for action, state, metas in ready:
        if (getattr(window, '_shelf_more', None) or {}).get(action) is not state:
            continue
        for name, list_id, _label in _SHELVES:
            if name == action and metas:
                _append_to_shelf(window, list_id, metas)


def _maybe_extend_focused_shelf(window):
    """Append the next posters when the remote is within four of the end.

    The row only had the first slice. Moving into the unloaded part
    left the container on a blank item, paint_hero cleared the title,
    and the row stopped taking left and right. What page one still
    holds is appended at once; a further page is fetched off the GUI
    thread (`_schedule_shelf_extend`).
    """
    focus = window.getFocusId()
    action = None
    for name, list_id, _label in _SHELVES:
        if list_id == focus:
            action = name
            break
    if focus == LIBRARY_SHELF:
        action = 'library'
    if action is None:
        return
    state = (getattr(window, '_shelf_more', None) or {}).get(action)
    if not state or state.get('exhausted'):
        return
    if action in (getattr(window, '_shelf_inflight', None) or ()):
        return
    control = window.getControl(focus)
    count = control.size()
    pos = control.getSelectedPosition()
    if count <= 0 or pos < max(0, count - 4):
        return
    shown = 0
    for index in range(count):
        if control.getListItem(index).getProperty('sid'):
            shown += 1
    room = _ROW_INITIAL if action == 'library' else _ROW_LIMIT - shown
    if room <= 0:
        return
    if state.get('pending'):
        _append_to_shelf(window, focus, _pull_more(state, room), sparse=(action == 'library'))
        return
    if action == 'library':
        state['exhausted'] = True
        return
    _schedule_shelf_extend(window, action, room)


def _fetch_library_meta(stype, sid):
    """Backdrop, description, and ratings for one library title.

    A library record is a name and a poster. The other rows already
    show whatever installed addon answers ``meta`` (Cinemeta, when it
    is installed). The same call fills this hero. A miss leaves the
    poster, drawn full-bleed.
    """
    from lib.ui.views import _fetch_meta

    return _fetch_meta(stype, sid)


#: Seconds before a failed library/Continue meta fetch is tried again.
_META_RETRY_SECONDS = 20.0


def _library_meta_lock(window):
    lock = getattr(window, '_library_meta_lock', None)
    if lock is None:
        lock = threading.Lock()
        window._library_meta_lock = lock
    return lock


def _schedule_library_meta(window, item):
    """Fetch the focused library title off the GUI thread.

    The remote must not wait on a catalog. The poster (full-bleed, when
    there is no backdrop) stays up until the answer is applied on the
    next action. A title already fetched, or one in flight, is not
    asked again.
    """
    if item is None or item.getProperty('needs_meta') != '1':
        with _library_meta_lock(window):
            previous = getattr(window, '_library_meta_latest', None)
            if previous is not None:
                previous[0].setProperty('meta_state', '')
            window._library_meta_latest = None
            window._library_meta_pending = None
            window._library_meta_ready = []
        return
    state = item.getProperty('meta_state')
    if state in ('loading', 'done'):
        return
    if state.startswith('failed:'):
        # A fetch that failed (timeout, addon down) is asked again after
        # a pause, not left blank for the session.
        import time
        try:
            failed_at = float(state.split(':', 1)[1])
        except ValueError:
            failed_at = 0.0
        if time.time() - failed_at < _META_RETRY_SECONDS:
            return
    stype = item.getProperty('stype')
    sid = item.getProperty('sid')
    if not stype or not sid:
        return
    request = (item, stype, sid)
    with _library_meta_lock(window):
        previous = getattr(window, '_library_meta_latest', None)
        if previous is not None and previous[0] is not item:
            previous[0].setProperty('meta_state', '')
        item.setProperty('meta_state', 'loading')
        window._library_meta_latest = request
        window._library_meta_pending = request
        window._library_meta_ready = []
        if getattr(window, '_library_meta_running', False):
            return
        window._library_meta_running = True

    thread = threading.Thread(target=_library_meta_worker, args=(window,), name='rivulet-library-meta', daemon=True)
    window._library_meta_thread = thread
    thread.start()


def _library_meta_worker(window):
    """Drain one latest-wins slot; stale answers never reach the GUI."""
    while True:
        with _library_meta_lock(window):
            wanted = window._library_meta_pending
            window._library_meta_pending = None
            if wanted is None:
                window._library_meta_running = False
                return
        _item, wanted_type, wanted_id = wanted
        try:
            meta = _fetch_library_meta(wanted_type, wanted_id)
        except Exception:
            meta = None
        with _library_meta_lock(window):
            if window._library_meta_latest is not wanted:
                continue
            window._library_meta_ready = [(wanted_type, wanted_id, meta)]
        try:
            import xbmc
            xbmc.executebuiltin('Action(noop)')
        except Exception:
            pass



def _join_library_meta(window):
    """Test hook. Production applies the answer on the worker's noop."""
    thread = getattr(window, '_library_meta_thread', None)
    if thread is not None:
        thread.join(timeout=2)


_HERO_PROPS = (
    'thumbnail', 'fanart', 'hero_logo', 'hero_title', 'hero_meta',
    'hero_plot', 'hero_facts', 'hero_fill', 'hero_runtime', 'needs_meta', 'stype', 'sid',
)


def _write_meta_onto(item, meta, keep_label=False):
    """Copy a fetched meta onto the poster that is already on the row.

    Rebuilding the list would send the cursor home. The card keeps its
    place; the hero reads the new properties on the next paint. No
    backdrop still means the poster, full-bleed.
    """
    merged = dict(meta)
    if not merged.get('poster'):
        merged['poster'] = item.getProperty('thumbnail')
    if not merged.get('name'):
        merged['name'] = item.getLabel()
    if not merged.get('id'):
        merged['id'] = item.getProperty('sid')
    if not merged.get('type'):
        merged['type'] = item.getProperty('stype')
    fresh = _poster_item(merged)
    background = merged.get('background') or ''
    poster = merged.get('poster') or item.getProperty('thumbnail') or ''
    if not background and poster:
        from lib.ui.urlutil import sized_image

        fresh.setProperty('hero_fill', '1')
        fresh.setProperty('fanart', sized_image(poster, 'fill'))
    fresh.setProperty('needs_meta', '')
    for key in _HERO_PROPS:
        item.setProperty(key, fresh.getProperty(key))
    label = fresh.getLabel()
    # A Continue card keeps its own label (the show it was started as).
    if label and not keep_label:
        item.setLabel(label)
    item.setProperty('meta_state', 'done')


def episode_label_for(meta, video_id):
    """``(label, overview)`` for `video_id` (``tt..:1:3``): ``S1E3 ·
    Title``, the title and overview from the series meta's videos when it
    has them. ``('', '')`` for anything that is not an episode id."""
    from lib.newepisodes import _episode_label

    if not isinstance(video_id, str) or not video_id:
        return '', ''
    show, season, episode = (video_id.rsplit(':', 2) + ['', ''])[:3]
    if not (show and season.isdigit() and episode.isdigit()):
        return '', ''
    title = overview = ''
    videos = meta.get('videos') if isinstance(meta, dict) else None
    for video in videos or []:
        if isinstance(video, dict) and video.get('id') == video_id:
            title = str(video.get('title') or video.get('name') or '').strip()
            overview = str(video.get('overview') or video.get('description') or '').strip()
            break
    return _episode_label(int(season), int(episode), title), overview


def apply_episode_hero(item, show, label, overview=''):
    """The hero for an episode card: the show's own hero, with the
    episode on top of the facts.

    The card keeps the episode still; the hero does not blow it up. The
    backdrop, clearlogo and title are the show's (its poster full-bleed
    when it has no backdrop), the first facts line is ``S1E3 · Title``,
    then the show's year, runtime and genres, and the plot is the
    episode's overview when there is one.
    """
    from lib.ui.uicommon import escape_label
    from lib.ui.urlutil import sized_image

    show = show if isinstance(show, dict) else {}
    background = show.get('background') or ''
    poster = show.get('poster') or ''
    if isinstance(background, str) and background:
        item.setProperty('fanart', sized_image(background, 'backdrop'))
        item.setProperty('hero_fill', '')
    elif isinstance(poster, str) and poster:
        item.setProperty('fanart', sized_image(poster, 'fill'))
        item.setProperty('hero_fill', '1')
    item.setProperty('hero_logo', show.get('logo') or '')
    name = show.get('name') or ''
    if name:
        item.setProperty('hero_title', escape_label(name))
    lines = [label] if label else []
    panel = _hero_meta_text(show)
    if panel:
        lines.append(panel)
    item.setProperty('hero_meta', escape_label('\n'.join(lines)))
    # The panel is written whole here; the ratings overlay would rebuild
    # it from the show's scores and drop the episode line.
    item.setProperty('hero_facts', '')
    item.setProperty('hero_plot', escape_label(_truncate(overview or show.get('description') or '', 280)))
    item.setProperty('hero_runtime', _runtime_minutes(show))


def _apply_library_meta(window):
    """Write fetched library metas onto their posters. UI thread only."""
    with _library_meta_lock(window):
        ready = list(getattr(window, '_library_meta_ready', None) or [])
        window._library_meta_ready = []
    if getattr(window, '_library_meta_latest', None) is not None:
        try:
            focused = window.getControl(window.getFocusId()).getSelectedItem()
        except Exception:
            focused = None
        ready = [(stype, sid, meta) for stype, sid, meta in ready
                 if focused is not None and focused.getProperty('stype') == stype
                 and focused.getProperty('sid') == sid]
    if not ready:
        return
    import time

    items = []
    # Library records and Continue entries both arrive without a
    # description; both rows get the same hero once the meta lands.
    for shelf in (LIBRARY_SHELF, CONTINUE_SHELF):
        try:
            control = window.getControl(shelf)
            items.extend((shelf, control.getListItem(index)) for index in range(control.size()))
        except Exception:
            continue
    for stype, sid, meta in ready:
        for shelf, item in items:
            if item.getProperty('stype') != stype or item.getProperty('sid') != sid:
                continue
            if meta is None:
                item.setProperty('meta_state', 'failed:%d' % int(time.time()))
                continue
            useful = isinstance(meta, dict) and (
                meta.get('name') or meta.get('background')
                or meta.get('description') or meta.get('poster')
            )
            if useful:
                _write_meta_onto(item, meta, keep_label=(shelf == CONTINUE_SHELF))
                if shelf == CONTINUE_SHELF:
                    _fill_continue_card(item, meta)
                    label, overview = episode_label_for(meta, item.getProperty('video_id'))
                    if label:
                        apply_episode_hero(item, meta, label, overview)
            else:
                item.setProperty('needs_meta', '')
                item.setProperty('meta_state', 'done')


def _fill_continue_card(item, meta):
    """A Continue card with no wide picture takes the fetched backdrop."""
    if item.getProperty('land'):
        return
    background = meta.get('background') if isinstance(meta, dict) else ''
    if isinstance(background, str) and background:
        from lib.ui.urlutil import sized_image

        item.setProperty('land', sized_image(background, 'backdrop'))


def _upcoming_facts(window, count=2):
    """`hero_facts` of the next posters on the focused row, so their
    ratings ride along once the focus rests. [] off a container."""
    facts = []
    try:
        control = window.getControl(window.getFocusId())
        position = control.getSelectedPosition()
        size = control.size()
    except Exception:
        return facts
    if not isinstance(position, int) or position < 0:
        return facts
    for index in range(position + 1, min(size, position + 1 + count)):
        try:
            raw = control.getListItem(index).getProperty('hero_facts') or ''
            parsed = json.loads(raw) if raw else None
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            facts.append(parsed)
    return facts


#: Two 1x1 image slots under the backdrop plate (Home and the hubs) that
#: load a clearlogo before the hero is allowed to show it.
LOGO_WARM_SLOTS = (30098, 30099)

#: How long a logo found missing from Kodi's texture cache is trusted to
#: still be missing before the cache is asked again. A logo that loaded
#: is known good for the rest of the session.
_LOGO_RECHECK_SECONDS = 3.0



def _texture_cached(url):
    """True when Kodi's texture cache holds `url`, i.e. it loaded before.

    A clearlogo that 404s never gets a row in Textures13.db; one that
    loaded once does, in this session or an earlier one. One indexed
    lookup over JSON-RPC (``Textures.GetTextures``). Any failure answers
    False, which only means the text title is shown.
    """
    import xbmc

    request = {
        'jsonrpc': '2.0', 'id': 1, 'method': 'Textures.GetTextures',
        'params': {
            'properties': ['url'],
            'filter': {'field': 'url', 'operator': 'is', 'value': url},
        },
    }
    try:
        answer = json.loads(xbmc.executeJSONRPC(json.dumps(request)) or '{}')
    except Exception:
        return False
    result = answer.get('result') if isinstance(answer, dict) else None
    textures = result.get('textures') if isinstance(result, dict) else None
    return bool(textures)


def _logo_known_good(url):
    """Whether the hero may swap the text title for this clearlogo.

    The skin hides the title whenever a logo is set, so a logo URL that
    404s left the title area blank (#10). Only a logo Kodi has already
    loaded replaces the text; until then the title shows and the logo is
    warmed in a slot.
    """
    import time

    from lib.ui import logocheck

    if not url:
        return False
    # Answered over HTTP (lib/ui/logocheck.py): an image, or not there.
    answered = logocheck.state(url)
    if answered is not None:
        return answered
    now = time.monotonic()
    state = logocheck.texture_state(url)
    if state is not None and (state[0] or now - state[1] < _LOGO_RECHECK_SECONDS):
        return state[0]
    ok = _texture_cached(url)
    logocheck.remember_texture(url, ok, now)
    if ok:
        logocheck.remember(url, True)
    else:
        # Kodi has not drawn it yet: ask its host. The worker repaints
        # the hero when the logo turns out to be real.
        logocheck.ask([url])
    return ok


def _upcoming_logos(window, count=3):
    """Clearlogos of the next posters on the focused row."""
    logos = []
    try:
        control = window.getControl(window.getFocusId())
        position = control.getSelectedPosition()
        size = control.size()
    except Exception:
        return logos
    if not isinstance(position, int) or position < 0:
        return logos
    for index in range(position + 1, min(size, position + 1 + count)):
        try:
            logo = control.getListItem(index).getProperty('hero_logo') or ''
        except Exception:
            logo = ''
        if logo:
            logos.append(logo)
    return logos


def _warm_logos(window, logos):
    """Load `logos` in the 1x1 slots so Kodi caches them. A window
    without the slots warms nothing."""
    from lib.ui import logocheck

    pending = [logo for logo in logos if logo and not (logocheck.texture_state(logo) or (False, 0))[0]]
    for slot, logo in zip(LOGO_WARM_SLOTS, pending):
        try:
            window.getControl(slot).setImage(logo)
        except Exception:
            return


def _set_fill_image(window, image):
    """The scale plate. Hubs have no library row, so the control is absent there."""
    try:
        window.getControl(HERO_FILL).setImage(image)
    except Exception:
        pass


def paint_hero(window, item=None):
    """Paint the backdrop from the focused poster.

    A button has no selected item. Leaving the labels alone in that case
    keeps the last title on screen while the remote is on the top bar,
    which is the reading order of this layout. A poster with no fanart
    falls back to the addon fanart so the hero never goes blank.

    A container that has scrolled past the items it actually holds hands
    back a blank list item. Writing that blank is what cleared the title
    and the plot and left the row looking dead. Keep the previous hero.
    """
    from lib.ui.newlook import fanart as addon_fanart

    if item is None:
        try:
            focus_id = window.getFocusId()
            if focus_id:
                item = window.getControl(focus_id).getSelectedItem()
        except Exception:
            item = None
    if item is None:
        return
    # A library poster has no plot until Cinemeta answers. Ask now, and
    # keep the poster on screen while that request is in flight.
    _schedule_library_meta(window, item)
    title = item.getProperty('hero_title') or ''
    label = item.getLabel() or ''
    if not title and not label and not item.getProperty('sid') and not item.getProperty('hero_logo'):
        return
    meta = item.getProperty('hero_meta') or ''
    facts_raw = item.getProperty('hero_facts') or ''
    if facts_raw and item.getProperty('facts_done') != '1':
        # A ratings key rebuilds this from the cached scores. No key, or
        # a cache miss, leaves the catalog line alone and returns at once.
        from lib.ui.ratingsched import overlay_text

        try:
            facts = json.loads(facts_raw)
        except ValueError:
            facts = None
        if isinstance(facts, dict):
            overlaid = overlay_text(facts, meta, _upcoming_facts(window))
            if overlaid != meta:
                # Scores applied: keep the result on the card, so the next
                # paint of this title skips the decode and the merge (#17).
                item.setProperty('hero_meta', overlaid)
                item.setProperty('facts_done', '1')
            meta = overlaid
    plot = item.getProperty('hero_plot') or item.getProperty('subtitle') or ''
    fanart = item.getProperty('fanart') or ''
    wanted_logo = item.getProperty('hero_logo') or ''
    # The text title stays up until Kodi has loaded the logo once (#10).
    logo = wanted_logo if _logo_known_good(wanted_logo) else ''
    upcoming_logos = _upcoming_logos(window)
    _warm_logos(window, ([wanted_logo] if wanted_logo and not logo else []) + upcoming_logos)
    # The next titles' logos are checked ahead, so they are ready on arrival.
    from lib.ui import logocheck

    logocheck.ask(upcoming_logos)
    fill = item.getProperty('hero_fill') == '1' and bool(fanart)
    runtime = item.getProperty('hero_runtime') or ''
    # Every action repaints (worker noops, mouse moves, a key that did not
    # move). An unchanged hero is a dozen boundary crossings and a bar
    # re-measure for nothing (#17).
    painted = (title or label, meta, plot, fanart, fill, logo, runtime)
    if painted == getattr(window, '_hero_painted', None):
        return
    window._hero_painted = painted
    try:
        window.setProperty('HeroLogo', logo)
        window.getControl(HERO_LOGO).setImage(logo)
        fitted = _fit_hero_title(title or label)
        window.getControl(HERO_TITLE).setLabel(fitted)
        window.getControl(HERO_META).setText(meta)
        window.getControl(HERO_PLOT).setText(plot)
        image = fanart or addon_fanart()
        # HeroFill shows the scale plate and hides the letterboxed one.
        # A real backdrop clears it, so the picture is shown whole.
        window.setProperty('HeroFill', '1' if fill else '')
        window.getControl(BACKGROUND).setImage(image)
        _set_fill_image(window, image if fill else '')
        from lib.ui import newlook

        # No bar: the facts and scores lines, stacked up from the row.
        newlook.paint_hero(window, plot, meta, runtime)
    except Exception:
        pass


class NewHomeWindow(BaseWindow):
    """See module docstring. Built/run by `homewindow.open_home()`."""

    def onInit(self):
        # Kodi re-runs onInit when this dialog is opened again, which is
        # the reopen after playback. That refreshes Continue in place and
        # keeps the remote where it was. The first open builds the rows.
        if getattr(self, '_built', False):
            _after_child(self, played=True)
            return
        self._build()
        self._built = True

    def _build(self, place=None):
        """Keep a failed build on Home, with empty/hidden poster rows.

        A data failure must not send the whole addon to recovery. This
        uses the same hidden-row state as a failed catalog fetch and
        adds no error controls to the pinned skin.
        """
        with _shelf_lock(self):
            self._shelf_ready = []
            self._shelf_inflight = {}
            self._shelf_threads = []
            self._shelf_more = {}
        try:
            self._build_rows(place)
        except Exception as exc:
            import xbmc

            from lib.stremio.addons import addon_error_detail
            from lib.ui.compat import log

            log('home: build failed: %s' % addon_error_detail(exc), xbmc.LOGERROR)
            for list_id, prop, _counter in _ROW_COUNTERS:
                self.setProperty(prop, '')
                self.getControl(list_id).reset()
            _number_rows(self)
            _focus_first(self)

    def _build_rows(self, place=None):
        from lib.ui.compat import setting_bool
        from lib.ui.newlook import fanart as addon_fanart

        store = get_store()
        auth = store.get_auth()
        self._hero_painted = None
        if place is None:
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
        if place is None:
            _focus_first(self)
        else:
            _restore_place(self, place)
        paint_hero(self)
        try:
            self._signature = _home_signature(store)
        except Exception:
            self._signature = None
        # The refresh generation these rows were built under.
        _drop_memory_if_refreshed(self)

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

        # The library fetch finished on a worker and woke a noop. The
        # poster properties have to be current before the hero paints.
        _apply_library_meta(self)
        _apply_shelf_extends(self)
        action_id = action.getId()
        if action_id in BACK_ACTIONS:
            self.close()
            return
        if action_id == 117:
            focus = self.getFocusId()
            if focus in _CLICKABLE and focus != BROWSE_LIST:
                _offer_library(self, self.getControl(focus).getSelectedItem(), focus)
            return
        # The header is one row (#23): the pills on the left, the tools on
        # the right, and a row's Up lands on the pills. With no types
        # installed the pills are hidden, so that Up has nowhere to go.
        # Kodi has already moved (or not) by the time this runs: an Up
        # that left the remote on the shelf it started on was that dead
        # end, and goes to the tools instead.
        focus = self.getFocusId()
        if action_id == 3 and focus == getattr(self, '_last_focus', None) and focus in _SHELF_IDS:
            if not self.getControl(BROWSE_LIST).size():
                self.setFocusId(TOOLS_LIST)
        # Right is what walks a shelf. Load the next posters before the
        # hero is painted, so the cell the remote just reached already
        # has a title.
        if action_id == 2:
            _maybe_extend_focused_shelf(self)
        paint_hero(self)
        _note_focus(self)

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
        _activate(self, focused, control_id)


def _open_signin(window):
    """Settings, where Account > Login signs in, then a refresh of this
    window.

    The login writes auth.json in this addon's profile. The new auth key
    changes Home's signature, so `_after_child` rebuilds the rows for it
    and keeps the remote where it was. Not `views.login()` itself: that
    ends a plugin handle, and Home has none to end.
    """
    _open_settings(window)


def _continue_card(entry):
    """``(wide picture, "S:1 E:2")`` for a Continue card (#9).

    The card is 16:9; the poster scaled into it was a slice through the
    middle of the poster. An episode with a Cinemeta id uses that
    episode's still (the picture the New Episodes cards use), anything
    else its backdrop. ``""`` when there is neither: the skin then shows
    the poster whole on the plate.
    """
    from lib.newepisodes import episode_still_url
    from lib.ui.urlutil import sized_image

    land = ''
    code = ''
    video_id = entry.get('video_id')
    if isinstance(video_id, str) and video_id:
        show, season, episode = (video_id.rsplit(':', 2) + ['', ''])[:3]
        if show and season.isdigit() and episode.isdigit():
            code = 'S:%d E:%d' % (int(season), int(episode))
            land = episode_still_url(show, int(season), int(episode))
    if not land:
        background = entry.get('background') or ''
        land = sized_image(background, 'backdrop') if isinstance(background, str) else ''
    return land, code


def _continue_item(entry):
    """A Continue poster. Carries the resume fields the dialog reads.

    Catalog and Library posters stay on `_poster_item` alone: those
    clicks still open the page, and the skin ignores unknown properties.
    The card itself is wide art with the show and the episode written
    bottom-left, the way the New Episodes cards read (#9).
    """
    from lib.ui.uicommon import escape_label

    item = _poster_item(entry)
    land, code = _continue_card(entry)
    props = {
        'land': land,
        'card_show': escape_label(entry.get('name') or ''),
        'card_code': code,
    }
    # Progress records carry a name and a poster, not a description:
    # fetch the meta on focus, the way Library does, so the hero reads
    # the same on every row. An episode always asks: its hero is the
    # show's (backdrop, logo) with the episode line on top.
    episode = bool(code)
    if (episode or not entry.get('description')) and entry.get('id') and entry.get('type'):
        props['needs_meta'] = '1'
    if episode and not entry.get('background'):
        # Until the show's meta lands, no picture beats the record's
        # poster blown up to the hero: that can be the episode still.
        props['fanart'] = ''
        props['hero_fill'] = ''
    band = entry.get('band')
    if band:
        props['band'] = str(band)
    video_id = entry.get('video_id')
    if video_id:
        props['video_id'] = str(video_id)
    for key in ('position_ms', 'duration_ms'):
        value = entry.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            props[key] = str(int(value))
    item.setProperties(props)
    return item


def _property_int(item, key):
    raw = item.getProperty(key) or ''
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _continue_offset_ms(item):
    """Milliseconds to offer Resume for, or 0 when this poster is not one.

    Next-up and recently finished share the Continue row and have no
    mid-title position. A duration-0 account pointer (timeOffset 1) is
    how Stremio marks "play the next episode", not a place to seek.
    The band check uses the same window the row was built with.
    """
    from lib.ui.mystuff import BAND_RESUME, RESUME_MAX_PERCENT, RESUME_MIN_PERCENT

    if item.getProperty('band') != BAND_RESUME:
        return 0
    position = _property_int(item, 'position_ms')
    duration = _property_int(item, 'duration_ms')
    if position <= 0 or duration <= 0:
        return 0
    percent = (float(position) / float(duration)) * 100.0
    if percent < RESUME_MIN_PERCENT or percent >= RESUME_MAX_PERCENT:
        return 0
    return position


def _continue_art(item):
    art = {}
    poster = item.getProperty('thumbnail') or ''
    fanart = item.getProperty('fanart') or ''
    if poster:
        art['poster'] = poster
    if fanart:
        art['fanart'] = fanart
    return art or None


def _continue_item_meta(item, show_id):
    """OSD / now-playing context for a Continue resume.

    `meta['id']` is the show (or movie) id. The play call's own sid is
    the episode id when there is one, which is what the picker passes,
    so subtitles and the progress key stay on the episode while sync
    stays on the show.
    """
    label = item.getProperty('hero_title') or item.getLabel() or ''
    item_meta = {}
    if label:
        item_meta['label'] = label
    art = _continue_art(item)
    if art:
        item_meta['art'] = art
    meta = {'id': show_id, 'type': item.getProperty('stype') or ''}
    if label:
        meta['name'] = label
    poster = item.getProperty('thumbnail') or ''
    if poster:
        meta['poster'] = poster
    item_meta['meta'] = meta
    return item_meta


def _continue_choice(item, offset_ms):
    """0 resume, 1 the existing page, -1 Back. Back closes the dialog."""
    from lib.ui.compat import L
    from lib.ui.dialogs import choose
    from lib.ui.playbackmeta import episode_label_from_id, format_resume_clock

    clock = format_resume_clock(offset_ms / 1000.0)
    code = episode_label_from_id(item.getProperty('video_id'))
    if code:
        resume = L(30438) % (code, clock)
    else:
        resume = L(30439) % (clock,)
    second = L(30440) if item.getProperty('stype') == 'series' else L(30441)
    heading = item.getProperty('hero_title') or item.getLabel() or ''
    return choose(heading, [resume, second])


def _meta_for_resume(stype, show_id, item_meta):
    """Fill `videos` before play, or report that the user cancelled.

    Continue's poster does not carry the episode list. The stop push
    still records a position without it. A finish does not: with no
    list, `finish_playback` leaves the watched bits alone and, with no
    next episode id, zeroes the offset instead of pointing Continue at
    the next episode. This is the same meta fetch the episode list
    already ran. Back on the spinner cancels the resume. A miss plays
    anyway, because the position sync does not need the list.
    """
    import xbmc

    from lib.ui.compat import L, log
    from lib.ui.uicommon import CANCELLED, run_cancellable
    from lib.ui.views import _fetch_meta

    fetched = run_cancellable(lambda: _fetch_meta(stype, show_id), L(30033))
    if fetched is CANCELLED:
        log('home: resume cancelled while loading the title', xbmc.LOGINFO)
        return item_meta, True
    if isinstance(fetched, dict) and (fetched.get('id') or fetched.get('videos')):
        meta = dict(fetched)
        meta['id'] = fetched.get('id') or show_id
        item_meta = dict(item_meta)
        item_meta['meta'] = meta
        if not item_meta.get('label') and meta.get('name'):
            item_meta['label'] = meta.get('name')
    return item_meta, False


def _resume_continue(item, offset_ms):
    """The stream picker for the episode (or movie) the card is on.

    Picking a stream plays it the stock way: the player finds the same
    saved position in the local progress cache and offers to resume
    there (`player._maybe_resume_offset_ms`). `offset_ms` is what the
    card offered; the player re-reads it, so it is not passed on.
    """
    from lib.ui.streamswindow import open_streams

    stype = item.getProperty('stype')
    show_id = item.getProperty('sid')
    video_id = item.getProperty('video_id') or None
    play_id = video_id or show_id
    item_meta, cancelled = _meta_for_resume(stype, show_id, _continue_item_meta(item, show_id))
    if cancelled:
        return False
    return open_streams(
        stype, play_id,
        poster=item.getProperty('thumbnail') or None,
        heading=item.getProperty('hero_title') or item.getLabel() or '',
        art=_continue_art(item),
        meta=item_meta.get('meta'),
        video_id=video_id,
    )


def _handle_continue(window, item):
    """True when this click was a resumable Continue poster.

    Back does nothing else. The second row is the page this click used
    to open (episode list, or details for a movie).
    """
    offset_ms = _continue_offset_ms(item)
    if not offset_ms:
        return False
    choice = _continue_choice(item, offset_ms)
    if choice < 0:
        return True
    if choice == 0:
        _open_child(window, lambda: _resume_continue(item, offset_ms))
        return True
    land_on = item.getProperty('video_id') or None
    _open_child(window, lambda: _open_detail_for(item, land_on=land_on))
    return True


def _activate(window, item, control_id=None):
    """A shelf poster with an id opens its page. Anything else is a
    menu action (including More, which carries the row's action and
    no id).

    Continue is the exception, and only for a poster that is actually
    part-way through: that click asks first. Next-up, recently finished,
    Library and the catalog rows still open the page directly.
    """
    if item is None:
        return
    action = item.getProperty('action')
    sid = item.getProperty('sid')
    if sid and not action:
        if control_id == CONTINUE_SHELF and _handle_continue(window, item):
            return
        land_on = None
        if control_id == CONTINUE_SHELF:
            # Next up and recently finished carry the episode too. The
            # page should open there, not on season 1.
            land_on = item.getProperty('video_id') or None
        _open_child(window, lambda: _open_detail_for(item, land_on=land_on))
        return
    handler = _ACTIONS.get(action)
    if handler:
        handler(window)


def _open_detail_for(item, land_on=None):
    """`open_detail` for a poster: the stock title page. `land_on` is the
    episode a Continue card is on; the stock page does not take one yet,
    so it opens where it always does."""
    from lib.ui.detailwindow import open_detail

    return open_detail(item.getProperty('stype'), item.getProperty('sid'))


def _open_type_row(window, action):
    """That type's catalog picker, over Home: the screen the stock Home's
    row opens. Back returns here. Playback closes both."""
    from lib.ui.catalogpicker import open_catalog_picker
    from lib.ui.compat import L

    types = TYPE_ROW_TYPES[action]
    if types is None:
        types = _remainder_types(_available_types(get_store().get_enabled_addons()))
    _open_child(window, lambda: open_catalog_picker(types=types, heading=L(L_FOR_ACTION[action])))


def _open_search(window):
    from lib.ui.searchwindow import open_search
    _open_child(window, open_search)


def _open_addons(window):
    """Add-ons never closes Home. A newly installed catalog shows up on
    the way back (`_after_child` sees the addon list change)."""
    from lib.ui.addonswindow import open_addons

    def _run():
        open_addons()
        return False

    _open_child(window, _run)


def _open_settings(window):
    from lib.ui.compat import ADDON

    ADDON.openSettings()
    # Account > Login returns here without re-running onInit. A sign-in,
    # a row switched on or off, or a new exclusion changes the signature
    # and rebuilds the rows; a look at Settings that changed nothing
    # leaves them, and the remote's place, alone.
    try:
        _after_child(window)
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
