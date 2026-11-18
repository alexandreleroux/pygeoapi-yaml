# =================================================================
#
# Authors: Alexandre Leroux
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

import json
import os
import time

import pytest

from pygeoapi.provider.base import (ProviderInvalidDataError,
                                    ProviderInvalidQueryError,
                                    ProviderItemNotFoundError)
from pygeoapi_yaml.provider import YAMLProvider


RECORDS = """
# observations, with comments that stay in the file
- id: obs-1
  name: Mont Royal
  lat: 45.5
  lon: -73.6
  count: 3
  score: 1.5
  seen: 2026-05-01
  checked: true
  tags: [birds, park]
- id: obs-2
  name: Île d'Orléans
  lat: 46.9
  lon: -71.0
  count: 10
  score: 2
  seen: 2026-06-15T08:30:00Z
  checked: false
  tags: [river]
- id: obs-3
  name: Somewhere unknown
  count: 1
  notes: >
    A long text, folded
    over two lines.
"""


@pytest.fixture()
def fixture(tmp_path):
    path = tmp_path / 'observations.yaml'
    path.write_text(RECORDS, encoding='utf-8')
    return str(path)


@pytest.fixture()
def config(fixture):
    return {
        'name': 'pygeoapi_yaml.provider.YAMLProvider',
        'type': 'feature',
        'data': fixture,
        'id_field': 'id',
        'time_field': 'seen',
        'geometry': {
            'x_field': 'lon',
            'y_field': 'lat'
        }
    }


def write(path, text):
    """Rewrite a file, making sure its modification time changes"""

    stat = os.stat(path)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


def test_get_fields(config):
    p = YAMLProvider(config)

    fields = p.get_fields()
    assert 'lat' not in fields
    assert 'lon' not in fields
    assert fields['id'] == {'type': 'string'}
    assert fields['name'] == {'type': 'string'}
    assert fields['count'] == {'type': 'integer'}
    # integers and floats mixed
    assert fields['score'] == {'type': 'number'}
    # a date and a timestamp mixed
    assert fields['seen'] == {'type': 'string'}
    assert fields['checked'] == {'type': 'boolean'}
    assert fields['tags'] == {'type': 'array'}
    # found in the last item only
    assert fields['notes'] == {'type': 'string'}


