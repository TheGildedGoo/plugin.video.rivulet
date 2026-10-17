# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The Fuse look: a second skin set, chosen in Settings.

Fuse is RevRivulet drawn the way a full-screen media skin draws a
title: the backdrop fills the screen and fades to black toward the left
and the bottom, the clearlogo is the title, one line of facts sits under
it, three lines of plot, then the scores and when the title would end.
There is no bar behind the text.

The files are ``Fuse`` plus the classic name (``FuseHomeWindow.xml``).
They declare every control id the classic file does, so the window
classes are the same; `tests/test_fuse.py` holds that. A screen without
a Fuse file keeps its classic file, which is how the look ships one
screen at a time. The setting is read when a window opens, so Home
re-opens itself when it changes (`homewindow._after_child`).

Nothing here is copied from another skin. The textures are drawn by
`tools/make_textures.py`, and the text uses whatever fonts the active
Kodi skin defines for the standard names (Estuary: Noto Sans).
"""

import time

#: Screens that have a Fuse file. Grow this as each screen is drawn.
FUSE_SKINS = frozenset(('HomeWindow.xml', 'HubWindow.xml', 'ShowcaseWindow.xml', 'DetailWindow.xml'))

#: Controls only the Fuse files have.
HERO_FACTS = 30024   # label: year • runtime • genres
HERO_SCORES = 30025  # label: IMDb 7.4   RT 88%   Ends at 22:28
HERO_STARS = 30027   # image: fuse_stars_00..10.png

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
    """True when Settings asks for the Fuse look."""
    from lib.ui.compat import setting_bool

    try:
        return setting_bool('ui_fuse', False)
    except Exception:
        return False


def skin_for(xml_name, use_fuse=None):
    """``FuseHomeWindow.xml`` for ``HomeWindow.xml`` when Fuse is on.

    A screen that has no Fuse file yet keeps its classic file.
    """
    if not xml_name or xml_name.startswith('Fuse') or xml_name not in FUSE_SKINS:
        return xml_name
    if use_fuse is None:
        use_fuse = enabled()
    return 'Fuse' + xml_name if use_fuse else xml_name


def is_fuse_window(window):
    """True for a window built from a Fuse file."""
    return str(getattr(window, '_skin_xml', '') or '').startswith('Fuse')


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
    """``(stars, facts_line, scores_line)`` for the Fuse hero.

    `stars` is a texture name or ``''``. The facts are joined with a
    bullet; the scores carry their short names dimmed, then "Ends at"
    when the runtime is known.
    """
    from lib.ui.compat import L
    from lib.ui.playbackmeta import fuse_hero_parts

    stars, facts, scores = fuse_hero_parts(panel_text)
    texture = 'fuse_stars_%02d.png' % stars if stars is not None else ''
    facts_line = '  •  '.join(facts)
    parts = ['[COLOR B3EDEDED]%s[/COLOR] %s' % (name, value) for name, value in scores]
    end = ends_at(runtime_minutes, now)
    if end:
        parts.append(L(30494) % end)
    return texture, facts_line, '      '.join(parts)


def _plot_height(plot):
    from lib.ui.heroscrim import block_size

    if not (plot or '').strip():
        return 0
    _width, height = block_size(
        plot, _STACK['plot_font'], _STACK['plot_line'], _STACK['plot_w'],
        _STACK['plot_lines'],
    )
    return height + _STACK['plot_inset'] if height else 0


def _move(window, control_id, x, y, height=None):
    try:
        control = window.getControl(control_id)
        control.setPosition(int(x), int(y))
        if height is not None:
            control.setHeight(int(max(height, 1)))
    except Exception:
        pass


def place_hero(window, plot, has_facts, has_scores, has_stars):
    """Stack the title, facts, plot and scores up from the row.

    A short plot moves everything above it down, so the scores always
    end the same distance above the row and nothing floats in a gap.
    """
    from lib.ui.homewindow import HERO_LOGO, HERO_PLOT, HERO_TITLE

    s = _STACK
    plot_h = _plot_height(plot)
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


def paint_hero(window, plot, panel_text, runtime_minutes):
    """Write the Fuse-only hero controls and place the stack."""
    stars, facts_line, scores_line = hero_lines(panel_text, runtime_minutes)
    try:
        window.getControl(HERO_STARS).setImage(stars)
        window.getControl(HERO_FACTS).setLabel(('•  ' + facts_line) if (stars and facts_line) else facts_line)
        window.getControl(HERO_SCORES).setLabel(scores_line)
    except Exception:
        return
    place_hero(window, plot, bool(facts_line), bool(scores_line), bool(stars))


def runtime_minutes(text):
    """Whole minutes out of a runtime string (``"112 min"``), or ``''``."""
    from lib.ui.playbackmeta import parse_duration_seconds

    seconds = parse_duration_seconds(text)
    return str(int(seconds // 60)) if seconds else ''


def paint_showcase(window, focused):
    """The coverflow's hero for `focused`: its labels are bound in the
    skin, so this sets the logo, the facts and scores, and the stack."""
    if focused is None:
        return
    from lib.ui.homewindow import HERO_LOGO, _logo_known_good, _warm_logos

    wanted = focused.getProperty('logo') or ''
    logo = wanted if _logo_known_good(wanted) else ''
    try:
        if wanted and not logo:
            _warm_logos(window, [wanted])
        window.setProperty('HeroLogo', logo)
        window.getControl(HERO_LOGO).setImage(logo)
    except Exception:
        pass
    paint_hero(
        window, focused.getProperty('plot') or '', focused.getProperty('meta_line') or '',
        runtime_minutes(focused.getProperty('runtime')),
    )


def short_date(iso_date):
    """``2024-02-27`` in Kodi's short date format (``27/02/2024``), or
    the input when it cannot be read."""
    text = str(iso_date or '').strip()
    if not text:
        return ''
    try:
        stamp = time.strptime(text[:10], '%Y-%m-%d')
    except ValueError:
        return text
    fmt = ''
    try:
        import xbmc

        fmt = xbmc.getRegion('dateshort') or ''
    except Exception:
        fmt = ''
    try:
        return time.strftime(fmt or '%d/%m/%Y', stamp)
    except Exception:
        return text


def show_logo(window, logo_url):
    """The episode page's logo once Kodi has it, else its name (#10)."""
    from lib.ui.homewindow import HERO_LOGO, _logo_known_good, _warm_logos

    wanted = logo_url or ''
    logo = wanted if _logo_known_good(wanted) else ''
    try:
        if wanted and not logo:
            _warm_logos(window, [wanted])
        window.setProperty('HeroLogo', logo)
        window.getControl(HERO_LOGO).setImage(logo)
    except Exception:
        pass
