"""Task-shaped functions for USDA NASS Quick Stats.

The public API (ADR-0001, layer 2). A task composes endpoint wrappers from ``api/``,
resolves pagination and reference lookups, and returns ``Result[T]`` with full
``ResultMeta``. Write the async version, derive the sync one with ``xippios.core.sync``,
and list the sync name in ``__all__``: the MCP server and the HTTP router register
exactly what is named there.

Docstrings are read by agents: one sentence first, then ``Args:`` with examples of
valid values for every parameter. ``/add-endpoint`` walks through the whole recipe.
"""

from datetime import date

from xippios.core import Result, ResultMeta, sync

from xippios.usda.nass import api
from xippios.usda.nass._client import SOURCE
from xippios.usda.nass.enums import StateAlpha
from xippios.usda.nass.errors import RECORD_LIMIT, QueryTooLarge
from xippios.usda.nass.models import CropProgressRecord, Filters, QuickStatsRecord
from xippios.usda.nass.params import packaged_values, validate_filters

__all__ = ["get_counts", "get_crop_condition", "get_crop_progress", "get_data", "list_param_values"]


async def get_counts_async(filters: Filters) -> Result[int]:
    """Count the Quick Stats records a set of filters would return, before fetching them.

    ``api_GET`` returns at most 50,000 records; check the count first and narrow the
    filters when it is higher.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values. Keys are checked against the column table before anything is sent;
            an unknown column or operator raises ``InvalidRequestError`` naming it.
            Columns are the What, Where and When dimensions, for example
            ``commodity_desc`` (``"CORN"``), ``statisticcat_desc`` (``"AREA PLANTED"``),
            ``agg_level_desc`` (``"STATE"``, ``"COUNTY"``), ``state_alpha`` (``"VA"``),
            ``year`` (``2012``), ``freq_desc`` (``"ANNUAL"``). Operators are suffixes:
            ``__LE``, ``__LT``, ``__GT``, ``__GE``, ``__LIKE``, ``__NOT_LIKE``, ``__NE``,
            so ``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``
            counts corn records for Virginia from 2012 on.
    """
    checked = validate_filters(filters)
    response = await api.get_counts(checked)
    meta = ResultMeta(source=SOURCE, endpoint="get_counts", request=checked)
    return Result(data=response.count, meta=meta)


get_counts = sync(get_counts_async)


async def get_data_async(filters: Filters) -> Result[list[QuickStatsRecord]]:
    """Fetch published Quick Stats estimates for a set of filters, up to 50,000 records.

    Calls ``get_counts`` first: a count of zero returns an empty result without a second
    call, and a count above 50,000 raises ``QueryTooLarge`` with the count and a hint to
    narrow, before anything is fetched. Each record carries every Quick Stats column;
    ``value`` is the published figure as a string (``"510,000"``, or a suppression code
    such as ``"(D)"``) and ``value_number`` the parsed number.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values; the same shape as for ``get_counts``. A query that stays well under
            the limit names the commodity, the statistic, the level and the time, e.g.
            ``{"commodity_desc": "CORN", "statisticcat_desc": "AREA PLANTED",
            "agg_level_desc": "STATE", "state_alpha": "VA", "year": 2012}``.
    """
    checked = validate_filters(filters)
    count = (await api.get_counts(checked)).count
    meta = ResultMeta(source=SOURCE, endpoint="api_GET", request=checked)
    if count == 0:
        return Result(data=[], meta=meta)
    if count > RECORD_LIMIT:
        raise QueryTooLarge(count)
    response = await api.api_GET(checked)
    return Result(data=response.data, meta=meta)


get_data = sync(get_data_async)


