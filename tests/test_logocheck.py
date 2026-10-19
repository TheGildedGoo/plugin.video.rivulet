"""lib/ui/logocheck.py: a clearlogo is shown once its host answers with an image."""
import lib.ui.logocheck as logocheck


class _Response:
    def __init__(self, status, kind):
        self.status_code = status
        self.headers = {'Content-Type': kind}
        self.closed = False

    def close(self):
        self.closed = True


def _fake_get(monkeypatch, response=None, error=None):
    import requests
    seen = []

    def get(url, **kwargs):
        seen.append((url, kwargs))
        if error:
            raise error
        return response

    monkeypatch.setattr(requests, 'get', get)
    return seen


def test_an_image_answer_is_good_and_the_response_is_closed(monkeypatch):
    response = _Response(206, 'image/png')
    seen = _fake_get(monkeypatch, response)
    assert logocheck.fetch_is_image('https://img/logo.png') is True
    assert response.closed is True
    assert seen[0][1]['stream'] is True and seen[0][1]['headers'] == {'Range': 'bytes=0-2047'}


def test_a_missing_or_wrong_answer_is_not(monkeypatch):
    _fake_get(monkeypatch, _Response(404, 'text/html'))
    assert logocheck.fetch_is_image('https://img/x') is False
    _fake_get(monkeypatch, _Response(200, 'text/html'))
    assert logocheck.fetch_is_image('https://img/x') is False
    _fake_get(monkeypatch, error=OSError('down'))
    assert logocheck.fetch_is_image('https://img/x') is False


def test_the_worker_records_the_answer_and_repaints(monkeypatch):
    repaints = []
    monkeypatch.setattr(logocheck, 'fetch_is_image', lambda url: url.endswith('good.png'))
    monkeypatch.setattr(logocheck, '_repaint', lambda: repaints.append(True))
    monkeypatch.setattr(logocheck._WAKE, 'wait', lambda timeout=None: False)
    logocheck._PENDING[:] = ['https://img/bad.png', 'https://img/good.png']

    logocheck._run()

    assert logocheck.state('https://img/good.png') is True
    assert logocheck.state('https://img/bad.png') is False
    assert repaints == [True]
    assert logocheck._WORKER == []


def test_remember_and_forget(monkeypatch):
    logocheck.remember('https://img/a.png', True)
    assert logocheck.state('https://img/a.png') is True
    logocheck.forget_all()
    assert logocheck.state('https://img/a.png') is None


# --- the queue (a fresh module: the real ask(), not conftest's recorder) ------

import pytest  # noqa: E402

from tests.kodistubs import install_kodi_stubs  # noqa: E402


class _Thread:
    started = []

    def __init__(self, target=None, name=None, daemon=None):
        self.target = target
        self.name = name
        self.daemon = daemon

    def start(self):
        _Thread.started.append(self)


@pytest.fixture
def fresh(monkeypatch):
    with install_kodi_stubs(reload=('lib.ui.logocheck',)) as ctx:
        module = ctx.logocheck
        _Thread.started = []
        monkeypatch.setattr(module.threading, 'Thread', _Thread)
        ctx.module = module
        yield ctx
        module.forget_all()
        del module._WORKER[:]


def test_ask_queues_only_what_has_no_answer(fresh):
    lc = fresh.module
    lc.remember('https://img/known.png', False)
    lc.ask(['https://img/a.png', '', None, 'https://img/known.png', 'https://img/a.png', 'https://img/b.png'])
    assert lc._PENDING == ['https://img/a.png', 'https://img/b.png']
    assert lc._WAKE.is_set()
    # One worker, named and a daemon so Kodi can quit under it.
    assert len(_Thread.started) == 1
    assert _Thread.started[0].name == 'rivulet-logocheck' and _Thread.started[0].daemon is True
    assert _Thread.started[0].target == lc._run


def test_ask_does_not_start_a_second_worker(fresh):
    lc = fresh.module
    lc.ask(['https://img/a.png'])
    lc.ask(['https://img/b.png'])
    assert len(_Thread.started) == 1
    assert lc._PENDING == ['https://img/a.png', 'https://img/b.png']


def test_nothing_new_to_ask_starts_nothing(fresh):
    lc = fresh.module
    lc.remember('https://img/a.png', True)
    lc.ask(['https://img/a.png'])
    lc.ask(None)
    lc.ask([])
    assert _Thread.started == []
    assert not lc._WAKE.is_set()


def test_the_queue_keeps_the_newest_asks(fresh):
    lc = fresh.module
    urls = ['https://img/%d.png' % n for n in range(lc._MAX_PENDING + 5)]
    lc.ask(urls)
    assert len(lc._PENDING) == lc._MAX_PENDING
    assert lc._PENDING[0] == 'https://img/5.png'
    # The remote is on the newest title: it is asked first.
    assert lc._next() == urls[-1]


def test_next_on_an_empty_queue_is_none(fresh):
    assert fresh.module._next() is None


def test_the_worker_sleeps_then_picks_up_new_asks(fresh, monkeypatch):
    lc = fresh.module
    fetched = []
    wakes = iter([True, False])

    def _wait(timeout=None):
        if fetched == [] and not lc._PENDING:
            lc._PENDING.append('https://img/late.png')
        return next(wakes)

    monkeypatch.setattr(lc, 'fetch_is_image', lambda url: fetched.append(url) or False)
    monkeypatch.setattr(lc._WAKE, 'wait', _wait)
    lc._WORKER.append('me')
    lc._run()
    assert fetched == ['https://img/late.png']
    assert lc.state('https://img/late.png') is False
    assert lc._WORKER == []


def test_the_worker_lets_go_of_its_slot_when_a_fetch_blows_up(fresh, monkeypatch):
    lc = fresh.module

    def _boom(url):
        raise RuntimeError('boom')

    monkeypatch.setattr(lc, 'fetch_is_image', _boom)
    lc._PENDING.append('https://img/a.png')
    lc._WORKER.append('me')
    with pytest.raises(RuntimeError):
        lc._run()
    # A later ask can start a new worker.
    assert lc._WORKER == []


def test_repaint_pokes_the_screen(fresh):
    fresh.module._repaint()
    assert fresh.env.executed_builtins[-1] == 'Action(noop)'


def test_repaint_never_raises(fresh, monkeypatch):
    import xbmc

    def _gone(cmd):
        raise RuntimeError('Kodi is going away')

    monkeypatch.setattr(xbmc, 'executebuiltin', _gone)
    fresh.module._repaint()


def test_forget_all_also_drops_the_queue(fresh):
    lc = fresh.module
    lc.ask(['https://img/a.png'])
    lc.forget_all()
    assert lc._PENDING == []


def test_remember_ignores_an_empty_url():
    logocheck.remember('', True)
    assert logocheck.state('') is None


def test_an_odd_response_is_not_an_image(monkeypatch):
    class _NoHeaders(_Response):
        @property
        def headers(self):
            raise RuntimeError('no headers')

        @headers.setter
        def headers(self, value):
            pass

    class _CloseFails(_Response):
        def close(self):
            raise OSError('reset')

    _fake_get(monkeypatch, _NoHeaders(200, 'image/png'))
    assert logocheck.fetch_is_image('https://img/x') is False
    _fake_get(monkeypatch, _CloseFails(200, 'image/jpeg'))
    assert logocheck.fetch_is_image('https://img/x') is True
    _fake_get(monkeypatch, _Response(200, None))
    assert logocheck.fetch_is_image('https://img/x') is False
