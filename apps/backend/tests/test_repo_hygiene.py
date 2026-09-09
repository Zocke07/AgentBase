"""Repository-level hygiene rules from BUILD_SPEC §5 Phase 0.

Kept as tests rather than as a lint plugin because they are cheap, they are
about the repository rather than about any one language, and a reviewer can read
them in ten seconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

PRUNED_DIRECTORIES = frozenset(
    {
        ".dev",  # redirected package caches + dev runtime data (see the justfile)
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)


def _walk_tracked_files() -> list[Path]:
    """Every file in the working tree, minus build output and vendored code."""
    found: list[Path] = []
    stack = [REPO_ROOT]
    while stack:
        directory = stack.pop()
        for entry in directory.iterdir():
            if entry.is_dir():
                if entry.name not in PRUNED_DIRECTORIES:
                    stack.append(entry)
            else:
                found.append(entry)
    return found


def test_repo_root_is_the_one_we_think_it_is() -> None:
    assert (REPO_ROOT / "BUILD_SPEC.md").is_file()
    assert (REPO_ROOT / "justfile").is_file()


def test_no_shell_or_batch_scripts() -> None:
    """§5 Phase 0: `just` recipes for every dev task. No `.sh` / `.bat` files."""
    offenders = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in _walk_tracked_files()
        if path.suffix.lower() in {".sh", ".bat", ".cmd", ".ps1"}
    )

    assert offenders == [], f"dev tasks belong in the justfile, not in scripts: {offenders}"


def test_gitattributes_normalizes_line_endings() -> None:
    """§5 Phase 0: `.gitattributes` with `* text=auto eol=lf`."""
    content = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "* text=auto eol=lf" in content


@pytest.mark.parametrize(
    "relative_path",
    [
        ".gitattributes",
        ".gitignore",
        ".nvmrc",
        ".python-version",
        "CLAUDE.md",
        "justfile",
        "apps/backend/pyproject.toml",
        "apps/desktop/package.json",
    ],
)
def test_required_scaffold_file_exists(relative_path: str) -> None:
    assert (REPO_ROOT / relative_path).is_file(), f"missing {relative_path}"


def test_python_is_pinned_to_312() -> None:
    """§1 constraint 8: Python 3.12 backend."""
    pinned = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()

    assert pinned.startswith("3.12")


def test_no_api_keys_in_tracked_files() -> None:
    """§1 constraint 4: keys live in the OS keychain, never in a repo file."""
    key_prefixes = ("sk-ant-", "sk-proj-", "sk-live-", "xoxb-", "ghp_")
    suffixes = {".py", ".ts", ".tsx", ".json", ".toml", ".yml", ".yaml", ".md", ".rs"}

    offenders: list[str] = []
    for path in _walk_tracked_files():
        if path.suffix.lower() not in suffixes or path.name == "test_repo_hygiene.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(prefix in text for prefix in key_prefixes):
            offenders.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))

    assert offenders == [], f"possible API key committed in: {offenders}"


def test_generated_trees_are_pruned_not_scanned() -> None:
    """The walker must never descend into `.dev`.

    Package caches are full of vendored `.sh` files and would make
    `test_no_shell_or_batch_scripts` fail for reasons that have nothing to do
    with this repository — and walking gigabytes of cache would make the suite
    slow enough that people stop running it.
    """
    assert ".dev" in PRUNED_DIRECTORIES

    scanned = _walk_tracked_files()
    dev_dir = REPO_ROOT / ".dev"

    assert not any(dev_dir in path.parents for path in scanned)


def test_dev_directory_is_git_ignored() -> None:
    """Redirected caches and dev runtime state must never be committed."""
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".dev/" in ignored
