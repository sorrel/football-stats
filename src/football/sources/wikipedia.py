"""Parse Wikipedia season articles (CC-BY-SA 4.0).

Two things are read, from two kinds of article:

- **League tables**, from the `{{#invoke:Sports table}}` template on a
  competition's season article. `team_order` gives the final positions and
  the per-club parameters give the record.
- **Attendances**, from the `{{Football box}}` templates on a *club's*
  season article, which the other sources do not carry before 1993.

Both are parsed from wikitext fetched through the page cache, never from
rendered HTML: the templates are structured data, while the rendered table
is a presentation of it and changes shape far more often.

Only recent seasons use these templates — the 1996-97 Third Division article
does not — which is why this fills the recent end while the standings source
covers 1888 to 2023-24.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from football.sources.common import parse_attendance

#: `{{#invoke:Sports table|main|style=WDL ... }}`
_TABLE = re.compile(r"\{\{#invoke:Sports table\s*\|", re.IGNORECASE)

_TEAM_ORDER = re.compile(r"\|\s*team_order\s*=\s*([^|\n}]+)")
_STAT = re.compile(r"\|\s*(win|draw|loss|gf|ga)_([A-Za-z0-9]+)\s*=\s*(-?\d+)")
_ADJUST = re.compile(r"\|\s*adjust_points_([A-Za-z0-9]+)\s*=\s*(-?\d+)")
#: A name runs to the end of its line: the value itself contains a pipe,
#: inside the wikilink, so it cannot be delimited by one.
_NAME = re.compile(r"\|\s*name_([A-Za-z0-9]+)\s*=\s*(.+?)\s*$", re.MULTILINE)
_UPDATE = re.compile(r"\|\s*update\s*=\s*([^|\n}]+)")

#: `[[Brighton & Hove Albion F.C.|Brighton & Hove Albion]]` -> the label.
_WIKILINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")

#: The season English league football switched from two points for a win.
_THREE_POINTS_FROM = 1981


@dataclass(frozen=True)
class TableRow:
    code: str
    name: str
    position: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    point_adjustment: int = 0

    @property
    def played(self) -> int:
        return self.won + self.drawn + self.lost

    def points(self, season_start: int) -> int:
        """Points as awarded that season, including any adjustment.

        Two points for a win before 1981-82. Wikipedia's template computes
        this rather than storing it, so it is computed here too — with the
        era rule made explicit rather than assumed.
        """
        per_win = 3 if season_start >= _THREE_POINTS_FROM else 2
        return self.won * per_win + self.drawn + self.point_adjustment


def clean_name(value: str) -> str:
    """Strip wiki markup from a club name."""
    text = _WIKILINK.sub(r"\1", value)
    return re.sub(r"<!--.*?-->", "", text).strip()


def has_league_table(wikitext: str) -> bool:
    return bool(_TABLE.search(wikitext))


def is_complete(wikitext: str) -> bool:
    """Whether the article marks the season as finished.

    A table still being updated is a snapshot, not a final position.
    """
    match = _UPDATE.search(wikitext)
    return bool(match) and match.group(1).strip().lower() == "complete"


def parse_league_table(wikitext: str) -> list[TableRow]:
    """Read the final table. Returns [] if the article has none."""
    start = _TABLE.search(wikitext)
    if not start:
        return []
    block = wikitext[start.start():]
    order_match = _TEAM_ORDER.search(block)
    if not order_match:
        return []

    codes = [code.strip() for code in order_match.group(1).split(",")
             if code.strip()]
    block = block[:_end_of_template(block)]

    stats: dict[str, dict[str, int]] = {}
    for stat, code, value in _STAT.findall(block):
        stats.setdefault(code, {})[stat] = int(value)
    adjustments = {code: int(value) for code, value in _ADJUST.findall(block)}
    names = {code: clean_name(value) for code, value in _NAME.findall(block)}

    rows = []
    for position, code in enumerate(codes, start=1):
        figures = stats.get(code)
        if not figures or {"win", "draw", "loss"} - figures.keys():
            continue  # a club with no record is not a finished season
        rows.append(TableRow(
            code=code,
            name=names.get(code, code),
            position=position,
            won=figures["win"], drawn=figures["draw"], lost=figures["loss"],
            goals_for=figures.get("gf", 0), goals_against=figures.get("ga", 0),
            point_adjustment=adjustments.get(code, 0),
        ))
    return rows


def _end_of_template(block: str) -> int:
    """Where the template ends, so a later table cannot bleed into this one."""
    depth = 0
    for index in range(len(block) - 1):
        pair = block[index:index + 2]
        if pair == "{{":
            depth += 1
        elif pair == "}}":
            depth -= 1
            if depth == 0:
                return index + 2
    return len(block)


#: `{{football box collapsible | date = 12 July 2025 | attendance = 31,729 }}`
_BOX = re.compile(r"\{\{football box(?:\s+collapsible)?\s*\|", re.IGNORECASE)

#: A parameter runs to the next one. The whitespace after `=` must not
#: include newlines: an empty value would otherwise swallow the parameters
#: that follow it.
_PARAM = re.compile(r"\|[ \t]*(\w+)[ \t]*=[ \t]*(.*?)(?=\n[ \t]*\||\n[ \t]*\}\})",
                    re.DOTALL)

_DATE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")

_MONTHS = {m.lower(): n for n, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), start=1)}


@dataclass(frozen=True)
class MatchBox:
    date: str
    home: str
    away: str
    attendance: str
    kickoff: str
    stadium: str


def parse_date(text: str) -> str:
    """`12 July 2025` -> `2025-07-12`. Returns "" if unreadable."""
    match = _DATE.search(_WIKILINK.sub(r"\1", text or ""))
    if not match:
        return ""
    day, month, year = match.groups()
    number = _MONTHS.get(month.lower())
    return f"{year}-{number:02d}-{int(day):02d}" if number else ""


def parse_match_boxes(wikitext: str) -> list[MatchBox]:
    """Every match box on a club's season article."""
    boxes = []
    for start in _BOX.finditer(wikitext):
        block = wikitext[start.start():]
        block = block[:_end_of_template(block)]
        values = {name: value.strip() for name, value in _PARAM.findall(block)}

        date = parse_date(values.get("date", ""))
        home = clean_name(values.get("team1", ""))
        away = clean_name(values.get("team2", ""))
        if not (date and home and away):
            continue

        kickoff = values.get("time", "").strip()
        boxes.append(MatchBox(
            date=date, home=home, away=away,
            attendance=parse_attendance(values.get("attendance", "")),
            kickoff=kickoff if re.fullmatch(r"\d{1,2}:\d{2}", kickoff) else "",
            stadium=clean_name(values.get("stadium", "")),
        ))
    return boxes


