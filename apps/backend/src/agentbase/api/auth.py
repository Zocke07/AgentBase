"""OAuth lifecycle endpoints. No credential or token is ever returned."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

if TYPE_CHECKING:
    from agentbase.providers.chatgpt import ChatGPTRuntime

__all__ = ["router"]

router = APIRouter(prefix="/auth")


class ChatGPTRuntimeResponse(BaseModel):
    """The fetched App Server runtime: absent, downloading with progress, ready or failed."""

    state: Literal["ready", "missing", "downloading", "error"]
    version: str
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error: str | None = None


class ChatGPTAuthResponse(BaseModel):
    state: Literal["connected", "connecting", "preparing", "disconnected", "error"]
    email: str | None = None
    plan: str | None = None
    error: str | None = None
    runtime: ChatGPTRuntimeResponse | None = None


class ChatGPTLoginResponse(BaseModel):
    login_id: str
    auth_url: str


def _runtime(request: Request) -> ChatGPTRuntime:
    runtime: ChatGPTRuntime = request.app.state.chatgpt_runtime
    return runtime


@router.get("/chatgpt")
async def chatgpt_status(request: Request) -> ChatGPTAuthResponse:
    return ChatGPTAuthResponse(**asdict(await _runtime(request).status()))


@router.post("/chatgpt/runtime")
async def chatgpt_install_runtime(request: Request) -> ChatGPTAuthResponse:
    """Fetch the pinned App Server runtime once; idempotent while it downloads."""
    try:
        status_now = await _runtime(request).install_runtime()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatGPTAuthResponse(**asdict(status_now))


@router.post("/chatgpt/login")
async def chatgpt_login(request: Request) -> ChatGPTLoginResponse:
    try:
        attempt = await _runtime(request).start_login()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatGPTLoginResponse(login_id=attempt.login_id, auth_url=attempt.auth_url)


@router.post("/chatgpt/login/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def chatgpt_cancel_login(request: Request) -> Response:
    try:
        await _runtime(request).cancel_login()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chatgpt/logout", status_code=status.HTTP_204_NO_CONTENT)
async def chatgpt_logout(request: Request) -> Response:
    try:
        await _runtime(request).logout()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
