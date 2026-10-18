"""The Fuse search screen (lib/ui/fusesearch.py)."""
import contextlib

import pytest

from tests.kodistubs import install_kodi_stubs

_RELOAD = (
    'lib.ui.compat', 'lib.ui.uicommon', 'lib.ui.fuse', 'lib.ui.homewindow', 'lib.ui.infowindow',
    'lib.ui.searchwindow', 'lib.ui.fusesearch', 'lib.ui.detailwindow', 'lib.ui.dependencies',
)


@pytest.fixture
def load():
    with contextlib.ExitStack() as stack:
        def _load(settings=None):
            return stack.enter_context(install_kodi_stubs(reload=_RELOAD, settings=settings))
        yield _load


def _window(ctx):
    win = ctx.fusesearch.FuseSearchWindow('FuseSearchWindow.xml', '/addon/path', 'Default', '1080i')
    win._skin_xml = 'FuseSearchWindow.xml'
    win._load_discover = lambda: None
    return win


def test_the_letters_are_the_alphabet_space_and_delete(load):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    labels = [item.getLabel() for item in win.getControl(ctx.fusesearch.LETTERS).items]
    assert labels[:3] == ['A', 'B', 'C'] and labels[-2:] == ['_', '<'] and len(labels) == 28
    assert win.getProperty('HeroLogo') == ''
    assert win.getControl(ctx.homewindow.HERO_TITLE).label == '[B]STR30508[/B]'


def _searching(ctx, monkeypatch, answer, failures=(), canceled=False, total=1):
    import lib.ui.dependencies as dependencies
    import lib.ui.searchwindow as sw

    asked = []

    def _run_query(store, client, query, report=None, **kwargs):
        asked.append(query)
        report.total_catalogs = total
        report.queried = total
        report.failures = list(failures)
        report.canceled = canceled
        return list(answer)

    monkeypatch.setattr(sw, 'run_query', _run_query)
    monkeypatch.setattr(dependencies, 'get_store', lambda: object())
    monkeypatch.setattr(dependencies, 'get_client', lambda: object())
    return asked


def test_picking_letters_fills_the_bar_and_does_not_search(load, monkeypatch):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    asked = _searching(ctx, monkeypatch, [])
    for key in ('A', 'N', 'D', 'O', 'R'):
        win._key(key)
    assert win.query == 'Andor'
    assert win.getControl(ctx.fusesearch.QUERY).label == 'Andor[COLOR 8007090B]|[/COLOR]'
    assert asked == []
    win._key('<')
    win._key(' ')
    win._key(' ')
    assert win.query == 'Ando '


def test_the_search_pill_searches_and_moves_to_the_results(load, monkeypatch):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    asked = _searching(ctx, monkeypatch, [{'id': 'tt9253284', 'type': 'series', 'name': 'Andor', 'description': 'A rebel.'}])
    win.query = 'Andor'
    win.onClick(ctx.fusesearch.GO)
    assert asked == ['Andor']
    row = win.getControl(ctx.fusesearch.ROW)
    assert [item.getLabel() for item in row.items] == ['Andor']
    assert win.getControl(ctx.fusesearch.ROW_HEADING).label == '[B]STR30507[/B]'
    assert win.getControl(ctx.homewindow.HERO_PLOT).text == 'A rebel.'
    assert win.getFocusId() == ctx.fusesearch.ROW
    assert win.getControl(ctx.fusesearch.STATUS).label == ''
    # Discover arriving late does not replace the results.
    win._post(('discover', '', [{'id': 'tt1', 'name': 'Popular'}]))
    win._apply_ready()
    assert [item.getLabel() for item in row.items] == ['Andor']


def test_no_results_is_said_under_the_pills(load, monkeypatch):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    _searching(ctx, monkeypatch, [])
    win.query = 'Zzzz'
    win._go()
    assert win.getControl(ctx.fusesearch.STATUS).label == 'STR30513 Zzzz'
    assert win.getFocusId() != ctx.fusesearch.ROW


def test_every_catalog_failing_is_said_not_no_results(load, monkeypatch):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    _searching(ctx, monkeypatch, [], failures=[('Cinemeta', 'timeout')])
    win.query = 'Andor'
    win._go()
    assert win.getControl(ctx.fusesearch.STATUS).label == 'STR30382'


