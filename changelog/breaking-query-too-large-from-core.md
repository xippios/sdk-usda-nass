- `QueryTooLarge` is a subclass of core's `xippios.core.QueryTooLarge`, which words its
  message from the count and upstream's limit of 50,000 records a call, then what narrows
  the query, while upstream's HTTP 413 names the request it refused, `GET /api/api_GET/`.
  It takes `count`, `year` and `request` and no `limit`, and `errors.NARROW` holds the
  advice for a whole query. (https://github.com/xippios/sdk-core/issues/317)
