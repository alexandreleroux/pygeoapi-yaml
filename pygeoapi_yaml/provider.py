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

import base64
from copy import deepcopy
from datetime import date, datetime, time, timezone
import logging
import os
import threading

from dateutil.parser import isoparse
from shapely.geometry import box, shape
import yaml

from pygeoapi.crs import crs_transform
from pygeoapi.provider.base import (BaseProvider, ProviderInvalidDataError,
                                    ProviderInvalidQueryError,
                                    ProviderItemNotFoundError)

LOGGER = logging.getLogger(__name__)

# pygeoapi creates a provider object for each request: parsed files are
# kept here, shared by all of them, and parsed again only when the
# file's modification time or size has changed
_CACHE = {}
_CACHE_LOCK = threading.Lock()


class YAMLProvider(BaseProvider):
    """Provider class backed by local YAML files

    The file holds either:

    * a list of records (mappings), at the top level of the document
      or under the key named by `items_key`
    * a GeoJSON FeatureCollection, written in YAML

    For records, the geometry is optional: a point built from two
    fields (`geometry.x_field`, `geometry.y_field`, as in the CSV
    provider), a field holding a GeoJSON geometry (`geometry.field`),
    or none (`geometry: null` in responses).

    Read-only. The file is read again as soon as it changes, without
    restarting pygeoapi. YAML is parsed with `yaml.safe_load`: no
    Python objects are ever built from the file.

    Values YAML parses natively and JSON lacks are converted in
    responses: dates and timestamps to ISO 8601 strings, binary to
    base64 strings.
    """

    def __init__(self, provider_def):
        """
        Initialize object

        :param provider_def: provider definition

        :returns: pygeoapi_yaml.provider.YAMLProvider
        """

        super().__init__(provider_def)

        geometry = provider_def.get('geometry') or {}
        self.geometry_x = geometry.get('x_field')
        self.geometry_y = geometry.get('y_field')
        self.geometry_field = geometry.get('field')
        if bool(self.geometry_x) != bool(self.geometry_y):
            msg = 'geometry needs both x_field and y_field'
            LOGGER.error(msg)
            raise RuntimeError(msg)
        if self.geometry_field and self.geometry_x:
            msg = 'geometry takes either field or x_field/y_field'
            LOGGER.error(msg)
            raise RuntimeError(msg)

        self.items_key = provider_def.get('items_key')

        self.get_fields()

    def get_fields(self):
        """
         Get provider field information (names, types)

        Types are read from all items: a field holding integers and
        floats is a number; a field holding values of other, mixed
        types is a string.

        :returns: dict of fields
        """

        if not self._fields:
            self._fields = deepcopy(self._read()['fields'])

        return self._fields

    def get_domains(self, properties=[], current=False):
        """
        Get domains from dataset

        :param properties: `list` of property names
        :param current: `bool` of whether to provide list of live
                        values (default `False`)

        :returns: `tuple` of domains and whether they are based on the
                  current/live dataset
        """

        domains = {}
        keys = properties or self.fields.keys()

        for key in keys:
            values = set()
            for feature in self._read()['features']:
                value = feature['properties'].get(key)
                if isinstance(value, (bool, int, float, str)):
                    values.add(value)
            if values:
                domains[key] = sorted(values, key=_sort_key)

        return domains, True

    def _read(self):
        """
        Read and parse the YAML file at self.data, or return the
        copy parsed earlier if the file has not changed since

        :returns: `dict` of features (JSON-ready) and fields
        """

        try:
            stat = os.stat(self.data)
        except FileNotFoundError:
            LOGGER.warning(f'File {self.data} does not exist.')
            return {'features': [], 'fields': {}}

        key = (type(self), os.path.abspath(self.data), self.items_key,
               self.id_field, self.geometry_x, self.geometry_y,
               self.geometry_field)
        stamp = (stat.st_mtime_ns, stat.st_size)

        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached and cached[0] == stamp:
            return cached[1]

        LOGGER.debug(f'Parsing {self.data}')
        try:
            with open(self.data, encoding='utf-8') as fh:
                document = yaml.safe_load(fh)
        except (yaml.YAMLError, UnicodeDecodeError) as err:
            msg = f'Invalid YAML file {self.data}'
            LOGGER.error(f'{msg}: {err}')
            raise ProviderInvalidDataError(msg)

        parsed = self._parse(document)

        with _CACHE_LOCK:
            _CACHE[key] = (stamp, parsed)

        return parsed

    def _parse(self, document):
        """
        Turn a parsed YAML document into JSON-ready GeoJSON features,
        and read the fields from them

        :param document: the parsed YAML document

        :returns: `dict` of features (JSON-ready) and fields
        """

        features = []
        fields = {}
        ids = set()

        for index, feature in enumerate(self._features(document)):
            identifier = feature.get('id')
            if identifier is None:
                LOGGER.warning(f'Item {index} has no id, using its position')
                identifier = index
            if str(identifier) in ids:
                LOGGER.warning(f'Duplicate id {identifier}')
            ids.add(str(identifier))

            properties = feature.get('properties') or {}
            for name, value in properties.items():
                _add_field(fields, str(name), value)

            features.append({
                'type': 'Feature',
                'id': _jsonable(identifier),
                'geometry': _jsonable(feature.get('geometry')),
                'properties': _jsonable(properties)
            })

        for field in fields.values():
            field.pop('_unset', None)

        return {'features': features, 'fields': fields}

    def _features(self, document):
        """
        Find the items of a parsed YAML document, as GeoJSON features

        Override this in a subclass to read another layout, or to
        compute properties: values may still be YAML values (dates…),
        and an id may be `None` (the item's position is then used).

        :param document: the parsed YAML document

        :returns: list of `dict` of GeoJSON features
        """

        if document is None:
            return []

        if isinstance(document, dict) and \
           document.get('type') == 'FeatureCollection':
            items = document.get('features') or []
            is_collection = True
        else:
            is_collection = False
            if self.items_key:
                if not isinstance(document, dict):
                    msg = f'{self.data}: items_key set, but not a mapping'
                    LOGGER.error(msg)
                    raise ProviderInvalidDataError(msg)
                items = document.get(self.items_key) or []
            else:
                items = document

        if not isinstance(items, list):
            msg = f'{self.data}: no list of items found (set items_key?)'
            LOGGER.error(msg)
            raise ProviderInvalidDataError(msg)

        features = []

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                LOGGER.warning(f'Item {index} is not a mapping, skipping')
                continue

            if is_collection:
                properties = dict(item.get('properties') or {})
                geometry = item.get('geometry')
                identifier = item.get('id')
                if identifier is None and self.id_field:
                    identifier = properties.get(self.id_field)
            else:
                properties = dict(item)
                geometry = self._geometry(properties, index)
                identifier = properties.get(self.id_field) \
                    if self.id_field else None

            features.append({
                'type': 'Feature',
                'id': identifier,
                'geometry': geometry,
                'properties': properties
            })

        return features

    def _geometry(self, properties, index):
        """
        Take the geometry out of a record

        :param properties: `dict` of the record (geometry fields are
                           removed from it)
        :param index: position of the record, for log messages

        :returns: `dict` of GeoJSON geometry, or `None`
        """

        if self.geometry_field:
            geometry = properties.pop(self.geometry_field, None)
            if geometry is not None and not _is_geometry(geometry):
                LOGGER.warning(f'Item {index}: invalid geometry, ignored')
                geometry = None
            return geometry

        if self.geometry_x:
            x = properties.pop(self.geometry_x, None)
            y = properties.pop(self.geometry_y, None)
            if x is None and y is None:
                return None
            try:
                return {
                    'type': 'Point',
                    'coordinates': [float(x), float(y)]
                }
            except (TypeError, ValueError):
                LOGGER.warning(f'Item {index}: invalid coordinates, ignored')
                return None

        return None

    def _load(self, bbox=[], datetime_=None, properties=[], sortby=[],
              q=None):
        """
        Select and sort the features of the YAML file

        :param bbox: bounding box [minx,miny,maxx,maxy]
        :param datetime_: temporal (datestamp or extent)
        :param properties: list of tuples (name, value)
        :param sortby: list of dicts (property, order)
        :param q: full-text search term(s)

        :returns: list of GeoJSON features (shared: do not modify)
        """

        features = self._read()['features']

        if properties:
            LOGGER.debug('processing properties parameter')
            for name, _ in properties:
                if name not in self.fields:
                    msg = 'Invalid query: invalid property name'
                    LOGGER.error(msg)
                    raise ProviderInvalidQueryError(msg)
            features = [f for f in features if all(
                _equals(f['properties'].get(name), value)
                for name, value in properties)]

        if datetime_ is not None:
            if self.time_field is None:
                LOGGER.debug('time_field not set, ignoring datetime')
            else:
                LOGGER.debug('processing datetime parameter')
                features = self._filter_datetime(features, datetime_)

        if q:
            LOGGER.debug('processing q parameter')
            features = [f for f in features if _search(f['properties'], q)]

        if bbox:
            LOGGER.debug('processing bbox parameter')
            if len(bbox) > 4:
                LOGGER.debug('bbox reduced to 4 elements')
                bbox = bbox[:4]
            area = box(*bbox)
            features = [f for f in features
                        if self._intersects(f['geometry'], area)]

        if sortby:
            LOGGER.debug('processing sortby parameter')
            features = list(features)
            for sort in reversed(sortby):
                name = sort['property']
                if name not in self.fields:
                    msg = 'Invalid query: invalid sortby property'
                    LOGGER.error(msg)
                    raise ProviderInvalidQueryError(msg)
                reverse = sort.get('order') == '-'
                present = [f for f in features
                           if f['properties'].get(name) is not None]
                missing = [f for f in features
                           if f['properties'].get(name) is None]
                present.sort(
                    key=lambda f: _sort_key(f['properties'][name]),
                    reverse=reverse)
                # items without the property come last, in either order
                features = present + missing

        return features

    def _filter_datetime(self, features, datetime_):
        """
        Keep the features whose time_field matches datetime_

        :param features: list of GeoJSON features
        :param datetime_: `str` of instant, or interval with `/`
                          (`..` for an open end)

        :returns: list of GeoJSON features
        """

        try:
            if '/' in datetime_:
                begin, end = datetime_.split('/')
                begin = None if begin in ('', '..') else _instant(begin)
                end = None if end in ('', '..') else _instant(end)
            else:
                begin = end = _instant(datetime_)
        except ValueError:
            msg = 'Invalid query: invalid datetime'
            LOGGER.error(msg)
            raise ProviderInvalidQueryError(msg)

        selected = []
        for feature in features:
            try:
                value = _instant(feature['properties'].get(self.time_field))
            except (TypeError, ValueError):
                continue
            if begin is not None and value < begin:
                continue
            if end is not None and value > end:
                continue
            selected.append(feature)

        return selected

    def _intersects(self, geometry, area):
        """
        Helper function to evaluate feature geometry intersection with a bbox

        :param geometry: `dict` of GeoJSON geometry
        :param area: shapely box of the bbox

        :returns: `bool` of whether geometry intersects with bbox
                  (`False` for a feature without geometry)
        """

        if geometry is None:
            return False

        try:
            return shape(geometry).intersects(area)
        except Exception as err:
            LOGGER.warning(f'Invalid geometry: {err}')
            return False

    def _shape(self, feature, skip_geometry=False, select_properties=[]):
        """
        Copy a feature for a response, with only the requested parts

        :param feature: `dict` of GeoJSON feature
        :param skip_geometry: bool of whether to skip geometry
        :param select_properties: list of property names

        :returns: `dict` of GeoJSON feature
        """

        feature = deepcopy(feature)

        if skip_geometry:
            feature['geometry'] = None

        if self.properties or select_properties:
            keep = set(self.properties) | set(select_properties)
            feature['properties'] = {
                k: v for k, v in feature['properties'].items() if k in keep}

        return feature

    @crs_transform
    def query(self, offset=0, limit=10, resulttype='results',
              bbox=[], datetime_=None, properties=[], sortby=[],
              select_properties=[], skip_geometry=False, q=None, **kwargs):
        """
        query the provider

        :param offset: starting record to return (default 0)
        :param limit: number of records to return (default 10)
        :param resulttype: return results or hit limit (default results)
        :param bbox: bounding box [minx,miny,maxx,maxy]
        :param datetime_: temporal (datestamp or extent)
        :param properties: list of tuples (name, value)
        :param sortby: list of dicts (property, order)
        :param select_properties: list of property names
        :param skip_geometry: bool of whether to skip geometry (default False)
        :param q: full-text search term(s)

        :returns: FeatureCollection dict of 0..n GeoJSON features
        """

        features = self._load(bbox=bbox, datetime_=datetime_,
                              properties=properties, sortby=sortby, q=q)

        feature_collection = {
            'type': 'FeatureCollection',
            'features': []
        }

        if self.count or resulttype == 'hits':
            feature_collection['numberMatched'] = len(features)

        if resulttype == 'hits':
            return feature_collection

        feature_collection['features'] = [
            self._shape(f, skip_geometry, select_properties)
            for f in features[offset:offset + limit]]
        feature_collection['numberReturned'] = len(
            feature_collection['features'])

        return feature_collection

    @crs_transform
    def get(self, identifier, **kwargs):
        """
        query the provider by id

        :param identifier: feature id

        :returns: dict of single GeoJSON feature
        """

        for feature in self._read()['features']:
            if str(feature['id']) == str(identifier):
                return self._shape(feature)

        err = f'item {identifier} not found'
        LOGGER.error(err)
        raise ProviderItemNotFoundError(err)

    def __repr__(self):
        return f'<YAMLProvider> {self.data}'


