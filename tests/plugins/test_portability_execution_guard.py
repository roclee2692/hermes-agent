from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_plugin():
    path = Path(__file__).parents[2] / "plugins/portability-execution-guard/__init__.py"
    spec = importlib.util.spec_from_file_location("portability_execution_guard", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "target_repo": str(target),
                "allowed_write_roots": [str(target)],
                "forbidden_write_roots": [str(tmp_path / "harness")],
                "ephemeral_root": str(tmp_path / "runtime"),
                "permissions": {
                    "source_write": True,
                    "dependency_install": "session_only",
                    "git_index_write": False,
                    "git_commit": False,
                    "git_push": False,
                    "git_merge": False,
                    "git_rebase": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_source_paths_and_git_capabilities_are_blocked(tmp_path, monkeypatch):
    plugin = _load_plugin()
    manifest = _manifest(tmp_path)
    monkeypatch.setenv(plugin.MANIFEST_ENV, str(manifest))
    assert plugin._on_pre_tool_call(
        tool_name="patch", args={"path": str(tmp_path / "harness/x.py")}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "git commit -m test"}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "git add target/x.py"}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "git -C /tmp/other commit -m test"},
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "git stash push -m test"}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "echo ok", "workdir": str(tmp_path / "harness")}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "python -c \"open('/tmp/x','w').write('x')\""}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "mv /tmp/a /tmp/b"}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "env FOO=1 mv /tmp/a /tmp/b"}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "echo x > relative.txt"}
    )["action"] == "block"


def test_session_only_install_and_execute_code_require_lane(tmp_path, monkeypatch):
    plugin = _load_plugin()
    manifest = _manifest(tmp_path)
    monkeypatch.setenv(plugin.MANIFEST_ENV, str(manifest))
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "python -m pip install torch"}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "python /tmp/workspace_guard.py resume --manifest /tmp/m.json"},
    ) is None
    assert plugin._on_pre_tool_call(
        tool_name="terminal", args={"command": "python CNN_B.py"}
    )["action"] == "block"
    assert plugin._on_pre_tool_call(
        tool_name="execute_code", args={"code": "open('x', 'w').write('x')"}
    )["action"] == "block"
    monkeypatch.setenv(plugin.LANE_ENV, "sandbox")
    monkeypatch.setenv(plugin.SANDBOX_ACTIVE_ENV, "1")
    assert plugin._on_pre_tool_call(
        tool_name="execute_code", args={"code": "print('ok')"}
    ) is None


def test_malformed_active_manifest_fails_closed(tmp_path, monkeypatch):
    plugin = _load_plugin()
    manifest = tmp_path / "bad.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(plugin.MANIFEST_ENV, str(manifest))
    result = plugin._on_pre_tool_call(tool_name="terminal", args={"command": "echo ok"})
    assert result and result["action"] == "block"
