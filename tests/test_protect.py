import subprocess

import pytest

from football.protect import (
    DirtyDataError, assert_data_committed, commit_data, plan_changes)


def test_a_new_key_is_reported_as_added():
    changes = plan_changes([], [{"slug": "arsenal", "name": "Arsenal"}], key="slug")
    assert len(changes.added) == 1
    assert changes.modified == [] and changes.unchanged == 0


def test_an_identical_row_is_reported_as_unchanged():
    row = {"slug": "arsenal", "name": "Arsenal"}
    changes = plan_changes([row], [dict(row)], key="slug")
    assert changes.unchanged == 1
    assert changes.added == [] and changes.modified == []


def test_a_differing_row_is_reported_as_modified_with_both_versions():
    old = {"slug": "arsenal", "name": "Arsenal"}
    new = {"slug": "arsenal", "name": "Arsenal FC"}
    changes = plan_changes([old], [new], key="slug")
    assert changes.modified == [(old, new)]


def test_a_row_absent_from_the_incoming_batch_is_never_a_deletion():
    """Re-parsing a subset must not delete everything it did not see."""
    existing = [{"slug": "arsenal", "name": "Arsenal"},
                {"slug": "watford", "name": "Watford"}]
    changes = plan_changes(existing, [{"slug": "arsenal", "name": "Arsenal"}],
                           key="slug")
    assert changes.unchanged == 1
    assert changes.added == [] and changes.modified == []
    assert not hasattr(changes, "removed"), "deletion is deliberately not a concept"


def test_is_empty_is_true_only_when_nothing_would_change():
    row = {"slug": "arsenal", "name": "Arsenal"}
    assert plan_changes([row], [dict(row)], key="slug").is_empty()
    assert not plan_changes([], [row], key="slug").is_empty()


def test_summary_names_the_counts():
    changes = plan_changes([{"slug": "a", "name": "A"}],
                           [{"slug": "a", "name": "B"}, {"slug": "c", "name": "C"}],
                           key="slug")
    summary = changes.summary()
    assert "1 added" in summary and "1 modified" in summary


def test_a_clean_data_directory_passes(tmp_path):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    assert_data_committed(tmp_path, tmp_path / "data", run=fake_run)


def test_uncommitted_changes_under_data_block_the_write(tmp_path):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout=" M data/matches/1982-83.csv\n", stderr="")

    with pytest.raises(DirtyDataError, match="1982-83.csv"):
        assert_data_committed(tmp_path, tmp_path / "data", run=fake_run)


def test_a_failing_git_call_blocks_rather_than_assuming_it_is_safe(tmp_path):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 128, stdout="", stderr="not a repo")

    with pytest.raises(DirtyDataError, match="could not confirm"):
        assert_data_committed(tmp_path, tmp_path / "data", run=fake_run)


def test_git_is_never_invoked_through_a_shell(tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    assert_data_committed(tmp_path, tmp_path / "data", run=fake_run)
    assert isinstance(seen["command"], list)
    assert seen["command"][0] == "git"
    assert "shell" not in seen["kwargs"]


def _staged(*, status_after_add: str):
    """A fake `run` for a repo where `git add` always succeeds and `git
    status` reports `status_after_add` for every call after that."""
    def fake_run(command, **kwargs):
        if command[:2] == ["git", "add"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=status_after_add, stderr="")
        if command[:2] == ["git", "commit"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")
    return fake_run


def test_a_real_change_is_committed(tmp_path):
    committed = commit_data(
        tmp_path, tmp_path / "data", "Collect rochdale from alpha",
        run=_staged(status_after_add=" M data/matches/1982-83.csv\n"))
    assert committed is True


def test_nothing_staged_means_nothing_committed(tmp_path):
    """A source whose batch changed nothing must not produce an empty commit."""
    committed = commit_data(
        tmp_path, tmp_path / "data", "Collect rochdale from alpha",
        run=_staged(status_after_add=""))
    assert committed is False


def test_a_failing_add_is_reported_rather_than_silently_skipped(tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 128, stdout="", stderr="not a repo")

    with pytest.raises(DirtyDataError, match="could not stage"):
        commit_data(tmp_path, tmp_path / "data", "message", run=fake_run)


def test_a_failing_commit_is_reported(tmp_path):
    def fake_run(command, **kwargs):
        if command[:2] == ["git", "add"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=" M data/x.csv\n", stderr="")
        return subprocess.CompletedProcess(
            command, 128, stdout="", stderr="no identity configured")

    with pytest.raises(DirtyDataError, match="could not commit"):
        commit_data(tmp_path, tmp_path / "data", "message", run=fake_run)
