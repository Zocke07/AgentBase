"""`POST /approvals/{id}` and the endpoints the Phase 7 dialog needs.

§3's layout names `api/approvals.py` for one endpoint, and it is the one that
matters: an agent inside a run is suspended on an `asyncio.Future`, and this is
the request that sets it. The two halves live in different requests, which is
why the service is application state rather than something a run owns: a test
here therefore also checks the *wiring*, not only the handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentspace.main import create_app
from agentspace.secrets import SecretStore
from agentspace.store.spaces import DEFAULT_SPACE_ID
from agentspace.tools.approval import ApprovalStatus
from agentspace.tools.catalogue import RiskLevel

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.config import AppPaths


@pytest.fixture
def client(app_paths: AppPaths) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=SecretStore())) as test_client:
        yield test_client


def a_pending_approval(client: TestClient, tool: str = "write_file") -> dict[str, Any]:
    """Create a run and an approval on it, the way a real call would."""
    run = client.post("/runs", json={"goal": "needs approval"}).json()
    service = client.app.state.approvals  # type: ignore[attr-defined]

    # `TestClient` runs the app on a worker thread with a blocking portal; this
    # is how a synchronous test reaches an async method on app state. Asserted
    # rather than narrowed with a cast: a `None` portal means the client is not
    # inside its context manager, which would fail far less legibly later.
    portal = client.portal
    assert portal is not None
    record = portal.call(
        service.store.create, run["id"], tool, {"path": "notes.txt"}, RiskLevel.MEDIUM
    )
    return {"run_id": run["id"], "id": record.id}


# --- wiring -------------------------------------------------------------------


def test_the_application_builds_a_tool_runtime(client: TestClient) -> None:
    """The gate is reachable from a request, not merely importable.

    Every gate test drives `ApprovalService` directly. This is the one that
    fails if `create_app` stops putting it on `app.state`, which would leave
    every one of those tests green while no shipped run could execute a tool.
    """
    state = client.app.state  # type: ignore[attr-defined]

    assert state.approvals is not None
    assert state.tool_runtime is not None
    assert (
        state.tool_runtime.sandbox.root == state.spaces.folder_for(DEFAULT_SPACE_ID).resolve()
    )
    # Directly under `spaces_dir`, not one level deeper. The first live launch
    # moved the workspace to `spaces/spaces/<id>`, because the store was
    # handed the data directory and joined "spaces" onto it a second time.
    assert (
        state.spaces.folder_for(DEFAULT_SPACE_ID) == state.paths.spaces_dir / DEFAULT_SPACE_ID
    )
    assert set(state.tool_runtime.tools) == {
        "read_file",
        "list_dir",
        "write_file",
        "http_get",
        "run_shell",
    }


def test_the_old_workspace_folder_is_adopted_by_the_default_space(
    app_paths: AppPaths, secrets: SecretStore
) -> None:
    """§5 Phase 11's third acceptance criterion, the folder half, through the
    real app: a data directory from before spaces keeps its files."""
    app_paths.legacy_workspace.mkdir(parents=True)
    (app_paths.legacy_workspace / "notes.txt").write_text("kept", encoding="utf-8")

    with TestClient(create_app(app_paths, secrets=secrets)) as client:
        state = client.app.state  # type: ignore[attr-defined]
        folder = state.spaces.folder_for(DEFAULT_SPACE_ID)
        assert folder == app_paths.spaces_dir / DEFAULT_SPACE_ID
        assert (folder / "notes.txt").read_text(encoding="utf-8") == "kept"
        assert not app_paths.legacy_workspace.exists()


def test_the_sandbox_root_is_inside_the_data_directory(client: TestClient) -> None:
    """Not the install directory, and not the repository.

    Every space's folder sits under `AppPaths.spaces_dir`, beside the event
    log in the OS app-data directory, which is the decision CLAUDE.md records
    for the database and which applies for the same reason: an uninstall
    should not be able to take the user's files with it.
    """
    state = client.app.state  # type: ignore[attr-defined]

    assert state.tool_runtime.sandbox.root.is_relative_to(state.paths.data_dir)
    assert state.tool_runtime.sandbox.root.exists()


# --- reading ------------------------------------------------------------------


def test_pending_approvals_are_listed(client: TestClient) -> None:
    """The Phase 7 dialog has to render what is outstanding when it opens.

    A UI relying only on the `approval.requested` event shows nothing to a user
    who opened the window a second too late, and the whole point of the gate
    is that somebody is there to answer it.
    """
    created = a_pending_approval(client)

    body = client.get("/approvals").json()

    assert [item["id"] for item in body] == [created["id"]]
    assert body[0]["tool"] == "write_file"
    assert body[0]["risk"] == "medium"
    assert body[0]["status"] == "pending"


def test_approvals_can_be_filtered_by_run(client: TestClient) -> None:
    first = a_pending_approval(client)
    a_pending_approval(client, tool="run_shell")

    body = client.get("/approvals", params={"run_id": first["run_id"]}).json()

    assert [item["id"] for item in body] == [first["id"]]


def test_one_approval_can_be_fetched(client: TestClient) -> None:
    created = a_pending_approval(client)

    response = client.get(f"/approvals/{created['id']}")

    assert response.status_code == 200
    assert response.json()["args"] == {"path": "notes.txt"}


def test_an_unknown_approval_is_a_404(client: TestClient) -> None:
    assert client.get("/approvals/does-not-exist").status_code == 404


# --- resolving ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("approved", "expected"),
    [(True, ApprovalStatus.APPROVED), (False, ApprovalStatus.DENIED)],
)
def test_an_approval_can_be_allowed_or_denied(
    client: TestClient, approved: bool, expected: ApprovalStatus
) -> None:
    created = a_pending_approval(client)

    response = client.post(f"/approvals/{created['id']}", json={"approved": approved})

    assert response.status_code == 200
    assert response.json()["status"] == str(expected)
    assert response.json()["resolved_at"] is not None
    assert client.get("/approvals").json() == []


def test_resolving_an_unknown_approval_is_a_404(client: TestClient) -> None:
    response = client.post("/approvals/does-not-exist", json={"approved": True})

    assert response.status_code == 404


def test_resolving_twice_is_a_409(client: TestClient) -> None:
    """Two windows showing the same dialog is ordinary.

    The second click has to fail in a way the UI can explain as "somebody
    already answered this" rather than as "that approval is gone", and it must
    not flip a denial into an approval.
    """
    created = a_pending_approval(client)
    client.post(f"/approvals/{created['id']}", json={"approved": False})

    response = client.post(f"/approvals/{created['id']}", json={"approved": True})

    assert response.status_code == 409
    assert "already denied" in response.json()["detail"]
    assert client.get(f"/approvals/{created['id']}").json()["status"] == "denied"


def test_a_misspelled_decision_field_is_rejected(client: TestClient) -> None:
    """`extra="forbid"`, and here the stakes are higher than usual.

    Pydantic's default is to drop an unknown field, so a client sending
    `{"approve": true}` would have `approved` fall back to its default. There
    is no safe default for "did the user say yes", which is why the field is
    required and the typo is a 422 rather than a silent denial, or worse, a
    silent approval.
    """
    created = a_pending_approval(client)

    response = client.post(f"/approvals/{created['id']}", json={"approve": True})

    assert response.status_code == 422
    assert client.get(f"/approvals/{created['id']}").json()["status"] == "pending"


def test_a_decision_is_required(client: TestClient) -> None:
    created = a_pending_approval(client)

    assert client.post(f"/approvals/{created['id']}", json={}).status_code == 422
