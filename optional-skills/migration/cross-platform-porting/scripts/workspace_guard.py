#!/usr/bin/env python3
"""Bind a portability repair session to one Git worktree.

The guard deliberately lives beside the skill instead of in Hermes or
portability-harness core.  It makes repository identity persistent across
model turns and fails closed before source mutation, Harness execution,
recovery, or evidence-based completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "1.0.0"
MAX_REPAIR_ATTEMPTS = 3
MAX_PROVIDER_RETRIES = 1
MUTABLE_STATES = {"ACTIVE"}
RECOVERY_STATES = {"NEEDS_RECOVERY", "PAUSED_PROVIDER"}
TERMINAL_STATES = {"BLOCKED", "COMPLETE"}
HARNESS_COMMANDS = {
    "scan",
    "fix",
    "verify",
    "render-github",
    "collect-github",
    "aggregate",
}


class GuardError(RuntimeError):
    """A stable fail-closed result suitable for machine handling."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise GuardError("COMMAND_FAILED", f"{' '.join(command)}: {message}")
    return result


def _git(repo: Path, *arguments: str) -> str:
    return _run(["git", *arguments], cwd=repo).stdout.strip()


def _canonical_existing(path: str | Path, *, label: str) -> Path:
    try:
        return Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GuardError("PATH_UNAVAILABLE", f"{label}: {path}: {exc}") from exc


def _canonical_candidate(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise GuardError("WRITE_PATH_NOT_ABSOLUTE", str(path))
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise GuardError("WRITE_PATH_UNRESOLVED", f"{path}: {exc}") from exc


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def repository_identity(repo: str | Path) -> dict[str, Any]:
    requested = _canonical_existing(repo, label="repository")
    top = _canonical_existing(
        _git(requested, "rev-parse", "--show-toplevel"), label="git top-level"
    )
    git_dir = _canonical_existing(
        _git(top, "rev-parse", "--absolute-git-dir"), label="git dir"
    )
    common_value = _git(top, "rev-parse", "--git-common-dir")
    common_path = Path(common_value)
    if not common_path.is_absolute():
        common_path = top / common_path
    common_dir = _canonical_existing(common_path, label="git common dir")
    head = _git(top, "rev-parse", "HEAD")
    return {
        "target_repo": str(top),
        "target_git_dir": str(git_dir),
        "git_common_dir": str(common_dir),
        "head_revision": head,
        "dedicated_worktree": git_dir != common_dir,
    }


def _status_paths(repo: Path) -> list[str]:
    output = _run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo,
    ).stdout
    paths: list[str] = []
    records = output.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status = record[:2]
        path = record[3:]
        if status[0] in {"R", "C"} and index < len(records):
            path = records[index]
            index += 1
        paths.append(path)
    return sorted(set(paths))


def _harness_identity(executable: Path, target_repo: Path) -> dict[str, str]:
    help_result = _run([str(executable), "--help"], cwd=target_repo)
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    missing = sorted(
        command for command in HARNESS_COMMANDS if command not in help_text
    )
    if missing:
        raise GuardError("HARNESS_CONTRACT_MISMATCH", ", ".join(missing))

    python_candidates = [
        executable.parent / "python",
        executable.parent / "python3",
        executable.parent / "python.exe",
    ]
    version: str | None = None
    for python in python_candidates:
        if not python.is_file():
            continue
        result = _run(
            [
                str(python),
                "-c",
                "from importlib.metadata import version; print(version('portability-harness'))",
            ],
            cwd=target_repo,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            version = result.stdout.strip()
            break
    if version is None:
        raise GuardError("HARNESS_VERSION_UNAVAILABLE", str(executable))

    digest = hashlib.sha256()
    with executable.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"version": version, "sha256": digest.hexdigest()}


def _default_manifest_path(session_id: str) -> Path:
    try:
        from hermes_constants import get_hermes_home
    except ImportError as exc:
        configured = os.environ.get("HERMES_HOME")
        if not configured:
            raise GuardError(
                "HERMES_HOME_UNAVAILABLE",
                "pass --manifest or run inside Hermes with a profile-scoped home",
            ) from exc
        home = Path(configured).expanduser().resolve(strict=False)
    else:
        home = get_hermes_home()
    return home / "portability-sessions" / session_id / "manifest.json"


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = _utc_now()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass


