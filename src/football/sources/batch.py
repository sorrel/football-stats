"""What an import wants to write, and how it gets written.

Every source produces a `Batch` — rows for whichever tables it knows about —
and one applier writes it. Sources therefore never touch the store directly,
so the guards apply uniformly: nothing is written blind, nothing is deleted,
and a source added later (11v11, say) inherits all of it by producing a
Batch like the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from football import protect, schema, store


@dataclass
class Batch:
    """Rows an import produced, by table."""

    matches: list[dict[str, str]] = field(default_factory=list)
    clubs: list[dict[str, str]] = field(default_factory=list)
    competitions: list[dict[str, str]] = field(default_factory=list)
    venues: list[dict[str, str]] = field(default_factory=list)
    seasons: list[dict[str, str]] = field(default_factory=list)
    #: Anything the source could not place, reported rather than guessed.
    notes: list[str] = field(default_factory=list)
    #: The club this import was about, marked as fully held once written.
    subject: str = ""

    def is_empty(self) -> bool:
        return not any((self.matches, self.clubs, self.competitions,
                        self.venues, self.seasons))


@dataclass(frozen=True)
class TableChange:
    table: str
    added: int
    modified: int
    unchanged: int

    @property
    def writes(self) -> int:
        return self.added + self.modified


@dataclass
class ImportReport:
    changes: list[TableChange] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    written: bool = False

    @property
    def total_writes(self) -> int:
        return sum(change.writes for change in self.changes)

    def summary(self) -> str:
        if not self.total_writes:
            return "nothing to change"
        parts = [f"{c.table}: +{c.added} ~{c.modified}"
                 for c in self.changes if c.writes]
        return ", ".join(parts)


def _existing(data_dir: Path, table: schema.Table) -> list[dict[str, str]]:
    if table is schema.MATCHES:
        return store.read_matches(data_dir)
    if table is schema.SEASONS:
        return store.read_seasons(data_dir)
    return store.read_table(data_dir, table)


def merge_row(existing: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    """Combine an incoming row with the one already held.

    A source writes only what it knows. An empty incoming value means "this
    source does not carry that field", not "the value is nothing" — so it
    never blanks what another source supplied. Re-importing engsoccerdata
    would otherwise wipe the attendances Wikipedia provided.

    Provenance accumulates rather than being replaced, so a row enriched by
    three sources still says so.
    """
    merged = dict(existing)
    for name, value in incoming.items():
        if name == "source":
            continue
        if value != "":
            merged[name] = value

    # A source tag may itself be compound ("engsoccerdata+football-data"),
    # so the parts are merged individually — appending the whole thing gives
    # "engsoccerdata+engsoccerdata+football-data".
    held = [part for part in existing.get("source", "").split("+") if part]
    for part in incoming.get("source", "").split("+"):
        if part and part not in held:
            held.append(part)
    if held:
        merged["source"] = "+".join(held)
    return merged


def _merge_all(existing: list[dict[str, str]], incoming: list[dict[str, str]],
               key: str) -> list[dict[str, str]]:
    """Every incoming row, merged onto the one it replaces."""
    held = {row[key]: row for row in existing}
    return [merge_row(held[row[key]], row) if row[key] in held else row
            for row in incoming]


def _write(data_dir: Path, table: schema.Table, rows: list[dict[str, str]]) -> None:
    merged = _merge_all(_existing(data_dir, table), rows, table.key)
    if table is schema.MATCHES:
        store.write_matches(data_dir, merged)
    elif table is schema.SEASONS:
        store.write_seasons(data_dir, merged)
    else:
        store.write_table(data_dir, table,
                          store.upsert(store.read_table(data_dir, table),
                                       merged, key=table.key))


#: The order matters: a match referring to a club the database does not yet
#: hold would fail the rebuild, so references are written before the rows
#: that point at them.
_TABLES = (
    ("clubs", schema.CLUBS, "clubs"),
    ("competitions", schema.COMPETITIONS, "competitions"),
    ("venues", schema.VENUES, "venues"),
    ("seasons", schema.SEASONS, "seasons"),
    ("matches", schema.MATCHES, "matches"),
)


def plan(data_dir: Path, batch: Batch) -> ImportReport:
    """What applying `batch` would change. Writes nothing.

    Includes the two things `apply` does beyond writing the batch itself —
    recomputing competition spans and marking the club as held — so a dry
    run describes the apply rather than a subset of it.
    """
    report = ImportReport(notes=list(batch.notes))
    for name, table, attribute in _TABLES:
        rows = getattr(batch, attribute)
        if not rows:
            continue
        existing = _existing(data_dir, table)
        changes = protect.plan_changes(
            existing, _merge_all(existing, rows, table.key), key=table.key)
        report.changes.append(TableChange(
            table=name, added=len(changes.added),
            modified=len(changes.modified), unchanged=changes.unchanged))

    spans = _span_changes(data_dir)
    if spans:
        report.notes.append(
            f"{spans} competition spans would be recomputed from every match")
    if batch.subject and batch.matches and not _is_marked(data_dir, batch.subject):
        report.notes.append(f"{batch.subject} would be marked as fully held")
    return report


def _span_changes(data_dir: Path) -> int:
    """How many competition spans differ from what the matches say."""
    spans: dict[str, list[str]] = {}
    for row in store.read_matches(data_dir):
        if row.get("season"):
            spans.setdefault(row["competition"], []).append(row["season"])
    changed = 0
    for competition in store.read_table(data_dir, schema.COMPETITIONS):
        seasons = spans.get(competition["slug"])
        if seasons and (competition["first_season"] != min(seasons)
                        or competition["last_season"] != max(seasons)):
            changed += 1
    return changed


def _is_marked(data_dir: Path, club: str) -> bool:
    return any(row["slug"] == club and row.get("imported") == "true"
               for row in store.read_table(data_dir, schema.CLUBS))


def apply(data_dir: Path, batch: Batch, repo_root: Path | None = None,
          force: bool = False) -> ImportReport:
    """Write `batch`, references first. Never deletes.

    Refuses unless git already holds a committed copy of `data_dir`, so a
    bad import is always one `git checkout` from undone. Hand corrections
    sitting uncommitted are exactly what this protects.
    """
    if not force:
        protect.assert_data_committed(repo_root or Path(data_dir).parent,
                                      data_dir)
    report = plan(data_dir, batch)
    for _, table, attribute in _TABLES:
        rows = getattr(batch, attribute)
        if rows:
            _write(data_dir, table, rows)
    _refresh_competition_spans(data_dir)
    # Only a batch that actually held matches means the club is now held.
    # A failed identification returns an empty batch, and marking it would
    # switch off the very warning that says the club is only an opponent.
    if batch.subject and batch.matches:
        _mark_imported(data_dir, batch.subject)
    report.written = True
    return report


def _mark_imported(data_dir: Path, club: str) -> None:
    """Record that this club is held completely, not just as an opponent."""
    clubs = store.read_table(data_dir, schema.CLUBS)
    for row in clubs:
        if row["slug"] == club and row.get("imported") != "true":
            row["imported"] = "true"
            store.write_table(data_dir, schema.CLUBS, clubs)
            return


def _refresh_competition_spans(data_dir: Path) -> None:
    """Recompute each competition's first and last season from every match.

    A builder only ever sees one club's matches from one source, so a span
    computed there is wrong twice over: it misses seasons another source
    supplied, and importing a second club would overwrite the competition's
    span with that club's. The store as a whole is the only thing that knows.
    """
    spans: dict[str, list[str]] = {}
    for row in store.read_matches(data_dir):
        season = row.get("season")
        if season:
            spans.setdefault(row["competition"], []).append(season)
    if not spans:
        return

    competitions = store.read_table(data_dir, schema.COMPETITIONS)
    for competition in competitions:
        seasons = spans.get(competition["slug"])
        if seasons:
            competition["first_season"] = min(seasons)
            competition["last_season"] = max(seasons)
    store.write_table(data_dir, schema.COMPETITIONS, competitions)
