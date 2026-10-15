# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Merge rules for account Continue rows and the offline push queue."""
import lib.librarysync as librarysync

NOW = '2020-01-01T00:00:00Z'
LATER = '2020-01-02T00:00:00Z'


def _item(item_id, offset, duration, removed=False, temp=False, last='2020-01-01T00:00:00Z',
          content_type='movie', video_id=None):
    return {
        '_id': item_id,
        'name': item_id,
        'type': content_type,
        'poster': 'p',
        'removed': removed,
        'temp': temp,
        'state': {
            'timeOffset': offset,
            'duration': duration,
            'lastWatched': last,
            'video_id': video_id,
        },
    }


class _MemStore:
    def __init__(self, progress=None, playing=None):
        self.progress = dict(progress or {})
        self.playing = playing
        self.writes = []

    def get_now_playing(self):
        return self.playing

    def get_progress(self, content_type, content_id, video_id=None):
        return self.progress.get((content_type, content_id, video_id))

    def set_progress(self, content_type, content_id, video_id, position_ms, duration_ms, now):
        entry = {'position_ms': position_ms, 'duration_ms': duration_ms, 'updated_at': now}
        self.progress[(content_type, content_id, video_id)] = entry
        self.writes.append((content_type, content_id, video_id, entry))


def test_continue_predicate_keeps_removed_temp_with_an_offset():
    assert librarysync.is_account_continue(_item('a', 1, 0, removed=True, temp=True)) is True
    assert librarysync.is_account_continue(_item('a', 40000, 100000, removed=True, temp=True)) is True


def test_continue_predicate_drops_explicit_removal_zero_offset_and_other():
    assert librarysync.is_account_continue(_item('a', 40000, 100000, removed=True, temp=False)) is False
    assert librarysync.is_account_continue(_item('a', 0, 100000, removed=True, temp=True)) is False
    assert librarysync.is_account_continue(_item('a', 10, 100, content_type='other')) is False
    assert librarysync.is_account_continue(_item('a', 10, 100, removed=False, temp=False)) is True


def test_newer_remote_wins_and_tie_keeps_local():
    local = [{
        'type': 'movie', 'id': 'a', 'video_id': None,
        'position_ms': 1000, 'duration_ms': 9000, 'updated_at': NOW,
    }]
    remote = [_item('a', 5000, 9000, last=LATER)]
    merged = librarysync.merge_progress_sources(local, remote)
    assert merged[0]['position_ms'] == 5000
    assert merged[0]['from_library'] is True

    remote_same = [_item('a', 5000, 9000, last=NOW)]
    tied = librarysync.merge_progress_sources(local, remote_same)
    assert tied[0]['position_ms'] == 1000
    assert tied[0].get('from_library') is not True


def test_newer_local_wins():
    local = [{
        'type': 'movie', 'id': 'a', 'video_id': None,
        'position_ms': 8000, 'duration_ms': 9000, 'updated_at': LATER,
    }]
    merged = librarysync.merge_progress_sources(local, [_item('a', 1000, 9000, last=NOW)])
    assert merged[0]['position_ms'] == 8000


def test_seed_copies_a_measured_newer_row_and_skips_the_pointer():
    store = _MemStore()
    librarysync.seed_progress(store, [
        _item('measured', 40000, 100000, last=LATER),
        _item('pointer', 1, 0, removed=True, temp=True, last=LATER),
    ])
    assert list(store.progress) == [('movie', 'measured', None)]
    assert store.progress[('movie', 'measured', None)]['updated_at'] == LATER


def test_seed_skips_a_sub_one_percent_position():
    """1ms against a real duration is the opening pointer, not a resume."""
    store = _MemStore()
    librarysync.seed_progress(store, [_item('barely', 1, 100000, last=LATER)])
    assert store.writes == []


def test_seed_skips_the_title_currently_playing_and_an_older_remote():
    store = _MemStore(
        progress={('movie', 'old', None): {'position_ms': 10, 'duration_ms': 100, 'updated_at': LATER}},
        playing={'id': 'playing'},
    )
    librarysync.seed_progress(store, [
        _item('playing', 40000, 100000, last=LATER),
        _item('old', 1000, 9000, last=NOW),
    ])
    assert store.writes == []


def test_should_mark_watched_rules():
    assert librarysync.should_mark_watched(50, 100, natural_end=False, playback_error=False) is False
    assert librarysync.should_mark_watched(91, 100, natural_end=False, playback_error=False) is True
    assert librarysync.should_mark_watched(50, 100, natural_end=True, playback_error=False) is True
    assert librarysync.should_mark_watched(99, 100, natural_end=False, playback_error=True) is False


class _ScriptAPI:
    def __init__(self, item=None):
        self.item = item
        self.puts = []

    def datastore_get(self, auth_key, collection='libraryItem', ids=None, all=True):
        return [self.item] if self.item else []

    def datastore_put(self, auth_key, changes, collection='libraryItem'):
        self.puts.append(changes[0])
        self.item = changes[0]


def test_retry_of_a_finished_put_does_not_increment_times_watched_again():
    api = _ScriptAPI()
    job = librarysync.build_push_job(
        {'id': 'tt1', 'type': 'movie', 'video_id': 'tt1', 'name': 'A', 'video_ids': ['tt1']},
        100, 100, finished=True, updated_at=LATER,
    )
    assert librarysync.push_library_job(api, 'tok', job) == 'put'
    assert api.item['state']['timesWatched'] == 1
    assert librarysync.push_library_job(api, 'tok', job) == 'skipped'
    assert api.item['state']['timesWatched'] == 1
    assert api.puts[0]['state']['lastWatched'] == LATER


def test_flush_stops_on_the_first_failure_and_keeps_the_rest():
    class _Boom:
        def __init__(self):
            self.calls = 0

        def datastore_get(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return []
            raise RuntimeError('offline')

        def datastore_put(self, *args, **kwargs):
            return None

    class _Queue:
        def __init__(self, jobs):
            self.jobs = jobs

        def get_pending_sync(self):
            return list(self.jobs)

        def set_pending_sync(self, jobs):
            self.jobs = list(jobs)

    first = librarysync.build_push_job({'id': 'a', 'type': 'movie'}, 1, 0, False, updated_at=NOW)
    second = librarysync.build_push_job({'id': 'b', 'type': 'movie'}, 1, 0, False, updated_at=NOW)
    store = _Queue([first, second])
    assert librarysync.flush_pending(store, _Boom(), 'tok') is False
    assert [job['id'] for job in store.jobs] == ['b']
