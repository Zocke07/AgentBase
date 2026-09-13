"""The chat message is a fold of the event log, and these pin what it says:
a terminal summary is a claim rendered beside a count of what executed, a
denial says which boundary stopped it, and `llm.token` is not a liveness signal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agentspace.channels.render import (
    DISCORD_MESSAGE_LIMIT,
    fold,
    render,
)
from agentspace.events.types import Event, EventType

RUN_ID = "3f2a9c1e-0000-4000-8000-000000000001"


def event(
    seq: int, type_: EventType, payload: dict[str, Any], agent: str | None = None
) -> Event:
    return Event(
        id=seq,
        run_id=RUN_ID,
        seq=seq,
        agent_id=agent,
        type=type_,
        payload=payload,
        ts=datetime(2026, 9, 10, 12, 0, seq % 60, tzinfo=UTC),
    )


def started(goal: str = "Summarise the quarterly report") -> list[Event]:
    return [
        event(1, EventType.CHANNEL_INBOUND, {"channel": "discord", "identity": "owner"}),
        event(2, EventType.RUN_STARTED, {"goal": goal}),
        event(3, EventType.AGENT_SPAWNED, {"role": "Plans and delegates"}, "supervisor"),
    ]


def test_the_goal_and_the_run_status_are_rendered() -> None:
    text = render(fold(started()), limit=DISCORD_MESSAGE_LIMIT)

    assert "Summarise the quarterly report" in text
    assert "running" in text


def test_each_spawned_agent_appears_with_its_role() -> None:
    events = [*started(), event(4, EventType.AGENT_SPAWNED, {"role": "Gathers sources"}, "rex")]

    view = fold(events)

    assert [agent.name for agent in view.agents] == ["supervisor", "rex"]
    assert "Gathers sources" in render(view, limit=DISCORD_MESSAGE_LIMIT)


def test_a_terminal_summary_is_rendered_as_a_claim_beside_what_executed() -> None:
    """The Phase 7 decision, carried into chat unchanged.

    Four live runs in this project have announced work the log shows never
    happened: `finish("reminder.txt")` from an agent that never called
    `write_file`. A chat reply that printed the summary alone would be
    repeating the confabulation to the one audience least able to check it,
    because a chat user cannot see the event log at all.
    """
    events = [
        *started(),
        event(4, EventType.TOOL_CALLED, {"tool": "read_file", "args": {}}, "supervisor"),
        event(5, EventType.RUN_COMPLETED, {"summary": "Saved to notes.txt"}),
    ]

    text = render(fold(events), limit=DISCORD_MESSAGE_LIMIT)

    assert "Saved to notes.txt" in text
    assert "said it did" in text
    assert "1 tool call" in text


def test_a_completed_run_that_called_no_tools_says_so_in_the_count() -> None:
    """The exact shape of the four confabulations: a claim with nothing behind it."""
    events = [*started(), event(4, EventType.RUN_COMPLETED, {"summary": "Wrote the file."})]

    assert "0 tool calls" in render(fold(events), limit=DISCORD_MESSAGE_LIMIT)


def test_a_failed_run_renders_the_reason_and_not_a_summary() -> None:
    events = [*started(), event(4, EventType.RUN_FAILED, {"reason": "Out of time."})]

    view = fold(events)

    assert view.status == "failed"
    assert view.claim is not None
    assert view.claim.kind == "failure"
    assert "said it did" not in render(view, limit=DISCORD_MESSAGE_LIMIT)


def test_a_denial_says_which_boundary_stopped_it() -> None:
    """`blocked_by` separates an agent probing the workspace boundary from a
    person declining a routine write. Collapsing them would render a
    prompt-injected escape attempt and an ordinary "no" identically."""
    events = [
        *started(),
        event(
            4,
            EventType.TOOL_DENIED,
            {"tool": "write_file", "reason": "outside the workspace", "blocked_by": "sandbox"},
            "rex",
        ),
    ]

    text = render(fold(events), limit=DISCORD_MESSAGE_LIMIT)

    assert "write_file" in text
    assert "sandbox" in text


def test_an_outstanding_approval_is_surfaced_with_its_prompt() -> None:
    """A run blocked on the gate has stopped emitting anything.

    In the dashboard that is obvious: the modal is on screen. In chat, the
    message simply stops updating, which is indistinguishable from the bot
    having crashed. Surfacing the question is what makes the gate usable from a
    channel at all.
    """
    events = [
        *started(),
        event(
            4,
            EventType.APPROVAL_REQUESTED,
            {
                "approval_id": "a1",
                "prompt": 'create "notes.txt" (36 characters)',
                "risk": "medium",
            },
            "rex",
        ),
    ]

    view = fold(events)

    assert [pending.approval_id for pending in view.approvals] == ["a1"]
    assert 'create "notes.txt"' in render(view, limit=DISCORD_MESSAGE_LIMIT)


def test_a_resolved_approval_stops_being_outstanding() -> None:
    events = [
        *started(),
        event(4, EventType.APPROVAL_REQUESTED, {"approval_id": "a1", "prompt": "p"}, "rex"),
        event(
            5, EventType.APPROVAL_RESOLVED, {"approval_id": "a1", "status": "approved"}, "rex"
        ),
    ]

    assert fold(events).approvals == ()


def test_token_events_are_not_a_liveness_signal() -> None:
    """Carried from Phase 7, which carried it from two live findings: Anthropic
    coalesces 1-10 deltas unpredictably, and a pure-tool-call response emits
    zero. An agent that streams nothing is working, not idle."""
    thinking = fold([*started(), event(4, EventType.AGENT_THINKING, {"step": 1}, "supervisor")])
    streaming = fold(
        [
            *started(),
            *(
                event(index + 4, EventType.LLM_TOKEN, {"text": "hello "}, "supervisor")
                for index in range(50)
            ),
        ]
    )

    # `agent.thinking` is a liveness signal and moves the agent's state.
    assert thinking.agents[0].state == "thinking"
    # Fifty streamed tokens move nothing, and the inverse matters just as much:
    # an agent whose whole response is a tool call emits no tokens at all, so a
    # renderer keyed on them would show a working agent as idle.
    assert streaming.agents[0].state == "spawned"
    assert streaming.activity == ()


def test_every_event_type_in_the_contract_is_handled_by_the_fold() -> None:
    """The Python half of §4's "adding an event type means updating the reducer".

    `mypy --strict` already proves this: the `case _` arm calls `assert_never`,
    so a new `EventType` member with no branch does not typecheck. This test is
    the belt to that braces, and it catches the specific way the proof could be
    defeated: someone adding a broad `case _: pass` to silence the error, which
    would typecheck perfectly and silently drop the new event.

    It asserts the *observable* consequence instead: folding a log of one event
    of every type raises nothing and counts every one of them.
    """
    events = [event(index + 1, type_, {}) for index, type_ in enumerate(EventType)]

    view = fold(events)

    assert view.event_count == len(list(EventType))


def test_a_long_run_is_clamped_to_the_platform_limit() -> None:
    """Discord rejects a message body over 2000 characters outright.

    A renderer that produced 6000 characters would not truncate, it would 400 -
    and the user would see the message stop updating at the exact moment the
    run got interesting.
    """
    events = list(started())
    for index in range(400):
        events.append(
            event(
                index + 4,
                EventType.AGENT_MESSAGE,
                {"text": f"line {index} " + "x" * 80},
                "rex",
            )
        )

    text = render(fold(events), limit=DISCORD_MESSAGE_LIMIT)

    assert len(text) <= DISCORD_MESSAGE_LIMIT


def test_clamping_keeps_the_goal_and_the_outcome_and_drops_the_middle() -> None:
    """What survives a trim is the part a reader cannot reconstruct.

    The activity tail is the least valuable thing in the message (the whole log
    is in the dashboard), while the goal and the terminal claim exist nowhere
    else in the conversation.
    """
    events = list(started("Find the revenue figures"))
    for index in range(400):
        events.append(event(index + 4, EventType.AGENT_MESSAGE, {"text": "y" * 90}, "rex"))
    events.append(event(500, EventType.RUN_COMPLETED, {"summary": "Revenue up 12%."}))

    text = render(fold(events), limit=DISCORD_MESSAGE_LIMIT)

    assert len(text) <= DISCORD_MESSAGE_LIMIT
    assert "Find the revenue figures" in text
    assert "Revenue up 12%." in text


def test_the_render_contains_no_markdown_control_characters_of_its_own() -> None:
    """Plain text, deliberately: see the module docstring in `render.py`.

    Agent output is arbitrary text, so any markdown mode is a grenade with a
    long fuse: originally Telegram's MarkdownV2, where an unescaped character
    loses the entire message; on Discord a stray `*` or backtick in a file's
    contents becomes formatting. One plain renderer cannot fail this way.
    """
    events = [*started("**bold** _italic_ `code` [x](y)")]

    text = render(fold(events), limit=DISCORD_MESSAGE_LIMIT)

    assert "**bold** _italic_ `code` [x](y)" in text


def test_a_partial_log_renders_without_implying_a_run_happened() -> None:
    """A log holding only `channel.inbound` must not render as work in progress.

    This is the state a reader sees for the fraction of a second between the
    message arriving and the orchestrator emitting `run.started`, and it is also
    what a log looks like if the run failed to start at all.
    """
    view = fold([event(1, EventType.CHANNEL_INBOUND, {"channel": "discord", "identity": None})])

    assert view.agents == ()
    assert view.claim is None
    assert view.status == "pending"
