# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

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
