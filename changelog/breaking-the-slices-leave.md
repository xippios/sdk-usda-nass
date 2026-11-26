- The thirteen tasks that fixed filters over `api_GET` for the caller leave with their MCP
  tools and their routes, by the boundary of a source package: `get_crop_progress`,
  `get_crop_condition`, `get_county_yield`, `get_county_production`, `get_acreage`,
  `get_acreage_forecasts`, `get_production_forecasts`, `get_production`,
  `get_prices_received`, `get_census_farms`, `get_livestock_inventory`,
  `get_milk_production` and `get_grain_stocks`. The query of each is one `get_data` call
  with the same filters, which counts the records first and fills `meta.total`. Its records
  come in upstream's order, where a slice sorted them, so a caller who needs an order sorts
  them itself. (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
