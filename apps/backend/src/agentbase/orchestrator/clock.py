"""The run's start time, stated to every agent in it.

Models have no clock. Without this, dated file names and records came from file
names already on disk or from guesses, and only the ChatGPT runtime supplied a
date at all. The sentence sits in each system prompt, which ``agent.spawned``
logs, so a replay shows the time the agents were given.
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, tzinfo

__all__ = ["started_note"]


def started_note(started: datetime, zone: tzinfo) -> str:
    """Say when the run started, in the machine's local time and in UTC.

    A Taipei morning is the previous day in UTC and in New York, so a stage
    naming files by date needs both.
    """
    local = started.astimezone(zone)
    offset = local.strftime("%z")
    utc = started.astimezone(UTC)
    return (
        f"This run started on {local:%A %Y-%m-%d} at {local:%H:%M} local time "
        f"(UTC{offset[:3]}:{offset[3:]}), which is {utc:%Y-%m-%d %H:%M} UTC. Use "
        "this for every date and time you write, and never guess one."
    )
