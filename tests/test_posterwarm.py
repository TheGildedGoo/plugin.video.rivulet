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


class _Slot:
    def __init__(self):
        self.images = []

    @property
    def image(self):
        return self.images[-1] if self.images else None

    def setImage(self, url):
        self.images.append(url)


class _Screen:
    """A Home or hub window: the eight warm slots its XML declares."""

    def __init__(self, missing=False):
        from lib.ui.posterwarm import WARM_SLOTS

        self.missing = missing
        self.slots = {control_id: _Slot() for control_id in WARM_SLOTS}

    def getControl(self, control_id):
        if self.missing:
            raise RuntimeError('Non-Existent Control %d' % control_id)
        return self.slots[control_id]


def test_warm_fills_the_screens_own_slots_then_stops_on_abort(load_warm):
    """The old warmer opened its own window. Kodi refuses that while a
    modal dialog is up, so nothing ever loaded."""
    ctx = load_warm()

    from lib.ui.posterwarm import WARM_SLOTS, reset_warmer, warm_posters

    reset_warmer()
    urls = ['https://img.example/%d.jpg' % index for index in range(12)]
    ctx.env.monitor_abort = lambda calls: calls >= 1
    screen = _Screen()

    warm_posters(screen, urls)

    first = [screen.slots[control_id].images[0] for control_id in WARM_SLOTS]
    assert first == urls[:8]
    # Aborted during the first hold: the second batch never went out,
    # and every slot let go of its URL on the way out.
    assert all(urls[8] not in slot.images for slot in screen.slots.values())
    assert all(slot.image == '' for slot in screen.slots.values())


def test_each_batch_is_held_long_enough_for_kodi_to_start_it(load_warm):
    ctx = load_warm()

    from lib.ui import posterwarm

    posterwarm.reset_warmer()
    ctx.env.monitor_abort = False
    screen = _Screen()

    posterwarm.warm_posters(screen, ['u%d' % index for index in range(16)])

    assert ctx.env.wait_calls == [posterwarm._HOLD_SECONDS, posterwarm._HOLD_SECONDS]
    assert posterwarm._HOLD_SECONDS >= 1.0


def test_a_screen_without_slots_warms_nothing(load_warm):
    """A Rev2 skin, or a window that has closed. No error, no window."""
    ctx = load_warm()

    from lib.ui.posterwarm import reset_warmer, warm_posters

    reset_warmer()
    ctx.env.monitor_abort = False

    warm_posters(_Screen(missing=True), ['u1', 'u2'])
    warm_posters(None, ['u1'])

    assert ctx.env.wait_calls == []


def test_home_and_hub_declare_the_warm_slots():
    import os
    import xml.etree.ElementTree as ET

    from lib.ui.posterwarm import WARM_SLOTS

    skin = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'resources', 'skins', 'Default', '1080i',
    )
    for name in ('HomeWindow.xml', 'HubWindow.xml'):
        root = ET.parse(os.path.join(skin, name)).getroot()
        for control_id in WARM_SLOTS:
            control = root.find(".//control[@id='%d']" % control_id)
            assert control is not None, (name, control_id)
            assert control.get('type') == 'image', name
            assert control.findtext('width') == '1' and control.findtext('height') == '1', name
            assert control.find('visible') is None, name
