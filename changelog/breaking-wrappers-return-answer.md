- `api.api_get` and `api.get_counts` return core's `Answer`, the parsed response as
  `payload` beside `retrieved_at`, the time it arrived, where they returned the response
  itself. They read through the client's `get_answer`, as `api.get_param_values` does.
  (https://github.com/xippios/sdk-core/issues/479)
