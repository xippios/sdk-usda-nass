- `get_data(split_by_year=True)` refuses a two-sided range over its ceiling in core's words,
  `split_by_year from 2000 to 2020 is 21 years; one call fetches at most 20 years. Nothing
  was sent.`, its class `InvalidRequestError` unchanged. A request after the first that
  fails raises its error naming the years answered before it, and the call returns
  nothing. (https://github.com/xippios/sdk-core/issues/315,
  https://github.com/xippios/sdk-usda-nass/issues/56)
