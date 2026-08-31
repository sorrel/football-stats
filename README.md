# Football Results

A local database of English football results, built for statistical queries.

**This repository holds the programs, not the data.** Canonical data is CSV
under `data/`, which the importers build for you from public sources; the
SQLite database under `build/` is derived from that and disposable. Both are
gitignored — see [Adding data](#adding-data) to build a database from
scratch, and [Sources and licences](#sources-and-licences) for the terms each
source sets.

## Usage

```bash
uv run football rebuild
uv run football query "SELECT club, COUNT(*) FROM club_matches GROUP BY club"
uv run football tables
```

`query` is read-only twice over: the statement must begin with `SELECT` or
`WITH`, and the connection is opened in SQLite's read-only mode.

## Running it

From the project directory:

```bash
uv run football record --club brighton
```

To run it from anywhere, install it once and point it at the data:

```bash
uv tool install --editable .        # puts `football` on your PATH
export FOOTBALL_DATA_DIR=/path/to/football-stats/data
export FOOTBALL_DB=/path/to/football-stats/build/football.db
export FOOTBALL_CLUB=brighton-hove-albion
```

With those set, `football record` works from any directory. Put the exports
in `~/.zshrc` to keep them. `uv tool uninstall football-results` undoes the
install (the package is named `football-results`; the command is `football`).

## Asking questions

Five questions, one shared filter vocabulary — so "the biggest win, in the FA
Cup, away, in the 1980s" is a question plus four filters, not a command of its
own.

```bash
football clubs albion                    # find a club by name
football record --club brighton --tier 1 # top-flight record, all eras
football h2h palace --club brighton      # split home, away and neutral
football runs                            # every longest run, home and away
football runs --of without-win --top 5   # the longest droughts, listed
football extremes --by attendance        # record crowds
football seasons                         # position and outcome per season
football seasons --cups                  # how far each cup run went
football coverage                        # seasons the record holds in part
```

`--club` is **required** — there is no default, because with more than one
club loaded a default would answer a question about one club with another's
record. Set `FOOTBALL_CLUB` to avoid typing it. Club names are matched
loosely: `brighton` works, and `albion` offers a numbered choice.

Filters: `--competition` `--tier` `--type` `--opponent` `--venue` `--side`
`--season-from` `--season-to` `--day` `--english-league-only`.

Two conventions worth knowing:

- **Runs use the final outcome**, including extra time and penalties: a tie
  lost on penalties ends an unbeaten run. Aggregate records use the
  90-minute result, as league tables always have. `runs` on its own answers
  every run question at once — unbeaten, wins, draws, losses, the droughts
  without a win and without a goal, and clean sheets — and `--of` lists one
  of them in full. Either way the answer comes combined, at home and away;
  `--no-split` collapses the listing back to one table. A drought is measured in matches and in days from the
  last win to the next; one the record cannot see the end of is marked `+`,
  meaning at least that long.
- **Play-offs are an addendum to a league season**, not part of the table or
  that season's league record. They carry a tier, so a tier filter includes
  them — and any command whose result mixes the two says so.
- **A run does not cross a gap in the record.** Two kinds of gap: a season
  holding cup ties and no league programme (Brighton before 1920-21), and a
  season holding nothing at all (Barrow's non-League decades, and both wars).
  The club played those seasons; the record has not imported them, so matches
  either side of one are not consecutive and no run joins them. `football
  coverage` names the gaps and `runs` says when its answer stopped at one.
  What this cannot see is a season imported in part.
- **Answers state their coverage.** `extremes --by attendance` reports that it
  rests on 41 of 4,749 matches, because a record crowd drawn silently from
  0.9% of the data would be misleading.

## Storage

| Path | Holds |
|---|---|
| `data/matches/<season>.csv` | Matches, one file per season |
| `data/clubs.csv` | Clubs, with an `english_league` flag |
| `data/competitions.csv` | Competitions, with a `tier` for leagues |
| `data/venues.csv` | Grounds |
| `build/football.db` | Derived, gitignored, rebuilt in seconds |
| `cache/` | Raw source pages, gitignored |

Each match is stored **once**, from the home side's perspective, under a
deterministic `match_id`. Adding a second club therefore cannot duplicate a
match the two clubs shared. Query the `club_matches` view to see both
perspectives, with `opponent`, `goals_for`, `goals_against`, `result` and
`day_of_week` worked out for you.

## Adding a field

Because raw pages are cached locally, adding a field never means crawling
again:

1. Add one `Field(...)` line to the relevant table in `src/football/schema.py`.
2. Teach the parser to populate it (`src/football/parse/`).
3. Re-parse from the cached pages.
4. `uv run football rebuild`.

Files written before the field existed read as empty, so nothing needs
migrating. `tests/test_extensibility.py` guards this workflow.

## Conventions

- `ht_*`, `ft_*` and `aet_*` are the score **at that point in the match**, not
  goals scored within the period. Subtract to get goals in a period.
- `pens_*` is a standalone shootout tally and is never cumulative — shootout
  penalties are not goals.
- Empty means unknown, which is not the same as zero.
- `result` is decided after 90 minutes; `final_result` accounts for extra time
  and penalties.
- British English throughout.

## Adding data

```bash
football sources                          # what exists, what it covers, licences
football fetch engsoccerdata              # download its pages, slowly, resumable
football import engsoccerdata --dry-run    # report what would change
football import engsoccerdata             # apply it
football rebuild
```

Fetching and importing are separate on purpose: fetching is slow and paced,
importing is instant and repeatable. A schema change is re-imported from the
cache without asking any host for anything.

Three properties make re-running safe:

- **An empty value means "this source does not carry that field"**, never
  "the value is nothing" — so re-importing one source cannot blank another's
  work. Re-importing an unchanged source is a no-op across every table.
- **Nothing is deleted.** A row a source did not mention is left alone.
- **`--dry-run` reports the change set** before anything is written.

Provenance accumulates in each row's `source`, so a match enriched by three
sources says so.

## Sources and licences

| Source | Covers | Licence |
|---|---|---|
| engsoccerdata | League, FA Cup, League Cup, play-offs | Free, non-commercial |
| football-data.co.uk | Half-time scores and cards, 1993 on | Free |
| openfootball | Cups 2018-19 on, Europe | CC0 (public domain) |
| Fjelstul English Football Database | Final league positions to 2023-24 | **CC-BY-SA 4.0** |
| Wikipedia | League tables from 2024-25; attendances | **CC-BY-SA 4.0** |

The programs here are MIT-licensed (see `LICENSE`). **That covers the code
alone.** Data you fetch with them stays under the terms of whoever published
it, and those terms differ: CC-BY-SA requires attribution and share-alike on
redistribution, engsoccerdata is free for non-commercial use, and
football-data.co.uk is free for personal use while restricting onward
redistribution.

Those obligations do not compose, which is why no data is published here.
Fetch your own, and check each source's terms before republishing anything
you build from them.

## Development

```bash
uv run pytest
```

No test touches the network. `tests/test_structure.py` enforces the
project-wide constraints: no source file over 850 code lines, no dynamic
execution, no `shell=True`, no absolute home-directory paths, and no network
imports outside the single page-source module.
