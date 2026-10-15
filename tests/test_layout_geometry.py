# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""1920x1080 geometry for every window, not just the ones a unit test names.

Kodi places a control where the XML says and never reports an overlap.
A title that meets a poster, or a focus ring that is a different box
from the card under it, ships looking wrong and the suite stays green.
This walks every skin file, turns nested groups into absolute pixels,
and checks three things:

- A label, text box, or button that is not inside a scrolling row does
  not intersect that row. Full-screen fanart is behind both on purpose
  and is not part of this check.
- A focus ring (`focus_stroke.png`) is the same rectangle as the poster
  (200x300) or landscape card (392x220) it sits on. The Library accent
  plate is the other mark: 8px past the poster, with an underline that
  shares the poster's left edge and width.
- Every static texture and diffuse mask names a file in media/, and the
  poster and landscape masks are the aspect the cards use. A square
  mask is what cut posters into ovals.
"""
import glob
import os
import struct
import xml.etree.ElementTree as ET

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIN = os.path.join(_ROOT, 'resources', 'skins', 'Default', '1080i')
_MEDIA = os.path.join(_ROOT, 'resources', 'skins', 'Default', 'media')
_SCREEN_W = 1920
_SCREEN_H = 1080
_POSTER = (200, 300)
_LAND = (392, 220)
_ROW_TYPES = frozenset({'list', 'fixedlist', 'panel', 'grouplist'})
_TEXT_TYPES = frozenset({'label', 'textbox', 'button'})


def _files():
    return sorted(glob.glob(os.path.join(_SKIN, '*.xml')))


def _px(el, tag, default=0):
    text = (el.findtext(tag) or '').strip()
    if not text:
        return default
    if text[0] == '-' and text[1:].isdigit():
        return int(text)
    if not text.isdigit():
        return default
    return int(text)


def _texture(el):
    node = el.find('texture')
    if node is None or not (node.text or '').strip():
        return ''
    return node.text.strip()


def _box(el, ox, oy):
    return (
        ox + _px(el, 'left'),
        oy + _px(el, 'top'),
        _px(el, 'width'),
        _px(el, 'height'),
    )


def _intersects(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _inside(box):
    x, y, w, h = box
    return x >= 0 and y >= 0 and x + w <= _SCREEN_W and y + h <= _SCREEN_H


def _walk(el, ox, oy, in_row, path, rows, heroes):
    if el.tag in ('itemlayout', 'focusedlayout'):
        return
    if el.tag != 'control':
        for child in list(el):
            _walk(child, ox, oy, in_row, path, rows, heroes)
        return
    left, top, width, height = _box(el, ox, oy)
    kind = el.get('type') or ''
    child_in_row = in_row
    if kind in _ROW_TYPES and width >= 400 and height >= 200:
        rows.append((path, el.get('id') or kind, (left, top, width, height)))
        child_in_row = True
    if (
        not child_in_row
        and kind in _TEXT_TYPES
        and width > 0
        and height > 0
    ):
        heroes.append((path, el.get('id') or kind, (left, top, width, height)))
    for child in list(el):
        if child.tag == 'control':
            _walk(child, left, top, child_in_row, path, rows, heroes)


def _layouts(path):
    root = ET.parse(path).getroot()
    found = []
    for el in root.iter():
        if el.tag in ('itemlayout', 'focusedlayout'):
            found.append(el)
    return found


def _images(layout):
    """Images in a cell, including ones wrapped in a group. The group's
    own offset is added. Item layouts in this skin put that group at 0,0."""
    found = []

    def walk(el, ox, oy):
        if el.tag != 'control':
            for child in list(el):
                walk(child, ox, oy)
            return
        left, top, _width, _height = _box(el, ox, oy)
        if el.get('type') == 'image':
            found.append((el, (left, top, _width, _height)))
        if el.get('type') == 'group':
            for child in list(el):
                if child.tag == 'control':
                    walk(child, left, top)

    for child in list(layout):
        walk(child, 0, 0)
    return found


def png_size(path):
    with open(path, 'rb') as handle:
        sig = handle.read(8)
        assert sig == b'\x89PNG\r\n\x1a\n', path
        handle.read(4)
        kind = handle.read(4)
        assert kind == b'IHDR', path
        return struct.unpack('>II', handle.read(8))


def test_every_window_parses_and_hero_text_does_not_meet_the_rows():
    """The title stack and the scrolling rows are different rectangles.

    A control inside a row (a heading, a poster label) is allowed to
    sit in that row. Anything outside it — the hero title, the pills,
    a dialog heading — must not cross into it, and both must stay on
    the 1920x1080 frame.
    """
    rows = []
    heroes = []
    for path in _files():
        root = ET.parse(path).getroot()
        assert root.tag == 'window', path
        _walk(root, 0, 0, False, os.path.basename(path), rows, heroes)
    assert rows, 'no scrolling row found'
    assert heroes, 'no hero text found'
    overlaps = []
    offscreen = []
    for path, cid, box in heroes:
        if not _inside(box):
            offscreen.append('%s#%s %s' % (path, cid, box))
    for path, cid, box in rows:
        # A row is wider than the screen on purpose: it scrolls sideways.
        # Its vertical span still has to sit on the 1080 frame.
        x, y, _w, h = box
        if x < 0 or y < 0 or y + h > _SCREEN_H:
            offscreen.append('%s#%s %s' % (path, cid, box))
    for hpath, hid, hbox in heroes:
        for rpath, rid, rbox in rows:
            if hpath == rpath and _intersects(hbox, rbox):
                overlaps.append('%s hero %s %s meets row %s %s' % (hpath, hid, hbox, rid, rbox))
    assert not offscreen, 'off the 1920x1080 frame:\n  ' + '\n  '.join(offscreen)
    assert not overlaps, 'hero overlaps a row:\n  ' + '\n  '.join(overlaps)


def test_focus_stroke_matches_the_poster_or_landscape_card():
    """The ring is the card. A different box reads as a frame floating
    beside the artwork, which is how an earlier ring shipped."""
    strokes = 0
    mismatches = []
    for path in _files():
        name = os.path.basename(path)
        for layout in _layouts(path):
            images = _images(layout)
            cards = []
            for image, box in images:
                tex = _texture(image)
                if tex == 'focus_stroke.png':
                    continue
                if box[2] > 0 and box[3] > 0:
                    cards.append(box)
            for image, box in images:
                if _texture(image) != 'focus_stroke.png':
                    continue
                strokes += 1
                if box not in cards:
                    mismatches.append('%s %s stroke %s has no card' % (name, layout.tag, box))
                if (box[2], box[3]) not in (_POSTER, _LAND):
                    mismatches.append('%s stroke %s is not poster or landscape' % (name, box))
    assert strokes >= 12, 'expected the hub rings plus the home cards, found %d' % strokes
    assert not mismatches, '\n'.join(mismatches)


def test_library_accent_frame_and_underline_follow_the_poster():
    """Library marks focus with a plate 8px past the poster and an
    underline as wide as the artwork. The ring on Home is a separate
    control; this one has to stay lined up with the 200px poster."""
    plates = 0
    underlines = 0
    for name in ('GridWindow.xml', 'Rev2GridWindow.xml'):
        for layout in _layouts(os.path.join(_SKIN, name)):
            if layout.tag != 'focusedlayout':
                continue
            poster = None
            for image, box in _images(layout):
                tex = image.find('texture')
                text = (tex.text or '') if tex is not None else ''
                if 'thumbnail' in text and box[2:] == _POSTER:
                    poster = box
            assert poster is not None, name
            left, top, width, height = poster
            for image, box in _images(layout):
                tex = image.find('texture')
                diffuse = (tex.get('colordiffuse') if tex is not None else '') or ''
                if _texture(image) in ('round_frame.png', 'rv_focus_frame.png'):
                    plates += 1
                    assert box == (left - 8, top, width + 16, height + 8), (name, box, poster)
                    continue
                if diffuse != 'FF38BDF8':
                    continue
                if box[3] == 4:
                    underlines += 1
                    assert box[0] == left and box[2] == width, (name, box, poster)
    assert plates == 8, plates
    assert underlines == 8, underlines


def test_decade_plates_match_the_poster_slots():
    """A decade tile uses the poster box, grey plate and centred label
    together. A label in a different box sits off the tile."""
    for name, plate in (
        ('HubWindow.xml', 'mask_poster.png'),
        ('Rev2HubWindow.xml', 'rv_mask_200x300.png'),
    ):
        seen = 0
        for layout in _layouts(os.path.join(_SKIN, name)):
            images = {
                box: _texture(image)
                for image, box in _images(layout)
                if _texture(image) == plate
            }
            for label in list(layout):
                if label.tag != 'control' or label.get('type') != 'label':
                    continue
                text = label.findtext('label') or ''
                if 'Property(n' not in text:
                    continue
                box = _box(label, 0, 0)
                assert images.get(box) == plate, (name, box)
                assert (box[2], box[3]) == _POSTER, (name, box)
                assert (label.findtext('align') or '').strip() == 'center', name
                assert (label.findtext('aligny') or '').strip() == 'center', name
                seen += 1
        assert seen == 16, (name, seen)


def test_masks_and_every_referenced_image_exist():
    """A missing mask draws the poster square. The poster mask is 2:3
    and the landscape mask matches the 392x220 card."""
    media = {}
    for path in glob.glob(os.path.join(_MEDIA, '*')):
        if os.path.isfile(path):
            media[os.path.basename(path)] = path
    missing = []
    for path in _files():
        for el in ET.parse(path).iter():
            if 'texture' not in el.tag.lower():
                continue
            names = []
            value = (el.text or '').strip()
            if value and not value.startswith('$'):
                names.append(value)
            diffuse = (el.get('diffuse') or '').strip()
            if diffuse and not diffuse.startswith('$'):
                names.append(diffuse)
            for name in names:
                if name not in media:
                    missing.append('%s -> %s' % (os.path.basename(path), name))
    assert not missing, '\n'.join(missing)
    poster_w, poster_h = png_size(media['mask_poster.png'])
    land_w, land_h = png_size(media['mask_land.png'])
    assert poster_w * 3 == poster_h * 2, (poster_w, poster_h)
    assert abs((land_w / float(land_h)) - (_LAND[0] / float(_LAND[1]))) < 0.02
    assert png_size(media['focus_stroke.png'])[0] > 0
    assert os.path.getsize(media['fade_v.png']) > 0
    assert os.path.getsize(media['fade_h.png']) > 0
