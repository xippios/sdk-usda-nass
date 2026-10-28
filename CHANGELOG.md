# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- `get_data(filters, split_by_year=True)`, and `split_by_year` on the MCP tool
  `usda_nass_get_data` and the HTTP route: the years are fetched one at a time where one
  call cannot serve them. The filters bound the years as `year`, `year__GE` with
  `year__LE`, or `year__GE` alone up to the current UTC year, checked before any call;
  another year filter, or none, raises `InvalidRequestError` naming the three forms. One
  call splits into at most 20 years (`errors.SPLIT_CEILING`, conventions §4): a longer
  split raises `InvalidRequestError` naming the ceiling, for a two-sided range before
  any call, for `year__GE` alone after its count, while an open range within the limit
  is fetched whole however far back it starts. Quick Stats keeps one bound on `year` per
  query (recorded 2026-10-28: `year__GE` with `year__LE` counts as `year__GE` alone, in
  either order, and beside `year__LT` the lower bound is dropped), which the
  `get_counts` and `get_data` docstrings state (ADR-0003), so `year__GE` with `year__LE`
  is always split, without a count of the range. `year` is counted and fetched once, as
  without the flag; `year__GE` alone is counted first and fetched once when the count is
  within the limit, else split. A split counts every year with `year=<y>` in place of
  the year filters before anything is fetched; a year over the limit on its own raises
  `QueryTooLarge` naming it, which now carries `year`; a year counting 0 is not fetched;
  the records come in year order, each year's in upstream's order. `meta.total` is the
  yearly counts summed and `meta.request` carries `split_by_year` beside the filters
  (conventions §4). Cost: up to two keyed calls per year, plus the first count for
  `year__GE` alone.
- `meta.total` on `get_data`: the count `get_counts` reported for the filters, `0` on
  the empty result it returns without a second call, never `len(data)`; `get_counts`
  carries its count there too, beside `data` (conventions §4, ADR-0012). The task-shaped
  functions skip the count and leave `total` `None`.

### Changed

- **BREAKING**: `get_counts` and `get_data` refuse an unknown value of a packaged
  parameter (`params.PACKAGED_PARAMS`, the lists `list_param_values` answers without a
  call, such as `state_alpha` and `sector_desc`) given as a bare key, before any call,
  with core's `UnknownCode`, an `InvalidRequestError` (HTTP 422), naming the packaged
  list, its fetch date and the closest known values, or, when none is close, pointing at
  the task `list_param_values('state_alpha')` and the MCP tool
  `usda_nass_list_param_values` (conventions §5, ADR-0022), where 0.1.0 sent it and
  answered a count of 0 or an empty result, which cannot be told from a query without
  data. The comparison ignores case, as Quick Stats does (`state_alpha=va` counts what
  `VA` counts, recorded 2026-10-28), so a value upstream serves is never refused, and the
  value is sent as given; an enum member is read by its value, and the hint names the
  canonical spelling. A key with an operator (`state_alpha__LIKE`, `sector_desc__NE`) is
  checked against the columns and operators and its value sent as given. Unknown columns
  and operators still raise `InvalidRequestError` first, with the same text.
- `QueryTooLarge`'s hint for a whole query names the way through the limit: narrower
  filters, or `get_data` with `split_by_year=True` (the MCP tool `usda_nass_get_data`)
  on a bounded year range of at most 20 years (conventions §8), where it said to split
  the query into several. A year over the limit on its own names narrower filters only.
- Adopted xippios-core 0.3.0, sdk-template v0.3.0 and conventions 1.22 (conventions §15).
- **BREAKING**: depends on `xippios-core~=0.3.0`, its `mcp`, `http` and `testing` extras
  likewise, from PyPI; a core minor keeps no compatibility with the one before it while
  core is 0.x (conventions §12).
