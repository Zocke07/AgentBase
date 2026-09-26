"""The built-in tools: what each one does, and what each one refuses.

The difference between the two failures matters: `ToolArgumentError` is a
malformed call the agent can retry (`tool.error`), `ToolExecutionError` a
correct call that did not work. Neither is a refusal; a tool that raised
`ToolArgumentError` for an out-of-bounds path would downgrade a `tool.denied`
into a `tool.error`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import TYPE_CHECKING

import httpx2
import pytest

from agentbase.tools.base import ToolArgumentError, ToolExecutionError
from agentbase.tools.builtin import build_registry
from agentbase.tools.builtin.filesystem import (
    MAX_READ_CHARS,
    MAX_WRITE_CHARS,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from agentbase.tools.builtin.knowledge import SearchKnowledgeTool
from agentbase.tools.builtin.memory import ProposeMemoryTool
from agentbase.tools.builtin.network import MAX_FEED_ENTRIES, HttpGetTool, ReadFeedTool
from agentbase.tools.builtin.shell import RunShellTool
from agentbase.tools.catalogue import CATALOGUE, RiskLevel
from agentbase.tools.sandbox import Sandbox, SandboxViolationError, UrlNotAllowedError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

pytestmark = pytest.mark.anyio


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    return Sandbox(root)


# --- the registry -------------------------------------------------------------


def test_the_registry_and_the_catalogue_name_the_same_tools() -> None:
    """Drift here is invisible without a test, because each half is consistent.

    A catalogue entry with no implementation is a tool the Phase 7 editor
    offers, a definition can allow, and a run then refuses. An implementation
    with no entry is worse in a quieter way: `allowed_tools` validates against
    the catalogue, so no definition could ever name it: unreachable code
    wearing the shape of a feature.
    """
    registry = build_registry()

    assert set(registry) == {declaration.name for declaration in CATALOGUE}


def test_no_tool_declares_its_own_risk() -> None:
    """Risk is read from the catalogue, so the editor and the gate agree.

    §5 Phase 7 requires the tool checkboxes to show "each tool's risk level
    next to it, so the consequence of ticking `run_shell` is visible at the
    moment of ticking it". If a tool restated its risk, that label could differ
    from the level the gate actually enforces, and the checkbox would be
    telling the user something untrue at the moment they decide.
    """
    registry = build_registry()

    for declaration in CATALOGUE:
        assert registry[declaration.name].risk is declaration.risk


def test_every_tool_has_a_usable_schema() -> None:
    """A model is told what arguments a tool takes, not left to guess.

    Phase 5 offered `additionalProperties: True` for every tool because the
    shapes belonged to this phase. They exist now, so an empty or open schema
    would be a tool that had not actually been implemented.
    """
    for tool in build_registry().values():
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert schema["properties"], tool.name
        for spec in schema["properties"].values():
            assert spec["description"], tool.name


# --- read_file ----------------------------------------------------------------


async def test_read_file_returns_the_contents(sandbox: Sandbox) -> None:
    (sandbox.root / "notes.txt").write_text("hello there", encoding="utf-8")
    tool = ReadFileTool()

    prepared = tool.prepare({"path": "notes.txt"}, sandbox)

    assert await tool.execute(prepared, sandbox) == "hello there"
    assert prepared.summary == "read the file notes.txt"


async def test_read_file_refuses_a_path_outside_the_workspace(sandbox: Sandbox) -> None:
    """A refusal, not a bad argument: the distinction the event log turns on."""
    tool = ReadFileTool()

    with pytest.raises(SandboxViolationError):
        tool.prepare({"path": "../outside.txt"}, sandbox)


async def test_read_file_without_a_path_is_a_bad_call(sandbox: Sandbox) -> None:
    tool = ReadFileTool()

    with pytest.raises(ToolArgumentError) as caught:
        tool.prepare({}, sandbox)

    assert "'path'" in str(caught.value)


async def test_reading_a_file_that_is_not_there_is_an_execution_failure(
    sandbox: Sandbox,
) -> None:
    """Not a crash and not a denial: the agent is told and carries on."""
    tool = ReadFileTool()
    prepared = tool.prepare({"path": "missing.txt"}, sandbox)

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(prepared, sandbox)

    assert "no file at missing.txt" in str(caught.value)


async def test_reading_a_directory_points_at_list_dir(sandbox: Sandbox) -> None:
    (sandbox.root / "reports").mkdir()
    tool = ReadFileTool()
    prepared = tool.prepare({"path": "reports"}, sandbox)

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(prepared, sandbox)

    assert "list_dir" in str(caught.value)


async def test_a_long_file_is_truncated_and_says_so(sandbox: Sandbox) -> None:
    """Silently returning a prefix is worse than the size.

    A model that believes it read a whole file reasons about the part it never
    saw, so the cap is stated in the result text where the model reads it.
    """
    (sandbox.root / "big.txt").write_text("x" * (MAX_READ_CHARS + 500), encoding="utf-8")
    tool = ReadFileTool()

    result = await tool.execute(tool.prepare({"path": "big.txt"}, sandbox), sandbox)

    assert "[truncated:" in result
    assert str(MAX_READ_CHARS) in result


async def test_search_knowledge_returns_cited_markdown_chunks(sandbox: Sandbox) -> None:
    (sandbox.root / "decision.md").write_text(
        "# Storage\n\nUse SQLite WAL for the local event log.", encoding="utf-8"
    )
    tool = SearchKnowledgeTool()

    result = await tool.execute(tool.prepare({"query": "database event log"}, sandbox), sandbox)

    assert "[[decision#Storage]]" in result
    assert "SQLite WAL" in result


async def test_propose_memory_creates_an_untrusted_inbox_note(sandbox: Sandbox) -> None:
    tool = ProposeMemoryTool()
    prepared = tool.prepare(
        {
            "title": "Storage choice",
            "content": "SQLite WAL worked for this workload.",
            "confidence": "high",
            "tags": ["database"],
            "citations": ["[[decision#Storage]]", "[[decision#Storage]]"],
        },
        sandbox,
    )

    result = await tool.execute(prepared, sandbox)
    notes = list((sandbox.root / "memory" / "inbox").glob("*.md"))
    written = notes[0].read_text(encoding="utf-8")

    assert tool.risk is RiskLevel.MEDIUM
    assert len(notes) == 1
    assert "status: proposed" in written
    assert written.count("- [[decision#Storage]]") == 1
    assert "## Sources" in written
    assert "Proposed memory [[memory/inbox/" in result
    with pytest.raises(ToolArgumentError):
        tool.prepare(
            {"title": "x", "content": "y", "confidence": "high", "citations": [""]}, sandbox
        )


# --- write_file ---------------------------------------------------------------


async def test_write_file_creates_the_file(sandbox: Sandbox) -> None:
    tool = WriteFileTool()
    prepared = tool.prepare({"path": "out.txt", "content": "written"}, sandbox)

    result = await tool.execute(prepared, sandbox)

    assert (sandbox.root / "out.txt").read_text(encoding="utf-8") == "written"
    assert "out.txt" in result


async def test_write_file_creates_missing_parent_directories(sandbox: Sandbox) -> None:
    tool = WriteFileTool()
    prepared = tool.prepare({"path": "a/b/c.txt", "content": "deep"}, sandbox)

    await tool.execute(prepared, sandbox)

    assert (sandbox.root / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "deep"


async def test_write_file_does_not_translate_newlines(sandbox: Sandbox) -> None:
    """`Path.write_text` turns `\\n` into `\\r\\n` on Windows.

    This project has already had six source files silently converted that way
    (CLAUDE.md, Phase 4). A tool doing it to a user's file is the same bug with
    a wider blast radius: an agent writing YAML, a diff, or a shell script
    would produce something subtly broken.
    """
    tool = WriteFileTool()
    prepared = tool.prepare({"path": "unix.txt", "content": "one\ntwo\n"}, sandbox)

    await tool.execute(prepared, sandbox)

    assert (sandbox.root / "unix.txt").read_bytes() == b"one\ntwo\n"


async def test_write_file_refuses_to_escape_the_workspace(sandbox: Sandbox) -> None:
    """§5 Phase 6's acceptance criterion at the unit level."""
    tool = WriteFileTool()

    with pytest.raises(SandboxViolationError):
        tool.prepare({"path": "../escaped.txt", "content": "x"}, sandbox)

    assert not (sandbox.root.parent / "escaped.txt").exists()


