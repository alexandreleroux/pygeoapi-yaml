# =================================================================
#
# Authors: Alexandre Leroux <alexandreleroux@icloud.com>
#
# Copyright (c) 2026 Alexandre Leroux
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# =================================================================

"""Tests through pygeoapi itself: the configuration, the OpenAPI
document and the OGC API - Features responses"""

from http import HTTPStatus
import json
import os

import pytest
from werkzeug.datastructures import ImmutableMultiDict
from werkzeug.test import create_environ
from werkzeug.wrappers import Request

from pygeoapi.api import API, APIRequest, describe_collections
from pygeoapi.api.itemtypes import (get_collection_item,
                                    get_collection_items,
                                    get_collection_queryables)
from pygeoapi.config import validate_config
from pygeoapi.openapi import get_oas
from pygeoapi.util import yaml_load


HERE = os.path.dirname(os.path.abspath(__file__))


def mock_api_request(params=None):
    """Mocks an APIRequest (as in pygeoapi's tests/util.py)"""

    environ = create_environ(base_url='http://localhost:5000/')
    request = Request(environ)
    request.args = ImmutableMultiDict((params or {}).items())
    return APIRequest.from_flask(request, supported_locales=['en-US'])


@pytest.fixture()
def config(monkeypatch):
    monkeypatch.chdir(os.path.dirname(HERE))
    with open(os.path.join(HERE, 'data', 'pygeoapi-test-config.yml')) as fh:
        return yaml_load(fh)


@pytest.fixture()
def api_(config):
    return API(config, get_oas(config))


def items(api_, collection, **params):
    headers, status, content = get_collection_items(
        api_, mock_api_request({'f': 'json', **params}), collection)
    return status, json.loads(content)


def test_config_is_valid(config):
    assert validate_config(config)


def test_openapi(config):
    openapi = get_oas(config)
    assert '/collections/observations/items' in openapi['paths']
    assert '/collections/empty/items' in openapi['paths']
    assert '/collections/notes/items' in openapi['paths']


def test_collections(api_):
    headers, status, content = describe_collections(
        api_, mock_api_request({'f': 'json'}))
    assert status == HTTPStatus.OK
    ids = [c['id'] for c in json.loads(content)['collections']]
    assert ids == ['observations', 'empty', 'notes']


def test_items(api_):
    status, content = items(api_, 'observations')
    assert status == HTTPStatus.OK
    assert content['numberMatched'] == 3
    assert content['numberReturned'] == 3
    assert content['features'][0]['properties']['seen'] == '2026-05-01'

    status, content = items(api_, 'observations', limit=1, offset=1)
    assert [f['id'] for f in content['features']] == ['obs-2']
    assert 'next' in [link['rel'] for link in content['links']]

    status, content = items(api_, 'observations', sortby='-count')
    assert [f['id'] for f in content['features']] == \
        ['obs-2', 'obs-1', 'obs-3']

    status, content = items(api_, 'observations', tags='river')
    assert [f['id'] for f in content['features']] == ['obs-2']

    status, content = items(api_, 'observations', q='royal')
    assert [f['id'] for f in content['features']] == ['obs-1']

    status, content = items(api_, 'observations', bbox='-74,45,-73,46')
    assert [f['id'] for f in content['features']] == ['obs-1']

    status, content = items(api_, 'observations',
                            datetime='2026-06-01/..')
    assert [f['id'] for f in content['features']] == ['obs-2', 'obs-3']

    status, content = items(api_, 'observations',
                            properties='name', skipGeometry='true')
    assert content['features'][0]['properties'] == {'name': 'Mont Royal'}
    assert content['features'][0]['geometry'] is None

    status, content = items(api_, 'observations', resulttype='hits')
    assert content['numberMatched'] == 3
    assert content['features'] == []


def test_items_bad_queries(api_):
    status, content = items(api_, 'observations', sortby='nope')
    assert status == HTTPStatus.BAD_REQUEST

    status, content = items(api_, 'observations', properties='nope')
    assert status == HTTPStatus.BAD_REQUEST


def test_items_html(api_):
    headers, status, content = get_collection_items(
        api_, mock_api_request({'f': 'html'}), 'observations')
    assert status == HTTPStatus.OK
    assert 'Mont Royal' in content


def test_item(api_):
    headers, status, content = get_collection_item(
        api_, mock_api_request({'f': 'json'}), 'observations', 'obs-2')
    assert status == HTTPStatus.OK
    content = json.loads(content)
    assert content['id'] == 'obs-2'
    assert content['geometry']['coordinates'] == [-71.0, 46.9]

    headers, status, content = get_collection_item(
        api_, mock_api_request({'f': 'json'}), 'observations', 'obs-9')
    assert status == HTTPStatus.NOT_FOUND


def test_queryables(api_):
    headers, status, content = get_collection_queryables(
        api_, mock_api_request({'f': 'json'}), 'observations')
    assert status == HTTPStatus.OK
    properties = json.loads(content)['properties']
    assert properties['count']['type'] == 'integer'
    assert properties['seen']['format'] == 'date'
    assert 'lat' not in properties


def test_empty_collection(api_):
    status, content = items(api_, 'empty')
    assert status == HTTPStatus.OK
    assert content['features'] == []
    assert content['numberMatched'] == 0

    headers, status, content = get_collection_queryables(
        api_, mock_api_request({'f': 'json'}), 'empty')
    assert status == HTTPStatus.OK


def test_directory_collection(api_):
    status, content = items(api_, 'notes')
    assert status == HTTPStatus.OK
    assert [f['id'] for f in content['features']] == ['n3', 'n1', 'n2']

    headers, status, content = get_collection_item(
        api_, mock_api_request({'f': 'json'}), 'notes', 'n2')
    assert status == HTTPStatus.OK
    assert json.loads(content)['properties']['text'] == 'Hello'

    headers, status, content = get_collection_item(
        api_, mock_api_request({'f': 'json'}), 'notes', 't1')
    assert status == HTTPStatus.NOT_FOUND
