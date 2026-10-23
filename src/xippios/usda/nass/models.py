"""Pydantic models mirroring USDA NASS Quick Stats payloads.

One model per upstream object, subclassing ``xippios.core.UpstreamModel``, with fields
named as upstream names them in snake_case. Where upstream spells a field differently,
``Field(validation_alias=...)`` accepts that spelling on input; never ``alias=``, which the
adapters would serialise, handing agents the upstream spelling. Within-source hygiene only:
dates become ``datetime.date``, numbers become numbers, upstream enumerations become
``StrEnum``. No cross-source normalisation (ADR-0003): an upstream concept stays an
upstream concept.

Quick Stats sends every value as a string; the models coerce the numeric and temporal
ones and keep the rest verbatim, empty strings included. ``value`` stays the published
string, because a suppression code such as ``"(D)"`` is information; ``value_number``
is its parsed form and travels as a JSON number. Column meanings are in
``docs/upstream/param_define.md``; the response shapes in ``api.md`` and the recorded
fixtures.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, computed_field, field_validator
from xippios.core import UpstreamModel, parse_decimal

__all__ = [
    "AcreageRecord",
    "ApiGetResponse",
    "AreaStatistic",
    "CountyEstimateRecord",
    "CropProgressRecord",
    "Filters",
    "GetCountsResponse",
    "PriceReceivedRecord",
    "QuickStatsRecord",
]

Filters = Mapping[str, str | int]
"""Quick Stats query parameters, as upstream names them.

