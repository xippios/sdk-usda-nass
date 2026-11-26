- `xippios.usda.nass.enums` leaves with its eleven `StrEnum` classes, nine of the packaged
  lists and two of the derived ones, `StateAlpha`, `UnitDesc`, `ProgressStage` and the
  rest, so an import of it fails. A filter takes upstream's text, which the tasks check
  against the packaged lists without regard to case before a request:
  `{"state_alpha": "IA", "unit_desc": "PCT PLANTED"}` in place of
  `{"state_alpha": StateAlpha.IA, "unit_desc": ProgressStage.PCT_PLANTED}`, and
  `list_param_values` lists the values. (https://github.com/xippios/sdk-core/issues/474,
  https://github.com/xippios/sdk-usda-nass/issues/89)
