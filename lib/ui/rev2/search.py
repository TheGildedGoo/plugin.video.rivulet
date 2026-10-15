# SPDX-FileCopyrightText: 2026 M0RF30
# SPDX-License-Identifier: MIT
"""Search sheet with an on-screen keyboard.

The query runs through ``searchwindow.run_query`` and the results open
the existing coverflow. A letter does not start a catalog fan-out: the
Search key does. Firing eight addons on every keypress is the thing the
spec's 400ms debounce was trying to avoid, and on a low-power box an
explicit key is the safer version of that.
"""
import xbmcgui

from lib.ui.rev2.keyboard import (
    CLEAR_BUTTON,
    DELETE,
    HISTORY_LIST,
    KEY_STRINGS,
    QUERY_LABEL,
    SEARCH,
    SPACE,
    button_map,
)
from lib.ui.uicommon import BaseWindow, gated_input, open_window


class SearchSheet(BaseWindow):
    """Keyboard, the query, and recent searches."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query = ''
        self.should_close_caller = False
        self._buttons = button_map()

    def start(self):
        self.doModal()
        return self.should_close_caller

    def onInit(self):
        from lib.ui.compat import L
        from lib.ui.dependencies import get_store

        for control_id, key in self._buttons.items():
            caption = L(KEY_STRINGS[key]) if key in KEY_STRINGS else key
            self.getControl(control_id).setLabel(caption)
        history = self.getControl(HISTORY_LIST)
        history.reset()
        history.addItems([
            xbmcgui.ListItem(label=query)
            for query in get_store().get_search_history()
            if query
        ])
        self._paint()
        self.setFocusId(min(self._buttons))

    def _paint(self):
        self.getControl(QUERY_LABEL).setLabel(self.query)

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

        if action.getId() in BACK_ACTIONS:
            self.close()

    @gated_input
    def onClick(self, control_id):
        if control_id == CLEAR_BUTTON:
            self._clear_history()
            return
        if control_id == HISTORY_LIST:
            item = self.getControl(HISTORY_LIST).getSelectedItem()
            if item is not None and item.getLabel():
                self.query = item.getLabel()
                self._paint()
                self._run()
            return
        key = self._buttons.get(control_id)
        if key is None:
            return
        if key == DELETE:
            self.query = self.query[:-1]
        elif key == SPACE:
            self.query += ' '
        elif key == SEARCH:
            self._run()
            return
        else:
            if len(self.query) < 80:
                self.query += key
        self._paint()

    def _clear_history(self):
        import xbmc

        from lib.ui import dialogs
        from lib.ui.compat import L
        from lib.ui.dependencies import get_store

        if not dialogs.confirm(
            L(30044), L(30046), xbmc.getLocalizedString(107), xbmc.getLocalizedString(106),
        ):
            return
        get_store().clear_search_history()
        self.onInit()

    def _run(self):
        from lib.ui.compat import L, log, notify
        from lib.ui.dependencies import get_client, get_store
        from lib.ui.searchwindow import SearchReport, _search_notice, run_query

        query = self.query.strip()
        if not query:
            return
        store = get_store()
        store.add_search_query(query)
        report = SearchReport()
        metas = run_query(store, get_client(), query, report=report)
        notice = _search_notice(report)
        if not metas:
            if not report.canceled:
                notify(notice or L(30380))
            return
        if notice:
            notify(notice)
        try:
            from lib.ui.infowindow import open_showcase
            selected = open_showcase(metas, catalog_title='%s \u00b7 %s' % (L(30001), query))
        except Exception as exc:  # a skin failure must surface, not vanish
            import xbmc
            log('rev2 search: coverflow failed: %r' % (exc,), xbmc.LOGERROR)
            notify(L(30032))
            return
        if not selected:
            return
        from lib.ui.detailwindow import open_detail
        if open_detail(selected.get('type') or 'movie', selected.get('id')):
            self.should_close_caller = True
            self.close()


def open_search():
    """Open the sheet. True when playback started and the caller should close."""
    from lib.ui.compat import L, log, notify

    log('rev2 search: opening search sheet')
    window = None
    try:
        window = open_window(SearchSheet, 'Rev2SearchSheet.xml')
        return window.start()
    except Exception as exc:
        import xbmc
        log('rev2 search: window failed: %r' % (exc,), xbmc.LOGERROR)
        notify(L(30032))
        return False
    finally:
        if window is not None:
            try:
                window.close()
            except Exception:
                pass
