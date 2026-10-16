# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Size the two hero scrims from the label text.

The dark rectangles behind the title and the ratings were the full-width
fade and the right-quarter fade. Those stay, but only as a light vignette
and a ramp into the poster row. The contrast is a scrim image
(``scrim_feather.png``, 9-slice border 40) behind each text block.

Kodi 19 cannot point that texture at the text. A textbox's auto height is
measured on the next frame and the control draws no background, so reading
``getHeight()`` in the same call as ``setText()`` returns the previous
title. A button snugs its width to one line and keeps the height it was
given. A grouplist reports a smaller size than it clips to, so an image
child still paints the max rectangle. The scrim is therefore sized here,
from the same string the label is about to show.

Advances are a little wider than Noto Sans (the Estuary face these fonts
map to) so the scrim covers the glyphs. A wrapped paragraph fills the
column, because that is the width Kodi wraps to. A ratings line does not:
those are already one fact per line, and the scrim hugs the longest one.
"""
import re

#: Must match ``border="40"`` on the scrim texture. The image is this
#: much larger than the text on every side, and that rim fades to clear.
FEATHER = 40
LEFT_SCRIM = 30026
RIGHT_SCRIM = 30027

_MARKUP = re.compile(r'\[/?(?:B|I|COLOR[^\]]*)\]', re.IGNORECASE)

# Fractions of the font size. Tuned above Noto Sans Regular so a bold
# title and a wide capital still land inside the scrim. A short label
# stays well under the column; see tests/test_heroscrim.py.
_NARROW = frozenset("ijlI.,:;'`|!")
_WIDE = frozenset('mwMW@%&')
_UPPER = frozenset('ABCDEFGHKNOPQRSTUVXYZ')


def _advance(ch):
    if ch == ' ':
        return 0.34
    if ch in _NARROW:
        return 0.36
    if ch in _WIDE:
        return 0.96
    if ch in _UPPER:
        return 0.78
    if 'a' <= ch <= 'z':
        return 0.62
    if ch.isdigit():
        return 0.66
    if ord(ch) < 128:
        return 0.52
    if ord(ch) < 0x300:
        return 0.72
    return 1.08


def _plain(text):
    """Drop Kodi's ``[B]`` / ``[COLOR]`` markup. ``[CR]`` is a newline."""
    raw = text or ''
    raw = raw.replace('[CR]', '\n').replace('[cr]', '\n')
    return _MARKUP.sub('', raw)


def text_width(text, font_px, bold=False):
    """Pixel width of one line. Empty text is 0.

    Kodi markup is not drawn, so it does not add width. A newline is
    not a line here; ``block_size`` splits those first.
    """
    text = _plain(text).replace('\n', '')
    if not text or font_px <= 0:
        return 0
    units = 0.0
    for ch in text:
        units += _advance(ch)
    scale = 1.12 if bold else 1.0
    return int(units * font_px * scale) + 2


def _wrap(text, font_px, max_width, bold=False):
    """Split into lines. The second value is true when a line wrapped."""
    lines = []
    wrapped = False
    for para in text.split('\n'):
        words = para.split()
        if not words:
            continue
        current = ''
        for word in words:
            if not current:
                current = word
                if text_width(word, font_px, bold) > max_width:
                    wrapped = True
                continue
            trial = current + ' ' + word
            if text_width(trial, font_px, bold) <= max_width:
                current = trial
                continue
            lines.append(current)
            wrapped = True
            current = word
            if text_width(word, font_px, bold) > max_width:
                wrapped = True
        if current:
            lines.append(current)
    return lines, wrapped


def block_size(text, font_px, line_px, max_width, max_lines, bold=False):
    """``(width, height)`` of the text, or ``(0, 0)`` when there is none.

    A line that had to wrap uses the whole column: that is the width
    Kodi wraps to, and a shorter scrim would leave the last word bare.
    A line that fits stays as wide as its own text, so a short rating
    does not stretch across the quarter.
    """
    plain = _plain(text).strip()
    if not plain or font_px <= 0 or line_px <= 0 or max_width <= 0 or max_lines <= 0:
        return 0, 0
    lines, wrapped = _wrap(plain, font_px, max_width, bold)
    if not lines:
        return 0, 0
    shown = lines[:max_lines]
    if wrapped:
        width = max_width
    else:
        width = 0
        for line in shown:
            measured = text_width(line, font_px, bold)
            if measured > width:
                width = measured
        if width > max_width:
            width = max_width
    return width, len(shown) * line_px


