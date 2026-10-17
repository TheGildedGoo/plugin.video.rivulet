# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""#11: text is read from across a room.

Secondary lines were font10 (23px) at 30-42% white, about 3.3-3.8:1 on
the near-black plates, under the 4.5:1 floor for body text. The rules
pinned here are the ones the RevRivulet skins now follow:

- no font10 anywhere; font12 (25px) is the smallest face;
- grey text (the EEF3F6 family) is at least 60% opaque (0x99, ~6.6:1),
  which the skins keep for counters and the wordmark crumb; read lines
  use 0xB3 (~8.8:1) or brighter;
- inline [COLOR] greys in the skin at least 50% (decorative separators).

The Rev2 test skins are not published and keep what they were built with.
"""
import glob
import os
import re

_SKIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'resources', 'skins', 'Default', '1080i',
)


def _read(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read()


def _revrivulet_skins():
    paths = sorted(glob.glob(os.path.join(_SKIN, '*.xml')))
    return [p for p in paths if not os.path.basename(p).startswith('Rev2')]


def test_no_revrivulet_skin_uses_font10():
    offenders = [os.path.basename(p) for p in _revrivulet_skins() if '<font>font10</font>' in _read(p)]
    assert not offenders, offenders


def test_grey_text_is_at_least_sixty_percent_white():
    offenders = []
    for path in _revrivulet_skins():
        text = _read(path)
        for alpha in re.findall(r'<textcolor>([0-9A-Fa-f]{2})EEF3F6</textcolor>', text):
            if int(alpha, 16) < 0x99:
                offenders.append('%s: %sEEF3F6' % (os.path.basename(path), alpha))
        for alpha in re.findall(r'\[COLOR ([0-9A-Fa-f]{2})EEF3F6\]', text):
            if int(alpha, 16) < 0x80:
                offenders.append('%s: [COLOR %sEEF3F6]' % (os.path.basename(path), alpha))
    assert not offenders, offenders