- **BREAKING**: `list_param_values` answers a packaged parameter with `meta.endpoint`
  `"get_param_values"`, the operation the list was fetched from, `meta.retrieved_at` the
  list's `fetched` and `meta.vintage` `None` (ADR-0022, rule 1), where 0.1.0 wrote
  `"reference"` and the fetch date as `vintage`. The packaged files are core's
  packaged-list files, `{"param", "endpoint", "fetched", "records"}` with an optional
  `"note"`, converted without a request: values and order unchanged, `fetched` the date
  it was (2026-10-25, read as 00:00 UTC), the derived lists' query under `note`.
- **BREAKING**: the endpoint wrapper `api_GET` is `api_get`, imported from
  `xippios.usda.nass.api.api_get`, its fixtures under `tests/fixtures/api_get/`
  (conventions 1.22 §2 and §10). A wrapper's module and function carry the upstream
  operation name in snake case, here from the path: `/api/api_GET/` is `api_get`. The
  request URL and `meta.endpoint` (`"api_GET"`) are unchanged, and so are the tasks.

### Removed

- **BREAKING**: `params.PackagedValues`, `params.packaged_values` and
  `params.derived_values`: a packaged list is read with
  `xippios.core.PackagedList.load("xippios.usda.nass", name)` (ADR-0022).

## [0.1.0] - 2026-10-25

### Added

- `MCP_CAPS` in `tasks.py`: over MCP, `usda_nass_list_param_values` returns up to 1,000
  values (`ResultCap(max_rows=1000)`, the default 64 KB), since lists fetched live run past
  the default 200 rows (`statisticcat_desc` has 278); its note says the tool takes no
  filter and that a value past the cap is still accepted as a filter value by
  `get_counts` and `get_data` (conventions §8, ADR-0016).
- `scripts/refresh_reference.py --render-only` regenerates `enums.py` from the packaged
  lists, packaged and derived, without a request or a key.
- `get_acreage_forecasts`: the in-season acreage reports (March prospective plantings,
  June acreage, monthly forecasts), oldest first; `get_acreage` keeps the final figure.
- `get_prices_received`: monthly and marketing-year prices received for a commodity,
  state or national, as `PriceReceivedRecord` (projection with the period codes kept).
  Fixtures recorded 2026-10-22 for Iowa and national corn 2023.
- `get_acreage`: annual planted or harvested acreage totals of a crop, state or national,
  as `AcreageRecord` (projection; breakdowns and forecasts excluded by fixed filters).
  `AreaStatistic` names the two statistics. Fixtures recorded 2026-10-22 for Iowa and
  national corn 2023.
- `get_county_yield` and `get_county_production`: annual final county estimates
  (`agg_level_desc` COUNTY, `reference_period_desc` YEAR) for a crop and year, one or
  all states, as `CountyEstimateRecord` (projection with `value` and `cv_percent`
  parsed; utilisation and production practice kept apart). Fixtures recorded
  2026-10-22 for Delaware corn 2023.
- `ProgressStage` and `ConditionCategory` enums, derived by the refresh script from one
  national year of weekly rows (`reference/progress_stages.json`,
  `reference/condition_categories.json`, with the query recorded). `get_crop_progress`
  and `get_crop_condition` take them instead of strings.
- `get_crop_progress` and `get_crop_condition`: weekly state or national series from the
  Crop Progress survey (`statisticcat_desc` PROGRESS / CONDITION), as
  `CropProgressRecord`, a projection of `QuickStatsRecord` under upstream column names
  with `value` parsed. Fixtures recorded 2026-10-22.
- Filter-key validation (`params.validate_filters`): `get_counts` and `get_data` reject
  unknown columns and operators with `InvalidRequestError` before calling upstream,
  naming the closest valid column names.
- `xippios.usda.nass.enums`: `StrEnum` classes for the six packaged parameter lists,
  generated by `scripts/refresh_reference.py`.
- `get_counts` task and `api.get_counts` wrapper for `GET /api/get_counts`: the number of
  records a set of Quick Stats filters would return. Fixtures recorded 2026-10-22.
