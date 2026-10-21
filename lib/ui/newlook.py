# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Hero layout for Rivulet's Home, drawn by NewHomeWindow.xml.

The backdrop fills the screen and fades to black toward the left and
bottom. The clearlogo, facts, plot, scores and end time share the pinned
RevRivulet layout. Textures are drawn by tools/make_new_look_textures.py;
text uses the active Kodi skin's standard font names.
"""

import math
import time

#: The backdrop behind a screen with no title focused: the addon's
#: artwork in greyscale, so the new look's black and white is not broken
#: by the blue of the stock fanart. In resources/, beside fanart.jpg.
FANART = 'fanart_grey.jpg'

#: Hero controls only the new-look files have.
HERO_FACTS = 30024   # label: year • runtime • genres
HERO_SCORES = 30025  # horizontal grouplist; moved as one row
HERO_STARS = 30027   # image: newlook_stars_00..10.png
HERO_IMDB = 30029
HERO_AUDIENCE_ICON, HERO_AUDIENCE = 30030, 30031
HERO_RT_ICON, HERO_RT = 30032, 30033
HERO_MC_ICON, HERO_MC = 30034, 30035
HERO_END = 30036

_SCORE_CONTROLS = (
    ('IMDb', None, HERO_IMDB),
    ('RT Audience', HERO_AUDIENCE_ICON, HERO_AUDIENCE),
    ('RT', HERO_RT_ICON, HERO_RT),
    ('MC', HERO_MC_ICON, HERO_MC),
    ('Ends at', None, HERO_END),
)

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
    """``(stars, facts_line, [(source, value), ...])`` for the hero.

    `stars` is a texture name or ``''``. The facts are joined with a
    bullet; scores stay structured so image controls can identify their
    source. "Ends at" is included only when the runtime is known.
    """
    from lib.ui.compat import L
    from lib.ui.playbackmeta import new_look_hero_parts

    stars, facts, scores = new_look_hero_parts(panel_text)
    texture = 'newlook_stars_%02d.png' % stars if stars is not None else ''
    facts_line = '  •  '.join(facts)
    parts = list(scores)
    end = ends_at(runtime_minutes, now)
    if end:
        parts.append(('Ends at', L(30494) % end))
    return texture, facts_line, parts


def _score_number(value):
    try:
        number = float(str(value).split('/')[0].strip().rstrip('%'))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 100 else None


def score_icon(kind, value):
    """Original source pictogram, selected by the published score bands."""
    number = _score_number(value)
    if number is None:
        return ''
    if kind == 'RT':
        return 'rating_rt_fresh.png' if number >= 60 else 'rating_rt_rotten.png'
    if kind == 'RT Audience':
        return 'rating_rt_audience_up.png' if number >= 60 else 'rating_rt_audience_spilled.png'
    if kind == 'MC':
        color = 'green' if number >= 61 else 'yellow' if number >= 40 else 'red'
        return 'rating_mc_%s.png' % color
    return ''


def _paint_score(window, kind, value, image_id, label_id):
    """Collapse absent pairs; an unparseable score keeps a text source."""
    texture, text = '', ''
    if value:
        if image_id is not None:
            texture = score_icon(kind, value)
            if texture:
                text = ' : %d%s' % (int(round(_score_number(value))), '%' if kind != 'MC' else '')
            else:
                text = '%s %s' % (kind, value)
        elif kind == 'IMDb':
            text = '[COLOR B3EDEDED]IMDb[/COLOR] %s' % value
        else:
            text = value
    label = window.getControl(label_id)
    label.setLabel(text)
    label.setVisible(bool(text))
    if image_id is not None:
        image = window.getControl(image_id)
        image.setImage(texture)
        image.setVisible(bool(texture))
    return bool(text)


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
    stars, facts_line, scores = hero_lines(panel_text, runtime_minutes)
    try:
        window.getControl(HERO_STARS).setImage(stars)
        window.getControl(HERO_FACTS).setLabel(('•  ' + facts_line) if (stars and facts_line) else facts_line)
        values = dict(scores)
        visible = [_paint_score(window, kind, values.get(kind), image_id, label_id)
                   for kind, image_id, label_id in _SCORE_CONTROLS]
        has_scores = any(visible)
        window.getControl(HERO_SCORES).setVisible(has_scores)
    except Exception:
        return
    place_hero(window, plot, bool(facts_line), has_scores, bool(stars), stack)


def runtime_minutes(text):
    """Whole minutes out of a runtime string (``"112 min"``), or ``''``."""
    from lib.ui.playbackmeta import parse_duration_seconds

    seconds = parse_duration_seconds(text)
    return str(int(seconds // 60)) if seconds else ''
