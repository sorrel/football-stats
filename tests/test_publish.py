"""What `tools/publish.sh` guarantees about the public mirror.

The script is the only thing standing between `data/` and a public
repository whose licences do not permit it, and it decides the name the
public history is written under. Both were untested. These run the real
script against a miniature repository and a local bare remote, so nothing
here touches the network or the real mirror.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PUBLISH = Path(__file__).resolve().parent.parent / "tools" / "publish.sh"

#: `tools/` is withheld from the public mirror, which publishes `tests/`.
#: There the script does not exist and there is nothing here to test, so
#: skip rather than fail — the mirror's suite must pass on a fresh clone.
pytestmark = pytest.mark.skipif(
    not PUBLISH.exists(),
    reason="tools/publish.sh is not published to the mirror")

#: Applied to every git process the script starts. Signing is off because a
#: test must never reach for a key, and an identity is set so the run does
#: not depend on the machine's own git config — which is the very thing the
#: authorship guarantee below is about.
GIT_ENV = {
    "GIT_CONFIG_COUNT": "3",
    "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "user.name", "GIT_CONFIG_VALUE_1": "Someone Else",
    "GIT_CONFIG_KEY_2": "user.email", "GIT_CONFIG_VALUE_2": "someone@example.com",
    "GIT_TERMINAL_PROMPT": "0",
}


def git(*args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check,
                          capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV})


def publish(private, remote, mirror, *args):
    return subprocess.run(["bash", str(PUBLISH), *args], cwd=private,
                          capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV,
                               "PUBLIC_REMOTE": str(remote),
                               "PUBLIC_DIR": str(mirror)})


@pytest.fixture
def pair(tmp_path):
    """A miniature private repository and an empty mirror to publish into."""
    private = tmp_path / "private"
    for directory in ("tools", "data", "docs", "public", "src"):
        (private / directory).mkdir(parents=True)
    shutil.copy(PUBLISH, private / "tools" / "publish.sh")
    (private / "data" / "matches.csv").write_text("match_id,date\n")
    (private / "docs" / "design.md").write_text("never published\n")
    (private / "public" / "README.md").write_text("# The public one\n")
    (private / "public" / "LICENSE").write_text("MIT\n")
    (private / "public" / "gitignore").write_text("data/\n")
    (private / "src" / "app.py").write_text("print('hello')\n")
    (private / "README.md").write_text("# The private one\n")
    (private / "CLAUDE.md").write_text("guidance\n")
    git("init", "-q", "-b", "master", cwd=private)
    git("add", "-A", cwd=private)
    git("commit", "-qm", "everything", cwd=private)

    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "-q", "-b", "main", cwd=seed)
    (seed / "README.md").write_text("# stale\n")
    git("add", "-A", cwd=seed)
    git("commit", "-qm", "first", cwd=seed)
    git("push", "-q", str(remote), "main", cwd=seed)

    return private, remote, tmp_path / "mirror"


def test_the_data_never_reaches_the_mirror(pair):
    _, _, mirror = pair
    result = publish(*pair)
    assert result.returncode == 0, result.stderr
    published = [p for p in mirror.rglob("*")
                 if p.is_file() and ".git" not in p.parts]
    assert published, "nothing was published at all"
    assert not [p for p in published if p.suffix in (".csv", ".db", ".json")]
    assert not [p for p in published if p.name == "matches.csv"]


def test_the_private_only_directories_are_withheld(pair):
    private, _, mirror = pair
    assert publish(*pair).returncode == 0
    for withheld in ("data", "docs", "public", "tools", "CLAUDE.md"):
        assert not (mirror / withheld).exists(), f"{withheld} was published"
    assert (mirror / "src" / "app.py").exists()


def test_the_public_readme_and_licence_are_laid_over_the_private_ones(pair):
    _, _, mirror = pair
    assert publish(*pair).returncode == 0
    assert (mirror / "README.md").read_text() == "# The public one\n"
    assert (mirror / "LICENSE").read_text() == "MIT\n"
    assert (mirror / ".gitignore").read_text() == "data/\n"


def test_the_history_is_written_under_the_no_reply_address(pair):
    """The machine's own git config must not decide what a public history
    says: here it is deliberately someone else's, and must not be used.
    """
    _, _, mirror = pair
    assert publish(*pair).returncode == 0
    who = git("log", "-1", "--format=%an <%ae>|%cn <%ce>", cwd=mirror).stdout.strip()
    author, committer = who.split("|")
    assert author == "Sorrel <200593+sorrel@users.noreply.github.com>"
    assert committer == "Sorrel <200593+sorrel@users.noreply.github.com>"
    assert "someone@example.com" not in who


def test_a_stray_data_file_in_the_published_tree_is_refused(pair):
    """The belt to the exclude list's braces: a CSV that slips past the
    directory exclusions must still stop the publish.
    """
    private, _, _ = pair
    (private / "src" / "leaked.csv").write_text("id\n")
    git("add", "-A", cwd=private)
    git("commit", "-qm", "oops", cwd=private)
    result = publish(*pair)
    assert result.returncode != 0
    assert "Refusing to publish" in result.stderr


def test_an_uncommitted_change_is_refused(pair):
    """What is published is what is recorded, not what is lying about."""
    private, _, _ = pair
    (private / "src" / "app.py").write_text("print('unrecorded')\n")
    result = publish(*pair)
    assert result.returncode != 0
    assert "working tree is dirty" in result.stderr


def test_a_dirty_mirror_is_refused_rather_than_overwritten(pair):
    private, remote, mirror = pair
    assert publish(*pair).returncode == 0
    (mirror / "src" / "app.py").write_text("someone was working here\n")
    result = publish(*pair)
    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr


def test_status_and_dry_run_leave_the_mirror_untouched(pair):
    private, remote, mirror = pair
    assert publish(*pair).returncode == 0
    (private / "src" / "app.py").write_text("print('changed')\n")
    git("add", "-A", cwd=private)
    git("commit", "-qm", "change", cwd=private)
    before = git("rev-parse", "HEAD", cwd=mirror).stdout
    for flag in ("--status", "--dry-run"):
        result = publish(private, remote, mirror, flag)
        assert result.returncode == 0, result.stderr
        assert "Out of step" in result.stdout
        assert git("rev-parse", "HEAD", cwd=mirror).stdout == before
        assert git("status", "--porcelain", cwd=mirror).stdout == ""


# --- The post-merge hook: publish what lands, and only that ---------------

HOOK = PUBLISH.parent / "hooks" / "post-merge"


def pull(private, remote, mirror, *args):
    """`git pull`, with the hook pointed at the miniature mirror."""
    return subprocess.run(["git", "pull", "-q", *args], cwd=private,
                          capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV,
                               "PUBLIC_REMOTE": str(remote),
                               "PUBLIC_DIR": str(mirror)})


@pytest.fixture
def landed(pair, tmp_path):
    """`pair`, with the hook enabled, an origin, and a second clone that
    lands changes on it the way a merged pull request does.
    """
    private, remote, mirror = pair
    (private / "tools" / "hooks").mkdir()
    shutil.copy(HOOK, private / "tools" / "hooks" / "post-merge")
    git("add", "-A", cwd=private)
    git("commit", "-qm", "the hook", cwd=private)
    git("config", "core.hooksPath", "tools/hooks", cwd=private)

    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "master", str(origin), cwd=tmp_path)
    git("remote", "add", "origin", str(origin), cwd=private)
    git("push", "-q", "-u", "origin", "master", cwd=private)
    elsewhere = tmp_path / "elsewhere"
    git("clone", "-q", str(origin), str(elsewhere), cwd=tmp_path)
    return private, remote, mirror, elsewhere


def land(elsewhere, text="print('landed')\n"):
    (elsewhere / "src" / "app.py").write_text(text)
    git("commit", "-qam", "a change", cwd=elsewhere)
    git("push", "-q", cwd=elsewhere)


def test_pulling_a_landed_change_publishes_it(landed):
    private, remote, mirror, elsewhere = landed
    land(elsewhere)
    result = pull(private, remote, mirror)
    assert result.returncode == 0, result.stderr
    assert (mirror / "src" / "app.py").read_text() == "print('landed')\n"
    assert not (mirror / "tools").exists()


def test_a_pull_into_another_branch_is_not_published(landed):
    private, remote, mirror, elsewhere = landed
    git("checkout", "-qb", "feature/elsewhere", cwd=private)
    land(elsewhere)
    result = pull(private, remote, mirror, "origin", "master")
    assert result.returncode == 0, result.stderr
    assert not mirror.exists()


def test_a_local_merge_not_yet_pushed_is_not_published(landed):
    """Publish what has landed on origin, never a merge only this machine
    has seen.
    """
    private, remote, mirror, _ = landed
    git("checkout", "-qb", "feature/local", cwd=private)
    (private / "src" / "app.py").write_text("print('local')\n")
    git("commit", "-qam", "local only", cwd=private)
    git("checkout", "-q", "master", cwd=private)
    result = subprocess.run(["git", "merge", "-q", "--ff-only", "feature/local"],
                            cwd=private, capture_output=True, text=True,
                            env={**os.environ, **GIT_ENV,
                                 "PUBLIC_REMOTE": str(remote),
                                 "PUBLIC_DIR": str(mirror)})
    assert result.returncode == 0, result.stderr
    assert "not level with" in result.stderr
    assert not mirror.exists()


def test_a_failed_publish_does_not_fail_the_pull(landed):
    """The pull has already happened; the hook can only warn."""
    private, remote, mirror, elsewhere = landed
    (private / "notes.txt").write_text("lying about\n")
    land(elsewhere)
    result = pull(private, remote, mirror)
    assert result.returncode == 0, result.stderr
    assert "did not publish" in result.stderr
    assert (private / "src" / "app.py").read_text() == "print('landed')\n"
    assert not (mirror / "src" / "app.py").exists()
