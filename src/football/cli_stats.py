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
from .analysis import coverage as coverage_analysis
from .analysis import filters as filters_module
from .analysis import records, runs
from .analysis import seasons as season_analysis
from .analysis.extremes import MEASURES, RESULTS
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
    ("runner-up", {"fg": 252, "bold": True}),
    ("relegated", {"fg": "red", "bold": True}),
    ("left-the-league", {"fg": "bright_yellow"}),
    ("current", {"dim": True}),
    ("war", {"dim": True}),
)


def display_outcome(outcome: str, position: int | None = None,
                    tier: int | None = None) -> str:
    """How an outcome reads in the table.

    Finishing top is reported as winning the division, whatever followed:
    it is the fact a supporter would name first. Promotion remains visible
    in the tier of the season below.

    Finishing second is only worth naming in the top flight — the runners-up
    medal that actually gets remembered — so it is marked there and nowhere
    else; second in League Two is just a promotion, already covered.

    An unchanged season shows a dash — sixty rows of "stayed" is noise, and
    the eye wants the exceptions.
    """
    if position == 1:
        return "champions"
    if position == 2 and tier == 1:
        return "runner-up"
    return "-" if outcome == "stayed" else outcome


def style_outcome(line: str) -> str:
    """Colour the outcome at the end of a rendered row, if there is one."""
    for outcome, style in _OUTCOME_STYLE:
        if line.endswith(outcome):
            return line[: -len(outcome)] + click.style(outcome, **style)
    return line


#: The top four rounds, each a deeper shade of green than the last — named
#: "green" and "bright_green" are only two colours between them, not four,
#: so these reach into the 256-colour palette for steps in between rather
#: than repeating one of the two. Plus the one poor result: an exit early
#: enough to be a letdown for the level the club played at that season.
#: Anything else — the rounds in between — is not remarkable enough either
#: way to be worth marking.
_CUP_OUTCOME_STYLE = {
    "quarter-final": {"fg": 22},                  # a dark, forest green
    "semi-final": {"fg": 34},                     # a fuller green
    "final": {"fg": 40},                          # brighter still
    "winners": {"fg": 46, "bold": True},           # the brightest green there is
    "early-exit": {"fg": "red", "bold": True},
}


def style_cup_line(line: str, ending: str, category: str) -> str:
    """Colour a cup row's outcome, known exactly rather than matched by text.

    Unlike a league outcome, a cup round's colour depends on the tier the
    club played at that season as well as the word itself, so the category
    a row carries is trusted outright rather than looked up from its text.
    """
    style = _CUP_OUTCOME_STYLE.get(category)
    return line[: -len(ending)] + click.style(ending, **style) if style else line


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


#: How each run type reads in a table. The slug is what you type; these are
#: what a supporter would say, so a column of them can be read as English.
_RUN_LABELS = {
    "unbeaten": "unbeaten",
    "wins": "wins",
    "draws": "draws",
    "losses": "losses",
    "without-win": "without a win",
    "without-scoring": "without a goal",
    "clean-sheets": "clean sheets",
}

#: How each result reads in a table, in the order the sections are shown.
_RESULT_LABELS = {
    "wins": "Wins",
    "losses": "Losses",
}

_HIGH_SCORING_LABEL = "Highest scoring"

_RUNS_FOOTNOTE = (
    "\nA run is broken by a match with no known result: an unbeaten "
    "sequence through a match nobody knows the outcome of is an assumption, "
    "not a fact. Outcomes include extra time and penalties.\n"
    "Days measure a drought from the last win — or the last goal — to the "
    "next, and any other run across its own matches. A drought the record "
    "cannot see the end of is marked +, meaning at least that long."
)


def _coverage_note(conn, filters) -> str | None:
    """What the record is missing, where that changes the answer.

    The principle the rest of the tool already follows — an answer states
    its coverage — applied to sequences. A run that stopped at a gap in the
    record looks like a run that stopped at a defeat unless we say so. A war
    is not a gap in what the record holds — there was no football to hold —
    but it is still a stretch no run may safely be said to cross.
    """
    gaps = _gaps(conn, filters)
    if not gaps:
        return None
    parts = [(f"no football was played for {', '.join(stretches)}"
              if held == "war" else f"{held} for {', '.join(stretches)}")
             for held, stretches in gaps]
    return "\nThe record has gaps: " + "; ".join(parts) + ". No run crosses them."


