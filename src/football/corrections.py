"""Hand corrections that always win, and survive any re-import.

A source can be wrong, or simply not know something. `data/corrections.csv`
holds what we know better, keyed by `match_id`, and is applied every time the
database is built.

Corrections are a *sparse overlay*: only the cells that are filled in are
applied, so a correction can supply a half-time score without disturbing
anything else in the row. This is why they live in their own file rather than
being edited into the season shards — an importer rewrites those, and a hand
correction edited into one would be silently lost the next time the source is
re-read.

A corrected match has its `source` marked, so it is never mistaken for
something the source actually said.
"""

from __future__ import annotations

from pathlib import Path

from football import store
from football.schema import MATCHES

#: Appended to a match's source when any cell of it has been corrected.
MANUAL = "+manual"

#: Never overwritten by a correction: these identify the row rather than
#: describe it, and changing one would silently create a different match.
_IDENTITY = {"match_id", "date", "home_club", "away_club", "season"}


def read(data_dir: Path) -> list[dict[str, str]]:
    """Read the corrections file. Missing means no corrections."""
    path = Path(data_dir) / "corrections.csv"
    if not path.exists():
        return []
    return store.read_csv_file(path, MATCHES)


def apply(
    rows: list[dict[str, str]],
    corrections: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Overlay corrections onto matches, returning the corrected rows.

    A correction for a match that is not present is ignored rather than
    inserted: corrections describe known matches, and a typo in a `match_id`
    should not conjure a fixture that never happened.
    """
    by_id = {row["match_id"]: row for row in rows}

    for correction in corrections:
        target = by_id.get(correction["match_id"])
        if target is None:
            continue
        changed = False
        for name, value in correction.items():
            if name in _IDENTITY or value == "":
                continue
            if target.get(name) != value:
                target[name] = value
                changed = True
        if changed and not target["source"].endswith(MANUAL):
            target["source"] = target["source"] + MANUAL

    return rows


def unmatched(
    rows: list[dict[str, str]],
    corrections: list[dict[str, str]],
) -> list[str]:
    """Correction ids that match nothing — a typo, or data not yet imported."""
    known = {row["match_id"] for row in rows}
    return sorted(c["match_id"] for c in corrections if c["match_id"] not in known)
