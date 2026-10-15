# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""HubWindow: one poster row per catalog, exercised against the kodistubs."""
import contextlib
import datetime
import json
import os

import pytest

from tests.kodistubs import install_kodi_stubs

_RELOAD = (
    'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.homewindow', 'lib.ui.hubwindow',
    'lib.ui.catalogpicker', 'lib.ui.detailwindow', 'lib.ui.mystuff',
)


@pytest.fixture
def load_hub():
    with contextlib.ExitStack() as stack:
        def _load(**kwargs):
            return stack.enter_context(install_kodi_stubs(reload=_RELOAD, **kwargs))

        yield _load


def _addons():
    return [{
        'transportUrl': 'https://a/manifest.json',
        'manifest': {'name': 'Cine', 'catalogs': [
            {'type': 'movie', 'id': 'top', 'name': 'Top'},
            {'type': 'movie', 'id': 'find', 'name': 'Find',
             'extra': [{'name': 'search', 'isRequired': True}]},
            {'type': 'movie', 'id': 'year', 'name': 'Year', 'extra': [
                {'name': 'genre', 'isRequired': True, 'options': ['2024', '2023']},
            ]},
            {'type': 'series', 'id': 'shows', 'name': 'Shows'},
        ]},
    }]


class _Store:
    def __init__(self, addons=None, auth=None):
        self._addons = [] if addons is None else addons
        self._auth = auth

    def get_auth(self):
        return self._auth

    def get_enabled_addons(self):
        return list(self._addons)


def test_descriptors_skip_search_and_keep_the_first_genre(load_hub, monkeypatch):
    ctx = load_hub()
    seen = []

    def _page(transport, manifest, catalog, extra=None):
        seen.append((catalog.get('id'), extra))
        return [{'id': catalog.get('id'), 'name': catalog.get('name'), 'type': 'movie', 'poster': 'p'}]

    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)

    descs = ctx.hubwindow._descriptors(_addons(), frozenset({'movie'}))
    ctx.hubwindow._fill_prefix(descs, 8)

    assert [desc['heading'] for desc in descs] == ['Top', 'Year']
    assert seen == [('top', None), ('year', [('genre', '2024')])]
    assert descs[0]['posters'][0].getProperty('sid') == 'top'


def test_hub_keeps_every_catalog_and_loads_only_the_first_screen(load_hub, monkeypatch):
    ctx = load_hub()
    catalogs = [
        {'type': 'movie', 'id': 'c%d' % index, 'name': 'C%d' % index}
        for index in range(10)
    ]
    addons = [{'transportUrl': 'https://a/manifest.json', 'manifest': {'catalogs': catalogs}}]
    seen = []

    def _page(transport, manifest, catalog, extra=None):
        seen.append(catalog.get('id'))
        return [{'id': catalog.get('id'), 'name': catalog.get('name'), 'type': 'movie', 'poster': 'p'}]

    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)

    descs = ctx.hubwindow._descriptors(addons, frozenset({'movie'}))
    assert len(descs) == 10
    ctx.hubwindow._fill_prefix(descs, ctx.hubwindow._INITIAL_ROWS)

    assert len(descs) == 10
    assert seen == ['c0', 'c1', 'c2']
    assert descs[3]['posters'] is None
    assert descs[9]['posters'] is None


def test_moving_down_loads_the_next_unfetched_row(load_hub, monkeypatch):
    ctx = load_hub()
    seen = []

    def _page(transport, manifest, catalog, extra=None):
        seen.append(catalog.get('id'))
        return [{'id': catalog.get('id'), 'name': catalog.get('name'), 'type': 'movie', 'poster': 'p'}]

    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)
    catalogs = [
        {'type': 'movie', 'id': 'c%d' % index, 'name': 'C%d' % index}
        for index in range(6)
    ]
    addons = [{'transportUrl': 'https://a/manifest.json', 'manifest': {'catalogs': catalogs}}]
    descs = ctx.hubwindow._descriptors(addons, frozenset({'movie'}))
    ctx.hubwindow._fill_prefix(descs, ctx.hubwindow._INITIAL_ROWS)
    seen.clear()
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = descs
    ctx.hubwindow._paint_list(win, select=2)

    import xbmcgui
    win.onAction(xbmcgui.Action(4))

    assert 'c3' in seen
    assert descs[3]['posters']
    assert descs[3]['posters'][0].getProperty('sid') == 'c3'


