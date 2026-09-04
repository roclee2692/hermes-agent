"""Contract tests for the cross-platform-porting optional skill."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "optional-skills"
    / "migration"
    / "cross-platform-porting"
    / "SKILL.md"
)
GUARD_PATH = SKILL_PATH.parent / "scripts" / "workspace_guard.py"
SAFETY_REFERENCE = SKILL_PATH.parent / "references" / "execution-safety.md"


def _verification_plan(repository: Path) -> dict:
    document = {
        "schema_version": "1.1.0",
        "generated_at": "2026-09-04T00:00:00+00:00",
        "repository": str(repository.resolve()),
        "platform": "macos",
        "architecture": "arm64",
        "work_dir": "${PORTABILITY_WORK_DIR}",
        "evidence_dir": "${PORTABILITY_EVIDENCE_DIR}",
        "project_types": ["cmake"],
        "detected_workflows": ["cmake"],
        "required_executables": ["cmake"],
        "tests_available": True,
        "steps": [
            {
                "name": "test",
                "kind": "test",
                "command": ["ctest", "--test-dir", "build"],
                "command_template": ["ctest", "--test-dir", "${BUILD_DIR}"],
                "cwd": str(repository.resolve()),
                "cwd_template": "${REPOSITORY}",
                "log": "test.log",
                "required": True,
                "depends_on": [],
                "environment": {},
                "environment_template": {},
                "timeout_seconds": 600,
            }
        ],
        "blocked_reasons": [],
    }
    identity = {
        "schema_version": document["schema_version"],
        "project_types": document["project_types"],
        "detected_workflows": document["detected_workflows"],
        "required_executables": document["required_executables"],
        "tests_available": document["tests_available"],
        "steps": [
            {
                "name": "test",
                "kind": "test",
                "command_template": ["ctest", "--test-dir", "${BUILD_DIR}"],
                "cwd_template": "${REPOSITORY}",
                "log": "test.log",
                "required": True,
                "depends_on": [],
                "environment_template": {},
                "timeout_seconds": 600,
            }
        ],
        "blocked_reasons": [],
    }
    import hashlib

    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    document["plan_sha256"] = hashlib.sha256(encoded).hexdigest()
    return document


def _frontmatter_and_body() -> tuple[dict, str]:
    content = SKILL_PATH.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    match = re.search(r"\n---\s*\n", content[3:])
    assert match, "frontmatter must close with ---"
    frontmatter = yaml.safe_load(content[3 : match.start() + 3])
    body = content[match.end() + 3 :]
    return frontmatter, body


def test_frontmatter_meets_hardline_standard() -> None:
    frontmatter, _ = _frontmatter_and_body()
    assert frontmatter["name"] == "cross-platform-porting"
    assert len(frontmatter["description"]) <= 60
    assert frontmatter["description"].endswith(".")
    assert frontmatter["version"] == "0.1.2"
    assert not frontmatter["author"].startswith("Hermes Agent")
    assert frontmatter["platforms"] == ["linux", "macos", "windows"]
    assert frontmatter["metadata"]["hermes"]["category"] == "migration"


def test_related_skills_resolve_in_repo() -> None:
    frontmatter, _ = _frontmatter_and_body()
    repository = SKILL_PATH.parents[3]
    for name in frontmatter["metadata"]["hermes"]["related_skills"]:
        matches = list(repository.glob(f"skills/*/{name}/SKILL.md")) + list(
            repository.glob(f"optional-skills/*/{name}/SKILL.md")
        )
        assert matches, f"related skill does not resolve: {name}"


def test_body_has_required_sections_in_order() -> None:
    _, body = _frontmatter_and_body()
    sections = [
        "## When to Use",
        "## Prerequisites",
        "## How to Run",
        "## Quick Reference",
        "## Procedure",
        "## Pitfalls",
        "## Verification",
    ]
    positions = [body.index(section) for section in sections]
    assert positions == sorted(positions)
    assert len(SKILL_PATH.read_text(encoding="utf-8")) <= 100_000


def test_every_procedure_step_has_a_completion_criterion() -> None:
    _, body = _frontmatter_and_body()
    procedure = body.split("## Procedure", 1)[1].split("## Pitfalls", 1)[0]
    steps = re.findall(
        r"^### \d+\..*?(?=^### \d+\.|\Z)", procedure, re.MULTILINE | re.DOTALL
    )
    assert len(steps) == 14
    assert all("**Done when:**" in step for step in steps)


def test_skill_preserves_core_and_permission_boundaries() -> None:
    _, body = _frontmatter_and_body()
    assert "action_required: false" in body
    assert "Stop at HIGH" in body
    assert "user authorization" in body
    assert "Do not copy Scanner" in body
    assert "job conclusion as diagnostic metadata only" in body
    assert "only its summary" in body
    assert "three remote repair iterations" in body
    assert "workspace_guard.py" in body
    assert "NEEDS_RECOVERY" in body
    assert "PAUSED_PROVIDER" in body
    assert SAFETY_REFERENCE.is_file()


def test_skill_uses_the_frozen_cli_contract() -> None:
    _, body = _frontmatter_and_body()
    for command in (
        "portability scan",
        "portability fix",
        "portability verify",
        "portability render-github",
        "portability collect-github",
        "portability aggregate",
    ):
        assert command in body
    for tool in ("`terminal`", "`read_file`", "`search_files`", "`patch`"):
        assert tool in body


def test_skill_requires_evidence_identity_for_tri_platform_status() -> None:
    _, body = _frontmatter_and_body()
    verification = body.split("## Verification", 1)[1]
    for field in ("plan_sha256", "source_revision", "GitHub run head SHA"):
        assert field in verification
    for platform in ("Windows", "macOS", "Linux"):
        assert platform in verification
    assert "TRI_PLATFORM_VERIFIED" in verification


def test_skill_contains_no_machine_local_paths() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    assert "/Users/" not in content
    assert "/home/" not in content
    assert not re.search(r"[A-Z]:\\\\Users", content)


@pytest.fixture
def guard_module():
    spec = importlib.util.spec_from_file_location("workspace_guard", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def bound_session(tmp_path: Path, guard_module, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test User")
    (source / "tracked.txt").write_text("checkpoint\n", encoding="utf-8")
    (source / "scan").write_text(
        "import os, sys\nprint(os.getcwd())\nprint(' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    (source / ".gitignore").write_text("outputs/\n", encoding="utf-8")
    _git(source, "add", "tracked.txt", "scan", ".gitignore")
    _git(source, "commit", "-q", "-m", "checkpoint")

    target = tmp_path / "repair-worktree"
    _git(source, "worktree", "add", "-q", "-b", "repair", str(target))
    harness_repo = tmp_path / "portability-harness"
    harness_repo.mkdir()
    state = tmp_path / "state"
    manifest_path = state / "manifest.json"
    monkeypatch.setattr(
        guard_module,
        "_harness_identity",
        lambda executable, target_repo: {
            "version": "test-harness-0.1.0",
            "sha256": "test-harness-sha256",
        },
    )
    guard_module.create_manifest(
        session_id="phase2-test",
        target_repo=target,
        harness_executable=sys.executable,
        forbidden_write_roots=[source, harness_repo],
        manifest_path=manifest_path,
    )
    return {
        "source": source,
        "target": target,
        "harness_repo": harness_repo,
        "state": state,
        "manifest": manifest_path,
    }


def test_guard_rejects_wrong_cwd(bound_session, guard_module) -> None:
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.guard_manifest(
            bound_session["manifest"], cwd=bound_session["source"]
        )
    assert error.value.code == "WORKSPACE_IDENTITY_MISMATCH"


def test_resume_rebinds_harness_to_manifest_target(
    bound_session, guard_module, monkeypatch
) -> None:
    monkeypatch.chdir(bound_session["source"])
    resumed = guard_module.resume_session(bound_session["manifest"])
    assert resumed["required_workdir"] == str(bound_session["target"].resolve())

    output_dir = bound_session["state"] / "scan-output"
    result = guard_module.run_bound_harness(
        bound_session["manifest"],
        ["scan", ".", "--output-dir", str(output_dir)],
    )
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == str(bound_session["target"].resolve())


def test_forbidden_repo_and_symlink_escape_are_rejected(
    bound_session, guard_module
) -> None:
    forbidden_file = bound_session["harness_repo"] / "fixture.py"
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.guard_manifest(
            bound_session["manifest"],
            cwd=bound_session["target"],
            write_paths=[forbidden_file],
        )
    assert error.value.code == "WRITE_INSIDE_FORBIDDEN_ROOT"

    link = bound_session["target"] / "escaped"
    try:
        link.symlink_to(bound_session["harness_repo"], target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this host: {exc}")
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.guard_manifest(
            bound_session["manifest"],
            cwd=bound_session["target"],
            write_paths=[link / "fixture.py"],
        )
    assert error.value.code == "WRITE_INSIDE_FORBIDDEN_ROOT"


def test_bound_harness_refuses_another_repository(bound_session, guard_module) -> None:
    _, manifest = guard_module.load_manifest(bound_session["manifest"])
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.validate_harness_arguments(
            manifest,
            [
                "scan",
                str(bound_session["harness_repo"]),
                "--output-dir",
                str(bound_session["state"] / "scan-output"),
            ],
        )
    assert error.value.code == "HARNESS_TARGET_MISMATCH"


def test_provider_interruption_requires_checkpoint_recovery(
    bound_session, guard_module
) -> None:
    target = bound_session["target"]
    guard_module.begin_attempt(
        bound_session["manifest"], cwd=target, capability="gpu.acceleration"
    )
    (target / "tracked.txt").write_text("partial patch\n", encoding="utf-8")
    (target / "new-file.txt").write_text("partial\n", encoding="utf-8")

    interrupted = guard_module.mark_interrupted(
        bound_session["manifest"], reason="provider 429", provider_error=True
    )
    assert interrupted["state"] == "NEEDS_RECOVERY"
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.resume_session(bound_session["manifest"])
    assert error.value.code == "NEEDS_RECOVERY"

    recovered = guard_module.recover_checkpoint(
        bound_session["manifest"], discard_current_attempt=True
    )
    assert recovered["state"] == "ACTIVE"
    assert (target / "tracked.txt").read_text(encoding="utf-8") == "checkpoint\n"
    assert not (target / "new-file.txt").exists()
    assert _git(target, "status", "--porcelain") == ""


def test_second_provider_failure_pauses_the_session(
    bound_session, guard_module
) -> None:
    manifest = bound_session["manifest"]
    target = bound_session["target"]
    guard_module.begin_attempt(manifest, cwd=target, capability="gpu.acceleration")
    first = guard_module.mark_interrupted(
        manifest, reason="provider 429", provider_error=True
    )
    assert first["state"] == "INTERRUPTED"
    guard_module.resume_session(manifest)

    second = guard_module.mark_interrupted(
        manifest, reason="provider 429 again", provider_error=True
    )
    assert second["state"] == "PAUSED_PROVIDER"
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.resume_session(manifest)
    assert error.value.code == "PAUSED_PROVIDER"


def test_non_provider_signal_cannot_consume_provider_retry(
    bound_session, guard_module
) -> None:
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.mark_interrupted(
            bound_session["manifest"],
            reason="process terminated externally by SIGTERM",
            provider_error=True,
        )
    assert error.value.code == "PROVIDER_ERROR_UNVERIFIED"
    _, saved = guard_module.load_manifest(bound_session["manifest"])
    assert saved["provider_retries"] == 0


def test_recovery_removes_only_ignored_files_created_during_attempt(
    bound_session, guard_module
) -> None:
    target = bound_session["target"]
    output = target / "outputs"
    output.mkdir()
    preserved = output / "preexisting.bin"
    preserved.write_bytes(b"keep")
    guard_module.begin_attempt(
        bound_session["manifest"], cwd=target, capability="gpu.acceleration"
    )
    generated = output / "generated.bin"
    generated.write_bytes(b"discard")

    interrupted = guard_module.mark_interrupted(
        bound_session["manifest"],
        reason="focused test process interrupted",
        provider_error=False,
    )
    assert interrupted["state"] == "NEEDS_RECOVERY"
    assert interrupted["new_ignored_paths"] == ["outputs/generated.bin"]
    recovered = guard_module.recover_checkpoint(
        bound_session["manifest"], discard_current_attempt=True
    )
    assert recovered["discarded_ignored_paths"] == ["outputs/generated.bin"]
    assert preserved.read_bytes() == b"keep"
    assert not generated.exists()


def test_semantic_repair_attempts_stop_after_three(bound_session, guard_module) -> None:
    manifest = bound_session["manifest"]
    target = bound_session["target"]
    for _ in range(3):
        guard_module.begin_attempt(manifest, cwd=target, capability="gpu.acceleration")
        guard_module.checkpoint_session(manifest, cwd=target)

    with pytest.raises(guard_module.GuardError) as error:
        guard_module.begin_attempt(manifest, cwd=target, capability="gpu.acceleration")
    assert error.value.code == "REPAIR_ATTEMPT_LIMIT"
    _, saved = guard_module.load_manifest(manifest)
    assert saved["state"] == "BLOCKED"


def test_focused_runner_accepts_only_test_entrypoints(
    bound_session, guard_module
) -> None:
    target = bound_session["target"]
    guard_module.begin_attempt(
        bound_session["manifest"], cwd=target, capability="gpu.acceleration"
    )
    tests = target / "tests"
    tests.mkdir()
    test_file = tests / "test_smoke.py"
    test_file.write_text("print('focused-pass')\n", encoding="utf-8")

    result = guard_module.run_focused_command(
        bound_session["manifest"],
        [sys.executable, str(test_file)],
        cwd=target,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "focused-pass"
    _, saved = guard_module.load_manifest(bound_session["manifest"])
    assert saved["focused_commands"][-1]["status"] == "passed"


@pytest.mark.parametrize(
    "arguments",
    [
        [sys.executable, "-m", "pip", "install", "example"],
        [sys.executable, "CNN_B.py"],
        [sys.executable, "-c", "print('not bounded')"],
    ],
)
def test_focused_runner_rejects_installers_and_application_code(
    bound_session, guard_module, arguments
) -> None:
    target = bound_session["target"]
    guard_module.begin_attempt(
        bound_session["manifest"], cwd=target, capability="gpu.acceleration"
    )
    (target / "CNN_B.py").write_text("print('training')\n", encoding="utf-8")
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.run_focused_command(
            bound_session["manifest"], arguments, cwd=target
        )
    assert error.value.code == "FOCUSED_COMMAND_REJECTED"


def test_final_report_requires_matching_repository_and_revision(
    bound_session, guard_module
) -> None:
    target = bound_session["target"]
    summary = bound_session["state"] / "summary.json"
    payload = {
        "repository": str(target.resolve()),
        "source_revision": "not-the-current-revision",
        "source_dirty": False,
        "plan_sha256": _verification_plan(target)["plan_sha256"],
        "verification_level": "LOCAL_VERIFIED",
    }
    summary.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(guard_module.GuardError) as error:
        guard_module.validate_final_evidence(
            bound_session["manifest"], cwd=target, summary_path=summary
        )
    assert error.value.code == "EVIDENCE_SOURCE_MISMATCH"

    payload["source_revision"] = _git(target, "rev-parse", "HEAD")
    summary.write_text(json.dumps(payload), encoding="utf-8")
    plan = bound_session["state"] / "plan.json"
    plan.write_text(json.dumps(_verification_plan(target)), encoding="utf-8")
    result = guard_module.validate_final_evidence(
        bound_session["manifest"],
        cwd=target,
        summary_path=summary,
        plan_path=plan,
    )
    assert result["target_repo"] == str(target.resolve())
    assert result["verification"] == "LOCAL_VERIFIED"
    assert result["state"] == "COMPLETE"


def test_tri_platform_aggregate_binds_all_evidence_to_target_head(
    bound_session, guard_module
) -> None:
    target = bound_session["target"]
    state = bound_session["state"]
    revision = _git(target, "rev-parse", "HEAD")
    plan_document = _verification_plan(target)
    plan_hash = plan_document["plan_sha256"]
    plan = state / "plan.json"
    plan.write_text(json.dumps(plan_document), encoding="utf-8")
    evidence = []
    for platform in ("windows", "macos", "linux"):
        summary = state / f"{platform}-summary.json"
        summary.write_text(
            json.dumps({
                "platform": platform,
                "source_revision": revision,
                "source_dirty": False,
                "plan_sha256": plan_hash,
                "verification_level": "LOCAL_VERIFIED",
            }),
            encoding="utf-8",
        )
        evidence.append({
            "summary": str(summary),
            "valid": True,
            "platform": platform,
            "source_revision": revision,
            "source_dirty": False,
            "plan_sha256": plan_hash,
            "status": "passed",
            "mandatory": {"passed": 3, "total": 3},
        })
    aggregate = state / "aggregate.json"
    aggregate.write_text(
        json.dumps({
            "verification": "TRI_PLATFORM_VERIFIED",
            "source_revision": revision,
            "plan_sha256": plan_hash,
            "platforms": {
                "windows": "passed",
                "macos": "passed",
                "linux": "passed",
            },
            "evidence_count": 3,
            "evidence": evidence,
        }),
        encoding="utf-8",
    )
    result = guard_module.validate_final_evidence(
        bound_session["manifest"],
        cwd=target,
        aggregate_path=aggregate,
        plan_path=plan,
    )
    assert result["verification"] == "TRI_PLATFORM_VERIFIED"
    assert result["source_revision"] == revision


def test_tri_platform_aggregate_rejects_tampered_inner_summary(
    bound_session, guard_module
) -> None:
    target = bound_session["target"]
    state = bound_session["state"]
    revision = _git(target, "rev-parse", "HEAD")
    plan_document = _verification_plan(target)
    plan_hash = plan_document["plan_sha256"]
    plan = state / "plan.json"
    plan.write_text(json.dumps(plan_document), encoding="utf-8")
    evidence = []
    for platform in ("windows", "macos", "linux"):
        summary = state / f"{platform}-summary.json"
        summary.write_text(
            json.dumps({
                "platform": platform,
                "source_revision": "wrong" if platform == "windows" else revision,
                "source_dirty": False,
                "plan_sha256": plan_hash,
            }),
            encoding="utf-8",
        )
        evidence.append({
            "summary": str(summary),
            "valid": True,
            "platform": platform,
            "source_revision": revision,
            "source_dirty": False,
            "plan_sha256": plan_hash,
            "status": "passed",
            "mandatory": {"passed": 3, "total": 3},
        })
    aggregate = state / "aggregate.json"
    aggregate.write_text(
        json.dumps({
            "verification": "TRI_PLATFORM_VERIFIED",
            "source_revision": revision,
            "plan_sha256": plan_hash,
            "platforms": {
                "windows": "passed",
                "macos": "passed",
                "linux": "passed",
            },
            "evidence_count": 3,
            "evidence": evidence,
        }),
        encoding="utf-8",
    )

    with pytest.raises(guard_module.GuardError) as error:
        guard_module.validate_final_evidence(
            bound_session["manifest"],
            cwd=target,
            aggregate_path=aggregate,
            plan_path=plan,
        )
    assert error.value.code == "AGGREGATE_SOURCE_MISMATCH"