# Geometry of the text controls, not the scrim. The scrim grows by FEATHER.
# title_h / plot_line are the line boxes the skin already uses.
_SHARED_META = {
    'meta_right': 1860,
    'meta_w': 380,
    'meta_font': 25,
    'meta_line': 32,
    'meta_lines': 8,
}
ANCHORS = {
    'home': {
        'left': 64, 'title_top': 420, 'title_h': 64, 'title_font': 37,
        'title_bold': False, 'gap': 8, 'plot_top': 492, 'plot_font': 30,
        'plot_line': 30, 'plot_lines': 6, 'text_w': 1056, 'meta_top': 420,
    },
    'hub': {
        'left': 64, 'title_top': 468, 'title_h': 64, 'title_font': 37,
        'title_bold': False, 'gap': 8, 'plot_top': 540, 'plot_font': 30,
        'plot_line': 30, 'plot_lines': 6, 'text_w': 1056, 'meta_top': 468,
    },
    'grid': {
        'left': 96, 'title_top': 372, 'title_h': 64, 'title_font': 37,
        'title_bold': False, 'gap': 8, 'plot_top': 444, 'plot_font': 30,
        'plot_line': 30, 'plot_lines': 6, 'text_w': 1056, 'meta_top': 372,
    },
    'showcase': {
        'left': 96, 'title_top': 460, 'title_h': 92, 'title_font': 60,
        'title_bold': True, 'gap': 8, 'plot_top': 560, 'plot_font': 27,
        'plot_line': 30, 'plot_lines': 6, 'text_w': 1056, 'meta_top': 460,
    },
}
for _spec in ANCHORS.values():
    _spec.update(_SHARED_META)


def _left_box(spec, title, plot, logo):
    title_w = 0
    title_h = 0
    if logo:
        title_w = spec['text_w']
        title_h = spec['title_h']
    else:
        title_w, title_lines = block_size(
            title, spec['title_font'], spec['title_h'], spec['text_w'], 1,
            bold=spec['title_bold'],
        )
        if title_lines:
            title_h = spec['title_h']
            title_w = title_w or spec['text_w']
    plot_w, plot_h = block_size(
        plot, spec['plot_font'], spec['plot_line'], spec['text_w'],
        spec['plot_lines'],
    )
    if title_h and plot_h:
        return spec['left'], spec['title_top'], max(title_w, plot_w), (
            title_h + spec['gap'] + plot_h
        )
    if title_h:
        return spec['left'], spec['title_top'], title_w, title_h
    if plot_h:
        return spec['left'], spec['plot_top'], plot_w, plot_h
    return None


def _right_box(spec, meta):
    width, height = block_size(
        meta, spec['meta_font'], spec['meta_line'], spec['meta_w'],
        spec['meta_lines'],
    )
    if not height:
        return None
    return spec['meta_right'], spec['meta_top'], width, height


def _move(control, x, y, width, height):
    if width <= 0 or height <= 0:
        control.setVisible(False)
        return
    if x < 0:
        x = 0
    if y < 0:
        y = 0
    control.setPosition(int(x), int(y))
    control.setWidth(int(width))
    control.setHeight(int(height))
    control.setVisible(True)


def place_hero_scrims(window, kind, title, plot, meta, logo=False):
    """Move the two scrim images so they hug this title's text.

    ``kind`` is ``home``, ``hub``, ``grid``, or ``showcase``. ``logo``
    keeps the title band at the full column: a clearlogo's pixels are
    not known here, and a white one needs the backing.
    """
    spec = ANCHORS[kind]
    left = _left_box(spec, title, plot, logo)
    right = _right_box(spec, meta)
    left_control = window.getControl(LEFT_SCRIM)
    right_control = window.getControl(RIGHT_SCRIM)
    if left is None:
        left_control.setVisible(False)
    else:
        x, y, width, height = left
        _move(
            left_control,
            x - FEATHER, y - FEATHER,
            width + 2 * FEATHER, height + 2 * FEATHER,
        )
    if right is None:
        right_control.setVisible(False)
    else:
        edge, y, width, height = right
        _move(
            right_control,
            edge - width - FEATHER, y - FEATHER,
            width + 2 * FEATHER, height + 2 * FEATHER,
        )
