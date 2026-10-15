# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""HubWindow: one poster row per catalog, exercised against the kodistubs."""
import contextlib

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


def test_catalog_rows_skip_search_and_pin_the_first_genre(load_hub, monkeypatch):
    ctx = load_hub()
    seen = []

    def _page(transport, manifest, catalog, extra=None):
        seen.append((catalog.get('id'), extra))
        return [{'id': catalog.get('id'), 'name': catalog.get('name'), 'type': 'movie', 'poster': 'p'}]

    monkeypatch.setattr(ctx.homewindow, '_one_catalog_page', _page)

    rows = ctx.hubwindow._catalog_rows(_addons(), frozenset({'movie'}), 8)

    assert [heading for heading, _items in rows] == ['Top', 'Year']
    assert seen == [('top', None), ('year', [('genre', '2024')])]
    assert rows[0][1][0].getProperty('sid') == 'top'


def test_catalog_rows_drop_past_the_skin_cap(load_hub, monkeypatch):
    ctx = load_hub()
    catalogs = [
        {'type': 'movie', 'id': 'c%d' % index, 'name': 'C%d' % index}
        for index in range(10)
    ]
    addons = [{'transportUrl': 'https://a/manifest.json', 'manifest': {'catalogs': catalogs}}]
    monkeypatch.setattr(
        ctx.homewindow, '_one_catalog_page',
        lambda transport, manifest, catalog, extra=None: [
            {'id': catalog.get('id'), 'name': catalog.get('name'), 'type': 'movie'},
        ],
    )

    rows = ctx.hubwindow._catalog_rows(addons, frozenset({'movie'}), len(ctx.hubwindow.HUB_ROWS))

    assert len(rows) == len(ctx.hubwindow.HUB_ROWS)


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

    rows, episodes = ctx.hubwindow._build_rows(
        _Store(), addons, frozenset({'series', 'tv'}),
    )

    assert episodes[0]['video_id'] == 'show:1:2'
    assert rows[0][1][0].getProperty('episode_index') == '0'
    assert rows[0][1][0].getProperty('sid') == 'show'
    assert len(rows) == 2


def test_clicking_the_first_new_episode_marks_it_seen(load_hub, monkeypatch):
    ctx = load_hub()
    marked = []
    opened = []
    monkeypatch.setattr(ctx.catalogpicker, '_mark_episode_seen', lambda episode: marked.append(episode))
    monkeypatch.setattr(
        ctx.detailwindow, 'open_detail',
        lambda ctype, sid: opened.append((ctype, sid)) or True,
    )
    import xbmcgui
    win = ctx.hubwindow.HubWindow('HubWindow.xml', '/addon/path', 'Default', '1080i')
    episode = {'type': 'series', 'id': 'show', 'video_id': 'show:1:2'}
    win._episodes = [episode]
    item = xbmcgui.ListItem('Show')
    item.setProperty('episode_index', '0')
    item.setProperty('sid', 'show')
    item.setProperty('stype', 'series')
    win.getControl(ctx.hubwindow.HUB_ROWS[0][0]).addItems([item])

    win.onClick(ctx.hubwindow.HUB_ROWS[0][0])

    assert marked == [episode]
    assert opened == [('series', 'show')]
    assert win.should_close_caller is True
    assert win.closed is True


def test_empty_hub_closes_and_notifies(load_hub, monkeypatch):
    ctx = load_hub()
    monkeypatch.setattr(ctx.hubwindow, 'get_store', lambda: _Store(addons=[]))
    monkeypatch.setattr(ctx.hubwindow, '_build_rows', lambda store, addons, types: ([], []))
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
    panels = [
        control for control in tree.iter('control')
        if control.get('type') == 'panel' and control.get('id')
    ]
    assert len(panels) == 8
    for panel in panels:
        blob = ET.tostring(panel.find('focusedlayout'), encoding='unicode')
        assert 'FFFFFFFF' in blob
        assert panel.find('onleft') is not None
        assert panel.find('onright') is not None
