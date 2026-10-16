# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The hero is full-screen fanart, and the focused row is a fixed band.

Kodi scales 1920x1080 skin space onto whatever display the box is
plugged into, so these numbers are the layout. On Home, the hubs, and
Library the fanart fills the screen from the top. A vertical fade is
opaque by the row band, and a solid plate covers that band, so the art
never runs behind the rows. The title (or the clearlogo) sits on the left, and the description
sits directly under it. Ratings sit in the right quarter, over a
fade. The picture is shown whole (`keep`), letterboxed on the black
plate, and the text ends above the band.

The focused row is the only row on screen, pinned to the bottom edge.
Home's row is 388px (a 32px heading plus the 356px poster panel), the
hubs' row is the existing 340px catalog item, and Library's row is
396px (a 32px header plus the 364px panel). A 300px poster plus its
heading does not fit in a literal quarter of 1080 without clipping the
focus frame, so the band is one card tall instead. Home and Library
pin it by making every row group exactly as tall as the viewport and
setting itemgap to 0: Kodi top-aligns on the way up and bottom-aligns
on the way down, and those are the same scroll when the heights match.
A negative gap would pull the next heading into the band. The hubs are
one fixedlist with focusposition 0 and a height of exactly one row.

A catalog, decade, or search list is the same idea with one horizontal
row of titles: Down and Up step a viewport of that row, and the hero
is bound to the focused item.
"""
import os
import xml.etree.ElementTree as ET

_SKIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'resources', 'skins', 'Default', '1080i',
)
# One row, sitting on y=1080. Poster and focus-frame sizes are unchanged.
_SCREEN = 1080

# font13 is 30. Two lines fit in 64 and a third (90) does not.
# font27 is 27. Three lines fit in 96 and a fourth (108) does not.
_ROWS = {
    'HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (692, 388),
    },
    'Rev2HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (692, 388),
    },
    'HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'fixedlist', 'band': (740, 340),
    },
    'Rev2HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'fixedlist', 'band': (740, 340),
    },
    'GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024',
        'rows': '30001', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (684, 396),
    },
    'Rev2GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024',
        'rows': '30001', 'lines': 2, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (684, 396),
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
    for box in root.iter('control'):
        if box.get('type') == 'textbox' and 'plot' in (box.findtext('label') or ''):
            return box
    raise AssertionError('showcase has no plot')


def _texture_name(control):
    node = control.find('texture')
    if node is None or node.text is None:
        return ''
    return node.text.strip()


def _assert_text_stack(name, title, meta, plot, spec):
    """Title on the left, description directly under it, ratings in the right quarter."""
    title_top, title_h = _px(title, 'top'), _px(title, 'height')
    plot_top, plot_h = _px(plot, 'top'), _px(plot, 'height')
    meta_left, meta_w = _px(meta, 'left'), _px(meta, 'width')
    assert title_h == spec['title_h'], name
    assert plot_top >= title_top + title_h, name
    assert plot_top <= title_top + title_h + 16, name
    # Two (or three) lines of the face it uses. The next line does not fit.
    assert spec['font'] * spec['lines'] <= plot_h < spec['font'] * (spec['lines'] + 1), name
    scroll = plot.find('autoscroll')
    assert scroll is not None and (scroll.text or '').strip() == 'true', name
    assert (title.findtext('wrapmultiline') or '').strip() == 'false', name
    assert _px(title, 'left') + _px(title, 'width') <= 1440, name
    assert _px(plot, 'left') + _px(plot, 'width') <= 1440, name
    assert meta_left >= 1440, name
    assert meta_left + meta_w <= 1920, name
    assert _px(meta, 'top') <= title_top + 8, name
    assert _px(meta, 'height') >= 160, name
    return plot_top + plot_h, title_top, title_h


def _assert_full_backdrop(name, root):
    fanart = _by_id(root, '30000')
    assert _px(fanart, 'width') == 1920 and _px(fanart, 'height') == _SCREEN, name
    assert (fanart.findtext('left') or '0').strip() in ('', '0'), name
    assert (fanart.findtext('top') or '0').strip() in ('', '0'), name
    aspect = (fanart.findtext('aspectratio') or '').strip()
    assert aspect == 'keep', name
    diffuse = (fanart.find('texture').get('colordiffuse') or '')
    assert diffuse == 'FFFFFFFF', name
    side = [
        el for el in root.iter('control')
        if el.get('type') == 'image' and _texture_name(el) == 'fade_h.png'
    ]
    assert len(side) == 1, name
    fade = side[0]
    assert _px(fade, 'left') == 1440, name
    assert _px(fade, 'width') == 480, name
    assert _px(fade, 'height') == _SCREEN, name


def test_focused_row_is_pinned_in_the_lower_band_over_full_screen_fanart():
    """Fanart fills the screen. Exactly one row is visible, pinned to
    the bottom of the skin. Up and down switch rows."""
    for name, spec in _ROWS.items():
        band_top, band_height = spec['band']
        root = _root(name)
        _assert_full_backdrop(name, root)

        fades = [
            el for el in root.iter('control')
            if el.get('type') == 'image' and _texture_name(el) == 'fade_v.png'
        ]
        assert len(fades) == 1, name
        fade = fades[0]
        # fade_v.png reaches alpha 255 at about 75% of its height and
        # stays there. That point has to be at or above the row band.
        opaque_at = _px(fade, 'top') + int(0.75 * _px(fade, 'height'))
        assert opaque_at <= band_top, name

        plates = [
            el for el in root.iter('control')
            if el.get('type') == 'image' and _texture_name(el) == 'white.png'
            and (el.findtext('top') or '').strip() == str(band_top)
        ]
        assert len(plates) == 1, name
        plate = plates[0]
        diffuse = (plate.find('texture').get('colordiffuse') or '')
        assert diffuse.startswith('FF') and len(diffuse) == 8, name
        assert _px(plate, 'width') == 1920, name
        assert _px(plate, 'top') + _px(plate, 'height') == _SCREEN, name

        title = _by_id(root, spec['title'])
        meta = _by_id(root, spec['meta'])
        plot = _by_id(root, spec['plot'])
        plot_bottom, title_top, title_h = _assert_text_stack(name, title, meta, plot, spec)
        assert plot_bottom <= _ZONE_BOTTOM, name

        rows = _by_id(root, spec['rows'])
        row_top, row_h = _px(rows, 'top'), _px(rows, 'height')
        assert row_top == band_top and row_h == band_height, name
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
            assert item_h == focused_h == row_h, name
        else:
            assert rows.get('type') == 'grouplist', name
            gap = int((rows.findtext('itemgap') or '').strip())
            assert gap == 0, name
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
                assert _px(panel, 'top') + _px(panel, 'height') <= row_h, name
                assert panel.find('onup') is not None and panel.find('ondown') is not None, name
                assert panel.find('onleft') is not None and panel.find('onright') is not None, name


def test_showcase_is_one_row_under_the_backdrop():
    """A catalog list is one poster row on the bottom edge. The title,
    metadata, and description stay above it and follow the focused item."""
    for name, spec in _SHOWCASE.items():
        root = _root(name)
        _assert_full_backdrop(name, root)
        title = _showcase_title(root)
        meta = _showcase_meta(root)
        plot = _showcase_plot(root)
        rows = _by_id(root, spec['rows'])
        plot_bottom, _title_top, _title_h = _assert_text_stack(name, title, meta, plot, spec)
        row_top, row_h = _px(rows, 'top'), _px(rows, 'height')
        assert plot_bottom <= _ZONE_BOTTOM, name
        assert row_top == 740 and row_h == 340, name
        assert row_top + row_h == _SCREEN, name
        assert row_top >= plot_bottom, name
        assert (rows.findtext('orientation') or '').strip() == 'horizontal', name
        assert (rows.findtext('focusposition') or '').strip() == '0', name
        item_h = int(rows.find('itemlayout').get('height'))
        focused_h = int(rows.find('focusedlayout').get('height'))
        assert item_h == focused_h == row_h, name
        fades = [
            el for el in root.iter('control')
            if el.get('type') == 'image' and _texture_name(el) == 'fade_v.png'
        ]
        assert len(fades) == 1, name
        opaque_at = _px(fades[0], 'top') + int(0.75 * _px(fades[0], 'height'))
        assert opaque_at <= row_top, name
