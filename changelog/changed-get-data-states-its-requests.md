- The description of `usda_nass_get_data` states the most requests that one call spends,
  retries counted: 2 requests in 8 attempts, and with `split_by_year` 23 requests in 92
  attempts at the MCP server's 11 years and 41 requests in 164 attempts at the 20 years of
  Python and HTTP. (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