def _gaps(conn, filters) -> list[tuple[str, list[str]]]:
    """The stretches the record does not hold, and what it holds instead.

    The war years are told apart from the rest: nothing is missing from a
    war, since nothing of the kind this asks about happened, which is a
    different fact from a source simply failing to catalogue what did.
    """
    absent = coverage_analysis.absent_seasons(conn, filters.club)
    war = coverage_analysis.war_seasons(absent)
    found = [
        ("cup football only", coverage_analysis.incomplete_seasons(
            conn, filters.club, filters.competition)),
        ("war", war),
        ("nothing at all", absent - war),
    ]
    return [(held, coverage_analysis.stretches(seasons))
            for held, seasons in found if seasons]


def _summary_cells(found: list[list[runs.Run | None]]) -> list[list[str]]:
    """Render the summary grid with each column's figures lined up.

    The figure and the season it fell in share a cell, which leaves the
    figures ragged: 6 and 22 start in the same place, so their units do not.
    A column of quantities is meant to be read down, so each is padded to the
    widest figure in its own column — which `present` cannot do for us,
    knowing only that the cell is text.
    """
    lengths = [["" if run is None else str(run.length) for run in row]
               for row in found]
    widths = [max(len(row[column]) for row in lengths)
              for column in range(len(lengths[0]))]
    return [
        [
            # An em dash, not a nought: a club that has never won three in a
            # row has no such run, which is not a run of length nil.
            "—" if run is None
            else f"{length:>{width}} ({_seasons(run)})"
            for run, length, width in zip(row, texts, widths)
        ]
        for row, texts in zip(found, lengths)
    ]


def _seasons(run: runs.Run) -> str:
    """The season a run belongs to, or the two it stretched between."""
    return (run.start.season if run.start.season == run.end.season
            else f"{run.start.season} to {run.end.season}")


def _days(run: runs.Run) -> str:
    """How long a run lasted, marked when that is only a lower bound."""
    return f"{run.days}" if run.bounded else f"{run.days}+"


def _heading(filters: Filters, title: str, conn=None) -> None:
    name = club_name(conn, filters.club) if conn is not None else filters.club
    click.echo()
    click.echo(click.style(title, fg="cyan", bold=True))
    click.echo("  " + click.style(name, fg="bright_yellow")
               + click.style(f" — {filters.describe()}", dim=True))
    if conn is not None and not is_fully_held(conn, filters.club):
        # A club held only as an opponent has just its meetings with the
        # clubs we do hold. Reported as a record it looks complete, and is
        # not — so say so before the figures rather than after.
        click.echo(click.style(
            f"  {name} has not been imported: these are only their matches "
            f"against clubs that have been.\n"
            f"  Run `football import engsoccerdata --club {filters.club}` "
            "for their full record.", fg="yellow"))


def _sides(filters: Filters, split: bool, *, neutral: bool = False,
           combined: bool = True) -> list[tuple[str, Filters]]:
    """The (label, filters) pairs a table is built across.

    An explicit --side has already answered the question, so it is reported
    on its own rather than alongside a breakdown that would repeat it. Every
    other caller wants the same partition — home, away, and optionally
    neutral, with or without a leading combined/total row of the unsplit
    filters — so this is the one place that logic lives.
    """
    if filters.side:
        return [(filters.side, filters)]
    if not split:
        return [("combined", filters)] if combined else []
    sides = [("home", replace(filters, side="home")),
             ("away", replace(filters, side="away"))]
    if neutral:
        sides.append(("neutral", replace(filters, side="neutral")))
    return [("combined", filters), *sides] if combined else sides


