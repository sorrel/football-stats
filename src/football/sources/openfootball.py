"""Parse the openfootball Football.TXT format (CC0, public domain).

Covers the League Cup and FA Cup from 2000-01, with half-time scores — the
two gaps the primary source leaves. The format is human-written text rather
than CSV:

    = English EFL Cup 2023/24

    ▪ Round 1
      Tue Aug 8 2023
        19:00  Huddersfield Town  v Middlesbrough FC   2-3 (1-1)
               Peterborough Utd   v Swindon Town       4-1 pen. (1-1, 1-0)

The score grammar is the subtle part. **The main score is the latest stage
reached, and the brackets list the preceding stages, most recent first.**

    2-3 (1-1)                      full time 2-3, half time 1-1
    4-1 pen. (1-1, 1-0)            shootout 4-1, full time 1-1, half time 1-0
    3-5 pen. (0-0)                 shootout 3-5, full time 0-0, half unknown
    0-1 a.e.t. (0-0)               extra time 0-1, full time 0-0, half unknown
    4-2 pen. 2-1 a.e.t. (2-1, 2-0) shootout 4-2, extra time 2-1, full 2-1, half 2-0

So a single bracket means half time on a plain line but full time on an
`a.e.t.`/`pen.` line. Reading it the other way round would silently corrupt
every extra-time match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

#: `= English EFL Cup 2023/24`
_HEADING = re.compile(r"^=\s*(?P<name>.+?)\s+(?P<season>\d{4})/(?P<yy>\d{2,4})\s*$")

#: `▪ Round 1`, `» Quarterfinals`
_ROUND = re.compile(r"^\s*[▪»■*]\s*(?P<round>.+?)\s*$")

#: `  Tue Aug 8 2023` or `  Sun Feb 25`
#: `# Date       Fri Nov 8 2019 - Sat Aug 1 2020 (267d)` — the file states
#: the span it covers, which is the only reliable way to place a date whose
#: year is omitted.
_SPAN = re.compile(
    r"^#\s*Date\s+(?:\w{3}\s+)?([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4})"
    r"\s*[-–]\s*(?:\w{3}\s+)?([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4})",
    re.MULTILINE)

_DATE = re.compile(
    r"^\s{2,}(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?P<rest>[A-Z][a-z]{2}\s+\d{1,2}(?:\s+\d{4})?)\s*$")

#: `4-2 pen.` — the shootout, when there was one.
_PENS = re.compile(r"^\s*(\d{1,2})-(\d{1,2})\s*pen\.\s*")

#: `2-1 a.e.t.` — the score after extra time, when it was played.
_AET = re.compile(r"^\s*(\d{1,2})-(\d{1,2})\s*a\.e\.t\.\s*")

#: A bare `2-3` — the main score, when no later stage is named.
_PLAIN = re.compile(r"^\s*(\d{1,2})-(\d{1,2})\s*")

#: `(1-1, 1-0)` — the stages preceding the main score, most recent first.
_BRACKETS = re.compile(r"\(([^)]*)\)\s*$")

#: A fixture line: optional kick-off, two club names either side of " v ",
#: then the result. Two or more spaces separate the away club from the
#: result, which is what keeps a name like "Aston Villa" intact.
_MATCH_LINE = re.compile(
    r"^\s+(?:(?P<time>\d{1,2}:\d{2})\s+)?"
    r"(?P<home>\S(?:.*?\S)?)\s+v\s+(?P<away>\S(?:.*?\S)?)\s{2,}"
    r"(?P<tail>\d.*)$"
)

_ROUND_NAMES = {
    "final": "Final", "semifinals": "Semi-final", "semi-finals": "Semi-final",
    "quarterfinals": "Quarter-final", "quarter-finals": "Quarter-final",
    "round of 16": "Round of 16",
}


@dataclass(frozen=True)
class Fixture:
    date: str
    kickoff: str
    round: str
    home: str
    away: str
    ht: tuple[str, str] = ("", "")
    ft: tuple[str, str] = ("", "")
    aet: tuple[str, str] = ("", "")
    pens: tuple[str, str] = ("", "")


@dataclass
class Document:
    competition: str = ""
    season: str = ""
    fixtures: list[Fixture] = field(default_factory=list)


def normalise_round(text: str) -> str:
    lowered = text.strip().lower()
    if lowered in _ROUND_NAMES:
        return _ROUND_NAMES[lowered]
    matched = re.fullmatch(r"round\s+(\d+)", lowered)
    return f"Round {matched.group(1)}" if matched else text.strip()


def _pair(text: str) -> tuple[str, str]:
    parts = text.split("-")
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", "")


def parse_result(tail: str) -> dict[str, tuple[str, str]]:
    """Split a result tail into its stages.

    The main score is the latest stage reached. The brackets hold the stages
    before it, most recent first — so on a plain line the single bracket is
    half time, but on an `a.e.t.`/`pen.` line it is full time.
    """
    text = tail.strip()
    stages: dict[str, tuple[str, str]] = {}

    brackets: list[str] = []
    bracketed = _BRACKETS.search(text)
    if bracketed:
        brackets = [part.strip() for part in bracketed.group(1).split(",")
                    if part.strip()]
        text = text[:bracketed.start()].strip()

    pens = _PENS.match(text)
    if pens:
        stages["pens"] = (pens.group(1), pens.group(2))
        text = text[pens.end():]

    aet = _AET.match(text)
    if aet:
        stages["aet"] = (aet.group(1), aet.group(2))
        text = text[aet.end():]

    if not stages:
        plain = _PLAIN.match(text)
        if not plain:
            return {}
        stages["ft"] = (plain.group(1), plain.group(2))
        if brackets:
            stages["ht"] = _pair(brackets[0])
        return stages

    # A later stage was named, so the brackets are full time then half time.
    if brackets:
        stages["ft"] = _pair(brackets[0])
    if len(brackets) > 1:
        stages["ht"] = _pair(brackets[1])
    return stages


def parse_span(text: str) -> tuple[str, str] | None:
    """The dates the file says it covers, if it says."""
    match = _SPAN.search(text)
    if not match:
        return None
    try:
        first = datetime.strptime(match.group(1), "%b %d %Y").date().isoformat()
        last = datetime.strptime(match.group(2), "%b %d %Y").date().isoformat()
    except ValueError:
        return None
    return first, last


def parse(text: str, default_year: int | None = None) -> Document:
    """Parse one Football.TXT file."""
    document = Document()
    current_round = ""
    current_date = ""
    season_start = default_year
    span = parse_span(text)

    for line in text.splitlines():
        if not line.strip():
            continue

        heading = _HEADING.match(line)
        if heading:
            document.competition = heading.group("name").strip()
            start = int(heading.group("season"))
            document.season = f"{start}-{heading.group('yy')[-2:]}"
            season_start = start
            continue

        if line.lstrip().startswith("#"):
            continue

        round_line = _ROUND.match(line)
        if round_line and " v " not in line:
            current_round = normalise_round(round_line.group("round"))
            continue

        date_line = _DATE.match(line)
        if date_line:
            current_date, season_start = _read_date(
                date_line.group("rest"), season_start, current_date, span)
            continue

        fixture = _MATCH_LINE.match(line)
        if fixture and current_date:
            stages = parse_result(fixture.group("tail"))
            if not stages:
                continue
            document.fixtures.append(Fixture(
                date=current_date,
                kickoff=fixture.group("time") or "",
                round=current_round,
                home=fixture.group("home").strip(),
                away=fixture.group("away").strip(),
                ht=stages.get("ht", ("", "")),
                ft=stages.get("ft", ("", "")),
                aet=stages.get("aet", ("", "")),
                pens=stages.get("pens", ("", "")),
            ))

    return document


def _read_date(rest: str, season_start: int | None, previous: str,
               span: tuple[str, str] | None = None
               ) -> tuple[str, int | None]:
    """Read `Aug 8 2023` or `Feb 25`.

    An explicit year is used as given. A missing one is placed inside the
    span the file declares, which is the only reliable way: a season normally
    runs August to May, but the 2019-20 FA Cup finished in July and August
    2020, so no rule about months can tell those from a season's opening
    August. Without the span, months from August fall in the starting year.
    """
    parts = rest.split()
    if len(parts) == 3:
        stamp = datetime.strptime(rest, "%b %d %Y")
        return stamp.date().isoformat(), season_start
    if season_start is None:
        return previous, season_start

    candidates = []
    for year in (season_start, season_start + 1):
        try:
            candidates.append(
                datetime.strptime(f"{rest} {year}", "%b %d %Y").date().isoformat())
        except ValueError:
            continue
    if not candidates:
        return previous, season_start

    if span:
        inside = [date for date in candidates if span[0] <= date <= span[1]]
        if inside:
            return inside[0], season_start

    # European qualifying is played in July of the starting year, so July
    # belongs there. Only a delayed season finishes in July, and those files
    # declare a span, which is handled above.
    month = datetime.strptime(parts[0], "%b").month
    year = season_start if month >= 7 else season_start + 1
    try:
        return (datetime.strptime(f"{rest} {year}", "%b %d %Y").date().isoformat(),
                season_start)
    except ValueError:
        return candidates[0], season_start
