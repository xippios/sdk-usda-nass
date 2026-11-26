# sdk-usda-nass — instructions for Claude Code

`xippios-usda-nass` wraps USDA NASS Quick Stats as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file holds what an agent needs to work on
the package: what it wraps, its layout, its commands and what only it knows. The documents it
follows, sdk-core's conventions among them, are listed under
[`## Documents` in the README](README.md#documents); read them before you change a file. The
rules that no change breaks stand in `.claude/rules/never.md`, which Claude Code loads with
this file.

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA NASS Quick Stats, https://quickstats.nass.usda.gov |
| API base URL | `https://quickstats.nass.usda.gov/api` |
| Documentation | https://quickstats.nass.usda.gov/api, snapshotted in `docs/upstream/` |
| Credentials | `NASS_API_KEY` from the environment, sent as the `key` query parameter |
| Rate limit | 30 requests per minute, burst 1; a self-imposed pace, upstream documents none (sdk-core ADR-0033, decision 1); enforced client-side in `_client.py` |
| Write tools | no, this package is read-only |

The snapshot listed in `docs/upstream/FETCHED.md` is the reference for names, parameters and
semantics; a wrapper is never written from memory of the API.

## Layout

What this package adds to the family's tree, and its import path, stand in `docs/layout.md`,
imported here:

@docs/layout.md

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays the fixtures
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
python3 -I scripts/adr_index.py --check   # the index matches the records in docs/adr/
uv run pytest -m live --tb=short --assert=plain   # needs XIPPIOS_LIVE_TESTS=1, NASS_API_KEY

uv run xippios-usda-nass-mcp   # stdio; add --http for streamable HTTP, and
                               # --split-years YEARS for the split ceiling on the MCP
                               # server (11 years by default, 1 to 20)
```

`.github/workflows/live.yml` runs the live tests nightly at 01:51 UTC, a time derived from
the slug so that sources sharing a key never start together, and on demand; a pull request never runs them.
Only its `uv run pytest -m live --tb=short --assert=plain` step sees the key, from the org secret `NASS_API_KEY`.
Every live run takes `--tb=short --assert=plain`, since the log of `live.yml` is public:
the first keeps a failing test's frame arguments out of it, a raw upstream payload among
them, and the second the values a failed `assert` compares. A live test asserts on shapes
and counts, never on a raw payload.

## Template updates

This repository is generated from sdk-template, at the tag `.copier-answers.yml` records. A
template release reaches it in a pull request of its own, with
`uvx --from 'copier>=9.19' copier update --defaults --vcs-ref=<tag>` (conventions §15). The
update never overwrites a file this package fills, those that `_skip_if_exists` lists in
sdk-template's [`copier.yml`](https://github.com/xippios/sdk-template/blob/main/copier.yml),
and sdk-template's
[CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md) says, per
release, what to port into those by hand in the same pull request.

The update writes every other file it renders again, since they are the template's,
`.claude/rules/never.md` among them. This package keeps no text of its own in them, the
docstring of `mcp.py` included: its own words go into a file it fills. A line it has to
add to one, such as a dependency in `pyproject.toml`, the update carries into the new
render, silently where the release leaves the lines around it alone and as a conflict
where it changes them.

## USDA NASS Quick Stats specifics

What Quick Stats does that `docs/upstream/` does not state stands in
`docs/upstream/OBSERVED.md` once, each note with the probe that showed it: its date, its
operation and its recording under `tests/fixtures/`. This section holds what the package
does with it and cites a note by its heading.

- `validate_filters` checks every key against `columns.csv` and the value of each packaged
  parameter against its list before a request, since Quick Stats ignores a column it does
  not know and counts no record for a value it does not know ("An unknown column is
  ignored", "An unknown value counts 0"). It compares a value without regard to case, as
  Quick Stats does ("A value's case is ignored"), and sends it as given.
- `classify` maps the three refusals once ("Refusals"): HTTP 413 to `QueryTooLarge`, HTTP
  400 `bad request - invalid query` to `NotFoundError`, and HTTP 400 `no value` of
  `get_param_values` to `NotFoundError` naming the parameter.
- `get_data(split_by_year=True)` splits a two-sided year range by year and never counts it
  whole, since Quick Stats counts `year__GE` with `year__LE` as `year__GE` alone ("One bound
  on year a query"); the docstrings of `count_data` and `get_data` say so to a caller.
- The packaged lists are declared as `PACKAGED_PARAMS` in `params.py`, the nine parameters
  that `get_param_values` lists, which the reference script hands core's frame as
  `packaged`: where `/refresh-reference-data` names `PACKAGED_LISTS`, read `PACKAGED_PARAMS`.
  No list declares an enum, so the frame leaves `enums.py` alone and the package ships none.
- `get_data(split_by_year=True)` splits one call into at most `tasks.SPLIT.value` years,
  core's `Ceiling`: 20 in Python and over HTTP, 11 on the MCP server by default, whose
  `--split-years` sets 1 to 20. One year costs two keyed requests, its count and its data,
  and `year__GE` alone a first count more, so 11 years send at most 23 requests.
- The client keeps the `get_param_values` lookups for a day and the counts and the data for
  300 seconds in core's cache, by the maintainer's decision of 2026-11-26. An answer over
  core's 8 MiB passes unstored, as one of about 9,000 records or more does ("A record is
  about 900 bytes"), so `get_data` stays unpaged over MCP.
- The reference script waits 300 seconds for an answer, where the client waits 60 ("A list
  can take more than a minute").
