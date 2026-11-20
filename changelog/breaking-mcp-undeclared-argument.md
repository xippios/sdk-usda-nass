- A tool refuses an argument that it does not declare before it runs, whatever its value,
  where the argument was dropped and the tool ran without it. `usda_nass_list_param_values`
  called with `parameter` answers `error: InvalidRequestError: parameter: Not an argument
  of this tool`, then names `param`, the one argument it takes.
  (https://github.com/xippios/sdk-core/issues/84)
