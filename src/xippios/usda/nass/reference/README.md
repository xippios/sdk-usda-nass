# Reference data for USDA NASS Quick Stats

Code lists and calendars the upstream publishes (commodities, countries, report
schedules) ship here as CSV or JSON, versioned with the package, and load through
`xippios.core.reference`:

```python
from xippios.core import load_table

rows = load_table("xippios.usda.nass", "commodities.csv", Commodity)
```

Rules:

- Files come from the upstream through `/refresh-reference-data`, never typed in by hand.
- Every file has a row below naming the endpoint or URL it came from and the date.
- Reference lookups are tools too (`usda.nass_list_<thing>`), so agents can form valid calls.

| File | Origin | Fetched |
| --- | --- | --- |
| (none yet) | | |
