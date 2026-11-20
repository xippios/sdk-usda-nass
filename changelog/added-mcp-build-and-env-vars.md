- `xippios.usda.nass.mcp` exports `build()`, the tool set of xippios-core's package
  contract with the tools' caps and the `--split-years` option, `server`, built from it,
  and `ENV_VARS`, the variables the package reads, `NASS_API_KEY` alone, so a host serves
  the package as `xippios-usda-nass-mcp` does.
  (https://github.com/xippios/sdk-core/issues/245)
