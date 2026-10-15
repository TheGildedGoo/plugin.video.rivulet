# SPDX-FileCopyrightText: 2026 M0RF30
# SPDX-License-Identifier: MIT
"""Two-pane settings for the options a remote actually changes.

The rest (server URL, torrent limits, account) stay in Kodi's addon
settings dialog, opened from the last button. That dialog's first
control in the server category is still the enable toggle: an edit
field focused on open traps the arrows, which is why the URL is not a
row here.
"""
import xbmcgui

from lib.ui.uicommon import BaseWindow, gated_input, open_window

CATEGORIES = 32010
OPTIONS = 32011
ALL_SETTINGS = 32012

#: (category string id, ((setting id, label string id, settings.xml default), ...))
#: Boolean settings only. About fifteen, which is the spec's pane;
#: everything else is behind All settings. The default matches
#: settings.xml so a key the user has never touched reads the same here
#: as in Kodi's dialog.
PANES = (
    (30219, (
        ('home_show_mystuff', 30244, True),
        ('home_show_new_episodes', 30314, True),
        ('home_show_movies', 30220, True),
        ('home_show_series', 30221, True),
        ('home_show_anime', 30222, True),
        ('home_show_other', 30229, True),
        ('home_hide_adult', 30280, True),
        ('startup_autoload', 30230, False),
    )),
    (30070, (
        ('buffer_enable', 30071, True),
        ('sync_progress', 30170, True),
        ('resume_ask', 30171, True),
        ('binge_enable', 30180, True),
        ('playback_exclude_cam', 30260, False),
        ('playback_cached_only', 30261, False),
    )),
    (30050, (
        ('subs_enable', 30051, True),
    )),
    (30101, (
        ('server_enable', 30103, True),
        ('server_force_library', 30362, False),
    )),
)


def _state_label(enabled):
    from lib.ui.compat import L
    return L(30436) if enabled else L(30437)


class SettingsWindow(BaseWindow):
    """Category list on the left, toggles on the right."""

    def onInit(self):
        from lib.ui.compat import L

        categories = self.getControl(CATEGORIES)
        categories.reset()
        categories.addItems([
            xbmcgui.ListItem(label=L(label_id)) for label_id, _rows in PANES
        ])
        self._fill_options()
        self.setFocusId(CATEGORIES)

    def _selected_pane(self):
        control = self.getControl(CATEGORIES)
        index = control.getSelectedPosition()
        if index is None or index < 0 or index >= len(PANES):
            index = 0
        return PANES[index][1]

    def _fill_options(self):
        from lib.ui.compat import L, setting_bool

        options = self.getControl(OPTIONS)
        options.reset()
        items = []
        for key, label_id, default in self._selected_pane():
            item = xbmcgui.ListItem(
                label=L(label_id), label2=_state_label(setting_bool(key, default)),
            )
            item.setProperty('setting', key)
            items.append(item)
        options.addItems(items)

    @gated_input
    def onAction(self, action):
        from lib.ui.uicommon import BACK_ACTIONS

        if action.getId() in BACK_ACTIONS:
            self.close()
            return
        if self.getFocusId() == CATEGORIES:
            self._fill_options()

    @gated_input
    def onClick(self, control_id):
        if control_id == ALL_SETTINGS:
            from lib.ui.compat import ADDON
            ADDON.openSettings()
            self._fill_options()
            return
        if control_id != OPTIONS:
            return
        item = self.getControl(OPTIONS).getSelectedItem()
        if item is None:
            return
        key = item.getProperty('setting')
        if not key:
            return
        from lib.ui.compat import ADDON, setting_bool
        default = True
        for candidate, _label_id, candidate_default in self._selected_pane():
            if candidate == key:
                default = candidate_default
                break
        ADDON.setSetting(key, 'false' if setting_bool(key, default) else 'true')
        self._fill_options()


def open_settings():
    """Block on the two-pane window. All settings opens Kodi's dialog on top."""
    window = open_window(SettingsWindow, 'Rev2SettingsWindow.xml')
    window.doModal()
    window.close()
