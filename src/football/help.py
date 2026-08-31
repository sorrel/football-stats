"""Coloured, sectioned help output.

Matches the house style of the sibling `home-connect` and `hue-control` tools:
cyan bold headings, green command names, dim descriptions. All width
arithmetic uses `display_width()` rather than `len()`, and colour is applied
after padding is calculated, never before.
"""

from __future__ import annotations

from dataclasses import dataclass

import click

from .present import display_width


@dataclass(frozen=True)
class Section:
    """One block of the quick-reference help: a heading and its commands."""

    name: str
    blurb: str
    entries: list[tuple[str, str]]


SECTIONS: list[Section] = [
    Section(
        name="DATABASE",
        blurb="Build the queryable database from the canonical files.",
        entries=[
            ("football rebuild", "Rebuild the database, validating as it loads."),
        ],
    ),
    Section(
        name="ANALYSIS",
        blurb="Ask a question, narrow it with filters. Try --help on any of these.",
        entries=[
            ("football record", "Played, won, drawn, lost, goals."),
            ("football h2h <club>", "The record against one opponent."),
            ("football runs", "Every longest run, combined and home/away."),
            ("football runs --of unbeaten", "One kind of run, listed in full."),
            ("football extremes --by margin", "Biggest wins, crowds, scorelines."),
            ("football clubs [name]", "List clubs, or find one by name."),
            ("football seasons", "League position and outcome per season."),
            ("football seasons --cups", "How far each cup run went."),
            ("  --club <name>", "Required. Fuzzy: \"albion\" offers a choice."),
            ("  filters", "-c <comp>  --tier N  --side away  --day saturday"),
            ("", "--season-from 1979-80  --season-to 1983-84  --opponent <club>"),
        ],
    ),
    Section(
        name="DATA",
        blurb="Where the data comes from, and how to add more.",
        entries=[
            ("football sources", "List the sources, what they cover, licences."),
            ("football fetch <source>", "Download its pages, slowly. Resumable."),
            ("football import <source>", "Turn cached pages into rows."),
            ("football import <source> --dry-run", "Report changes, write nothing."),
            ("football verify", "Where the sources contradict the database."),
        ],
    ),
    Section(
        name="QUERIES",
        blurb="Ask questions of the results. Read-only, always.",
        entries=[
            ('football query "<sql>"', "Run a read-only SQL query."),
            ('football query "<sql>" --json', "Machine-readable output."),
            ("football tables", "List the tables, views and columns available."),
        ],
    ),
]


class ColouredGroup(click.Group):
    """A `click.Group` that prints the sectioned quick reference."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        click.echo(
            click.style("football", fg="cyan", bold=True)
            + click.style(" — a local database of English football results", dim=True)
        )
        click.echo()
        for section in SECTIONS:
            click.echo(click.style(section.name, fg="cyan", bold=True))
            click.echo(click.style(f"  {section.blurb}", dim=True))
            width = max(display_width(command) for command, _ in section.entries)
            for command, description in section.entries:
                padding = " " * (width - display_width(command))
                click.echo("  " + click.style(command, fg="green") + padding
                           + "  " + click.style(description, dim=True))
            click.echo()