def test_get_fields_dates(tmp_path):
    path = tmp_path / 'dates.yaml'
    path.write_text('- {id: 1, day: 2026-01-02, at: 2026-01-02 10:00:00}\n'
                    '- {id: 2, day: null}\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})

    fields = p.get_fields()
    assert fields['day'] == {'type': 'string', 'format': 'date'}
    assert fields['at'] == {'type': 'string', 'format': 'date-time'}
    assert fields['id'] == {'type': 'integer'}


def test_query(config):
    p = YAMLProvider(config)

    results = p.query()
    assert len(results['features']) == 3
    assert results['numberMatched'] == 3
    assert results['numberReturned'] == 3
    assert results['features'][0]['id'] == 'obs-1'
    assert results['features'][0]['geometry'] == {
        'type': 'Point', 'coordinates': [-73.6, 45.5]}
    assert results['features'][2]['geometry'] is None
    assert 'lat' not in results['features'][0]['properties']

    # YAML dates become ISO 8601 strings
    properties = results['features'][0]['properties']
    assert properties['seen'] == '2026-05-01'
    assert results['features'][1]['properties']['seen'] == \
        '2026-06-15T08:30:00+00:00'
    assert results['features'][2]['properties']['notes'] == \
        'A long text, folded over two lines.\n'
    json.dumps(results)

    results = p.query(offset=1, limit=1)
    assert results['numberMatched'] == 3
    assert results['numberReturned'] == 1
    assert results['features'][0]['id'] == 'obs-2'

    results = p.query(resulttype='hits')
    assert results['numberMatched'] == 3
    assert len(results['features']) == 0

    results = p.query(select_properties=['name'])
    assert results['features'][0]['properties'] == {'name': 'Mont Royal'}

    results = p.query(skip_geometry=True)
    assert results['features'][0]['geometry'] is None


def test_query_properties(config):
    p = YAMLProvider(config)

    results = p.query(properties=[('name', 'Mont Royal')])
    assert [f['id'] for f in results['features']] == ['obs-1']

    # values in a URL are strings
    results = p.query(properties=[('count', '10')])
    assert [f['id'] for f in results['features']] == ['obs-2']

    results = p.query(properties=[('score', '1.5')])
    assert [f['id'] for f in results['features']] == ['obs-1']

    results = p.query(properties=[('checked', 'false')])
    assert [f['id'] for f in results['features']] == ['obs-2']

    # a list matches if one of its values does
    results = p.query(properties=[('tags', 'park')])
    assert [f['id'] for f in results['features']] == ['obs-1']

    results = p.query(properties=[('seen', '2026-05-01')])
    assert [f['id'] for f in results['features']] == ['obs-1']

    results = p.query(properties=[('tags', 'park'), ('count', '10')])
    assert results['numberMatched'] == 0

    with pytest.raises(ProviderInvalidQueryError):
        p.query(properties=[('nope', 'x')])


def test_query_bbox(config):
    p = YAMLProvider(config)

    results = p.query(bbox=[-74, 45, -73, 46])
    assert [f['id'] for f in results['features']] == ['obs-1']

    results = p.query(bbox=[-74, 45, -73, 46, 0, 0])
    assert [f['id'] for f in results['features']] == ['obs-1']

    # items without geometry are not in any bbox
    results = p.query(bbox=[-180, -90, 180, 90])
    assert results['numberMatched'] == 2

    results = p.query(bbox=[120, 10, 126, 11])
    assert results['numberMatched'] == 0
    assert results['numberReturned'] == 0


def test_query_sortby(config):
    p = YAMLProvider(config)

    results = p.query(sortby=[{'property': 'count', 'order': '-'}])
    assert [f['id'] for f in results['features']] == \
        ['obs-2', 'obs-1', 'obs-3']

    results = p.query(sortby=[{'property': 'name', 'order': '+'}])
    assert [f['id'] for f in results['features']] == \
        ['obs-1', 'obs-3', 'obs-2']

    # items without the property come last, in either order
    for order in '+-':
        results = p.query(sortby=[{'property': 'checked', 'order': order}])
        assert results['features'][2]['id'] == 'obs-3'

    with pytest.raises(ProviderInvalidQueryError):
        p.query(sortby=[{'property': 'nope', 'order': '+'}])


def test_query_sortby_several(tmp_path):
    path = tmp_path / 'sort.yaml'
    path.write_text('- {id: a, kind: x, n: 2}\n'
                    '- {id: b, kind: y, n: 1}\n'
                    '- {id: c, kind: x, n: 1}\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})

    results = p.query(sortby=[{'property': 'kind', 'order': '+'},
                              {'property': 'n', 'order': '-'}])
    assert [f['id'] for f in results['features']] == ['a', 'c', 'b']


def test_query_q(config):
    p = YAMLProvider(config)

    results = p.query(q='royal')
    assert [f['id'] for f in results['features']] == ['obs-1']

    # commas separate alternatives
    results = p.query(q='royal,orléans')
    assert [f['id'] for f in results['features']] == ['obs-1', 'obs-2']

    # spaces separate words that must all be found
    results = p.query(q='long folded')
    assert [f['id'] for f in results['features']] == ['obs-3']

    results = p.query(q='long royal')
    assert results['numberMatched'] == 0

    # text in lists too
    results = p.query(q='river')
    assert [f['id'] for f in results['features']] == ['obs-2']


def test_query_datetime(config):
    p = YAMLProvider(config)

    results = p.query(datetime_='2026-05-01')
    assert [f['id'] for f in results['features']] == ['obs-1']

    results = p.query(datetime_='2026-06-01/..')
    assert [f['id'] for f in results['features']] == ['obs-2']

    results = p.query(datetime_='../2026-06-01')
    assert [f['id'] for f in results['features']] == ['obs-1']

    results = p.query(datetime_='2026-01-01T00:00:00Z/2026-12-31T00:00:00Z')
    assert [f['id'] for f in results['features']] == ['obs-1', 'obs-2']

    with pytest.raises(ProviderInvalidQueryError):
        p.query(datetime_='yesterday')


def test_get(config):
    p = YAMLProvider(config)

    result = p.get('obs-2')
    assert isinstance(result, dict)
    assert result['properties']['name'] == "Île d'Orléans"
    assert result['geometry']['coordinates'] == [-71.0, 46.9]


def test_get_not_existing_item_raise_exception(config):
    """Testing query for a not existing object"""
    p = YAMLProvider(config)
    with pytest.raises(ProviderItemNotFoundError):
        p.get('obs-4')


def test_no_count(config):
    config['count'] = False
    p = YAMLProvider(config)

    results = p.query()
    assert 'numberMatched' not in results
    assert results['numberReturned'] == 3


def test_results_are_copies(config):
    p = YAMLProvider(config)

    results = p.query()
    results['features'][0]['properties']['name'] = 'changed'
    results['features'][0]['geometry']['coordinates'][0] = 0

    result = YAMLProvider(config).get('obs-1')
    assert result['properties']['name'] == 'Mont Royal'
    assert result['geometry']['coordinates'] == [-73.6, 45.5]


def test_reload_on_change(fixture, config):
    p = YAMLProvider(config)
    assert p.query()['numberMatched'] == 3

    write(fixture, RECORDS + '- {id: obs-4, name: New, color: red}\n')

    # the same provider sees the new item
    assert p.query()['numberMatched'] == 4
    assert p.get('obs-4')['properties']['name'] == 'New'

    # a new provider (pygeoapi makes one per request) sees the new field
    assert 'color' in YAMLProvider(config).get_fields()


def test_cache(fixture, config, monkeypatch):
    YAMLProvider(config).query()

    def fail(*args, **kwargs):
        raise AssertionError('parsed again')

    monkeypatch.setattr('pygeoapi_yaml.provider.yaml.safe_load', fail)
    assert YAMLProvider(config).query()['numberMatched'] == 3


def test_items_key(tmp_path):
    path = tmp_path / 'places.yaml'
    path.write_text('title: Places\n'
                    'places:\n'
                    '  - {code: 1, name: One}\n'
                    '  - {code: 2, name: Two}\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature', 'data': str(path),
                      'id_field': 'code', 'items_key': 'places'})

    results = p.query()
    assert results['numberMatched'] == 2
    assert results['features'][1]['id'] == 2
    assert results['features'][1]['geometry'] is None
    assert p.get('2')['properties']['name'] == 'Two'

    # a mapping without items_key
    with pytest.raises(ProviderInvalidDataError):
        YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'code'})


