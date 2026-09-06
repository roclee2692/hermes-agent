# Phase 2.3 — CI Failure Repair Loop

This reference freezes the repair-loop contract for the
`cross-platform-porting` Skill. It is an orchestration protocol, not a new
Scanner, Safe Fixer, CI client, or model API. The Harness remains the source of
truth for plans, summaries, and aggregates; Hermes decides what to do next; the
bundled `pre_tool_call` guard decides whether a requested mutation is allowed.

## Evidence-first input

Always read the offline aggregate before opening any CI detail. A remote repair
iteration is valid only when the selected run, attempt, `plan_sha256`, and
`source_revision` identify one source revision. A green GitHub job is diagnostic
metadata, not verification evidence; `summary.json` and the Aggregator decide
the verification level.

The context budget for one failure is deliberately narrow:

1. `verification-aggregate.json`.
2. The failed platform's `summary.json`.
3. The non-passing mandatory step and its raw log.
4. The source locations named by that evidence and the smallest required
   surrounding context.

Do not reopen successful-lane summaries or logs, and do not rescan the whole
repository to rediscover a failure already named by evidence.

## Root-cause classification

Classify before reading unrelated source or proposing a patch:

| Class | Evidence examples | Allowed action |
|---|---|---|
| `code` | compiler error, test assertion, runtime traceback, or platform API failure in a mandatory step | Read only implicated source; guard every destination; make the smallest related patch; run a focused local check; then request the next CI run |
| `dependency` | lock/resolve/install failure, missing package, incompatible toolchain, or dependency metadata error | Do not edit application source. Installation is session-only and separately authorized; otherwise report the dependency blocker |
| `infrastructure` | registry/network timeout, GitHub API failure, runner outage/cancellation, cache outage, or artifact-upload/download failure | Make zero source changes. Retry only the allowed operation and preserve the original evidence; do not invent a portability finding |

If classification is ambiguous, stop with `BLOCKED` and preserve the evidence.
Never convert a provider, network, or artifact error into a semantic repair.

## Bounded repair loop

For a `code` failure:

1. Confirm the failed lane and its source/plan identity from the aggregate.
2. Call `begin-attempt` and reload the manifest before reading or mutating.
3. Call `guard` immediately before each `patch`; one guard result authorizes one
   following patch only.
4. Change only files implicated by the failed evidence. Preserve successful
   lanes and unrelated dirty files.
5. Run the focused local check through `run-focused`, then rescan/verify as
   required by the Plan.
6. Ask for explicit authorization before pushing or rerunning remote CI.
7. Stop after three remote repair iterations. The Aggregator, not the model,
   decides the final verification level.

Provider failures are a separate recovery path: interrupt the session, recover
to `last_known_good`, and allow at most one provider retry. A retry never
authorizes an additional source patch.

For `dependency` or `infrastructure`, do not call `begin-attempt`, do not call
`patch`, and do not change source. A permitted retry must produce fresh,
run-bound evidence before any further decision.

## Benchmark cases

Phase 2.3 is accepted only after both benchmark classes are exercised against a
clean, isolated worktree:

### Case A — platform code failure

Inject one reproducible platform-only defect that static scanning does not
report. The initial remote evidence must contain two successful lanes and one
failed lane. The expected trace is:

```text
aggregate
  -> failed lane summary
  -> failed mandatory step log
  -> implicated source context
  -> guarded minimal patch
  -> focused local check
  -> remote rerun (<= 3 iterations)
  -> aggregate decides TRI_PLATFORM_VERIFIED or a precise blocker
```

Record at least:

```json
{
  "benchmark": "<name>",
  "classification": "code",
  "initial_findings": 0,
  "failed_lane": "<platform>",
  "successful_lanes_reopened": 0,
  "files_read": [],
  "files_changed": [],
  "repair_attempts": 0,
  "remote_iterations": 0,
  "unrelated_files_changed": 0,
  "final_verification": "BLOCKED"
}
```

The concrete values must come from the run; this example is not evidence.

### Case B — infrastructure failure

Inject a registry timeout, GitHub/network failure, runner transient error, or
artifact upload failure after a valid plan is selected. The expected trace is:

```text
failed evidence
  -> classify infrastructure
  -> retry only the permitted operation
  -> zero source changes
  -> preserve the failure evidence or collect a fresh run
```

The benchmark fails if Hermes edits source, fabricates a portability finding, or
counts a retry as a semantic repair. Record the protected-repository delta and
the exact retry count.

## Safety invariants

- Every resumed or retried operation reloads the manifest; cwd is never session
  state.
- Every write is checked by the native guard and remains inside the target
  worktree's allowed roots.
- Successful lanes are preserved and are not reread for a failed-lane repair.
- Infrastructure/dependency failures produce zero source changes by default.
- No more than three remote repair iterations and one provider retry are
  consumed without an explicit user decision.
- Final status is returned by the Aggregator and identity gate, never by model
  self-report.
