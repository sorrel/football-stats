"""Build the derived SQLite database from the canonical CSVs.

The database is disposable: it is dropped and rebuilt from the files every
time. The load doubles as validation — a broken reference or a duplicate
fixture fails the build and names the row, rather than being silently
accepted.
"""

import sqlite3
from pathlib import Path

from football import corrections, schema, store

_SQL_KIND = {"int": "INTEGER", "bool": "INTEGER", "text": "TEXT",
             "date": "TEXT", "time": "TEXT"}

#: Shared by both halves of the union, so the two perspectives cannot drift
#: apart. `{club}`/`{opponent}` and the goal columns are swapped per half.
_PERSPECTIVE = """
SELECT
    m.match_id, m.date, m.season, m.competition, m.round, m.venue, m.neutral,
    m.attendance, m.kickoff,
    m.{us}_yellows AS yellows_for, m.{them}_yellows AS yellows_against,
    m.{us}_reds AS reds_for, m.{them}_reds AS reds_against,
    CASE CAST(strftime('%w', m.date) AS INTEGER)
        WHEN 0 THEN 'Sunday'    WHEN 1 THEN 'Monday'   WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday' WHEN 4 THEN 'Thursday' WHEN 5 THEN 'Friday'
        ELSE 'Saturday' END AS day_of_week,
    m.{club} AS club, m.{opponent} AS opponent, '{side}' AS home_or_away,
    m.ft_{us} AS goals_for, m.ft_{them} AS goals_against,
    CASE WHEN m.ft_{us} > m.ft_{them} THEN 'W'
         WHEN m.ft_{us} < m.ft_{them} THEN 'L' ELSE 'D' END AS result,
    CASE
        WHEN m.pens_{us} IS NOT NULL AND m.pens_{them} IS NOT NULL
            THEN CASE WHEN m.pens_{us} > m.pens_{them} THEN 'W' ELSE 'L' END
        WHEN m.aet_{us} IS NOT NULL AND m.aet_{them} IS NOT NULL
            THEN CASE WHEN m.aet_{us} > m.aet_{them} THEN 'W'
                      WHEN m.aet_{us} < m.aet_{them} THEN 'L' ELSE 'D' END
        ELSE CASE WHEN m.ft_{us} > m.ft_{them} THEN 'W'
                  WHEN m.ft_{us} < m.ft_{them} THEN 'L' ELSE 'D' END
    END AS final_result
FROM matches m
"""


def _club_matches_view() -> str:
    home = _PERSPECTIVE.format(
        club="home_club", opponent="away_club", side="H", us="home", them="away")
    away = _PERSPECTIVE.format(
        club="away_club", opponent="home_club", side="A", us="away", them="home")
    return f"CREATE VIEW club_matches AS {home} UNION ALL {away}"


class ValidationError(Exception):
    """The canonical files are internally inconsistent."""


def _create_table_sql(table: schema.Table) -> str:
    columns = []
    for field in table.fields:
        parts = [field.name, _SQL_KIND[field.kind]]
        if field.name == table.key:
            parts.append("PRIMARY KEY")
        elif field.required:
            parts.append("NOT NULL")
        columns.append(" ".join(parts))
    return f"CREATE TABLE {table.name} ({', '.join(columns)})"


def _coerce(value: str, kind: str):
    if value == "":
        return None
    if kind == "int":
        return int(value)
    if kind == "bool":
        return 1 if value.lower() in {"true", "yes", "1"} else 0
    return value


def _rows_for(data_dir: Path, table: schema.Table) -> list[dict[str, str]]:
    # Matches are sharded per season; the reference tables are single files.
    if table is schema.MATCHES:
        rows = store.read_matches(data_dir)
        return corrections.apply(rows, corrections.read(data_dir))
    if table is schema.SEASONS:
        return store.read_seasons(data_dir)
    return store.read_table(data_dir, table)


def build(data_dir: Path, db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    for table in schema.TABLES:
        conn.execute(_create_table_sql(table))

    for table in schema.TABLES:
        placeholders = ", ".join("?" for _ in table.fields)
        insert = (f"INSERT INTO {table.name} "
                  f"({', '.join(table.field_names())}) VALUES ({placeholders})")
        for row in _rows_for(data_dir, table):
            values = [_coerce(row[f.name], f.kind) for f in table.fields]
            try:
                conn.execute(insert, values)
            except sqlite3.IntegrityError as exc:
                raise ValidationError(
                    f"{table.name}: {exc} in row {row.get(table.key)!r}") from exc

    _validate_references(conn)
    _validate_no_duplicate_fixtures(conn)
    _validate_no_repeated_ties(conn)

    conn.execute(_club_matches_view())
    conn.execute("CREATE INDEX idx_matches_date ON matches(date)")
    conn.commit()
    return conn


def _validate_references(conn: sqlite3.Connection) -> None:
    checks = [
        ("home_club", "clubs", "slug"), ("away_club", "clubs", "slug"),
        ("competition", "competitions", "slug"), ("venue", "venues", "slug"),
    ]
    for column, target, target_key in checks:
        orphans = conn.execute(
            f"SELECT DISTINCT m.{column} FROM matches m "
            f"LEFT JOIN {target} t ON m.{column} = t.{target_key} "
            f"WHERE m.{column} IS NOT NULL AND t.{target_key} IS NULL"
        ).fetchall()
        if orphans:
            names = ", ".join(sorted(str(o[0]) for o in orphans))
            raise ValidationError(
                f"matches.{column} refers to unknown {target}: {names}")


def _validate_no_repeated_ties(conn: sqlite3.Connection) -> None:
    """Two matches for the same tie, on different dates, that are neither a
    replay nor a leg.

    This is what a corrected date leaves behind: the identifier embeds the
    date, so fixing one creates a second row rather than changing the first.
    Legitimate repeats are excluded — a replay carries `is_replay`, a
    two-legged tie carries `leg`, and a group meeting swaps the two clubs.
    """
    repeats = conn.execute(
        """
        SELECT season, competition, round, home_club, away_club,
               COUNT(*), GROUP_CONCAT(date)
        FROM matches
        WHERE round <> '' AND round IS NOT NULL
          AND COALESCE(is_replay, 0) = 0
          AND COALESCE(leg, '') = ''
        GROUP BY season, competition, round, home_club, away_club
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    if repeats:
        first = repeats[0]
        raise ValidationError(
            f"the same tie appears twice: {first[3]} v {first[4]} in "
            f"{first[2]} of the {first[1]} in {first[0]}, on {first[6]}. "
            "A corrected date leaves the old row behind; remove it.")


def _validate_no_duplicate_fixtures(conn: sqlite3.Connection) -> None:
    duplicates = conn.execute(
        "SELECT date, home_club, away_club, COUNT(*) FROM matches "
        "GROUP BY date, home_club, away_club HAVING COUNT(*) > 1"
    ).fetchall()
    if duplicates:
        first = duplicates[0]
        raise ValidationError(
            f"duplicate fixture: {first[1]} v {first[2]} on {first[0]} "
            f"appears {first[3]} times")
