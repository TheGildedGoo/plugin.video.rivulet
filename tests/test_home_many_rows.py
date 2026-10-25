"""Forty rows keep the first paint small and native items on the GUI thread."""
import queue
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from tools.make_home_rows import ROW, generate

from lib import homelayout
from tests.test_home_startup import prepare
from tests.test_home_teardown import _Recorder
from tests.test_newhome import load_homewindow as load_homewindow
from tests.test_newhome_tabs import metas


@pytest.mark.parametrize('leave', ['', 'tab', 'close', 'failed'])
def test_late_rows_never_block_first_paint_and_only_apply_to_current_tab(
        load_homewindow, monkeypatch, leave):
    ctx = load_homewindow()
    hw = ctx.newhome
    entered, release = threading.Event(), threading.Event()
    calls, running, peak = [], [0], [0]
    lock = threading.Lock()
    def page(_transport, _manifest, catalog):
        index = int(catalog['id'][3:])
        with lock:
            calls.append(index)
        if index >= 8:
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            entered.set()
            try:
                assert release.wait(5)
                if leave == 'failed':
                    raise hw.CatalogUnavailable('late row')
            finally:
                with lock:
                    running[0] -= 1
        return metas(index * 100, 24)
    win, _ = prepare(ctx, monkeypatch, count=40, first=page)
    recorder = _Recorder(monkeypatch)
    original = None
    try:
        win.onInit()  # returns before release, despite 32 deferred catalogs
        assert entered.wait(5)
        assert len(win._rows) == 40 and win._tab_loaded['home']
        assert sum(bool(win.getProperty('shelf_slot%d' % i)) for i in range(40)) == 8
        assert win.getControl(30151).label == '1 / 8'
        assert sorted(index for index in calls if index < 8) == list(range(8))
        assert win.getControl(30227).size() == 0
        original = win._rows[30227]
        assert original['unloaded']
        if leave == 'tab':
            hw._switch_tab(win, 'mystuff')
        elif leave == 'close':
            win.close()
    finally:
        release.set()
        hw._join_shelf_extends(win)
    hw._apply_shelf_extends(win)
    assert 1 <= peak[0] <= 2
    assert recorder.threads == {threading.current_thread()}
    if not leave:
        assert len(calls) == 40
        assert win.getControl(30227).size() == 24
        assert win.getProperty('shelf_slot39') == '1'
        assert win.getControl(30427).label == '40 / 40'
        assert not original['unloaded']
    else:
        assert not original['items'] and win.getControl(30227).size() == 0
    assert win._tab_loaded['home']  # a later failure/cancellation never poisons startup
    original = None
    hw.release_items(win)
    assert not recorder.alive()  # window itself is deliberately still referenced


def test_deferred_rows_resume_when_returning_to_a_cached_tab(load_homewindow, monkeypatch):
    ctx = load_homewindow()
    hw = ctx.newhome
    win, _ = prepare(ctx, monkeypatch, count=15, first=lambda *_: metas(0, 24))
    # Suppress only the background scheduling, to leave a deterministic
    # unfinished snapshot. The real scheduling resumes when revisited.
    top_up = hw._top_up_shelves
    monkeypatch.setattr(hw, '_top_up_shelves', lambda *_: None)
    win.onInit()
    assert win._rows[30202]['unloaded']
    hw._switch_tab(win, 'mystuff')
    monkeypatch.setattr(hw, '_top_up_shelves', top_up)
    hw._switch_tab(win, 'home')
    hw._join_shelf_extends(win)
    hw._apply_shelf_extends(win)
    assert win.getProperty('shelf_slot14') == '1'
    assert win.getControl(30402).label == '15 / 15'
    hw.release_items(win)


def test_library_and_continue_are_in_the_blocking_pass_alongside_eight_catalogs(
        load_homewindow, monkeypatch):
    ctx = load_homewindow()
    hw = ctx.newhome
    calls, reads = [], []
    def page(_transport, _manifest, catalog):
        calls.append(catalog['id'])
        return metas(0, 24)
    win, store = prepare(ctx, monkeypatch, count=16, first=page)
    layout = store.get_home_layout()
    layout['tabs']['home'] = ['continue:movie', 'library:movie'] + layout['tabs']['home']
    win._active_tab, win._layout = 'home', layout
    win._catalogs = homelayout.installed_catalogs(store.get_enabled_addons())
    monkeypatch.setattr(hw, '_fetch_library', lambda *_: reads.append(True) or [])
    rows = hw._load_rows(win, store, {'authKey': 'fake'})
    assert reads == [True]
    assert [state['kind'] for state in rows[:2]] == ['continue', 'library']
    assert sorted(calls) == ['top%d' % i for i in range(8)]
    assert sum(bool(state.get('unloaded')) for state in rows) == 8
    hw.release_items(win)


@pytest.mark.parametrize('after_timeout', [False, True])
def test_first_paint_collector_keeps_a_result_published_as_the_last_worker_finishes(
        load_homewindow, after_timeout):
    ctx = load_homewindow()
    class Results(queue.Queue):
        timeout_once = after_timeout
        def get(self, timeout=None):
            if self.timeout_once:
                self.timeout_once = False
                raise queue.Empty
            return super().get(timeout=timeout)
    results = Results()
    class Finishing:
        calls = 0
        def is_alive(self):
            self.calls += 1
            if after_timeout and self.calls == 1:
                return True
            if self.calls == (2 if after_timeout else 1):
                results.put(('row', ['poster']))
            return False
    fetched = ctx.newhome._collect_home_rows(results, 1, [Finishing()], lambda: False)
    assert fetched == {'row': ['poster']}


def test_new_xml_rows_are_exact_copies_with_only_slot_ids_and_navigation_changed():
    path = Path(__file__).parents[1] / 'resources/skins/Default/1080i/NewHomeWindow.xml'
    text = path.read_text()
    assert generate(text) == text
    rows = list(ROW.finditer(text))
    assert len(rows) == 40
    template = rows[0].group()
    controls = {int(c.get('id')): c for c in ET.fromstring(text).iter('control') if c.get('id')}
    panels = list(range(30041, 30053)) + list(range(30200, 30228))
    for index in range(12, 40):
        panel = panels[index]
        normalized = rows[index].group().replace('shelf_slot%d' % index, 'shelf_slot0')
        normalized = normalized.replace('<onup>%d</onup>' % panels[index - 1], '<onup>30040</onup>')
        normalized = normalized.replace('<ondown>%d</ondown>' % panels[min(index + 1, 39)],
                                         '<ondown>30042</ondown>')
        for value, original in ((panel, 30041), (30300 + index - 12, 30141),
                                (30400 + index - 12, 30151)):
            normalized = normalized.replace(str(value), str(original))
        assert normalized == template
        assert controls[panel].findtext('onup') == str(panels[index - 1])
        assert controls[panel].findtext('ondown') == str(panels[min(index + 1, 39)])
