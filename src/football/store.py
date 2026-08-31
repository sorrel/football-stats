"""Read and write the canonical CSV files.

Rows are written sorted by key with a fixed column order, so re-scraping
produces a clean diff. Reading tolerates a file that predates a newly added
column (it reads as empty) but rejects a column the schema does not know
about, because that means the file and the code have diverged.

Matches are sharded one file per season under `matches/`; the three small
reference tables are single files. Every write merges by key rather than
replacing wholesale, so a partial write can never delete rows it did not
mention.
"""

import csv
from collections.abc import Iterable
from pathlib import Path

from football.schema import MATCHES, SEASONS, Table


class UnknownColumnError(Exception):
    """A CSV file carries a column the schema does not declare."""


def _read_csv(path: Path, table: Table) -> list[dict[str, str]]:
    if not path.exists():
        return []
    known = set(table.field_names())
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        unknown = set(reader.fieldnames or ()) - known
        if unknown:
            raise UnknownColumnError(
                f"{path.name} has column(s) the schema does not declare: "
                f"{', '.join(sorted(unknown))}"
            )
        return [
            {name: (row.get(name) or "") for name in table.field_names()}
            for row in reader
        ]


def _write_csv(path: Path, table: Table, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row.get(table.key, ""))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table.field_names()))
        writer.writeheader()
        for row in ordered:
            writer.writerow({name: row.get(name, "") for name in table.field_names()})


def read_csv_file(path: Path, table: Table) -> list[dict[str, str]]:
    """Read any CSV that follows `table`'s columns, from an explicit path."""
    return _read_csv(Path(path), table)


def _table_path(data_dir: Path, table: Table) -> Path:
    return Path(data_dir) / f"{table.name}.csv"


def read_table(data_dir: Path, table: Table) -> list[dict[str, str]]:
    """Read one of the single-file reference tables."""
    return _read_csv(_table_path(data_dir, table), table)


def write_table(data_dir: Path, table: Table, rows: Iterable[dict[str, str]]) -> None:
    """Write one of the single-file reference tables."""
    _write_csv(_table_path(data_dir, table), table, rows)


def upsert(
    rows: list[dict[str, str]],
    new_rows: Iterable[dict[str, str]],
    key: str,
) -> list[dict[str, str]]:
    """Merge new rows into existing ones, replacing by key.

    Deletion is deliberately not a concept: a key absent from `new_rows` is
    carried through untouched.
    """
    merged = {row[key]: row for row in rows}
    for row in new_rows:
        merged[row[key]] = row
    return list(merged.values())


def read_seasons(data_dir: Path) -> list[dict[str, str]]:
    """Every stored club-season."""
    return _read_csv(Path(data_dir) / "seasons.csv", SEASONS)


def write_seasons(data_dir: Path, rows: Iterable[dict[str, str]]) -> None:
    """Merge club-seasons into the canonical file, never deleting."""
    path = Path(data_dir) / "seasons.csv"
    merged = upsert(_read_csv(path, SEASONS), rows, key=SEASONS.key)
    _write_csv(path, SEASONS, merged)


def _season_path(data_dir: Path, season: str) -> Path:
    return Path(data_dir) / "matches" / f"{season}.csv"


def seasons(data_dir: Path) -> list[str]:
    """Every season with a stored shard, oldest first."""
    directory = Path(data_dir) / "matches"
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.csv"))


def read_matches(data_dir: Path) -> list[dict[str, str]]:
    """Every stored match, gathered from all season shards."""
    rows: list[dict[str, str]] = []
    for season in seasons(data_dir):
        rows.extend(_read_csv(_season_path(data_dir, season), MATCHES))
    return rows


def read_season(data_dir: Path, season: str) -> list[dict[str, str]]:
    """The matches stored for one season."""
    return _read_csv(_season_path(data_dir, season), MATCHES)


def write_matches(data_dir: Path, rows: Iterable[dict[str, str]]) -> None:
    """Merge matches into their per-season shards.

    Only the seasons present in `rows` are touched, and within each of those,
    existing matches not mentioned are carried through. Writing part of a
    season is therefore always safe.
    """
    by_season: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        season = row.get("season", "")
        if not season:
            raise ValueError(
                f"match {row.get('match_id')!r} has no season to file it under"
            )
        by_season.setdefault(season, []).append(row)

    for season, season_rows in by_season.items():
        existing = read_season(data_dir, season)
        merged = upsert(existing, season_rows, key=MATCHES.key)
        _write_csv(_season_path(data_dir, season), MATCHES, merged)
