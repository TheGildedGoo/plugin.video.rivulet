# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Poster texture warm: posters only, four at a time, abort stops it."""
import contextlib

import pytest

from tests.kodistubs import install_kodi_stubs

_RELOAD = ('lib.ui.compat', 'lib.ui.posterwarm')


@pytest.fixture
def load_warm():
    with contextlib.ExitStack() as stack:
        def _load(**kwargs):
            return stack.enter_context(install_kodi_stubs(reload=_RELOAD, **kwargs))

        yield _load


def test_collect_keeps_posters_and_ignores_backgrounds():
    from lib.ui.posterwarm import collect_poster_urls

    groups = [
        [{'poster': 'p%d' % index, 'background': 'b%d' % index, 'logo': 'l%d' % index} for index in range(40)],
        [],
        [{'poster': 's%d' % index, 'background': 'fan'} for index in range(2)],
        [{'poster': 'third', 'background': 'only-fan'}],
        [{'poster': 'too-far'}],
    ]
    urls = collect_poster_urls(groups, limit_rows=3, limit_titles=30)
    assert urls[0] == 'p0'
    assert len([url for url in urls if url.startswith('p')]) == 30
    assert 's0' in urls and 's1' in urls and 'third' in urls
    assert all(not url.startswith('b') and not url.startswith('l') and url != 'fan' for url in urls)
    assert 'too-far' not in urls
    assert 'only-fan' not in urls


def test_warm_sets_four_posters_then_stops_on_abort(load_warm):
    ctx = load_warm()
    import xbmcgui

    from lib.ui.posterwarm import reset_warmer, warm_posters

    reset_warmer()
    urls = ['https://img.example/%d.jpg' % index for index in range(6)]

    def abort(calls):
        return calls > 1

    ctx.env.monitor_abort = abort
    windows = []

    class _Recording(xbmcgui.Window):
        def __init__(self, window_id=0):
            super().__init__(window_id)
            windows.append(self)

    xbmcgui.Window = _Recording
    warm_posters(urls)
    assert len(windows) == 1
    window = windows[0]
    assert window.shown is True
    assert window.closed is True
    assert len(window.controls) == 4
    assert all(control.width == 1 and control.height == 1 for control in window.controls)
    shown = [control.image for control in window.controls]
    assert shown == urls[:4]
    assert urls[4] not in shown
    assert urls[5] not in shown