def test_geometry_field(tmp_path):
    path = tmp_path / 'shapes.yaml'
    path.write_text('- id: a\n'
                    '  shape:\n'
                    '    type: LineString\n'
                    '    coordinates: [[0, 0], [2, 2]]\n'
                    '- id: b\n'
                    '  shape: not a geometry\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature', 'data': str(path),
                      'id_field': 'id', 'geometry': {'field': 'shape'}})

    assert 'shape' not in p.get_fields()
    results = p.query()
    assert results['features'][0]['geometry']['type'] == 'LineString'
    assert results['features'][1]['geometry'] is None
    assert p.query(bbox=[1, 1, 3, 3])['numberMatched'] == 1


def test_feature_collection(tmp_path):
    path = tmp_path / 'collection.yaml'
    path.write_text('type: FeatureCollection\n'
                    'features:\n'
                    '  - type: Feature\n'
                    '    id: 123-456\n'
                    '    geometry: {type: Point, coordinates: [125.6, 10.1]}\n'
                    '    properties: {name: Dinagat Islands, foo: bar}\n'
                    '  - type: Feature\n'
                    '    geometry: null\n'
                    '    properties: {code: x-1, name: No geometry}\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'code'})

    assert p.get_fields() == {'name': {'type': 'string'},
                              'foo': {'type': 'string'},
                              'code': {'type': 'string'}}
    results = p.query(bbox=[120, 10, 126, 11])
    assert [f['id'] for f in results['features']] == ['123-456']
    assert p.get('x-1')['properties']['name'] == 'No geometry'


def test_ids(tmp_path):
    path = tmp_path / 'ids.yaml'
    path.write_text('- {name: first}\n'
                    '- {name: second}\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature', 'data': str(path)})

    # without id_field, an item's id is its position
    assert [f['id'] for f in p.query()['features']] == [0, 1]
    assert p.get('1')['properties']['name'] == 'second'


