"""Home owns its workers until close, independently of SWIG window lifetime."""
import threading
import time

import pytest

from lib import homelayout
from tests.kodistubs import install_kodi_stubs
from tests.test_newhome import _RELOAD_MODULE_NAMES, _FakeStore
from tests.test_newhome_tabs import build, metas


@pytest.fixture
def session(monkeypatch):
    shared = ('lib.ui.logocheck', 'lib.ui.ratingsched', 'lib.ui.posterwarm')
    with install_kodi_stubs(reload=_RELOAD_MODULE_NAMES + shared) as ctx:
        monkeypatch.setattr(ctx.logocheck, 'fetch_is_image', lambda url: False)
        win = ctx.newhome.NewHomeWindow('NewHomeWindow.xml', '/addon/path', 'Default', '1080i')
        ctx.window = win
        before = set(threading.enumerate())
        yield ctx
        win.close()
        for worker in set(threading.enumerate()) - before:
            if worker.name.startswith('rivulet-'):
                worker.join(1)
                assert not worker.is_alive(), worker.name


def workers_since(before):
    return [t for t in threading.enumerate() if t not in before and t.name.startswith('rivulet-')]


def join_promptly(workers):
    deadline = time.monotonic() + 1
    for worker in workers:
        worker.join(max(0, deadline - time.monotonic()))
    assert not [worker.name for worker in workers if worker.is_alive()]


@pytest.mark.parametrize('abort', [False, True])
def test_all_idle_home_workers_stop_while_window_is_still_referenced(session, monkeypatch, tmp_path, abort):
    ctx, win = session, session.window
    hw = ctx.newhome
    monkeypatch.setattr(hw, '_fetch_library_meta', lambda *_: None)
    before = set(threading.enumerate())
    item = hw._poster_item({'id': 'tt1', 'type': 'movie'}, sparse=True)
    hw._schedule_library_meta(win, item)
    hw._join_library_meta(win)
    # Exercise real shared workers as well as the window's metadata worker.
    warmed = threading.Event()
    original_slots = ctx.posterwarm._slots
    monkeypatch.setattr(ctx.posterwarm, '_slots', lambda window: warmed.set() or original_slots(window))
    ctx.posterwarm.request_warm(win, ['p%d' % i for i in range(90)])
    assert warmed.wait(0.5)
    from lib.stremio.ratings import RatingsCache
    monkeypatch.setattr(ctx.ratingsched, '_DWELL_SECONDS', 60)
    ctx.ratingsched._schedule('tt0000001', 'key', '', RatingsCache(str(tmp_path / 'ratings.json')))
    logo_done = threading.Event()
    monkeypatch.setattr(ctx.logocheck, 'fetch_is_image', lambda _: logo_done.set() or False)
    ctx.logocheck.ask(['logo'])
    assert logo_done.wait(0.5)
    workers = workers_since(before)
    assert {'rivulet-library-meta', 'rivulet-poster-warm', 'rivulet-ratings', 'rivulet-logocheck'} <= {t.name for t in workers}
    if abort:
        ctx.env.monitor_abort_requested = True
    else:
        win.close()
    join_promptly(workers)
    assert win is ctx.window  # A strong reference survives, just as in Kodi.
    assert not win._library_meta_running
    assert all(win.getControl(slot).image == '' for slot in ctx.posterwarm.WARM_SLOTS)


