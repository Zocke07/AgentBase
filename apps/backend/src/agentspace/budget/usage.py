"""The usage report: what a month of model calls cost and carried, sliced.

Everything here is read from the `spend` ledger, which holds one row per
model call with its tokens and its integer-micro cost, joined to `runs` for
the space and the goal. Nothing is estimated: a figure that is not in the
ledger is not on the report. A call's input tokens are the context it sent,
so the largest of them in a run is the most context that run carried.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel

from agentspace.providers.pricing import format_micros

if TYPE_CHECKING:
    import sqlite3

    from agentspace.store.db import Database

__all__ = [
    "MAX_RUN_ROWS",
    "UsageBucket",
    "UsageReport",
    "UsageRun",
    "UsageStore",
    "UsageTotals",
]

#: The most runs one report lists, costliest first; the rest are in the totals.
MAX_RUN_ROWS: Final[int] = 40


class UsageTotals(BaseModel):
    calls: int
    runs: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
    cost_display: str


class UsageBucket(BaseModel):
    """One slice of the period: a model, a space or a day."""

    key: str
    label: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
    cost_display: str


class UsageRun(BaseModel):
    run_id: str | None
    space_id: str | None
    goal: str | None
    status: str | None
    origin: str | None
    created_at: str | None
    calls: int
    input_tokens: int
    output_tokens: int
    #: The most tokens one call in this run sent: the largest context it carried.
    peak_context: int
    #: The mean input tokens per call: how much context a typical call carried.
    mean_context: int
    cost_micros: int
    cost_display: str


class UsageReport(BaseModel):
    period: str
    #: Every period the ledger has rows for, newest first, so the UI can offer them.
    periods: list[str]
    space_id: str | None
    cap_micros: int
    totals: UsageTotals
    by_model: list[UsageBucket]
    by_space: list[UsageBucket]
    by_day: list[UsageBucket]
    #: The costliest runs of the period, up to MAX_RUN_ROWS.
    runs: list[UsageRun]


def _bucket(key: str, label: str, row: sqlite3.Row) -> UsageBucket:
    cost = int(row["cost_micros"])
    return UsageBucket(
        key=key,
        label=label,
        calls=int(row["calls"]),
        input_tokens=int(row["input_tokens"]),
        output_tokens=int(row["output_tokens"]),
        cost_micros=cost,
        cost_display=format_micros(cost),
    )


class UsageStore:
    """Reads the ledger for the report. Read-only: the ledger writes."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def report(self, period: str, space_id: str | None, cap_micros: int) -> UsageReport:
        return await asyncio.to_thread(self._report_sync, period, space_id, cap_micros)

    def _report_sync(self, period: str, space_id: str | None, cap_micros: int) -> UsageReport:
        # The space filter joins through runs; a deleted run has no space any
        # more (its spend row keeps a NULL run_id, by design), so a per-space
        # report cannot count it and the all-spaces report lists it as such.
        where = "WHERE spend.period = ?"
        params: list[object] = [period]
        if space_id is not None:
            where += " AND runs.space_id = ?"
            params.append(space_id)
        base = f"FROM spend LEFT JOIN runs ON runs.id = spend.run_id {where}"
        with_spaces = (
            "FROM spend LEFT JOIN runs ON runs.id = spend.run_id"
            f" LEFT JOIN spaces ON spaces.id = runs.space_id {where}"
        )
        sums = (
            "COUNT(*) AS calls, COALESCE(SUM(spend.input_tokens), 0) AS input_tokens,"
            " COALESCE(SUM(spend.output_tokens), 0) AS output_tokens,"
            " COALESCE(SUM(spend.cost_micros), 0) AS cost_micros"
        )

        with self._db.read() as connection:
            periods = [
                str(row["period"])
                for row in connection.execute(
                    "SELECT DISTINCT period FROM spend ORDER BY period DESC"
                ).fetchall()
            ]
            total = connection.execute(
                f"SELECT {sums}, COUNT(DISTINCT spend.run_id) AS runs {base}",
                params,
            ).fetchone()
            by_model = connection.execute(
                f"SELECT spend.provider AS provider, spend.model AS model, {sums} {base}"
                " GROUP BY spend.provider, spend.model ORDER BY cost_micros DESC, calls DESC",
                params,
            ).fetchall()
            by_space = connection.execute(
                f"SELECT runs.space_id AS space_id, spaces.name AS space_name, {sums}"
                f" {with_spaces} GROUP BY runs.space_id ORDER BY cost_micros DESC, calls DESC",
                params,
            ).fetchall()
            by_day = connection.execute(
                f"SELECT substr(spend.ts, 1, 10) AS day, {sums} {base}"
                " GROUP BY day ORDER BY day",
                params,
            ).fetchall()
            runs = connection.execute(
                "SELECT spend.run_id AS run_id, runs.space_id AS space_id, runs.goal AS goal,"
                " runs.status AS status, runs.origin AS origin, runs.created_at AS created_at,"
                f" {sums}, COALESCE(MAX(spend.input_tokens), 0) AS peak_context,"
                " COALESCE(AVG(spend.input_tokens), 0) AS mean_context"
                f" {base} GROUP BY spend.run_id ORDER BY cost_micros DESC, calls DESC LIMIT ?",
                [*params, MAX_RUN_ROWS],
            ).fetchall()

        total_cost = int(total["cost_micros"])
        return UsageReport(
            period=period,
            periods=periods,
            space_id=space_id,
            cap_micros=cap_micros,
            totals=UsageTotals(
                calls=int(total["calls"]),
                runs=int(total["runs"]),
                input_tokens=int(total["input_tokens"]),
                output_tokens=int(total["output_tokens"]),
                cost_micros=total_cost,
                cost_display=format_micros(total_cost),
            ),
            by_model=[
                _bucket(
                    f"{row['provider']}/{row['model']}",
                    f"{row['provider']} · {row['model']}",
                    row,
                )
                for row in by_model
            ],
            by_space=[
                _bucket(
                    str(row["space_id"]) if row["space_id"] is not None else "",
                    str(row["space_name"]) if row["space_name"] is not None else "deleted runs",
                    row,
                )
                for row in by_space
            ],
            by_day=[_bucket(str(row["day"]), str(row["day"]), row) for row in by_day],
            runs=[
                UsageRun(
                    run_id=row["run_id"],
                    space_id=row["space_id"],
                    goal=row["goal"],
                    status=row["status"],
                    origin=row["origin"],
                    created_at=row["created_at"],
                    calls=int(row["calls"]),
                    input_tokens=int(row["input_tokens"]),
                    output_tokens=int(row["output_tokens"]),
                    peak_context=int(row["peak_context"]),
                    mean_context=round(float(row["mean_context"])),
                    cost_micros=int(row["cost_micros"]),
                    cost_display=format_micros(int(row["cost_micros"])),
                )
                for row in runs
            ],
        )