def test_back_on_the_spinner_leaves_the_row_alone(load, monkeypatch):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    win._post(('discover', '', [{'id': 'tt1', 'name': 'Popular'}]))
    win._apply_ready()
    _searching(ctx, monkeypatch, [], canceled=True)
    win.query = 'Andor'
    win._go()
    row = win.getControl(ctx.fusesearch.ROW)
    assert [item.getLabel() for item in row.items] == ['Popular']
    assert win.getControl(ctx.fusesearch.STATUS).label == ''


def test_discover_fills_the_row_until_two_letters_are_picked(load):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    win._post(('discover', '', [{'id': 'tt9', 'name': 'Popular'}]))
    win._apply_ready()
    assert win.getControl(ctx.fusesearch.ROW_HEADING).label == '[B]STR30506[/B]'
    assert win.getProperty('SearchHasRow') == '1'


def test_the_search_skin_has_the_pill_and_the_status_line():
    import os
    import xml.etree.ElementTree as ET

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tree = ET.parse(os.path.join(root, 'resources', 'skins', 'Default', '1080i', 'FuseSearchWindow.xml'))
    ids = {el.get('id') for el in tree.iter('control')}
    assert {'30204', '30205', '30203', '30202'} <= ids
    letters = [el for el in tree.iter('control') if el.get('id') == '30202'][0]
    assert letters.find('onup').text == '30204'


def test_ok_on_a_result_opens_it_and_saves_the_query(load, monkeypatch):
    ctx = load()
    win = _window(ctx)
    win.onInit()
    win.query = 'Dune'
    win._metas = [{'id': 'tt1', 'type': 'movie', 'name': 'Dune'}]
    win._show(win._metas, results=True)
    saved = []

    class _Store:
        def add_search_query(self, q):
            saved.append(q)

    import lib.ui.dependencies as dependencies
    monkeypatch.setattr(dependencies, 'get_store', lambda: _Store())
    opened = []
    import lib.ui.detailwindow as detailwindow
    monkeypatch.setattr(detailwindow, 'open_detail', lambda stype, sid: opened.append((stype, sid)) or False)
    win.setFocusId(ctx.fusesearch.ROW)
    win.onClick(ctx.fusesearch.ROW)
    assert opened == [('movie', 'tt1')] and saved == ['Dune']


def test_search_opens_the_fuse_screen_when_the_look_is_on(load, monkeypatch):
    ctx = load(settings={'ui_fuse': 'true'})
    import lib.ui.fusesearch as fusesearch
    monkeypatch.setattr(fusesearch, 'open_search', lambda: 'fuse')
    assert ctx.searchwindow.open_search() == 'fuse'


def test_a_quiet_search_shows_no_spinner(load, monkeypatch):
    ctx = load()
    sw = ctx.searchwindow

    def _no_dialog(*a, **k):
        raise AssertionError('busy dialog opened')

    monkeypatch.setattr(sw, 'busy_dialog', _no_dialog)
    monkeypatch.setattr(sw, '_search_catalogs', lambda store: [('https://a', {'name': 'A'}, {'id': 'c', 'type': 'movie'})])
    monkeypatch.setattr(sw, '_start_search_workers', lambda client, query, jobs: None)
    monkeypatch.setattr(sw, '_collect_answers', lambda dialog, results, jobs, report: {0: ([{'id': 'tt1', 'name': 'Dune', 'type': 'movie'}], None)})

    class _Loader:
        def __init__(self, store, client):
            pass

        def wait(self, dialog):
            return None

    monkeypatch.setattr(sw, '_FeedIndexLoader', _Loader)
    import threading
    metas = sw.run_query(object(), object(), 'dune', report=sw.SearchReport(), quiet=True, cancel=threading.Event())
    assert [m['id'] for m in metas] == ['tt1']


def test_the_search_skin_names_only_shipped_textures():
    import os
    import xml.etree.ElementTree as ET

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skin = os.path.join(root_dir, 'resources', 'skins', 'Default', '1080i', 'FuseSearchWindow.xml')
    media = os.path.join(root_dir, 'resources', 'skins', 'Default', 'media')
    root = ET.parse(skin).getroot()
    ids = {int(c.get('id')) for c in root.iter('control') if c.get('id')}
    assert {30201, 30202, 30203, 30215, 30140, 30020, 30022, 30023, 30024, 30025, 30027, 30000} <= ids
    for node in root.iter():
        if node.tag in ('texture', 'texturefocus', 'texturenofocus'):
            value = (node.text or '').strip()
            if value and not value.startswith('$'):
                assert os.path.isfile(os.path.join(media, value)), value
