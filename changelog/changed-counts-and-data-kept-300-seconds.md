- The client keeps the answers of `get_counts` and `api_GET` for 300 seconds in core's
  response cache, beside the lists it keeps for a day, so a count, a query or a split
  repeated within that time sends nothing and carries the time its answer was stored. A
  body over the cache's bound of 8 MiB, a year of data among them, passes unstored.
  (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
