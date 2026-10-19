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