def load_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = _canonical_existing(path, label="session manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError("MANIFEST_INVALID", f"{manifest_path}: {exc}") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise GuardError(
            "MANIFEST_SCHEMA_MISMATCH", str(manifest.get("schema_version"))
        )
    return manifest_path, manifest


def create_manifest(
    *,
    session_id: str,
    target_repo: str | Path,
    harness_executable: str | Path,
    allowed_write_roots: Sequence[str | Path] = (),
    forbidden_write_roots: Sequence[str | Path] = (),
    manifest_path: str | Path | None = None,
    require_worktree: bool = True,
) -> tuple[Path, dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", session_id):
        raise GuardError("SESSION_ID_INVALID", session_id)
    identity = repository_identity(target_repo)
    target = Path(identity["target_repo"])
    if require_worktree and not identity["dedicated_worktree"]:
        raise GuardError(
            "DEDICATED_WORKTREE_REQUIRED",
            "MEDIUM/HIGH repair sessions must bind to a linked Git worktree",
        )

    harness = _canonical_existing(harness_executable, label="Harness executable")
    if not harness.is_file() or not os.access(harness, os.X_OK):
        raise GuardError("HARNESS_NOT_EXECUTABLE", str(harness))

    allowed_values = allowed_write_roots or (target,)
    allowed = [
        _canonical_existing(value, label="allowed write root")
        for value in allowed_values
    ]
    forbidden = [
        _canonical_existing(value, label="forbidden write root")
        for value in forbidden_write_roots
    ]
    for root in allowed:
        if not _is_within(root, target):
            raise GuardError(
                "ALLOWED_ROOT_OUTSIDE_TARGET", f"{root} is outside {target}"
            )
        if any(
            _is_within(root, blocked) or _is_within(blocked, root)
            for blocked in forbidden
        ):
            raise GuardError("WRITE_ROOT_CONFLICT", str(root))

    path = (
        Path(manifest_path).expanduser().resolve(strict=False)
        if manifest_path is not None
        else _default_manifest_path(session_id)
    )
    if any(_is_within(path, root) for root in [*allowed, *forbidden]):
        raise GuardError(
            "MANIFEST_ROOT_CONFLICT",
            "the manifest must live outside source and forbidden repositories",
        )
    harness_identity = _harness_identity(harness, target)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "state": "ACTIVE",
        "target_repo": str(target),
        "target_git_dir": identity["target_git_dir"],
        "git_common_dir": identity["git_common_dir"],
        "base_revision": identity["head_revision"],
        "last_known_good": identity["head_revision"],
        "harness_executable": str(harness),
        "harness_version": harness_identity["version"],
        "harness_sha256": harness_identity["sha256"],
        "allowed_write_roots": [str(root) for root in allowed],
        "forbidden_write_roots": [str(root) for root in forbidden],
        "artifact_root": str(path.parent),
        "dedicated_worktree": identity["dedicated_worktree"],
        "repair_attempts": 0,
        "provider_retries": 0,
        "current_attempt": None,
        "interruptions": [],
        "recoveries": [],
        "created_at": _utc_now(),
    }
    _write_manifest(path, manifest)
    return path, manifest


