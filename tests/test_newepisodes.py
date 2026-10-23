# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT
"""Tests for lib.newepisodes: the episode still URL and label Home's
Continue row builds from a ``tt..:s:e`` id. Pure Python, no Kodi stubs."""
import pytest

from lib.newepisodes import _episode_label, episode_still_url


def test_still_url_for_an_imdb_series_points_at_the_metahub_episode_image():
    assert episode_still_url('tt123', 2, 5) == 'https://episodes.metahub.space/tt123/2/5/w780.jpg'


@pytest.mark.parametrize('series_id,season,episode', [
    ('kitsu:1', 1, 1), ('tt123', 0, 1), ('tt123', 1, 0), ('tt', 1, 1), (None, 1, 1),
])
def test_still_url_is_empty_when_there_is_nothing_to_point_at(series_id, season, episode):
    assert episode_still_url(series_id, season, episode) == ''


def test_hostile_numbers_from_an_addon_do_not_raise():
    # json.loads accepts the literal Infinity; int(float('inf')) raises OverflowError.
    assert episode_still_url('tt123', float('inf'), 1) == ''
    assert _episode_label(float('inf'), None, 'Pilot') == 'Pilot'


def test_label_is_unpadded_and_degrades_to_the_title_alone():
    assert _episode_label(1, 3, 'Pilot') == 'S1E3 \u00b7 Pilot'
    assert _episode_label(1, 3, '') == 'S1E3'
    assert _episode_label(None, None, 'Pilot') == 'Pilot'
