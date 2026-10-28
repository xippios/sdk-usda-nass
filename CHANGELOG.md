# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- `get_census_farms(year, statistic, state=, by_county=)`, the MCP tool
  `usda_nass_get_census_farms` and its HTTP route: the Census of Agriculture's farm
  counts (`FarmStatistic.OPERATIONS`) or land in farms (`FarmStatistic.AREA_OPERATED`)
  for a Census year (2022, 2017), national, for one state, or by county, of one state
  or of the whole country. Fixed filters, read from upstream with `get_counts` on
  2026-10-28: `source_desc` `CENSUS`, `group_desc` `FARMS & LAND & ASSETS`,
  `commodity_desc` `FARM OPERATIONS`, `class_desc` `ALL CLASSES`,
  `prodn_practice_desc` `ALL PRODUCTION PRACTICES` and `domain_desc` `TOTAL`, so the
  breakdowns by farm size, sales class, typology, organization and the like are left
  out (of the 4,114 national rows the 2022 Census has for `FARM OPERATIONS` in that
  group, 7 remain: 2 for `OPERATIONS`, 5 for `AREA OPERATED`). `unit_desc` tells the
  rows apart (`OPERATIONS`, `PCT OF FARM OPERATIONS`; `ACRES`, `ACRES / OPERATION`,
  `ACRES / OPERATION, MEDIAN`, `PCT OF AG LAND`, `PCT OF TOTAL LAND`); rows are sorted
  by state, county and unit and come as `CensusFarmsRecord`, a projection under
  upstream column names with `cv_percent` parsed. Like the other slices it skips the
  count (`meta.total` `None`) and leaves `published_at` empty.
- `get_livestock_inventory(commodity, year, state=, class_desc=)` and
  `get_milk_production(year, state=, frequency=)`, two task-shaped slices of `api_GET`,
  with the MCP tools `usda_nass_get_livestock_inventory` and
  `usda_nass_get_milk_production` and their HTTP routes. `get_livestock_inventory`
  returns the survey head counts of cattle, hogs or sheep (`LivestockCommodity`, a
  `StrEnum` of the three upstream `commodity_desc` values, in `models.py`) on the survey
  days of a year, state or national, one row per survey day, class and `short_desc`
  (`statisticcat_desc` `INVENTORY`, `unit_desc` `HEAD`, `domain_desc` `TOTAL`,
  `freq_desc` `POINT IN TIME`, `source_desc` `SURVEY`; cattle on feed carry
  `ALL CLASSES` with `prodn_practice_desc` `ON FEED`), sorted by the day (`begin_code`),
  then `reference_period_desc`, `class_desc` and `short_desc`;
  `class_desc` keeps one class, `None` returns every class. `get_milk_production` returns
  the milk production series in pounds, the year and the months and quarters, state or
  national (`commodity_desc` `MILK`, `class_desc` `ALL CLASSES`, `statisticcat_desc`
  `PRODUCTION`, `unit_desc` `LB`, `domain_desc` `TOTAL`, `source_desc` `SURVEY`), sorted
  by frequency, then period; `frequency` keeps `MONTHLY` or `ANNUAL`, `None` returns
  both. `class_desc` `ALL CLASSES` leaves out the ten manufactured dairy products (dry and
  condensed milk) that upstream files nationally under the same statistic and unit
  (recorded 2026-10-28: 147 national records for 2024 without it, 17 with it). Both
  return projections under upstream column names, `LivestockInventoryRecord` and
  `MilkProductionRecord`, skip the count and leave `published_at` empty, as the other
  slices do. Fixtures recorded 2026-10-28: national cattle and Iowa hogs 2024, national
  and Wisconsin monthly milk 2024, and the two national milk counts. Live smoke tests
  `test_livestock_inventory_live` and `test_milk_production_live`; the older live
  assertions on a record's field or on `len(result.data)` bind the value to a local
  first, so a failure prints the figure or the count, not the records.
