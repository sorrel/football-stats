"""The analysis commands.

Kept out of `cli.py`, which stays the plumbing. Every command here takes the
same filter options, so "the biggest win in the FA Cup away in the 1980s" is
one question and four filters rather than a command of its own.
"""

from __future__ import annotations

import functools

import click

from . import present
from .analysis import extremes as ex
from dataclasses import replace

import sys

from .analysis import clubs as club_matching
from .analysis import filters as filters_module
from .analysis import records, runs
from .analysis import seasons as season_analysis
from .analysis.extremes import MEASURES
from .analysis.filters import RUN_TYPES, SIDES, Filters


#: The shared filter vocabulary, declared once and keyed by the parameter
#: name each option binds to. `filter_options` attaches these to a command
#: and `prepared` removes them again after building the Filters, so the two
#: cannot drift apart into two lists of the same thing.
FILTER_OPTIONS = {
    "club": click.option("--club", default=None, envvar="FOOTBALL_CLUB",
                         help="Whose record to report. Required; may be set "
                          "with the FOOTBALL_CLUB environment variable."),
    "competition": click.option("--competition", "-c", default=None,
                                help="Competition slug, e.g. fa-cup."),
    "tier": click.option("--tier", type=int, default=None,
                         help="League tier, 1 to 4."),
    "comp_type": click.option("--type", "comp_type", default=None,
                              help="Competition type: league, play-off, "
                               "europe, or a cup's own slug. Each cup is its "
                               "own type."),
    "opponent": click.option("--opponent", "-o", default=None,
                             help="Opponent slug."),
    "venue": click.option("--venue", default=None, help="Venue slug."),
    "side": click.option("--side", type=click.Choice(SIDES), default=None,
                         help="Home, away, or on a neutral ground."),
    "season_from": click.option("--season-from", default=None,
                                help="First season, e.g. 1979-80."),
    "season_to": click.option("--season-to", default=None,
                              help="Last season, e.g. 1982-83."),
    "day": click.option("--day", default=None, help="Day of the week."),
    "english_league_only": click.option("--english-league-only", is_flag=True,
                                        help="Exclude non-League and foreign "
                                         "opposition."),
}

#: The parameter names those options bind to.
_FILTER_NAMES = tuple(FILTER_OPTIONS)


def filter_options(*, exclude=()):
    """Attach the shared filter vocabulary to a command.

    `exclude` drops a filter the command already states another way. Click
    keys its parse results by parameter name, so two parameters of one name
    share a single slot: whichever fills it discards the other's value
    without a word. `h2h` names its opponent positionally, so it must not
    also carry `--opponent`.
    """
    unknown = sorted(set(exclude) - set(FILTER_OPTIONS))
    if unknown:
        raise ValueError(f"not filter options: {unknown}")

    def decorate(command):
        for name, option in reversed(FILTER_OPTIONS.items()):
            if name not in exclude:
                command = option(command)
        return command
    return decorate


def _candidates(conn) -> list[club_matching.Candidate]:
    return [club_matching.Candidate(slug, name or slug)
            for slug, name in conn.execute("SELECT slug, name FROM clubs")]


def resolve_club(conn, club: str | None) -> str:
    """The club to report on, or a refusal explaining what to do.

    There is deliberately no default: with more than one club loaded, a
    default would answer a question about one club with another's record.

    An unrecognised name is refused rather than silently returning no
    matches, because a typo and a club with nothing to report look identical
    in the output. An ambiguous one — "Albion" is three clubs — offers a
    numbered choice when there is someone there to answer, and lists the
    options and stops when there is not, so a script never hangs on a prompt.
    """
    if not club:
        raise click.ClickException(
            "Which club? Pass --club <slug>, or set the FOOTBALL_CLUB "
            "environment variable.\nRun `football clubs` to see them.")

    found = club_matching.find_clubs(_candidates(conn), club)

    if not found:
        raise click.ClickException(
            f"{club!r} is not a club in this database. "
            "Run `football clubs` to see them.")
    if len(found) == 1:
        return found[0].slug

    lines = [f"{club!r} matches {len(found)} clubs:"]
    for number, candidate in enumerate(found, start=1):
        lines.append(f"  {number}. {candidate.name}  ({candidate.slug})")

    if not sys.stdin.isatty():
        raise click.ClickException(
            "\n".join(lines) + "\n\nName one exactly, or use its slug.")

    click.echo("\n".join(lines))
    choice = click.prompt("Which one?", type=click.IntRange(1, len(found)))
    return found[choice - 1].slug


