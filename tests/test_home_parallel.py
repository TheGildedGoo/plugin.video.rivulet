"""Continue metadata shares startup time, with a hard budget and idle workers."""
import threading
import time

import pytest

from tests.test_home_shutdown import session as session
from tests.test_home_startup import prepare
from tests.test_newhome import load_homewindow as load_homewindow
from tests.test_newhome_tabs import metas


def continue_plan(ctx, monkeypatch, count=3):
    win, store = prepare(ctx, monkeypatch)
    layout = store.get_home_layout()
    layout['tabs']['home'].insert(0, 'continue')
    store._progress_entries = [{'type': 'movie', 'id': 'tt%d' % n, 'position_ms': 60000,
                                'duration_ms': 120000, 'updated_at': '2026-10-21T00:00:00Z'}
                               for n in range(count)]
    monkeypatch.setattr(ctx.mystuff, 'get_store', lambda: store)
    return win, store


def test_three_ten_second_lookups_cannot_hold_startup_and_retry_next_load(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    hw = ctx.newhome
    win, store = continue_plan(ctx, monkeypatch)
    release = threading.Event()
    started = threading.Barrier(4)
    calls = []
    before = set(threading.enumerate())

    def fetch(stype, sid, should_stop, **kw):
        calls.append(sid)
        if not release.is_set():
            started.wait(1)
            assert release.wait(10)
        return {'id': sid, 'name': 'too late', 'poster': 'late'}

    monkeypatch.setattr(ctx.views, '_fetch_meta_for_home', fetch)
    begin = time.monotonic()
    collector = threading.Thread(target=win.onInit)
    collector.start()
    try:
        started.wait(1)
        collector.join(2.5)
        assert not collector.is_alive()
        assert time.monotonic() - begin < 2.5
        assert win.getControl(hw.CONTINUE_SHELF).size() == 0
        assert hw._continue_meta_misses == set()
        release.set()
        for worker in set(threading.enumerate()) - before:
            if worker is not collector:
                worker.join(1)
        rows = hw._load_rows(win, store, store.get_enabled_addons(), None)
        assert len(rows[0]['items']) == 3 and len(calls) == 6
    finally:
        release.set()
        collector.join(1)
        for worker in set(threading.enumerate()) - before:
            worker.join(1)
    assert win.getControl(hw.CONTINUE_SHELF).size() == 0
    win.close()


def test_continue_lookup_starts_while_catalog_first_page_is_still_running(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, _ = continue_plan(ctx, monkeypatch, count=1)
    together = threading.Barrier(2)
    fetched = []

    def page(*args):
        together.wait(1)
        return metas(0, 30)

    def meta(stype, sid, should_stop, **kw):
        together.wait(1)
        fetched.append(sid)
        return {'id': sid, 'name': 'resolved', 'poster': 'p'}

    monkeypatch.setattr(ctx.newhome, '_one_catalog_page', page)
    monkeypatch.setattr(ctx.views, '_fetch_meta_for_home', meta)
    win.onInit()
    assert fetched == ['tt0']
    assert win.getControl(ctx.newhome.CONTINUE_SHELF).size() == 1
    assert win._tab_load_timing['continue'] < 1
    win.close()


def test_missing_meta_is_not_retried_in_a_second_home_load(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, store = continue_plan(ctx, monkeypatch, count=1)
    calls = []
    def missing(*args, **kw):
        calls.append(True)
        kw['on_not_found']()
        return None
    monkeypatch.setattr(ctx.views, '_fetch_meta_for_home', missing)
    win.onInit()
    ctx.newhome._load_rows(win, store, store.get_enabled_addons(), None)
    assert calls == [True]
    assert ctx.newhome._continue_meta_misses == {('movie', 'tt0')}
    win.close()


def test_continue_budget_starts_after_twelve_slow_catalog_jobs(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, store = continue_plan(ctx, monkeypatch, count=1)
    layout = store.get_home_layout()
    catalog_id = layout['tabs']['home'][1]
    # Repeated descriptors exercise the real queue starvation independently
    # of the layout model's per-tab row limit.
    from lib.homelayout import installed_catalogs, resolve
    win._active_tab, win._layout = 'home', layout
    win._catalogs = installed_catalogs(store.get_enabled_addons())
    plan = resolve(layout, 'home', win._catalogs)
    catalog = next(job for job in plan if job[2] is not None)
    plan = [plan[0]] + [(30041 + i, *catalog[1:]) for i in range(12)]
    monkeypatch.setattr('lib.homelayout.resolve', lambda *args: plan)
    monkeypatch.setattr(ctx.newhome, '_one_catalog_page', lambda *a: time.sleep(0.7) or metas(0, 20))
    calls = []
    def fetch(stype, sid, should_stop, **kw):
        calls.append(sid)
        assert not should_stop()
        return {'id': sid, 'name': 'resolved', 'poster': 'p'}
    monkeypatch.setattr(ctx.views, '_fetch_meta_for_home', fetch)
    rows = ctx.newhome._load_rows(win, store, store.get_enabled_addons(), None)
    assert catalog_id and calls == ['tt0']
    assert len(rows[0]['items']) == 1
    assert not ctx.newhome._continue_meta_misses
    win.close()


def test_seventeen_lookups_use_eight_workers_and_cutoff_is_not_a_miss(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    win, store = continue_plan(ctx, monkeypatch, count=17)
    from lib.homelayout import installed_catalogs
    win._active_tab, win._layout = 'home', store.get_home_layout()
    win._catalogs = installed_catalogs(store.get_enabled_addons())
    lock = threading.Lock()
    running = [0, 0]
    before = set(threading.enumerate())
    def fetch(stype, sid, should_stop, **kw):
        with lock:
            running[0] += 1
            running[1] = max(running)
        time.sleep(0.8)
        with lock:
            running[0] -= 1
        return None if should_stop() else {'id': sid, 'name': 'resolved', 'poster': 'p'}
    monkeypatch.setattr(ctx.views, '_fetch_meta_for_home', fetch)
    try:
        rows = ctx.newhome._load_rows(win, store, store.get_enabled_addons(), None)
        assert running[1] == 8
        assert len(rows[0]['items']) == min(16, ctx.newhome.SHELF_CAP)
        assert not ctx.newhome._continue_meta_misses
    finally:
        for worker in set(threading.enumerate()) - before:
            worker.join(1)
        win.close()


def test_stopping_a_thousand_times_constructs_one_monitor(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    import xbmc
    original = xbmc.Monitor
    calls = []
    monkeypatch.setattr(xbmc, 'Monitor', lambda: calls.append(True) or original())
    for _ in range(1000):
        assert not ctx.newhome._stopping()
    assert calls == [True]


@pytest.mark.parametrize('abort', [False, True])
def test_idle_worker_waits_are_at_most_three_in_two_seconds_and_stop_promptly(session, monkeypatch, tmp_path, abort):
    ctx, win = session, session.window
    counts = {'meta': 0, 'ratings': 0, 'logo': 0}
    original_event = threading.Event

    class Event(original_event):
        def wait(self, timeout=None):
            name = threading.current_thread().name
            key = {'rivulet-library-meta': 'meta', 'rivulet-ratings': 'ratings',
                   'rivulet-logocheck': 'logo'}.get(name)
            if key:
                counts[key] += 1
            return super().wait(timeout)

    # Existing module-level wake events predate this patch.
    for module, attr in ((ctx.ratingsched, '_wake'), (ctx.logocheck, '_WAKE')):
        monkeypatch.setattr(module, attr, Event())
    monkeypatch.setattr(ctx.newhome.threading, 'Event', Event)
    monkeypatch.setattr(ctx.newhome, '_fetch_library_meta', lambda *_: None)
    ctx.newhome._schedule_library_meta(win, ctx.newhome._poster_item({'id': 'tt1', 'type': 'movie'}, sparse=True))
    from lib.stremio.ratings import RatingsCache
    monkeypatch.setattr(ctx.ratingsched, '_DWELL_SECONDS', 60)
    ctx.ratingsched._schedule('tt0000001', 'key', '', RatingsCache(str(tmp_path / 'ratings.json')))
    fetched = original_event()
    monkeypatch.setattr(ctx.logocheck, 'fetch_is_image', lambda _: fetched.set() or False)
    ctx.logocheck.ask(['logo'])
    assert fetched.wait(0.5)
    workers = [thread for thread in threading.enumerate() if thread.name in (
        'rivulet-library-meta', 'rivulet-ratings', 'rivulet-logocheck')]
    time.sleep(2)
    assert all(value <= 3 for value in counts.values()), counts
    started_at = time.monotonic()
    if abort:
        ctx.env.monitor_abort_requested = True
    else:
        win.close()
    for worker in workers:
        worker.join(max(0, 1.05 - (time.monotonic() - started_at)))
    assert not any(worker.is_alive() for worker in workers)
    assert time.monotonic() - started_at < 1.05
