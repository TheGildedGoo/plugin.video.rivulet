# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Search in the Fuse look: a search bar, letters, and a row of results.

The classic search is a list (New search, phone, history) that opens the
keyboard and then a coverflow. This screen is one page, after the
reference the user sent: a white search bar, the alphabet under it, the
focused title's hero, and one row of posters. With nothing typed the row
is Discover (the first page of the first plain movie catalog); as
letters are picked it becomes the results.

The Search pill searches what is in the bar at once and moves to the
results. The letters also search on their own once the remote has rested
on them for `SETTLE_SECONDS`. Either way the search runs on a worker with
no spinner (`searchwindow.run_query(quiet=True)`), a line under the pills
says "Searching for ..." until it answers (or "No results for ..."), and
a newer letter cancels the search it replaced. The answer is applied on
the UI thread, on the `Action(noop)` the worker posts. The phone pill
fills the bar from a phone instead (nothing is typed on the TV either
way). OK on a poster opens the title the way the coverflow does; the
query then goes into the search history.
"""

import threading

import xbmcgui

from lib.ui.uicommon import BaseWindow, escape_label, gated_input, open_window

QUERY = 30201
LETTERS = 30202
PHONE = 30203
#: The Search pill: runs what is in the bar now.
GO = 30204
#: One line under the pills: "Searching for ...", "No results for ...".
STATUS = 30205
ROW = 30215
ROW_HEADING = 30140
BACKGROUND = 30000
#: Letters, then space and delete. The skin draws " " as "_" and "<" as "<".
KEYS = tuple('ABCDEFGHIJKLMN') + tuple('OPQRSTUVWXYZ') + (' ', '<')
#: Seconds the remote rests on the letters before the search runs on
#: its own. Moving across the letters with a remote takes about a
#: second per letter, so a shorter wait started a search per letter.
SETTLE_SECONDS = 1.6
#: Fewer letters than this do not search on their own (the row shows
#: Discover). The Search pill searches any query.
MIN_QUERY = 2
MAX_QUERY = 60
#: The hero here sits between the letters and the row: a shorter logo,
#: two lines of plot.
_STACK = {'title_h': 100, 'plot_lines': 2}
_BACK_ACTIONS = frozenset((9, 10, 92))


class FuseSearchWindow(BaseWindow):
    """See module docstring. Built/run via `open_search()`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query = ''
        self.should_close_caller = False
        self._metas = []
        self._discover = []
        self._lock = threading.Lock()
        self._ready = []
        self._timer = None
        self._cancel = None
        self._painted_key = None
        #: Focus the results when they land: the Search pill was pressed.
        self._focus_results = False

    def start(self):
        self.should_close_caller = False
        self.doModal()
        return self.should_close_caller

    # --- screen ------------------------------------------------------------

    def onInit(self):
        letters = self.getControl(LETTERS)
        letters.reset()
        items = []
        for key in KEYS:
            item = xbmcgui.ListItem('_' if key == ' ' else key)
            item.setProperty('key', key)
            items.append(item)
        letters.addItems(items)
        self._paint_query()
        if self._metas:
            self._show(self._metas, results=True)
        elif self._discover:
            self._show(self._discover, results=False)
        else:
            self._welcome()
            self._load_discover()
        self.setFocusId(LETTERS)

    def _paint_query(self):
        text = escape_label(self.query)
        self.getControl(QUERY).setLabel('%s[COLOR 8007090B]|[/COLOR]' % text)

    def _welcome(self):
        from lib.ui.compat import L
        from lib.ui.homewindow import HERO_PLOT, HERO_TITLE

        self.setProperty('HeroLogo', '')
        self.getControl(HERO_TITLE).setLabel('[B]%s[/B]' % L(30508))
        self.getControl(HERO_PLOT).setText(L(30509))
        from lib.ui import fuse

        fuse.paint_hero(self, L(30509), '', '', _STACK)
        self._painted_key = None

    def _show(self, metas, results):
        from lib.ui.compat import L
        from lib.ui.infowindow import _item_properties

        row = self.getControl(ROW)
        row.reset()
        items = []
        for index, meta in enumerate(metas):
            item = xbmcgui.ListItem(escape_label(meta.get('name') or meta.get('id') or ''))
            props = _item_properties(meta)
            props['position'] = str(index)
            item.setProperties(props)
            items.append(item)
        row.addItems(items)
        self.getControl(ROW_HEADING).setLabel('[B]%s[/B]' % L(30507 if results else 30506))
        self.setProperty('SearchHasRow', '1' if items else '')
        if items:
            self._paint_hero(items[0])

    def _paint_hero(self, item):
        """The focused poster's hero: its backdrop, title, plot, logo,
        facts and scores (lib/ui/fuse.py)."""
        if item is None:
            return
        key = item.getProperty('position') + '|' + item.getLabel()
        if key == self._painted_key:
            return
        self._painted_key = key
        from lib.ui import fuse
        from lib.ui.compat import addon_fanart
        from lib.ui.homewindow import HERO_PLOT, HERO_TITLE

        try:
            self.getControl(BACKGROUND).setImage(item.getProperty('fanart') or addon_fanart())
            self.getControl(HERO_TITLE).setLabel('[B]%s[/B]' % item.getLabel())
            self.getControl(HERO_PLOT).setText(item.getProperty('plot') or '')
        except Exception:
            return
        fuse.paint_showcase(self, item, _STACK)

    # --- input ---------------------------------------------------------------

    @gated_input
    def onAction(self, action):
        action_id = action.getId()
        if action_id in _BACK_ACTIONS:
            self._stop_pending()
            self.close()
            return
        self._apply_ready()
        if self.getFocusId() == ROW:
            self._paint_hero(self.getControl(ROW).getSelectedItem())

    @gated_input
    def onClick(self, control_id):
        if control_id == LETTERS:
            item = self.getControl(LETTERS).getSelectedItem()
            if item is not None:
                self._key(item.getProperty('key'))
            return
        if control_id == PHONE:
            self._phone()
            return
        if control_id == GO:
            self._go()
            return
        if control_id == ROW:
            self._open_focused()

    def _key(self, key):
        if key == '<':
            self.query = self.query[:-1]
        elif key == ' ':
            if self.query and not self.query.endswith(' '):
                self.query += ' '
        elif key and len(self.query) < MAX_QUERY:
            self.query += key.lower() if self.query and not self.query.endswith(' ') else key
        self._paint_query()
        self._schedule()

    def _go(self):
        """The Search pill: search what is in the bar now, then move to
        the results."""
        if not self.query.strip():
            return
        self._focus_results = True
        self._schedule(delay=0, explicit=True)

    def _status(self, text):
        try:
            self.getControl(STATUS).setLabel(text)
        except Exception:
            pass

    def _phone(self):
        from lib.ui.pairwindow import phone_search

        query = (phone_search() or '').strip()
        if not query:
            return
        self.query = query[:MAX_QUERY]
        self._paint_query()
        self._focus_results = True
        self._schedule(delay=0, explicit=True)

    # --- searching -----------------------------------------------------------

    def _stop_pending(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._cancel is not None:
            self._cancel.set()
            self._cancel = None

    def _schedule(self, delay=None, explicit=False):
        """Search once the remote has rested; a newer letter replaces it."""
        from lib.ui.compat import L

        self._stop_pending()
        query = self.query.strip()
        if not explicit:
            self._focus_results = False
        if not query or (len(query) < MIN_QUERY and not explicit):
            self._metas = []
            self._status('')
            if self._discover:
                self._show(self._discover, results=False)
            return
        # Said at once, so a search that takes a few seconds is visibly
        # under way (rev18 showed nothing until the answer).
        self._status(_with_query(L(30512), query))
        cancel = threading.Event()
        self._cancel = cancel
        timer = threading.Timer(SETTLE_SECONDS if delay is None else delay, self._search, (query, cancel))
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _search(self, query, cancel):
        from lib.ui.dependencies import get_client, get_store
        from lib.ui.searchwindow import SearchReport, run_query

        if cancel.is_set():
            return
        try:
            metas = run_query(get_store(), get_client(), query, report=SearchReport(), quiet=True, cancel=cancel)
        except Exception as exc:  # the line under the pills says "No results"
            import xbmc

            from lib.ui.compat import log

            log('fusesearch: search for %r failed: %r' % (query, exc), xbmc.LOGWARNING)
            metas = []
        if cancel.is_set():
            return
        self._post(('results', query, metas))

    def _load_discover(self):
        def _work():
            metas = discover_metas()
            self._post(('discover', '', metas))

        threading.Thread(target=_work, name='rivulet-search-discover', daemon=True).start()

    def _post(self, answer):
        with self._lock:
            self._ready.append(answer)
        try:
            import xbmc

            xbmc.executebuiltin('Action(noop)')
        except Exception:
            pass

    def _apply_ready(self):
        """Answers from the workers, on the UI thread. A result for a
        query that is no longer in the bar is dropped."""
        with self._lock:
            ready, self._ready = self._ready, []
        for kind, query, metas in ready:
            if kind == 'discover':
                self._discover = list(metas or [])
                if len(self.query.strip()) < MIN_QUERY and self._discover:
                    self._show(self._discover, results=False)
            elif query == self.query.strip():
                from lib.ui.compat import L

                self._metas = list(metas or [])
                if self._metas:
                    self._status('')
                    self._show(self._metas, results=True)
                    if self._focus_results:
                        self.setFocusId(ROW)
                else:
                    self._status(_with_query(L(30513), query))
                self._focus_results = False

    def _open_focused(self):
        item = self.getControl(ROW).getSelectedItem()
        if item is None:
            return
        try:
            index = int(item.getProperty('position'))
        except ValueError:
            return
        metas = self._metas if self._metas else self._discover
        if index < 0 or index >= len(metas):
            return
        meta = metas[index]
        if self._metas and self.query.strip():
            from lib.ui.dependencies import get_store

            try:
                get_store().add_search_query(self.query.strip())
            except Exception:
                pass
        from lib.ui.detailwindow import open_detail

        if open_detail(meta.get('type') or 'movie', meta.get('id')):
            self.should_close_caller = True
            self.close()


def _with_query(text, query):
    """`text` (a string with one ``%s``) around the query."""
    query = escape_label(query)
    return text % query if text.count('%s') == 1 else '%s %s' % (text, query)


def discover_metas():
    """The first page of the first plain movie catalog (else series)."""
    from lib.stremio.addons import _base_type, iter_catalogs
    from lib.ui.catalogpicker import _classify_catalog, _reachable_catalogs
    from lib.ui.dependencies import get_store
    from lib.ui.homewindow import CatalogUnavailable, _one_catalog_page

    try:
        addons = get_store().get_enabled_addons() or []
        catalogs = _reachable_catalogs(list(iter_catalogs(addons)))
    except Exception:
        return []
    for wanted in ('movie', 'series'):
        for transport, manifest, catalog in catalogs:
            if _base_type(catalog.get('type')) != wanted or _classify_catalog(catalog) != 'open':
                continue
            try:
                metas = _one_catalog_page(transport, manifest, catalog)
            except CatalogUnavailable:
                continue
            except Exception:
                continue
            metas = [meta for meta in (metas or []) if isinstance(meta, dict)]
            if metas:
                return metas[:40]
    return []


def open_search():
    """Open the Fuse search. True when playback started (close the caller)."""
    import xbmc

    from lib.ui.compat import L, log, notify

    log('fusesearch: opening', xbmc.LOGINFO)
    window = None
    try:
        window = open_window(FuseSearchWindow, 'FuseSearchWindow.xml')
        return window.start()
    except Exception as exc:  # a skin failure must surface, not vanish
        log('fusesearch: window failed: %r' % (exc,), xbmc.LOGERROR)
        notify(L(30032))
        return False
    finally:
        if window is not None:
            try:
                window._stop_pending()
                window.close()
            except Exception:
                pass
