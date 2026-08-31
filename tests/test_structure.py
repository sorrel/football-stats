"""Guards on the project-wide constraints.

These check properties of the tree rather than behaviour of any one module.
A failure here means a constraint from the design has been broken — fix the
offending file rather than relaxing the guard.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "football"
ALL_PY = sorted(SRC.rglob("*.py"))
MAX_LINES = 850


def _code_lines(path: Path) -> int:
    """Lines excluding blanks, comments and docstring bodies."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef
                          | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            docstring_lines.update(
                range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    count = 0
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or number in docstring_lines:
            continue
        count += 1
    return count


def test_there_is_something_to_check():
    assert ALL_PY, "no source files found; the path guard itself is broken"


@pytest.mark.parametrize("path", ALL_PY, ids=lambda p: p.name)
def test_no_source_file_exceeds_the_line_limit(path):
    lines = _code_lines(path)
    assert lines <= MAX_LINES, f"{path.name} has {lines} code lines (limit {MAX_LINES})"


@pytest.mark.parametrize("path", ALL_PY, ids=lambda p: p.name)
def test_no_dynamic_execution(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = {"eval", "exec", "compile", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in banned, f"{path.name} calls {node.func.id}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in {"pickle", "marshal"}, (
                    f"{path.name} imports {alias.name}")
        if isinstance(node, ast.ImportFrom):
            assert node.module not in {"pickle", "marshal"}, (
                f"{path.name} imports from {node.module}")


@pytest.mark.parametrize("path", ALL_PY, ids=lambda p: p.name)
def test_subprocess_is_never_given_a_shell(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            assert keyword.arg != "shell", (
                f"{path.name} passes shell= to a subprocess call")


@pytest.mark.parametrize("path", ALL_PY, ids=lambda p: p.name)
def test_no_absolute_home_directory_paths(path):
    assert "/Users/" not in path.read_text(encoding="utf-8"), (
        f"{path.name} contains an absolute home-directory path")


def test_the_source_site_is_not_named_anywhere_in_the_tree():
    """The data may be licensed; the tree does not advertise where it came from."""
    pattern = re.compile(r"\b\d{1,2}v\d{1,2}\.com\b", re.IGNORECASE)
    skip = {".git", ".venv", "build", "cache", "__pycache__", ".pytest_cache"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in skip for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert not pattern.search(text), f"{path} names the source site"


def test_only_the_page_source_may_import_a_network_library():
    """Exactly one module may reach the network; everything else uses the cache."""
    allowed = {"fetch.py"}
    network = {"requests", "httpx", "urllib3", "socket", "playwright",
               "urllib.request", "urllib.error", "http.client", "ftplib"}
    # `urllib.parse` builds and quotes URL strings and makes no request, so it
    # is not a way round the rule. Checking the full dotted name rather than
    # the top-level package keeps the guard precise instead of merely strict.
    for path in ALL_PY:
        if path.name in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name not in network, (
                    f"{path.name} imports {name}; only the page source may reach "
                    "the network")
                assert name.split(".")[0] not in {"requests", "httpx", "playwright"}, (
                    f"{path.name} imports {name}")

        # `from urllib import request` names the module as `urllib`, so the
        # dotted check above cannot see it. Only `parse` may be taken this way.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {"urllib", "http"}:
                for alias in node.names:
                    assert f"{node.module}.{alias.name}" not in network, (
                        f"{path.name} imports {node.module}.{alias.name}")


def test_the_network_guard_still_catches_a_real_import(tmp_path):
    """A guard that cannot fail is not a guard."""
    offender = tmp_path / "sneaky.py"
    offender.write_text("import urllib.request\n")
    tree = ast.parse(offender.read_text())
    imported = [alias.name for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names]
    assert "urllib.request" in imported


def test_the_from_import_form_is_caught_too():
    """`from urllib import request` names the module as `urllib`."""
    tree = ast.parse("from urllib import request\n")
    found = [f"{node.module}.{alias.name}" for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) for alias in node.names]
    assert "urllib.request" in found


def test_urllib_parse_remains_allowed():
    """It builds URL strings and makes no request."""
    tree = ast.parse("from urllib.parse import quote\n")
    modules = [node.module for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom)]
    assert modules == ["urllib.parse"]
