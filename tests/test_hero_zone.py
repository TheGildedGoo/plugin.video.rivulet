# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The hero is full-screen fanart, and the focused row is a fixed band.

Kodi scales 1920x1080 skin space onto whatever display the box is
plugged into, so these numbers are the layout. On Home, the hubs, and
Library the fanart fills the screen from the top. A vertical fade is
opaque by the row band, and a solid plate covers that band, so the art
never runs behind the rows. The title (or the clearlogo) sits on the
left, just above the row, and the description sits directly under it.
Ratings sit in the right quarter. The picture
is shown whole (`keep`), letterboxed on the black plate, and the text
ends on the row.

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

The title and the description sit in the lower part of that hero, just
above the row, not under the header. The description is six lines in a
column 55% of the screen wide (1056px). A two-line box under the header
clipped the plot at the top and at the right edge. Ratings share that
lower band, in the right quarter. Both sit on one black bar
(hero_bar.png) across the screen. The bar's top 64 pixels fade into
the picture. Python shortens the bar when the text is short. On Home
and the hubs the bar stops 40px above the row, and a 2px grey line
runs across the top of that row, so the row title is not tight against
the description. Grid and a catalog list still end on the row. The
vertical fade starts at y=0 and stays clear through that text, so the
header is not on a lighter strip. It is opaque by the row.
"""
import os
import xml.etree.ElementTree as ET

_SKIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'resources', 'skins', 'Default', '1080i',
)
# One row, sitting on y=1080. Poster and focus-frame sizes are unchanged.
_SCREEN = 1080

# font13 is 30. Six lines need 180; the box is 200 so a textbox inset
# does not clip the first or last line, and a seventh (210) does not fit.
# font27 is 27. Six lines need 162; the box is 180, and a seventh (189)
# does not fit.
# 1056 is 55% of 1920. The column stays left of the right-quarter fade.
_TEXT_WIDTH = 1056
_ROWS = {
    'HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 6, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (692, 388), 'gap': 40,
    },
    'Rev2HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 6, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (692, 388), 'gap': 40,
    },
    'HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 6, 'font': 30, 'title_h': 64,
        'kind': 'fixedlist', 'band': (740, 340), 'gap': 40,
    },
    'Rev2HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 6, 'font': 30, 'title_h': 64,
        'kind': 'fixedlist', 'band': (740, 340), 'gap': 40,
    },
    'GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024', 'caption': '30025',
        'rows': '30001', 'lines': 6, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (684, 396),
    },
    'Rev2GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024', 'caption': '30025',
        'rows': '30001', 'lines': 6, 'font': 30, 'title_h': 64,
        'kind': 'grouplist', 'band': (684, 396),
    },
}
_SHOWCASE = {
    'ShowcaseWindow.xml': {'rows': '30002', 'lines': 6, 'font': 27, 'title_h': 92},
    'Rev2ShowcaseWindow.xml': {'rows': '30002', 'lines': 6, 'font': 27, 'title_h': 92},
}
# Below the header. A title back up at y=172 is the clipped layout.
_HERO_TEXT_TOP = 360


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
    assert title_top >= _HERO_TEXT_TOP, name
    assert plot_top >= title_top + title_h, name
    assert plot_top <= title_top + title_h + 16, name
    # Six lines of the face it uses. The next line does not fit.
    assert spec['font'] * spec['lines'] <= plot_h < spec['font'] * (spec['lines'] + 1), name
    scroll = plot.find('autoscroll')
    assert scroll is not None and (scroll.text or '').strip() == 'true', name
    assert (title.findtext('wrapmultiline') or '').strip() == 'false', name
    assert _px(title, 'width') == _TEXT_WIDTH, name
    assert _px(plot, 'width') == _TEXT_WIDTH, name
    assert _px(title, 'left') == _px(plot, 'left'), name
    assert _px(title, 'left') + _px(title, 'width') <= 1440, name
    assert _px(plot, 'left') + _px(plot, 'width') <= 1440, name
    assert meta_left >= 1440, name
    assert meta_left + meta_w <= 1880, name
    assert abs(_px(meta, 'top') - title_top) <= 8, name
    assert _px(meta, 'top') + _px(meta, 'height') <= 1080, name
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
    assert _px(fade, 'top') == 0, name
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
        # The ramp starts at the top of the screen. A control that began
        # lower left a lighter strip behind the header and a hard edge.
        # fade_v.png reaches alpha 255 at about 75% of its height.
        assert _px(fade, 'top') == 0, name
        opaque_at = int(0.75 * _px(fade, 'height'))
        assert opaque_at <= band_top, name

        plates = [
            el for el in root.iter('control')
            if el.get('type') == 'image' and _texture_name(el) == 'white.png'
            and (el.findtext('top') or '').strip() == str(band_top)
            and _px(el, 'top') + _px(el, 'height') == _SCREEN
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
        # Home and the hubs stop the text short of the row so the heading
        # is not tight against the description. A hairline marks that edge.
        gap = spec.get('gap', 0)
        stack_limit = band_top - gap
        if gap:
            lines = [
                el for el in root.iter('control')
                if el.get('type') == 'image' and _texture_name(el) == 'white.png'
                and (el.findtext('top') or '').strip() == str(band_top)
                and _px(el, 'height') == 2
            ]
            assert len(lines) == 1, name
            assert (lines[0].find('texture').get('colordiffuse') or '') == 'FF8B949E', name
            assert _px(lines[0], 'width') == 1920, name
            assert _px(lines[0], 'left') == 0, name
        caption_id = spec.get('caption')
        if caption_id:
            caption = _by_id(root, caption_id)
            caption_top = _px(caption, 'top')
            caption_bottom = caption_top + _px(caption, 'height')
            assert caption_top >= plot_bottom, name
            assert caption_top <= plot_bottom + 16, name
            assert _px(caption, 'width') == _TEXT_WIDTH, name
            assert caption_bottom <= stack_limit, name
            assert stack_limit - caption_bottom <= 8, name
            stack_bottom = caption_bottom
        else:
            assert plot_bottom <= stack_limit, name
            assert stack_limit - plot_bottom <= 8, name
            stack_bottom = plot_bottom
        assert _px(meta, 'top') + _px(meta, 'height') <= stack_limit + 8, name
        assert stack_bottom <= stack_limit, name

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
        assert plot_bottom <= row_top, name
        assert row_top - plot_bottom <= 8, name
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
        assert _px(fades[0], 'top') == 0, name
        opaque_at = int(0.75 * _px(fades[0], 'height'))
        assert opaque_at <= row_top, name


def _bar_control(root):
    found = [
        el for el in root.iter('control')
        if el.get('type') == 'image' and _texture_name(el) == 'hero_bar.png'
    ]
    assert len(found) == 1
    return found[0]


def test_hero_bar_spans_the_screen_and_ends_on_the_row():
    """One bar, full width, bottom on the poster row, fade above the words.

    Two floating boxes read as holes in the picture. The texture's top
    border is the unscaled fade, so stretching the bar does not draw a
    hard line under the backdrop.
    """
    names = list(_ROWS) + list(_SHOWCASE)
    for name in names:
        root = _root(name)
        assert root.find(".//control[@id='30027']") is None, name
        bar = _bar_control(root)
        assert bar.get('id') == '30026', name
        texture = bar.find('texture')
        assert (texture.get('border') or '') == '0,64,0,8', name
        assert _px(bar, 'left') == 0, name
        assert _px(bar, 'width') == 1920, name
        band_top = _ROWS[name]['band'][0] if name in _ROWS else 740
        gap = _ROWS[name].get('gap', 0) if name in _ROWS else 0
        assert _px(bar, 'top') + _px(bar, 'height') == band_top - gap, name
        controls = list(root.iter('control'))
        title = _by_id(root, '30020')
        assert controls.index(bar) < controls.index(title), name
        # The fade starts above the words. The solid part is the text.
        assert _px(bar, 'top') < _px(title, 'top'), name
        assert _px(title, 'top') - _px(bar, 'top') == 64, name


def test_hero_fades_are_smooth_full_height_ramps():
    """The right fade is a light vignette, clear on the left.

    The file it replaced reached black, so the ratings sat in a
    hard-edged rectangle. The vertical fade stays clear through the
    hero text and is opaque by the row, so the title is not in a
    dark slab and there is no step under the header.
    """
    import pytest
    pytest.importorskip('PIL')
    from PIL import Image

    media = os.path.join(os.path.dirname(_SKIN), 'media')
    side = Image.open(os.path.join(media, 'fade_h.png')).convert('RGBA')
    width, height = side.size
    assert height >= _SCREEN and width >= 64
    pixels = side.load()
    assert pixels[0, height // 2][3] <= 8
    # A vignette, not a black plate. 255 was the rectangle.
    assert 60 <= pixels[width - 1, height // 2][3] <= 120
    assert abs(pixels[width // 2, 0][3] - pixels[width // 2, height - 1][3]) <= 2
    previous = pixels[0, height // 2][3]
    for x in range(width):
        alpha = pixels[x, height // 2][3]
        assert previous - 1 <= alpha <= previous + 8
        previous = alpha

    down = Image.open(os.path.join(media, 'fade_v.png')).convert('RGBA')
    down_w, down_h = down.size
    assert down_h >= 128
    column = down.load()
    assert column[down_w // 2, 0][3] <= 8
    # Still clear where the title sits, about 40% down the ramp.
    assert column[down_w // 2, int(0.40 * (down_h - 1))][3] <= 8
    hold = int(round(0.75 * (down_h - 1)))
    assert column[down_w // 2, hold][3] >= 250
    assert column[down_w // 2, down_h - 1][3] >= 250
    previous = column[down_w // 2, 0][3]
    for y in range(down_h):
        alpha = column[down_w // 2, y][3]
        assert previous - 1 <= alpha <= previous + 8
        previous = alpha

    bar = Image.open(os.path.join(media, 'hero_bar.png')).convert('RGBA')
    bw, bh = bar.size
    assert bw >= 8 and bh > 64
    bp = bar.load()
    assert bp[bw // 2, 0][3] <= 8
    assert bp[bw // 2, 63][3] >= 250
    assert bp[bw // 2, bh - 1][3] >= 250
    previous = bp[bw // 2, 0][3]
    for y in range(bh):
        alpha = bp[bw // 2, y][3]
        assert previous - 1 <= alpha
        previous = alpha

    shade = Image.open(os.path.join(media, 'card_shade.png')).convert('RGBA')
    sw, sh = shade.size
    sp = shade.load()
    assert sp[sw // 2, 0][3] <= 8
    assert sp[sw // 2, sh - 1][3] >= 160