- `get_production_forecasts(commodity, year, statistic, *, state=None)` and
  `get_production(commodity, year, statistic, *, state=None)`, the MCP tools
  `usda_nass_get_production_forecasts` and `usda_nass_get_production` and their HTTP
  routes: a crop's in-season production or yield forecasts, oldest first, and its final
  figure, state or national, as rows of the new projection `ProductionRecord`.
  `statistic` is the new `ProductionStatistic` (`PRODUCTION`, `YIELD`), a
  `statisticcat_desc` value; both send `domain_desc` `TOTAL`, `prodn_practice_desc`
  `ALL PRODUCTION PRACTICES` and `freq_desc` `ANNUAL`, the forecasts
  `reference_period_desc__LIKE` `FORECAST` (upstream's `__LIKE` counts what
  `reference_period_desc__NE` `YEAR` counts on these filters, recorded 2026-10-28), the
  final figure `reference_period_desc` `YEAR`. Utilisations, classes and units are rows
  under upstream's columns: grain and silage, wheat's classes, and the value of
  production in `$` beside the quantity. The forecasts are sorted by `load_time`, then
  utilisation, class and unit, the final figure by state, utilisation, class, unit and
  source. Like the other task-shaped functions they skip the count (`meta.total` is
  `None`) and leave `published_at` empty.
- Live smoke tests for `get_crop_condition`, `get_county_production` and
  `get_acreage_forecasts` (`test_crop_condition_live`, `test_county_production_live`,
  `test_acreage_forecasts_live`), so every task has one (conventions §10);
  `test_list_param_values_live` asks for `commodity_desc`, a list fetched live, where it
  asked for the packaged `sector_desc`, which spent no call.
- `get_data(filters, split_by_year=True)`, and `split_by_year` on the MCP tool
  `usda_nass_get_data` and the HTTP route: the years are fetched one at a time where one
  call cannot serve them. The filters bound the years as `year`, `year__GE` with
  `year__LE`, or `year__GE` alone up to the current UTC year, checked before any call;
  another year filter, or none, raises `InvalidRequestError` naming the three forms, and
  a `year__GE` or `year__LE` past the current UTC year raises it naming that year. One
  call splits into at most 20 years in Python and over HTTP (`errors.SPLIT_CEILING`,
  conventions §4) and 5 by default on the MCP server (`errors.MCP_SPLIT_YEARS`), whose
  `xippios-usda-nass-mcp --split-years` sets 1 to 20 through core's option hooks,
  process-wide (`tasks.split_ceiling`, `tasks.set_split_ceiling`): a longer split raises
  `InvalidRequestError` naming the ceiling, for a two-sided range before any call, for
  `year__GE` alone after its count, while an open range within the limit is fetched
  whole however far back it starts. Quick Stats keeps one bound on `year` per query
  (recorded 2026-10-28: `year__GE` with `year__LE` counts as `year__GE` alone, in either
  order, and beside `year__LT` the lower bound is dropped), which the `get_counts` and
  `get_data` docstrings state (ADR-0003), so `year__GE` with `year__LE` is always split,
  without a count of the range. `year` is counted and fetched once, as without the flag;
  `year__GE` alone is counted first and fetched once when the count is within the limit,
  else split. A split counts every year with `year=<y>` in place of the year filters
  before anything is fetched; a year over the limit on its own raises `QueryTooLarge`
  naming it, which now carries `year`; a year counting 0 is skipped, since it has no
  records, or none published yet, which Quick Stats does not tell apart (`meta.vintage`
  stays `None`: Quick Stats names no release); the records come in year order, each
  year's in upstream's order. `meta.total` is the yearly counts summed and
  `meta.request` carries `split_by_year` beside the filters (conventions §4). Cost: up
  to two keyed calls per year, plus the first count for `year__GE` alone.
- `meta.total` on `get_data`: the count `get_counts` reported for the filters, `0` on
  the empty result it returns without a second call, never `len(data)`; `get_counts`
  carries its count there too, beside `data` (conventions §4, ADR-0012). The task-shaped
  functions skip the count and leave `total` `None`.

