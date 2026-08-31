"""The contract every page parser satisfies.

Phase 2 supplies the parser that understands the real markup. This module
fixes the interface and the score-consistency rules, which are properties of
football rather than of any particular source.
"""

from dataclasses import dataclass, field
from typing import Protocol

from football import schema


class InconsistentScore(Exception):
    """A parsed score is internally impossible."""


@dataclass(frozen=True)
class ParsedPage:
    matches: list[dict[str, str]] = field(default_factory=list)
    clubs: list[dict[str, str]] = field(default_factory=list)
    competitions: list[dict[str, str]] = field(default_factory=list)
    venues: list[dict[str, str]] = field(default_factory=list)


class MatchParser(Protocol):
    def parse(self, page_text: str) -> ParsedPage: ...


def blank_row(table: schema.Table) -> dict[str, str]:
    """An empty row with every declared column — empty means unknown."""
    return {name: "" for name in table.field_names()}


def _as_int(value: str) -> int | None:
    return int(value) if value != "" else None


def check_scores(row: dict[str, str]) -> None:
    """Enforce the running-total convention. Unknown values are permitted."""
    ht_h, ht_a = _as_int(row["ht_home"]), _as_int(row["ht_away"])
    ft_h, ft_a = _as_int(row["ft_home"]), _as_int(row["ft_away"])
    et_h, et_a = _as_int(row["aet_home"]), _as_int(row["aet_away"])
    pk_h, pk_a = _as_int(row["pens_home"]), _as_int(row["pens_away"])

    if None not in (ht_h, ft_h) and ht_h > ft_h:
        raise InconsistentScore(
            f"half-time home goals {ht_h} exceed full-time {ft_h}")
    if None not in (ht_a, ft_a) and ht_a > ft_a:
        raise InconsistentScore(
            f"half-time away goals {ht_a} exceed full-time {ft_a}")
    if None not in (ft_h, et_h) and et_h < ft_h:
        raise InconsistentScore(
            f"extra time home goals {et_h} are fewer than at full time {ft_h}")
    if None not in (ft_a, et_a) and et_a < ft_a:
        raise InconsistentScore(
            f"extra time away goals {et_a} are fewer than at full time {ft_a}")
    if None not in (pk_h, pk_a) and pk_h == pk_a:
        raise InconsistentScore(f"shootout cannot be drawn at {pk_h}-{pk_a}")