Keys are column names from ``docs/upstream/param_define.md`` (``commodity_desc``,
``state_alpha``, ``year``, ...), optionally suffixed with an operator: ``__LE``, ``__LT``,
``__GT``, ``__GE``, ``__LIKE``, ``__NOT_LIKE``, ``__NE``. Example:
``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``. Upstream ignores
unknown column names rather than rejecting them; the tasks validate keys first.
"""


class GetCountsResponse(UpstreamModel):
    """Payload of ``GET /api/get_counts``: ``{"count": 22345}``.

    Attributes:
        count: Number of records the same filters would return from ``api_GET``.
    """

    count: int


class _Published(UpstreamModel):
    """The published figure as Quick Stats sends it, plus its parsed form."""

    value: str = Field(validation_alias="Value")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value_number(self) -> Decimal | None:
        """``value`` as a number, or ``None`` for a suppression code."""
        return parse_decimal(self.value)


class QuickStatsRecord(_Published):
    """One published estimate from ``api_GET``, every column Quick Stats returns.

    Columns keep their upstream names; ``Value`` and ``CV (%)`` are read under the
    upstream spelling and carried as ``value`` and ``cv_percent``. ``value`` stays a
    string because it carries either a number with thousands separators (``"510,000"``)
    or a suppression code such as ``"(D)"``; ``value_number`` parses the numeric case.
    """

    source_desc: str
    sector_desc: str
    group_desc: str
    commodity_desc: str
    class_desc: str
    prodn_practice_desc: str
    util_practice_desc: str
    statisticcat_desc: str
    unit_desc: str
    short_desc: str
    domain_desc: str
    domaincat_desc: str
    agg_level_desc: str
    state_ansi: str
    state_fips_code: str
    state_alpha: str
    state_name: str
    asd_code: str
    asd_desc: str
    county_ansi: str
    county_code: str
    county_name: str
    region_desc: str
    zip_5: str
    watershed_code: str
    watershed_desc: str
    congr_district_code: str
    country_code: str
    country_name: str
    location_desc: str
    year: int
    freq_desc: str
    begin_code: str
    end_code: str
    reference_period_desc: str
    week_ending: date | None
    load_time: datetime
    cv_percent: str = Field(validation_alias="CV (%)")

    @field_validator("week_ending", mode="before")
    @classmethod
    def _empty_is_none(cls, raw: object) -> object:
        return None if raw == "" else raw


class ApiGetResponse(UpstreamModel):
    """Payload of ``GET /api/api_GET`` with ``format=JSON``: ``{"data": [...]}``."""

    data: list[QuickStatsRecord]


class CropProgressRecord(_Published):
    """One weekly crop progress or condition estimate: a projection of ``QuickStatsRecord``.

    Columns keep their upstream names (ADR-0003); only the ones that vary within a
    progress or condition series are kept. ``unit_desc`` carries the stage
    (``"PCT PLANTED"``, ``"PCT EMERGED"``, ...) or the condition category
    (``"PCT EXCELLENT"`` ... ``"PCT VERY POOR"``); ``value`` is that percentage as
    published and ``value_number`` its parsed form. ``state_alpha`` is ``"US"`` for the
    national series.
    """

    commodity_desc: str
    class_desc: str
    util_practice_desc: str
    statisticcat_desc: str
    unit_desc: str
    short_desc: str
    agg_level_desc: str
    state_alpha: str
    state_name: str
    year: int
    week_ending: date | None
    reference_period_desc: str
    source_desc: str
    load_time: datetime


class CountyEstimateRecord(_Published):
    """One annual county estimate (yield or production): a projection of ``QuickStatsRecord``.

    Columns keep their upstream names (ADR-0003). ``prodn_practice_desc`` separates the
    all-practices figure from irrigated and non-irrigated ones where a state reports
    them; ``util_practice_desc`` separates grain from silage; ``unit_desc`` names the
    unit (``"BU / ACRE"``, ``"TONS / ACRE"``, ``"BU"``, ``"TONS"``). ``cv_percent`` is the
    coefficient of variation when published, parsed.
    """

    commodity_desc: str
    class_desc: str
    util_practice_desc: str
    prodn_practice_desc: str
    statisticcat_desc: str
    unit_desc: str
    short_desc: str
    source_desc: str
    agg_level_desc: str
    state_alpha: str
    state_name: str
    asd_code: str
    asd_desc: str
    county_ansi: str
    county_code: str
    county_name: str
    year: int
    reference_period_desc: str
    cv_percent: Decimal | None
    load_time: datetime


class AreaStatistic(StrEnum):
    """The two ``statisticcat_desc`` values the acreage slice covers, as upstream names them."""

    AREA_PLANTED = "AREA PLANTED"
    AREA_HARVESTED = "AREA HARVESTED"


class AcreageRecord(_Published):
    """One acreage estimate in acres: a projection of ``QuickStatsRecord``.

    Columns keep their upstream names (ADR-0003). ``statisticcat_desc`` is
    ``AREA PLANTED`` or ``AREA HARVESTED``; ``reference_period_desc`` is ``YEAR`` for a
    final figure or names the forecast (``YEAR - AUG FORECAST``); ``util_practice_desc``
    separates grain from silage on the harvested side; ``source_desc`` tells survey from
    census figures.
    """

    commodity_desc: str
    class_desc: str
    util_practice_desc: str
    prodn_practice_desc: str
    statisticcat_desc: str
    unit_desc: str
    short_desc: str
    source_desc: str
    agg_level_desc: str
    state_alpha: str
    state_name: str
    year: int
    freq_desc: str
    reference_period_desc: str
    cv_percent: Decimal | None
    load_time: datetime


class PriceReceivedRecord(_Published):
    """One price-received estimate: a projection of ``QuickStatsRecord``.

    Columns keep their upstream names (ADR-0003). ``freq_desc`` is ``MONTHLY`` or
    ``ANNUAL`` (the marketing-year average); ``reference_period_desc`` names the month or
    ``MARKETING YEAR`` and ``begin_code``/``end_code`` carry the month numbers, ``00`` for
    the year. ``unit_desc`` is the price unit (``"$ / BU"``) or, in the national series,
    ``"PCT OF PARITY"``.
    """

    commodity_desc: str
    class_desc: str
    util_practice_desc: str
    statisticcat_desc: str
    unit_desc: str
    short_desc: str
    source_desc: str
    agg_level_desc: str
    state_alpha: str
    state_name: str
    year: int
    freq_desc: str
    reference_period_desc: str
    begin_code: str
    end_code: str
    load_time: datetime
