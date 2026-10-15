# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Kodi's addon version order, which the publisher has to match.

Pinned against xbmc/addons/AddonVersion.cpp: split on the first '-', compare
the upstream component first, and compare digit runs as integers. A string
sort would publish 0.30.1.rev10 and Kodi would keep 0.30.1.rev9.
"""

from scripts.kodi_addon_version import bump_rev, ensure_newer, kodi_cmp, kodi_lt


def test_hyphen_revision_sorts_after_the_plain_release():
    assert kodi_lt("0.30.1", "0.30.1-ui.1")
    assert kodi_lt("0.30.1-ui.1", "0.30.1.rev1")
    assert kodi_cmp("0.30.1.rev1", "0.30.1.rev1") == 0


def test_rev_counter_is_numeric():
    assert kodi_lt("0.30.1.rev9", "0.30.1.rev10")
    assert kodi_lt("0.30.1.rev1", "0.30.1.rev2")
    assert kodi_lt("0.30.1.rev1", "0.30.2")
    assert kodi_cmp("0.30.1.REV10", "0.30.1.rev10") == 0


def test_bump_rev_always_increases_under_kodi():
    samples = ("0.30.1", "0.30.1-ui.1", "0.30.1.rev1", "0.30.1.rev9")
    for version in samples:
        nxt = bump_rev(version)
        assert kodi_lt(version, nxt)


def test_ensure_newer_keeps_a_version_kodi_has_not_seen():
    assert ensure_newer("0.30.1.rev1", None) == "0.30.1.rev1"
    assert ensure_newer("0.30.2", "0.30.1.rev5") == "0.30.2"


def test_ensure_newer_bumps_when_published_has_caught_up():
    assert ensure_newer("0.30.1.rev1", "0.30.1.rev1") == "0.30.1.rev2"
    assert ensure_newer("0.30.1.rev3", "0.30.1.rev5") == "0.30.1.rev6"
    assert kodi_lt("0.30.1-ui.1", ensure_newer("0.30.1-ui.1", "0.30.1-ui.1"))
