- `xippios-usda-nass-mcp` names itself in its usage line and its errors, a refused
  `--split-years 25` ending `xippios-usda-nass-mcp: error: the split ceiling, ...`, where
  they named the server, `xippios-usda-nass`. Its help says that `--allow-remote` changes
  nothing on this read server, which is not held to loopback.
  (https://github.com/xippios/sdk-core/issues/167)
