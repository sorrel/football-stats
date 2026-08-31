"""Applying an import batch."""

import pytest

from football import schema, store
from football.parse.base import blank_row
from football.sources.batch import Batch, apply, plan


def _club(slug="arsenal"):
    return {"slug": slug, "name": slug.title(), "former_names": "",
            "english_league": "true", "country": "England"}


def _match(match_id="m1", **overrides):
    row = blank_row(schema.MATCHES)
    row.update({"match_id": match_id, "date": "1983-04-02", "season": "1982-83",
                "home_club": "brighton-hove-albion", "away_club": "arsenal",
                "competition": "division-one", "status": "played",
                "source": "test"})
    row.update(overrides)
    return row


def test_an_empty_batch_changes_nothing(tmp_path):
    report = plan(tmp_path, Batch())
    assert report.total_writes == 0
    assert report.summary() == "nothing to change"


def test_planning_writes_nothing(tmp_path):
    plan(tmp_path, Batch(clubs=[_club()]))
    assert store.read_table(tmp_path, schema.CLUBS) == []


def test_planning_counts_what_would_be_added(tmp_path):
    report = plan(tmp_path, Batch(clubs=[_club()], matches=[_match()]))
    counts = {c.table: c.added for c in report.changes}
    assert counts == {"clubs": 1, "matches": 1}


def test_applying_writes_the_rows(tmp_path):
    apply(tmp_path, Batch(clubs=[_club()], matches=[_match()]), force=True)
    assert len(store.read_table(tmp_path, schema.CLUBS)) == 1
    assert len(store.read_matches(tmp_path)) == 1


def test_a_second_apply_reports_no_change(tmp_path):
    batch = Batch(clubs=[_club()], matches=[_match()])
    apply(tmp_path, batch, force=True)
    report = plan(tmp_path, batch)
    assert report.total_writes == 0


def test_a_changed_row_is_counted_as_modified_not_added(tmp_path):
    apply(tmp_path, Batch(matches=[_match(ft_home="1")]), force=True)
    report = plan(tmp_path, Batch(matches=[_match(ft_home="2")]))
    change = report.changes[0]
    assert (change.added, change.modified) == (0, 1)


