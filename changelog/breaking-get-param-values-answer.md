- `api.get_param_values` returns xippios-core's `Answer[list[str]]`, its `payload` the
  values and its `retrieved_at` the time, and `ParamValues`, the pair it returned, is gone
  from `xippios.usda.nass.api`. A caller that unpacked the pair, as `values, retrieved_at =
  await api.get_param_values("sector_desc")`, reads `answer.payload` and
  `answer.retrieved_at`. (https://github.com/xippios/sdk-core/issues/123)
