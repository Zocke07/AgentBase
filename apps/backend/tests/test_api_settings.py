"""Tests for the settings and budget endpoints.

`test_switching_provider_is_an_http_call_and_nothing_else` never imports a
provider class: it changes a stored value over HTTP and watches the selection
change, which is the strongest form of "a settings change with no code change".
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentspace.api.settings import UpdateSettingsRequest
from agentspace.main import create_app
from agentspace.secrets import SecretStore
from agentspace.store.settings import DEFAULT_MONTHLY_CAP_MICROS, WorkspaceSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.config import AppPaths

FAKE_KEY = "totally-not-a-real-key-9f3a2b"


@pytest.fixture
def secrets() -> SecretStore:
    return SecretStore({"anthropic_api_key": FAKE_KEY, "openai_api_key": "another"})


@pytest.fixture
def client(app_paths: AppPaths, secrets: SecretStore) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=secrets)) as test_client:
        yield test_client


# --- reading -----------------------------------------------------------------


def test_settings_start_at_the_documented_defaults(client: TestClient) -> None:
    body = client.get("/settings").json()

    assert body["settings"]["provider"] == "anthropic"
    assert body["settings"]["model"] == "claude-opus-5"
    assert body["settings"]["monthly_cap_micros"] == DEFAULT_MONTHLY_CAP_MICROS


def test_settings_report_which_keys_are_configured_but_never_their_values(
    client: TestClient,
) -> None:
    """§1 constraint 4. The UI needs "key configured"; it never needs the key,
    and an endpoint that returns one is an exfiltration endpoint."""
    response = client.get("/settings")

    assert response.json()["configured_secrets"] == [
        "anthropic_api_key",
        "openai_api_key",
    ]
    assert FAKE_KEY not in response.text


def test_no_endpoint_returns_a_key(client: TestClient) -> None:
    """Swept across the whole Phase 3 surface rather than one endpoint."""
    for path in ("/settings", "/settings/providers", "/budget", "/openapi.json"):
        assert FAKE_KEY not in client.get(path).text

    assert FAKE_KEY not in client.post("/settings/verify").text


def test_settings_report_whether_the_model_is_priced(client: TestClient) -> None:
    assert client.get("/settings").json()["model_is_priced"] is True


def test_a_local_model_is_reported_as_priced(client: TestClient) -> None:
    """Found by running the thing, on the seventh instance of this shape.

    `GET /settings` used to price `settings.model` verbatim, while the provider
    that actually runs namespaces an Ollama model to `ollama/<name>` before the
    ledger ever sees it. So every local model reported `model_is_priced: false`
    (whose docstring promises "every run will be refused") while runs in fact
    worked perfectly and cost nothing. The Phase 7 header rendered that as
    "unpriced: runs will be refused" over a configuration that was fine.
    """
    client.patch("/settings", json={"provider": "ollama", "model": "qwen3:4b"})

    assert client.get("/settings").json()["model_is_priced"] is True


def test_settings_and_verify_agree_about_pricing(client: TestClient) -> None:
    """The two endpoints must not disagree about the same configuration.

    `POST /settings/verify` was right because it builds the provider and asks
    about `provider.model`; `GET /settings` was wrong because it asked about the
    raw setting. Comparing them is what stops the next provider with a naming
    rule of its own repeating it.
    """
    for provider, model in (("ollama", "qwen3:4b"), ("ollama", "gemma4:e4b")):
        client.patch("/settings", json={"provider": provider, "model": model})

        settings_says = client.get("/settings").json()["model_is_priced"]
        verify = client.post("/settings/verify").json()

        assert settings_says is True
        assert verify["ok"] is True, verify


def test_an_unpriced_cloud_model_is_still_reported_as_unpriced(client: TestClient) -> None:
    """The check must still be capable of saying no, or it protects nothing."""
    client.patch("/settings", json={"provider": "anthropic", "model": "claude-not-a-model"})

    assert client.get("/settings").json()["model_is_priced"] is False


# --- the acceptance criterion ------------------------------------------------


def test_switching_provider_is_an_http_call_and_nothing_else(client: TestClient) -> None:
    """BUILD_SPEC §5 Phase 3, acceptance criterion, first clause.

    No provider class is imported in this module. The only thing that happens
    between the two assertions is a PATCH.
    """
    assert client.get("/settings").json()["settings"]["provider"] == "anthropic"

    response = client.patch("/settings", json={"provider": "openai", "model": "gpt-5.4"})

    assert response.status_code == 200
    assert response.json()["settings"]["provider"] == "openai"
    assert client.get("/settings").json()["settings"]["model"] == "gpt-5.4"


def test_openai_access_mode_is_a_persisted_setting(client: TestClient) -> None:
    response = client.patch("/settings", json={"openai_access": "chatgpt"})

    assert response.status_code == 200
    assert response.json()["settings"]["openai_access"] == "chatgpt"
    assert client.get("/settings").json()["settings"]["openai_access"] == "chatgpt"


def test_an_unknown_openai_access_mode_is_rejected(client: TestClient) -> None:
    response = client.patch("/settings", json={"openai_access": "shared-password"})

    assert response.status_code == 422


def test_the_switch_survives_a_restart(app_paths: AppPaths, secrets: SecretStore) -> None:
    """A setting that lives only in memory is not a setting."""
    with TestClient(create_app(app_paths, secrets=secrets)) as first:
        first.patch("/settings", json={"provider": "openai", "model": "gpt-5.4"})

    with TestClient(create_app(app_paths, secrets=secrets)) as second:
        assert second.get("/settings").json()["settings"]["provider"] == "openai"


def test_verify_reports_the_selected_provider_can_be_built(client: TestClient) -> None:
    body = client.post("/settings/verify").json()

    assert body["ok"] is True
    assert body["provider"] == "anthropic"


def test_verify_reports_a_missing_key_without_calling_the_model(
    app_paths: AppPaths,
) -> None:
    """Verification must not spend money to answer a configuration question."""
    with TestClient(create_app(app_paths, secrets=SecretStore())) as client:
        body = client.post("/settings/verify").json()

    assert body["ok"] is False
    assert "key" in body["reason"].lower()


def test_verify_rejects_an_unpriced_model(client: TestClient) -> None:
    """An unpriced model means every run is refused, so say so up front."""
    client.patch("/settings", json={"model": "model-from-the-future"})

    body = client.post("/settings/verify").json()

    assert body["ok"] is False
    assert "price" in body["reason"].lower()


def test_ollama_verifies_with_no_key_at_all(app_paths: AppPaths) -> None:
    """The abstraction must not assume cloud (§7)."""
    with TestClient(create_app(app_paths, secrets=SecretStore())) as client:
        client.patch("/settings", json={"provider": "ollama", "model": "ollama/llama3.3"})

        assert client.post("/settings/verify").json()["ok"] is True


# --- validation --------------------------------------------------------------


def test_an_unknown_provider_is_a_400_naming_the_field(client: TestClient) -> None:
    """§5 Phase 5 phrases the rule for agent defs; the same applies here -
    the settings form renders this message inline on the offending field,
    which it can only do if the body says which field. The docstring on the
    endpoint claimed as much while it answered a bare string."""
    response = client.patch("/settings", json={"provider": "hal9000"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "hal9000" in detail["message"]
    assert "anthropic" in detail["message"]
    assert detail["field"] == "provider"


def test_a_duplicate_channel_identity_names_its_field(client: TestClient) -> None:
    """The store refuses it as a pydantic error; the field must survive the
    trip out rather than arriving as a multi-line traceback string."""
    entry = {"channel": "discord", "external_user_id": "1", "identity": "owner"}
    response = client.patch("/settings", json={"channel_identities": [entry, entry]})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["field"] == "channel_identities"
    assert "\n" not in detail["message"]


def test_a_negative_cap_is_rejected(client: TestClient) -> None:
    response = client.patch("/settings", json={"monthly_cap_micros": -1})

    assert response.status_code == 422


def test_an_empty_update_is_rejected(client: TestClient) -> None:
    response = client.patch("/settings", json={})

    assert response.status_code == 400
    assert response.json()["detail"]["field"] is None


def test_a_partial_update_leaves_other_fields_alone(client: TestClient) -> None:
    client.patch("/settings", json={"provider": "openai", "model": "gpt-5.4"})

    client.patch("/settings", json={"monthly_cap_micros": 500})

    settings = client.get("/settings").json()["settings"]
    assert settings["provider"] == "openai"
    assert settings["model"] == "gpt-5.4"
    assert settings["monthly_cap_micros"] == 500


def test_settings_lists_every_secret_the_sidecar_would_accept(client: TestClient) -> None:
    """The settings screen renders one row per secret, set or not, and must
    not keep its own copy of the names: Rust has one, Python has one, and a
    test already holds those two together. The UI reads this instead."""
    from agentspace.secrets import SECRET_KEYS

    body = client.get("/settings").json()

    assert body["known_secrets"] == sorted(SECRET_KEYS)
    assert set(body["configured_secrets"]) <= set(body["known_secrets"])


# --- provider catalogue ------------------------------------------------------


def test_the_provider_list_reports_which_need_a_key(client: TestClient) -> None:
    providers = {p["name"]: p for p in client.get("/settings/providers").json()["providers"]}

    assert providers["anthropic"]["requires_key"] is True
    assert providers["ollama"]["requires_key"] is False


def test_the_model_list_comes_from_the_price_table_grouped_by_provider(
    client: TestClient,
) -> None:
    """Phase 7's dropdown reads this instead of hardcoding a list that would
    drift from pricing.py.

    Grouped, because a flat list let the editor offer every Anthropic model
    under provider ``openai`` and offered no Ollama model at all: the wildcard
    row is not a selectable model, and Ollama's models are whatever the user has
    pulled, which no table can enumerate.
    """
    body = client.get("/settings/providers").json()
    models = body["models"]

    assert "claude-opus-5" in models["anthropic"]
    assert "gpt-4o" in models["openai"]
    assert "claude-opus-5" not in models["openai"]
    assert models["ollama"] == []
    assert not any(model.endswith("/*") for group in models.values() for model in group)

    providers = {p["name"]: p for p in body["providers"]}
    assert providers["ollama"]["free_text_model"] is True
    assert providers["anthropic"]["free_text_model"] is False


def test_every_supported_provider_has_a_model_group(client: TestClient) -> None:
    """Two lists that must agree, compared rather than trusted: the shape of
    Phase 6's `auto_approve` lesson."""
    body = client.get("/settings/providers").json()

    assert set(body["models"]) == {p["name"] for p in body["providers"]}


