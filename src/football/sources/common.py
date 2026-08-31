"""Helpers every source needs.

Season labels and attendance figures were each parsed in three places, with
the same rules written slightly differently every time. One copy means one
place to be right — and one place to fix when a source turns out to write
something unexpected.
"""

from __future__ import annotations

import re

#: How sources write "we do not know". `NA` is engsoccerdata's, `None` is
#: Wikipedia's; both mean absent, and neither is a value.
ABSENT = frozenset({"", "NA", "N/A", "NULL", "None", "-"})


def clean(value: str | None) -> str:
    """A source's value, or "" if it means nothing."""
    text = (value or "").strip()
    return "" if text in ABSENT else text


def season_label(start_year: str | int) -> str:
    """The season beginning in `start_year`: 1982 -> "1982-83"."""
    year = int(start_year)
    return f"{year}-{(year + 1) % 100:02d}"


#: engsoccerdata writes some large crowds in scientific notation — nine
#: League Cup finals are recorded as `1e+05`. Read as a leading run of
#: digits that is 1, five orders of magnitude out.
_SCIENTIFIC = re.compile(r"^(\d+(?:\.\d+)?)[eE]\+?(\d+)$")


def parse_attendance(text: str | None) -> str:
    """A crowd figure with its separators removed.

    A stated zero is kept: matches behind closed doors really had no crowd,
    which is a fact rather than a gap.
    """
    value = clean(text)
    if not value:
        return ""

    scientific = _SCIENTIFIC.match(value)
    if scientific:
        return str(int(float(scientific.group(1))
                       * 10 ** int(scientific.group(2))))

    leading = re.match(r"([\d,\s]+)", value)
    return re.sub(r"[^\d]", "", leading.group(1)) if leading else ""


def parse_score(text: str | None) -> tuple[str, str]:
    """Split a "2-1" score. Empty strings when it cannot be read."""
    match = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)\s*", clean(text))
    return (match.group(1), match.group(2)) if match else ("", "")