- `get_data` task and `api.api_GET` wrapper for `GET /api/api_GET`: published estimates
  as `QuickStatsRecord` (every column, `year` and `load_time` typed, `value_number`
  parsed). `get_data` checks the count first; `QueryTooLarge` above 50,000 records.
  Upstream's HTTP 413 maps to `QueryTooLarge`, its HTTP 400 "invalid query" for filters
  that match nothing maps to `NotFoundError`. Fixtures recorded 2026-10-22.
- `list_param_values` task and `api.get_param_values` wrapper for
  `GET /api/get_param_values`: the values a filter parameter can take. An unknown
  parameter (upstream: HTTP 400 `{"<param>": ["no value"]}`) maps to `NotFoundError`.
  Fixtures recorded 2026-10-22.
- Packaged reference data (`xippios.usda.nass.params`): the value lists of
  `source_desc`, `sector_desc`, `group_desc`, `agg_level_desc`, `freq_desc` and
  `state_alpha` (fetched 2026-10-22) and `columns.csv` from `param_define.md`.
  `list_param_values` answers those six from the package, with `meta.endpoint`
  `"reference"` and `meta.vintage` the fetch date; everything else stays live.
  `scripts/refresh_reference.py` rebuilds the files.
- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA NASS Quick Stats, empty task layer, MCP server and FastAPI router
  wired to it, test harness, CI and publishing.

### Changed

- The packaged lists are refreshed (fetched 2026-10-25): no row changed in any of the
  eight and no code disappeared, so only the fetch date moved, in `meta.vintage` of a
  packaged answer and in the `enums.py` docstrings; `reference/README.md` names 2025 as
  the year the two derived lists come from.
- Adopted xippios-core 0.2.0, sdk-template v0.2.0 and conventions 1.13 (conventions §15).
  `xippios-core~=0.2.0`, its extras likewise, from PyPI; CI runs pre-commit; the nightly
  `live.yml` runs the live tests at 01:51 UTC; mypy checks `scripts/`; the sdist ships no
  tests; `enums.py` is re-rendered by core's renderer (its first line only).
- `RATE_LIMIT` is `RateLimit(per_minute=30, burst=1)`, a self-imposed pace since Quick
  Stats documents no limit; it allowed a burst of 30 (ADR-0010).
- Replay tests read what was sent through `xippios.core.testing.sent_urls(route)` instead
  of `route.calls`, so no request carrying the key sits in a test's frame (ADR-0013).
- `test_upstream_answers` is a keyless reachability probe, a plain GET to `BASE_URL`
  through `httpx`, so it spends no keyed call.
- Updated to sdk-template v0.1.5: `.gitattributes` keeps `docs/upstream/` byte-exact,
  `.gitignore` covers `.env.*` and `.envrc.*`, the detect-secrets baseline skips
  `.copier-answers.yml`, `_client` exports `auth`, the MCP instructions and three commands
  are reworded.
- Projections keep `value` as the published string and expose `value_number` as a
  computed field that travels as a JSON number; `QuickStatsRecord.value_number` likewise.
  Projections are built with `UpstreamModel.project` (ADR-0008).
- Task-shaped functions skip the count check; their fixed filters keep results small and
  an over-limit answer still raises `QueryTooLarge`.
- Upstream's error shapes are mapped once in `_client.classify`; the wrappers use
  `get_json` and no longer inspect status codes. `scripts/refresh_reference.py` renders
  enums through `xippios.core.reference.render_str_enums`.
- `QueryTooLarge` is an `InvalidRequestError` (HTTP 422 through the adapter).

### Removed

- The `placeholder_api_key` fixture and `PLACEHOLDER_KEY` in `tests/conftest.py`, and
  `test_replay_tests_send_the_placeholder_key`: core 0.2.0's test plugin pins the
  placeholder key in every test not marked live and sets `NASS_API_KEY`, named under
  `xippios_placeholder_key_envs`, to it (ADR-0013).
- The `get_counts` mounts of eleven slice tests, whose tasks skip the count, and the
  fifteen fixtures no test replays.

### Security

- `virtualenv` bumped to 21.14.13 in `uv.lock` (GHSA-cx6f-vjhg-g3cc, CVE-2026-115586):
  the dev group's `pre-commit` dependency; the published wheel never carried it.