def _jsonable(value):
    """
    Convert what YAML parses and JSON lacks

    :param value: a value parsed from YAML

    :returns: the value, with dates as ISO 8601 strings and binary
              as base64 strings
    """

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode('ascii')
    return value


def _field_type(value):
    """
    JSON Schema type (and format) of a value parsed from YAML

    :param value: a value parsed from YAML

    :returns: `dict` of type and optional format
    """

    if isinstance(value, bool):
        return {'type': 'boolean'}
    if isinstance(value, int):
        return {'type': 'integer'}
    if isinstance(value, float):
        return {'type': 'number'}
    if isinstance(value, datetime):
        return {'type': 'string', 'format': 'date-time'}
    if isinstance(value, date):
        return {'type': 'string', 'format': 'date'}
    if isinstance(value, (list, tuple, set)):
        return {'type': 'array'}
    if isinstance(value, dict):
        return {'type': 'object'}
    return {'type': 'string'}


def _add_field(fields, name, value):
    """
    Add what a value says about its field to fields

    :param fields: `dict` of fields, updated in place
    :param name: `str` of field name
    :param value: a value of that field

    :returns: `None`
    """

    if value is None:
        fields.setdefault(name, {'type': 'string'})
        fields[name].setdefault('_unset', True)
        return

    type_ = _field_type(value)
    current = fields.get(name)

    if current is None or current.get('_unset'):
        fields[name] = type_
    elif current != type_:
        numbers = {'integer', 'number'}
        if {current['type'], type_['type']} <= numbers:
            fields[name] = {'type': 'number'}
        else:
            fields[name] = {'type': 'string'}


