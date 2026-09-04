---
name: cross-platform-porting
description: Orchestrate evidence-backed cross-platform repository ports.
version: 0.1.1
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
- MEDIUM and HIGH semantic work must use a dedicated linked Git worktree.
- Local build and test tools declared by the Verification Plan must be available.
- Remote execution requires an authenticated `gh` CLI and a GitHub remote, but
  neither is required for scanning, safe fixes, local verification, rendering,
  or offline aggregation.

Use `terminal` for CLI invocations, `read_file` for reports and exact logs,
`search_files` for locating referenced source, and `patch` for narrow semantic
repairs. Never expose credentials in prompts, logs, commits, or artifacts.

## How to Run

Create a persistent session manifest before asking the model to inspect or
modify source. Run the deterministic guard through `terminal`:

```text
python <skill-directory>/scripts/workspace_guard.py init \
  --session-id <session-id> \
  --target-repo <dedicated-worktree> \
  --harness-executable <absolute-portability-executable> \
  --forbidden-write-root <harness-repository> \
  --forbidden-write-root <original-source-repository>
```

Resolve every placeholder to an absolute path. Retain the returned manifest
path as the only session state. Do not use remembered cwd or search `PATH` for
Harness. On resume, provider retry, or a new model turn, call `resume` first and
use its `required_workdir` and `harness_executable` values.

The manifest and state machine are specified in
[references/execution-safety.md](references/execution-safety.md). Read that
reference before any MEDIUM repair, resume, recovery, or final report.

## Quick Reference

`<guard>` is the absolute path to `scripts/workspace_guard.py`; `<manifest>` is
the immutable path returned by `init`. These commands bind the frozen
`portability scan`, `portability fix`, `portability verify`,
`portability render-github`, `portability collect-github`, and
`portability aggregate` contracts to one target.

| Purpose | Command |
|---|---|
| Rebind after resume | `python <guard> resume --manifest <manifest>` |
| Guard source writes | `python <guard> guard --manifest <manifest> --cwd <target> --write-path <absolute-file>` |
| Scan | `python <guard> run-harness --manifest <manifest> -- scan . --output-dir <artifact-root>/scan` |
| Preview LOW fixes | `python <guard> run-harness --manifest <manifest> -- fix . --safe --dry-run` |
| Apply LOW fixes | `python <guard> run-harness --manifest <manifest> -- fix . --safe` |
| Generate Plan | `python <guard> run-harness --manifest <manifest> -- verify . --plan-only --output-dir <artifact-root>/plan` |
| Local verify | `python <guard> run-harness --manifest <manifest> -- verify . --plan <artifact-root>/plan/plan.json --output-dir <artifact-root>/local-evidence` |
| Record interruption | `python <guard> interrupt --manifest <manifest> --provider-error --reason <reason>` |
| Recover partial attempt | `python <guard> recover --manifest <manifest> --discard-current-attempt` |
| Final identity gate | `python <guard> finalize --manifest <manifest> --cwd <target> --plan <plan> (--summary <summary> \| --aggregate <aggregate>)` |

## Procedure

### 1. Bind the repository and Harness

Create a dedicated linked worktree for semantic repair. Initialize the Session
Manifest with its absolute target, Git dir/common-dir identity, exact Harness
executable, allowed source root, and explicit forbidden roots. The manifest
must live outside all source repositories. It, not cwd, is session state.

At every resume, provider retry, restored session, or new model turn, call
`resume`. Never continue from remembered cwd. If the manifest reports
`NEEDS_RECOVERY`, recover or stop before reading more source.

**Done when:** `resume` returns the intended worktree as `required_workdir`, the
exact Harness executable passes its version check, and the worktree is clean.

### 2. Run the initial scan

Use the guard's `run-harness` command with `scan .` and an output directory
under the manifest artifact root. Read the generated JSON report with
`read_file`; do not independently scan or load the whole repository into
context.

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
the guarded Harness runner only when the user's request authorizes source
changes and the Git safety gate accepts the worktree. Before applying, call
`guard --write-path` once for every absolute touched path.

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

Call `begin-attempt` before reading repair context. Immediately before every
`patch`, call `guard` with the exact absolute destination paths; a missing or
failed guard prohibits the mutation. Preserve behavior and add or run focused
tests for each capability. Commit a verified capability repair locally, then
call `checkpoint` while the worktree is clean. Never turn MEDIUM coverage into
a new generic Harness fixer.

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

Generate and execute the Plan through `run-harness`, storing Plan, work, summary,
and logs beneath the manifest artifact root. Do not replace the detected project
workflow with a preferred toolchain.

Read `summary.json` first. Load a step log with `read_file` only when that step
failed or was blocked.

**Done when:** local evidence records the Plan hash, source state, mandatory
counts, and an honest verification level.

### 9. Render, do not reinterpret, CI

Guard the intended workflow path, call the bound Harness renderer, then run the
same command with `--check`. Do not hand-translate Plan argv into shell commands
or add a parallel build/test path to the workflow.

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

For a provider error, do not keep mutating or add another patch on top. Call
`interrupt`; a dirty attempt becomes `NEEDS_RECOVERY` and must be discarded back
to `last_known_good`. Provider retry is limited to one and semantic repair to
three attempts. A second provider failure becomes `PAUSED_PROVIDER`.

**Done when:** the failed evidence has a demonstrated root cause and a minimal
verified repair, or the loop stops with a precise blocker.

### 14. Report the final evidence identity

Call `finalize` before drafting success text. For local evidence, pass Summary
and Plan; for remote evidence, pass Aggregate and Plan. It rechecks target
repository, current revision, Plan hash, artifact root, and evidence identity.
Report only the returned verification level, identity, platform statuses,
mandatory counts, evidence path, and untouched user changes.

**Done when:** every success claim comes from the final identity gate and no
green job or model memory is presented as proof by itself.

## Pitfalls

- Do not copy Scanner, fixer, verifier, renderer, or aggregation code into this
  Skill. Missing Harness behavior is a Core issue, not an orchestration feature.
- Do not use cwd as session state, search for Harness with `which`, or resume on
  top of an unverified partial diff.
- Do not call `patch` unless the immediately preceding guard authorized every
  destination path. A path mismatch is `WORKSPACE_IDENTITY_MISMATCH`, not a cue
  to guess another directory.
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

- The Session Manifest still resolves to the same target, Git dir/common dir,
  Harness executable, allowed roots, and forbidden roots.
- Wrong cwd, forbidden-root writes, symlink escapes, and unrecovered partial
  attempts are rejected by `workspace_guard.py`.
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