def test_references_are_written_before_the_rows_that_use_them(tmp_path):
    """A match naming a club we do not yet hold would fail the rebuild."""
    from football import db
    store.write_table(tmp_path, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(tmp_path, schema.VENUES, [])
    apply(tmp_path, Batch(
        clubs=[_club("brighton-hove-albion"), _club("arsenal")],
        matches=[_match()]), force=True)
    conn = db.build(tmp_path, tmp_path / "f.db")
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


def test_notes_are_carried_into_the_report(tmp_path):
    report = plan(tmp_path, Batch(notes=["could not place 1899-00"]))
    assert report.notes == ["could not place 1899-00"]


def test_nothing_is_ever_deleted(tmp_path):
    apply(tmp_path, Batch(matches=[_match("keep")]), force=True)
    apply(tmp_path, Batch(matches=[_match("also")]), force=True)
    assert len(store.read_matches(tmp_path)) == 2


def test_a_source_never_blanks_what_another_supplied():
    """Re-importing one source must not wipe another's enrichment."""
    from football.sources.batch import merge_row
    held = _match(attendance="4998", kickoff="15:00", source="engsoccerdata+wikipedia")
    fresh = _match(attendance="", kickoff="", source="engsoccerdata")
    merged = merge_row(held, fresh)
    assert merged["attendance"] == "4998"
    assert merged["kickoff"] == "15:00"


def test_a_real_correction_still_applies():
    from football.sources.batch import merge_row
    merged = merge_row(_match(ft_home="1"), _match(ft_home="2"))
    assert merged["ft_home"] == "2"


def test_provenance_accumulates_rather_than_being_replaced():
    from football.sources.batch import merge_row
    merged = merge_row(_match(source="engsoccerdata"),
                       _match(attendance="100", source="wikipedia"))
    assert merged["source"] == "engsoccerdata+wikipedia"


def test_a_source_already_credited_is_not_repeated():
    from football.sources.batch import merge_row
    merged = merge_row(_match(source="engsoccerdata+wikipedia"),
                       _match(source="wikipedia"))
    assert merged["source"] == "engsoccerdata+wikipedia"


def test_reimporting_an_unchanged_source_is_a_no_op(tmp_path):
    """The strongest check that a pipeline is reproducible."""
    batch = Batch(matches=[_match(attendance="500", source="a")])
    apply(tmp_path, batch, force=True)
    # Another source enriches it.
    apply(tmp_path, Batch(matches=[_match(kickoff="15:00", source="b")]),
          force=True)
    # Re-running the first must change nothing.
    report = plan(tmp_path, batch)
    assert report.total_writes == 0


def test_a_compound_source_tag_is_merged_part_by_part():
    """Appending the whole tag gives "engsoccerdata+engsoccerdata+..."."""
    from football.sources.batch import merge_row
    merged = merge_row(_match(source="engsoccerdata"),
                       _match(source="engsoccerdata+football-data"))
    assert merged["source"] == "engsoccerdata+football-data"


def test_merging_three_sources_lists_each_once():
    from football.sources.batch import merge_row
    row = merge_row(_match(source="a+b"), _match(source="b+c"))
    assert row["source"] == "a+b+c"


def test_writing_is_refused_when_the_data_is_not_committed(tmp_path, monkeypatch):
    """A bad import must always be one `git checkout` from undone."""
    import subprocess

    from football import protect
    from football.sources import batch as batch_module

    def dirty(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=" M data/x.csv\n",
                                           stderr="")

    # Captured first: patching the attribute would otherwise make `refuse`
    # call itself, since batch_module.protect is the protect module.
    original = protect.assert_data_committed

    def refuse(root, data, run=None):
        return original(root, data, run=dirty)

    monkeypatch.setattr(batch_module.protect, "assert_data_committed", refuse)

    with pytest.raises(protect.DirtyDataError, match="uncommitted"):
        apply(tmp_path, Batch(clubs=[_club()]))


def test_force_writes_anyway(tmp_path):
    """The escape hatch exists, but must be asked for."""
    apply(tmp_path, Batch(clubs=[_club()]), force=True)
    assert len(store.read_table(tmp_path, schema.CLUBS)) == 1


def test_competition_spans_are_recomputed_from_every_match(tmp_path):
    """A builder sees one club from one source; only the store knows the span."""
    apply(tmp_path, Batch(
        competitions=[{"slug": "fa-cup", "name": "FA Cup", "type": "fa-cup",
                       "tier": "", "first_season": "", "last_season": ""}],
        matches=[_match("a", season="1905-06", competition="fa-cup"),
                 _match("b", season="2024-25", competition="fa-cup")]),
        force=True)
    stored = {row["slug"]: row
              for row in store.read_table(tmp_path, schema.COMPETITIONS)}
    assert stored["fa-cup"]["first_season"] == "1905-06"
    assert stored["fa-cup"]["last_season"] == "2024-25"


def test_the_subject_club_is_marked_as_fully_held(tmp_path):
    """Otherwise a club held only as an opponent reports a complete-looking
    record of its handful of meetings."""
    apply(tmp_path, Batch(clubs=[_club("arsenal"), _club("accrington")],
                          matches=[_match()], subject="arsenal"), force=True)
    held = {row["slug"]: row.get("imported")
            for row in store.read_table(tmp_path, schema.CLUBS)}
    assert held["arsenal"] == "true"
    assert held["accrington"] != "true"


def test_an_import_with_no_subject_marks_nothing(tmp_path):
    apply(tmp_path, Batch(clubs=[_club("arsenal")]), force=True)
    row = store.read_table(tmp_path, schema.CLUBS)[0]
    assert row.get("imported") != "true"


def test_a_batch_that_imported_nothing_does_not_mark_the_club(tmp_path):
    """A failed identification returns an empty batch; marking it would
    switch off the warning that says the club is only an opponent."""
    apply(tmp_path, Batch(clubs=[_club("barrow")],
                          notes=["could not identify this club"],
                          subject="barrow"), force=True)
    row = next(r for r in store.read_table(tmp_path, schema.CLUBS)
               if r["slug"] == "barrow")
    assert row.get("imported") != "true"


def test_a_dry_run_mentions_the_club_it_would_mark(tmp_path):
    """Otherwise a dry run describes less than the apply does."""
    apply(tmp_path, Batch(clubs=[_club("arsenal")]), force=True)
    report = plan(tmp_path, Batch(matches=[_match()], subject="arsenal"))
    assert any("marked as fully held" in note for note in report.notes)