def _is_geometry(value):
    """
    Whether a value looks like a GeoJSON geometry

    :param value: a value parsed from YAML

    :returns: `bool`
    """

    return isinstance(value, dict) and isinstance(value.get('type'), str) \
        and ('coordinates' in value or 'geometries' in value)


def _equals(value, expected):
    """
    Whether a property value matches a query value (always a string
    in a URL); a list matches if one of its values does

    :param value: the property value
    :param expected: the query value

    :returns: `bool`
    """

    if isinstance(value, list):
        return any(_equals(v, expected) for v in value)
    if isinstance(value, bool):
        return str(value).lower() == str(expected).lower()
    if isinstance(value, (int, float)):
        try:
            return float(expected) == value
        except (TypeError, ValueError):
            return False
    return value is not None and str(value) == str(expected)


def _search(properties, q):
    """
    Full-text search, as in OGC API - Records: terms separated by
    commas are alternatives, words separated by spaces must all be
    found; case-insensitive, in all text values (nested included)

    :param properties: `dict` of feature properties
    :param q: `str` of q parameter value

    :returns: `bool`
    """

    text = ' '.join(_texts(properties)).lower()

    for term in q.split(','):
        words = term.lower().split()
        if words and all(word in text for word in words):
            return True

    return False


def _texts(value):
    """
    All text values found in a value

    :param value: a JSON-ready value

    :returns: generator of `str`
    """

    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    elif isinstance(value, list):
        for v in value:
            yield from _texts(v)


def _instant(value):
    """
    A comparable, timezone-aware datetime from an ISO 8601 value

    :param value: `str`, `date` or `datetime`

    :returns: `datetime` (UTC when no timezone is given)
    """

    if isinstance(value, str):
        value = isoparse(value)
    if isinstance(value, datetime):
        pass
    elif isinstance(value, date):
        value = datetime.combine(value, time())
    else:
        raise TypeError(f'not a date: {value!r}')

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value


def _sort_key(value):
    """
    Sort key mixing types without failing: numbers, then text

    :param value: a property value

    :returns: `tuple`
    """

    if isinstance(value, bool):
        return (0, int(value), '')
    if isinstance(value, (int, float)):
        return (0, value, '')
    return (1, 0, str(value))
