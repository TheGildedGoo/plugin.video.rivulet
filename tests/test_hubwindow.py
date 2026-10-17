# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""HubWindow: one poster row per catalog, exercised against the kodistubs."""
import contextlib
import datetime
import json
import os
import threading

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
            {'type': 'movie', 'id': 'genre', 'name': 'Genre', 'extra': [
                {'name': 'genre', 'isRequired': True, 'options': ['Action', 'Comedy']},
            ]},
            {'type': 'movie', 'id': 'year', 'name': 'Year', 'extra': [
                {'name': 'genre', 'isRequired': True, 'options': ['2026', '2024', '1994', '1950', '1920']},
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

    assert [desc['heading'] for desc in descs] == ['Top', 'Genre', 'Year']
    # A word genre still uses its first option. A year catalog does not
    # fetch: it is decade tiles, and nothing older than the 1960s.
    assert seen == [('top', None), ('genre', [('genre', 'Action')])]
    assert descs[0]['posters'][0].getProperty('sid') == 'top'
    assert descs[2]['kind'] == 'decade'
    assert [item.getLabel() for item in descs[2]['posters']] == ['2020s', '1990s']
    assert descs[2]['posters'][0].getProperty('decade_years') == '2026,2024'


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
    threads = []

    def _page(transport, manifest, catalog, extra=None):
        seen.append(catalog.get('id'))
        threads.append(threading.current_thread().name)
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
    del threads[:]
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = descs
    ctx.hubwindow._paint_list(win, select=2)

    import xbmcgui
    win.onAction(xbmcgui.Action(4))
    ctx.hubwindow._join_row_fetches(win)

    assert 'c3' in seen
    assert threads
    assert all(name != 'MainThread' for name in threads)
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


def test_oninit_paints_the_first_card_before_the_remote_moves(load_hub, monkeypatch):
    """The first card is focused as the hub opens, but getFocusId() is
    still the top bar. The hero used to stay on the addon fanart until
    the selection moved. The descriptor already has that card."""
    ctx = load_hub()
    import xbmcgui
    monkeypatch.setattr(ctx.hubwindow, 'get_store', lambda: _Store(auth=None))
    poster = xbmcgui.ListItem('Dune')
    poster.setProperty('hero_title', 'Dune')
    poster.setProperty('hero_plot', 'A desert.')
    poster.setProperty('fanart', 'back.jpg')
    poster.setProperty('sid', 'tt1')
    poster.setProperty('stype', 'movie')
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win.types = frozenset({'movie'})
    win.heading = 'Movies'
    win._descs = [{'heading': 'TOP', 'posters': [poster], 'col': 0}]
    win._episodes = []
    # What Kodi reports during onInit: the default control, not the list.
    win.getFocusId = lambda: ctx.hubwindow.BTN_SEARCH

    win.onInit()

    assert win.getControl(ctx.homewindow.BACKGROUND).image == 'back.jpg'
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == 'Dune'
    assert win.getControl(ctx.homewindow.HERO_PLOT).text == 'A desert.'
    assert win.getProperty('HeroFill') == ''


def test_empty_hub_closes_and_notifies(load_hub, monkeypatch):
    ctx = load_hub()
    monkeypatch.setattr(ctx.hubwindow, 'get_store', lambda: _Store(addons=[]))
    monkeypatch.setattr(ctx.hubwindow, '_build', lambda store, addons, types: ([], []))
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win.types = frozenset({'movie'})

    win.onInit()

    assert win.closed is True
    assert ctx.env.notifications
    # Movies / Series / Other land here when the category is empty.
    # The message stays. The notification chime does not.
    assert ctx.env.notification_sounds == [False]


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
        if (el.find('texture') is not None)
        and (el.find('texture').get('diffuse') or '') == 'mask_land.png'
        and (el.findtext('texture') or '').strip().startswith('$INFO')
    ]
    assert len(land_art) == 4
    for el in land_art:
        assert (el.findtext('width') or '').strip() == '392'
        assert (el.findtext('height') or '').strip() == '220'
        assert (el.findtext('aspectratio') or '').strip() == 'scale'
        visible = [(node.text or '').strip() for node in el.findall('visible')]
        assert 'String.IsEqual(ListItem.Property(layout),land)' in visible
    assert 'pill_fill.png' in ET.tostring(bar, encoding='unicode')
    blob = ET.tostring(rows, encoding='unicode')
    assert 'String.IsEqual(ListItem.Property(layout),decade)' in blob
    assert blob.count('ListItem.Property(n0)') >= 2
    rev2 = ET.parse(os.path.join(
        root, 'resources', 'skins', 'Default', '1080i', 'Rev2HubWindow.xml',
    )).getroot()
    rev2_rows = ET.tostring(rev2.find(".//control[@id='31000']"), encoding='unicode')
    assert 'String.IsEqual(ListItem.Property(layout),decade)' in rev2_rows
    assert 'rv_mask_200x300.png' in rev2_rows


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
    assert row_item.getProperty('show0') == 'Game of Thrones'
    assert row_item.getProperty('code0') == 'S:1 E:3'
    assert row_item.getProperty('div1') == ''
    focused = row.find('focusedlayout')
    shades = [
        el for el in focused.findall('control')
        if (el.findtext('texture') or '').strip() == 'card_shade.png'
    ]
    assert len(shades) == 4
    labels = [
        (el.findtext('label') or '').strip()
        for el in focused.findall('control')
        if el.get('type') == 'label'
    ]
    assert '$INFO[ListItem.Property(show0)]' in labels
    assert '$INFO[ListItem.Property(code0)]' in labels


def test_episode_cards_group_a_show_and_split_the_next(load_hub, monkeypatch):
    """Interleaved episodes of two shows become one run per show.

    The row stays one strip. A divider is only the boundary between
    shows, and a card with no season or episode number has no code.
    """
    episodes = [
        {
            'type': 'series', 'id': 'alpha', 'name': 'Alpha',
            'label': 'S1E1 · One', 'season': 1, 'episode': 1,
            'poster': 'a1', 'overview': 'first',
        },
        {
            'type': 'series', 'id': 'beta', 'name': 'Beta',
            'label': 'S2E4 · Two', 'season': 2, 'episode': 4,
            'poster': 'b1', 'overview': 'second',
        },
        {
            'type': 'series', 'id': 'alpha', 'name': 'Alpha',
            'label': 'S1E2 · Three', 'season': 1, 'episode': 2,
            'poster': 'a2', 'overview': 'third',
        },
        {
            'type': 'series', 'id': 'gamma', 'name': 'Gamma',
            'label': 'Untitled', 'season': False, 'episode': None,
            'poster': 'g', 'overview': '',
        },
    ]
    ctx = load_hub()
    monkeypatch.setattr(ctx.catalogpicker, '_new_episode_items', lambda store: episodes)
    desc = ctx.hubwindow._episode_descriptor(_Store(), frozenset({'series', 'tv'}))
    assert [item.getProperty('show_key') for item in desc['posters']] == [
        'alpha', 'alpha', 'beta', 'gamma',
    ]
    assert [item.getProperty('card_code') for item in desc['posters']] == [
        'S:1 E:1', 'S:1 E:2', 'S:2 E:4', '',
    ]
    import xbmcgui
    row = xbmcgui.ListItem('New Episodes')
    ctx.hubwindow._apply_posters(row, desc['posters'], 0, 'land')
    assert row.getProperty('show0') == 'Alpha'
    assert row.getProperty('code0') == 'S:1 E:1'
    assert row.getProperty('show1') == 'Alpha'
    assert row.getProperty('div1') == ''
    assert row.getProperty('show2') == 'Beta'
    assert row.getProperty('code2') == 'S:2 E:4'
    assert row.getProperty('div2') == '1'
    assert row.getProperty('div3') == '1'
    assert row.getProperty('code3') == ''
    assert row.getProperty('hero_title') == 'S1E1 · One'
    assert row.getProperty('hero_meta') == 'Alpha'
    ctx.hubwindow._apply_posters(row, desc['posters'], 0, '')
    assert row.getProperty('show0') == ''
    assert row.getProperty('code0') == ''
    assert row.getProperty('div1') == ''


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


def test_series_year_catalog_stays_on_its_first_option(load_hub, monkeypatch):
    """Decade tiles are the Movies hub only. Series keeps the first year."""
    ctx = load_hub()
    seen = []

    def _page(transport, manifest, catalog, extra=None):
        seen.append(extra)
        return [{'id': 'show', 'name': 'Show', 'type': 'series', 'poster': 'p'}]

    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)
    addons = [{'transportUrl': 'https://a/manifest.json', 'manifest': {'catalogs': [
        {'type': 'series', 'id': 'year', 'name': 'New', 'extra': [
            {'name': 'genre', 'isRequired': True, 'options': ['2024', '2020']},
        ]},
    ]}}]
    descs = ctx.hubwindow._descriptors(addons, frozenset({'series', 'tv'}))
    ctx.hubwindow._fill_prefix(descs, 3)
    assert descs[0]['kind'] == 'catalog'
    assert seen == [[('genre', '2024')]]


