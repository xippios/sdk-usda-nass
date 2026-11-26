- `get_data(split_by_year=True)` sums no yearly counts into `meta.total`: a two-sided range,
  which Quick Stats counts as `year__GE` alone, answers with `meta.total` `None`, and
  `year__GE` alone over the limit keeps upstream's count of the range, where both read the
  yearly counts summed. A caller who needs the records' number reads `len(data)`.
  (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
