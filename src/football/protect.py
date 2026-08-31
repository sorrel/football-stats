"""Guards protecting the canonical CSV files.

The database can be rebuilt in seconds. The CSV files represent weeks of
paced crawling, so every write path goes through here first:

- changes are computed and can be reported before anything is written;
- a row not present in an incoming batch is left alone, never deleted;
- writing is refused unless git already holds a recoverable copy.
"""

import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


class DirtyDataError(Exception):
    """The canonical files have uncommitted changes, or git could not be asked."""


@dataclass(frozen=True)
class ChangeSet:
    added: list[dict[str, str]]
    modified: list[tuple[dict[str, str], dict[str, str]]]
    unchanged: int

    def is_empty(self) -> bool:
        return not self.added and not self.modified

    def summary(self) -> str:
        return (f"{len(self.added)} added, {len(self.modified)} modified, "
                f"{self.unchanged} unchanged")


def plan_changes(
    existing: Iterable[dict[str, str]],
    incoming: Iterable[dict[str, str]],
    key: str,
) -> ChangeSet:
    """Work out what writing `incoming` would do, without writing anything.

    Deletion is deliberately not a concept: a key absent from `incoming` is
    left untouched, so re-parsing part of the data cannot destroy the rest.
    """
    current = {row[key]: row for row in existing}
    added: list[dict[str, str]] = []
    modified: list[tuple[dict[str, str], dict[str, str]]] = []
    unchanged = 0

    for row in incoming:
        previous = current.get(row[key])
        if previous is None:
            added.append(row)
        elif previous == row:
            unchanged += 1
        else:
            modified.append((previous, row))

    return ChangeSet(added=added, modified=modified, unchanged=unchanged)


def assert_data_committed(
    repo_root: Path,
    data_dir: Path,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Refuse to write unless git already holds a recoverable copy of `data_dir`.

    A git failure is treated as unsafe rather than safe: if we cannot confirm
    the files are recoverable, we do not overwrite them.
    """
    result = run(
        ["git", "status", "--porcelain", "--", str(data_dir)],
        cwd=repo_root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise DirtyDataError(
            "could not confirm the canonical files are committed: "
            f"{result.stderr.strip()}")
    if result.stdout.strip():
        raise DirtyDataError(
            "the canonical files have uncommitted changes; commit or discard "
            f"them first so this write can be undone:\n{result.stdout.rstrip()}")
