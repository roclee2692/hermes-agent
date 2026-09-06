# Execution safety contract

Read this reference before MEDIUM repair, session resume, provider recovery, or
final reporting. `workspace_guard.py` is the executable authority; this document
explains its contract and failure states.

## Session Manifest

`init` records canonical, symlink-resolved identity:

```json
{
  "session_id": "portability-session",
  "state": "ACTIVE",
  "target_repo": "/absolute/dedicated-worktree",
  "target_git_dir": "/absolute/git-worktree-dir",
  "git_common_dir": "/absolute/common-git-dir",
  "base_revision": "commit-sha",
  "last_known_good": "commit-sha",
  "harness_executable": "/absolute/portability",
  "harness_version": "0.1.0",
  "harness_sha256": "entrypoint-sha256",
  "allowed_write_roots": ["/absolute/dedicated-worktree"],
  "forbidden_write_roots": [
    "/absolute/portability-harness",
    "/absolute/original-repository"
  ]
}
```

The actual manifest also records attempt counts, interruptions, recovery
receipts, and a profile-scoped artifact root. It must not live inside the target
or any forbidden repository.

The manifest is also the runtime capability policy. It records
`source_write: true`, session-only dependency installation, and denies Git
index/commit/push/merge/rebase operations by default. Before launching Hermes,
prepare its session runtime:

```text
python <guard> prepare-runtime --manifest <manifest>
python <guard> runtime-env --manifest <manifest> --lane mutation
```

Pass the returned environment to the Hermes process. It redirects Python
user-site, bytecode, package/tool caches, and temporary files beneath the
manifest artifact root, prepends the session virtualenv to `PATH`, sets
`VIRTUAL_ENV`, and sets `PORTABILITY_SESSION_MANIFEST`. Hermes then
auto-loads the bundled `portability-execution-guard` plugin and its native
`pre_tool_call` hook. A malformed or missing active manifest fails closed.

The target is a linked worktree by default. `--allow-primary-checkout` exists
for explicitly reviewed read-only or exceptional workflows; do not use it for
MEDIUM/HIGH source mutation.

## Mutation gate

Before every source mutation, call:

```text
python <guard> guard \
  --manifest <manifest> \
  --cwd <required-workdir> \
  --write-path <absolute-destination>
```

The guard recomputes all Git identity fields, verifies the exact Harness path,
entrypoint SHA-256, package version, and six-command help surface, resolves
existing symlinks, and requires every destination to be inside an allowed root
and outside every forbidden root. Relative write paths are refused. Any nonzero
result prohibits the mutation.

Harness must run through `run-harness`. That runner always executes the
manifest's absolute executable with the target as cwd. It accepts only the six
frozen v0.1.0 commands, rejects another source target, and confines generated
work/evidence paths to the manifest artifact root.

Python syntax/unit checks must run through `run-focused` with an absolute
interpreter argv. It accepts only `unittest`, `pytest`, `compileall`,
`py_compile`, or a `test*.py` script beneath the target's `tests/` directory,
caps execution at five minutes, and records the command in the manifest. It
rejects package installers, arbitrary modules, interactive code, and direct
application/training scripts. Dependency installation is a separately
authorized operation, not an implicit reaction to a failed test. Inline
interpreter snippets through `terminal` are denied; arbitrary `execute_code`
requires an explicitly active sandbox lane. The runtime gate applies the same
policy to `patch`, `write_file`, `skill_manage`, and `terminal` calls.

## Resume and interruption states

```text
ACTIVE
  | provider/execution interruption
  +--> INTERRUPTED       no partial diff
  +--> NEEDS_RECOVERY    partial diff exists
  +--> PAUSED_PROVIDER   provider retry limit exceeded

ACTIVE -- honest terminal evidence --> COMPLETE or BLOCKED
```

On every restored turn, call `resume`; never infer state from the process cwd.
`resume` validates the manifest target directly and returns
`required_workdir`. It refuses `NEEDS_RECOVERY` and `PAUSED_PROVIDER` sessions.

Call `begin-attempt` once per semantic capability. The script allows at most
three repair attempts. Provider failures are recorded separately and allow one
retry; they do not become evidence that the semantic repair was wrong.

If an interruption leaves tracked or untracked changes, call `interrupt` and
then explicitly call:

```text
python <guard> recover \
  --manifest <manifest> \
  --discard-current-attempt
```

Recovery is available only in a dedicated linked worktree. It refuses to move a
changed HEAD, restores tracked content from the recorded checkpoint, removes
attempt-created untracked files, and removes only ignored files absent from the
attempt-start snapshot. Pre-existing ignored files are preserved. It verifies a
clean result and records both discarded path lists. A provider retry is counted
only when the reason contains a recognizable provider failure signature; an
ordinary process signal cannot consume that budget. After a verified repair is
committed locally, call `checkpoint` to advance `last_known_good`.

## Final evidence gate

`finalize` validates the current Git identity again. All supplied Plan, Summary,
Aggregate, and downloaded evidence paths must live beneath the manifest
artifact root.

For local verification, the Summary must name the manifest target and current
source revision and contain a Plan hash. A successful level additionally
requires `source_dirty: false`.

For remote verification, pass the Aggregate instead of a runner Summary, whose
repository path is necessarily runner-local. Every aggregate evidence record
must be valid, bound to current source and Plan identities, and point to a
downloaded Summary beneath the artifact root. `TRI_PLATFORM_VERIFIED`
additionally requires exactly Windows, macOS, and Linux with all mandatory
steps passed and clean sources. The supplied Plan's identity must match either
successful path. The guard independently recalculates the frozen Core v1 Plan
SHA-256 and checks the identity fields inside every downloaded Summary, not
only the Aggregate's outer records. A mismatch returns a stable error code and
no success conclusion may be produced.

## Stable failure outcomes

- `WORKSPACE_IDENTITY_MISMATCH`: cwd or Git identity differs from the manifest.
- `WRITE_INSIDE_FORBIDDEN_ROOT`: destination resolves into a protected repo.
- `WRITE_OUTSIDE_ALLOWED_ROOT`: destination is outside the repair worktree.
- `HARNESS_TARGET_MISMATCH`: a bound Harness command names another repository.
- `NEEDS_RECOVERY`: an interrupted partial attempt must be discarded.
- `PAUSED_PROVIDER`: the single provider retry has been exhausted.
- `REPAIR_ATTEMPT_LIMIT`: three semantic attempts have been consumed.
- `EVIDENCE_*_MISMATCH`: final evidence is not about the bound target/revision.

These are stop conditions, not prompts to rediscover the workspace.
