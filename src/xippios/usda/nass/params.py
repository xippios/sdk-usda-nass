"""Packaged Quick Stats parameter lists and column definitions (conventions §3).

Nine parameter lists ship inside the package so the common lookups need no network
call, and the column table from ``docs/upstream/param_define.md`` ships as
``columns.csv``. Files are produced by ``scripts/refresh_reference.py``
(``/refresh-reference-data``), never by hand, and a list is read with
``PackagedList.load(PACKAGE, name)``; ``reference/README.md`` carries the provenance.
"""

import difflib
import functools

from pydantic import Field, field_validator
from xippios.core import InvalidRequestError, UpstreamModel, load_table

from xippios.usda.nass._client import SOURCE
from xippios.usda.nass.models import Filters

__all__ = [
    "DERIVED_LISTS",
    "OPERATORS",
    "PACKAGED_PARAMS",
    "Column",
    "columns",
    "validate_filters",
]

OPERATORS: tuple[str, ...] = ("LE", "LT", "GT", "GE", "LIKE", "NOT_LIKE", "NE")
"""Suffixes a filter key may carry after ``__``, as ``docs/upstream/api.md`` lists them."""

PACKAGE = "xippios.usda.nass"

PACKAGED_PARAMS: tuple[str, ...] = (
    "source_desc",
    "sector_desc",
    "group_desc",
    "agg_level_desc",
    "freq_desc",
    "state_alpha",
    "statisticcat_desc",
    "unit_desc",
    "domain_desc",
)
"""Parameters whose value lists ship inside the package."""

DERIVED_LISTS: dict[str, dict[str, str | int]] = {
    "progress_stages": {"statisticcat_desc": "PROGRESS", "agg_level_desc": "NATIONAL"},
    "condition_categories": {"statisticcat_desc": "CONDITION", "agg_level_desc": "NATIONAL"},
}
"""Lists of ``unit_desc`` values derived from one year of national weekly data.

Quick Stats has no endpoint for "the stages a progress series uses", so the refresh
script fetches the national PROGRESS and CONDITION rows of the previous year and keeps
the distinct ``unit_desc`` values; the file, ``reference/<name>.json`` with ``param``
``unit_desc``, records the query it came from in its ``note``.
"""


class Column(UpstreamModel):
    """One row of ``reference/columns.csv``: a Quick Stats column as ``param_define.md`` defines it.

    Attributes:
        column: Column name, usable as a filter key.
        dimension: The What, Where, When or Data Value dimension heading it sits under.
        max_length: Maximum length upstream documents for the value.
        definition: Upstream's definition text.
    """

    column: str
    dimension: str
    max_length: int | None = Field(default=None)
    definition: str

    @field_validator("max_length", mode="before")
    @classmethod
    def _empty_is_none(cls, raw: object) -> object:
        return None if raw == "" else raw


def columns() -> list[Column]:
    """Every Quick Stats column, from the packaged ``columns.csv``."""
    return load_table(PACKAGE, "columns.csv", Column)


@functools.cache
def _column_names() -> frozenset[str]:
    return frozenset(column.column for column in columns())


def validate_filters(filters: Filters) -> dict[str, str | int]:
    """Check every filter key against the packaged column table before calling upstream.

    Quick Stats ignores unknown column names, so a misspelt key would silently query the
    whole database. A key is ``<column>`` or ``<column>__<OPERATOR>``.

    Args:
        filters: The query parameters as the caller gave them.

    Returns:
        The filters as a plain dict, unchanged.

    Raises:
        InvalidRequestError: Naming every unknown column, with the closest valid names,
            and every unknown operator.
    """
    known = _column_names()
    problems: list[str] = []
    for key in filters:
        column, _, operator = key.partition("__")
        if column not in known:
            close = difflib.get_close_matches(column, sorted(known), n=3)
            hint = f"; did you mean {', '.join(close)}?" if close else ""
            problems.append(f"{key!r} is not a Quick Stats column{hint}")
        elif operator and operator not in OPERATORS:
            allowed = ", ".join(f"__{op}" for op in OPERATORS)
            problems.append(f"{key!r}: unknown operator {operator!r}; use one of {allowed}")
    if problems:
        raise InvalidRequestError(
            "; ".join(problems) + ". Columns are defined in docs/upstream/param_define.md.",
            source=SOURCE,
        )
    return dict(filters)
