"""lib/ui/newhome.py: how the New look Home builds its rows.

The row helpers on their own, against the kodistubs fakes: what a row
shows when the account or an addon fails, how a row grows past its
first page, and which library records count as "in progress".
"""
import contextlib

import pytest

from tests.kodistubs import install_kodi_stubs
from tests.test_newhome import _RELOAD_MODULE_NAMES


@pytest.fixture
def home():
    with contextlib.ExitStack() as stack:
        ctx = stack.enter_context(install_kodi_stubs(reload=_RELOAD_MODULE_NAMES))
        ctx.home = ctx.newhome
        yield ctx


# --- text --------------------------------------------------------------------------


def test_truncate_keeps_short_text_and_ends_long_text_with_an_ellipsis(home):
    t = home.home._truncate
    assert t('  short  ', 10) == 'short'
    assert t(None, 10) == ''
    assert t('a long title here', 8) == 'a long…'


@pytest.mark.parametrize('runtime, text', [
    ('  155 min ', '155 min'), (98, '98 min'), (98.7, '98 min'), (0, ''), (-5, ''), (True, ''), (None, ''), ([], ''),
])
def test_runtime_text(home, runtime, text):
    assert home.home._runtime_text({'runtime': runtime}) == text


# --- a catalog's first page --------------------------------------------------------


def test_a_failing_addon_is_logged_and_raised_as_unavailable(home, monkeypatch):
    import lib.ui.catalogpages as catalogpages
    from lib.stremio.addons import AddonError

    def _addon_error(*args):
        raise AddonError('https://addon.example/catalog?token=SECRET failed')

    monkeypatch.setattr(catalogpages, 'cached_first_page', _addon_error)
    with pytest.raises(home.home.CatalogUnavailable) as caught:
        home.home._one_catalog_page('https://addon.example/manifest.json', {}, {'id': 'top'})
    assert str(caught.value) == 'top'

    def _bug(*args):
        raise KeyError('metas')

    monkeypatch.setattr(catalogpages, 'cached_first_page', _bug)
    with pytest.raises(home.home.CatalogUnavailable):
        home.home._one_catalog_page('https://addon.example/manifest.json', {}, 'not a catalog')
    logged = [msg for msg, _level in home.env.log_calls if 'home: catalog' in msg]
    assert len(logged) == 2
    # The addon's own detail is logged, never its URL's token.
    assert not any('SECRET' in msg for msg in logged)


def test_a_catalog_page_is_returned_whole(home, monkeypatch):
    import lib.ui.catalogpages as catalogpages

    page = [{'id': 'tt%d' % n} for n in range(40)]
    monkeypatch.setattr(catalogpages, 'cached_first_page', lambda *args: page)
    assert home.home._one_catalog_page('t', {}, {'id': 'top'}) is page


# --- growing a row -------------------------------------------------------------------


def test_no_generator_without_a_catalog(home):
    gen = home.home._shelf_page_gen
    assert gen(None) is None
    assert gen({'transport': '', 'catalog': {'id': 'x'}}) is None
    assert gen({'transport': 't', 'catalog': None}) is None


def test_the_generator_is_made_once_and_skips_page_one(home, monkeypatch):
    import lib.ui.views as views

    made = []

    def _after(transport, stype, cid, skip, seen, extra=None, catalog=None, manifest=None):
        made.append((stype, cid, skip, seen, extra))
        return iter([])

    monkeypatch.setattr(views, 'iter_catalog_pages_after', _after)
    state = {
        'transport': 't', 'catalog': {'type': 'movie', 'id': 'top'}, 'extra': {'genre': 'Drama'},
        'metas': [{'id': 'tt1'}, 'junk', {'id': 'tt2'}],
    }
    gen = home.home._shelf_page_gen(state)
    assert home.home._shelf_page_gen(state) is gen
    assert made == [('movie', 'top', 2, ['tt1', 'tt2'], {'genre': 'Drama'})]


def test_leftovers_come_before_the_network(home, monkeypatch):
    def _never(state):
        raise AssertionError('no fetch while leftovers remain')

    monkeypatch.setattr(home.home, '_shelf_page_gen', _never)
    state = {'pending': [{'id': 'tt%d' % n} for n in range(5)]}
    assert [m['id'] for m in home.home._pull_more(state, 3)] == ['tt0', 'tt1', 'tt2']
    assert [m['id'] for m in state['pending']] == ['tt3', 'tt4']


@pytest.mark.parametrize('state, room', [(None, 5), ({}, 0), ({'exhausted': True, 'pending': [{'id': 'x'}]}, 5)])
def test_nothing_more_when_there_is_no_room_or_the_row_ended(home, state, room):
    assert home.home._pull_more(state, room) == []


