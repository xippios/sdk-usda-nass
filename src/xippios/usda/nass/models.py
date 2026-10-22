"""Pydantic models mirroring USDA NASS Quick Stats payloads.

One model per upstream object, subclassing ``xippios.core.UpstreamModel``, with fields
named as upstream names them in snake_case. Within-source hygiene only: dates become
``datetime.date``, numbers become numbers, upstream enumerations become ``StrEnum``.
No cross-source normalisation (ADR-0003): an upstream concept stays an upstream concept.

Quick Stats sends every value as a string; the models coerce the numeric and temporal
ones and keep the rest verbatim, empty strings included. Column meanings are in
``docs/upstream/param_define.md``; the response shapes in ``api.md`` and the recorded
fixtures.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import Field, field_validator
from xippios.core import UpstreamModel

__all__ = [
    "ApiGetResponse",
    "CropProgressRecord",
    "Filters",
    "GetCountsResponse",
    "QuickStatsRecord",
]

Filters = Mapping[str, str | int]
"""Quick Stats query parameters, as upstream names them.

Keys are column names from ``docs/upstream/param_define.md`` (``commodity_desc``,
``state_alpha``, ``year``, ...), optionally suffixed with an operator: ``__LE``, ``__LT``,
``__GT``, ``__GE``, ``__LIKE``, ``__NOT_LIKE``, ``__NE``. Example:
``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``. Upstream ignores
unknown column names rather than rejecting them.
"""


class GetCountsResponse(UpstreamModel):
    """Payload of ``GET /api/get_counts``: ``{"count": 22345}``.

    Attributes:
        count: Number of records the same filters would return from ``api_GET``.
    """

    count: int


class QuickStatsRecord(UpstreamModel):
    """One published estimate from ``api_GET``, every column Quick Stats returns.

    Columns keep their upstream names; ``Value`` and ``CV (%)`` get snake_case names with
    the upstream spelling as alias. ``value`` stays a string because it carries either a
    number with thousands separators (``"510,000"``) or a suppression code such as
    ``"(D)"``; ``value_number`` parses the numeric case.
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
    value: str = Field(alias="Value")
    cv_percent: str = Field(alias="CV (%)")

    @field_validator("week_ending", mode="before")
    @classmethod
    def _empty_is_none(cls, raw: object) -> object:
        return None if raw == "" else raw

    @property
    def value_number(self) -> Decimal | None:
        """``value`` as a number, or ``None`` for a suppression code."""
        try:
            return Decimal(self.value.replace(",", ""))
        except InvalidOperation:
            return None


class ApiGetResponse(UpstreamModel):
    """Payload of ``GET /api/api_GET`` with ``format=JSON``: ``{"data": [...]}``."""

    data: list[QuickStatsRecord]


class CropProgressRecord(UpstreamModel):
    """One weekly crop progress or condition estimate: a projection of ``QuickStatsRecord``.

    Columns keep their upstream names (ADR-0003); only the ones that vary within a
    progress or condition series are kept. ``unit_desc`` carries the stage
    (``"PCT PLANTED"``, ``"PCT EMERGED"``, ...) or the condition category
    (``"PCT EXCELLENT"`` ... ``"PCT VERY POOR"``); ``value`` is that percentage, parsed,
    or ``None`` for a suppression code. ``state_alpha`` is ``"US"`` for the national
    series.
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
    value: Decimal | None
    source_desc: str
    load_time: datetime

    @classmethod
    def from_record(cls, record: QuickStatsRecord) -> "CropProgressRecord":
        """Project a full record; every field keeps its upstream name and value."""
        return cls(
            commodity_desc=record.commodity_desc,
            class_desc=record.class_desc,
            util_practice_desc=record.util_practice_desc,
            statisticcat_desc=record.statisticcat_desc,
            unit_desc=record.unit_desc,
            short_desc=record.short_desc,
            agg_level_desc=record.agg_level_desc,
            state_alpha=record.state_alpha,
            state_name=record.state_name,
            year=record.year,
            week_ending=record.week_ending,
            reference_period_desc=record.reference_period_desc,
            value=record.value_number,
            source_desc=record.source_desc,
            load_time=record.load_time,
        )
