# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Account-collection union. Locals are kept. Unsafe remotes are not."""
from lib.stremio.collection import union_addon_descriptors


def test_union_keeps_locals_and_appends_only_new_safe_remotes():
    local = [
        {'transportUrl': 'https://local.example/manifest.json', 'flags': {'disabled': True}},
    ]
    remote_same = {
        'transportUrl': 'https://local.example/manifest.json',
        'manifest': {'id': 'local'},
        'flags': {},
    }
    remote_new = {
        'transportUrl': 'HTTPS://Added.Example/manifest.json',
        'manifest': {'id': 'org.added'},
    }
    snapshot = dict(remote_new)
    merged, discarded = union_addon_descriptors(local, [remote_same, remote_new])
    assert discarded == []
    assert merged[0] is local[0]
    assert merged[0]['flags'] == {'disabled': True}
    assert merged[1]['transportUrl'] == 'https://added.example/manifest.json'
    assert remote_new == snapshot


def test_union_drops_unsafe_urls_and_does_not_delete_a_local_the_remote_omitted():
    local = {'transportUrl': 'https://kept.example/manifest.json', 'manifest': {'id': 'kept'}}
    unsafe = {
        'transportUrl': 'https://attacker:hunter2@evil.example/manifest.json',
        'manifest': {'id': 'org.evil'},
    }
    merged, discarded = union_addon_descriptors([local], [unsafe])
    assert merged == [local]
    assert discarded[0][0] == 'org.evil'
    assert 'hunter2' not in discarded[0][1]
    assert 'evil.example' in discarded[0][1]
