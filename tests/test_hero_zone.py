# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The hero is full-screen fanart, and the focused row is a fixed band.

Kodi scales 1920x1080 skin space onto whatever display the box is
plugged into, so these numbers are the layout. On Home, the hubs, and
Library the fanart fills the screen from the top. A vertical fade is
opaque by the row band, and a solid plate covers that band, so the art
never runs behind the rows. The title (or the clearlogo), the metadata
line, and the description sit in the upper left, in that order, and
end above the band.

The focused row is pinned inside the band (y=652, height 428, the
bottom 40% of the skin — about the bottom 35% once the heading above
the poster is counted; the poster art itself starts at y=684). Home
and Library pin it by making every row group exactly as tall as the
viewport: Kodi top-aligns on the way up and bottom-aligns on the way
down, and those are the same scroll when the heights match. A negative
itemgap pulls the next row into the bottom of that viewport, so at
most one partial row shows. The hubs are one fixedlist with
focusposition 0 and a height of one row plus a peek.

Showcase keeps the older top third. It is a single horizontal strip,
not this row band.
"""
import os
import xml.etree.ElementTree as ET

_SKIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'resources', 'skins', 'Default', '1080i',
)
# Poster art starts at band_top + the 32px heading. 1080 - 684 is 36.7%
# of the skin: the closest a 300px poster, its caption, and a peek of
# the next row can sit while staying on the 1080 frame.
_BAND_TOP = 652
_BAND_HEIGHT = 428
_SCREEN = 1080

# font13 is 30. Two lines fit in 64 and a third (90) does not.
# font27 is 27. Three lines fit in 96 and a fourth (108) does not.
_ROWS = {
    'HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist',
    },
    'Rev2HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist',
    },
    'HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'fixedlist',
    },
    'Rev2HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'fixedlist',
    },
    'GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024',
        'rows': '30001', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist',
    },
    'Rev2GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024',
        'rows': '30001', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist',
    },
}
_SHOWCASE = {
    'ShowcaseWindow.xml': {'rows': '30002', 'lines': 3, 'font': 27, 'title_h': 92},
    'Rev2ShowcaseWindow.xml': {'rows': '30002', 'lines': 3, 'font': 27, 'title_h': 92},
}
# The top third, which Showcase still uses.
_ZONE_BOTTOM = 360


def _root(name):
    return ET.parse(os.path.join(_SKIN, name)).getroot()


def _px(el, tag):
    text = (el.findtext(tag) or '').strip()
    assert text.isdigit(), '%s is %r, not a skin pixel' % (tag, text)
    return int(text)


def _by_id(root, control_id):
    found = root.find(".//control[@id='%s']" % control_id)
    assert found is not None, 'missing control %s' % control_id
    return found


def _showcase_title(root):
    for label in root.iter('control'):
        if label.get('type') == 'label' and (label.findtext('font') or '').strip() == 'font60':
            return label
    raise AssertionError('showcase has no font60 title')


def _showcase_meta(root):
    for label in root.iter('control'):
        text = label.findtext('label') or ''
        if 'meta_line' in text:
            return label
    raise AssertionError('showcase has no metadata line')


def _showcase_plot(root):
    box = root.find(".//control[@type='textbox']")
    assert box is not None
    return box


def _texture_name(control):
    node = control.find('texture')
    if node is None or node.text is None:
        return ''
    return node.text.strip()


def _assert_text_stack(name, title, meta, plot, spec):
    title_top, title_h = _px(title, 'top'), _px(title, 'height')
    meta_top, meta_h = _px(meta, 'top'), _px(meta, 'height')
    plot_top, plot_h = _px(plot, 'top'), _px(plot, 'height')
    assert title_h == spec['title_h'], name
    assert meta_top >= title_top + title_h, name
    assert plot_top >= meta_top + meta_h, name
    # Two (or three) lines of the face it uses. The next line does not fit.
    assert spec['font'] * spec['lines'] <= plot_h < spec['font'] * (spec['lines'] + 1), name
    scroll = plot.find('autoscroll')
    assert scroll is not None and (scroll.text or '').strip() == 'true', name
    assert (title.findtext('wrapmultiline') or '').strip() == 'false', name
    return plot_top + plot_h, title_top, title_h


def test_focused_row_is_pinned_in_the_lower_band_over_full_screen_fanart():
    """Fanart fills the screen. The focused row stays in the lower band,
    and at most one partial row shows under it."""
    for name, spec in _ROWS.items():
        root = _root(name)
        fanart = _by_id(root, '30000')
        assert _px(fanart, 'width') == 1920 and _px(fanart, 'height') == _SCREEN, name
        assert (fanart.findtext('left') or '0').strip() in ('', '0'), name
        assert (fanart.findtext('top') or '0').strip() in ('', '0'), name

        fades = [
            el for el in root.iter('control')
            if el.get('type') == 'image' and _texture_name(el) == 'fade_v.png'
        ]
        assert len(fades) == 1, name
        fade = fades[0]
        # fade_v.png reaches alpha 255 at about 75% of its height and
        # stays there. That point has to be at or above the row band.
        opaque_at = _px(fade, 'top') + int(0.75 * _px(fade, 'height'))
        assert opaque_at <= _BAND_TOP, name

        plates = [
            el for el in root.iter('control')
            if el.get('type') == 'image' and _texture_name(el) == 'white.png'
            and (el.findtext('top') or '').strip() == str(_BAND_TOP)
        ]
        assert len(plates) == 1, name
        plate = plates[0]
        diffuse = (plate.find('texture').get('colordiffuse') or '')
        assert diffuse.startswith('FF') and len(diffuse) == 8, name
        assert _px(plate, 'width') == 1920, name
        assert _px(plate, 'top') + _px(plate, 'height') == _SCREEN, name

        side = [
            el for el in root.iter('control')
            if el.get('type') == 'image' and _texture_name(el) == 'fade_h.png'
        ]
        assert side and _px(side[0], 'width') >= 960, name

        title = _by_id(root, spec['title'])
        meta = _by_id(root, spec['meta'])
        plot = _by_id(root, spec['plot'])
        plot_bottom, title_top, title_h = _assert_text_stack(name, title, meta, plot, spec)
        assert plot_bottom <= _ZONE_BOTTOM, name

        rows = _by_id(root, spec['rows'])
        row_top, row_h = _px(rows, 'top'), _px(rows, 'height')
        assert row_top == _BAND_TOP and row_h == _BAND_HEIGHT, name
        assert row_top + row_h == _SCREEN, name
        assert row_top >= plot_bottom, name

        logo_id = spec.get('logo')
        if logo_id:
            logo = _by_id(root, logo_id)
            assert _px(logo, 'top') == title_top, name
            assert _px(logo, 'height') == title_h, name
            assert 'keep' in (logo.findtext('aspectratio') or ''), name

        pills_id = spec.get('pills')
        if pills_id:
            pills = _by_id(root, pills_id)
            assert _px(pills, 'top') + _px(pills, 'height') <= title_top, name

        if spec['kind'] == 'fixedlist':
            assert rows.get('type') == 'fixedlist', name
            assert (rows.findtext('focusposition') or '').strip() == '0', name
            assert (rows.findtext('orientation') or '').strip() == 'vertical', name
            item_h = int(rows.find('itemlayout').get('height'))
            focused_h = int(rows.find('focusedlayout').get('height'))
            assert item_h == focused_h, name
            # One full row, plus a partial next row, and not a second full one.
            assert item_h < row_h < item_h * 2, name
        else:
            assert rows.get('type') == 'grouplist', name
            gap = int((rows.findtext('itemgap') or '').strip())
            assert gap < 0, name
            peek = -gap
            assert 16 <= peek < row_h, name
            groups = [
                child for child in list(rows)
                if child.tag == 'control' and child.get('type') == 'group'
            ]
            assert len(groups) >= 4, name
            for group in groups:
                assert _px(group, 'height') == row_h, name
                panel = next(
                    child for child in list(group)
                    if child.tag == 'control' and child.get('type') == 'panel'
                )
                assert panel.find('onup') is not None and panel.find('ondown') is not None, name
                assert panel.find('onleft') is not None and panel.find('onright') is not None, name


def test_showcase_hero_stays_in_the_top_third():
    """Showcase is one horizontal strip. It does not use the row band."""
    for name, spec in _SHOWCASE.items():
        root = _root(name)
        title = _showcase_title(root)
        meta = _showcase_meta(root)
        plot = _showcase_plot(root)
        rows = _by_id(root, spec['rows'])
        plot_bottom, _title_top, _title_h = _assert_text_stack(name, title, meta, plot, spec)
        row_top = _px(rows, 'top')
        assert plot_bottom <= _ZONE_BOTTOM, name
        assert row_top >= _ZONE_BOTTOM, name
        assert row_top >= plot_bottom, name
