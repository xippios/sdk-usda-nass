- The MCP server splits one `usda_nass_get_data` call into at most 11 years by default,
  where it split 5, the most whose split stays within the about two dozen requests that one
  tool call may spend, at most 23. `--split-years` still sets 1 to 20, and Python and HTTP
  keep 20. (https://github.com/xippios/sdk-usda-nass/issues/89)
