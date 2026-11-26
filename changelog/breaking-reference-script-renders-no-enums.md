- `scripts/refresh_reference.py` writes the packaged lists and `columns.csv` alone and
  renders no module, so its `--render-only` leaves with the names it set for the enums'
  classes and members. `--only <list> [<list> ...]` stays its one option.
  (https://github.com/xippios/sdk-usda-nass/issues/89)