@pytest.mark.parametrize('abort', [False, True])
def test_close_drops_queued_and_late_meta_and_can_reopen_for_playback(session, monkeypatch, abort):
    ctx, win = session, session.window
    hw = ctx.newhome
    entered, release = threading.Event(), threading.Event()
    fetched = []

    def fetch(_type, sid, stop=None):
        fetched.append(sid)
        entered.set()
        assert release.wait(1)
        return {'id': sid, 'description': 'late'}

    monkeypatch.setattr(hw, '_fetch_library_meta', fetch)
    first = hw._poster_item({'id': 'tt1', 'type': 'movie'}, sparse=True)
    second = hw._poster_item({'id': 'tt2', 'type': 'movie'}, sparse=True)
    hw._schedule_library_meta(win, first)
    assert entered.wait(0.5)
    worker = win._library_meta_thread
    hw._schedule_library_meta(win, second)
    if abort:
        ctx.env.monitor_abort_requested = True
    else:
        win.close()
    pokes = len(ctx.env.executed_builtins)
    release.set()
    join_promptly([worker])
    assert fetched == ['tt1']
    assert not win._library_meta_ready
    assert len(ctx.env.executed_builtins) == pokes
    ctx.env.monitor_abort_requested = False
    win.close()
    monkeypatch.setattr(win, '_build', lambda: None)
    win.onInit()
    hw._schedule_library_meta(win, second)
    hw._join_library_meta(win)
    assert win._library_meta_thread is not worker
    assert fetched == ['tt1', 'tt2']
    win.close()
    join_promptly([win._library_meta_thread])


def test_playback_reopen_hands_pending_meta_to_a_new_session(session, monkeypatch):
    ctx, win = session, session.window
    hw = ctx.newhome
    entered, release = threading.Event(), threading.Event()
    fetched = []

    def fetch(_type, sid, stop=None):
        fetched.append(sid)
        entered.set()
        assert release.wait(1)
        return {'id': sid}

    monkeypatch.setattr(hw, '_fetch_library_meta', fetch)
    item = hw._poster_item({'id': 'tt1', 'type': 'movie'}, sparse=True)
    hw._schedule_library_meta(win, item)
    assert entered.wait(0.5)
    old_worker = win._library_meta_thread
    win.close()
    monkeypatch.setattr(win, '_build', lambda: None)
    win.onInit()
    hw._schedule_library_meta(win, item)
    release.set()
    join_promptly([old_worker])
    hw._join_library_meta(win)
    assert fetched == ['tt1', 'tt1']
    assert win._library_meta_ready == [('movie', 'tt1', {'id': 'tt1'})]
    win.close()
    join_promptly([win._library_meta_thread])


@pytest.mark.parametrize('abort', [False, True])
def test_page_workers_stop_before_another_page_and_discard_late_results(session, monkeypatch, abort):
    ctx = session
    hw = ctx.newhome
    win, _, _ = build(ctx, monkeypatch)
    ctx.window.close()
    ctx.window = win
    from lib.ui import catalogpages, views
    catalogpages.clear_later_pages()
    state = win._rows[30041]
    state.update(pending=[], served=24, filter='series', exhausted=False)
    entered, release = threading.Event(), threading.Event()
    fetched = []

    def fetch(*args, extra=None):
        fetched.append(dict(extra)['skip'])
        entered.set()
        assert release.wait(1)
        return metas(24, 24)  # No series: normally another page is fetched.

    monkeypatch.setattr(views, '_fetch_catalog', fetch)
    hw._schedule_shelf_extend(win, 30041, 24)
    assert entered.wait(0.5)
    workers = list(win._shelf_threads)
    if abort:
        ctx.env.monitor_abort_requested = True
    else:
        win.close()
    release.set()
    join_promptly(workers)
    assert fetched == [24]
    assert not win._shelf_ready
    assert state['served'] == 24
    assert win._shelf_running == 0
    win.close()