def prepared(connect):
    """Wrap a command so it receives an open connection and ready filters.

    Every analysis command opened a connection, resolved the club and built
    the filters in the same three lines. Repeating that is where a command
    added later quietly forgets one of them — the club resolution in
    particular, which is what keeps a typo from reading as an empty record.
    """
    def decorate(function):
        @functools.wraps(function)
        @click.pass_context
        def command(ctx, *args, **kwargs):
            conn = connect(ctx)
            kwargs["club"] = resolve_club(conn, kwargs.get("club"))
            filters = build_filters(**kwargs)
            for name in _FILTER_NAMES:
                kwargs.pop(name, None)
            return function(conn, filters, *args, **kwargs)
        return command
    return decorate


def build_filters(**kwargs) -> Filters:
    return Filters(
        club=kwargs["club"], competition=kwargs.get("competition"),
        tier=kwargs.get("tier"), type=kwargs.get("comp_type"),
        opponent=kwargs.get("opponent"), venue=kwargs.get("venue"),
        side=kwargs.get("side"), season_from=kwargs.get("season_from"),
        season_to=kwargs.get("season_to"), day=kwargs.get("day"),
        english_league_only=kwargs.get("english_league_only", False),
    )


def club_name(conn, slug: str) -> str:
    """The club's display name, falling back to the slug."""
    row = conn.execute("SELECT name FROM clubs WHERE slug = ?", (slug,)).fetchone()
    return row[0] if row and row[0] else slug.replace("-", " ")


#: Colour is applied *after* the table is laid out — the outcome is the last
#: column, so styling it cannot disturb the alignment of anything before it,
#: and `display_width` would otherwise count the escape codes as characters.
#: Longest first, so "promoted" cannot match inside "promoted-via-play-offs".
_OUTCOME_STYLE = (
    ("champions", {"fg": "bright_green", "bold": True}),
    ("promoted-via-play-offs", {"fg": "bright_green", "bold": True}),
    ("play-offs-lost", {"fg": "yellow"}),
    ("promoted", {"fg": "bright_green", "bold": True}),
    ("relegated", {"fg": "bright_yellow", "bold": True}),
    ("left-the-league", {"fg": "bright_yellow"}),
    ("current", {"dim": True}),
    ("war", {"dim": True}),
)


def display_outcome(outcome: str, position: int | None = None) -> str:
    """How an outcome reads in the table.

    Finishing top is reported as winning the division, whatever followed:
    it is the fact a supporter would name first. Promotion remains visible
    in the tier of the season below.

    An unchanged season shows a dash — sixty rows of "stayed" is noise, and
    the eye wants the exceptions.
    """
    if position == 1:
        return "champions"
    return "-" if outcome == "stayed" else outcome


def style_outcome(line: str) -> str:
    """Colour the outcome at the end of a rendered row, if there is one."""
    for outcome, style in _OUTCOME_STYLE:
        if line.endswith(outcome):
            return line[: -len(outcome)] + click.style(outcome, **style)
    return line


def is_fully_held(conn, slug: str) -> bool:
    """Whether this club has been imported, or is only ever an opponent."""
    row = conn.execute("SELECT imported FROM clubs WHERE slug = ?",
                       (slug,)).fetchone()
    return bool(row and row[0])


#: How each competition type is headed, in the order the tables are shown.
#: A type not listed keeps its own name and follows these.
_TYPE_LABELS = (
    ("league", "League"),
    ("play-off", "Play-offs"),
    ("fa-cup", "FA Cup"),
    ("league-cup", "League Cup"),
    ("europe", "Europe"),
)


def _type_label(comp_type: str) -> str:
    for name, label in _TYPE_LABELS:
        if name == comp_type:
            return label
    return comp_type.replace("-", " ").capitalize()


def _type_order(comp_type: str) -> tuple[int, str]:
    names = [name for name, _ in _TYPE_LABELS]
    known = comp_type in names
    return (names.index(comp_type) if known else len(names), comp_type)


