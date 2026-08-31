"""The `sources`, `fetch` and `import` commands.

Fetching and importing are separate commands on purpose. Fetching is slow,
paced and resumable; importing is instant and repeatable. Keeping them apart
means a schema change is re-imported from the cache without asking any host
for anything.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import click

from . import db, present, protect, store
from .analysis import verify
from .analysis.seasons import league_seasons
from .cache import PageCache
from .ids import slugify
from .crawl import crawl
from .schema import CLUBS
from .sources import builders  # noqa: F401  (registers the sources)
from .sources import registry
from .sources.batch import apply, plan
from .sources.fetch import FetchError, HttpSource


def resolve_for_import(resolve_club, conn, club: str | None) -> str:
    """The club to import, which need not exist yet.

    Analysis commands are strict: a typo returning an empty record looks
    exactly like a real answer. Importing is the opposite case — the club is
    often absent precisely because this is the import that will add it, and
    refusing would mean nothing could ever be imported into an empty
    database.
    """
    if not club:
        raise click.ClickException(
            "Which club? Pass --club <slug>, or set the FOOTBALL_CLUB "
            "environment variable.")
    try:
        return resolve_club(conn, club)
    except click.ClickException:
        # Slugified before returning: the builders compare it against
        # slugs, so "Barrow" or "crystal palace" would match nothing, and
        # it also becomes the subject that marks the club as imported.
        slug = slugify(club)
        click.echo(click.style(
            f"{slug} is not in the database yet; this import will add it.",
            fg="yellow"))
        return slug


def _open(data_dir, db_path):
    """A connection for the import commands, even if the data is inconsistent.

    Importing must not require a database that builds: an import is often
    exactly what would repair one that does not. Matches naming a
    competition we have not created yet is the ordinary case here, so a
    failed build falls back to a database holding only the club list, which
    is all these commands need to resolve a name.
    """
    # Built to one side first: db.build deletes its target before loading,
    # so building straight into db_path would leave the working database
    # destroyed whenever the data is inconsistent — and the failure is the
    # ordinary case here.
    scratch = Path(db_path).with_suffix(".building")
    try:
        conn = db.build(data_dir, scratch)
    except (db.ValidationError, store.UnknownColumnError) as exc:
        scratch.unlink(missing_ok=True)
        click.echo(click.style(
            f"The database does not currently build ({exc}). Continuing with "
            "the club list only — an import may well be what fixes it. The "
            "existing database is untouched.", fg="yellow"))
        return _clubs_only(data_dir)

    conn.close()
    scratch.replace(db_path)
    return db.sqlite3.connect(db_path)


def _is_api_error(text: str) -> bool:
    """Whether a response is an API error rather than a page."""
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return False
    try:
        return "error" in json.loads(text)
    except ValueError:
        return False


def _clubs_only(data_dir):
    """A throwaway in-memory database holding just the clubs."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE clubs (slug TEXT PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT OR IGNORE INTO clubs (slug, name) VALUES (?, ?)",
        [(row["slug"], row["name"])
         for row in store.read_table(data_dir, CLUBS)])
    return conn


def _cache(ctx: click.Context) -> PageCache:
    return PageCache(ctx.obj.get("cache_dir", "cache"))


def _context(data_dir: Path, club: str, conn) -> dict:
    """What a builder needs to know about what we already hold.

    Takes the connection the command already opened rather than building a
    second database of its own, which left a stray file behind and did the
    work twice.
    """
    clubs = store.read_table(data_dir, CLUBS)
    name = next((row["name"] for row in clubs if row["slug"] == club), club)

    try:
        league = {s.season: (s.competition, str(s.tier) if s.tier else "")
                  for s in league_seasons(conn, club)}
    except sqlite3.Error:
        # A database missing the seasons table is not a reason to refuse a
        # fetch; builders that need it will report they had nothing.
        league = {}

    row = next((row for row in clubs if row["slug"] == club), {})
    former = [part.strip() for part in (row.get("former_names") or "").split("|")
              if part.strip()]

    return {"club_name": name, "club_names": [name, *former], "clubs": clubs,
            "matches": store.read_matches(data_dir), "league_seasons": league}