async def test_write_file_refuses_an_oversized_write(sandbox: Sandbox) -> None:
    tool = WriteFileTool()

    with pytest.raises(ToolArgumentError):
        tool.prepare({"path": "big.txt", "content": "x" * (MAX_WRITE_CHARS + 1)}, sandbox)


async def test_write_file_needs_content(sandbox: Sandbox) -> None:
    tool = WriteFileTool()

    with pytest.raises(ToolArgumentError) as caught:
        tool.prepare({"path": "out.txt"}, sandbox)

    assert "'content'" in str(caught.value)


# --- list_dir -----------------------------------------------------------------


async def test_list_dir_lists_files_and_directories(sandbox: Sandbox) -> None:
    (sandbox.root / "a.txt").write_text("aa", encoding="utf-8")
    (sandbox.root / "sub").mkdir()
    tool = ListDirTool()

    result = await tool.execute(tool.prepare({}, sandbox), sandbox)

    assert "a.txt (2 bytes)" in result
    assert "sub/" in result


async def test_list_dir_defaults_to_the_workspace_root(sandbox: Sandbox) -> None:
    """The obvious first call an agent makes. Requiring '.' would waste a step."""
    tool = ListDirTool()

    prepared = tool.prepare({}, sandbox)

    assert prepared.summary == "list the contents of the workspace root"


