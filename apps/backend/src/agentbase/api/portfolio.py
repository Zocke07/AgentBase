"""Personal stock-data editing initiated by the person using the app."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from agentbase.store.portfolio import (
    PortfolioConflictError,
    PortfolioInputError,
    PortfolioResponse,
    PortfolioValuation,
    SavePortfolioRequest,
    load_portfolio,
    load_valuation,
    save_portfolio,
)
from agentbase.store.spaces import DEFAULT_SPACE_ID, SpaceNotFoundError
from agentbase.tools.sandbox import SandboxViolationError

if TYPE_CHECKING:
    from pathlib import Path

    from agentbase.store.db import Database
    from agentbase.store.spaces import SpaceStore

router = APIRouter(prefix="/spaces/{space_id}/portfolio")


async def _root(request: Request, space_id: str, *, write: bool = False) -> Path:
    spaces: SpaceStore = request.app.state.spaces
    try:
        space = await spaces.require(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if space.id != DEFAULT_SPACE_ID:
        # Part of the default space's investment pipeline, which stays there
        # (2026-10-13); other spaces have no personal stock data.
        home = await spaces.require(DEFAULT_SPACE_ID)
        raise HTTPException(
            status_code=404,
            detail=f"Personal stock data is kept only in {home.name}, the space with the "
            f"investment pipeline.",
        )
    if write and space.archived:
        raise HTTPException(
            status_code=409, detail="Unarchive this space before changing its portfolio."
        )
    return spaces.folder_for(space_id)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, PortfolioConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, SandboxViolationError) or "symlink" in str(exc):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, OSError):
        return HTTPException(
            status_code=500,
            detail="Could not save or read the portfolio files. Close files open in another app and try again. Your previous data is backed up when saving.",
        )
    return HTTPException(status_code=422, detail=str(exc))


@router.get("")
async def get_portfolio(request: Request, space_id: str) -> PortfolioResponse:
    root = await _root(request, space_id)
    try:
        return await asyncio.to_thread(load_portfolio, root)
    except (PortfolioInputError, SandboxViolationError, OSError, ValueError, TypeError) as exc:
        raise _error(exc) from exc


@router.get("/valuation")
async def get_valuation(request: Request, space_id: str) -> PortfolioValuation | None:
    """The newest valuation for Home: its worth, and what changed and went
    unreported since the report before it. Null until a run has valued it."""
    root = await _root(request, space_id)
    return await asyncio.to_thread(load_valuation, root)


@router.put("")
async def put_portfolio(
    request: Request, space_id: str, body: SavePortfolioRequest
) -> PortfolioResponse:
    root = await _root(request, space_id, write=True)
    database: Database = request.app.state.db

    def save() -> PortfolioResponse:
        # Hold the shared SQLite connection lock until the files are replaced.
        # A new run cannot be recorded between the busy check and the save.
        with database.read() as connection:
            space = connection.execute(
                "SELECT archived FROM spaces WHERE id=?", (space_id,)
            ).fetchone()
            if space is None:
                raise HTTPException(status_code=404, detail="This space no longer exists.")
            if space["archived"]:
                raise HTTPException(
                    status_code=409,
                    detail="Unarchive this space before changing its portfolio.",
                )
            active = connection.execute(
                "SELECT 1 FROM runs WHERE space_id=? AND status IN ('pending','running','paused') LIMIT 1",
                (space_id,),
            ).fetchone()
            if active:
                raise PortfolioConflictError(
                    "A run is using this portfolio. Wait for it to finish, or cancel it, before saving changes."
                )
            return save_portfolio(root, body)

    try:
        return await asyncio.to_thread(save)
    except (
        PortfolioInputError,
        PortfolioConflictError,
        SandboxViolationError,
        OSError,
        ValueError,
        TypeError,
    ) as exc:
        raise _error(exc) from exc