def test_both_catalogue_endpoints_are_typed_in_the_schema(client: TestClient) -> None:
    """§5 Phase 7: never hand-write the API types. An endpoint answering an
    untyped ``dict`` has no schema, and the frontend was hand-writing one."""
    paths = client.get("/openapi.json").json()["paths"]

    for path, method in (("/settings/providers", "get"), ("/settings/verify", "post")):
        schema = paths[path][method]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert "$ref" in schema, f"{method.upper()} {path} answers with no response model"


# --- budget ------------------------------------------------------------------


def test_budget_starts_empty(client: TestClient) -> None:
    body = client.get("/budget").json()

    assert body["spent_micros"] == 0
    assert body["cap_micros"] == DEFAULT_MONTHLY_CAP_MICROS
    assert body["percent_used"] == 0
    assert body["spent_display"] == "$0.0000"


def test_budget_reflects_a_changed_cap(client: TestClient) -> None:
    client.patch("/settings", json={"monthly_cap_micros": 1_000_000})

    body = client.get("/budget").json()

    assert body["cap_micros"] == 1_000_000
    assert body["cap_display"] == "$1.0000"


def test_budget_reports_the_current_period(client: TestClient) -> None:
    body: dict[str, Any] = client.get("/budget").json()

    assert len(body["period"]) == 7
    assert body["period"][4] == "-"


