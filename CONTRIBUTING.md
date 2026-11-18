# Contributing to pygeoapi-yaml

Thank you for your interest. Issues and pull requests are welcome.

## Before a pull request

For anything beyond a small fix, please open an issue first, so that we can agree
on the change before you write it.

## What a change needs

- **A test for each behaviour.** A test should fail when the behaviour it covers
  is removed. Please check this: break the code on purpose, and see the test
  fail. Tests that go through pygeoapi itself (`tests/test_api.py`) are welcome
  when a change touches what pygeoapi sees.
- **pygeoapi's style.** The provider follows `pygeoapi/provider/geojson.py` and
  `csv_.py`: the same structure, `:param:`/`:returns:` docstrings, the MIT file
  header, the exceptions of `pygeoapi.provider.base`. flake8 must pass.
- **Passing checks.** Run them before you push:

  ```bash
  .venv/bin/pytest
  .venv/bin/flake8 pygeoapi_yaml tests
  ```

- **One coherent change per commit**, with a message that says why.

## AI-assisted contributions

They are welcome. This project is itself written mostly by an AI (see
[Authorship](README.md#authorship)). Two things are asked:

- **Say so.** Add a `Co-Authored-By:` trailer to the commit, or a line in the
  pull request.
- **Stand behind it.** You have run the tests yourself, and you can explain what
  the change does and why. The bar is the same as for any other change.

Note that pygeoapi itself has its own policy
(["By Humans, For Humans"](https://github.com/geopython/pygeoapi/blob/master/CONTRIBUTING.md)).
It applies to contributions to pygeoapi, not to this plugin.

## License

By contributing, you agree that your contributions are licensed under the
[MIT license](LICENSE), like the rest of the project.
