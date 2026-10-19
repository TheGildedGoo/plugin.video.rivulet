# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""How tall a block of hero text will be, measured in Python.

The new-look hero (`lib.ui.newlook`) stacks the title, facts, plot and
scores up from the poster row, so a short plot moves everything above it
down. That needs the plot's height in the same call that sets it.

Kodi 19 cannot give it: a textbox's auto height is measured on the next
frame, and reading ``getHeight()`` in the same call as ``setText()``
returns the previous title. The height is therefore computed here, from
the same string the label shows.

Advances are a little wider than Noto Sans (the Estuary face these
fonts map to). A wrapped paragraph fills the column, because that is
the width Kodi wraps to.
"""
import re

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