def test_series_hub_pins_new_episodes_ahead_of_catalogs(load_hub, monkeypatch):
    ctx = load_hub()
    monkeypatch.setattr(ctx.catalogpicker, '_new_episode_items', lambda store: [{
        'type': 'series', 'id': 'show', 'name': 'Show', 'poster': 'p', 'video_id': 'show:1:2',
    }])
    monkeypatch.setattr(
        ctx.homewindow, '_one_catalog_page',
        lambda transport, manifest, catalog, extra=None: [
            {'id': 'pop', 'name': 'Popular', 'type': 'series'},
        ],
    )
    addons = [{'transportUrl': 'https://a/manifest.json', 'manifest': {'catalogs': [
        {'type': 'series', 'id': 'pop', 'name': 'Popular'},
    ]}}]

    descs, episodes = ctx.hubwindow._build(
        _Store(), addons, frozenset({'series', 'tv'}),
    )

    assert episodes[0]['video_id'] == 'show:1:2'
    assert descs[0]['posters'][0].getProperty('episode_index') == '0'
    assert descs[0]['posters'][0].getProperty('sid') == 'show'
    assert descs[0]['posters'][0].getProperty('thumbnail') == 'p'
    assert descs[0]['posters'][0].getProperty('fanart') == 'p'
    assert len(descs) == 2


def test_clicking_the_first_new_episode_marks_it_seen(load_hub, monkeypatch):
    ctx = load_hub()
    marked = []
    opened = []
    monkeypatch.setattr(ctx.catalogpicker, '_mark_episode_seen', lambda episode: marked.append(episode))
    monkeypatch.setattr(
        ctx.detailwindow, 'open_detail',
        lambda ctype, sid, video_id=None: opened.append((ctype, sid, video_id)) or True,
    )
    import xbmcgui
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    episode = {'type': 'series', 'id': 'show', 'video_id': 'show:1:2'}
    poster = xbmcgui.ListItem('Show')
    poster.setProperty('episode_index', '0')
    poster.setProperty('sid', 'show')
    poster.setProperty('stype', 'series')
    win._episodes = [episode]
    win._descs = [{'heading': 'New', 'posters': [poster], 'col': 0}]
    ctx.hubwindow._paint_list(win, select=0)

    win.onClick(ctx.hubwindow.HUB_LIST)

    assert marked == [episode]
    assert opened == [('series', 'show', 'show:1:2')]
    assert win.should_close_caller is True
    assert win.closed is True


def test_right_moves_the_focus_to_the_next_poster(load_hub):
    ctx = load_hub()
    import xbmcgui
    posters = []
    for index in range(3):
        poster = xbmcgui.ListItem('T%d' % index)
        poster.setProperty('thumbnail', 'p%d' % index)
        poster.setProperty('sid', 'id%d' % index)
        poster.setProperty('hero_title', 'T%d' % index)
        posters.append(poster)
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = [{'heading': 'Top', 'posters': posters, 'col': 0}]
    ctx.hubwindow._paint_list(win, select=0)

    win.onAction(xbmcgui.Action(2))

    assert win._descs[0]['col'] == 1
    item = win.getControl(ctx.hubwindow.HUB_LIST).getSelectedItem()
    assert item.getProperty('sid') == 'id1'
    # Slot 1 of the visible window, which is where the stroke for that poster is drawn.
    assert item.getProperty('focusslot') == '1'


