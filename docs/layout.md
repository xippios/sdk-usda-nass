# Layout

The files that every source of the family holds are laid out once, in the tree of
sdk-template's README,
[What gets generated](https://github.com/xippios/sdk-template/blob/main/README.md#what-gets-generated).
This file holds what `xippios-usda-nass` adds to that tree, a module, a task file, a
script or a test of its own, each with what it holds, and the change that adds one updates it.

The import path is `xippios.usda.nass` (sdk-core ADR-0006); `src/xippios/` is a
namespace package, and so is `src/xippios/usda/`, the provider level.
Where the API's operation ids repeat across its services, `api/` keeps one module per service
instead, named after the service, and this file says so (conventions §2).

```
src/xippios/usda/nass/
  _client.py         the client's cache, core's MemoryCache, keeps the get_param_values
                     lookups for a day and no other answer
  errors.py          QueryTooLarge, core's with the year, NARROW, RECORD_LIMIT,
                     SPLIT_CEILING (20) and MCP_SPLIT_YEARS (11)
  models.py          ApiGetResponse, GetCountsResponse and QuickStatsRecord, the records of
                     the three operations; no value set written by hand
  api/api_get.py     api_GET, the records for a set of filters, core's Answer
  api/get_counts.py  get_counts, the count of a set of filters, core's Answer
  api/get_param_values.py  get_param_values, the values of one parameter, core's Answer
  tasks.py           get_counts, get_data and list_param_values; SPLIT, core's Ceiling of
                     the split by year, with its two option hooks for --split-years
  params.py          PACKAGED_PARAMS, the nine packaged lists, codes() with core's check,
                     validate_filters, and columns() over load_table, the package's own
  reference/         the nine parameter lists, <param>.json, and columns.csv, the column
                     table of docs/upstream/param_define.md; no enums.py, since no list
                     declares an enum
tests/
  fixtures/          recorded responses, <wrapper>/<case>.json, never hand-written
  test_refresh_reference.py  the reference script offline: its one Lists, its fetch, the
                     column table's parse and write, the read timeout of 300 seconds
  test_refresh_upstream.py   the snapshot script's declaration: its two pages, the
                     converter, the attribution and the package's client
docs/upstream/       api.md and param_define.md, the two pages converted to Markdown
```
