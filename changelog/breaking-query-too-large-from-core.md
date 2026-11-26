- `QueryTooLarge` is a subclass of core's `xippios.core.QueryTooLarge`, which words its
  message, `query would return 85,535 records; upstream serves at most 50,000 per call.`
  and then what narrows the query, while upstream's HTTP 413 names the request it refused,
  `upstream refused GET /api/api_GET/ as too large`. It takes `count`, `year` and
  `request` and no `limit`, and `errors.NARROW` holds the advice for a whole query.
  (https://github.com/xippios/sdk-core/issues/317)
