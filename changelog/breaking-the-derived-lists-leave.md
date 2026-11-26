- The two lists that the package derived from one year of national weekly rows leave,
  `progress_stages` and `condition_categories` under `reference/` with
  `params.DERIVED_LISTS`, since a package builds no list of its own. The packaged
  `unit_desc` list holds each of their 16 stages and 5 categories, such as `PCT PLANTED`
  and `PCT GOOD`, which `list_param_values("unit_desc")` lists. The reference refresh sends
  9 requests where it sent 11. (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