def _competition_types(conn, filters: Filters) -> list[str]:
    """Which competition types these matches fall under, in reading order."""
    where, params = filters.where()
    found = conn.execute(
        f"SELECT DISTINCT comp.type {filters_module.FROM_CLAUSE} "
        f"WHERE {where}", params).fetchall()
    return sorted((row[0] for row in found if row[0]), key=_type_order)


#: Where each named stage falls, for putting rounds in the order they are
#: played. Numbered rounds sort among themselves by number; "3pp" is the
#: third-place play-off, which follows the semi-finals.
_STAGES = ("Round of 16", "Quarter-final", "Semi-final", "3pp", "Final")


def _round_order(name: str) -> tuple[int, float, str]:
    """A sort key putting a group stage first and the final last."""
    if name.startswith("Group"):
        return (0, 0, name)
    if name.startswith("Round "):
        number = name.removeprefix("Round ")
        if number.isdigit():
            return (1, int(number), name)
    if name in _STAGES:
        return (2, _STAGES.index(name), name)
    return (3, 0, name)  # anything unrecognised, alphabetically, at the end


def _heading(filters: Filters, title: str, conn=None) -> None:
    name = club_name(conn, filters.club) if conn is not None else filters.club
    click.echo()
    click.echo(click.style(title, fg="cyan", bold=True))
    click.echo(click.style(f"  {name} — {filters.describe()}", dim=True))
    if conn is not None and not is_fully_held(conn, filters.club):
        # A club held only as an opponent has just its meetings with the
        # clubs we do hold. Reported as a record it looks complete, and is
        # not — so say so before the figures rather than after.
        click.echo(click.style(
            f"  {name} has not been imported: these are only their matches "
            f"against clubs that have been.\n"
            f"  Run `football import engsoccerdata --club {filters.club}` "
            "for their full record.", fg="yellow"))