def validate_workspace(
    manifest: dict[str, Any],
    *,
    cwd: str | Path | None,
    write_paths: Sequence[str | Path] = (),
) -> dict[str, Any]:
    target = Path(manifest["target_repo"])
    identity = repository_identity(target)
    for key in ("target_repo", "target_git_dir", "git_common_dir"):
        if identity[key] != manifest[key]:
            raise GuardError(
                "WORKSPACE_IDENTITY_MISMATCH",
                f"{key}: expected {manifest[key]}, found {identity[key]}",
            )

    harness = _canonical_existing(
        manifest["harness_executable"], label="Harness executable"
    )
    if str(harness) != manifest["harness_executable"]:
        raise GuardError("HARNESS_IDENTITY_MISMATCH", str(harness))
    harness_identity = _harness_identity(harness, target)
    version = harness_identity["version"]
    if version != manifest["harness_version"]:
        raise GuardError(
            "HARNESS_VERSION_MISMATCH",
            f"expected {manifest['harness_version']}, found {version}",
        )
    if harness_identity["sha256"] != manifest["harness_sha256"]:
        raise GuardError(
            "HARNESS_IDENTITY_MISMATCH",
            f"SHA-256 changed for {harness}",
        )

    if cwd is not None:
        try:
            current = repository_identity(cwd)
        except GuardError as exc:
            raise GuardError(
                "WORKSPACE_IDENTITY_MISMATCH", f"cwd is not the bound repository: {cwd}"
            ) from exc
        if current["target_repo"] != manifest["target_repo"]:
            raise GuardError(
                "WORKSPACE_IDENTITY_MISMATCH",
                f"cwd is {current['target_repo']}, target is {manifest['target_repo']}",
            )

    allowed = [Path(value) for value in manifest["allowed_write_roots"]]
    forbidden = [Path(value) for value in manifest["forbidden_write_roots"]]
    guarded: list[str] = []
    for value in write_paths:
        resolved = _canonical_candidate(value)
        if any(_is_within(resolved, root) for root in forbidden):
            raise GuardError("WRITE_INSIDE_FORBIDDEN_ROOT", str(resolved))
        if not any(_is_within(resolved, root) for root in allowed):
            raise GuardError("WRITE_OUTSIDE_ALLOWED_ROOT", str(resolved))
        guarded.append(str(resolved))

    return {
        **identity,
        "harness_executable": str(harness),
        "harness_version": version,
        "write_paths": guarded,
        "dirty_paths": _status_paths(target),
    }


