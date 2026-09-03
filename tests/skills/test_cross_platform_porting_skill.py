"""Contract tests for the cross-platform-porting optional skill."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / "optional-skills"
    / "migration"
    / "cross-platform-porting"
    / "SKILL.md"
)


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
    assert frontmatter["version"] == "0.1.0"
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
    steps = re.findall(r"^### \d+\..*?(?=^### \d+\.|\Z)", procedure, re.MULTILINE | re.DOTALL)
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
