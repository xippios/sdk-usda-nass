# Reference data for USDA NASS Quick Stats

Code lists and column definitions ship here, versioned with the package, and load through
`xippios.core.PackagedList` and `xippios.usda.nass.params` (built on `xippios.core.reference`):

```python
from xippios.core import PackagedList
from xippios.usda.nass.params import PACKAGE, columns

states = PackagedList.load(PACKAGE, "state_alpha")
[record["state_alpha"] for record in states.records]  # ['AK', 'AL', ...], no network call
[c.column for c in columns()]  # every Quick Stats column, from param_define.md
```

Each `reference/<name>.json` holds `{"param", "endpoint", "fetched", "records"}` and an
optional `"note"`: upstream's records under upstream's field names, a value list as records
of one field named by its Quick Stats parameter (`unit_desc` for the two derived lists),
written by `/refresh-reference-data`'s script with `PackagedList.write`, never by hand, and
read with `PackagedList.load`; `columns.csv` is the column table of
`docs/upstream/param_define.md`, rebuilt by the same script. One row per file: Origin is the
endpoint or URL it was fetched from, or the `docs/upstream/` file it was rebuilt from;
Fetched is the UTC time of that fetch, or the snapshot's `Fetched` time for a rebuilt file.

| File | Origin | Fetched |
| --- | --- | --- |
| `source_desc.json` | `GET /api/get_param_values?param=source_desc` | 2026-10-25 |
| `sector_desc.json` | `GET /api/get_param_values?param=sector_desc` | 2026-10-25 |
| `group_desc.json` | `GET /api/get_param_values?param=group_desc` | 2026-10-25 |
| `agg_level_desc.json` | `GET /api/get_param_values?param=agg_level_desc` | 2026-10-25 |
| `freq_desc.json` | `GET /api/get_param_values?param=freq_desc` | 2026-10-25 |
| `state_alpha.json` | `GET /api/get_param_values?param=state_alpha` | 2026-10-25 |
| `progress_stages.json` | distinct `unit_desc` of `GET /api/api_GET` with statisticcat_desc=PROGRESS, agg_level_desc=NATIONAL, freq_desc=WEEKLY, year=2025 | 2026-10-25 |
| `condition_categories.json` | distinct `unit_desc` of `GET /api/api_GET` with statisticcat_desc=CONDITION, agg_level_desc=NATIONAL, freq_desc=WEEKLY, year=2025 | 2026-10-25 |
| `columns.csv` | `docs/upstream/param_define.md` (snapshot of https://quickstats.nass.usda.gov/param_define) | 2026-10-22 |

The two derived lists come from the year before the fetch; each file records the query
under `note`.
