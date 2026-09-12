"""The CI workflow's structure, asserted rather than trusted to a review.

BUILD_SPEC §5 Phase 9's first requirement is an ordering: "Test job runs before
the build job and gates it... A red test blocks the build job entirely." That
ordering lives in one line of YAML, `needs: test`, and deleting it breaks nothing
visible: the workflow still parses, both jobs still run, every tick is still
green, and installers start being built from code no test has looked at.

The second ordering is inside the build job and fails even more quietly.
`just verify-build` can only say anything once a bundle exists: it launches the
frozen binary and compares the sidecar inside the produced installer against the
freshly built one. Run *before* the build it has nothing to inspect, and its
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
        "bundle to inspect, and its tests skip when nothing is built, which "
        "means this reports success while checking nothing"
    )


def test_the_rust_shell_is_linted_after_the_sidecar_exists() -> None:
    """Counterintuitive, and load-bearing: the lint cannot run before the build.

    `tauri-build`'s build script validates `externalBin` and runs for every cargo
    invocation, clippy included. With no frozen sidecar in `binaries/` it fails
    with "resource path ... doesn't exist" before clippy has linted a line, which
    is how CI run #3 failed on both platforms while passing on a dev machine,
    where a sidecar from the last build is already sitting there.

    So a lint step placed first, which is where anybody would reasonably put it,
    is broken in a way only CI can see. Pinned here so it stays where it works.
    """
    build = _job("build")
    built = _step_index(build, "just build-installer")
    linted = _step_index(build, "just check-tauri")

    assert built < linted, (
        "`just check-tauri` runs before `just build-installer`, so tauri-build "
        "will fail on a missing externalBin before clippy lints anything"
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


def test_every_recipe_ci_runs_works_on_a_clean_clone() -> None:
    """A recipe that only works on a warm dev tree fails only in CI.

    Twice in this phase. `just check-tauri` passed locally because `binaries/`
    still held a sidecar from the last build; `just build-installer` passed
    locally because `node_modules` was already there, and in CI it froze the
    sidecar and then died on npm's "could not determine executable to run".

    Phase 0 already settled the rule for `check` (it depends on `setup` because
    its acceptance criterion is a clean clone), and the build path needs the same
    guarantee. So every recipe the workflow invokes at the top level must either
    depend on `setup` or need no installed dependencies at all.
    """
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")

    # Recipe lines sit at column zero as `name: dep1 dep2`. Assignments (`x := y`)
    # and comments are not recipes.
    direct: dict[str, list[str]] = {}
    for line in justfile.splitlines():
        if not line or line[0].isspace() or line.startswith("#") or ":" not in line:
            continue
        head, _, tail = line.partition(":")
        if "=" in head or tail.startswith("="):
            continue
        direct[head.strip()] = tail.split()

    def depends_on_setup(recipe: str, seen: frozenset[str] = frozenset()) -> bool:
        """Whether `setup` is reachable from `recipe`, at any depth.

        Transitively, because `ci` depends on `check` which depends on `setup` -
        checking only direct dependencies would call that a failure.
        """
        if recipe in seen:
            return False
        for dependency in direct.get(recipe, []):
            if dependency == "setup" or depends_on_setup(dependency, seen | {recipe}):
                return True
        return False

    invoked = {
        command.removeprefix("just").strip()
        for job in _workflow()["jobs"].values()
        for command in _run_steps(job)
        if command.startswith("just ")
    }
    assert invoked, "the workflow runs no `just` recipes, which cannot be right"

    # `check-tauri` is cargo alone (it reads a sidecar an earlier step froze and
    # installs nothing) so it is exempt by inspection rather than by rule.
    for recipe in sorted(invoked - {"check-tauri"}):
        assert recipe in direct, f"{recipe!r} is not a recipe in the justfile"
        assert depends_on_setup(recipe), (
            f"`just {recipe}` never reaches `setup`, so it works only where "
            f"node_modules and .venv already exist, which is every dev machine "
            f"and no CI runner"
        )


def test_the_smoke_job_installs_the_artefact_the_build_job_uploaded() -> None:
    """§5 Phase 9's "second Windows machine", as close as this project can get.

    See CLAUDE.md's "The machine reality": there will be no second Windows
    machine, so a fresh runner stands in for it. Three things make that honest
    rather than cosmetic, and each is pinned here. It must wait on the build, or
    there is nothing to install. It must run on Windows, because the artefact is
    an NSIS installer. And it must install the *downloaded* artefact (the bytes a
    user would get) rather than rebuilding locally, which is what
    `AGENTSPACE_INSTALLER_DIR` pointing at the download directory guarantees.
    """
    smoke = _workflow()["jobs"]["smoke"]

    assert smoke["needs"] == "build"
    assert smoke["runs-on"] == "windows-latest"

    downloads = [s for s in smoke["steps"] if "download-artifact" in str(s.get("uses", ""))]
    assert len(downloads) == 1, "the smoke job must download the build job's artefact"
    assert downloads[0]["with"]["name"] == "AgentSpace-windows-installer"

    runs = [s for s in smoke["steps"] if "just verify-installed" in str(s.get("run", ""))]
    assert len(runs) == 1, "the smoke job must run `just verify-installed`"
    assert "AGENTSPACE_INSTALLER_DIR" in runs[0].get("env", {}), (
        "verify-installed must be pointed at the downloaded artefact, or it falls "
        "back to a local bundle directory that does not exist on the runner"
    )


def test_the_release_job_only_fires_for_a_version_tag() -> None:
    """Publishing is deliberate. Every other green run still leaves an artefact."""
    release = _workflow()["jobs"]["release"]

    assert "refs/tags/v" in release["if"]
    needs = release["needs"]
    gates = [needs] if isinstance(needs, str) else list(needs)
    assert "build" in gates, "the release job must wait on the build job"
    assert "smoke" in gates, (
        "the release job must wait on the smoke job: an installer that built but "
        "did not run on a clean machine is exactly the one that must not ship"
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
