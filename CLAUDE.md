# sdk-usda-nass — instructions for Claude Code

`xippios-usda-nass` wraps USDA NASS Quick Stats as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file is the contract for every session
that works here; the family rules it points to apply as well.

@.claude/family.md

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA NASS Quick Stats, https://quickstats.nass.usda.gov |
| API base URL | `https://quickstats.nass.usda.gov/api` |
| Documentation | https://quickstats.nass.usda.gov/api, snapshotted in `docs/upstream/` |
| Credentials | `NASS_API_KEY` from the environment, sent as the `key` query parameter |
| Rate limit | 30 requests per minute, burst 1; a self-imposed pace, upstream documents none (ADR-0010); enforced client-side in `_client.py` |
| Write tools | no, this package is read-only |

The snapshot in `docs/upstream/` is the reference for names, parameters and semantics.

## Layout

```
src/xippios/usda/nass/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the one configured AsyncClient (base URL, key, rate limit)
  models.py        pydantic models mirroring upstream payloads (UpstreamModel)
  api/             endpoint wrappers, one module per upstream operation
  tasks.py         task functions; __all__ is what the adapters register, but BULK_TASKS,
                   the Python-only ones; MCP_CAPS any per-tool result caps
  mcp.py           xippios-usda-nass-mcp entry point
  http.py          FastAPI router
  params.py        the packaged reference lists, read from reference/
  enums.py         StrEnums (IntEnums for integer ids) generated from the packaged lists;
                   never edited by hand
  reference/       packaged code lists (CSV/JSON) plus README with provenance
scripts/
  refresh_reference.py   fetches the packaged lists through api/ and regenerates enums.py
  refresh_upstream.py    captures docs/upstream/, the api and param_define pages as Markdown,
                         and writes FETCHED.md (/refresh-upstream)
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <endpoint>/<case>.json, never hand-written
  test_family.py   core's family check, one line: namespace levels, py.typed, __version__,
                   the adapters serving exactly the tasks, task shapes and docstrings, the
                   README status table, the template tag, the core bound
  test_tasks.py    per-task replay tests
  test_live.py     @pytest.mark.live smoke tests, one per task
docs/upstream/     documentation snapshot and FETCHED.md
.github/workflows/ ci.yml (the required ci check, with the CHANGELOG and fixture-size steps),
                   publish.yml (the release train: tag, build, PyPI), live.yml (nightly live
                   tests), gates.yml (the merge gates as jobs, off until GATES_CALLER is 1)
                   siblings.yml (the sibling proof of ADR-0006: this wheel beside the
                   siblings under xippios.usda, a visible check the ruleset does not require)
.github/scripts/   check-siblings.sh, which siblings.yml runs; the template's, as is the workflow
.claude/family.md  the family rules, the template's, imported above
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep,
                   adopt-release
```

`src/xippios/` has **no** `__init__.py`: it is a PEP 420 namespace package shared with
`xippios-core` and every other source package, and so is every level
between it and the package (`src/xippios/usda/`). The import path is
`xippios.usda.nass` (ADR-0006).

## Commands

```bash
uv run pytest -m live --tb=short   # needs XIPPIOS_LIVE_TESTS=1 and NASS_API_KEY

uv run xippios-usda-nass-mcp   # stdio; add --http for streamable HTTP
```

The offline run sends the key's placeholder, with `NASS_API_KEY` set to it because
`pyproject.toml` names that variable under `xippios_placeholder_key_envs`; the package
keeps no placeholder fixture of its own.

`.github/workflows/live.yml` runs `uv run pytest -m live --tb=short` with
`XIPPIOS_LIVE_TESTS=1` nightly at 01:51 UTC, a time derived from the slug so that sources
sharing a key never start together, and on demand from the Actions tab; pull requests
never run live tests. Only its `uv run pytest -m live --tb=short` step sees the key, from
the org secret `NASS_API_KEY`.
