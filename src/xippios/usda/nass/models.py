"""Pydantic models mirroring upstream's payloads, one ``UpstreamModel`` per object.

Conventions §3 and ``/add-endpoint`` give the rules.

Quick Stats sends every value of a record as a string but ``year``, an integer
(``docs/upstream/OBSERVED.md``, "A record's fields"); the models coerce the numeric and
temporal ones and keep the rest verbatim, empty strings included. ``value`` stays the published
string, because a suppression code such as ``"(D)"`` is information; ``value_number``
is its parsed form and travels as a JSON number, and ``cv_percent`` and
``cv_percent_number`` stand so too (conventions §3). Each code field declares by
``NamedBy`` the field beside it in which Quick Stats sends the code's name (conventions
§4; sdk-core ADR-0067, decision 6). Column meanings are in
``docs/upstream/param_define.md``; the response shapes in ``api.md`` and the recorded
fixtures. None of those columns is a personal identifier, so ``QuickStatsRecord`` keeps
every one.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, computed_field, field_validator
from xippios.core import NamedBy, UpstreamModel, parse_decimal

__all__ = ["ApiGetResponse", "Filters", "GetCountsResponse", "QuickStatsRecord"]

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
    ``cv_percent`` stays the printed coefficient of variation, a number, a code such as
    ``"(L)"`` or empty, and ``cv_percent_number`` parses the numeric case
    (https://github.com/xippios/sdk-usda-nass/issues/36). The state, district, county,
    watershed and country codes each name the field beside them that holds their name;
    ``congr_district_code``, ``begin_code``, ``end_code`` and ``zip_5`` have none.
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
    state_ansi: Annotated[str, NamedBy("state_name")]
    state_fips_code: Annotated[str, NamedBy("state_name")]
    state_alpha: Annotated[str, NamedBy("state_name")]
    state_name: str
    asd_code: Annotated[str, NamedBy("asd_desc")]
    asd_desc: str
    county_ansi: Annotated[str, NamedBy("county_name")]
    county_code: Annotated[str, NamedBy("county_name")]
    county_name: str
    region_desc: str
    zip_5: str
    watershed_code: Annotated[str, NamedBy("watershed_desc")]
    watershed_desc: str
    congr_district_code: str
    country_code: Annotated[str, NamedBy("country_name")]
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cv_percent_number(self) -> Decimal | None:
        """``cv_percent`` as a number, or ``None`` for a code such as ``"(L)"`` or none."""
        return parse_decimal(self.cv_percent)

    @field_validator("week_ending", mode="before")
    @classmethod
    def _empty_is_none(cls, raw: object) -> object:
        return None if raw == "" else raw


class ApiGetResponse(UpstreamModel):
    """Payload of ``GET /api/api_GET`` with ``format=JSON``: ``{"data": [...]}``."""

    data: list[QuickStatsRecord]
