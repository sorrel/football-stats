"""Compare what the sources say against what the database holds.

Every other check asks whether the data is internally possible. This one
asks whether it is *right*, by re-reading the sources and reporting where
they disagree with the store or with each other.

That is the only check that catches a plausible wrong value. A misdated cup
final broke no constraint, contradicted no rule, and read perfectly — it was
found only because two sources named the same round differently.

Disagreements are reported, never resolved: which source is right is a
judgement, and the applier's rule (a later non-empty value wins) makes that
judgement silently. This makes it visible.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Fields where a difference is a real disagreement rather than one source
#: simply knowing more. Provenance and derived fields are excluded.
COMPARED = (
    "date", "season", "competition", "round", "leg", "tier",
    "ht_home", "ht_away", "ft_home", "ft_away",
    "aet_home", "aet_away", "pens_home", "pens_away",
    "attendance", "kickoff", "venue", "neutral", "is_replay", "status",
)


@dataclass(frozen=True)
class Disagreement:
    match_id: str
    field: str
    held: str
    offered: str
    source: str

    def describe(self) -> str:
        return (f"{self.match_id}: {self.field} is {self.held!r} but "
                f"{self.source} says {self.offered!r}")


def compare(
    held: Iterable[dict[str, str]],
    offered: Iterable[dict[str, str]],
    source: str,
) -> list[Disagreement]:
    """Where `offered` contradicts `held`.

    A blank on either side is not a disagreement: it means one of them does
    not carry that field, which is the ordinary case between sources.
    """
    by_id = {row["match_id"]: row for row in held}
    found: list[Disagreement] = []

    for row in offered:
        current = by_id.get(row["match_id"])
        if current is None:
            continue
        for field in COMPARED:
            mine, theirs = current.get(field, ""), row.get(field, "")
            if mine and theirs and mine != theirs:
                found.append(Disagreement(
                    match_id=row["match_id"], field=field,
                    held=mine, offered=theirs, source=source))
    return found


def unknown_to_us(
    held: Iterable[dict[str, str]],
    offered: Iterable[dict[str, str]],
) -> list[str]:
    """Matches a source offers that the database does not hold.

    Usually a competition we have not imported. Occasionally a match we lost
    — a date correction that left the old row behind and had it removed, say.
    """
    known = {row["match_id"] for row in held}
    return sorted({row["match_id"] for row in offered
                   if row["match_id"] not in known})


def summarise(found: list[Disagreement]) -> list[tuple[str, int, str]]:
    """Disagreements by field, commonest first, with one example."""
    by_field: dict[str, list[Disagreement]] = {}
    for item in found:
        by_field.setdefault(item.field, []).append(item)
    return sorted(
        ((field, len(items), items[0].describe())
         for field, items in by_field.items()),
        key=lambda row: (-row[1], row[0]))