# --- the Phase 4 run limits --------------------------------------------------
#
# Found by running the app rather than by reading it: a PATCH carrying
# `max_steps_per_agent` returned `200 OK` with the limit unchanged, because
# `UpdateSettingsRequest` did not declare the field and Pydantic drops unknown
# ones by default. §5 Phase 4 says the limits are "all configurable", and they
# were, but only by writing to SQLite directly, which is not a capability the
# product has.


def test_run_limits_are_settable_over_http(client: TestClient) -> None:
    """§5 Phase 4: "All configurable"."""
    response = client.patch(
        "/settings",
        json={"max_steps_per_agent": 7, "max_agents_per_run": 3, "max_run_seconds": 45},
    )

    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["max_steps_per_agent"] == 7
    assert settings["max_agents_per_run"] == 3
    assert settings["max_run_seconds"] == 45

    # And they survive a round trip, rather than only appearing in the response.
    assert client.get("/settings").json()["settings"]["max_steps_per_agent"] == 7


def test_a_limit_of_zero_is_rejected(client: TestClient) -> None:
    """Zero is not a stricter setting, it is a run that cannot do anything."""
    response = client.patch("/settings", json={"max_steps_per_agent": 0})

    assert response.status_code == 422


def test_an_unknown_setting_is_rejected_rather_than_silently_ignored(
    client: TestClient,
) -> None:
    """The bug above was silent, which is what made it survive.

    A caller that misspells a field, or names one this version does not support
    yet, must not be told the change succeeded. This is the test that would
    have caught it.
    """
    response = client.patch("/settings", json={"max_steps": 7})

    assert response.status_code == 422
    assert "max_steps" in response.text


