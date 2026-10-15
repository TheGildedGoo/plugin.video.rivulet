# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Row planning for the Rev2 home and hub.

Pure: no xbmc import, so a catalog failure is a missing row rather than
a skin concern. The window turns the tuples into ListItems.
"""

ROW_CAP = 12
PEEK_CAP = 9


def visible_rows(bands):
    """Drop empty bands and keep at most ``ROW_CAP``.

    ``bands`` is ``(key, title, items)`` in display order. An empty
    band is hidden, not drawn as a blank header. Later bands stay in
    order, so a slow catalog cannot jump ahead of an earlier one.
    """
    rows = []
    for key, title, items in bands:
        if not items:
            continue
        rows.append((key, title, list(items)))
        if len(rows) >= ROW_CAP:
            break
    return rows


def keep_library(entries):
    """Library cells worth a row.

    ``entries`` are ``{sid, action}``. The empty-library notice has
    neither, so Home hides that band. A sign-in cell has an action and
    stays. Real titles have a sid.
    """
    return [entry for entry in entries if entry.get('sid') or entry.get('action')]


def peek_for(rows, index, enabled, limit=PEEK_CAP):
    """``(title, items)`` for the row under ``index``, or ``('', [])``.

    The peek is not focusable. Turning it off (or standing on the last
    row) clears it.
    """
    if not enabled or index is None or index < 0:
        return '', []
    nxt = index + 1
    if nxt >= len(rows):
        return '', []
    _key, title, items = rows[nxt]
    return title, list(items)[:limit]


def clamp_text(text, limit):
    """Clamp ``text`` on a word boundary and add an ellipsis.

    Kodi does not ellipsize a wrapping textbox, so the plot is shortened
    before it is handed to the control. The ellipsis is three ASCII dots:
    a single-character ellipsis is easy to lose in a font fallback.
    """
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0].rstrip(',.;:-')
    if not cut:
        cut = text[:limit].rstrip()
    return cut + '...'
