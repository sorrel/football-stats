"""The `football` command line interface.

Read-only by construction: `rebuild` is the only command that writes, and it
writes only the derived database. Queries run against a connection opened in
SQLite's read-only mode, so a mistyped statement cannot alter anything.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import click

from . import cli_import, cli_stats, db, present, schema, store
from . import help as help_module

#: `-h` alongside `--help`, on the group and every subcommand beneath it.
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

#: Anything that is not a bare SELECT/WITH is refused. Leading comments and
#: whitespace are stripped first so a write cannot hide behind them.
_COMMENT = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/|\s)+", re.DOTALL)


def _run(action):
    """Run a zero-argument callable, turning known failures into guidance.

    Every call that can reach the files or the database is routed through
    here rather than wrapped in its own try/except, so the translation from
    exception to user-facing message stays in one place.
    """
    try:
        return action()
    except db.ValidationError as exc:
        raise click.ClickException(
            f"The canonical files are inconsistent: {exc}\n"
            "The files are the truth, so fix data/ rather than the database."
        ) from exc
    except store.UnknownColumnError as exc:
        raise click.ClickException(
            f"{exc}\nEither add the field to src/football/schema.py or remove "
            "the column from the file."
        ) from exc
    except sqlite3.OperationalError as exc:
        # A mistyped column or table name: by some distance the likeliest
        # failure at the prompt, and one that would otherwise be a traceback.
        raise click.ClickException(
            f"SQLite could not run that query: {exc}\n"
            "Run `football tables` to see what is available."
        ) from exc


def _plural(count: int, singular: str, plural: str) -> str:
    """"1 venue" rather than "1 venues"."""
    return f"{count} {singular if count == 1 else plural}"


def _strip_leading_comments(sql: str) -> str:
    return _COMMENT.sub("", sql, count=1)


@click.group(cls=help_module.ColouredGroup, context_settings=CONTEXT_SETTINGS)
@click.option("--data-dir", default="data", envvar="FOOTBALL_DATA_DIR",
              type=click.Path(path_type=Path),
              help="Directory holding the canonical CSV files. "
                   "May be set with FOOTBALL_DATA_DIR.")
@click.option("--db", "db_path", default="build/football.db",
              envvar="FOOTBALL_DB", type=click.Path(path_type=Path),
              help="Path to the derived SQLite database. "
                   "May be set with FOOTBALL_DB.")
@click.option("--cache-dir", default="cache", envvar="FOOTBALL_CACHE",
              type=click.Path(path_type=Path),
              help="Where downloaded pages are kept. May be set with "
                   "FOOTBALL_CACHE.")
@click.pass_context
def cli(ctx: click.Context, data_dir: Path, db_path: Path,
        cache_dir: Path) -> None:
    """A local database of English football results."""
    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = data_dir
    ctx.obj["db_path"] = db_path
    ctx.obj["cache_dir"] = cache_dir


@cli.command()
@click.pass_context
def rebuild(ctx: click.Context) -> None:
    """Rebuild the database from the canonical files, validating as it loads."""
    conn = _run(lambda: db.build(ctx.obj["data_dir"], ctx.obj["db_path"]))
    counts = {
        table.name: conn.execute(f"SELECT COUNT(*) FROM {table.name}").fetchone()[0]
        for table in schema.TABLES
    }
    summary = ", ".join(
        _plural(counts[name], singular, plural)
        for name, singular, plural in (
            ("matches", "match", "matches"),
            ("clubs", "club", "clubs"),
            ("competitions", "competition", "competitions"),
            ("venues", "venue", "venues"),
        )
    )
    click.echo(
        click.style(f"Rebuilt {ctx.obj['db_path']}", fg="green") + f": {summary}."
    )


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise click.ClickException(
            f"No database at {db_path}. Run `football rebuild` first.")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


@cli.command()
@click.argument("sql")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def query(ctx: click.Context, sql: str, as_json: bool) -> None:
    """Run a read-only SQL query against the database."""
    if not _strip_leading_comments(sql).lower().startswith(("select", "with")):
        raise click.ClickException(
            "Queries are read-only: the statement must begin with SELECT or WITH.")

    conn = _read_only_connection(ctx.obj["db_path"])
    cursor = _run(lambda: conn.execute(sql))
    headers = [description[0] for description in cursor.description]
    rows = cursor.fetchall()

    if as_json:
        click.echo(json.dumps([dict(zip(headers, row)) for row in rows], indent=2))
        return

    click.echo(present.render_table(headers, rows))


@cli.command()
@click.pass_context
def tables(ctx: click.Context) -> None:
    """List the tables, views and columns available to query."""
    conn = _read_only_connection(ctx.obj["db_path"])
    names = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
        "ORDER BY type DESC, name"
    ).fetchall()
    for (name,) in names:
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({name})")]
        click.echo(click.style(name, fg="green", bold=True))
        click.echo(click.style("  " + ", ".join(columns), dim=True))


def _analysis_connection(ctx: click.Context) -> sqlite3.Connection:
    """Open the database read-only for an analysis command."""
    return _read_only_connection(ctx.obj["db_path"])


# Registered last so the analysis commands share the group's options.
cli_stats.register(cli, _analysis_connection)
cli_import.register(cli, cli_stats.resolve_club)


def main() -> None:
    """Entry point: run the CLI, then leave a blank line behind it.

    The trailing line is a reading aid at the prompt only — it is skipped
    when the output is piped or redirected, so nothing downstream has to
    cope with a stray newline.
    """
    try:
        cli.main()
    finally:
        if sys.stdout.isatty():
            click.echo()
