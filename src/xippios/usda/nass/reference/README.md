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
  (`/refresh-reference-data`), never typed in by hand.
- Every file has a row below naming where it came from and the date.
- `list_param_values` answers from the packaged lists for the six parameters below and
  goes live for every other parameter.

| File | Origin | Fetched |
| --- | --- | --- |
| `source_desc.json` | `GET /api/get_param_values?param=source_desc` | 2026-10-22 |
| `sector_desc.json` | `GET /api/get_param_values?param=sector_desc` | 2026-10-22 |
| `group_desc.json` | `GET /api/get_param_values?param=group_desc` | 2026-10-22 |
| `agg_level_desc.json` | `GET /api/get_param_values?param=agg_level_desc` | 2026-10-22 |
| `freq_desc.json` | `GET /api/get_param_values?param=freq_desc` | 2026-10-22 |
| `state_alpha.json` | `GET /api/get_param_values?param=state_alpha` | 2026-10-22 |
| `columns.csv` | `docs/upstream/param_define.md` (snapshot of https://quickstats.nass.usda.gov/param_define, fetched 2026-10-22) | 2026-10-22 |
