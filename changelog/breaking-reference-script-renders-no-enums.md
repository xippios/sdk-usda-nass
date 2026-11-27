- `scripts/refresh_reference.py` writes the packaged lists, their provenance rows and
  `columns.csv` and renders no module, so the names it set for the enums' classes and
  members leave. Its options are those of core's frame, `--only <list> [<list> ...]` and
  `--render-only`, which writes the provenance rows alone.
  (https://github.com/xippios/sdk-core/issues/482,
  https://github.com/xippios/sdk-usda-nass/issues/89)
