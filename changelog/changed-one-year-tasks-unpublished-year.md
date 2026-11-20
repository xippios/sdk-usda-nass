- The thirteen tasks that take a `year`, `get_production` and `get_crop_progress` among
  them, say under `year`, and so in their MCP tools' descriptions, that an empty answer may
  be a year not yet published: Quick Stats names no release and answers such a year as one
  without records, so `NotFoundError` may mean either. `get_data` says the same of a count
  of 0 for one `year`, which returns an empty result, as its `split_by_year` said already of
  a year counting 0; sdk-core's conventions §4 ask it of every task that fetches one period.
  (https://github.com/xippios/sdk-usda-nass/issues/42)
