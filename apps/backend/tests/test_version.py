"""Release versions that must identify the same build."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, cast

from agentbase import __version__
from agentbase.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def _toml(relative: str) -> dict[str, Any]:
    return tomllib.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


def _json(relative: str) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
    return parsed


def _locked_version(relative: str, package: str) -> str:
    packages = _toml(relative)["package"]
    return cast(str, next(entry["version"] for entry in packages if entry["name"] == package))


def test_every_release_version_identifies_the_same_build() -> None:
    """A partial bump can label APIs, bundles and lockfiles as different releases."""
    desktop_lock = _json("apps/desktop/package-lock.json")
    versions = {
        "Python package": _toml("apps/backend/pyproject.toml")["project"]["version"],
        "Python lock": _locked_version("apps/backend/uv.lock", "agentbase"),
        "Python runtime": __version__,
        "FastAPI": create_app().version,
        "desktop package": _json("apps/desktop/package.json")["version"],
        "desktop lock": desktop_lock["packages"][""]["version"],
        "Rust package": _toml("apps/desktop/src-tauri/Cargo.toml")["package"]["version"],
        "Rust lock": _locked_version("apps/desktop/src-tauri/Cargo.lock", "agentbase-desktop"),
        "Tauri bundle": _json("apps/desktop/src-tauri/tauri.conf.json")["version"],
        "schemas package": _json("packages/schemas/package.json")["version"],
        "schemas lock": desktop_lock["packages"]["../../packages/schemas"]["version"],
        "OpenAPI": _json("packages/schemas/openapi.json")["info"]["version"],
    }

    assert set(versions.values()) == {__version__}, versions
    assert (REPO_ROOT / "docs" / "releases" / f"{__version__}.md").is_file()


def test_macos_release_requests_an_ad_hoc_signature() -> None:
    """Browser downloads need a bundle seal that leaves PyInstaller runnable."""
    tauri = _json("apps/desktop/src-tauri/tauri.conf.json")
    macos = tauri["bundle"]["macOS"]

    assert macos["signingIdentity"] == "-"
    assert macos["hardenedRuntime"] is False
