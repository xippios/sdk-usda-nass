- A refusal of `get_data` after a count says what was sent: `QueryTooLarge` over the limit
  says `The count was sent, and no record was asked for.` and, for a year of
  `split_by_year`, `Only counts were sent, and no record was asked for.`, and the refusal of
  `year__GE` alone over the split's ceiling says that the count of the range was sent and
  no year was counted or fetched. The classes are unchanged, and upstream's own refusal of
  a query as too large names the data request it refused, as before.
  (https://github.com/xippios/sdk-core/issues/481,
  https://github.com/xippios/sdk-usda-nass/issues/89)