async def test_list_dir_on_an_empty_directory_says_so(sandbox: Sandbox) -> None:
    """An empty string would read to a model as a failed call."""
    tool = ListDirTool()

    result = await tool.execute(tool.prepare({"path": "."}, sandbox), sandbox)

    assert "empty" in result


async def test_list_dir_on_a_file_points_at_read_file(sandbox: Sandbox) -> None:
    (sandbox.root / "a.txt").write_text("aa", encoding="utf-8")
    tool = ListDirTool()

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(tool.prepare({"path": "a.txt"}, sandbox), sandbox)

    assert "read_file" in str(caught.value)


# --- http_get -----------------------------------------------------------------


def _resolves_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    """Make every name resolve to ``addresses``, in that order."""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0))
            for a in addresses
        ],
    )


async def test_http_get_returns_the_body(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="the page")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = HttpGetTool(client)

    prepared = tool.prepare({"url": "https://example.com/page"}, sandbox)
    assert await tool.execute(prepared, sandbox) == "the page"

    await client.aclose()


async def test_http_get_connects_to_the_address_it_checked(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DNS rebinding: a name that answers public when checked and private when
    connected. The check and the connection used to be two resolutions, and
    the module docstring conceded the gap. Now the connection goes to the
    address the check saw: the URL carries the address, the `Host` header
    and the SNI carry the name, so a second answer is never asked for.

    The second resolver here answers private; it must never be consulted.
    """
    import socket

    _resolves_to(monkeypatch, "93.184.216.34")
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text="pinned")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = HttpGetTool(client)

    prepared = tool.prepare({"url": "https://example.com:8443/page?q=1"}, sandbox)

    # The rebinding: by the time the request is made, the name points inside.
    # A resolver consulted now is the failure, so it does not merely answer
    # differently: it raises.
    def rebound(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the name was resolved a second time")

    monkeypatch.setattr(socket, "getaddrinfo", rebound)

    assert await tool.execute(prepared, sandbox) == "pinned"
    await client.aclose()

    (request,) = seen
    assert request.url.host == "93.184.216.34"
    assert request.url.port == 8443
    assert request.url.path == "/page"
    assert request.url.query == b"q=1"
    assert request.headers["host"] == "example.com:8443"
    assert request.extensions["sni_hostname"] == "example.com"


async def test_http_get_pins_an_ipv6_address_in_brackets(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "2606:2800:220:1:248:1893:25c8:1946")
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text="six")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = HttpGetTool(client)

    prepared = tool.prepare({"url": "http://example.com/six"}, sandbox)
    assert await tool.execute(prepared, sandbox) == "six"
    await client.aclose()

    (request,) = seen
    assert str(request.url) == "http://[2606:2800:220:1:248:1893:25c8:1946]/six"
    assert request.headers["host"] == "example.com"
    # Plain HTTP has no TLS handshake to name the server in.
    assert "sni_hostname" not in request.extensions


async def test_http_get_leaves_a_literal_address_alone(sandbox: Sandbox) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text="literal")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = HttpGetTool(client)

    prepared = tool.prepare({"url": "https://93.184.216.34/x"}, sandbox)
    assert await tool.execute(prepared, sandbox) == "literal"
    await client.aclose()

    (request,) = seen
    assert str(request.url) == "https://93.184.216.34/x"
    assert request.headers["host"] == "93.184.216.34"


async def test_http_get_refuses_loopback_before_any_request(sandbox: Sandbox) -> None:
    """The tool that would otherwise let an agent call this app's own API.

    §1 constraint 3 stops other *machines* reaching the sidecar. It does
    nothing about an agent inside a run fetching `127.0.0.1:8787/settings`, and
    this is what does.
    """
    called = False

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001  # pragma: no cover
        nonlocal called
        called = True
        return httpx2.Response(200, text="secrets")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = HttpGetTool(client)

    with pytest.raises(UrlNotAllowedError):
        tool.prepare({"url": "http://127.0.0.1:8787/settings"}, sandbox)

    assert called is False
    await client.aclose()


async def test_http_get_does_not_follow_redirects(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A redirect is how a checked public URL becomes an unchecked private one.

    The sandbox validated the address the agent named; a `Location` header
    names one nothing validated. Handing the target back makes the agent ask
    for it explicitly, which puts it through `check_url` and the gate again.
    """

    _resolves_to(monkeypatch, "93.184.216.34")

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(302, headers={"location": "http://169.254.169.254/"})

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = HttpGetTool(client)

    result = await tool.execute(tool.prepare({"url": "https://example.com"}, sandbox), sandbox)

    assert "redirected to" in result
    assert "169.254.169.254" in result
    assert "not followed" in result

    await client.aclose()


async def test_http_get_reports_an_error_status(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")

    def handler(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(404, text="nope")

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = HttpGetTool(client)

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(tool.prepare({"url": "https://example.com"}, sandbox), sandbox)

    assert "404" in str(caught.value)
    await client.aclose()


# --- read_feed ---------------------------------------------------------------


async def test_read_feed_returns_complete_bounded_deterministic_entries(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")
    seen: list[httpx2.Request] = []
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Market news</title>
<item><title>Apple launches a product - Reuters</title>
<link>https://news.google.com/articles/newer</link>
<pubDate>Sat, 26 Sep 2026 05:00:00 GMT</pubDate>
<source url="https://www.reuters.com/">Reuters</source>
<description><![CDATA[<b>Newer</b> summary<script>ignore me</script>]]></description></item>
<item><title>Apple launches a product - Associated Press</title>
<link>https://news.google.com/articles/earlier</link>
<pubDate>Sat, 26 Sep 2026 03:00:00 GMT</pubDate>
<source url="https://apnews.com/">Associated Press</source>
<description><![CDATA[<p>Earlier safe summary</p>]]></description></item>
<item><title>Apple names a new executive</title>
<link>https://example.com/executive</link>
<pubDate>Sat, 26 Sep 2026 04:00:00 GMT</pubDate>
<description>Leadership changed.</description></item>
</channel></rss>"""

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, text=rss, headers={"content-type": "application/rss+xml"})

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    tool = ReadFeedTool(client)
    result = json.loads(
        await tool.execute(
            tool.prepare({"url": "https://example.com/feed", "limit": 1}, sandbox),
            sandbox,
        )
    )
    await client.aclose()

    assert result["feed_title"] == "Market news"
    assert result["available_entries"] == 3
    assert result["valid_entries"] == 3
    assert result["deduplicated_entries"] == 2
    assert result["returned_entries"] == 1
    assert result["truncated"] is True
    (entry,) = result["entries"]
    assert entry["url"] == "https://news.google.com/articles/earlier"
    assert entry["published"] == "2026-09-26T03:00:00Z"
    assert entry["source"] == "apnews.com"
    assert entry["summary"] == "Earlier safe summary"
    expected = hashlib.sha1(
        f"{entry['url']}{entry['title']}".encode(), usedforsecurity=False
    ).hexdigest()
    assert entry["id"] == expected
    assert len(entry["dedupe_key"]) == 40

    (request,) = seen
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"


async def test_read_feed_understands_atom(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")
    atom = """<feed xmlns="http://www.w3.org/2005/Atom">
<title>Company feed</title><entry><title>Quarterly filing</title>
<link rel="alternate" href="/report"/>
<published>2026-09-26T01:02:03+02:00</published>
<summary type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Filed
<script>ignore me</script>&amp; accepted.</div></summary></entry></feed>"""

    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, text=atom))
    )
    tool = ReadFeedTool(client)
    result = json.loads(
        await tool.execute(tool.prepare({"url": "https://example.com/atom"}, sandbox), sandbox)
    )
    await client.aclose()

    assert result["returned_entries"] == 1
    assert result["entries"][0]["published"] == "2026-09-25T23:02:03Z"
    assert result["entries"][0]["source"] == "example.com"
    assert result["entries"][0]["url"] == "https://example.com/report"
    assert result["entries"][0]["summary"] == "Filed & accepted."


async def test_read_feed_refuses_unsafe_or_malformed_xml(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")
    unsafe = b'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss><channel><title>&xxe;</title></channel></rss>'
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, content=unsafe))
    )
    tool = ReadFeedTool(client)

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(tool.prepare({"url": "https://example.com/feed"}, sandbox), sandbox)

    assert "safe, well-formed" in str(caught.value)
    await client.aclose()


async def test_read_feed_stops_at_its_network_input_limit(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")
    monkeypatch.setattr("agentbase.tools.builtin.network.MAX_FEED_BYTES", 100)
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _request: httpx2.Response(200, content=b"x" * 101)
        )
    )
    tool = ReadFeedTool(client)

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(tool.prepare({"url": "https://example.com/feed"}, sandbox), sandbox)

    assert "100-byte feed safety limit" in str(caught.value)
    await client.aclose()


async def test_read_feed_counts_streamed_bytes_when_length_is_not_advertised(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Chunks(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"x" * 60
            yield b"x" * 41

    _resolves_to(monkeypatch, "93.184.216.34")
    monkeypatch.setattr("agentbase.tools.builtin.network.MAX_FEED_BYTES", 100)
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(200, stream=Chunks()))
    )
    tool = ReadFeedTool(client)

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(tool.prepare({"url": "https://example.com/feed"}, sandbox), sandbox)

    assert "100-byte feed safety limit" in str(caught.value)
    await client.aclose()


async def test_read_feed_reports_redirects_instead_of_following_them(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda _request: httpx2.Response(
                302, headers={"location": "http://169.254.169.254/feed"}
            )
        )
    )
    tool = ReadFeedTool(client)

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(tool.prepare({"url": "https://example.com/feed"}, sandbox), sandbox)

    assert "redirected to" in str(caught.value)
    assert "not followed" in str(caught.value)
    await client.aclose()


def test_read_feed_validates_its_limit_and_refuses_loopback(sandbox: Sandbox) -> None:
    tool = ReadFeedTool()

    with pytest.raises(ToolArgumentError):
        tool.prepare(
            {"url": "https://example.com/feed", "limit": MAX_FEED_ENTRIES + 1}, sandbox
        )
    with pytest.raises(UrlNotAllowedError):
        tool.prepare({"url": "http://127.0.0.1/feed"}, sandbox)


# --- run_shell ----------------------------------------------------------------


async def test_run_shell_returns_output(sandbox: Sandbox) -> None:
    tool = RunShellTool()
    prepared = tool.prepare({"command": "echo hello"}, sandbox)

    result = await tool.execute(prepared, sandbox)

    assert "hello" in result


async def test_run_shell_runs_inside_the_workspace(sandbox: Sandbox) -> None:
    """The command's working directory is the sandbox root.

    Not a boundary: a shell command can `cd` anywhere, which is exactly why
    `run_shell` is `high` risk and why the module says plainly that this is not
    isolation. It is still the right default: a relative path in a command
    means the same thing it means to every other tool.
    """
    (sandbox.root / "marker.txt").write_text("here", encoding="utf-8")
    tool = RunShellTool()
    command = "dir" if sys.platform == "win32" else "ls"

    result = await tool.execute(tool.prepare({"command": command}, sandbox), sandbox)

    assert "marker.txt" in result


async def test_run_shell_reports_a_non_zero_exit_rather_than_failing(
    sandbox: Sandbox,
) -> None:
    """A failing command is frequently the informative result.

    A test run that fails or a grep that matches nothing is a real answer, and
    raising `tool.error` for it would tell the agent the tool broke when the
    tool worked perfectly.
    """
    tool = RunShellTool()
    command = "exit 3"

    result = await tool.execute(tool.prepare({"command": command}, sandbox), sandbox)

    assert "status 3" in result


async def test_run_shell_refuses_an_empty_command(sandbox: Sandbox) -> None:
    tool = RunShellTool()

    with pytest.raises(ToolArgumentError):
        tool.prepare({"command": "   "}, sandbox)


async def test_run_shell_does_not_inherit_the_sidecar_environment(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child gets a constructed environment, not a filtered copy of ours.

    The sidecar holds API keys in memory (§1 constraint 4). Nothing puts one in
    an environment variable today, and a child inheriting the environment
    wholesale is a standing invitation for the next thing that does. An
    allowlist means a variable added later is excluded by default rather than
    included by default.
    """
    monkeypatch.setenv("AGENTBASE_TEST_SECRET", "swordfish")
    tool = RunShellTool()
    command = (
        "echo %AGENTBASE_TEST_SECRET%"
        if sys.platform == "win32"
        else "echo $AGENTBASE_TEST_SECRET"
    )

    result = await tool.execute(tool.prepare({"command": command}, sandbox), sandbox)

    assert "swordfish" not in result


async def test_run_shell_kills_a_command_that_outlives_its_timeout(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5 Phase 6: "`run_shell` has ... a hard timeout."

    Patched down to a second rather than waiting sixty. What is being asserted
    is that the timeout fires and the call comes back as an execution failure -
    a command that hung the run forever would be the failure this prevents.
    """
    monkeypatch.setattr("agentbase.tools.builtin.shell.SHELL_TIMEOUT_SECONDS", 1.0)
    tool = RunShellTool()
    command = "ping -n 30 127.0.0.1" if sys.platform == "win32" else "sleep 30"

    with pytest.raises(ToolExecutionError) as caught:
        await tool.execute(tool.prepare({"command": command}, sandbox), sandbox)

    assert "killed" in str(caught.value)


def test_run_shell_is_the_only_high_risk_tool() -> None:
    """The risk levels the approval gate branches on.

    `high` is what makes `run_shell` stop and ask even in a workspace that
    pre-approved everything else, so a tool wrongly marked `medium` would be
    silently auto-approved by a policy the user set for something far tamer.
    """
    registry = build_registry()
    high = {name for name, tool in registry.items() if tool.risk is RiskLevel.HIGH}

    assert high == {"run_shell"}