def test_a_partial_update_leaves_the_other_limits_alone(client: TestClient) -> None:
    client.patch("/settings", json={"max_steps_per_agent": 9, "max_run_seconds": 30})
    client.patch("/settings", json={"max_run_seconds": 60})

    settings = client.get("/settings").json()["settings"]
    assert settings["max_steps_per_agent"] == 9
    assert settings["max_run_seconds"] == 60


def test_every_workspace_setting_can_be_patched() -> None:
    """`UpdateSettingsRequest` must list every field of `WorkspaceSettings`.

    The two models duplicate that list because they differ in bounds and
    optionality, and a duplicated list drifts. It already has, twice: Phase 4's
    run limits were reported by `GET /settings` and dropped by `PATCH`, and
    Phase 6's `auto_approve` was reported and then *rejected* with a 422: the
    workspace's whole approval policy unsettable through the API while every
    test stayed green, because every test set it through the store instead.

    Asserted structurally rather than by patching each field in turn, so a
    field added in Phase 8 is covered by a test written in Phase 6.
    """
    settable = set(UpdateSettingsRequest.model_fields)
    stored = set(WorkspaceSettings.model_fields)

    assert stored - settable == set(), "these settings are readable but not writable"
    assert settable - stored == set(), "these fields are accepted but stored nowhere"


def test_the_approval_policy_can_actually_be_set(client: TestClient) -> None:
    """§5 Phase 6's policy setting, over HTTP, end to end.

    The specific instance of the drift above, kept as its own test because it
    is the one that governs whether a tool call stops to ask.
    """
    response = client.patch("/settings", json={"auto_approve": ["low", "medium"]})

    assert response.status_code == 200
    assert response.json()["settings"]["auto_approve"] == ["low", "medium"]
    assert client.get("/settings").json()["settings"]["auto_approve"] == ["low", "medium"]


