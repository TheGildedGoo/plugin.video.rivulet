# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""The Settings checklist for countries and original languages.

Two remote lists, no keyboard. The first picks Countries or Original
languages. The second is Kodi's multi-select: OK toggles a row, and
confirming writes the setting. Back on either list leaves the setting
alone. The names in the list are the English names catalogs send
("India", "Hindi"), which is what the match is made against.
"""
import xbmcgui

from lib.stremio.regionfilter import (
    COUNTRIES,
    LANGUAGES,
    names_for,
    parse_exclude,
    replace_group,
)


def excluded_tokens():
    """The tokens the setting currently hides. Empty hides nothing.

    Kodi returns settings.xml's default until the user saves this key.
    The test double returns '' for a key nobody set, which is the same
    as a user who cleared the list.
    """
    from lib.ui.compat import ADDON

    try:
        raw = ADDON.getSetting('content_exclude')
    except Exception:  # noqa: BLE001 - a broken setting read must not hide the row
        raw = ''
    return parse_exclude(raw)


def apply_region_filter(metas):
    """Drop titles the setting hides. Unknown country and language stay."""
    from lib.stremio.regionfilter import filter_metas

    excluded = excluded_tokens()
    if not excluded or not metas:
        return metas
    return filter_metas(metas, excluded)


def exclusion_summary():
    """The short line next to the setting on the remote pane."""
    from lib.ui.compat import L

    names = names_for(excluded_tokens())
    if not names:
        return L(30473)
    if len(names) <= 2:
        return ', '.join(names)
    return '%s, %s +%d' % (names[0], names[1], len(names) - 2)


def edit_exclusions():
    """Open the two lists and save when the user confirms the second.

    Cancelling either list does not write. Confirming writes this
    group's ticks and leaves the other group as it was.
    """
    from lib.ui.compat import ADDON, L
    from lib.ui.dialogs import choose

    which = choose(L(30470), (L(30471), L(30472)))
    if which not in (0, 1):
        return
    choices = COUNTRIES if which == 0 else LANGUAGES
    heading = L(30471) if which == 0 else L(30472)
    current = excluded_tokens()
    preselect = [index for index, (token, _name) in enumerate(choices) if token in current]
    picked = xbmcgui.Dialog().multiselect(
        heading, [name for _token, name in choices], preselect=preselect,
    )
    if picked is None:
        return
    ADDON.setSetting('content_exclude', replace_group(current, choices, picked))