def test_a_row_without_a_catalog_ends(home):
    state = {'pending': []}
    assert home.home._pull_more(state, 5) == []
    assert state['exhausted'] is True


def _with_pages(home, monkeypatch, pages):
    def _gen():
        for page in pages:
            if isinstance(page, BaseException):
                raise page
            yield page

    gen = _gen()
    monkeypatch.setattr(home.home, '_shelf_page_gen', lambda state: gen)


def test_the_next_page_is_fetched_once_the_leftovers_are_gone(home, monkeypatch):
    _with_pages(home, monkeypatch, [[{'id': 'tt5'}, 'junk', {'id': 'tt6'}, {'id': 'tt7'}]])
    state = {'pending': []}
    assert [m['id'] for m in home.home._pull_more(state, 2)] == ['tt5', 'tt6']
    assert [m['id'] for m in state['pending']] == ['tt7']
    assert not state.get('exhausted')


@pytest.mark.parametrize('pages', [[], [[]], [['junk', None]], [RuntimeError('addon down')]])
def test_an_empty_or_failed_page_ends_the_row(home, monkeypatch, pages):
    _with_pages(home, monkeypatch, pages)
    state = {'pending': []}
    assert home.home._pull_more(state, 5) == []
    assert state['exhausted'] is True


def test_a_test_assertion_inside_the_fetch_is_not_swallowed(home, monkeypatch):
    _with_pages(home, monkeypatch, [AssertionError('bug')])
    with pytest.raises(AssertionError):
        home.home._pull_more({'pending': []}, 5)


# --- Continue from the account --------------------------------------------------------


@pytest.mark.parametrize('entry, percent', [
    ({'state': {'timeOffset': 30, 'duration': 120}}, 25.0),
    ({'state': {'timeOffset': 0, 'duration': 120}}, 0.0),
    ({'state': {'timeOffset': 30, 'duration': 0}}, None),
    ({'state': {'timeOffset': 30, 'duration': True}}, None),
    ({'state': {'timeOffset': '30', 'duration': 120}}, None),
    ({'state': {'timeOffset': True, 'duration': 120}}, None),
    ({'state': {'timeOffset': 30, 'duration': '120'}}, None),
    ({'state': 'junk'}, None),
    ('junk', None),
])
def test_state_percent(home, entry, percent):
    assert home.home._state_percent(entry) == percent


def _entry(**overrides):
    entry = {
        '_id': 'tt1', 'name': 'One', 'type': 'movie', 'poster': 'p', 'background': 'b',
        'state': {'timeOffset': 600000, 'duration': 6000000, 'video_id': 'tt1'},
    }
    entry.update(overrides)
    return entry


def test_titles_part_way_through_on_the_account_are_continued(home):
    metas = home.home._library_continue_metas([
        _entry(),
        _entry(_id='tt2', removed=True, temp=True),            # played, not added: still Continue
        _entry(_id='tt3', removed=True),                       # removed by the viewer
        _entry(_id='tt4', state={'timeOffset': 1, 'duration': 6000000}),       # barely started
        _entry(_id='tt5', state={'timeOffset': 5900000, 'duration': 6000000}),  # finished
        _entry(_id='', name='No id'),
        _entry(_id='tt6', name='', poster=''),
        'junk',
    ])
    assert [meta['id'] for meta in metas] == ['tt1', 'tt2']
    first = metas[0]
    assert first['band'] == 'resume'
    assert first['position_ms'] == 600000 and first['duration_ms'] == 6000000
    assert first['video_id'] == 'tt1'
    assert home.home._library_continue_metas(None) == []


def test_a_continue_row_without_a_video_id_resumes_the_title(home):
    entry = _entry()
    del entry['state']['video_id']
    assert home.home._library_continue_metas([entry])[0]['video_id'] is None


def test_library_is_read_newest_first(home):
    rows = home.home._newest_first([
        {'_id': 'a', '_ctime': '2026-01-01'},
        'junk',
        {'_id': 'b', '_mtime': '2026-03-01'},
        {'_id': 'c'},
        {'_id': 'd', '_ctime': '2026-02-01', '_mtime': '2026-09-01'},
    ])
    assert [row['_id'] for row in rows] == ['b', 'd', 'a', 'c']
    assert home.home._newest_first(None) == []


# --- the account read ------------------------------------------------------------------


