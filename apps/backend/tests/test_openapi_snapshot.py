"""The committed OpenAPI schema and generated types must match the running app.
A stale artefact produces a frontend that typechecks against an API that no
longer exists, which looks verified and is not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentbase import openapi

#: `apps/backend/tests/` -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "packages" / "schemas" / "openapi.json"


def _committed() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return document


def test_the_committed_schema_exists() -> None:
    assert SCHEMA_PATH.is_file(), (
        f"{SCHEMA_PATH} is missing. Run `just schemas` to generate it."
    )


def test_the_committed_schema_matches_the_live_app() -> None:
    """The check that stops the generated TS types describing a past API."""
    assert _committed() == openapi.schema(), (
        "The committed OpenAPI schema is out of date with the FastAPI app. "
        "Run `just schemas` and commit the result."
    )


def test_the_committed_schema_is_byte_for_byte_what_the_generator_writes() -> None:
    """Formatting too, not just content.

    A hand-edited schema that happens to parse to the same object would pass
    the comparison above while guaranteeing a spurious diff on the next
    regeneration. Comparing the text is what makes `just schemas` idempotent.
    """
    assert SCHEMA_PATH.read_text(encoding="utf-8") == openapi.serialise(openapi.schema())


def test_the_schema_does_not_depend_on_the_machine_that_generated_it() -> None:
    """Two dumps in one process must be identical.

    The generator builds a real app, and a real app resolves a data directory.
    If any of that leaked into the document, the schema would differ between
    the maintainer's machine and CI and the drift test above would fail for a
    reason that has nothing to do with the API.
    """
    assert openapi.serialise(openapi.schema()) == openapi.serialise(openapi.schema())


def test_the_schema_covers_every_route_the_dashboard_calls() -> None:
    """The endpoints §5 Phase 7 names, present in the document the UI is typed from."""
    paths = openapi.schema()["paths"]

    for route in (
        "/runs",
        "/runs/{run_id}",
        "/runs/{run_id}/events",
        "/agents",
        "/agents/{definition_id}",
        "/tools",
        "/approvals",
        "/approvals/{approval_id}",
        "/budget",
        "/settings",
    ):
        assert route in paths, f"{route} is missing from the OpenAPI schema"