@pytest.mark.parametrize('text', ['', '# nothing yet\n', '[]\n'])
def test_empty(tmp_path, text):
    path = tmp_path / 'empty.yaml'
    path.write_text(text)
    p = YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})

    assert p.get_fields() == {}
    results = p.query()
    assert results['features'] == []
    assert results['numberMatched'] == 0
    assert results['numberReturned'] == 0


def test_missing_file(tmp_path):
    p = YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(tmp_path / 'nope.yaml'), 'id_field': 'id'})

    assert p.get_fields() == {}
    assert p.query()['numberMatched'] == 0


def test_invalid_yaml(tmp_path):
    path = tmp_path / 'invalid.yaml'
    path.write_text('- id: 1\n  name: [unclosed\n')

    with pytest.raises(ProviderInvalidDataError):
        YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})


def test_no_python_objects(tmp_path):
    """A YAML file can never run code: safe_load refuses Python tags"""
    path = tmp_path / 'unsafe.yaml'
    path.write_text('- id: 1\n'
                    '  name: !!python/object/apply:os.system ["true"]\n')

    with pytest.raises(ProviderInvalidDataError):
        YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})


def test_not_a_list(tmp_path):
    path = tmp_path / 'scalar.yaml'
    path.write_text('just text\n')

    with pytest.raises(ProviderInvalidDataError):
        YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})


def test_items_not_mappings_are_skipped(tmp_path):
    path = tmp_path / 'mixed.yaml'
    path.write_text('- {id: a}\n- just text\n- {id: b}\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})

    assert [f['id'] for f in p.query()['features']] == ['a', 'b']


def test_binary(tmp_path):
    path = tmp_path / 'binary.yaml'
    path.write_text('- {id: a, data: !!binary aGVsbG8=}\n')
    p = YAMLProvider({'name': 'YAML', 'type': 'feature',
                      'data': str(path), 'id_field': 'id'})

    assert p.get('a')['properties']['data'] == 'aGVsbG8='


def test_get_domains(config):
    p = YAMLProvider(config)

    domains, current = p.get_domains(['count', 'checked'])
    assert current is True
    assert domains['count'] == [1, 3, 10]
    assert domains['checked'] == [False, True]


def test_geometry_config(fixture):
    with pytest.raises(RuntimeError):
        YAMLProvider({'name': 'YAML', 'type': 'feature', 'data': fixture,
                      'geometry': {'x_field': 'lon'}})

    with pytest.raises(RuntimeError):
        YAMLProvider({'name': 'YAML', 'type': 'feature', 'data': fixture,
                      'geometry': {'x_field': 'lon', 'y_field': 'lat',
                                   'field': 'shape'}})


def test_repr(config):
    assert repr(YAMLProvider(config)).startswith('<YAMLProvider>')


def test_large_file_parsed_once(tmp_path, monkeypatch):
    path = tmp_path / 'large.yaml'
    path.write_text(''.join(f'- {{id: {i}, name: item {i}}}\n'
                            for i in range(5000)))
    config = {'name': 'YAML', 'type': 'feature',
              'data': str(path), 'id_field': 'id'}
    YAMLProvider(config)

    start = time.perf_counter()
    for _ in range(20):
        YAMLProvider(config).query(limit=10)
    assert time.perf_counter() - start < 2


def test_subclass(fixture, config):
    """A subclass can change how items become features"""

    class Uppercase(YAMLProvider):
        def _features(self, document):
            features = super()._features(document)
            for feature in features:
                name = feature['properties'].get('name')
                feature['properties']['name'] = (name or '').upper()
            return features

    assert Uppercase(config).get('obs-1')['properties']['name'] == \
        'MONT ROYAL'
    # each class keeps its own parsed copy of the same file
    assert YAMLProvider(config).get('obs-1')['properties']['name'] == \
        'Mont Royal'
