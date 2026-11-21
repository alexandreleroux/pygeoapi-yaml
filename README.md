# pygeoapi-yaml

A [pygeoapi](https://pygeoapi.io) provider for YAML files. pygeoapi reads the YAML
file directly, so you don't need to convert it to GeoJSON first.

YAML and JSON map almost one to one, so GeoJSON can be written in YAML as it is:
a FeatureCollection in a YAML file is served unchanged. YAML adds what is pleasant
when you keep data by hand: comments, long texts that stay readable, and clean
diffs in git. Data kept by hand is often a plain list of records, as in a CSV
file, so the provider reads that too: you say where the id and the geometry are.

This provider publishes such a file as an OGC API - Features collection. The YAML
file stays the source of truth. pygeoapi answers in GeoJSON, as it does for every
other provider.

**Status: alpha, read-only.** See [Status and roadmap](#status-and-roadmap).

## Install

```bash
pip install pygeoapi-yaml
```

It needs pygeoapi 0.24 or later, in the same Python environment.

## Configure

Declare the provider in your pygeoapi configuration by its Python path. A file
can be written in one of three ways.

### A list of records, with coordinates in two fields

```yaml
# observations.yaml
- id: obs-1
  name: Mont Royal
  lat: 45.5
  lon: -73.6
  seen: 2026-05-01
  tags: [birds, park]
- id: obs-2
  name: Somewhere unknown   # no coordinates: geometry is null
  seen: 2026-07-20
```

```yaml
providers:
  - type: feature
    name: pygeoapi_yaml.provider.YAMLProvider
    data: /data/observations.yaml
    id_field: id
    title_field: name
    time_field: seen          # optional, enables ?datetime=
    geometry:                 # optional, as in the CSV provider
      x_field: lon
      y_field: lat
```

### Records under a key, with a GeoJSON geometry in a field

```yaml
# trails.yaml
title: Trails
trails:
  - code: T1
    name: Lakeshore
    path:
      type: LineString
      coordinates: [[-73.60, 45.50], [-73.58, 45.51]]
```

```yaml
providers:
  - type: feature
    name: pygeoapi_yaml.provider.YAMLProvider
    data: /data/trails.yaml
    items_key: trails         # where the list is
    id_field: code
    geometry:
      field: path             # a GeoJSON geometry
```

With no `geometry` setting at all, every item is served with `geometry: null`.
This is fine for data that isn't spatial.

### A GeoJSON FeatureCollection, written in YAML

```yaml
type: FeatureCollection
features:
  - type: Feature
    id: 123-456
    geometry: {type: Point, coordinates: [125.6, 10.1]}
    properties: {name: Dinagat Islands}
```

This needs no setting beyond `data`. `id_field` is used only for features
without an `id`.

### A directory of YAML files

`data` can also be a directory. All the YAML files under it, in its
subdirectories too, make one collection:
- each file can hold items in any of the layouts above;
- or a file can be a single item, written as a mapping (without `items_key`).

```text
notes/
  home.yaml               # page: /home, notes: [...]
  guides/install.yaml
  template.yaml           # left out, see exclude
```

```yaml
providers:
  - type: feature
    name: pygeoapi_yaml.provider.YAMLProvider
    data: /data/notes
    items_key: notes          # in each file
    id_field: id
    pattern: '*.yaml'         # the default
    exclude:                  # file names or paths in the directory
      - template.yaml
```

Items come in the order of their files' paths (`guides/install.yaml` before
`home.yaml`). Hidden files and directories (starting with `.`) are skipped.
An invalid file is logged and left out, and the others are still served.

## Behaviour

- **Queries.** All of these are supported:
  - `limit` and `offset`;
  - `resulttype=hits`;
  - property filters (`?name=...`);
  - `bbox`;
  - `datetime` (an instant or an interval, open with `..`, on `time_field`);
  - `sortby` (several properties allowed);
  - `q`;
  - `properties` (select properties);
  - `skipGeometry`;
  - `count: false`.
- **Field types** are read from all items. Integers and floats in the same field
  give `number`. Other mixed types give `string`. YAML dates give
  `string` with format `date` or `date-time`, so the queryables are right.
- **YAML values JSON lacks** are converted in responses:
  - dates and timestamps become ISO 8601 strings;
  - `!!binary` becomes base64.
- **Property filters** compare typed values: `?count=10` matches `10` and `10.0`,
  and `?checked=true` matches a YAML `true`. If the field holds a list, the filter
  matches when the list contains the value (`?tags=park`).
- **`q`** follows OGC API - Records:
  - commas separate alternatives;
  - spaces separate words that must all be found.
  
  The search ignores case and looks in every text value, including values in
  lists and nested mappings.
- **`bbox`** never matches an item without geometry. The OGC API - Features
  specification asks for this. pygeoapi's GeoJSON and CSV providers include such
  items instead.
- **Sorting** puts items without the property last, whether the order is
  ascending or descending.
- **Ids** come from `id_field`. An item without one gets its position in the list
  as its id, and a warning is logged, as are duplicate ids.
- **Changes are seen at once.** Each file is parsed once, then kept in memory
  until its modification time or size changes. For a directory, the provider also
  re-reads the files when one is added or removed, including a file that isn't YAML.
  No restart is needed. pygeoapi creates a provider for each request, so the
  parsed copy is shared between them.
- **Empty files** (empty, only comments, or `[]`) and **missing files** give an
  empty collection, not an error.
- **Safe parsing.** The provider uses `yaml.safe_load`, so a YAML file can never
  build Python objects or run code. An invalid file gives an error response, with
  the details in the log.
- **Read-only.** OGC API - Features - Part 4 (create, replace, update, delete) is
  not implemented yet. See the roadmap.

## Extending

To read another layout, or to compute properties, subclass `YAMLProvider` and
override `_features(document, path)`. It receives a parsed YAML document and the
path of its file, and returns GeoJSON features. With a directory, it is called
once for each file. In the features it returns:
- values can still be YAML values, such as dates;
- an `id` can be `None`.

The provider still takes care of the rest: ids, field types, conversion to JSON,
queries and caching. Each subclass keeps its own parsed copy of a file.

```python
from pygeoapi_yaml.provider import YAMLProvider


class MyProvider(YAMLProvider):
    def _features(self, document, path):
        features = super()._features(document, path)
        for feature in features:
            feature['properties']['label'] = feature['properties']['name'].upper()
        return features
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/flake8 pygeoapi_yaml tests
```

There are two kinds of tests:
- `tests/test_yaml_provider.py` tests the provider on its own, in the style of
  pygeoapi's provider tests.
- `tests/test_api.py` goes through pygeoapi itself:
  - the configuration is validated against pygeoapi's schema;
  - the OpenAPI document is generated;
  - `/collections`, `/items`, `/items/{id}`, the queryables, an empty
    collection and a directory are checked.

See [CONTRIBUTING.md](https://github.com/alexandreleroux/pygeoapi-yaml/blob/main/CONTRIBUTING.md) before opening a pull request.

## Status and roadmap

Done (0.1.0, on PyPI):

- [x] Read-only provider: `get_fields`, `query`, `get` and `get_domains`.
- [x] Three file layouts: records, records under `items_key`, a FeatureCollection.
- [x] Geometry from `x_field`/`y_field`, from a GeoJSON field, or none.
- [x] Every query parameter pygeoapi passes to a feature provider.
- [x] The file is read again when it changes; its parsed copy is shared between
  requests.
- [x] Subclassing: override `_features()` to read another layout.
- [x] Tests for the provider alone and through pygeoapi, checked by mutation
  testing (each deliberate bug in the provider makes a test fail).
- [x] Continuous integration: pytest and flake8 on Python 3.12 and 3.13.

Done (0.2.0, on PyPI):

- [x] A directory of YAML files as a single collection: items in each file, or
  one item per file; `pattern` and `exclude`; read again when a file is added,
  changed or removed.
- [x] `_features(document, path)`: subclasses get the path of each file. In
  0.1.0 it was `_features(document)`.

Next:

- [ ] CI on both the oldest supported pygeoapi and the latest. For now they are
  the same: 0.24 is both the minimum and the latest release.
- [ ] Listing on the
  [pygeoapi community plugins page](https://github.com/geopython/pygeoapi/wiki/CommunityPluginsThemes).
- [ ] A `cql2` filter (`filter=`), through pygeofilter, as other providers do.
- [ ] Writing (OGC API - Features - Part 4). This only comes with
  [ruamel.yaml](https://yaml.dev/doc/ruamel.yaml/), so that comments and
  formatting survive a write. Otherwise a write would erase them.
- [ ] Then, on top of it, a catalogue of
  [pygeometa](https://geopython.github.io/pygeometa) MCF files (YAML metadata,
  one record per file) served as OGC API - Records.

## Authorship

Most of the code, tests and documentation were written by Claude, an AI model
made by Anthropic, working in [Claude Code](https://claude.com/claude-code).
Alexandre Leroux started the project, set its goals and made its design
decisions, and directed the work. Commits written with Claude carry a
`Co-Authored-By: Claude` trailer.

Whoever types the code, it is held to the same checks: each behaviour has a
test, some tests go through pygeoapi itself, and mutation testing shows that the
tests catch deliberate bugs.

## License

MIT, like pygeoapi. See [LICENSE](https://github.com/alexandreleroux/pygeoapi-yaml/blob/main/LICENSE).