@pytest.mark.parametrize('mode', ['close', 'abort', 'cancel'])
def test_first_load_collects_with_timed_waits_and_stops_queued_rows(session, monkeypatch, mode):
    ctx, win = session, session.window
    hw = ctx.newhome
    installed = [{'transportUrl': 't', 'manifest': {'catalogs': [
        {'type': 'movie', 'id': 'c%d' % n} for n in range(10)]}}]
    store = _FakeStore(addons=installed)
    win._active_tab = 'home'
    win._layout = homelayout.default_layout()
    win._layout['tabs']['home'] = ['rest:movie']
    win._catalogs = homelayout.installed_catalogs(installed)
    entered = threading.Barrier(5)
    release = threading.Event()
    fetched = []
    collectors = []
    before = set(threading.enumerate())

    def fetch(descriptor):
        fetched.append(descriptor['catalog']['id'])
        entered.wait(1)
        assert release.wait(1)
        return {'metas': metas(), 'exhausted': True}

    def cancellable(load, _label):
        collector = threading.Thread(target=load, name='test-home-collector')
        collectors.append(collector)
        collector.start()
        entered.wait(1)
        if mode == 'close':
            win.close()
        elif mode == 'abort':
            ctx.env.monitor_abort_requested = True
        return ctx.uicommon.CANCELLED

    monkeypatch.setattr(hw, '_open_shelf', fetch)
    monkeypatch.setattr(ctx.uicommon, 'run_cancellable', cancellable)
    assert hw._load_rows(win, store, installed, None) == []
    workers = workers_since(before)
    assert len(workers) == 4
    # Collector must return even while in-flight calls haven't completed.
    join_promptly(collectors)
    release.set()
    join_promptly(workers)
    assert len(fetched) == 4
    win.close()


def test_first_load_cannot_wait_forever_if_a_worker_exits_without_a_result(session, monkeypatch):
    ctx, win = session, session.window
    hw = ctx.newhome
    win._active_tab = 'home'
    win._layout = homelayout.default_layout()
    win._catalogs = homelayout.installed_catalogs([{'transportUrl': 't', 'manifest': {
        'catalogs': [{'id': 'c', 'type': 'movie'}]}}])
    # Simulate a dead worker without producing an unhandled-thread warning.
    class DeadWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return False

    monkeypatch.setattr(hw.threading, 'Thread', DeadWorker)
    monkeypatch.setattr(ctx.uicommon, 'run_cancellable', lambda load, _: load())
    start = time.monotonic()
    rows = hw._load_rows(win, _FakeStore(), [], None)
    assert time.monotonic() - start < 1
    assert rows[-1]['metas'] == []


def test_home_meta_fanout_cancels_its_collector_and_queued_addon_lookups(session, monkeypatch):
    ctx, win = session, session.window
    installed = [{'transportUrl': str(n), 'manifest': {'types': ['movie'], 'resources': ['meta']}}
                 for n in range(20)]
    store = _FakeStore(addons=installed)
    monkeypatch.setattr(ctx.views, 'get_store', lambda: store)
    entered = threading.Barrier(9)
    release = threading.Event()
    fetched = []

    class Client:
        def meta(self, transport, *_):
            fetched.append(transport)
            entered.wait(1)
            assert release.wait(1)
            return None

    monkeypatch.setattr(ctx.views, 'get_client', Client)
    before = set(threading.enumerate())
    item = ctx.newhome._poster_item({'id': 'tt1', 'type': 'movie'}, sparse=True)
    ctx.newhome._schedule_library_meta(win, item)
    entered.wait(1)
    worker = win._library_meta_thread
    win.close()
    join_promptly([worker])  # The collector exits while HTTP is still blocked.
    assert not win._library_meta_ready
    release.set()
    join_promptly(list(set(threading.enumerate()) - before))
    assert len(fetched) == 8  # Twelve queued addon calls were never started.
    assert ctx.newhome._fetch_library_meta('movie', 'tt1', win._home_stop) is None


def test_close_during_first_page_prevents_filtered_followup_pages(session, monkeypatch):
    ctx, win = session, session.window
    descriptor = homelayout.installed_catalogs([{'transportUrl': 't', 'manifest': {'catalogs': [
        {'id': 'anime', 'type': 'anime', 'extra': [{'name': 'skip'}]}]}}])[0]

    def first(*args):
        win.close()
        return metas(stype='series')

    monkeypatch.setattr(ctx.newhome, '_one_catalog_page', first)
    monkeypatch.setattr(ctx.newhome, '_shelf_page_gen', lambda _: pytest.fail('fetch after close'))
    state = ctx.newhome._open_shelf(dict(descriptor, _stop=ctx.newhome._home_stop(win)))
    assert state['metas'] == []
