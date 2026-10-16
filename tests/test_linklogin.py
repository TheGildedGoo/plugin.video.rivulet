# SPDX-FileCopyrightText: 2026 M0Rf30
# SPDX-License-Identifier: MIT

"""Stremio's code sign-in (link.stremio.com). No network: a fake session."""
import pytest
import requests

from lib.stremio.linklogin import LINK_API_URL, LinkError, create_code, read_auth_key
from tests.conftest import FakeResponse, FakeSession


class _NotJson(FakeResponse):
    def json(self):
        raise ValueError('not json')


def test_create_code_reads_the_code_and_its_page():
    session = FakeSession(responses=[FakeResponse({
        'success': True, 'code': 'WUS8', 'link': 'https://link.stremio.com/WUS8',
        'qrcode': 'data:image/png;base64,xx', 'result': {'code': 'WUS8'},
    })])
    assert create_code(session=session) == ('WUS8', 'https://link.stremio.com/WUS8')
    call = session.calls[0]
    assert call['url'] == LINK_API_URL + '/create'
    assert call['kwargs']['params'] == {'type': 'Create'}


def test_create_code_under_result_and_without_a_safe_link():
    session = FakeSession(responses=[FakeResponse({'result': {'code': 'AB12', 'link': 'javascript:x'}})])
    assert create_code(session=session) == ('AB12', 'https://link.stremio.com/AB12')


def test_create_code_without_a_code_is_an_error():
    with pytest.raises(LinkError):
        create_code(session=FakeSession(responses=[FakeResponse({'success': False})]))


def test_create_code_unreachable_or_nonsense_is_an_error():
    with pytest.raises(LinkError):
        create_code(session=FakeSession(exc=requests.exceptions.ConnectionError('down')))
    with pytest.raises(LinkError):
        create_code(session=FakeSession(responses=[_NotJson()]))
    with pytest.raises(LinkError):
        create_code(session=FakeSession(responses=[FakeResponse(['not', 'a', 'dict'])]))
    with pytest.raises(LinkError):
        create_code(session=FakeSession(responses=[FakeResponse({}, status_code=502)]))


def test_read_is_not_yet_while_the_code_waits():
    waiting = {'result': None, 'error': {'code': 101, 'message': 'Invalid or expired token'}}
    session = FakeSession(responses=[FakeResponse(waiting)])
    assert read_auth_key('WUS8', session=session) is None
    call = session.calls[0]
    assert call['url'] == LINK_API_URL + '/read'
    assert call['kwargs']['params'] == {'type': 'Read', 'code': 'WUS8'}


def test_read_finds_the_key_at_the_top_or_under_result():
    top = FakeSession(responses=[FakeResponse({'authKey': ' key-1 '})])
    nested = FakeSession(responses=[FakeResponse({'result': {'authKey': 'key-2', 'user': {}}})])
    assert read_auth_key('WUS8', session=top) == 'key-1'
    assert read_auth_key('WUS8', session=nested) == 'key-2'


def test_read_unreachable_is_an_error():
    with pytest.raises(LinkError):
        read_auth_key('WUS8', session=FakeSession(exc=requests.exceptions.Timeout('slow')))