def register(cli, connect):
    """Add the analysis commands to `cli`. `connect` opens the database."""

    def _populated_sides(conn, filters: Filters
                          ) -> list[tuple[str, Filters, records.Record]]:
        """Each home/away/neutral split under `filters` that has matches.

        A neutral ground is its own row, never folded into away: a cup final
        at a neutral ground is not an away match, whoever is listed first.
        """
        found = []
        for label, at in _sides(filters, split=True, neutral=True, combined=False):
            result = records.record(conn, at)
            if result.played:
                found.append((label, at, result))
        return found

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

        # Home, away and neutral, then the total. A --side filter is the user
        # having already chosen; splitting would override their filter and
        # report matches they excluded, so _populated_sides reports it alone.
        lines = [_line(label, split)
                 for label, _, split in _populated_sides(conn, filters)]
        if not filters.side and len(lines) != 1:
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
            """Home, away and neutral under `these` filters."""
            rows = []
            for label, at, split in _populated_sides(conn, these):
                if not cup:
                    rows.append([label, *_figures(split)])
                    continue
                extras = records.cup_extras(conn, at)
                played, *rest, percentage = _figures(split)
                rows.append([label, extras.contests, played, *rest, extras.replays,
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
    @click.option("--of", type=click.Choice(RUN_TYPES), default=None,
                  help="Drill into one kind of run. Omit for all of them.")
    @click.option("--split/--no-split", default=True, show_default=True,
                  help="With --of, a table each for combined, home and away.")
    @click.option("--top", default=5, show_default=True, help="How many to list.")
    @filter_options()
    @prepared(connect)
    def runs_command(conn, filters, of, split, top):
        """Longest sequences: unbeaten, wins, droughts, clean sheets.

        Every kind of run at once, or one kind listed in full with --of.
        Either way the answer comes combined, at home and away.
        """
        if of is None:
            _heading(filters, "Longest runs", conn)
            _runs_summary(conn, filters)
        else:
            _heading(filters, f"Longest runs — {_RUN_LABELS[of]}", conn)
            for side, sided in _sides(filters, split):
                _runs_listing(conn, sided, of, top, side if split else None)
        note = _coverage_note(conn, filters)
        if note:
            click.echo(click.style(note, fg="yellow"))
        click.echo(click.style(_RUNS_FOOTNOTE, dim=True))

    def _runs_summary(conn, filters):
        """Every kind of run, each side by side across the venues."""
        columns = _sides(filters, split=True)
        found = [[runs.longest(runs.matches_in_order(conn, sided), of)
                  for _, sided in columns] for of in RUN_TYPES]
        rows = [[_RUN_LABELS[of], *cells]
                for of, cells in zip(RUN_TYPES, _summary_cells(found))]
        click.echo(present.render_table(
            ["run", *(label for label, _ in columns)], rows))

    def _runs_listing(conn, filters, of, top, side):
        """The longest runs of one kind, at length."""
        found = runs.all_runs(runs.matches_in_order(conn, filters),
                              of, minimum=2)[:top]
        caption = click.style(f"{_RUN_LABELS[of]} — {side}",
                              fg="cyan") if side else None
        if not found:
            # Said rather than silently skipped: a missing table reads as an
            # oversight, where "no run of wins — away" is an answer.
            click.echo("\n" + (f"No run of {_RUN_LABELS[of]}"
                               + (f" — {side}" if side else "")
                               + " under those filters."))
            return
        click.echo(present.render_table(
            ["length", "from", "to", "seasons", "days"],
            [[r.length, r.start.date, r.end.date, _seasons(r), _days(r)]
             for r in found],
            caption=caption))

    @cli.command(name="coverage")
    @filter_options()
    @click.pass_context
    def coverage_command(ctx, **kwargs):
        """Which seasons the record holds only in part, and how complete the
        figures are within the seasons it does hold.

        A club playing cup ties was in a league that season. Where we hold
        the ties and no league match at all, a whole programme is missing —
        and any answer that counts one match as following another is wrong
        across it. The war years are told apart from that: nothing is
        missing from a war, since there was no football to hold.

        Without --club, this is a question about the whole database rather
        than one club's record, so it shows every imported club's coverage
        side by side instead — the same grid as `football clubs --coverage`.
        """
        conn = connect(ctx)
        if not kwargs.get("club"):
            other = {name: value for name, value in kwargs.items()
                     if name != "club" and value not in (None, False, ())}
            if other:
                raise click.ClickException(
                    "Which club? Filters narrow one club's record; without "
                    "--club there's no record to narrow.\nPass --club <name>, "
                    "or drop the filters to see every club's coverage.")
            found = sorted(_candidates(conn), key=lambda c: c.name)
            if not found:
                click.echo("No clubs in this database yet.")
                return
            _render_coverage_grid(conn, found)
            return
        kwargs["club"] = resolve_club(conn, kwargs["club"])
        filters = build_filters(**kwargs)
        _coverage_report(conn, filters)

    def _coverage_report(conn, filters):
        _heading(filters, "Coverage", conn)
        strip = _timeline_strip(conn, filters.club)
        if strip:
            click.echo()
            click.echo(strip)
            click.echo(_timeline_legend())

        gaps = _gaps(conn, filters)
        if not gaps:
            click.echo("\n" + "Every season between the club's first match "
                       "and its last is held in full.")
        else:
            rows = sorted(([stretch, held,
                            _matches_between(conn, filters.club, stretch)]
                           for held, stretches in gaps for stretch in stretches),
                          key=lambda row: row[0])
            click.echo(present.render_table(["seasons", "held", "matches"], rows))
            if any(held != "war" for held, _ in gaps):
                click.echo(click.style(
                    "\nThe club played these seasons; the record does not "
                    "have them. No run crosses them, and no total for them "
                    "is a full total.", dim=True))
            if any(held == "war" for held, _ in gaps):
                click.echo(click.style(
                    "\nNo football was played through the war years shown: "
                    "there is nothing to hold, not something missing. "
                    "No run crosses them either.", dim=True))
            held_from = coverage_analysis.held_in_full_from(conn, filters.club)
            if held_from:
                click.echo(click.style(
                    f"\nHeld in full from {held_from} onwards "
                    "(all leagues and cups).", fg="bright_green"))

        click.echo()
        click.echo(click.style("Recorded figures", fg="cyan", bold=True))
        for label, column in (("crowd", "cm.attendance"), ("scores", "cm.goals_for")):
            league, cups = _split_coverage(conn, filters, column)
            click.echo(f"  {label:<7} league  {_bar(league)}")
            click.echo(f"  {'':<7} cups    {_bar(cups)}")
        cards_from = coverage_analysis.CARDS_FROM
        cards_filters = replace(filters,
                                extra=(*filters.extra, f"cm.season >= '{cards_from}'"))
        cards = ex.coverage(conn, cards_filters, "cm.yellows_for")
        click.echo(f"  {'cards':<7}         {_bar(cards)}")
        click.echo(click.style(
            f"\nCards: yellow and red cards were not used in English "
            f"football before {cards_from}, so their coverage is judged "
            "only from then, not against every match.", dim=True))

    #: One character per status a season in the timeline can carry, in the
    #: order `coverage.TIMELINE_STATUSES` ranks them, best to worst.
    _TIMELINE_GLYPHS = {
        "held": ("█", {"fg": "bright_green"}),
        "partial": ("▒", {"fg": "yellow"}),
        "war": ("·", {"dim": True}),
        "absent": ("×", {"fg": "red"}),
    }

    _TIMELINE_LABELS = {
        "held": "held in full", "partial": "cup football only",
        "war": "war — nothing to hold", "absent": "not held",
    }

    def _timeline_parts(conn, club) -> tuple[str, str, str, int] | None:
        """The first season, the coloured strip itself, the last season,
        and the strip's length in seasons (not its width on screen, which
        colour codes would throw off) — split apart so a caller lining
        several clubs up in columns can pad what it needs to before
        adding colour, and pad the bar itself to a common length so a
        shorter one does not pull the end season in under a longer one."""
        line = coverage_analysis.timeline(conn, club)
        if not line:
            return None
        strip = "".join(click.style(glyph, **style)
                        for glyph, style in
                        (_TIMELINE_GLYPHS[status] for _, status in line))
        return line[0][0], strip, line[-1][0], len(line)

    def _timeline_strip(conn, club) -> str | None:
        """A season-by-season strip: solid where the record is held in
        full, shaded through cup-only seasons, a dot through a war, a cross
        where a season is missing outright."""
        parts = _timeline_parts(conn, club)
        if not parts:
            return None
        first, strip, last, _ = parts
        return f"  {first} {strip} {last}"

    def _timeline_legend() -> str:
        return "  " + "   ".join(
            click.style(glyph, **style) + f" {_TIMELINE_LABELS[status]}"
            for status, (glyph, style) in _TIMELINE_GLYPHS.items())

    def _split_coverage(conn, filters, column):
        """The same coverage question, asked of the league and the cups
        apart — a crowd recorded for every league match says nothing about
        whether it was recorded for cup ties too."""
        league = replace(filters, extra=(*filters.extra, "comp.type = 'league'"))
        cups = replace(filters,
                       extra=(*filters.extra, "comp.type NOT IN ('league', 'play-off')"))
        return ex.coverage(conn, league, column), ex.coverage(conn, cups, column)

    def _bar(cov, width=16) -> str:
        """A compact bar: filled share of `width`, coloured by how complete
        it is, with the percentage and raw figures alongside."""
        if not cov.total:
            return click.style("n/a", dim=True)
        share = 100.0 * cov.available / cov.total
        filled = round(width * cov.available / cov.total)
        bar = "█" * filled + "░" * (width - filled)
        style = ({"fg": "bright_green"} if share >= 90
                 else {"fg": "yellow"} if share >= 40 else {"fg": "red"})
        return (click.style(bar, **style) + f" {share:3.0f}% "
                + click.style(f"({cov.available:,} of {cov.total:,})", dim=True))

    def _matches_between(conn, club, stretch):
        """How many matches the record does hold across a stretch."""
        first, _, last = stretch.partition(" to ")
        return conn.execute(
            "SELECT COUNT(*) FROM club_matches WHERE club = ? "
            "AND season BETWEEN ? AND ?",
            (club, first, last or first)).fetchone()[0]

    def _render_coverage_grid(conn, found):
        """Every imported club's coverage timeline, lined up on a shared
        season axis so a gap in one club's history reads straight down
        against what the others were doing at the time."""
        imported = [c for c in found if is_fully_held(conn, c.slug)]
        if not imported:
            click.echo("None of these have been imported yet. Run "
                       "`football collect --club <name>` for one.")
            return
        # That shared axis needs the earliest first season and latest last
        # season across the whole list — Crystal Palace reaches back to
        # 1872-73, decades before Arsenal's record starts — with blank
        # space either side of a club's own bar out to those edges. Blank,
        # not a glyph: a season before a club existed is not a gap in its
        # record.
        club_parts = [(club, _timeline_parts(conn, club.slug))
                      for club in imported]
        held = [parts for _, parts in club_parts if parts]
        name_width = max(present.display_width(c.name) for c in imported)
        season_width = max((present.display_width(parts[0])
                           for parts in held), default=0)
        first_year = min((int(parts[0][:4]) for parts in held), default=0)
        last_year = max((int(parts[2][:4]) for parts in held), default=0)
        click.echo()
        for club, parts in club_parts:
            name_pad = " " * (name_width - present.display_width(club.name))
            if not parts:
                click.echo(click.style(club.name, fg="bright_yellow")
                           + name_pad + "  no matches held")
                continue
            first, strip, last, _count = parts
            season_pad = " " * (season_width - present.display_width(first))
            left_pad = " " * (int(first[:4]) - first_year)
            right_pad = " " * (last_year - int(last[:4]))
            click.echo(click.style(club.name, fg="bright_yellow") + name_pad
                       + f"  {season_pad}{first} "
                         f"{left_pad}{strip}{right_pad} {last}")
        click.echo()
        click.echo(_timeline_legend())

    @cli.command(name="clubs")
    @click.argument("search", required=False)
    @click.option("--coverage", is_flag=True,
                  help="Show each imported club's season-by-season coverage "
                       "instead of listing names and slugs.")
    @click.pass_context
    def clubs_command(ctx, search, coverage):
        """List the clubs, optionally filtered by name."""
        conn = connect(ctx)
        found = (club_matching.find_clubs(_candidates(conn), search) if search
                 else sorted(_candidates(conn), key=lambda c: c.name))
        if not found:
            click.echo(f"Nothing matching {search!r}.")
            return

        if coverage:
            _render_coverage_grid(conn, found)
            return

        click.echo(present.render_table(
            ["name", "slug"], [[c.name, c.slug] for c in found]))

    def _cup_rows(conn, filters, split):
        """Every cup run, or just each season's combined figure.

        A season with only one competition has no combined row of its own to
        fall back to — it would only repeat the one entry — so its lone run
        stands in for it rather than being dropped.
        """
        found = season_analysis.cup_runs(conn, filters.club)
        if split:
            return found
        by_season: dict[str, list[tuple]] = {}
        for row in found:
            by_season.setdefault(row[0], []).append(row)
        return [next((row for row in rows if row[1] == "Combined"), rows[0])
                for rows in by_season.values()]

    @cli.command(name="seasons")
    @click.option("--cups", is_flag=True, help="Show cup runs instead.")
    @click.option("--split/--no-split", default=True, show_default=True,
                  help="With --cups, each competition as well as the combined "
                   "figure for the season.")
    @filter_options()
    @prepared(connect)
    def seasons_command(conn, filters, cups, split):
        """League position and outcome for each season."""
        if cups:
            _heading(filters, "Cup runs", conn)
            runs_found = _cup_rows(conn, filters, split)
            if not runs_found:
                click.echo("\n" + "No cup runs recorded.")
                return
            table = present.render_table(
                ["season", "competition", "outcome"],
                [[season, competition, ending]
                 for season, competition, _round, ending, _cat in runs_found])
            lines = table.splitlines()
            data = lines[-len(runs_found):]
            styled = [style_cup_line(line, ending, category)
                     for line, (*_, ending, category) in zip(data, runs_found)]
            click.echo("\n".join([*lines[: -len(runs_found)], *styled]))
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
              display_outcome(o, s.position, s.tier)]
             for s, o in rows])
        click.echo("\n".join(style_outcome(line) for line in table.splitlines()))
        click.echo(click.style(
            "\nPlay-offs are an addendum to a league season, not part of the "
            "table or that season's league record.", dim=True))

    @cli.command(name="extremes")
    @click.option("--by", type=click.Choice(MEASURES), default=None,
                  help="Rank by one measure instead: margin, defeat, goals, "
                   "scored, or attendance. Omit for wins, losses and the "
                   "highest-scoring matches together.")
    @click.option("--split/--no-split", default=True, show_default=True,
                  help="A table each for combined, home and away.")
    @click.option("--top", default=10, show_default=True, help="How many to list.")
    @filter_options()
    @prepared(connect)
    def extremes_command(conn, filters, by, split, top):
        """Biggest wins and defeats, highest-scoring matches, record crowds.

        Every result at once, or one measure ranked in full with --by.
        Either way the answer comes combined, at home and away.
        """
        if by is None:
            _heading(filters, "Extremes", conn)
            sides = _sides(filters, split)
            # Computed once per side and kept, not just shown: a 6-5 win is
            # nobody's biggest win by margin, but it is still high-scoring,
            # so the third section needs to know what the first two already
            # said before it can say what is left.
            by_result = {result: {side: ex.extremes_by_result(conn, sided, result,
                                                               limit=top)
                                  for side, sided in sides}
                        for result in RESULTS}
            for result in RESULTS:
                for side, _sided in sides:
                    rows, cover = by_result[result][side]
                    caption = (f"{_RESULT_LABELS[result]} — {side}" if split
                               else _RESULT_LABELS[result])
                    _extremes_table(rows, cover, caption)
            for side, sided in sides:
                exclude_ids = frozenset(
                    row[-1] for result in RESULTS
                    for row in by_result[result][side][0])
                rows, cover = ex.high_scoring(conn, sided, exclude_ids, limit=top)
                caption = (f"{_HIGH_SCORING_LABEL} — {side}" if split
                           else _HIGH_SCORING_LABEL)
                _extremes_table(rows, cover, caption)
        else:
            _heading(filters, f"Extremes — by {by}", conn)
            for side, sided in _sides(filters, split):
                rows, cover = ex.extremes(conn, sided, by=by, limit=top)
                _extremes_table(rows, cover, side if split else None)

    def _extremes_table(rows, cover, caption):
        """One table of matches, or a word that there are none, with its coverage.

        Each row carries a trailing match id so a later section can tell it
        was already shown here; that id is never itself a column to show.
        """
        if not rows:
            click.echo("\n" + "Nothing matches those filters."
                       + (f" — {caption}" if caption else ""))
            return
        click.echo(present.render_table(
            ["date", "season", "competition", "opponent", "h/a",
             "for", "against", "crowd"], [row[:-1] for row in rows],
            caption=click.style(caption, fg="cyan") if caption else None))
        style = {"fg": "yellow"} if cover.is_partial else {"dim": True}
        click.echo(click.style(f"\n{cover.describe()}", **style))