def test_the_app_wide_model_follows_the_provider(client: TestClient) -> None:
    """Settings no longer chooses a model, only a provider; the fallback model
    a space without one would inherit moves with the provider so it can
    never name another provider's model. A model sent explicitly still wins."""
    moved = client.patch("/settings", json={"provider": "openai"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["settings"]["model"] == "gpt-5.5"

    explicit = client.patch(
        "/settings", json={"provider": "anthropic", "model": "claude-sonnet-5"}
    )
    assert explicit.json()["settings"]["model"] == "claude-sonnet-5"

    same = client.patch("/settings", json={"provider": "anthropic"})
    assert same.json()["settings"]["model"] == "claude-sonnet-5"


def test_per_tool_answers_can_be_set_and_name_only_real_tools(client: TestClient) -> None:
    """The per-tool map replaces the stored one whole; `ask` is dropped as
    the absence of an answer, and a tool that does not exist is a 400 on
    the field, not a silent no-op."""
    response = client.patch(
        "/settings",
        json={
            "tool_policies": {"write_file": "allow", "run_shell": "deny", "read_file": "ask"}
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["tool_policies"] == {
        "write_file": "allow",
        "run_shell": "deny",
    }

    bad = client.patch("/settings", json={"tool_policies": {"teleport": "allow"}})
    assert bad.status_code == 400
    assert bad.json()["detail"]["field"] == "tool_policies"
    assert "teleport" in bad.json()["detail"]["message"]

    cleared = client.patch("/settings", json={"tool_policies": {}})
    assert cleared.json()["settings"]["tool_policies"] == {}


def test_the_approval_policy_can_be_turned_back_off(client: TestClient) -> None:
    """An empty list is a meaningful value, not an omission.

    `exclude_none` rather than `exclude_unset` is what makes `[]` reach the
    store: a user withdrawing pre-authorization must not be read as "no change
    requested", which would leave the gate silently permissive.
    """
    client.patch("/settings", json={"auto_approve": ["high"]})

    response = client.patch("/settings", json={"auto_approve": []})

    assert response.status_code == 200
    assert response.json()["settings"]["auto_approve"] == []


def test_an_invalid_risk_level_is_rejected(client: TestClient) -> None:
    response = client.patch("/settings", json={"auto_approve": ["catastrophic"]})

    assert response.status_code == 422


def test_a_structured_setting_round_trips_without_a_serialisation_warning(
    tmp_path: Path,
) -> None:
    """`channel_identities` is the first setting whose value is a list of models.

    The first version of `_update_sync` merged with `model_copy(update=...)`,
    which does not validate, so a list of dicts from the API sat in a field
    annotated `list[ChannelIdentity]` until a `model_dump()` round-trip
    coerced it, and Pydantic warned on every settings write. Nothing was lost,
    and a `PydanticSerializationUnexpectedValue` in a sidecar log is
    indistinguishable at a glance from the kind that precedes real data loss.

    Raising on the warning is the assertion: a scalar-only settings model would
    never have surfaced this, so the test has to use the structured one.
    """
    import warnings

    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore

    database = Database(tmp_path / "settings.sqlite3")
    database.connect()
    try:
        store = SettingsStore(database)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            updated = asyncio.run(
                store.update(
                    {
                        "channel_identities": [
                            {
                                "channel": "discord",
                                "external_user_id": "4210",
                                "identity": "owner",
                            }
                        ]
                    }
                )
            )

        # Typed on the way out, not merely accepted on the way in.
        assert updated.channel_identities[0].identity == "owner"
        assert asyncio.run(store.get()).channel_identities[0].external_user_id == "4210"
    finally:
        database.close()


def test_a_duplicate_channel_identity_is_refused_by_the_api(tmp_path: Path) -> None:
    """The allowlist validator has to fire through the endpoint, not only in
    the model: that is the Phase 6 lesson about a rule nobody can reach."""
    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore

    database = Database(tmp_path / "settings.sqlite3")
    database.connect()
    try:
        store = SettingsStore(database)
        entry = {"channel": "discord", "external_user_id": "1", "identity": "owner"}

        with pytest.raises(ValueError, match="appears twice"):
            asyncio.run(
                store.update({"channel_identities": [entry, {**entry, "identity": "x"}]})
            )
    finally:
        database.close()
