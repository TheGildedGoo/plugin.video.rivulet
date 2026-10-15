# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Home/Add-ons pull, and the pull that has to happen before a push."""
import os

from lib.stremio.api import ApiError
from lib.ui import addonsync


class _Api:
    def __init__(self, addons, modified='t1', error=None):
        self.addons = addons
        self.modified = modified
        self.error = error
        self.gets = 0

    def addon_collection_state(self, auth_key):
        self.gets += 1
        if self.error is not None:
            raise self.error
        return list(self.addons), self.modified


class _Store:
    def __init__(self, addons, auth=None, mtime=None):
        self.addons = list(addons)
        self.auth = {'authKey': 'k'} if auth is None else auth
        self.mtime = mtime
        self.writes = 0
        self.auth_cleared = False

    def get_auth(self):
        return self.auth

    def set_auth(self, auth):
        self.auth = auth
        self.auth_cleared = auth is None

    def get_addons(self):
        return list(self.addons)

    def update_addons(self, transform):
        self.addons = transform(self.addons)
        self.writes += 1
        return self.addons

    def get_addon_collection_mtime(self):
        return self.mtime

    def set_addon_collection_mtime(self, value):
        self.mtime = value


def setup_function():
    addonsync.reset_pull_clock()


def test_pull_adds_a_web_only_addon_and_keeps_locals():
    local = {'transportUrl': 'https://local.example/manifest.json', 'flags': {'disabled': True}}
    web = {'transportUrl': 'https://web.example/manifest.json', 'manifest': {'id': 'web'}}
    store = _Store([local])
    api = _Api([local, web], modified='newer')
    assert addonsync.pull_account_addons(store, api=api, force=True, now=10) is True
    assert [item['transportUrl'] for item in store.addons] == [
        local['transportUrl'], web['transportUrl'],
    ]
    assert store.addons[0]['flags'] == {'disabled': True}
    assert store.mtime == 'newer'
    assert store.writes == 1


def test_unchanged_timestamp_skips_the_addon_write():
    local = {'transportUrl': 'https://local.example/manifest.json'}
    store = _Store([local], mtime='same')
    api = _Api([{'transportUrl': 'https://web.example/manifest.json'}], modified='same')
    assert addonsync.pull_account_addons(store, api=api, force=True, now=10) is False
    assert store.writes == 0
    assert len(store.addons) == 1
    assert api.gets == 1


def test_open_pull_respects_fifteen_minutes_and_a_push_does_not():
    local = {'transportUrl': 'https://local.example/manifest.json'}
    store = _Store([local])
    api = _Api([local], modified='t')
    assert addonsync.pull_account_addons(store, api=api, force=False, now=100) is False
    assert api.gets == 1
    assert addonsync.pull_account_addons(store, api=api, force=False, now=100 + 60) is False
    assert api.gets == 1
    assert addonsync.pull_account_addons(store, api=api, force=True, now=100 + 60) is False
    assert api.gets == 2
    assert addonsync.pull_account_addons(store, api=api, force=False, now=160 + 15 * 60) is False
    assert api.gets == 3


def test_pull_failure_does_not_clear_auth_or_write():
    store = _Store([{'transportUrl': 'https://local.example/manifest.json'}])
    api = _Api([], error=ApiError('timeout'))
    try:
        addonsync.pull_account_addons(store, api=api, force=True, now=1)
    except ApiError:
        pass
    else:
        raise AssertionError('expected ApiError')
    assert store.auth_cleared is False
    assert store.writes == 0


def test_real_store_skips_rewriting_addons_when_the_timestamp_matches(tmp_path):
    from lib.store import Store

    store = Store(str(tmp_path))
    current = store.get_addons()
    store.set_addon_collection_mtime('stamp')
    before = os.stat(os.path.join(str(tmp_path), 'addons.json')).st_mtime_ns
    api = _Api(current, modified='stamp')
    assert addonsync.pull_account_addons(store, api=api, force=True, now=5) is False
    after = os.stat(os.path.join(str(tmp_path), 'addons.json')).st_mtime_ns
    assert before == after


def test_playback_service_does_not_pull_the_collection():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'lib', 'service_runner.py'), encoding='utf-8') as handle:
        text = handle.read()
    assert 'addonCollection' not in text
    assert 'addonsync' not in text
    assert 'pull_account_addons' not in text
