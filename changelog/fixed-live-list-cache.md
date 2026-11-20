- A list that `list_param_values` fetches live is kept for 24 hours only once its answer
  parsed, so an answer that does not parse is asked again on the next lookup, where it was
  kept and failed every lookup until its entry expired. The lookup that fetched a list and
  every lookup the cache answers report one `meta.retrieved_at`.
  (https://github.com/xippios/sdk-core/issues/122,
  https://github.com/xippios/sdk-core/issues/79)