def test_signed_out_reads_no_library(home, monkeypatch):
    import lib.ui.mystuff as mystuff

    monkeypatch.setattr(mystuff, '_fetch_library_entries', lambda store: pytest.fail('not asked'))
    assert home.home._fetch_library(object(), None) == []


def test_a_library_read_that_breaks_leaves_the_rows_empty(home, monkeypatch):
    import lib.ui.mystuff as mystuff

    def _boom(store):
        raise RuntimeError('store gone')

    monkeypatch.setattr(mystuff, '_fetch_library_entries', _boom)
    assert home.home._fetch_library(object(), {'authKey': 'k'}) == []
    monkeypatch.setattr(mystuff, '_fetch_library_entries', lambda store: [])
    monkeypatch.setattr(mystuff, 'apply_library_writes', lambda rows: 'junk')
    assert home.home._fetch_library(object(), {'authKey': 'k'}) == []


def test_a_pending_write_shows_on_the_library_read(home, monkeypatch):
    import lib.ui.mystuff as mystuff

    mystuff.clear_library_writes()
    monkeypatch.setattr(mystuff, '_fetch_library_entries', lambda store: [{'_id': 'tt1', '_ctime': '2020'}])
    mystuff.note_library_write({'_id': 'tt9', 'removed': False, '_ctime': '2026', '_mtime': '2026'})
    try:
        rows = home.home._fetch_library(object(), {'authKey': 'k'})
    finally:
        mystuff.clear_library_writes()
    assert sorted(row['_id'] for row in rows) == ['tt1', 'tt9']


def test_the_library_row_signed_out_is_one_sign_in_cell(home):
    items = home.home._library_posters(None, [])
    assert len(items) == 1
    assert items[0].getProperty('action') == 'signin'
    assert items[0].getLabel() == 'STR30427'


def test_an_empty_or_unreadable_library_shows_the_notice(home, monkeypatch):
    import lib.ui.mystuff as mystuff

    items = home.home._library_posters({'authKey': 'k'}, [])
    assert [item.getLabel() for item in items] == ['STR30426']

    def _boom(entries):
        raise ValueError('odd record')

    monkeypatch.setattr(mystuff, 'library_metas', _boom)
    items = home.home._library_posters({'authKey': 'k'}, [{'_id': 'tt1', 'name': 'One'}])
    assert [item.getLabel() for item in items] == ['STR30426']


def test_the_library_row_is_not_capped(home):
    entries = [{'_id': 'tt%07d' % n, 'name': 'T%d' % n, 'type': 'movie', '_ctime': '2026-01-%02d' % (n % 28 + 1)}
               for n in range(home.home.SHELF_CAP + 6)]
    items = home.home._library_posters({'authKey': 'k'}, entries)
    assert len(items) == home.home.SHELF_CAP + 6


# --- the first screen of every row ------------------------------------------------------


def test_a_shelf_that_fails_is_an_empty_row_and_the_rest_still_load(home, monkeypatch):
    def _open(addons, types):
        if 'series' in types:
            raise RuntimeError('addon down')
        if 'tv' in types:
            return None
        return {'metas': [{'id': 'tt%d' % n} for n in range(40)]}

    monkeypatch.setattr(home.home, '_open_shelf', _open)
    pages, more = home.home._catalog_pages([], {'movies': {'movie'}, 'series': {'series'}, 'tv': {'tv'}})
    assert len(pages['movies']) == home.home._ROW_INITIAL
    assert len(more['movies']['metas']) == 40
    assert pages['series'] == [] and more['series'] is None
    assert pages['tv'] == [] and more['tv'] is None


def test_one_shelf_is_fetched_without_a_pool(home, monkeypatch):
    import threading

    threads = []
    monkeypatch.setattr(home.home, '_open_shelf', lambda addons, types: threads.append(threading.current_thread()) or None)
    pages, more = home.home._catalog_pages([], {'movies': {'movie'}})
    assert threads == [threading.current_thread()]
    assert pages == {'movies': []} and more == {'movies': None}


def test_back_on_the_home_spinner_paints_empty_rows(home, monkeypatch):
    import lib.ui.uicommon as uicommon

    monkeypatch.setattr(home.home, '_enabled_shelf_types', lambda addons: {'movies': {'movie'}})
    monkeypatch.setattr(uicommon, 'run_cancellable', lambda func, heading, message='': uicommon.CANCELLED)

    class _Win:
        pass

    win = _Win()
    assert home.home._load_rows(win, object(), [], {'authKey': 'k'}) == ([], [], {}, {'movies': {'movie'}})
    # Nothing was kept, so the next paint asks again.
    assert not hasattr(win, '_catalog_pages')