def _argument_path(value: str, *, target: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = target / candidate
    return candidate.resolve(strict=False)


def _option_values(arguments: Sequence[str], name: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == name:
            if index + 1 >= len(arguments):
                raise GuardError("HARNESS_ARGUMENT_INVALID", f"{name} needs a value")
            values.append(arguments[index + 1])
            index += 2
            continue
        prefix = f"{name}="
        if token.startswith(prefix):
            values.append(token[len(prefix) :])
        index += 1
    return values


def validate_harness_arguments(
    manifest: dict[str, Any], arguments: Sequence[str]
) -> None:
    if not arguments or arguments[0] not in HARNESS_COMMANDS:
        raise GuardError(
            "HARNESS_COMMAND_NOT_ALLOWED", arguments[0] if arguments else "<missing>"
        )

    command = arguments[0]
    target = Path(manifest["target_repo"])
    artifact_root = Path(manifest["artifact_root"])
    allowed = [Path(value) for value in manifest["allowed_write_roots"]]
    forbidden = [Path(value) for value in manifest["forbidden_write_roots"]]

    def checked(value: str, roots: Sequence[Path], code: str) -> Path:
        resolved = _argument_path(value, target=target)
        if any(_is_within(resolved, blocked) for blocked in forbidden):
            raise GuardError("HARNESS_FORBIDDEN_PATH", str(resolved))
        if not any(_is_within(resolved, root) for root in roots):
            raise GuardError(code, str(resolved))
        return resolved

    if command in {"scan", "fix", "verify"}:
        if len(arguments) < 2 or arguments[1].startswith("-"):
            raise GuardError("HARNESS_TARGET_REQUIRED", command)
        resolved_target = _argument_path(arguments[1], target=target)
        if resolved_target != target:
            raise GuardError("HARNESS_TARGET_MISMATCH", str(resolved_target))

    if command in {"scan", "verify", "collect-github"}:
        output_dirs = _option_values(arguments, "--output-dir")
        if len(output_dirs) != 1:
            raise GuardError("HARNESS_ARTIFACT_ROOT_REQUIRED", command)
        checked(output_dirs[0], [artifact_root], "HARNESS_ARTIFACT_ROOT_MISMATCH")

    for value in _option_values(arguments, "--work-dir"):
        checked(value, [artifact_root], "HARNESS_WORK_ROOT_MISMATCH")
    for value in _option_values(arguments, "--plan"):
        checked(value, [artifact_root, *allowed], "HARNESS_PLAN_ROOT_MISMATCH")
    for value in _option_values(arguments, "--report"):
        checked(value, [artifact_root], "HARNESS_REPORT_ROOT_MISMATCH")

    if command == "render-github":
        if len(arguments) < 2 or arguments[1].startswith("-"):
            raise GuardError("HARNESS_PLAN_REQUIRED", command)
        checked(arguments[1], [artifact_root, *allowed], "HARNESS_PLAN_ROOT_MISMATCH")
        for value in _option_values(arguments, "--output"):
            checked(
                value,
                [artifact_root, *allowed],
                "HARNESS_OUTPUT_ROOT_MISMATCH",
            )

    if command == "aggregate":
        if len(arguments) < 2 or arguments[1].startswith("-"):
            raise GuardError("HARNESS_EVIDENCE_REQUIRED", command)
        checked(arguments[1], [artifact_root], "HARNESS_EVIDENCE_ROOT_MISMATCH")
        outputs = _option_values(arguments, "--output")
        if len(outputs) != 1:
            raise GuardError("HARNESS_ARTIFACT_ROOT_REQUIRED", command)
        checked(outputs[0], [artifact_root], "HARNESS_ARTIFACT_ROOT_MISMATCH")


def guard_manifest(
    manifest_path: str | Path,
    *,
    cwd: str | Path,
    write_paths: Sequence[str | Path] = (),
) -> dict[str, Any]:
    _, manifest = load_manifest(manifest_path)
    if manifest["state"] not in MUTABLE_STATES:
        raise GuardError("SESSION_NOT_MUTABLE", manifest["state"])
    return validate_workspace(manifest, cwd=cwd, write_paths=write_paths)


def resume_session(manifest_path: str | Path) -> dict[str, Any]:
    path, manifest = load_manifest(manifest_path)
    identity = validate_workspace(manifest, cwd=None)
    state = manifest["state"]
    if state in {"NEEDS_RECOVERY", "PAUSED_PROVIDER"}:
        raise GuardError(state, "recover the checkpoint before another mutation")
    if state in TERMINAL_STATES:
        raise GuardError("SESSION_TERMINAL", state)
    if state == "INTERRUPTED":
        manifest["state"] = "ACTIVE"
        _write_manifest(path, manifest)
    return {
        "target_repo": manifest["target_repo"],
        "required_workdir": manifest["target_repo"],
        "harness_executable": manifest["harness_executable"],
        "state": manifest["state"],
        "head_revision": identity["head_revision"],
        "dirty_paths": identity["dirty_paths"],
    }


def begin_attempt(
    manifest_path: str | Path,
    *,
    cwd: str | Path,
    capability: str,
) -> dict[str, Any]:
    path, manifest = load_manifest(manifest_path)
    identity = validate_workspace(manifest, cwd=cwd)
    if manifest["state"] not in MUTABLE_STATES:
        raise GuardError("SESSION_NOT_MUTABLE", manifest["state"])
    if identity["dirty_paths"]:
        raise GuardError("CHECKPOINT_NOT_CLEAN", ", ".join(identity["dirty_paths"]))
    attempts = int(manifest["repair_attempts"]) + 1
    if attempts > MAX_REPAIR_ATTEMPTS:
        manifest["state"] = "BLOCKED"
        _write_manifest(path, manifest)
        raise GuardError("REPAIR_ATTEMPT_LIMIT", str(MAX_REPAIR_ATTEMPTS))
    manifest["repair_attempts"] = attempts
    manifest["current_attempt"] = {
        "number": attempts,
        "capability": capability,
        "checkpoint_revision": identity["head_revision"],
        "started_at": _utc_now(),
    }
    _write_manifest(path, manifest)
    return manifest["current_attempt"]


def mark_interrupted(
    manifest_path: str | Path,
    *,
    reason: str,
    provider_error: bool,
) -> dict[str, Any]:
    path, manifest = load_manifest(manifest_path)
    identity = validate_workspace(manifest, cwd=None)
    if manifest["state"] in TERMINAL_STATES:
        raise GuardError("SESSION_TERMINAL", manifest["state"])
    if provider_error:
        manifest["provider_retries"] = int(manifest["provider_retries"]) + 1
    dirty_paths = identity["dirty_paths"]
    if provider_error and manifest["provider_retries"] > MAX_PROVIDER_RETRIES:
        state = "PAUSED_PROVIDER"
    elif dirty_paths:
        state = "NEEDS_RECOVERY"
    else:
        state = "INTERRUPTED"
    record = {
        "at": _utc_now(),
        "reason": reason,
        "provider_error": provider_error,
        "dirty_paths": dirty_paths,
        "state": state,
    }
    manifest["interruptions"].append(record)
    manifest["state"] = state
    _write_manifest(path, manifest)
    return record


def recover_checkpoint(
    manifest_path: str | Path,
    *,
    discard_current_attempt: bool,
) -> dict[str, Any]:
    if not discard_current_attempt:
        raise GuardError(
            "RECOVERY_CONFIRMATION_REQUIRED", "pass --discard-current-attempt"
        )
    path, manifest = load_manifest(manifest_path)
    identity = validate_workspace(manifest, cwd=None)
    if manifest["state"] not in RECOVERY_STATES:
        raise GuardError("RECOVERY_NOT_REQUIRED", manifest["state"])
    if not manifest["dedicated_worktree"]:
        raise GuardError("RECOVERY_REQUIRES_WORKTREE", manifest["target_repo"])

    attempt = manifest.get("current_attempt") or {}
    checkpoint = attempt.get("checkpoint_revision") or manifest["last_known_good"]
    if identity["head_revision"] != checkpoint:
        raise GuardError(
            "CHECKPOINT_HEAD_MOVED",
            f"expected HEAD {checkpoint}, found {identity['head_revision']}",
        )
    target = Path(manifest["target_repo"])
    before = identity["dirty_paths"]
    _run(
        ["git", "restore", "--source", checkpoint, "--staged", "--worktree", "--", "."],
        cwd=target,
    )
    clean_result = _run(["git", "clean", "-fd"], cwd=target)
    remaining = _status_paths(target)
    if remaining:
        raise GuardError("RECOVERY_INCOMPLETE", ", ".join(remaining))

    next_state = (
        "PAUSED_PROVIDER"
        if int(manifest["provider_retries"]) > MAX_PROVIDER_RETRIES
        else "ACTIVE"
    )
    record = {
        "at": _utc_now(),
        "checkpoint_revision": checkpoint,
        "discarded_paths": before,
        "git_clean_output": clean_result.stdout.strip(),
        "state": next_state,
    }
    manifest["recoveries"].append(record)
    manifest["current_attempt"] = None
    manifest["state"] = next_state
    _write_manifest(path, manifest)
    return record


def checkpoint_session(
    manifest_path: str | Path,
    *,
    cwd: str | Path,
) -> dict[str, Any]:
    path, manifest = load_manifest(manifest_path)
    identity = validate_workspace(manifest, cwd=cwd)
    if manifest["state"] not in MUTABLE_STATES:
        raise GuardError("SESSION_NOT_MUTABLE", manifest["state"])
    if identity["dirty_paths"]:
        raise GuardError("CHECKPOINT_NOT_CLEAN", ", ".join(identity["dirty_paths"]))
    manifest["last_known_good"] = identity["head_revision"]
    manifest["current_attempt"] = None
    _write_manifest(path, manifest)
    return {
        "last_known_good": manifest["last_known_good"],
        "state": manifest["state"],
    }


def _load_artifact_json(
    value: str | Path, *, label: str, artifact_root: Path
) -> tuple[Path, dict[str, Any]]:
    path = _canonical_existing(value, label=label)
    if not _is_within(path, artifact_root):
        raise GuardError("EVIDENCE_OUTSIDE_ARTIFACT_ROOT", str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError("EVIDENCE_INVALID", f"{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GuardError("EVIDENCE_INVALID", f"{path}: expected JSON object")
    return path, payload


def _calculate_plan_sha256(document: dict[str, Any]) -> str:
    """Recompute the frozen Core v1 portable plan identity without importing Core."""
    try:
        steps = []
        for step in document["steps"]:
            steps.append({
                "name": step["name"],
                "kind": step["kind"],
                "command_template": step.get("command_template") or step["command"],
                "cwd_template": step.get("cwd_template") or step["cwd"],
                "log": step["log"],
                "required": step["required"],
                "depends_on": step["depends_on"],
                "environment_template": step.get("environment_template")
                or step["environment"],
                "timeout_seconds": step["timeout_seconds"],
            })
        identity = {
            "schema_version": document["schema_version"],
            "project_types": document["project_types"],
            "detected_workflows": document["detected_workflows"],
            "required_executables": document["required_executables"],
            "tests_available": document["tests_available"],
            "steps": steps,
            "blocked_reasons": document["blocked_reasons"],
        }
    except (KeyError, TypeError) as exc:
        raise GuardError("EVIDENCE_PLAN_INVALID", str(exc)) from exc
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_final_evidence(
    manifest_path: str | Path,
    *,
    cwd: str | Path,
    summary_path: str | Path | None = None,
    aggregate_path: str | Path | None = None,
    plan_path: str | Path | None = None,
) -> dict[str, Any]:
    path, manifest = load_manifest(manifest_path)
    identity = validate_workspace(manifest, cwd=cwd)
    artifact_root = Path(manifest["artifact_root"])
    if summary_path is None and aggregate_path is None:
        raise GuardError("EVIDENCE_REQUIRED", "pass --summary or --aggregate")

    summary_file: Path | None = None
    summary: dict[str, Any] | None = None
    plan_hash: str | None = None
    verification = "UNVERIFIED"
    if summary_path is not None:
        summary_file, summary = _load_artifact_json(
            summary_path,
            label="verification summary",
            artifact_root=artifact_root,
        )
        evidence_repository = summary.get("repository")
        if not isinstance(evidence_repository, str) or not evidence_repository:
            raise GuardError("EVIDENCE_REPOSITORY_MISSING", str(evidence_repository))
        evidence_repo = _canonical_existing(
            evidence_repository, label="evidence repository"
        )
        if str(evidence_repo) != manifest["target_repo"]:
            raise GuardError("EVIDENCE_REPOSITORY_MISMATCH", str(evidence_repo))
        if summary.get("source_revision") != identity["head_revision"]:
            raise GuardError(
                "EVIDENCE_SOURCE_MISMATCH", str(summary.get("source_revision"))
            )
        plan_hash = summary.get("plan_sha256")
        verification = summary.get("verification_level", "UNVERIFIED")

    aggregate_file: Path | None = None
    aggregate: dict[str, Any] | None = None
    if aggregate_path is not None:
        aggregate_file, aggregate = _load_artifact_json(
            aggregate_path,
            label="verification aggregate",
            artifact_root=artifact_root,
        )
        if aggregate.get("source_revision") != identity["head_revision"]:
            raise GuardError(
                "AGGREGATE_SOURCE_MISMATCH", str(aggregate.get("source_revision"))
            )
        aggregate_plan_hash = aggregate.get("plan_sha256")
        if plan_hash is not None and aggregate_plan_hash != plan_hash:
            raise GuardError("AGGREGATE_PLAN_MISMATCH", str(aggregate_plan_hash))
        plan_hash = aggregate_plan_hash
        verification = aggregate.get("verification", "UNVERIFIED")
        evidence = aggregate.get("evidence")
        if not isinstance(evidence, list) or aggregate.get("evidence_count") != len(
            evidence
        ):
            raise GuardError("AGGREGATE_EVIDENCE_INVALID", str(evidence))
        for item in evidence:
            if not isinstance(item, dict) or item.get("valid") is not True:
                raise GuardError("AGGREGATE_EVIDENCE_INVALID", str(item))
            if item.get("source_revision") != identity["head_revision"]:
                raise GuardError(
                    "AGGREGATE_SOURCE_MISMATCH", str(item.get("source_revision"))
                )
            if item.get("plan_sha256") != plan_hash:
                raise GuardError(
                    "AGGREGATE_PLAN_MISMATCH", str(item.get("plan_sha256"))
                )
            evidence_summary = item.get("summary")
            if not isinstance(evidence_summary, str):
                raise GuardError("AGGREGATE_EVIDENCE_INVALID", str(evidence_summary))
            _, evidence_document = _load_artifact_json(
                evidence_summary,
                label="aggregate evidence summary",
                artifact_root=artifact_root,
            )
            if evidence_document.get("source_revision") != identity["head_revision"]:
                raise GuardError(
                    "AGGREGATE_SOURCE_MISMATCH",
                    str(evidence_document.get("source_revision")),
                )
            if evidence_document.get("plan_sha256") != plan_hash:
                raise GuardError(
                    "AGGREGATE_PLAN_MISMATCH",
                    str(evidence_document.get("plan_sha256")),
                )
        if verification == "TRI_PLATFORM_VERIFIED":
            platforms = aggregate.get("platforms", {})
            expected = {"windows", "macos", "linux"}
            if set(platforms) != expected or any(
                platforms[name] != "passed" for name in expected
            ):
                raise GuardError("AGGREGATE_PLATFORM_MISMATCH", str(platforms))
            for item in evidence:
                mandatory = item.get("mandatory", {})
                if (
                    item.get("status") != "passed"
                    or item.get("source_dirty") is not False
                    or mandatory.get("passed") != mandatory.get("total")
                ):
                    raise GuardError("AGGREGATE_MANDATORY_INCOMPLETE", str(item))

    if not isinstance(plan_hash, str) or not plan_hash:
        raise GuardError("EVIDENCE_PLAN_MISSING", str(plan_hash))

    levels = {
        "UNVERIFIED",
        "LOCAL_VERIFIED",
        "PARTIALLY_VERIFIED",
        "TRI_PLATFORM_VERIFIED",
        "BLOCKED",
    }
    if verification not in levels:
        raise GuardError("EVIDENCE_VERIFICATION_INVALID", str(verification))

    successful = verification in {
        "LOCAL_VERIFIED",
        "PARTIALLY_VERIFIED",
        "TRI_PLATFORM_VERIFIED",
    }
    if successful and summary is not None and summary.get("source_dirty") is not False:
        raise GuardError("SUCCESS_EVIDENCE_DIRTY", str(summary.get("source_dirty")))
    plan_file: Path | None = None
    if successful:
        if plan_path is None:
            raise GuardError("EVIDENCE_PLAN_FILE_REQUIRED", verification)
        plan_file, plan = _load_artifact_json(
            plan_path, label="verification plan", artifact_root=artifact_root
        )
        if plan.get("plan_sha256") != plan_hash:
            raise GuardError("EVIDENCE_PLAN_MISMATCH", str(plan.get("plan_sha256")))
        calculated_plan_hash = _calculate_plan_sha256(plan)
        if calculated_plan_hash != plan_hash:
            raise GuardError("EVIDENCE_PLAN_HASH_INVALID", calculated_plan_hash)

    manifest["state"] = "BLOCKED" if verification == "BLOCKED" else "COMPLETE"
    manifest["final_evidence"] = {
        "summary": str(summary_file) if summary_file else None,
        "aggregate": str(aggregate_file) if aggregate_file else None,
        "plan": str(plan_file) if plan_file else None,
        "source_revision": identity["head_revision"],
        "plan_sha256": plan_hash,
        "verification": verification,
        "recorded_at": _utc_now(),
    }
    _write_manifest(path, manifest)
    return {
        **manifest["final_evidence"],
        "state": manifest["state"],
        "target_repo": manifest["target_repo"],
    }


def run_bound_harness(
    manifest_path: str | Path,
    arguments: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    _, manifest = load_manifest(manifest_path)
    if manifest["state"] not in MUTABLE_STATES:
        raise GuardError("SESSION_NOT_RUNNABLE", manifest["state"])
    validate_workspace(manifest, cwd=None)
    validate_harness_arguments(manifest, arguments)
    target = Path(manifest["target_repo"])
    return _run(
        [manifest["harness_executable"], *arguments],
        cwd=target,
        check=False,
        timeout=3600,
    )


def _emit(value: Any, *, stream: Any = sys.stdout) -> None:
    json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a bound session manifest")
    init.add_argument("--session-id", required=True)
    init.add_argument("--target-repo", required=True)
    init.add_argument("--harness-executable", required=True)
    init.add_argument("--allowed-write-root", action="append", default=[])
    init.add_argument("--forbidden-write-root", action="append", default=[])
    init.add_argument("--manifest")
    init.add_argument("--allow-primary-checkout", action="store_true")

    guard = subparsers.add_parser("guard", help="validate identity and write paths")
    guard.add_argument("--manifest", required=True)
    guard.add_argument("--cwd", default=os.getcwd())
    guard.add_argument("--write-path", action="append", default=[])

    resume = subparsers.add_parser("resume", help="rebind from manifest state")
    resume.add_argument("--manifest", required=True)

    harness = subparsers.add_parser(
        "run-harness", help="run the bound Harness executable in the target"
    )
    harness.add_argument("--manifest", required=True)
    harness.add_argument("arguments", nargs=argparse.REMAINDER)

    begin = subparsers.add_parser("begin-attempt", help="start one capability repair")
    begin.add_argument("--manifest", required=True)
    begin.add_argument("--cwd", default=os.getcwd())
    begin.add_argument("--capability", required=True)

    interrupted = subparsers.add_parser(
        "interrupt", help="record provider or execution interruption"
    )
    interrupted.add_argument("--manifest", required=True)
    interrupted.add_argument("--reason", required=True)
    interrupted.add_argument("--provider-error", action="store_true")

    recover = subparsers.add_parser(
        "recover", help="restore a dedicated worktree to its checkpoint"
    )
    recover.add_argument("--manifest", required=True)
    recover.add_argument("--discard-current-attempt", action="store_true")

    checkpoint = subparsers.add_parser(
        "checkpoint", help="record a clean verified Git revision"
    )
    checkpoint.add_argument("--manifest", required=True)
    checkpoint.add_argument("--cwd", default=os.getcwd())

    final = subparsers.add_parser(
        "finalize", help="bind the final report to repository evidence"
    )
    final.add_argument("--manifest", required=True)
    final.add_argument("--cwd", default=os.getcwd())
    final.add_argument("--summary")
    final.add_argument("--aggregate")
    final.add_argument("--plan")

    show = subparsers.add_parser("show", help="print the current manifest")
    show.add_argument("--manifest", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            path, manifest = create_manifest(
                session_id=args.session_id,
                target_repo=args.target_repo,
                harness_executable=args.harness_executable,
                allowed_write_roots=args.allowed_write_root,
                forbidden_write_roots=args.forbidden_write_root,
                manifest_path=args.manifest,
                require_worktree=not args.allow_primary_checkout,
            )
            result: Any = {"manifest": str(path), **manifest}
        elif args.command == "guard":
            result = guard_manifest(
                args.manifest, cwd=args.cwd, write_paths=args.write_path
            )
        elif args.command == "resume":
            result = resume_session(args.manifest)
        elif args.command == "run-harness":
            arguments = (
                args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            )
            process = run_bound_harness(args.manifest, arguments)
            if process.stdout:
                sys.stdout.write(process.stdout)
            if process.stderr:
                sys.stderr.write(process.stderr)
            return process.returncode
        elif args.command == "begin-attempt":
            result = begin_attempt(
                args.manifest, cwd=args.cwd, capability=args.capability
            )
        elif args.command == "interrupt":
            result = mark_interrupted(
                args.manifest,
                reason=args.reason,
                provider_error=args.provider_error,
            )
        elif args.command == "recover":
            result = recover_checkpoint(
                args.manifest,
                discard_current_attempt=args.discard_current_attempt,
            )
        elif args.command == "checkpoint":
            result = checkpoint_session(args.manifest, cwd=args.cwd)
        elif args.command == "finalize":
            result = validate_final_evidence(
                args.manifest,
                cwd=args.cwd,
                summary_path=args.summary,
                aggregate_path=args.aggregate,
                plan_path=args.plan,
            )
        else:
            _, result = load_manifest(args.manifest)
    except GuardError as exc:
        _emit({"ok": False, "code": exc.code, "detail": exc.detail}, stream=sys.stderr)
        return 2
    _emit({"ok": True, "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