def test_decade_tile_opens_the_coverflow(load_hub, monkeypatch):
    ctx = load_hub()
    opened = []

    def _fetch(desc, years, label):
        assert years == ['1994', '1990']
        assert label == '1990s'
        return [{'id': 'shawshank', 'type': 'movie', 'name': 'The Shawshank Redemption'}]

    def _showcase(metas, catalog_title=None, more_pages=None):
        opened.append((list(metas), catalog_title))
        return None

    monkeypatch.setattr(ctx.hubwindow, '_fetch_decade', _fetch)
    monkeypatch.setattr('lib.ui.infowindow.open_showcase', _showcase)
    import xbmcgui
    tile = xbmcgui.ListItem('1990s')
    tile.setProperty('decade', '1990')
    tile.setProperty('decade_years', '1994,1990')
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = [{
        'heading': 'New', 'kind': 'decade', 'layout': 'decade',
        'transport': 'https://a/manifest.json',
        'catalog': {'type': 'movie', 'id': 'year'},
        'posters': [tile], 'col': 0,
    }]
    ctx.hubwindow._paint_list(win, select=0)
    win.onClick(ctx.hubwindow.HUB_LIST)
    assert opened == [([{'id': 'shawshank', 'type': 'movie', 'name': 'The Shawshank Redemption'}], 'New')]
    assert win.closed is not True


