"""The sandbox: what a tool call may reach, decided before anyone is asked.

§6 says to write the test before the feature for the event store, the budget
ledger and the sandbox. This file is that test, and it exists before
`tools/sandbox.py` does.

**What is actually being asserted.** §5 Phase 6 requires that "path traversal
outside [the workspace root] is rejected before the approval prompt is even
shown", and its acceptance criterion is that an agent told to write outside the
root is "blocked at the sandbox layer". So the property under test is not that
a write fails — it is that the *decision* is reachable without executing
anything and without asking anyone. Every test here calls the sandbox directly,
with no tool, no agent and no approval in sight, because that is the layer the
guarantee lives at.

The escape attempts below are the ones that actually work against a naive
implementation, not a list of scary-looking strings: a `..` segment, an
absolute path, a symlink whose target is elsewhere, and — on Windows — a drive
letter and an alternate data stream. An implementation that string-matches
`".."` passes a third of them.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from agentspace.tools.sandbox import (
    Sandbox,
    SandboxViolationError,
    UrlNotAllowedError,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    root = tmp_path / "workspace"
    root.mkdir()
    return Sandbox(root)


# --- paths inside the root are allowed ------------------------------------


def test_a_plain_relative_path_resolves_inside_the_root(sandbox: Sandbox) -> None:
    resolved = sandbox.resolve_path("notes.txt")

    assert resolved == sandbox.root / "notes.txt"
    assert resolved.is_relative_to(sandbox.root)


def test_a_nested_relative_path_resolves_inside_the_root(sandbox: Sandbox) -> None:
    resolved = sandbox.resolve_path("reports/2026/q1.md")

    assert resolved.is_relative_to(sandbox.root)
    assert resolved.name == "q1.md"


def test_a_path_that_does_not_exist_yet_still_resolves(sandbox: Sandbox) -> None:
    """`write_file` names a file before it exists. Resolution cannot require it."""
    resolved = sandbox.resolve_path("brand/new/file.txt")

    assert not resolved.exists()
    assert resolved.is_relative_to(sandbox.root)


def test_interior_dot_dot_that_stays_inside_is_allowed(sandbox: Sandbox) -> None:
    """`a/../b` never leaves the root, so rejecting it would be superstition.

    This is the test that stops the implementation being a substring search for
    `".."`, which would reject a legitimate path and still miss a symlink.
    """
    resolved = sandbox.resolve_path("reports/../notes.txt")

    assert resolved == sandbox.root / "notes.txt"


def test_the_root_itself_resolves(sandbox: Sandbox) -> None:
    assert sandbox.resolve_path(".") == sandbox.root


# --- paths outside the root are rejected ----------------------------------


def test_a_dot_dot_escape_is_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxViolationError) as caught:
        sandbox.resolve_path("../escaped.txt")

    assert "outside the workspace" in str(caught.value)


def test_a_deep_dot_dot_escape_is_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxViolationError):
        sandbox.resolve_path("a/b/../../../../../../etc/passwd")


def test_an_absolute_path_outside_the_root_is_rejected(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"

    with pytest.raises(SandboxViolationError):
        sandbox.resolve_path(str(outside))


def test_an_absolute_path_inside_the_root_is_allowed(sandbox: Sandbox) -> None:
    """Absolute is not itself the offence; leaving the root is."""
    inside = sandbox.root / "fine.txt"

    assert sandbox.resolve_path(str(inside)) == inside


def test_an_empty_path_is_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxViolationError):
        sandbox.resolve_path("")


def test_a_whitespace_only_path_is_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxViolationError):
        sandbox.resolve_path("   ")


@pytest.mark.skipif(sys.platform != "win32", reason="drive-relative paths are Windows-only")
def test_a_windows_drive_path_is_rejected(sandbox: Sandbox) -> None:
    """`C:\\Windows\\System32\\config` is absolute on Windows and outside the root.

    Worth its own test because a POSIX-shaped implementation treats `C:` as an
    ordinary relative segment and happily creates a directory called `C:`.
    """
    with pytest.raises(SandboxViolationError):
        sandbox.resolve_path("C:\\Windows\\System32\\drivers\\etc\\hosts")


@pytest.mark.skipif(sys.platform != "win32", reason="alternate data streams are Windows-only")
def test_a_windows_alternate_data_stream_is_rejected(sandbox: Sandbox) -> None:
    """`notes.txt:hidden` writes a stream most tooling never shows.

    It stays inside the root, so the containment check alone does not catch it;
    it is rejected because a tool that claims to have written `notes.txt` and
    actually wrote an invisible stream is lying to the user.
    """
    with pytest.raises(SandboxViolationError):
        sandbox.resolve_path("notes.txt:hidden")


def _link_to_directory(link: Path, target: Path) -> None:
    """Make ``link`` point at ``target``, by whatever means this OS allows.

    Windows refuses `CreateSymbolicLink` to an unprivileged account unless
    Developer Mode is on, so on the project's primary platform (§1 constraint 7)
    the obvious `symlink_to` call skips — and it skips on exactly the test that
    covers the only escape a syntactic check cannot see. A *junction* needs no
    privilege, is followed by :meth:`Path.resolve` identically, and is what the
    real escape would use for that reason.

    :raises OSError: if neither mechanism is available, so the caller skips
        rather than passing vacuously.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_a_symlink_pointing_out_of_the_root_is_rejected(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    """The escape a string check cannot see.

    The path contains no `..` and is not absolute; it is inside the root by
    every syntactic measure, and it resolves elsewhere. This is why the
    implementation has to resolve before it compares.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    link = sandbox.root / "link"
    try:
        _link_to_directory(link, outside)
    except (OSError, NotImplementedError, AttributeError):  # pragma: no cover
        pytest.skip("this platform/user can create neither a symlink nor a junction")

    # The link really does reach the file — otherwise the test would pass
    # because the path was broken rather than because it was refused.
    assert (link / "secret.txt").read_text(encoding="utf-8") == "secret"

    with pytest.raises(SandboxViolationError):
        sandbox.resolve_path("link/secret.txt")


def test_the_violation_names_the_path_that_was_refused(sandbox: Sandbox) -> None:
    """§5 Phase 6 wants human-legible refusals, and this one reaches a user."""
    with pytest.raises(SandboxViolationError) as caught:
        sandbox.resolve_path("../../etc/passwd")

    message = str(caught.value)
    assert "etc/passwd" in message.replace("\\", "/")
    assert "workspace" in message


# --- the root itself -------------------------------------------------------


def test_the_root_is_resolved_once_at_construction(tmp_path: Path) -> None:
    """A root given as a relative or unresolved path must not defeat the check.

    Comparing a resolved candidate against an unresolved root is a real bug:
    on macOS `/var` is a symlink to `/private/var`, so every candidate under a
    `/var`-rooted workspace resolves to a path that is not relative to the root
    as written, and the sandbox rejects everything.
    """
    root = tmp_path / "workspace"
    root.mkdir()

    sandbox = Sandbox(root / "." / "sub" / "..")

    assert sandbox.root == root.resolve()
    assert sandbox.resolve_path("notes.txt") == root.resolve() / "notes.txt"


def test_a_relative_root_is_made_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path as _Path

    monkeypatch.chdir(tmp_path)
    (tmp_path / "ws").mkdir()

    sandbox = Sandbox(_Path("ws"))

    assert sandbox.root.is_absolute()
    assert sandbox.root == (tmp_path / "ws").resolve()


# --- urls ------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "https://example.com/path?query=1",
        "http://example.com:8080/thing",
    ],
)
def test_an_ordinary_public_url_is_allowed(sandbox: Sandbox, url: str) -> None:
    assert sandbox.check_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "data:text/plain,hello",
        "javascript:alert(1)",
    ],
)
def test_a_non_http_scheme_is_rejected(sandbox: Sandbox, url: str) -> None:
    """`http_get` fetches over HTTP. `file://` would be a filesystem read that
    never touched the path sandbox at all."""
    with pytest.raises(UrlNotAllowedError):
        sandbox.check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8787/settings",
        "http://localhost:8787/runs",
        "http://[::1]:8787/",
        "http://0.0.0.0/",
    ],
)
def test_a_loopback_url_is_rejected(sandbox: Sandbox, url: str) -> None:
    """The sidecar is on loopback, and so is Ollama.

    Without this, `http_get` is a tool that lets an agent call this
    application's own API — reading settings, starting runs, resolving its own
    approvals — from inside a run. §1 constraint 3 keeps other machines out;
    nothing else keeps the agent from reaching back in.
    """
    with pytest.raises(UrlNotAllowedError) as caught:
        sandbox.check_url(url)

    assert "loopback" in str(caught.value).lower() or "private" in str(caught.value).lower()


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/",
        "http://192.168.1.1/admin",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_a_private_or_link_local_url_is_rejected(sandbox: Sandbox, url: str) -> None:
    """169.254.169.254 is the cloud metadata endpoint, and the rest is the LAN —
    the user's router, printer and NAS. A local-first app has no business
    reaching any of it on an agent's say-so."""
    with pytest.raises(UrlNotAllowedError):
        sandbox.check_url(url)


def test_a_url_with_no_host_is_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(UrlNotAllowedError):
        sandbox.check_url("http://")


def test_a_url_that_is_not_a_url_is_rejected(sandbox: Sandbox) -> None:
    with pytest.raises(UrlNotAllowedError):
        sandbox.check_url("not a url at all")
