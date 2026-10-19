# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The "New look" (Settings > Home screen), off by default.

The new look draws a title the way a full-screen media skin does: the
backdrop fills the screen and fades to black toward the left and the
bottom, the clearlogo is the title, one line of facts sits under it,
three lines of plot, then the scores and when the title would end.
There is no bar behind the text.

Each screen it covers keeps its stock window untouched and adds a second
window that is only opened while the setting is on, so with it off
nothing runs differently. Home is the first (`lib.ui.newhome`,
NewHomeWindow.xml); the hubs, search and the episode page follow the
same way. The setting is read when a window opens, so Home reopens
itself when it changes (`newhome._restyle_if_changed`,
`homewindow._open_settings`).

The textures are drawn by `tools/make_new_look_textures.py`, and the
text uses whatever fonts the active Kodi skin defines for the standard
names (Estuary: Noto Sans).
"""

import time

#: The settings.xml id.
SETTING_ID = 'ui_new_look'

#: The backdrop behind a screen with no title focused: the addon's
#: artwork in greyscale, so the new look's black and white is not broken
#: by the blue of the stock fanart. In resources/, beside fanart.jpg.
FANART = 'fanart_grey.jpg'

#: Hero controls only the new-look files have.
HERO_FACTS = 30024   # label: year • runtime • genres
HERO_SCORES = 30025  # label: IMDb 7.4   RT 88%   Ends at 22:28
HERO_STARS = 30027   # image: newlook_stars_00..10.png

#: The hero stack, bottom-up from the row band (y=630, 40px above it).
#: Pixels at 1080p. The
#: plot is font13: 30px a line in Kodi's measure (heroscrim), three
#: lines at most, plus the inset a textbox keeps so a line is not clipped.
_STACK = {
    'left': 80,
    'bottom': 590,
    'title_h': 120,
    'text_title_h': 80,
    'facts_h': 40,
    'scores_h': 40,
    'plot_font': 30,
    'plot_line': 30,
    'plot_lines': 3,
    'plot_w': 920,
    'plot_inset': 20,
    'gap_title': 16,
    'gap': 10,
    'stars_w': 150,
    'stars_gap': 16,
}


def enabled():
    """True when Settings asks for the new look. Any failure reading it
    means the stock look."""
    from lib.ui.compat import setting_bool

    try:
        return setting_bool(SETTING_ID, False)
    except Exception:
        return False


def fanart():
    """Filesystem path of `FANART` in this addon."""
    import xbmcvfs

    from lib.ui.compat import ADDON_ID

    return xbmcvfs.translatePath('special://home/addons/%s/resources/%s' % (ADDON_ID, FANART))


def _clock_format():
    """Kodi's time format without seconds (``%H:%M`` or ``%I:%M %p``)."""
    fmt = ''
    try:
        import xbmc

        fmt = xbmc.getRegion('time') or ''
    except Exception:
        fmt = ''
    if not fmt:
        return '%H:%M'
    return fmt.replace(':%S', '').replace('.%S', '')


def ends_at(runtime_minutes, now=None):
    """The clock time a title started now would end, or ``''``."""
    try:
        minutes = int(runtime_minutes)
    except (TypeError, ValueError):
        return ''
    if minutes <= 0:
        return ''
    stamp = (time.time() if now is None else now) + minutes * 60
    fmt = _clock_format()
    try:
        text = time.strftime(fmt, time.localtime(stamp))
    except Exception:
        return ''
    # A 12-hour clock reads "9:05 PM", not "09:05 PM".
    return text[1:] if '%I' in fmt and text.startswith('0') else text


def hero_lines(panel_text, runtime_minutes=None, now=None):
    """``(stars, facts_line, scores_line)`` for the new-look hero.

    `stars` is a texture name or ``''``. The facts are joined with a
    bullet; the scores carry their short names dimmed, then "Ends at"
    when the runtime is known.
    """
    from lib.ui.compat import L
    from lib.ui.playbackmeta import new_look_hero_parts

    stars, facts, scores = new_look_hero_parts(panel_text)
    texture = 'newlook_stars_%02d.png' % stars if stars is not None else ''
    facts_line = '  •  '.join(facts)
    parts = ['[COLOR B3EDEDED]%s[/COLOR] %s' % (name, value) for name, value in scores]
    end = ends_at(runtime_minutes, now)
    if end:
        parts.append(L(30494) % end)
    return texture, facts_line, '      '.join(parts)


def _plot_height(plot, s=None):
    from lib.ui.heroscrim import block_size

    s = s or _STACK
    if not (plot or '').strip():
        return 0
    _width, height = block_size(
        plot, s['plot_font'], s['plot_line'], s['plot_w'], s['plot_lines'],
    )
    return height + s['plot_inset'] if height else 0


def _move(window, control_id, x, y, height=None):
    try:
        control = window.getControl(control_id)
        control.setPosition(int(x), int(y))
        if height is not None:
            control.setHeight(int(max(height, 1)))
    except Exception:
        pass


def place_hero(window, plot, has_facts, has_scores, has_stars, stack=None):
    """Stack the title, facts, plot and scores up from the row.

    A short plot moves everything above it down, so the scores always
    end the same distance above the row and nothing floats in a gap.
    """
    from lib.ui.newhome import HERO_LOGO, HERO_PLOT, HERO_TITLE

    s = dict(_STACK, **(stack or {}))
    plot_h = _plot_height(plot, s)
    y = s['bottom']
    if has_scores:
        y -= s['scores_h']
        _move(window, HERO_SCORES, s['left'], y, s['scores_h'])
        y -= s['gap']
    if plot_h:
        y -= plot_h
        _move(window, HERO_PLOT, s['left'], y, plot_h)
        y -= s['gap']
    if has_facts or has_stars:
        y -= s['facts_h']
        _move(window, HERO_STARS, s['left'], y + 6)
        facts_x = s['left'] + (s['stars_w'] + s['stars_gap'] if has_stars else 0)
        _move(window, HERO_FACTS, facts_x, y, s['facts_h'])
        y -= s['gap_title']
    y -= s['title_h']
    _move(window, HERO_LOGO, s['left'], y, s['title_h'])
    text_h = s['text_title_h']
    _move(window, HERO_TITLE, s['left'], y + s['title_h'] - text_h, text_h)


def paint_hero(window, plot, panel_text, runtime_minutes, stack=None):
    """Write the new-look hero controls and place the stack."""
    stars, facts_line, scores_line = hero_lines(panel_text, runtime_minutes)
    try:
        window.getControl(HERO_STARS).setImage(stars)
        window.getControl(HERO_FACTS).setLabel(('•  ' + facts_line) if (stars and facts_line) else facts_line)
        window.getControl(HERO_SCORES).setLabel(scores_line)
    except Exception:
        return
    place_hero(window, plot, bool(facts_line), bool(scores_line), bool(stars), stack)


def runtime_minutes(text):
    """Whole minutes out of a runtime string (``"112 min"``), or ``''``."""
    from lib.ui.playbackmeta import parse_duration_seconds

    seconds = parse_duration_seconds(text)
    return str(int(seconds // 60)) if seconds else ''
