# What Quick Stats does but never documents

Notes, written by hand, on what USDA NASS Quick Stats' API does that neither page of this
snapshot states (sdk-core's conventions §3, sdk-core ADR-0028). `api.md` documents the three
resources, `api_GET`, `get_param_values` and `get_counts`, their parameters, the operators
and four error messages, and `param_define.md` the columns. The status of each error answer,
the shapes of the answers, what a filter that Quick Stats does not know does and the sizes
below come from the wire, and `models.py`, `_client.classify`, `params.validate_filters` and
`tests/fixtures/` follow it. `scripts/refresh_upstream.py` neither writes nor checks this
file, and `FETCHED.md` lists it in a row of its own.

Each note ends with its probe: the date, the operation by its resource's name and the
sample. A sample recorded as a fixture is named by its path under `tests/fixtures/`, whose
`recorded_at` gives the time of the request, and a packaged list by its file, whose
`fetched` gives the time of its fetch. A probe that kept no answer names its request. The
notes moved here on 2026-11-26 from the README, `CLAUDE.md`, `_client.py`, `params.py`,
`tasks.py` and the reference script; no request was sent to write this file.

## Error answers

### A query over the limit: HTTP 413

A query that matches more than 50,000 records answers HTTP 413 with
`{"error":["exceeds limit=50000"]}`: the documented message, without its spaces around `=`,
in a list under `error`. The documentation names the message and no status. Corn alone,
`commodity_desc=CORN`, is over the limit.

Probe: 2026-10-22, `api_GET`; sample `tests/fixtures/api_get/exceeds_limit.json`.

### Filters that match no record: HTTP 400 from api_GET

`api_GET` of corn in Virginia in 1800 answers HTTP 400 with
`{"error":["bad request - invalid query"]}`, the message that the documentation gives to an
error in the query string, such as a wrong parameter name or value. `get_counts` of the same
filters answers HTTP 200 with `{"count":0}`.

Probe: 2026-10-22, `api_GET` and `get_counts`; samples `tests/fixtures/api_get/no_match.json`
and `tests/fixtures/get_counts/no_match.json`.

### An unknown parameter of get_param_values: HTTP 400

`get_param_values` of `param=not_a_column` answers HTTP 400 with
`{"not_a_column":["no value"]}`, keyed by the parameter as a list's answer is.

Probe: 2026-10-22, `get_param_values`; sample
`tests/fixtures/get_param_values/unknown_param.json`.

## Filters

### One bound on year a query

Quick Stats keeps one bound on `year` in a query. Iowa with `year__GE=2023` and
`year__LE=2024` counts 31,461, in either order of the two, and so does `year__GE=2023`
alone, where 2023 counts 8,635 and 2024 counts 12,799. Iowa with `year__GE=2023` and
`year__LT=2025` counts 1,425,389, far more than `year__GE=2023` alone: the lower bound is
dropped.

Probe: 2026-10-28, `get_counts`; samples `tests/fixtures/get_counts/ia_2023_2024.json`,
`tests/fixtures/get_counts/ia_2023_2024_le_first.json`,
`tests/fixtures/get_counts/ia_since_2023.json`,
`tests/fixtures/get_counts/ia_2023_2024_2023.json`,
`tests/fixtures/get_counts/ia_2023_2024_2024.json` and
`tests/fixtures/get_counts/ia_2023_lt_2025.json`.

### A value's case is ignored

Corn in Virginia from 2012 counts 22,347 with `state_alpha=va`, where it counted 22,345 with
`state_alpha=VA` six days before: Quick Stats compares a value without regard to case.

Probe: 2026-10-22 and 2026-10-28, `get_counts`; samples
`tests/fixtures/get_counts/corn_va_since_2012.json`, recorded 2026-10-22, and
`tests/fixtures/get_counts/corn_va_since_2012_lowercase.json`, recorded 2026-10-28.

### An unknown column is ignored

`not_a_column=x` alone counts 57,873,464 records and is not refused: Quick Stats ignores a
column that it does not know, where the documentation gives "bad request - invalid query"
to a wrong parameter name.

Probe: 2026-10-22, `get_counts`; sample `tests/fixtures/get_counts/unknown_column.json`.

### An unknown value counts 0

`state_alpha=XX` counts 0 and is not refused, the answer of filters without data.

Probe: 2026-10-28, `get_counts`; sample `tests/fixtures/get_counts/unknown_state_alpha.json`.

## Answers

### A count is a JSON integer

`get_counts` answers `{"count":22345}`, the count a JSON integer, where the documentation's
example prints `{"count":"27"}`, a string.

Probe: 2026-10-22, `get_counts`; sample `tests/fixtures/get_counts/corn_va_since_2012.json`.

### A record's fields

A record of `api_GET` holds 39 fields, every value a JSON string but `year`, a JSON integer
(`2012`), which the documentation's example prints as a string. Beside the fields of that
example it holds `state_fips_code`, `county_code`, `location_desc` and `CV (%)`, and it
spells `class_desc` in lower case, where the example prints `Class_desc`.
`Value` prints thousands with commas (`510,000`), `week_ending` is empty outside a weekly
series, and `load_time` prints a date and a time with three decimals and no zone
(`2018-01-23 08:13:26.000`).

Probe: 2026-10-22, `api_GET`; samples `tests/fixtures/api_get/corn_va_2012_area_planted.json`
and `tests/fixtures/api_get/corn_progress_planted_ia_2024.json`.

### A record is about 900 bytes

A record of `api_GET` takes 920 to 950 bytes of JSON: 13 records of corn prices in Iowa take
11,992 bytes, 11 of corn planted in Iowa 10,391 and 2 of corn planted in Virginia 1,866. At
that size 50,000 records are about 46 MB, and an answer passes core's cache bound of 8 MiB
from about 9,000 records, an estimate.

Probe: 2026-10-22, `api_GET`; samples
`tests/fixtures/api_get/corn_price_received_ia_2023.json`,
`tests/fixtures/api_get/corn_progress_planted_ia_2024.json` and
`tests/fixtures/api_get/corn_va_2012_area_planted.json`.

### The lists' lengths

Of the nine packaged lists `domain_desc` is the longest, 616 values in 22,194 bytes of
compact JSON, then `unit_desc` with 373 and `statisticcat_desc` with 278, and the other six
hold fewer than 60. A list fetched live runs past 200 too: `commodity_desc` holds 467
values, an answer of 6,792 bytes.

Probe: 2026-10-28, `get_param_values`; samples
`src/xippios/usda/nass/reference/domain_desc.json`,
`src/xippios/usda/nass/reference/unit_desc.json`,
`src/xippios/usda/nass/reference/statisticcat_desc.json` and
`tests/fixtures/get_param_values/commodity_desc.json`.

### A list can take more than a minute

Two runs of the reference script on 2026-11-20 got the first three lists and no answer for
the fourth, `agg_level_desc`, within the client's read timeout of 60 seconds. One request
for it with a read timeout of 300 seconds was answered in 7.5 seconds with 11 values, so
Quick Stats answers the list and was slow at times
(https://github.com/xippios/sdk-usda-nass/issues/78).

Observed: 2026-11-20, `get_param_values`; the request
`GET /api/get_param_values/?param=agg_level_desc`, sent three times on 2026-11-20, kept no
answer.

### No header of a quota

No answer carries a header of a quota or of the requests left: each recording holds `date`,
`server` (`Kestrel`), `strict-transport-security`, `x-content-type-options`, `content-type`
on all but the two error answers of `api_GET`, and four headers of the proxy in front,
`x-author`, `x-proxyversion`, `x-cache` and `x-handler-apgw-05-12`. The documentation
states no rate limit.

Probe: 2026-10-22 and 2026-10-28, `api_GET`, `get_counts` and `get_param_values`; samples
`tests/fixtures/api_get/exceeds_limit.json`, recorded 2026-10-22,
`tests/fixtures/get_counts/ia_since_2023.json` and
`tests/fixtures/get_param_values/commodity_desc.json`, recorded 2026-10-28.
