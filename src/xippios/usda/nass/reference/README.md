# Reference data for USDA NASS Quick Stats

Code lists and column definitions ship here, versioned with the package, and load through
`xippios.usda.nass.params` (built on `xippios.core.reference`):

```python
from xippios.usda.nass.params import columns, packaged_values

packaged_values("state_alpha").values  # ['AK', 'AL', ...], no network call
[c.column for c in columns()]  # every Quick Stats column, from param_define.md
```

Rules:

- Files come from the upstream through `scripts/refresh_reference.py`
  (`/refresh-reference-data`), never typed in by hand; the script also regenerates
  `enums.py` with `xippios.core.reference`: one `StrEnum` per value list
  (`render_str_enums`), or one `IntEnum` per list of integer ids (`render_int_enums`).
  Quick Stats' lists are value lists, so `enums.py` holds a `StrEnum` for each of the
  eight `.json` files below; `--render-only` regenerates it from them without a request.
- Files keep upstream's names: a value list keeps its Quick Stats parameter as `param`
  (`unit_desc` for the two derived lists) and its values verbatim, and `columns.csv` keeps
  every column name as `param_define.md` spells it.
- Every file has a row below naming where it came from and the date.
- Agents get a lookup task for every packaged list so they can form valid calls: one
  lookup task per list, `list_<thing>`, served as the MCP tool `usda_nass_list_<thing>`,
  or the upstream's own lookup operation when it serves every list through one. Quick
  Stats serves every list through `get_param_values`, so `list_param_values` (the MCP
  tool `usda_nass_list_param_values`) answers from the packaged lists for the six
  parameters below and goes live for every other parameter. The two derived lists are
  the values of `get_crop_progress`'s `stage` and `get_crop_condition`'s `category`,
  listed in those tools' input schemas.

| File | Origin | Fetched |
| --- | --- | --- |
| `source_desc.json` | `GET /api/get_param_values?param=source_desc` | 2026-10-22 |
| `sector_desc.json` | `GET /api/get_param_values?param=sector_desc` | 2026-10-22 |
| `group_desc.json` | `GET /api/get_param_values?param=group_desc` | 2026-10-22 |
| `agg_level_desc.json` | `GET /api/get_param_values?param=agg_level_desc` | 2026-10-22 |
| `freq_desc.json` | `GET /api/get_param_values?param=freq_desc` | 2026-10-22 |
| `state_alpha.json` | `GET /api/get_param_values?param=state_alpha` | 2026-10-22 |
| `progress_stages.json` | distinct `unit_desc` of `GET /api/api_GET` with statisticcat_desc=PROGRESS, agg_level_desc=NATIONAL, freq_desc=WEEKLY, year=2024 | 2026-10-22 |
| `condition_categories.json` | distinct `unit_desc` of `GET /api/api_GET` with statisticcat_desc=CONDITION, agg_level_desc=NATIONAL, freq_desc=WEEKLY, year=2024 | 2026-10-22 |
| `columns.csv` | `docs/upstream/param_define.md` (snapshot of https://quickstats.nass.usda.gov/param_define, fetched 2026-10-22) | 2026-10-22 |
