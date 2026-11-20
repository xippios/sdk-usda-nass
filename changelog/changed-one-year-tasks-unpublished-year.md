- The thirteen tasks that take a `year`, `get_production` and `get_crop_progress` among
  them, say under `year`, and so in their MCP tools' descriptions, that an empty answer may
  be a year not yet published: Quick Stats names no release and answers such a year as one
  without records, so `NotFoundError` may mean either. `get_data` with `split_by_year` said
  so already of a year counting 0, and sdk-core's conventions §4 ask it of every task that
  fetches one period. (https://github.com/xippios/sdk-usda-nass/issues/42)
