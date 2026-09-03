---
name: cross-platform-porting
description: Orchestrate evidence-backed cross-platform repository ports.
version: 0.1.0
author: Raelon Veritas Lee (roclee2692), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Migration, Portability, CI, Verification, GitHub]
    category: migration
    related_skills: [github-pr-workflow, systematic-debugging]
---

# Cross-Platform Porting Skill

Use the model for orchestration and narrow semantic repair while
`portability-harness` remains the portability truth engine. This skill does not
copy Harness logic, add model calls to Harness, or treat a green CI job as
verification evidence.

## When to Use

- A user asks to port a Python or C/C++ repository across Windows, macOS, and
  Linux.
- A repository already has Harness findings or verification evidence that must
  be repaired and proven.
- A user wants an evidence-backed portability result, including
  `TRI_PLATFORM_VERIFIED`.

Do not use this skill for adding new Scanner rules, broad architecture rewrites,
or CI repair unrelated to portability findings. Do not use it when the user only
wants a static code review with no migration work.

## Prerequisites

- The `portability` CLI must expose `scan`, `fix`, `verify`, `render-github`,
  `collect-github`, and `aggregate`. V1 assumes the frozen v0.1.0 contract.
- The target must be a Git repository for source-revision-bound remote evidence.
- Local build and test tools declared by the Verification Plan must be available.
- Remote execution requires an authenticated `gh` CLI and a GitHub remote, but
  neither is required for scanning, safe fixes, local verification, rendering,
  or offline aggregation.

Use `terminal` for CLI invocations, `read_file` for reports and exact logs,
`search_files` for locating referenced source, and `patch` for narrow semantic
repairs. Never expose credentials in prompts, logs, commits, or artifacts.

## How to Run

Run Harness from the target repository so relative artifact paths stay
inspectable. Start by recording the installed version and available commands:

```json
{"command":"python -m pip show portability-harness && portability --help","workdir":"<target-repository>"}
```

Replace `<target-repository>` with the resolved absolute repository path before
calling `terminal`; never execute placeholder text literally. If the installed
version differs from v0.1.0, verify that all six commands and the expected JSON
fields exist before continuing. Do not emulate a missing command in the Skill.

## Quick Reference

All examples are `terminal` calls with the target repository as `workdir`.

| Purpose | Command |
|---|---|
| Scan | `portability scan . --output-dir .portability/scan` |
| Preview LOW fixes | `portability fix . --safe --dry-run` |
| Apply LOW fixes | `portability fix . --safe` |
| Generate Plan | `portability verify . --plan-only --output-dir .portability` |
| Local verify | `portability verify . --plan .portability/plan.json --output-dir .portability/local-evidence` |
| Render workflow | `portability render-github .portability/plan.json` |
| Check workflow drift | `portability render-github .portability/plan.json --check` |
| Collect GitHub evidence | `portability collect-github RUN_ID --repo OWNER/REPO --output-dir .portability/github-RUN_ID` |
| Offline aggregate | `portability aggregate EVIDENCE_DIR --output verification-aggregate.json` |

## Procedure

### 1. Preflight the repository and Harness

Use `terminal` to inspect Git status, current branch, remotes, installed Harness
version, and CLI help. Record existing dirty paths before any mutation. Never
stash, overwrite, or commit pre-existing user changes; create a clean worktree
when migration work would overlap them.

**Done when:** the repository path, base revision, dirty paths, Harness version,
and available command surface are recorded.

### 2. Run the initial scan

Call `terminal(command="portability scan . --output-dir .portability/scan")`.
Read the generated JSON report with `read_file`; do not independently scan or
load the whole repository into context.

**Done when:** every decision starts from a structured Harness finding rather
than an agent-invented portability concern.

### 3. Remove already-resolved findings from the work queue

Treat `action_required: false` as authoritative. Do not refactor findings whose
resolution is already guarded, already mitigated, backed by a portable shim, or
intentionally platform-specific. Preserve them in the report as evidence.

**Done when:** the repair queue contains only findings where
`action_required: true`.

### 4. Preview and apply deterministic LOW fixes

Preview with `terminal(command="portability fix . --safe --dry-run")`. Inspect
the touched-file set and repository-policy evidence. Apply with
`terminal(command="portability fix . --safe")` only when the user's request
authorizes source changes and the Git safety gate accepts the worktree.

Do not force a LOW fix past repository EOL policy or use dirty mode as a blanket
override. If an existing dirty file intersects the plan, use a clean worktree or
stop.

**Done when:** the applied patch exactly matches the preview and no unrelated
file changed.

### 5. Re-run Harness scan after safe fixes

Run the same Harness scan command again. Compare finding IDs, locations,
resolution, and `action_required`; do not manually re-inventory the repository.

**Done when:** targeted deterministic findings disappeared or became resolved,
and no unexpected actionable finding was introduced.

### 6. Repair MEDIUM findings one capability at a time

Group only closely related findings with the same capability. Read their source
locations and the smallest required surrounding context, then use `patch` for a
minimal semantic repair. Choose strategies in this fixed order:

1. Standard library.
2. Mature cross-platform library already compatible with the project.
3. Runtime capability detection.
4. Thin platform adapter.
5. Guarded OS branch.
6. Platform fork.