def test_a_hub_row_pages_on_without_fetching_page_one_again(load_hub, monkeypatch):
    ctx = load_hub()
    monkeypatch.setattr(
        ctx.homewindow, '_one_catalog_page',
        lambda *args, **kwargs: [{'id': 'tt%d' % index, 'name': 'T%d' % index} for index in range(1, 4)],
    )
    requested = []

    def fake_fetch(transport, ctype, cid, extra=None):
        requested.append(list(extra or []))
        return [{'id': 'tt4', 'name': 'T4'}]

    import lib.ui.views as views

    monkeypatch.setattr(views, '_fetch_catalog', fake_fetch)
    desc = {
        'transport': 'https://addon.example/manifest.json',
        'manifest': {'id': 'x'},
        'catalog': {'type': 'movie', 'id': 'top', 'extra': [{'name': 'skip'}]},
        'extra': None,
        'posters': None,
        'col': 0,
    }

    ctx.hubwindow._load_posters(desc)
    posters = ctx.hubwindow._extend_row(desc)

    assert requested == [[('skip', 3)]]
    assert [poster.getProperty('sid') for poster in posters] == ['tt1', 'tt2', 'tt3', 'tt4']


def _row_of(ctx, count, prefix='tt'):
    return [
        ctx.homewindow._poster_item({'id': '%s%d' % (prefix, index), 'type': 'movie', 'name': 'T%d' % index, 'poster': 'p%d' % index})
        for index in range(count)
    ]


def test_a_scrolled_row_moves_the_ring_before_it_moves_the_row(load_hub):
    """#12: the window moves only when the focus would leave it. The start
    used to be derived from the column alone, so once a row had scrolled,
    every Left slid the whole row and the ring stayed pinned right."""
    ctx = load_hub()
    import xbmcgui
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = [{'heading': 'Top', 'kind': 'catalog', 'posters': _row_of(ctx, 12), 'col': 0,
                   'pending': ['x'], 'exhausted': True}]
    ctx.hubwindow._paint_list(win, select=0)
    win.setFocusId(ctx.hubwindow.HUB_LIST)
    row = win.getControl(ctx.hubwindow.HUB_LIST).getSelectedItem()

    for _ in range(9):
        win.onAction(xbmcgui.Action(2))
    assert row.getProperty('col') == '9'
    assert row.getProperty('focusslot') == '7'
    assert row.getProperty('p0') == 'p2'

    win.onAction(xbmcgui.Action(1))
    # The ring steps left; the row does not move.
    assert row.getProperty('col') == '8'
    assert row.getProperty('focusslot') == '6'
    assert row.getProperty('p0') == 'p2'

    for _ in range(7):
        win.onAction(xbmcgui.Action(1))
    # Past the first visible poster, the row scrolls back with the ring.
    assert row.getProperty('col') == '1'
    assert row.getProperty('focusslot') == '0'
    assert row.getProperty('p0') == 'p1'


