- The task `get_counts` is `count_data`, its MCP tool `usda_nass_count_data` and its route
  `/usda-nass/count_data`, with no alias, so a call of `tasks.get_counts` or of the tool
  `usda_nass_get_counts` fails. The verb `count_` names upstream's own count operation in
  the family, and the wrapper `api.get_counts` keeps upstream's name of it.
  (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
