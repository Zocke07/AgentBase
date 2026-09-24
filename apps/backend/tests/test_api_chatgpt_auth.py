"""Browser ChatGPT authentication exposed by the loopback sidecar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from agentbase.main import create_app
from agentbase.providers.base import Message, ToolSpec
from agentbase.providers.chatgpt import (
    ChatGPTAuthStatus,
    ChatGPTLoginAttempt,
    ChatGPTModelDelta,
    ChatGPTModelResponse,
)
from agentbase.providers.codex_runtime import CodexRuntimeStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agentbase.config import AppPaths


@dataclass
class FakeChatGPTRuntime:
    auth: ChatGPTAuthStatus
    closed: bool = False

    async def status(self) -> ChatGPTAuthStatus:
        return self.auth

    async def install_runtime(self) -> ChatGPTAuthStatus:
        self.auth = ChatGPTAuthStatus(
            state="preparing",
            runtime=CodexRuntimeStatus(
                state="downloading",
                version="0.154.0",
                downloaded_bytes=1_000,
                total_bytes=112_690_061,
            ),
        )
        return self.auth

    async def start_login(self) -> ChatGPTLoginAttempt:
        self.auth = ChatGPTAuthStatus(state="connecting")
        return ChatGPTLoginAttempt(
            login_id="login_123",
            auth_url="https://auth.openai.com/oauth/authorize?client_id=test",
        )

    async def cancel_login(self) -> None:
        self.auth = ChatGPTAuthStatus(state="disconnected")

    async def logout(self) -> None:
        self.auth = ChatGPTAuthStatus(state="disconnected")

    async def infer(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        *,
        system: str | None,
        max_tokens: int,
    ) -> ChatGPTModelResponse:
        raise AssertionError("auth endpoint must not call a model")

    async def stream_infer(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        *,
        system: str | None,
        max_tokens: int,
    ) -> AsyncIterator[ChatGPTModelDelta | ChatGPTModelResponse]:
        del model, messages, tools, system, max_tokens
        events: tuple[ChatGPTModelDelta | ChatGPTModelResponse, ...] = ()
        for event in events:
            yield event
        raise AssertionError("auth endpoint must not stream a model")

    async def aclose(self) -> None:
        self.closed = True


def test_chatgpt_auth_lifecycle_is_reported_without_tokens(app_paths: AppPaths) -> None:
    runtime = FakeChatGPTRuntime(ChatGPTAuthStatus(state="disconnected"))

    with TestClient(create_app(app_paths, chatgpt_runtime=runtime)) as client:
        assert client.get("/auth/chatgpt").json() == {
            "state": "disconnected",
            "email": None,
            "plan": None,
            "error": None,
            "runtime": None,
        }

        started = client.post("/auth/chatgpt/login")
        assert started.status_code == 200
        assert started.json() == {
            "login_id": "login_123",
            "auth_url": "https://auth.openai.com/oauth/authorize?client_id=test",
        }
        assert "token" not in started.text.lower()
        assert client.get("/auth/chatgpt").json()["state"] == "connecting"

        assert client.post("/auth/chatgpt/login/cancel").status_code == 204
        assert client.get("/auth/chatgpt").json()["state"] == "disconnected"

        runtime.auth = ChatGPTAuthStatus(
            state="connected", email="person@example.com", plan="plus"
        )
        connected = client.get("/auth/chatgpt").json()
        assert connected["email"] == "person@example.com"
        assert connected["plan"] == "plus"

        assert client.post("/auth/chatgpt/logout").status_code == 204
        assert client.get("/auth/chatgpt").json()["state"] == "disconnected"

    assert runtime.closed is True


def test_chatgpt_access_verifies_as_openai_without_an_api_key(app_paths: AppPaths) -> None:
    runtime = FakeChatGPTRuntime(
        ChatGPTAuthStatus(state="connected", email="person@example.com", plan="plus")
    )

    with TestClient(create_app(app_paths, chatgpt_runtime=runtime)) as client:
        changed = client.patch(
            "/settings",
            json={
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "openai_access": "chatgpt",
            },
        )
        assert changed.status_code == 200

        verified = client.post("/settings/verify").json()

    assert verified == {
        "ok": True,
        "reason": None,
        "provider": "openai",
        "model": "gpt-5.6-terra",
    }


def test_chatgpt_access_verify_explains_when_login_is_missing(app_paths: AppPaths) -> None:
    runtime = FakeChatGPTRuntime(ChatGPTAuthStatus(state="disconnected"))

    with TestClient(create_app(app_paths, chatgpt_runtime=runtime)) as client:
        client.patch(
            "/settings",
            json={
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "openai_access": "chatgpt",
            },
        )

        verified = client.post("/settings/verify").json()

    assert verified["ok"] is False
    assert "chatgpt" in verified["reason"].lower()
    assert "sign in" in verified["reason"].lower()


def test_the_runtime_can_be_fetched_before_sign_in_and_reports_progress(
    app_paths: AppPaths,
) -> None:
    """Sign-in waits for the runtime; the endpoint that fetches it is idempotent."""
    runtime = FakeChatGPTRuntime(ChatGPTAuthStatus(state="disconnected"))

    with TestClient(create_app(app_paths, chatgpt_runtime=runtime)) as client:
        started = client.post("/auth/chatgpt/runtime")
        assert started.status_code == 200, started.text
        assert started.json()["state"] == "preparing"
        assert started.json()["runtime"] == {
            "state": "downloading",
            "version": "0.154.0",
            "downloaded_bytes": 1_000,
            "total_bytes": 112_690_061,
            "error": None,
        }
        assert client.get("/auth/chatgpt").json()["state"] == "preparing"
        assert "token" not in started.text.lower()
