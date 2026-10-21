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


def test_three_ten_second_lookups_cannot_hold_startup_or_repeat_after_deadline(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    hw = ctx.newhome
    win, store = continue_plan(ctx, monkeypatch)
    release = threading.Event()
    started = threading.Barrier(4)
    calls = []
    before = set(threading.enumerate())

    def fetch(stype, sid, should_stop, **kw):
        calls.append(sid)
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
        assert len(hw._continue_meta_misses) == 3
        before_retry = len(calls)
        rows = hw._load_rows(win, store, store.get_enabled_addons(), None)
        assert rows[0]['items'] == [] and len(calls) == before_retry == 3
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
    monkeypatch.setattr(ctx.views, '_fetch_meta_for_home', lambda *a, **kw: calls.append(True) or None)
    win.onInit()
    ctx.newhome._load_rows(win, store, store.get_enabled_addons(), None)
    assert calls == [True]
    assert ctx.newhome._continue_meta_misses == {('movie', 'tt0')}
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