async def list_param_values_async(param: str) -> Result[list[str]]:
    """List every value a Quick Stats filter parameter can take, to form valid queries.

    Six small, stable lists are answered from data packaged with this version, with no
    upstream call (``meta.endpoint`` is ``"reference"`` and ``meta.vintage`` the day they
    were fetched): ``source_desc``, ``sector_desc``, ``group_desc``, ``agg_level_desc``,
    ``freq_desc``, ``state_alpha``. Every other parameter is fetched live.

    Args:
        param: A Quick Stats column name. Large lists worth fetching live:
            ``"commodity_desc"``, ``"statisticcat_desc"``, ``"short_desc"``,
            ``"county_name"``, ``"year"``. Definitions are in
            ``docs/upstream/param_define.md``.
    """
    packaged = packaged_values(param)
    if packaged is not None:
        meta = ResultMeta(
            source=SOURCE,
            endpoint="reference",
            vintage=packaged.fetched.isoformat(),
            request={"param": param},
        )
        return Result(data=list(packaged.values), meta=meta)
    values = await api.get_param_values(param)
    meta = ResultMeta(source=SOURCE, endpoint="get_param_values", request={"param": param})
    return Result(data=values, meta=meta)


list_param_values = sync(list_param_values_async)


async def _weekly_series(
    statisticcat_desc: str,
    commodity: str,
    year: int,
    state: StateAlpha | None,
    unit_desc: str | None,
) -> Result[list[CropProgressRecord]]:
    filters: dict[str, str | int] = {
        "commodity_desc": commodity,
        "statisticcat_desc": statisticcat_desc,
        "freq_desc": "WEEKLY",
        "year": year,
        "agg_level_desc": "NATIONAL" if state is None else "STATE",
    }
    if state is not None:
        filters["state_alpha"] = state.value
    if unit_desc is not None:
        filters["unit_desc"] = unit_desc
    result = await get_data_async(filters)
    rows = sorted(
        (CropProgressRecord.from_record(record) for record in result.data),
        key=lambda row: (row.week_ending or date.min, row.unit_desc, row.short_desc),
    )
    return Result(data=rows, meta=result.meta)


async def get_crop_progress_async(
    commodity: str,
    year: int,
    *,
    state: StateAlpha | None = None,
    stage: str | None = None,
) -> Result[list[CropProgressRecord]]:
    """Weekly crop progress: the percentage planted, emerged, silking, harvested and so on.

    One row per week and stage, from the NASS Crop Progress survey (``statisticcat_desc``
    ``PROGRESS``, ``freq_desc`` ``WEEKLY``), sorted by week. Stages differ by crop;
    ``unit_desc`` names each one and ``value`` is the percentage.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``,
            ``"WINTER WHEAT"``, ``"COTTON"``; ``list_param_values("commodity_desc")``
            lists them.
        year: Crop year, e.g. ``2024``.
        state: Two-letter state code for the state series; ``None`` returns the
            national ``US TOTAL`` series.
        stage: A single stage as upstream names it, e.g. ``"PCT PLANTED"``,
            ``"PCT EMERGED"``, ``"PCT SILKING"``, ``"PCT MATURE"``, ``"PCT HARVESTED"``;
            ``None`` returns every stage.
    """
    return await _weekly_series("PROGRESS", commodity, year, state, stage)


async def get_crop_condition_async(
    commodity: str,
    year: int,
    *,
    state: StateAlpha | None = None,
    category: str | None = None,
) -> Result[list[CropProgressRecord]]:
    """Weekly crop condition: the percentage of a crop rated very poor through excellent.

    One row per week and category, from the NASS Crop Progress survey
    (``statisticcat_desc`` ``CONDITION``, ``freq_desc`` ``WEEKLY``), sorted by week.
    ``unit_desc`` names the category and ``value`` is the percentage.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``,
            ``"WINTER WHEAT"``.
        year: Crop year, e.g. ``2024``.
        state: Two-letter state code for the state series; ``None`` returns the
            national ``US TOTAL`` series.
        category: One of ``"PCT VERY POOR"``, ``"PCT POOR"``, ``"PCT FAIR"``,
            ``"PCT GOOD"``, ``"PCT EXCELLENT"``; ``None`` returns all five.
    """
    return await _weekly_series("CONDITION", commodity, year, state, category)


get_crop_progress = sync(get_crop_progress_async)
get_crop_condition = sync(get_crop_condition_async)
