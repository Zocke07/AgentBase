"""The CI workflow's structure, asserted rather than trusted to a review.

BUILD_SPEC §5 Phase 9's first requirement is an ordering: "Test job runs before
the build job and gates it... A red test blocks the build job entirely." That
ordering lives in one line of YAML, `needs: test`, and deleting it breaks nothing
visible — the workflow still parses, both jobs still run, every tick is still
green, and installers start being built from code no test has looked at.

The second ordering is inside the build job and fails even more quietly.
`just verify-build` can only say anything once a bundle exists: it launches the
frozen binary and compares the sidecar inside the produced installer against the
freshly built one. Run *before* the build it has nothing to inspect — and its
underlying tests are written to skip when there is nothing built, so moving it
earlier turns a real check into a green no-op. `--require-build-checks` is what
stops that being silent, and this pins the step order that makes it unnecessary.

Both are the shape this project keeps meeting: correct everywhere except where it
is actually consumed, and invisible to an otherwise green suite. So they are
compared here instead of remembered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

#: §3's layout names this path exactly.
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build.yml"
TOOLCHAIN = REPO_ROOT / ".github" / "actions" / "toolchain" / "action.yml"

#: §1 constraint 7: Windows ships, macOS builds from day one to catch breakage.
EXPECTED_PLATFORMS = ["windows-latest", "macos-latest"]


def _load(path: Path) -> dict[str, Any]:
    parsed: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parsed


def _workflow() -> dict[str, Any]:
    return _load(WORKFLOW)


def _job(name: str) -> dict[str, Any]:
    job: dict[str, Any] = _workflow()["jobs"][name]
    return job


def _run_steps(job: dict[str, Any]) -> list[str]:
    """Every shell command the job runs, in order."""
    return [str(step["run"]).strip() for step in job["steps"] if "run" in step]


def _step_index(job: dict[str, Any], fragment: str) -> int:
    """Where a command appears among the job's steps, by substring."""
    for index, command in enumerate(_run_steps(job)):
        if fragment in command:
            return index
    pytest.fail(f"no step running {fragment!r}; the job runs {_run_steps(job)}")


def test_the_workflow_is_where_the_layout_says() -> None:
    assert WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(REPO_ROOT)}"
    assert TOOLCHAIN.is_file(), f"missing {TOOLCHAIN.relative_to(REPO_ROOT)}"


def test_the_build_job_is_gated_on_the_test_job() -> None:
    """§5 Phase 9: a red test blocks the build job entirely.

    This is the assertion the whole module exists for. `needs` is normalized
    because GitHub accepts a bare string or a list and they mean the same thing.
    """
    # `.get`, not `[...]`: a deleted `needs:` should fail with the sentence below
    # rather than a KeyError, because that sentence is what explains the problem.
    needs = _job("build").get("needs") or []
    gates = [needs] if isinstance(needs, str) else list(needs)

    assert "test" in gates, (
        "the build job does not declare `needs: test`, so an installer can be "
        "built from code no test has run against"
    )


def test_the_test_job_gates_nothing_else_by_accident() -> None:
    """The test job must not itself wait on the build, which would deadlock."""
    assert "needs" not in _job("test")


@pytest.mark.parametrize("job_name", ["test", "build"])
def test_both_jobs_run_on_windows_and_macos(job_name: str) -> None:
    """§5 Phase 9: a windows-latest + macos-latest matrix."""
    matrix = _job(job_name)["strategy"]["matrix"]["os"]

    assert sorted(matrix) == sorted(EXPECTED_PLATFORMS), (
        f"the {job_name} job runs on {matrix}, not {EXPECTED_PLATFORMS}"
    )


@pytest.mark.parametrize("job_name", ["test", "build"])
def test_one_platform_failing_still_reports_the_other(job_name: str) -> None:
    """Nothing in this project had ever run on macOS before this phase.

    With `fail-fast` left at its default, the first macOS failure cancels the
    Windows leg and the run shows one answer where two were needed.
    """
    assert _job(job_name)["strategy"]["fail-fast"] is False


def test_the_test_job_runs_the_whole_gate() -> None:
    """`just ci` is lint + typecheck + both suites; CI runs the same recipe.

    Asserted as a recipe name rather than a list of tools on purpose: a workflow
    that inlines `pytest` and `npm test` is a second build system, and it drifts
    from the justfile the moment either grows a step.
    """
    assert _run_steps(_job("test")) == ["just ci"]


def test_the_built_artefacts_are_verified_after_the_build_not_before() -> None:
    """The ordering that turns into a green no-op when it is wrong."""
    build = _job("build")
    built = _step_index(build, "just build-installer")
    verified = _step_index(build, "just verify-build")

    assert built < verified, (
        "`just verify-build` runs before `just build-installer`, so it has no "
        "bundle to inspect — and its tests skip when nothing is built, which "
        "means this reports success while checking nothing"
    )


def test_only_the_windows_installer_is_published() -> None:
    """§5 Phase 9 and §7: macOS is built to catch breakage, never published."""
    uploads = [
        step
        for step in _job("build")["steps"]
        if "upload-artifact" in str(step.get("uses", ""))
    ]

    assert len(uploads) == 1, f"expected exactly one upload step, found {len(uploads)}"
    assert uploads[0]["if"] == "runner.os == 'Windows'"

    # A bundle that silently failed to appear must fail the job, not upload
    # nothing under a green tick.
    assert uploads[0]["with"]["if-no-files-found"] == "error"


def test_the_release_job_only_fires_for_a_version_tag() -> None:
    """Publishing is deliberate. Every other green run still leaves an artefact."""
    release = _workflow()["jobs"]["release"]

    assert "refs/tags/v" in release["if"]
    assert release["needs"] == "build", (
        "the release job must wait on the build job, which waits on the tests"
    )
    assert release["permissions"]["contents"] == "write"


def test_the_workflow_is_read_only_by_default() -> None:
    """Only the job that publishes may write, and it asks for that itself."""
    assert _workflow()["permissions"]["contents"] == "read"


def test_every_action_is_pinned_to_a_major_version() -> None:
    """A floating `@main` makes a build reproduce differently tomorrow."""
    unpinned: list[str] = []
    documents = [_workflow()["jobs"].values(), [_load(TOOLCHAIN)["runs"]]]
    for group in documents:
        for job in group:
            for step in job.get("steps", []):
                uses = step.get("uses")
                if uses is None or uses.startswith("./"):
                    continue
                reference = str(uses).partition("@")[2]
                if not reference or reference in {"main", "master"}:
                    unpinned.append(str(uses))

    assert unpinned == [], f"pin these to a version: {unpinned}"


@pytest.mark.parametrize("job_name", ["test", "build"])
def test_both_jobs_share_one_toolchain_definition(job_name: str) -> None:
    """Six duplicated setup steps are two lists that drift; this repo has form.

    Phase 6's settings models, Phase 8's `SECRET_NAMES` and two others were all
    the same bug: two places that had to agree, and did not.
    """
    uses = [step.get("uses") for step in _job(job_name)["steps"]]

    assert "./.github/actions/toolchain" in uses, (
        f"the {job_name} job does not use the shared toolchain action"
    )