- `statisticcat_desc` (278 values), `unit_desc` (373) and `domain_desc` (616) ship as
  packaged lists (fetched 2026-10-28), with the `StrEnum` classes `StatisticcatDesc`,
  `UnitDesc` and `DomainDesc` in `xippios.usda.nass.enums`; `list_param_values` answers
  nine parameters from the package, with no upstream call. The refresh script names some
  members itself, where the renderer would derive none, one name for two values, or a
  name that reads as a unit, not a price: in `UnitDesc`, every value with `$` (61) reads
  `$` as `DOLLARS` and `/` as `PER`, so `"$"` is `DOLLARS`, `"$ / BU"` is
  `DOLLARS_PER_BU` beside `BU`, `"$ / ACRE"` is `DOLLARS_PER_ACRE` and
  `"$, CHERRY BASIS"` is `DOLLARS_CHERRY_BASIS`; in `DomainDesc`, a `_SPELLED_OUT` suffix
  marks the two landlord domains upstream also spells with `AND` in place of `&`.
- A list `list_param_values` fetches live (`commodity_desc`, `short_desc`, ...) is cached
  in memory for 24 hours in the process, so a repeated lookup sends nothing; its
  `meta.retrieved_at` is the time the cached answer was fetched (ADR-0015, decision 5).
  `get_counts`, `get_data` and the tasks built on `api_GET` always ask upstream.

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
- The packaged lists are refreshed (fetched 2026-10-28): no value changed, moved or
  disappeared in the six lists packaged before and the two derived ones. Each file's
  `fetched` is the full UTC time of its fetch (`2026-10-28T15:01:38Z`), so
  `meta.retrieved_at` of a packaged answer is that time, where it read 00:00 UTC of
  2026-10-25; the `enums.py` docstrings name 2026-10-28, and `reference/README.md` lists
  the eleven files with their fetch times.
- `list_param_values` answers `statisticcat_desc`, `unit_desc` and `domain_desc` from
  the package, no longer live. The live path's replay test uses a new
  `get_param_values/commodity_desc` fixture (recorded 2026-10-28); the
  `statisticcat_desc` fixture, which no test replays any more, is removed.
- `QueryTooLarge`'s hint for a whole query names the way through the limit: narrower
  filters, or `get_data` with `split_by_year=True` (the MCP tool `usda_nass_get_data`)
  on a bounded year range of at most 20 years in Python and over HTTP, 5 by default on
  the MCP server (`--split-years`) (conventions §8), where it said to split the query
  into several. A year over the limit on its own names narrower filters only.
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
- **BREAKING**: the endpoint wrapper `api.get_param_values` returns
  `ParamValues(values, retrieved_at)`, read through `AsyncClient.get_answer`, where it
  returned the list alone: `retrieved_at` is a cached answer's stored time, else the time
  the answer arrived. The refresh script writes that time as a packaged list's `fetched`.
- **BREAKING**: the endpoint wrapper `api_GET` is `api_get`, imported from
  `xippios.usda.nass.api.api_get`, its fixtures under `tests/fixtures/api_get/`
  (conventions 1.22 §2 and §10). A wrapper's module and function carry the upstream
  operation name in snake case, here from the path: `/api/api_GET/` is `api_get`. The
  request URL and `meta.endpoint` (`"api_GET"`) are unchanged, and so are the tasks.
- The upstream snapshot is refreshed (2026-10-28) through `scripts/refresh_upstream.py`,
  the template's capture script filled for the api and param_define pages, with
  `markdownify==1.2.3` pinned in it and in the dev group; `docs/upstream/FETCHED.md`
  follows conventions §3 (the UTC time with `Z`, the attribution, one row per page with
  status, size and sha256), and the column-definitions table, which has merged cells, is
  kept as HTML. Upstream's content is unchanged since the snapshot of 2026-10-22.
  `scripts/refresh_reference.py` reads that HTML table before it writes any file, and
  reproduces `columns.csv` from it byte for byte. `columns.csv` itself is not rebuilt
  here: its provenance row in the reference README (snapshot of 2026-10-22) moves at the
  next `/refresh-reference-data` run.
- The README's "Upstream terms and attribution" displays the notice the NASS API Terms of
  Service ask every service that uses the API to display.

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