def test_right_at_the_end_of_the_screen_appends_the_rest_and_keeps_the_hero(load_hub):
    """The first screen is not the end of the row. Right near it must
    bring the held-back posters in, move onto the next one, and leave
    that title on the hero. A blank list item used to wipe the title
    and the plot and then ignore the remote."""
    ctx = load_hub()
    import xbmcgui
    posters = []
    for index in range(3):
        poster = xbmcgui.ListItem('T%d' % index)
        poster.setProperty('hero_title', 'T%d' % index)
        poster.setProperty('hero_plot', 'plot %d' % index)
        poster.setProperty('sid', 'id%d' % index)
        posters.append(poster)
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = [{
        'heading': 'Top',
        'posters': posters,
        'col': 2,
        'pending': [
            {'id': 'id3', 'name': 'T3', 'type': 'movie', 'poster': 'p3', 'description': 'plot 3'},
            {'id': 'id4', 'name': 'T4', 'type': 'movie', 'poster': 'p4', 'description': 'plot 4'},
        ],
    }]
    ctx.hubwindow._paint_list(win, select=0)
    win.setFocusId(ctx.hubwindow.HUB_LIST)

    win.onAction(xbmcgui.Action(2))

    assert win._descs[0]['col'] == 3
    assert [item.getProperty('sid') for item in win._descs[0]['posters']] == [
        'id0', 'id1', 'id2', 'id3', 'id4',
    ]
    selected = win.getControl(ctx.hubwindow.HUB_LIST).getSelectedItem()
    assert selected.getProperty('hero_title') == 'T3'
    assert selected.getProperty('focusslot') == '3'
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'T3'
    assert win.getControl(ctx.homewindow.HERO_PLOT).text == 'plot 3'


def test_empty_hub_closes_and_notifies(load_hub, monkeypatch):
    ctx = load_hub()
    monkeypatch.setattr(ctx.hubwindow, 'get_store', lambda: _Store(addons=[]))
    monkeypatch.setattr(ctx.hubwindow, '_build', lambda store, addons, types: ([], []))
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win.types = frozenset({'movie'})

    win.onInit()

    assert win.closed is True
    assert ctx.env.notifications


def test_hub_bar_is_right_aligned_and_posters_have_a_focus_frame():
    import os
    import xml.etree.ElementTree as ET

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'resources', 'skins', 'Default', '1080i', 'HubWindow.xml')
    tree = ET.parse(path).getroot()
    bar = tree.find(".//control[@id='30011']")
    assert bar.get('type') == 'grouplist'
    assert (bar.findtext('align') or '').strip() == 'right'
    buttons = [child.get('id') for child in list(bar) if child.tag == 'control']
    assert buttons[-1] == '30072'
    rows = tree.find(".//control[@id='31000']")
    assert rows is not None and rows.get('type') == 'fixedlist'
    assert (rows.findtext('focusposition') or '').strip() == '0'
    assert rows.find('onleft') is not None and rows.find('onright') is not None
    blob = ET.tostring(rows.find('focusedlayout'), encoding='unicode')
    assert 'FFFFFFFF' in blob
    assert 'mask_poster.png' in blob
    assert 'mask_land.png' in blob
    assert 'round_mask.png' not in blob
    assert 'focusleft' not in blob
    # Eight poster strokes plus four landscape strokes for New Episodes.
    assert blob.count('focus_stroke.png') == 12
    focused = rows.find('focusedlayout')
    strokes = [
        el for el in focused.findall('control')
        if (el.findtext('texture') or '').strip() == 'focus_stroke.png'
    ]
    land = []
    posters = []
    for el in strokes:
        visible = [(node.text or '').strip() for node in el.findall('visible')]
        if 'String.IsEqual(ListItem.Property(layout),land)' in visible:
            land.append(el)
        if '!String.IsEqual(ListItem.Property(layout),land)' in visible:
            posters.append(el)
    assert len(land) == 4
    assert len(posters) == 8
    for el in land:
        assert (el.findtext('width') or '').strip() == '392'
        assert (el.findtext('height') or '').strip() == '220'
    for el in posters:
        assert (el.findtext('width') or '').strip() == '200'
        assert (el.findtext('height') or '').strip() == '300'
    land_art = [
        el for el in focused.findall('control')
        if (el.find('texture').get('diffuse') if el.find('texture') is not None else '') == 'mask_land.png'
    ]
    assert len(land_art) == 4
    for el in land_art:
        assert (el.findtext('width') or '').strip() == '392'
        assert (el.findtext('height') or '').strip() == '220'
        assert (el.findtext('aspectratio') or '').strip() == 'scale'
        visible = [(node.text or '').strip() for node in el.findall('visible')]
        assert 'String.IsEqual(ListItem.Property(layout),land)' in visible
    assert 'pill_fill.png' in ET.tostring(bar, encoding='unicode')


