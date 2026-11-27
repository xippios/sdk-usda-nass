# xippios-usda-nass

Typed Python client, MCP server and FastAPI routes for
[USDA NASS Quick Stats](https://quickstats.nass.usda.gov), part of the
[xippios SDK family](https://github.com/xippios). Names and semantics follow the
upstream documentation; every response carries its metadata (source, endpoint,
retrieved_at, request).

## Install

```bash
uv add xippios-usda-nass            # client only
uv add "xippios-usda-nass[mcp]"     # + MCP server
uv add "xippios-usda-nass[http]"    # + FastAPI router
```

Set `NASS_API_KEY` in the environment. Nothing is read from files.

## 30-second example

```python
from xippios.usda.nass import tasks

filters = {
    "commodity_desc": "CORN",
    "statisticcat_desc": "AREA PLANTED",
    "agg_level_desc": "STATE",
    "state_alpha": "VA",
    "year": 2012,
}
tasks.get_counts(filters).data  # 2 records would come back from api_GET
records = tasks.get_data(filters).data
records[0].short_desc  # 'CORN - ACRES PLANTED'
records[0].value, records[0].value_number  # '510,000', Decimal('510000'); JSON: 510000
```

`get_data` calls `get_counts` first: zero matches return an empty result, more than
50,000 raise `QueryTooLarge` with the count and a hint, narrower filters or a split by
year, before anything is fetched. `list_param_values("sector_desc")` lists the values a
filter can take.

`get_data(filters, split_by_year=True)` fetches the years one at a time where one call
cannot serve them, when its filters bound the years as `year`, `year__GE` with
`year__LE`, or `year__GE` alone up to the current UTC year; any other year filter, and a
`year__GE` or `year__LE` past the current UTC year, is refused with
`InvalidRequestError` before a call. Quick Stats keeps one bound on `year` per query
(recorded 2026-10-28: it counts `year__GE` with `year__LE` as `year__GE` alone, and
drops `year__GE` beside `year__LT`), so a two-sided year range is served only by this
split. That form is always split, every year counted before anything is fetched; `year`
is counted and fetched once, and `year__GE` alone is counted first and split only over
the limit. One call splits into at most 20 years in Python and over HTTP, and 11 by
default on the MCP server, whose `--split-years` sets 1 to 20: a longer split raises
`InvalidRequestError` naming the ceiling, for a two-sided range before any call, for
`year__GE` alone after its count, while an open range within the limit is fetched whole
however far back it starts. A year counting 0 is skipped: it has no records, or none
published yet, which Quick Stats does not tell apart, and `meta.vintage` stays `None`,
since Quick Stats names no release. A year over 50,000 on its own still raises
`QueryTooLarge` naming it, and the records come in year order with `meta.total` the
yearly counts summed. A split costs up to two keyed calls per year.

Each record carries every column of Quick Stats under its upstream name; `value` stays
the published string and `value_number` its parsed form. `meta.published_at` stays
empty: Quick Stats publishes no release time and each row's `load_time` carries no zone,
so nothing is read into it.

Filters are Quick Stats column names, optionally suffixed with an operator (`__GE`,
`__LE`, `__LIKE`, ...), mapped to values; the columns are listed in
`docs/upstream/param_define.md`. Quick Stats ignores unknown column names, so the
package checks every key against its column table and raises `InvalidRequestError`,
naming the closest valid names, before anything is sent; it checks the value of a
packaged parameter (`state_alpha`, `sector_desc`, `unit_desc`, ...) against its packaged
list too and refuses an unknown one with `UnknownCode` before the call, since Quick Stats
counts no records for it.

## MCP

```json
{
  "mcpServers": {
    "usda-nass": {
      "command": "uvx",
      "args": ["--from", "xippios-usda-nass[mcp]", "xippios-usda-nass-mcp"],
      "env": { "NASS_API_KEY": "..." }
    }
  }
}
```

Tools are read-only and named `usda_nass_<verb>_<noun>`. Results are capped, at
200 rows or 64 KB unless a tool has a cap of its own, with a note on how to see the rest:
`usda_nass_list_param_values` returns up to 1,000 values, since its lists run longer than
200 (`domain_desc`, packaged, has 616; `commodity_desc`, fetched live, 467), and takes
`offset`, the values already shown, which continues a cut list from the package or the
client's cache without a request. `--http`
serves streamable HTTP instead of stdio. `--split-years YEARS`, 1 to 20 and 11 by default,
is the most years one `usda_nass_get_data` call with `split_by_year` splits into, at most
23 keyed calls at 11; the setting holds for the whole process.

## Status

<!-- Core's family check (tests/test_family.py) reads this table: keep the "## Status"
heading and the "Task function" column. Each row's Task function cell starts with the
task's name in backticks, alone or as its call (`get_data(code, year)`); several tasks in
one row are backticked names separated by commas; prose may follow. The tables list
exactly tasks.__all__, and tasks_write.__all__ where the package has write tasks. -->

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| `get_counts` | `tasks.get_counts(filters)` | `usda_nass_get_counts` | alpha |
| `api_GET` | `tasks.get_data(filters, split_by_year=)` | `usda_nass_get_data` | alpha |
| `get_param_values` | `tasks.list_param_values(param)` | `usda_nass_list_param_values` | alpha |

The package serves these three tasks, where 0.3.0 served sixteen: the thirteen that fixed
filters over `api_GET` for the caller left, and the query of each is one `get_data` call
with the same filters. 0.3.0 requires xippios-core 0.4.x (`~=0.4.0`); 0.2.0 does not
work with core 0.4.0. Alpha: the public surface may change in a minor version before 1.0
(conventions §12); `CHANGELOG.md` lists every change.

## Upstream terms and attribution

Data comes from USDA NASS Quick Stats (https://quickstats.nass.usda.gov) under its own terms of use;
this package adds no rights to it. Documentation snapshot: `docs/upstream/`.

The NASS API Terms of Service ask every service that uses the API to display this notice:

> This product uses the NASS API but is not endorsed or certified by NASS.

## Workflows

`ci.yml` runs ruff, its format check, mypy, pytest and pre-commit on Python 3.12, 3.13 and
3.14, requires a changelog entry of every pull request but Dependabot's and refuses a
fixture file over 256 KiB that a pull request adds or changes. It runs on every pull request and,
called by `publish.yml`, once for a release, and its job `ci` is the check the
organization's ruleset requires. It is handed no secret, and no variable switches it off.

`publish.yml` is the release train (conventions §12): on a push to `main` whose
`pyproject.toml` names a version that has no tag yet and has its section in `CHANGELOG.md`,
it runs `ci.yml`, refuses a core pinned to git, tags the merge commit, builds the package
and, once a reviewer of the environment `pypi` approves the run, publishes it to PyPI by
trusted publishing. Every push to `main` and a dispatch start it, and a push that brings no
release ends quietly. It is handed no secret: the step that tells a release is handed the
job's token as `GH_TOKEN`, the tag goes with the job's token and PyPI trusts the workflow
itself. Its job `tag` holds the one checkout of the repository that keeps its credentials,
since it pushes the tag with the job's token; every other checkout sets
`persist-credentials: false` (conventions §13). No variable switches it off.

`live.yml` runs every `live` test against the upstream with `--tb=short --assert=plain`, so
its public log holds neither a failing test's arguments nor the values an assertion compared.
It runs every night at 01:51 UTC and on demand, never on a pull request.
Its pytest step alone is handed `XIPPIOS_LIVE_TESTS` and, each from the secret of the same
name, `NASS_API_KEY`, so the checkout, setup-uv and `uv sync` see none.
A variable `WORKFLOW_LIVE` of `off`, the repository's over the organization's, switches it off.

`conventions.yml` calls the organization's review of a pull request against the documents
listed under Documents below, the check `conventions / conventions`, when a pull request
opens, is pushed to, reopens or is edited, and on a push to `main` or a dispatch the review
of the range of commits, `range / range`. It hands the review the organization's
secret of the model's key, by name. A variable `WORKFLOW_CONVENTIONS` of `off`, the
repository's over the organization's, switches both off.

`adr-index.yml` calls the organization's check of the ADR index, `adr-index / adr-index`,
which runs `scripts/adr_index.py --check`, when a pull request opens, is pushed to or
reopens. It hands over nothing, and the called workflow reads its switch itself: a variable
`WORKFLOW_ADR_INDEX` of `off`, the repository's over the organization's, skips the check.

`siblings.yml` runs `.github/scripts/check-siblings.sh`, which installs the wheel beside
every sibling on PyPI under the same provider namespace that shares its core minor and
beside the source packages it depends on, and proves that the namespace levels stay portions
(sdk-core ADR-0006, sdk-core ADR-0021). It runs on every pull request and push to `main`, a
check the ruleset does not require, in a workflow of its own, since `ci.yml` is core's file,
which `publish.yml` calls for a release. It hands the script the job's read-only token as
`GITHUB_TOKEN`, for the listing of the organization's repositories, since GitHub limits the
calls of a runner without one. A variable `WORKFLOW_SIBLINGS` of `off`, the repository's
over the organization's, switches it off.

## Documents

- sdk-core: [docs/conventions.md](https://github.com/xippios/sdk-core/blob/main/docs/conventions.md) — the conventions every xippios source package follows: its layout, names, results, tests and releases.
- sdk-core: [docs/adr.md](https://github.com/xippios/sdk-core/blob/main/docs/adr.md) — the index of the family's architecture decisions, which the conventions cite.
- sdk-core: [docs/definition-of-done.md](https://github.com/xippios/sdk-core/blob/main/docs/definition-of-done.md) — what a change satisfies before its pull request is opened.
- sdk-core: [docs/review-checklist.md](https://github.com/xippios/sdk-core/blob/main/docs/review-checklist.md) — what the review of a pull request checks, in order.
- sdk-usda-nass: [docs/adr.md](https://github.com/xippios/sdk-usda-nass/blob/main/docs/adr.md) — the index of this package's own decisions, generated from the records in `docs/adr/`.
- sdk-usda-nass: [docs/upstream/FETCHED.md](https://github.com/xippios/sdk-usda-nass/blob/main/docs/upstream/FETCHED.md) — the snapshot of the upstream documentation, the reference for names, parameters and semantics.

## Licence

Apache-2.0. See [LICENSE](https://github.com/xippios/sdk-usda-nass/blob/main/LICENSE).
