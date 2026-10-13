"""A call whose arguments the provider could not read is answered, never run."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentbase.orchestrator import execute_run
from agentbase.providers.base import ToolCall
from agentbase.tools.catalogue import RiskLevel
from support import ScriptedProvider, call, reconstruct, says, tool_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from agentbase.budget.ledger import BudgetLedger
    from agentbase.events.store import EventStore
    from agentbase.secrets import SecretStore
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.db import Database
    from agentbase.store.settings import SettingsStore

pytestmark = pytest.mark.anyio


async def test_an_unreadable_call_is_explained_and_the_rest_of_its_batch_runs(
    store: EventStore,
    settings: SettingsStore,
    agents: AgentDefStore,
    ledger: BudgetLedger,
    secrets: SecretStore,
    db: Database,
    tmp_path: Path,
) -> None:
    """2026-10-13: in a batch of ten reads one arrived as ``{}``; told it gave
    no path, the decision moved on without MSFT's figures."""
    workspace = tmp_path / "space"
    (workspace / "raw/filings").mkdir(parents=True)
    (workspace / "raw/filings/MU.json").write_text('{"ticker": "MU"}', encoding="utf-8")
    await settings.update({"auto_approve": [RiskLevel.LOW, RiskLevel.MEDIUM]})
    runtime, _ = tool_runtime(store, db, workspace)
    await agents.create(
        {
            "name": "reader",
            "role": "Reads files",
            "system_prompt": "Read what you are asked to read.",
            "allowed_tools": ["read_file"],
        }
    )
    unreadable = ToolCall(
        id="r2",
        name="read_file",
        argument_error="they are not valid JSON (Expecting ',' delimiter at character 31)",
    )
    provider = ScriptedProvider(
        [
            says("Delegating.", call("spawn_agent", "s1", agent="reader", task="Read")),
            says("", call("read_file", "r1", path="raw/filings/MU.json"), unreadable),
            says("Done.", call("finish", "f1", result="Read MU.")),
            says("Done.", call("finish", "s2", result="Handled.")),
        ]
    )
    run = await store.create_run(goal="Read the filings", origin="ui")

    await execute_run(
        store,
        settings,
        agents,
        ledger,
        secrets,
        run.id,
        "Read the filings",
        provider=provider,
        runtime=runtime,
    )

    reader = reconstruct(await store.read(run.id)).agent("reader")
    # Only the readable call ran; the other was explained, not run as ``{}``.
    assert reader.tool_calls == [
        ("read_file", {"path": "raw/filings/MU.json"}),
        ("finish", {"result": "Read MU."}),
    ]
    [error] = reader.tool_errors
    assert error.startswith("The arguments for this read_file call could not be read:")
    assert "not valid JSON" in error and "Send it again" in error
    assert "needs a 'path'" not in error
    # The model is told which of its calls failed, beside the one that worked.
    replies = [
        message.content
        for message in provider.requests[2]
        if message.tool_call_id in {"r1", "r2"}
    ]
    assert replies[0] == '{"ticker": "MU"}' and replies[1] == error
