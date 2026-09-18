"""The schedules API: CRUD, run-now, the preview, and the settings fields the
About box and the first-run tour read."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from agentspace import __version__
from agentspace.main import create_app
from agentspace.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from collections.abc import Iterator

    from agentspace.config import AppPaths
    from agentspace.secrets import SecretStore


@pytest.fixture
def client(app_paths: AppPaths, secrets: SecretStore) -> Iterator[TestClient]:
    with TestClient(create_app(app_paths, secrets=secrets)) as test_client:
        yield test_client


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "space_id": DEFAULT_SPACE_ID,
        "name": "Morning digest",
        "goal": "Summarise what changed in the notes since yesterday.",
        "cadence": {"kind": "weekly", "at": "09:00", "weekdays": [0, 1, 2, 3, 4]},
    }
    body.update(overrides)
    return body


def test_a_schedule_is_created_listed_by_space_and_described(client: TestClient) -> None:
    created = client.post("/schedules", json=_body())
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["summary"] == "Weekdays at 09:00"
    assert schedule["enabled"] is True
    assert schedule["missed"] == "run_on_launch"
    assert schedule["last_run_id"] is None
    next_run = datetime.fromisoformat(schedule["next_run_at"])
    assert next_run > datetime.now(UTC)
    assert next_run.astimezone().strftime("%H:%M") == "09:00"

    assert [entry["id"] for entry in client.get("/schedules").json()] == [schedule["id"]]
    listed = client.get("/schedules", params={"space_id": DEFAULT_SPACE_ID}).json()
    assert [entry["id"] for entry in listed] == [schedule["id"]]
    assert client.get("/schedules", params={"space_id": "elsewhere"}).json() == []
    assert client.get(f"/schedules/{schedule['id']}").json() == schedule
    assert client.get("/schedules/ghost").status_code == 404


def test_refusals_name_the_field(client: TestClient) -> None:
    no_space = client.post("/schedules", json=_body(space_id="ghost"))
    assert no_space.status_code == 400
    assert no_space.json()["detail"] == {
        "message": "no space with id 'ghost'",
        "field": "space_id",
    }

    bad_time = client.post("/schedules", json=_body(cadence={"kind": "daily", "at": "9am"}))
    assert bad_time.status_code == 422
    assert bad_time.json()["detail"][0]["loc"][-1] == "at"

    unknown = client.post("/schedules", json=_body(cadence={"kind": "monthly", "day": 1}))
    assert unknown.status_code == 422

    schedule = client.post("/schedules", json=_body()).json()
    empty = client.patch(f"/schedules/{schedule['id']}", json={})
    assert empty.status_code == 400
    stray = client.patch(f"/schedules/{schedule['id']}", json={"colour": "blue"})
    assert stray.status_code == 422
    assert client.patch("/schedules/ghost", json={"name": "x"}).status_code == 404


def test_editing_recomputes_the_time_and_deleting_removes_it(client: TestClient) -> None:
    schedule = client.post("/schedules", json=_body()).json()

    paused = client.patch(f"/schedules/{schedule['id']}", json={"enabled": False}).json()
    assert paused["enabled"] is False
    assert paused["next_run_at"] is None

    hourly = client.patch(
        f"/schedules/{schedule['id']}",
        json={
            "enabled": True,
            "cadence": {"kind": "interval", "every_hours": 2},
            "missed": "skip",
        },
    ).json()
    assert hourly["summary"] == "Every 2 hours"
    assert hourly["missed"] == "skip"
    assert hourly["next_run_at"] is not None

    assert client.delete(f"/schedules/{schedule['id']}").status_code == 204
    assert client.get(f"/schedules/{schedule['id']}").status_code == 404
    assert client.delete(f"/schedules/{schedule['id']}").status_code == 404


def test_run_now_starts_a_scheduled_run_without_moving_the_next_time(
    client: TestClient,
) -> None:
    schedule = client.post("/schedules", json=_body()).json()

    started = client.post(f"/schedules/{schedule['id']}/run")
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["origin"] == "schedule"
    assert run["origin_ref"] == schedule["id"]
    assert run["space_id"] == DEFAULT_SPACE_ID
    assert run["goal"] == schedule["goal"]

    after = client.get(f"/schedules/{schedule['id']}").json()
    assert after["last_run_id"] == run["id"]
    assert after["last_outcome"] == "Started by hand."
    assert after["next_run_at"] == schedule["next_run_at"]

    assert client.get("/runs").json()[0]["id"] == run["id"]
    assert client.post("/schedules/ghost/run").status_code == 404


def test_run_now_refuses_an_archived_space(client: TestClient) -> None:
    lab = client.post("/spaces", json={"name": "Lab"}).json()
    schedule = client.post("/schedules", json=_body(space_id=lab["id"])).json()
    client.patch(f"/spaces/{lab['id']}", json={"archived": True})
    assert client.post(f"/schedules/{schedule['id']}/run").status_code == 409


def test_the_preview_says_what_a_cadence_means_before_it_is_saved(client: TestClient) -> None:
    preview = client.post(
        "/schedules/preview",
        json={"cadence": {"kind": "weekly", "at": "07:30", "weekdays": [5, 6]}},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["summary"] == "Saturdays and Sundays at 07:30"
    upcoming = [datetime.fromisoformat(stamp) for stamp in body["next"]]
    assert len(upcoming) == 3
    assert upcoming == sorted(upcoming)
    assert all(stamp.astimezone().weekday() in (5, 6) for stamp in upcoming)
    assert all(stamp.astimezone().strftime("%H:%M") == "07:30" for stamp in upcoming)


def test_deleting_a_space_with_schedules_still_works(client: TestClient) -> None:
    lab = client.post("/spaces", json={"name": "Lab"}).json()
    client.post("/schedules", json=_body(space_id=lab["id"]))
    assert client.delete(f"/spaces/{lab['id']}").status_code == 204
    assert client.get("/schedules", params={"space_id": lab["id"]}).json() == []


# --- the settings the window reads beside these ---------------------------------


def test_settings_carry_the_version_and_data_directory(
    client: TestClient, app_paths: AppPaths
) -> None:
    body = client.get("/settings").json()
    assert body["version"] == __version__
    assert body["data_dir"] == str(app_paths.data_dir)


def test_the_tour_flag_starts_false_and_is_patched_like_any_setting(client: TestClient) -> None:
    assert client.get("/settings").json()["settings"]["onboarding_completed"] is False
    updated = client.patch("/settings", json={"onboarding_completed": True})
    assert updated.status_code == 200, updated.text
    assert updated.json()["settings"]["onboarding_completed"] is True
    assert client.get("/settings").json()["settings"]["onboarding_completed"] is True
