# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Size the one hero bar from the label text.

The title, the description, and the ratings sit on a single black bar
across the bottom of the hero, just above the poster row. The bar's
texture (``hero_bar.png``) fades over its top 64 pixels and is solid
below that, so the top edge does not cut the picture. Python shortens
the bar when the text is short and keeps its bottom on the row.

Kodi 19 cannot size that texture from the textbox. A textbox's auto
height is measured on the next frame, and reading ``getHeight()`` in
the same call as ``setText()`` returns the previous title. The height
is therefore computed here, from the same string the label shows.

Advances are a little wider than Noto Sans (the Estuary face these
fonts map to). A wrapped paragraph fills the column, because that is
the width Kodi wraps to.
"""
import re

#: Must match ``border="0,64,0,8"`` on the bar. Those top 64 pixels are
#: the unscaled fade; the rest of the control stretches as solid black.
FADE = 64
BAR = 30026

_MARKUP = re.compile(r'\[/?(?:B|I|COLOR[^\]]*)\]', re.IGNORECASE)

# Fractions of the font size. Tuned above Noto Sans Regular so a bold
# title and a wide capital still land inside the column. A short label
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


# title_top is the highest the text sits (a full plot). A shorter plot
# moves down so the stack still ends on `band` minus `row_gap`. Home and
# the hubs leave 40px under the description: the row title (MOVIES, NEW
# EPISODES) was sitting on the last line. The skin draws a hairline on
# the row's top edge in that gap. Grid and a catalog list have no
# row_gap; their stack still ends on the row.
# plot_max is the skin's textbox. plot_inset is the slack that box keeps
# so Kodi's textbox padding does not clip a line. Six lines of font13
# are 180, and the box is 200, so the inset is 20.
_SHARED = {
    'meta_left': 1480,
    'meta_w': 380,
    'meta_font': 25,
    'meta_line': 32,
    'meta_lines': 8,
    'gap': 8,
    'text_w': 1056,
    'plot_inset': 20,
    'caption_h': 32,
    'caption_gap': 8,
}
ANCHORS = {
    'home': {
        'left': 64, 'title_top': 380, 'band': 692, 'row_gap': 40, 'title_h': 64,
        'title_id': 30020, 'logo_id': 30023, 'plot_id': 30022,
        'plot_font': 30, 'plot_line': 30, 'plot_lines': 6, 'plot_max': 200,
        'meta_id': 30021, 'meta_max': 272, 'caption_id': None,
    },
    'hub': {
        'left': 64, 'title_top': 428, 'band': 740, 'row_gap': 40, 'title_h': 64,
        'title_id': 30020, 'logo_id': 30023, 'plot_id': 30022,
        'plot_font': 30, 'plot_line': 30, 'plot_lines': 6, 'plot_max': 200,
        'meta_id': 30021, 'meta_max': 272, 'caption_id': None,
    },
    'grid': {
        'left': 96, 'title_top': 372, 'band': 684, 'title_h': 64,
        'title_id': 30020, 'logo_id': None, 'plot_id': 30024,
        'plot_font': 30, 'plot_line': 30, 'plot_lines': 6, 'plot_max': 200,
        'meta_id': 30021, 'meta_max': 312, 'caption_id': 30025,
    },
    'showcase': {
        'left': 96, 'title_top': 460, 'band': 740, 'title_h': 92,
        'title_id': 30020, 'logo_id': None, 'plot_id': 30022,
        'plot_font': 27, 'plot_line': 30, 'plot_lines': 6, 'plot_max': 180,
        'meta_id': 30021, 'meta_max': 280, 'caption_id': None,
    },
}
for _spec in ANCHORS.values():
    _spec.update(_SHARED)


def _stack(spec, title, plot, meta, logo, caption):
    """``(title_h, plot_h, caption_h, left_h, meta_h)`` for this text.

    A clearlogo keeps the title band: its pixels are not known here.
    An empty block is 0, so the bar does not reserve a blank row.
    """
    title_h = spec['title_h'] if (logo or _plain(title).strip()) else 0
    _plot_w, plot_lines = block_size(
        plot, spec['plot_font'], spec['plot_line'], spec['text_w'],
        spec['plot_lines'],
    )
    plot_h = 0
    if plot_lines:
        plot_h = min(spec['plot_max'], plot_lines + spec['plot_inset'])
    caption_h = spec['caption_h'] if _plain(caption).strip() else 0
    left = 0
    if title_h:
        left += title_h
    if plot_h:
        if left:
            left += spec['gap']
        left += plot_h
    if caption_h:
        if left:
            left += spec['caption_gap']
        left += caption_h
    _meta_w, meta_h = block_size(
        meta, spec['meta_font'], spec['meta_line'], spec['meta_w'],
        spec['meta_lines'],
    )
    if meta_h > spec['meta_max']:
        meta_h = spec['meta_max']
    return title_h, plot_h, caption_h, left, meta_h


def _shift(control, x, y, height):
    """Move a text control. Width stays the skin's column."""
    if control is None or height <= 0:
        return
    control.setPosition(int(x), int(y))
    control.setHeight(int(height))


def place_hero_bar(window, kind, title, plot, meta, logo=False, caption=''):
    """Put the title, the plot, and the ratings on one bar.

    The bar's bottom is the poster row, minus ``row_gap`` where the row
    has a heading. A short plot moves the text down onto a shorter bar.
    The top 64 pixels are the fade, above the words. ``kind`` is
    ``home``, ``hub``, ``grid``, or ``showcase``.
    """
    spec = ANCHORS[kind]
    title_h, plot_h, caption_h, left_h, meta_h = _stack(
        spec, title, plot, meta, logo, caption,
    )
    content = left_h if left_h > meta_h else meta_h
    bar = window.getControl(BAR)
    if content <= 0:
        bar.setVisible(False)
        return
    end = spec['band'] - spec.get('row_gap', 0)
    text_top = spec['title_top']
    room = end - text_top
    if content < room:
        text_top += room - content
    bar_top = text_top - FADE
    if bar_top < 0:
        bar_top = 0
    bar.setPosition(0, int(bar_top))
    bar.setWidth(1920)
    bar.setHeight(int(end - bar_top))
    bar.setVisible(True)

    y = text_top
    if title_h:
        _shift(window.getControl(spec['title_id']), spec['left'], y, title_h)
        if spec['logo_id'] is not None:
            _shift(window.getControl(spec['logo_id']), spec['left'], y, title_h)
        y += title_h
    if plot_h:
        if title_h:
            y += spec['gap']
        _shift(window.getControl(spec['plot_id']), spec['left'], y, plot_h)
        y += plot_h
    if caption_h and spec['caption_id'] is not None:
        y += spec['caption_gap']
        _shift(window.getControl(spec['caption_id']), spec['left'], y, caption_h)
    if meta_h:
        _shift(window.getControl(spec['meta_id']), spec['meta_left'], text_top, meta_h)