def test_a_catalog_that_fails_keeps_its_row_with_a_try_again_card(load_hub, monkeypatch):
    """#16: a failed first page used to drop the row silently, with no log
    line. The row stays with one card; OK on it asks again."""
    ctx = load_hub()
    calls = []

    def _page(transport, manifest, catalog, extra=None):
        calls.append(catalog.get('id'))
        if len(calls) == 1:
            raise ctx.homewindow.CatalogUnavailable(catalog.get('id'))
        return [{'id': 'tt1', 'name': 'One', 'type': 'movie', 'poster': 'p1'}]

    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)
    desc = {'heading': 'Top', 'kind': 'catalog', 'transport': 't', 'manifest': {},
            'catalog': {'type': 'movie', 'id': 'top'}, 'extra': None, 'posters': None, 'col': 0}
    posters = ctx.hubwindow._load_posters(desc)

    assert len(posters) == 1
    card = posters[0]
    assert card.getProperty('retry') == '1'
    assert card.getLabel() == 'STR30490'
    assert card.getProperty('hero_title') == 'Top'
    assert card.getProperty('hero_plot') == 'STR30491'
    assert desc['exhausted'] is True

    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    win._descs = [desc]
    ctx.hubwindow._paint_list(win, select=0)
    win.onClick(ctx.hubwindow.HUB_LIST)
    ctx.hubwindow._join_row_fetches(win)
    import xbmcgui
    win.onAction(xbmcgui.Action(0))

    assert calls == ['top', 'top']
    assert [poster.getProperty('sid') for poster in desc['posters']] == ['tt1']
    row = win.getControl(ctx.hubwindow.HUB_LIST).getListItem(0)
    assert row.getProperty('p0') == 'p1'
    assert row.getProperty('sid') == 'tt1'


def test_a_landed_page_paints_under_its_own_row_after_another_row_is_dropped(load_hub, monkeypatch):
    """#16: workers were handed list positions. The UI thread drops empty
    rows meanwhile, so a page could land under another row's heading."""
    ctx = load_hub()
    gate = threading.Event()

    def _page(transport, manifest, catalog, extra=None):
        if catalog.get('id') == 'slow':
            gate.wait(2)
            return [{'id': 'slow1', 'name': 'Slow', 'type': 'movie', 'poster': 'ps'}]
        return []

    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    first = {'heading': 'Shown', 'kind': 'catalog', 'posters': _row_of(ctx, 2), 'col': 0}
    empty = {'heading': 'Empty', 'kind': 'catalog', 'transport': 't', 'catalog': {'type': 'movie', 'id': 'none'},
             'extra': None, 'posters': None, 'col': 0}
    slow = {'heading': 'Slow', 'kind': 'catalog', 'transport': 't', 'catalog': {'type': 'movie', 'id': 'slow'},
            'extra': None, 'posters': None, 'col': 0}
    win._descs = [first, empty, slow]
    ctx.hubwindow._paint_list(win, select=0)

    ctx.hubwindow._schedule_row_fetch(win, [2])
    ctx.hubwindow._schedule_row_fetch(win, [1])
    # The empty row lands first and is dropped; the slow one lands after.
    for thread in list(win._row_fetch_threads)[1:]:
        thread.join(2)
    ctx.hubwindow._apply_fetched_rows(win)
    assert [desc['heading'] for desc in win._descs] == ['Shown', 'Slow']
    gate.set()
    ctx.hubwindow._join_row_fetches(win)
    ctx.hubwindow._apply_fetched_rows(win)

    rows = win.getControl(ctx.hubwindow.HUB_LIST)
    assert rows.getListItem(1).getProperty('heading') == 'Slow'
    assert rows.getListItem(1).getProperty('p0') == 'ps'


def test_a_landscape_catalog_uses_the_wide_row(load_hub, monkeypatch):
    """#24: channel and video catalogs publish 16:9 art (posterShape
    landscape). A 2:3 slot letterboxed it; the row uses the four wide
    slots New Episodes uses."""
    ctx = load_hub()
    monkeypatch.setattr(
        ctx.homewindow, '_one_catalog_page',
        lambda *args, **kwargs: [
            {'id': 'c%d' % index, 'name': 'C%d' % index, 'type': 'tv', 'poster': 'w%d' % index, 'posterShape': 'landscape'}
            for index in range(6)
        ],
    )
    desc = {'heading': 'Channels', 'kind': 'catalog', 'transport': 't', 'catalog': {'type': 'tv', 'id': 'ch'},
            'extra': None, 'posters': None, 'col': 0}
    ctx.hubwindow._load_posters(desc)
    assert desc['layout'] == 'land'
    import xbmcgui
    row = xbmcgui.ListItem('Channels')
    ctx.hubwindow._apply_posters(row, desc['posters'], 0, desc['layout'])
    assert [row.getProperty('p%d' % slot) for slot in range(5)] == ['w0', 'w1', 'w2', 'w3', '']

    poster_desc = {'heading': 'Movies', 'kind': 'catalog', 'transport': 't', 'catalog': {'type': 'movie', 'id': 'm'},
                   'extra': None, 'posters': None, 'col': 0}
    monkeypatch.setattr(
        ctx.homewindow, '_one_catalog_page',
        lambda *args, **kwargs: [{'id': 'm1', 'name': 'M', 'type': 'movie', 'poster': 'p', 'posterShape': 'poster'}],
    )
    ctx.hubwindow._load_posters(poster_desc)
    assert not poster_desc.get('layout')
