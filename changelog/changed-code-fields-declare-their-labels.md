- Each code field of `QuickStatsRecord` declares by core's `NamedBy` the field beside it
  that holds its name, `state_alpha`, `state_ansi` and `state_fips_code` by `state_name`,
  `county_ansi` and `county_code` by `county_name`, `asd_code` by `asd_desc`,
  `watershed_code` by `watershed_desc` and `country_code` by `country_name`. The answers
  are unchanged, and `meta.names` takes no entry for a code whose name stands on its
  record. (https://github.com/xippios/sdk-core/issues/478,
  https://github.com/xippios/sdk-usda-nass/issues/89)