def register(cli, resolve_club):
    """Add the source commands to `cli`."""

    @cli.command(name="sources")
    def sources_command():
        """List the data sources, what they cover, and what is cached."""
        rows = []
        for source in registry.all_sources():
            state = "available" if source.available else "unavailable"
            rows.append([source.name, source.covers, source.licence, state])
        click.echo(present.render_table(
            ["source", "covers", "licence", "state"], rows))
        for source in registry.all_sources():
            if not source.available:
                click.echo(click.style(
                    f"\n{source.name}: {source.unavailable_because}",
                    fg="yellow"))

    @cli.command(name="fetch")
    @click.argument("source_name")
    @click.option("--club", default=None, envvar="FOOTBALL_CLUB",
                  help="Whose pages to fetch. Required.")
    @click.option("--budget", default=200, show_default=True,
                  help="Most pages to fetch in this run. It resumes where it "
                       "stopped, so a large job can be done over several runs.")
    @click.pass_context
    def fetch_command(ctx, source_name, club, budget):
        """Download a source's pages into the cache, slowly."""
        source = _require(source_name)
        conn = _open(ctx.obj["data_dir"], ctx.obj["db_path"])
        club = resolve_for_import(resolve_club, conn, club)

        cache = _cache(ctx)
        keys = source.keys(_context(Path(ctx.obj["data_dir"]), club, conn))
        outstanding = [key for key in keys if not cache.has(key)]
        click.echo(f"{len(keys)} pages, {len(outstanding)} not yet cached.")
        if not outstanding:
            click.echo("Nothing to fetch.")
            return

        http = HttpSource()
        pace = http.delay_for(outstanding[0])
        click.echo(f"Fetching up to {budget} at about {pace:.0f}s apart. "
                   "Interrupt at any time; it resumes.")

        failures: list[str] = []

        class Reporting:
            def delay_for(self, key):
                return http.delay_for(key)

            def fetch(self, key):
                try:
                    text = http.fetch(key)
                    if _is_api_error(text):
                        # A 200 carrying "no such page". Returning it empty
                        # keeps it out of the cache, so a corrected address
                        # is tried afresh rather than skipped as fetched.
                        failures.append(f"{key}: no such page")
                        return ""
                    return text
                except FetchError as exc:
                    # Report and carry on: one missing page must not end a
                    # crawl. The empty result is not cached, so it retries.
                    failures.append(str(exc))
                    return ""

        result = crawl(outstanding, cache, Reporting(), budget=budget)
        click.echo(f"Fetched {result.fetched}, {result.remaining} still to go.")
        if failures:
            click.echo(click.style(
                f"{len(failures)} pages could not be fetched; they are not "
                "cached, so running again will retry them.", fg="yellow"))

    @cli.command(name="verify")
    @click.option("--club", default=None, envvar="FOOTBALL_CLUB",
                  help="Whose matches to check. Required.")
    @click.option("--source", "only", default=None,
                  help="Check one source rather than all of them.")
    @click.pass_context
    def verify_command(ctx, club, only):
        """Re-read the sources and report where they contradict the database.

        Every other check asks whether the data is possible. This asks
        whether it is right — the only kind that catches a plausible wrong
        value.
        """
        data_dir = Path(ctx.obj["data_dir"])
        conn = _open(data_dir, ctx.obj["db_path"])
        club = resolve_for_import(resolve_club, conn, club)
        cache = _cache(ctx)
        context = _context(data_dir, club, conn)
        held = store.read_matches(data_dir)

        wanted = [registry.get(only)] if only else registry.all_sources()
        if only and wanted[0] is None:
            raise click.ClickException(f"{only!r} is not a source.")

        total = 0
        for source in wanted:
            if not source.available:
                continue
            if not any(cache.has(key) for key in source.keys(context)):
                continue
            batch = source.build(cache, club, context)
            found = verify.compare(held, batch.matches, source.name)
            missing = verify.unknown_to_us(held, batch.matches)
            total += len(found)

            if not found and not missing:
                click.echo(click.style(f"{source.name}: agrees", dim=True))
                continue

            click.echo(click.style(f"{source.name}:", fg="cyan", bold=True))
            for field, count, example in verify.summarise(found):
                click.echo(f"  {count:>4} × {field}")
                click.echo(click.style(f"       {example}", dim=True))
            if missing:
                click.echo(click.style(
                    f"  {len(missing)} matches it holds that we do not "
                    f"(e.g. {missing[0]})", dim=True))

        click.echo()
        click.echo(click.style(
            f"{total} disagreements. None are resolved automatically: which "
            "source is right is a judgement.",
            fg="yellow" if total else "green"))

    @cli.command(name="import")
    @click.argument("source_name")
    @click.option("--club", default=None, envvar="FOOTBALL_CLUB",
                  help="Whose data to import. Required.")
    @click.option("--dry-run", is_flag=True,
                  help="Report what would change and write nothing.")
    @click.option("--force", is_flag=True,
                  help="Write even with uncommitted changes in the data "
                       "directory. Only when you mean to lose them.")
    @click.pass_context
    def import_command(ctx, source_name, club, dry_run, force):
        """Turn a source's cached pages into rows."""
        source = _require(source_name)
        data_dir = Path(ctx.obj["data_dir"])
        conn = _open(data_dir, ctx.obj["db_path"])
        club = resolve_for_import(resolve_club, conn, club)

        cache = _cache(ctx)
        context = _context(data_dir, club, conn)
        cached = sum(1 for key in source.keys(context) if cache.has(key))
        if not cached:
            raise click.ClickException(
                f"No pages cached for {source.name}. "
                f"Run `football fetch {source.name}` first.")

        batch = source.build(cache, club, context)
        batch.subject = club
        if dry_run:
            report = plan(data_dir, batch)
        else:
            try:
                report = apply(data_dir, batch, force=force)
            except protect.DirtyDataError as exc:
                raise click.ClickException(
                    f"{exc}\n\nCommit or discard them first, or pass --force "
                    "if you mean to lose them.") from exc

        click.echo(click.style(
            f"{source.name}: {report.summary()}",
            fg="green" if report.total_writes else None))
        if report.changes:
            click.echo(present.render_table(
                ["table", "added", "modified", "unchanged"],
                [[c.table, c.added, c.modified, c.unchanged]
                 for c in report.changes]))
        for note in report.notes[:10]:
            click.echo(click.style(f"  note: {note}", dim=True))
        if len(report.notes) > 10:
            click.echo(click.style(
                f"  ... and {len(report.notes) - 10} more notes", dim=True))

        if dry_run:
            click.echo(click.style("\nNothing written (--dry-run).", dim=True))
        elif report.total_writes:
            click.echo("\nRun `football rebuild` to load the changes.")


def _require(name: str):
    source = registry.get(name)
    if source is None:
        raise click.ClickException(
            f"{name!r} is not a source. Known: {', '.join(registry.names())}")
    if not source.available:
        raise click.ClickException(
            f"{name} is not available: {source.unavailable_because}")
    return source