def register(cli, connect):
    """Add the analysis commands to `cli`. `connect` opens the database."""

    @cli.command()
    @filter_options()
    @prepared(connect)
    def record(conn, filters):
        """Played, won, drawn, lost, and goals."""
        result = records.record(conn, filters)
        _heading(filters, "Record", conn)
        if not result.played:
            click.echo("\n" + "No matches match those filters.")
            return
        def _line(label, record):
            return [label, record.played, record.won, record.drawn,
                    record.lost, record.goals_for, record.goals_against,
                    record.goal_difference, f"{record.win_percentage:.1f}"]

        # Home, away and neutral, then the total. A neutral ground is its own
        # line and never folded into away: a cup final at Wembley is not an
        # away match, whoever is listed first.
        #
        # A --side filter is the user having already chosen; splitting would
        # override their filter and report matches they excluded.
        if filters.side:
            lines = [_line(filters.side, result)]
        else:
            lines = []
            for side in ("home", "away", "neutral"):
                split = records.record(conn, replace(filters, side=side))
                if split.played:
                    lines.append(_line(side, split))
            if len(lines) != 1:
                lines.append(_line("total", result))

        click.echo(present.render_table(
            ["venue", "played", "won", "drawn", "lost", "for", "against",
             "diff", "win %"], lines))
        if result.without_score:
            click.echo(click.style(
                f"\n{result.without_score} of these have no recorded score and "
                "are excluded from the goal totals.", dim=True))

        # Play-off matches carry a tier, so a tier filter sweeps them in
        # alongside league matches. Rather than change what --tier means,
        # say so: a league record that quietly includes play-offs is wrong.
        where, params = filters.where()
        play_offs = conn.execute(
            f"SELECT COUNT(*) {filters_module.FROM_CLAUSE} "
            f"WHERE {where} AND comp.type = 'play-off'", params).fetchone()[0]
        if play_offs:
            click.echo(click.style(
                f"\nIncludes {play_offs} play-off "
                f"{'match' if play_offs == 1 else 'matches'}. Play-offs are an "
                "addendum to a league season, not part of it — add "
                "--type league to exclude them.", fg="yellow"))

    @cli.command()
    @click.argument("opponent")
    @click.option("--list", "list_all", is_flag=True, help="Show every meeting.")
    @filter_options(exclude=("opponent",))
    @click.pass_context
    def h2h(ctx, opponent, list_all, **kwargs):
        """The record against one opponent, split by where it was played."""
        conn = connect(ctx)
        kwargs["club"] = resolve_club(conn, kwargs.get("club"))
        kwargs["opponent"] = resolve_club(conn, opponent)
        filters = build_filters(**kwargs)

        us = club_name(conn, filters.club)
        them = club_name(conn, filters.opponent)
        click.echo()
        click.echo(click.style(f"{us} v {them}", fg="cyan", bold=True))
        # The opponent is in the heading, so leave it out of the subtitle.
        other = replace(filters, opponent=None).describe()
        if other != "all matches":
            click.echo(click.style(f"  {other}", dim=True))
        click.echo()

        overall = records.record(conn, filters)
        if not overall.played:
            click.echo("They have never met under those filters.")
            return
        click.echo(overall.summary())

        def _figures(record):
            return [record.played, record.won, record.drawn, record.lost,
                    record.goals_for, record.goals_against,
                    f"{record.win_percentage:.1f}"]

        columns = ["played", "won", "drawn", "lost", "for", "against", "win %"]
        # A cup draw settles nothing, so the cup tables say what became of
        # it: how many contests the matches made up, and how each was
        # decided. "Contests" rather than the football word "ties", which
        # reads as a synonym for draws.
        cup_columns = ["contests", "played", "won", "drawn", "lost", "for",
                       "against", "replays", "aet", "pens", "win %"]

        def _venue_rows(these, cup=False):
            """Home, away and neutral under `these` filters.

            Neutral is its own row, never folded into away: a cup final at a
            neutral ground is not an away match, whoever is listed first.
            """
            rows = []
            for side in ("home", "away", "neutral"):
                at = replace(these, side=side)
                split = records.record(conn, at)
                if not split.played:
                    continue  # a permanent row of zeros is noise
                if not cup:
                    rows.append([side, *_figures(split)])
                    continue
                extras = records.cup_extras(conn, at)
                played, *rest, percentage = _figures(split)
                rows.append([side, extras.contests, played, *rest, extras.replays,
                             extras.extra_time, extras.penalties, percentage])
            return rows

        # A table per competition: a league meeting and a cup contest are
        # different questions, and each has its own home, away and neutral.
        def _breakdown_rows(these, expression, cup, order):
            """A total for each round, or each division, in playing order."""
            groups = sorted(records.breakdown(conn, these, expression), key=order)
            rows = []
            for group in groups:
                played, *rest, percentage = _figures(group.record)
                if cup:
                    rows.append([group.label, group.extras.contests, played,
                                 *rest, group.extras.replays,
                                 group.extras.extra_time,
                                 group.extras.penalties, percentage])
                else:
                    rows.append([group.label, played, *rest, percentage])
            return rows

        types = _competition_types(conn, filters)
        replayed = 0
        for comp_type in types:
            cup = comp_type != "league"
            these = replace(filters, type=comp_type)
            label = _type_label(comp_type)
            rows = _venue_rows(these, cup=cup)
            if cup:
                replayed += sum(row[8] for row in rows)
            click.echo(present.render_table(
                ["venue", *(cup_columns if cup else columns)], rows,
                caption=click.style(label, fg="cyan")))

            # Which rounds a cup run reached, and which divisions the league
            # meetings were in — a total apiece, since the venue split above
            # has already answered where they were played.
            if cup:
                heading, expression, order = (
                    "round", "cm.round", lambda g: _round_order(g.label))
            else:
                heading, expression, order = (
                    "division", "comp.name", lambda g: g.first_date)
            split = _breakdown_rows(these, expression, cup, order)
            if split:  # a cup whose rounds went unrecorded has nothing to say
                click.echo(present.render_table(
                    [heading, *(cup_columns if cup else columns)], split,
                    caption=click.style(f"{label} by {heading}", fg="cyan")))

        # "replays" could as easily mean the draws that were replayed, and
        # the two counts sit on different rows: the draw is at one ground and
        # the replay at the other. Say which is meant, but only when there
        # are any — on the great majority of pairings there are none.
        if replayed:
            click.echo(click.style(
                "\nA replay is a further match in the same contest, so "
                "played exceeds contests: replays counts the matches played "
                "as a replay, "
                "not the draws that led to them.", dim=True))

        # Then the totals, which is where the competitions are compared. With
        # only one of them the table would be that competition twice over.
        if len(types) > 1:
            totals = [[_type_label(comp_type),
                       *_figures(records.record(conn,
                                                replace(filters, type=comp_type)))]
                      for comp_type in types]
            totals.append(["total", *_figures(overall)])
            click.echo(present.render_table(
                ["competition", *columns], totals,
                caption=click.style("Totals", fg="cyan")))
        elif not types:
            # Nothing carries a competition type: fall back to one table.
            click.echo(present.render_table(["venue", *columns],
                                            _venue_rows(filters)))

        if list_all:
            click.echo(present.render_table(
                ["date", "season", "competition", "round", "h/a",
                 "for", "against", "result", "crowd"],
                records.meetings(conn, filters)))

    @cli.command(name="runs")
    @click.option("--of", type=click.Choice(RUN_TYPES), default="unbeaten",
                  show_default=True, help="What kind of run.")
    @click.option("--top", default=5, show_default=True, help="How many to list.")
    @filter_options()
    @prepared(connect)
    def runs_command(conn, filters, of, top):
        """Longest sequences: unbeaten, wins, losses, clean sheets."""
        matches = runs.matches_in_order(conn, filters)
        _heading(filters, f"Longest runs — {of}", conn)
        found = runs.all_runs(matches, of, minimum=2)[:top]
        if not found:
            click.echo("\n" + f"No run of {of} under those filters.")
            return
        click.echo(present.render_table(
            ["length", "from", "to", "seasons"],
            [[r.length, r.start.date, r.end.date,
              r.start.season if r.start.season == r.end.season
              else f"{r.start.season} to {r.end.season}"] for r in found]))
        click.echo(click.style(
            "\nA run is broken by a defeat or by a match with no known result. "
            "Outcomes include extra time and penalties.", dim=True))

    @cli.command(name="clubs")
    @click.argument("search", required=False)
    @click.pass_context
    def clubs_command(ctx, search):
        """List the clubs, optionally filtered by name."""
        conn = connect(ctx)
        found = (club_matching.find_clubs(_candidates(conn), search) if search
                 else sorted(_candidates(conn), key=lambda c: c.name))
        if not found:
            click.echo(f"Nothing matching {search!r}.")
            return
        click.echo(present.render_table(
            ["name", "slug"], [[c.name, c.slug] for c in found]))

    @cli.command(name="seasons")
    @click.option("--cups", is_flag=True, help="Show cup runs instead.")
    @filter_options()
    @prepared(connect)
    def seasons_command(conn, filters, cups):
        """League position and outcome for each season."""
        if cups:
            _heading(filters, "Cup runs", conn)
            runs_found = season_analysis.cup_runs(conn, filters.club)
            if not runs_found:
                click.echo("\n" + "No cup runs recorded.")
                return
            click.echo(present.render_table(
                ["season", "competition", "furthest round", "outcome"],
                [list(row) for row in runs_found]))
            return

        _heading(filters, "Seasons", conn)
        rows = season_analysis.season_rows(conn, filters.club)
        if not rows:
            click.echo("\n" + "No league seasons recorded.")
            return
        table = present.render_table(
            ["season", "competition", "tier", "position", "points",
             "play-offs", "outcome"],
            [[s.season, s.competition, s.tier, s.position, s.points,
              "yes" if s.played_play_offs else "",
              display_outcome(o, s.position)]
             for s, o in rows])
        click.echo("\n".join(style_outcome(line) for line in table.splitlines()))
        click.echo(click.style(
            "\nPlay-offs are an addendum to a league season, not part of the "
            "table or that season's league record.", dim=True))

    @cli.command(name="extremes")
    @click.option("--by", type=click.Choice(MEASURES), default="margin",
                  show_default=True, help="What to rank by.")
    @click.option("--top", default=10, show_default=True, help="How many to list.")
    @filter_options()
    @prepared(connect)
    def extremes_command(conn, filters, by, top):
        """Biggest wins and defeats, highest scoring, record crowds."""
        rows, cover = ex.extremes(conn, filters, by=by, limit=top)
        _heading(filters, f"Extremes — by {by}", conn)
        if not rows:
            click.echo("\n" + "Nothing matches those filters.")
            return
        click.echo(present.render_table(
            ["date", "season", "competition", "opponent", "h/a",
             "for", "against", "crowd"], rows))
        style = {"fg": "yellow"} if cover.is_partial else {"dim": True}
        click.echo(click.style(f"\n{cover.describe()}", **style))