def enrich_matches(
    matches: list[dict[str, str]],
    boxes: list[MatchBox],
    club_slug: str,
    slugify_name,
) -> tuple[int, list[str]]:
    """Fill blank attendances and kick-off times on matches we already hold.

    Never inserts. A club's season article covers friendlies and testimonials
    we deliberately do not store, so an unmatched box is reported rather than
    added — and only blank fields are filled, so a figure from a more
    authoritative source is never overwritten.
    """
    by_key: dict[tuple[str, bool], dict[str, str]] = {}
    for row in matches:
        if row["home_club"] == club_slug:
            by_key[(row["date"], True)] = row
        elif row["away_club"] == club_slug:
            by_key[(row["date"], False)] = row

    filled = 0
    unmatched: list[str] = []

    for box in boxes:
        we_are_home = slugify_name(box.home) == club_slug
        if not we_are_home and slugify_name(box.away) != club_slug:
            continue  # neither side is us: not our match
        row = by_key.get((box.date, we_are_home))
        if row is None:
            unmatched.append(box.date)
            continue

        changed = False
        for field, value in (("attendance", box.attendance),
                             ("kickoff", box.kickoff)):
            if value and not row.get(field):
                row[field] = value
                changed = True
        if changed:
            filled += 1
            if "wikipedia" not in row["source"]:
                row["source"] = f"{row['source']}+wikipedia"

    return filled, sorted(set(unmatched))
