# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""The hero zone is the top third of the 1920x1080 skin.

Kodi scales that coordinate space onto whatever display the box is
plugged into, so these numbers are the layout. On every screen that
puts rows under a focused title, the title (or the clearlogo), the
metadata line, and the description occupy that third in that order.
The rows start at y=360.

The Series hub photo showed the title and then the New Episodes row,
with the overview running into the row. The description box ended
twenty pixels above the list and was tall enough for a third line of
font13, which Kodi does not clip to the control. The box is now two
lines, and anything longer scrolls inside it.
"""
import os
import xml.etree.ElementTree as ET

_SKIN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'resources', 'skins', 'Default', '1080i',
)
# Top third of the 1080-tall skin.
_ZONE_BOTTOM = 360

# font13 is 30. Two lines fit in 64 and a third (90) does not.
# font27 is 27. Three lines fit in 96 and a fourth (108) does not.
_ROWS = {
    'HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 2, 'font': 30, 'title_h': 64,
    },
    'Rev2HomeWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '30001', 'pills': '30010', 'lines': 2, 'font': 30, 'title_h': 64,
    },
    'HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 2, 'font': 30, 'title_h': 64,
    },
    'Rev2HubWindow.xml': {
        'title': '30020', 'logo': '30023', 'meta': '30021', 'plot': '30022',
        'rows': '31000', 'lines': 2, 'font': 30, 'title_h': 64,
    },
    'GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024',
        'rows': '30001', 'lines': 2, 'font': 30, 'title_h': 64,
    },
    'Rev2GridWindow.xml': {
        'title': '30020', 'meta': '30021', 'plot': '30024',
        'rows': '30001', 'lines': 2, 'font': 30, 'title_h': 64,
    },
    'ShowcaseWindow.xml': {
        'rows': '30002', 'lines': 3, 'font': 27, 'title_h': 92,
    },
    'Rev2ShowcaseWindow.xml': {
        'rows': '30002', 'lines': 3, 'font': 27, 'title_h': 92,
    },
}


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


def test_hero_zone_is_the_top_third_and_the_rows_start_below_it():
    """Title, metadata, and description stack inside y<360. Rows do not."""
    for name, spec in _ROWS.items():
        root = _root(name)
        if spec.get('title'):
            title = _by_id(root, spec['title'])
            meta = _by_id(root, spec['meta'])
            plot = _by_id(root, spec['plot'])
        else:
            title = _showcase_title(root)
            meta = _showcase_meta(root)
            plot = _showcase_plot(root)
        rows = _by_id(root, spec['rows'])

        title_top, title_h = _px(title, 'top'), _px(title, 'height')
        meta_top, meta_h = _px(meta, 'top'), _px(meta, 'height')
        plot_top, plot_h = _px(plot, 'top'), _px(plot, 'height')
        row_top = _px(rows, 'top')

        assert title_h == spec['title_h'], name
        assert meta_top >= title_top + title_h, name
        assert plot_top >= meta_top + meta_h, name
        assert plot_top + plot_h <= _ZONE_BOTTOM, name
        assert row_top >= _ZONE_BOTTOM, name
        assert row_top >= plot_top + plot_h, name

        # Clamped to N lines of the face it uses. The next line does not fit.
        assert spec['font'] * spec['lines'] <= plot_h < spec['font'] * (spec['lines'] + 1), name
        scroll = plot.find('autoscroll')
        assert scroll is not None and (scroll.text or '').strip() == 'true', name
        assert (title.findtext('wrapmultiline') or '').strip() == 'false', name

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