def test_new_episodes_row_paints_the_cinemeta_still_the_skin_reads(load_hub, monkeypatch):
    """Game of Thrones S1E3, as Cinemeta actually returns it.

    HubWindow.xml does not read ListItem.Art(thumb/poster/fanart). The
    card texture is ``$INFO[ListItem.Property(p0)]``, and ``_apply_posters``
    copies the focused poster's ``thumbnail`` property into ``p0``. That
    property has to be the episode still, not the series poster. The
    hero title is ``S1E3 · Lord Snow`` and the plot is the episode
    overview. The series logo stays off, or the skin hides the title.
    """
    import xml.etree.ElementTree as ET

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skin = ET.parse(os.path.join(
        root, 'resources', 'skins', 'Default', '1080i', 'HubWindow.xml',
    )).getroot()
    row = skin.find(".//control[@id='31000']")
    textures = [
        node.text.strip()
        for node in row.iter('texture')
        if node.text and 'ListItem.Property(p0)' in node.text
    ]
    assert textures
    assert all(text == '$INFO[ListItem.Property(p0)]' for text in textures)
    blob = ET.tostring(row, encoding='unicode')
    assert 'ListItem.Art(poster)' not in blob
    assert 'ListItem.Art(thumb)' not in blob
    assert 'ListItem.Art(fanart)' not in blob

    with open(os.path.join(root, 'tests', 'fixtures', 'cinemeta_tt0944947.json')) as fh:
        meta = json.load(fh)
    from lib.newepisodes import new_episodes
    episodes = new_episodes(
        [{'type': 'series', 'id': meta['id'], 'video_id': 'tt0944947:1:2'}],
        {meta['id']: meta},
        {},
        datetime.datetime(2026, 10, 15),
    )
    assert len(episodes) == 1
    episode = episodes[0]
    still = 'https://episodes.metahub.space/tt0944947/1/3/w780.jpg'
    assert episode['poster'] == still
    assert episode['poster'] != meta['poster']
    assert episode['background'] == still
    assert episode['label'] == 'S1E3 \u00b7 Lord Snow'
    assert episode['overview'].startswith('Jon impresses Tyrion')

    ctx = load_hub()
    monkeypatch.setattr(ctx.catalogpicker, '_new_episode_items', lambda store: episodes)
    desc = ctx.hubwindow._episode_descriptor(_Store(), frozenset({'series', 'tv'}))
    assert desc is not None
    import xbmcgui
    assert desc['layout'] == 'land'
    row_item = xbmcgui.ListItem('New Episodes')
    ctx.hubwindow._apply_posters(row_item, desc['posters'], 0, desc['layout'])

    assert row_item.getProperty('layout') == 'land'
    assert row_item.getProperty('p0') == still
    assert meta['poster'] not in row_item.getProperty('p0')
    assert row_item.getProperty('hero_title') == 'S1E3 \u00b7 Lord Snow'
    assert row_item.getProperty('hero_meta') == 'Game of Thrones'
    assert row_item.getProperty('hero_plot').startswith('Jon impresses Tyrion')
    assert row_item.getProperty('hero_logo') == ''
    assert row_item.getProperty('fanart') == still


def test_landscape_row_slides_inside_four_slots(load_hub):
    """New Episodes draws four wide cards. The fifth title slides the
    window so the ring stays on a landscape slot, and the portrait
    properties stay empty."""
    ctx = load_hub()
    import xbmcgui
    posters = []
    for index in range(6):
        poster = xbmcgui.ListItem('E%d' % index)
        poster.setProperty('thumbnail', 'still-%d' % index)
        posters.append(poster)
    row = xbmcgui.ListItem('New Episodes')

    ctx.hubwindow._apply_posters(row, posters, 4, 'land')

    assert row.getProperty('layout') == 'land'
    assert row.getProperty('focusslot') == '3'
    assert row.getProperty('p0') == 'still-1'
    assert row.getProperty('p3') == 'still-4'
    assert row.getProperty('p4') == ''
