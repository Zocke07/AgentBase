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
    #: The account's model list; ``None`` is unknown.
    included: frozenset[str] | None = None

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

    async def models(self) -> frozenset[str] | None:
        return self.included

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
        "suggested_model": None,
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


# --- a plan that lacks models the price list sells -------------------------------

#: What Codex listed for a ChatGPT account on 2026-09-29: GPT-6 Sol and Luna
#: are API models the subscription does not include.
PLAN = frozenset({"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"})


def _plan_client(app_paths: AppPaths) -> tuple[TestClient, FakeChatGPTRuntime]:
    runtime = FakeChatGPTRuntime(ChatGPTAuthStatus(state="connected"), included=PLAN)
    return TestClient(create_app(app_paths, chatgpt_runtime=runtime)), runtime


def test_the_catalogue_says_which_openai_models_the_plan_includes(app_paths: AppPaths) -> None:
    client, _ = _plan_client(app_paths)
    with client:
        before = client.get("/settings/providers").json()["catalog"]["openai"]
        assert {entry["available"] for entry in before} == {None}

        client.patch("/settings", json={"provider": "openai", "openai_access": "chatgpt"})
        after = {
            entry["id"]: entry["available"]
            for entry in client.get("/settings/providers").json()["catalog"]["openai"]
        }
        anthropic = client.get("/settings/providers").json()["catalog"]["anthropic"]

    assert after["gpt-6-sol"] is False and after["gpt-6-luna"] is False
    assert after["gpt-6-astra"] is True and after["gpt-5.6-sol"] is True
    assert {entry["available"] for entry in anthropic} == {None}


def test_a_new_space_on_the_plan_starts_on_a_model_it_includes(app_paths: AppPaths) -> None:
    client, _ = _plan_client(app_paths)
    with client:
        client.patch("/settings", json={"openai_access": "chatgpt"})
        created = client.post("/spaces", json={"name": "Lab", "provider": "openai"}).json()

    # A new space starts on the default tier, strong: the plan has one where
    # the API lineup did not, so it is GPT-5.6 Sol rather than GPT-6 Sol.
    assert created["model"] == "gpt-5.6-sol"


def test_the_check_names_a_model_the_plan_lacks_and_offers_the_closest(
    app_paths: AppPaths,
) -> None:
    client, _ = _plan_client(app_paths)
    with client:
        client.patch("/settings", json={"openai_access": "chatgpt"})
        space = client.post(
            "/spaces", json={"name": "Lab", "provider": "openai", "model": "gpt-6-sol"}
        ).json()
        verdict = client.post("/settings/verify", params={"space_id": space["id"]}).json()

    assert verdict["ok"] is False
    assert "does not include gpt-6-sol" in verdict["reason"]
    # A space on GPT-6 Sol stands where GPT-6 has no strong model; the plan's
    # strong one is GPT-5.6 Sol (maintainer's choice, 2026-09-29).
    assert verdict["suggested_model"] == "gpt-5.6-sol"


def test_staying_on_openai_plans_the_move_to_models_the_plan_includes(
    app_paths: AppPaths,
) -> None:
    client, _ = _plan_client(app_paths)
    with client:
        client.patch("/settings", json={"openai_access": "chatgpt"})
        space = client.post(
            "/spaces", json={"name": "Lab", "provider": "openai", "model": "gpt-6-sol"}
        ).json()
        for name, provider, model in (
            ("scanner", "openai", "gpt-6-luna"),
            ("analyst", "openai", "gpt-6-sol"),
            ("drafter", "openai", "gpt-5.6-terra"),
            ("follower", None, None),
        ):
            created = client.post(
                "/agents",
                json={
                    "space_id": space["id"],
                    "name": name,
                    "role": "r",
                    "system_prompt": "p",
                    "provider": provider,
                    "model": model,
                    "allowed_tools": [],
                },
            )
            assert created.status_code == 201, created.text
        plan = client.get(
            f"/spaces/{space['id']}/provider-switch", params={"provider": "openai"}
        ).json()

    assert plan["model"] == "gpt-5.6-sol"
    # An agent on Sol keeps Sol's own tier: it may have been a Sonnet analyst.
    assert sorted((agent["name"], agent["to_model"]) for agent in plan["agents"]) == [
        ("analyst", "gpt-5.6-terra"),
        ("scanner", "gpt-5.6-luna"),
    ]


def test_the_app_wide_check_leaves_the_backing_model_alone(app_paths: AppPaths) -> None:
    """The app-wide model only backs a space row naming none, and each
    space's check covers what its runs use: Settings must not report it."""
    client, _ = _plan_client(app_paths)
    with client:
        client.patch(
            "/settings",
            json={"provider": "openai", "model": "gpt-6-sol", "openai_access": "chatgpt"},
        )
        verdict = client.post("/settings/verify").json()

    assert verdict["ok"] is True


def test_a_provider_change_starts_on_a_model_the_plan_includes(app_paths: AppPaths) -> None:
    client, _ = _plan_client(app_paths)
    with client:
        client.patch("/settings", json={"openai_access": "chatgpt"})
        changed = client.patch("/settings", json={"provider": "openai"}).json()
        entries = client.get("/settings/providers").json()["providers"]

    assert changed["settings"]["model"] == "gpt-5.6-sol"
    defaults = {entry["name"]: entry["default_model"] for entry in entries}
    assert defaults["openai"] == "gpt-5.6-sol"


def test_a_plan_with_no_priced_model_says_so_rather_than_offer_one(
    app_paths: AppPaths,
) -> None:
    runtime = FakeChatGPTRuntime(
        ChatGPTAuthStatus(state="connected"), included=frozenset({"gpt-reserve"})
    )
    with TestClient(create_app(app_paths, chatgpt_runtime=runtime)) as client:
        client.patch("/settings", json={"openai_access": "chatgpt"})
        space = client.post(
            "/spaces", json={"name": "Lab", "provider": "openai", "model": "gpt-6-sol"}
        ).json()
        verdict = client.post("/settings/verify", params={"space_id": space["id"]}).json()

    assert verdict["ok"] is False
    assert "none of the models it does include has a price" in verdict["reason"]
    assert verdict["suggested_model"] is None
