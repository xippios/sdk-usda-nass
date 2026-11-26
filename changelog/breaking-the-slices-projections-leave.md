- The nine projections that the slices returned leave `xippios.usda.nass.models`,
  `CropProgressRecord`, `CountyEstimateRecord`, `AcreageRecord`, `CensusFarmsRecord`,
  `ProductionRecord`, `PriceReceivedRecord`, `LivestockInventoryRecord`,
  `MilkProductionRecord` and `GrainStocksRecord`, and so do the four value sets written for
  the slices' arguments, `AreaStatistic`, `FarmStatistic`, `ProductionStatistic` and
  `LivestockCommodity`. `QuickStatsRecord`, which `get_data` returns, carries every column
  that a projection kept, with `cv_percent` as upstream prints it where a projection parsed
  it into a number. A filter takes a statistic or a commodity as upstream's text, such as
  `{"statisticcat_desc": "AREA PLANTED"}`. (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
