"""Fail-closed pre_tool_call policy for portability repair sessions.

The portability skill creates a manifest outside all repositories and launches
Hermes with ``PORTABILITY_SESSION_MANIFEST`` pointing at it.  This plugin is
deliberately small: it does not replace the manifest guard or the Harness.  It
is the last policy check before a Hermes tool reaches its implementation.

The environment variable is an internal session bridge, not a user-facing
configuration knob.  Without it, the plugin is inert so normal Hermes sessions
keep their existing behaviour.  With it, malformed state fails closed.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Mapping


MANIFEST_ENV = "PORTABILITY_SESSION_MANIFEST"
LANE_ENV = "PORTABILITY_EXECUTION_LANE"
SANDBOX_ACTIVE_ENV = "PORTABILITY_SANDBOX_ACTIVE"

_DEFAULT_PERMISSIONS = {
    "source_write": True,
    "dependency_install": "session_only",
    "git_index_write": False,
    "git_commit": False,
    "git_push": False,
    "git_merge": False,
    "git_rebase": False,
}

_GIT_WRITE_RE = re.compile(
    r"(?:^|[;&|()\n])\s*(?:env\s+)?git(?:\s+-[A-Za-z]+(?:\s+[^\s;&|()]+)*)?\s+"
    r"(?P<verb>add|commit|push|merge|rebase|reset|restore|clean|checkout|stash|cherry-pick|revert|am|switch)\b",
    re.IGNORECASE,
)
_INSTALL_RE = re.compile(
    r"(?:^|[;&|()\n])\s*(?:python(?:\d+(?:\.\d+)?)?\s+-m\s+)?"
    r"(?P<tool>pip(?:\d+(?:\.\d+)?)?|uv|conda|npm|poetry)\b[^\n;&|()]*\b(?:install|sync|add)\b",
    re.IGNORECASE,
)
_REDIRECTION_RE = re.compile(r"(?:^|[\s])(?:\d*>>?|<<)\s*([^\s;&|()]+)")
_INLINE_CODE_RE = re.compile(
    r"(?:^|[;&|()\n\s])(?:python(?:\d+(?:\.\d+)?)?|pypy3?|perl|ruby|node|bash|sh|zsh)"
    r"\s+(?:-+[^\s;&|()]*\s+)*-c\b",
    re.IGNORECASE,
)
_ABSOLUTE_CD_RE = re.compile(r"(?:^|[;&|()\n])\s*cd\s+(/[^\s;&|()]+)", re.IGNORECASE)
_SHELL_MUTATORS = {"rm", "mv", "cp", "install", "touch", "mkdir", "ln", "tee", "chmod", "chown"}
_INTERPRETERS = {"python", "python3", "python2", "pypy", "pypy3", "bash", "sh", "zsh", "node", "perl", "ruby"}


class PolicyError(RuntimeError):
    """Raised when the active manifest cannot be trusted."""


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _real(path: str | Path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def _load_manifest() -> tuple[Path, dict[str, Any]] | None:
    raw = os.environ.get(MANIFEST_ENV, "").strip()
    if not raw:
        return None
    path = _real(raw)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot load session manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError("session manifest root must be an object")
    return path, data


def _policy(manifest: Mapping[str, Any]) -> dict[str, Any]:
    target_raw = manifest.get("target_repo")
    if not isinstance(target_raw, str) or not target_raw:
        raise PolicyError("manifest target_repo is missing")
    target = _real(target_raw)
    allowed_raw = manifest.get("allowed_write_roots") or [str(target)]
    forbidden_raw = manifest.get("forbidden_write_roots") or []
    if not isinstance(allowed_raw, list) or not isinstance(forbidden_raw, list):
        raise PolicyError("manifest write roots must be arrays")
    allowed = [_real(item) for item in allowed_raw if isinstance(item, str)]
    forbidden = [_real(item) for item in forbidden_raw if isinstance(item, str)]
    if not allowed or not all(_within(root, target) for root in allowed):
        raise PolicyError("allowed_write_roots must be inside target_repo")
    permissions = dict(_DEFAULT_PERMISSIONS)
    raw_permissions = manifest.get("permissions")
    if raw_permissions is not None:
        if not isinstance(raw_permissions, Mapping):
            raise PolicyError("manifest permissions must be an object")
        permissions.update(raw_permissions)
    ephemeral = manifest.get("ephemeral_root") or manifest.get("artifact_root")
    ephemeral_root = _real(ephemeral) if isinstance(ephemeral, str) else None
    return {
        "target": target,
        "allowed": allowed,
        "forbidden": forbidden,
        "permissions": permissions,
        "ephemeral_root": ephemeral_root,
    }


def _path_arg(args: Mapping[str, Any], tool_name: str) -> str | None:
    if tool_name in {"write_file", "patch"}:
        value = args.get("path")
    elif tool_name == "skill_manage":
        value = args.get("file_path") or args.get("path")
    else:
        value = None
    return value if isinstance(value, str) else None


def _check_destination(value: str, policy: Mapping[str, Any]) -> str | None:
    candidate = Path(os.path.expanduser(value))
    if not candidate.is_absolute():
        return "mutation destinations must be absolute under an active portability manifest"
    resolved = _real(candidate)
    if any(_within(resolved, root) for root in policy["forbidden"]):
        return f"destination is inside a forbidden repository: {resolved}"
    if not any(_within(resolved, root) for root in policy["allowed"]):
        return f"destination is outside allowed portability roots: {resolved}"
    return None


def _check_git(command: str, permissions: Mapping[str, Any]) -> str | None:
    for match in _GIT_WRITE_RE.finditer(command):
        verb = match.group("verb").lower()
        capability = {
            "add": "git_index_write",
            "reset": "git_index_write",
            "restore": "git_index_write",
            "clean": "git_index_write",
            "checkout": "git_index_write",
            "stash": "git_index_write",
            "cherry-pick": "git_index_write",
            "revert": "git_index_write",
            "am": "git_index_write",
            "switch": "git_index_write",
            "commit": "git_commit",
            "push": "git_push",
            "merge": "git_merge",
            "rebase": "git_rebase",
        }[verb]
        if not permissions.get(capability, False):
            return f"git {verb} is denied by portability session capability {capability}"
    return None


def _check_terminal(command: str, policy: Mapping[str, Any]) -> str | None:
    permissions = policy["permissions"]
    denied = _check_git(command, permissions)
    if denied:
        return denied
    if _INLINE_CODE_RE.search(command):
        return "inline interpreter code is denied; use a sandboxed execute_code lane"
    lane = os.environ.get(LANE_ENV, "").strip().lower()
    sandbox_active = os.environ.get(SANDBOX_ACTIVE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    if not (lane == "sandbox" and sandbox_active):
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            return "unparseable shell execution is denied"
        segment: list[str] = []
        segments: list[list[str]] = []
        for token in tokens + [";"]:
            if token in {";", "&&", "||", "|", "&"}:
                if segment:
                    segments.append(segment)
                segment = []
                continue
            segment.append(token)
        for segment in segments:
            index = 0
            while index < len(segment) and (
                segment[index] == "env"
                or ("=" in segment[index] and segment[index].split("=", 1)[0].replace("_", "").isalnum())
            ):
                index += 1
            if index >= len(segment):
                continue
            executable = Path(segment[index]).name.lower()
            if executable in _INTERPRETERS:
                if not any("workspace_guard.py" in value for value in segment[index + 1:]):
                    return "interpreter execution is limited to workspace_guard.py outside a sandbox"
    for match in _ABSOLUTE_CD_RE.finditer(command):
        reason = _check_destination(match.group(1), policy)
        if reason:
            return f"directory change denied: {reason}"
    install = _INSTALL_RE.search(command)
    if install and permissions.get("dependency_install") == "session_only":
        ephemeral = policy.get("ephemeral_root")
        if ephemeral is None or str(ephemeral) not in command:
            return "dependency installation is limited to the session runtime root"
    for match in _REDIRECTION_RE.finditer(command):
        candidate = match.group(1)
        if candidate in {"/dev/null", "/dev/stdout", "/dev/stderr"}:
            continue
        if not candidate.startswith("/"):
            return "relative shell redirection is denied; use a guarded write tool"
        reason = _check_destination(candidate, policy)
        if reason:
            return f"shell redirection denied: {reason}"
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return "unparseable shell mutation is denied"
    command_position = True
    for token in tokens:
        if token in {";", "&&", "||", "|", "&"}:
            command_position = True
            continue
        if not command_position:
            continue
        if token == "env" or ("=" in token and token.split("=", 1)[0].replace("_", "").isalnum()):
            command_position = True
            continue
        command_position = False
        basename = Path(token).name.lower()
        if basename not in _SHELL_MUTATORS:
            continue
        return (
            f"shell file mutation command {basename!r} is denied; use guarded "
            "patch/write_file or a sandboxed lane"
        )
    return None


def _check_cwd(args: Mapping[str, Any], policy: Mapping[str, Any]) -> str | None:
    value = args.get("workdir") or args.get("cwd") or os.environ.get("TERMINAL_CWD")
    if value is None:
        # Terminal maintains a per-session cwd internally.  When no explicit
        # workdir (and no session seed) is supplied, let that resolver provide
        # the cwd; path-bearing writes are still checked below.
        return None
    if not isinstance(value, str):
        return "tool cwd must be an absolute path under the bound target repository"
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return "tool cwd must be absolute under the bound target repository"
    resolved = _real(candidate)
    if not _within(resolved, policy["target"]):
        return f"tool cwd is outside the bound target repository: {resolved}"
    return None


def _block(reason: str) -> dict[str, str]:
    return {"action": "block", "message": f"BLOCKED by portability execution policy: {reason}"}


def _on_pre_tool_call(
    *, tool_name: str = "", args: Any = None, **_: Any
) -> dict[str, str] | None:
    """Return a block directive before a portability session tool executes."""
    try:
        loaded = _load_manifest()
        if loaded is None:
            return None
        _, manifest = loaded
        policy = _policy(manifest)
        tool_args = args if isinstance(args, Mapping) else {}
        permissions = policy["permissions"]

        destination = _path_arg(tool_args, tool_name)
        if destination is not None:
            if not permissions.get("source_write", False):
                return _block("source_write capability is denied")
            reason = _check_destination(destination, policy)
            if reason:
                return _block(reason)

        if tool_name == "terminal":
            cwd_reason = _check_cwd(tool_args, policy)
            if cwd_reason:
                return _block(cwd_reason)
            command = tool_args.get("command")
            if isinstance(command, str):
                reason = _check_terminal(command, policy)
                if reason:
                    return _block(reason)

        if tool_name == "execute_code":
            lane = os.environ.get(LANE_ENV, "").strip().lower()
            sandbox_active = os.environ.get(SANDBOX_ACTIVE_ENV, "").strip().lower()
            if lane != "sandbox" or sandbox_active not in {"1", "true", "yes", "on"}:
                return _block("execute_code requires an active sandbox mutation lane")
    except PolicyError as exc:
        return _block(str(exc))
    return None


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
