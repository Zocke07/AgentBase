"""`ToolRuntime.policy_for` and the catalogue's narrowing arithmetic."""

from __future__ import annotations

import pytest

from agentspace.store.settings import WorkspaceSettings
from agentspace.tools.catalogue import (
    RiskLevel,
    ToolPolicy,
    effective_tool_policies,
    stricter,
)


def test_stricter_orders_allow_ask_deny() -> None:
    assert stricter(ToolPolicy.ALLOW, ToolPolicy.ASK) is ToolPolicy.ASK
    assert stricter(ToolPolicy.ASK, ToolPolicy.DENY) is ToolPolicy.DENY
    assert stricter(ToolPolicy.DENY, ToolPolicy.ALLOW) is ToolPolicy.DENY
    assert stricter(ToolPolicy.ALLOW, ToolPolicy.ALLOW) is ToolPolicy.ALLOW


def test_effective_tool_policies_never_widens() -> None:
    policy = {"write_file": ToolPolicy.ALLOW, "run_shell": ToolPolicy.DENY}
    wanted = {
        "write_file": ToolPolicy.DENY,
        "run_shell": ToolPolicy.ALLOW,
        "http_get": ToolPolicy.ALLOW,
    }

    assert effective_tool_policies(wanted, policy) == {
        "write_file": ToolPolicy.DENY,
        "run_shell": ToolPolicy.DENY,
        # A request to allow what the app asks about is a question still.
        "http_get": ToolPolicy.ASK,
    }
    assert effective_tool_policies({}, policy) == policy


def test_settings_refuse_a_policy_for_a_tool_that_does_not_exist() -> None:
    with pytest.raises(ValueError, match="teleport"):
        WorkspaceSettings(tool_policies={"teleport": ToolPolicy.ALLOW})
    # `ask` is the absence of an answer and is not stored.
    kept = WorkspaceSettings(
        tool_policies={"read_file": ToolPolicy.ASK, "write_file": ToolPolicy.DENY}
    )
    assert kept.tool_policies == {"write_file": ToolPolicy.DENY}


def test_policy_for_narrows_an_allow_by_the_definition_levels(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from agentspace.events.bus import EventBus
    from agentspace.events.store import EventStore
    from agentspace.store.db import Database
    from agentspace.tools.approval import ApprovalService, ApprovalStore
    from agentspace.tools.runtime import ToolRuntime
    from agentspace.tools.sandbox import Sandbox

    db = Database(tmp_path / "t.sqlite3")
    db.connect()
    try:
        service = ApprovalService(ApprovalStore(db), EventStore(db, EventBus()))
        runtime = ToolRuntime.build(
            Sandbox(tmp_path),
            service,
            workspace_tool_policies={
                "write_file": ToolPolicy.ALLOW,
                "run_shell": ToolPolicy.DENY,
            },
        )

        # Unnarrowed: the allow stands, the deny stands, the rest asks.
        assert runtime.policy_for("write_file", ()) is ToolPolicy.ALLOW
        assert runtime.policy_for("run_shell", ()) is ToolPolicy.DENY
        assert runtime.policy_for("read_file", ()) is ToolPolicy.ASK
        # A definition limited to low-risk calls turns the medium-risk allow
        # back into a question, and a deny is already as strict as it gets.
        assert runtime.policy_for("write_file", (RiskLevel.LOW,)) is ToolPolicy.ASK
        assert runtime.policy_for("write_file", (RiskLevel.MEDIUM,)) is ToolPolicy.ALLOW
        assert runtime.policy_for("run_shell", (RiskLevel.HIGH,)) is ToolPolicy.DENY
    finally:
        db.close()
