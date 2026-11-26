- `tasks.split_ceiling()` and `tasks.set_split_ceiling(years)` are removed, so a call of
  either fails, and core's `Ceiling` `tasks.SPLIT` holds the split's ceiling of 20 years in
  their place, read as `tasks.SPLIT.value` and set with `tasks.SPLIT.set(years)`. Its
  refusal of a ceiling outside 1 to 20 reads `the series ceiling, --split-years on the MCP
  server, ...` in core's words, its class `InvalidRequestError` unchanged.
  (https://github.com/xippios/sdk-core/issues/315,
  https://github.com/xippios/sdk-usda-nass/issues/56)
