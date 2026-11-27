- `get_data(split_by_year=True)` refuses a two-sided range over its ceiling in core's words,
  naming the range, its years and the ceiling, and that nothing was sent, its class
  `InvalidRequestError` unchanged. A request after the first that fails raises its error
  naming the years answered before it, and the call returns nothing.
  (https://github.com/xippios/sdk-core/issues/315,
  https://github.com/xippios/sdk-usda-nass/issues/56)