Preserve behavior and add or run focused tests for each capability before moving
to the next group. Never turn MEDIUM coverage into a new generic Harness fixer.

**Done when:** one capability group is repaired, its focused tests pass, and the
new scan evidence reflects the change.

### 7. Stop at HIGH architecture findings

Do not automatically migrate COM, DirectX, Registry-dependent architecture,
Win32 GUI, drivers, CUDA kernels, or equivalent platform-bound systems. Produce
an architecture migration proposal covering boundaries, candidate adapters,
behavioral risks, and a verification plan.

**Done when:** HIGH findings remain unmodified and the user has a concrete
proposal or an explicit blocker.

### 8. Generate and execute the local Verification Plan

Generate the Plan once with `portability verify . --plan-only --output-dir
.portability`, then execute that exact file with `portability verify . --plan
.portability/plan.json --output-dir .portability/local-evidence`. Do not replace
the detected project workflow with a preferred toolchain.

Read `summary.json` first. Load a step log with `read_file` only when that step
failed or was blocked.

**Done when:** local evidence records the Plan hash, source state, mandatory
counts, and an honest verification level.

### 9. Render, do not reinterpret, CI

Call `terminal(command="portability render-github .portability/plan.json")`,
then run the same command with `--check`. Do not hand-translate Plan argv into
shell commands or add a parallel build/test path to the workflow.

**Done when:** renderer drift check passes and every matrix lane calls the same
Harness verifier contract.

### 10. Gate all GitHub writes on user authorization

Rendering and offline evidence work do not authorize commit, push, PR, rerun,
or merge. If the user explicitly authorizes real CI, use a clean branch or
worktree, commit all source and Harness integration files, then use the
`github-pr-workflow` discipline for Git operations. Never include unrelated
dirty changes.

**Done when:** the remote run points at one reproducible clean source revision,
or the workflow stops before any GitHub mutation.

### 11. Collect evidence through the read-only Adapter

After the run completes, call `portability collect-github` with its exact run ID
and repository. Treat GitHub job conclusion as diagnostic metadata only.

**Done when:** downloaded evidence is bound to the selected run ID, attempt, and
head SHA and has been passed to the offline Aggregator.

### 12. Accept only Aggregator verification levels

Read `verification-aggregate.json`. Sign `TRI_PLATFORM_VERIFIED` only when valid
Windows, macOS, and Linux summaries share one non-null `source_revision`, one
recomputed `plan_sha256`, and every platform passed all mandatory steps.

**Done when:** the reported outcome is exactly one of `UNVERIFIED`,
`LOCAL_VERIFIED`, `PARTIALLY_VERIFIED`, `TRI_PLATFORM_VERIFIED`, or `BLOCKED`,
with its evidence path supplied to the user.

### 13. Repair only failed platform lanes

For `PARTIALLY_VERIFIED` or `BLOCKED`, read the aggregate first. For each failed
platform, load only its summary, non-passing step, corresponding raw log, and
the source context implicated by that evidence. Do not reload successful lane
logs or the whole repository.

Make the smallest patch that addresses the observed failure, repeat focused
local verification, then request authorization before another push. Stop after
three remote repair iterations and report the remaining blocker unless the user
explicitly asks to continue.

**Done when:** the failed evidence has a demonstrated root cause and a minimal
verified repair, or the loop stops with a precise blocker.

### 14. Report the final evidence identity

Report the verification level, Plan hash, source revision, platform statuses,
mandatory counts, evidence path, and any untouched user changes. Distinguish
synthetic tests, local evidence, job conclusions, and real aggregated remote
evidence.

**Done when:** every success claim is traceable to an aggregate and no green job
is presented as proof by itself.

## Pitfalls

- Do not copy Scanner, fixer, verifier, renderer, or aggregation code into this
  Skill. Missing Harness behavior is a Core issue, not an orchestration feature.
- Do not independently rediscover the repository after Harness emits findings;
  use location and evidence fields to load minimal context.
- Do not modify `action_required: false` findings to make the diff look active.
- Do not let a clean local build imply cross-platform verification.
- Do not combine evidence from different Plan hashes, commits, runs, or attempts.
- Do not commit generated evidence logs unless the repository explicitly tracks
  acceptance artifacts.
- Do not install MCP servers, model APIs, containers, or alternate build systems
  merely to complete this workflow.

## Verification

Before declaring the migration complete, confirm:

- The final `source_revision` is committed and the verification checkout was clean.
- The rendered workflow passes `--check` against the committed Plan.
- Each required platform summary is schema-valid and has no identity issue.
- Each platform's mandatory passed count equals its mandatory total.
- The aggregate `plan_sha256` matches the recomputed committed Plan hash.
- Every evidence `source_revision` equals the selected GitHub run head SHA.
- Windows, macOS, and Linux are all `passed` before reporting
  `TRI_PLATFORM_VERIFIED`.
- Pre-existing user changes remain untouched and are named in the final report.

The portability-harness v0.1.0 golden acceptance cases are Harness self-E2E and
flight-management-system E2E. Any Core change must preserve both before this
Skill treats the revised Core contract as stable.
