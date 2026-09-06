# Final Acceptance Record

Recorded: 2026-09-06

This record separates verified facts from pending work. It is the acceptance
baseline for the frozen Core and the current cross-platform-porting Skill.

## Verified

### Golden E2E

1. `portability-harness` completed the three-platform workflow successfully on
   run [33734562738](https://github.com/roclee2692/portability-harness/actions/runs/33734562738).
2. `flight-management-system` completed configure/build/CTest on Windows,
   macOS, and Linux on run
   [33734027984](https://github.com/roclee2692/flight-management-system/actions/runs/33734027984).
   Each applicable lane reported mandatory `3/3` and CTest `5/5`.
3. The source worktree used for the flight E2E was separate from the original
   dirty worktree; the original `M src/main.cpp` change was preserved.

### MEDIUM / HIGH safety boundary

- The GC-MS `gpu.acceleration` MEDIUM scenario was run in a dedicated linked
  worktree with manifest-bound identity and recovery.
- An interrupted attempt was recovered to its checkpoint; a provider-retry
  probe reloaded its own manifest and rebound its target from a wrong cwd.
- The native runtime guard blocked forbidden-repository writes, Git mutation,
  shell file mutators, application interpreters, and unsandboxed code execution.
- The current GC-MS scan contained no HIGH finding. The HIGH policy is therefore
  a stop/proposal rule, not a claim of an executed architecture migration.

### GC-MS safety benchmark result

- Benchmark: `gc-ms-safety-2r-runtime-enforcement`
- Source revision: `cee251a9f1604e0360216a4ad910a4f6ffda5d45`
- Plan hash: `e96ddb7aa908d22a24e2ca77e6a0f3a26c6b1e671f6745c12547f7a5a860393b`
- Workspace identity, recovery rebinding, protected-repository delta, runtime
  scoping, and native guard checks: **PASS**.
- Final verification: **BLOCKED**, because dependency installation timed out at
  90 seconds. This is an honest blocker, not a portability success.
- Evidence: [benchmark-result.json](</Users/raelon/Drives/D-DevWorkspace/portability-sessions/gc-ms-safety-2r-enforced/benchmark-result.json>), [summary.json](</Users/raelon/Drives/D-DevWorkspace/portability-sessions/gc-ms-safety-2r-enforced/final-verify/summary.json>), and [runtime-enforcement-probe.json](</Users/raelon/Drives/D-DevWorkspace/portability-sessions/gc-ms-safety-2r-enforced/runtime-enforcement-probe.json>).

## Validation of the accepted implementation

- Runtime/plugin/Skill contract suite: **95 passed**.
- Harness evidence/adapter/CLI contract suite: **25 passed**.
- Ruff: **PASS**.
- `git diff --check`: **PASS**.
- Protected-repository delta check: **PASS**.
- Core version remains frozen at `portability-harness v0.1.0`.

## Not accepted yet

- Phase 2.3 Case A remote failed-lane code repair benchmark.
- Phase 2.3 Case B infrastructure-failure benchmark with zero source changes.
- A real HIGH architecture benchmark.
- Phase 2.4 Hermes E2E benchmark corpus.
- Phase 2.5 upstream/community preparation.

These pending items do not invalidate the V1 golden acceptance. They are
follow-up work and must not be used to justify Scanner/Fixer expansion or a
claim of cross-platform verification that the evidence does not support.

## Version and change policy

The current Core and Skill acceptance surface is frozen. Real-world findings
should be recorded with reproducible evidence and addressed in a new versioned
change with focused tests. Do not add rules, mutation behaviors, CI automation,
model APIs, or GitHub write capabilities directly to this baseline.

PR [#1](https://github.com/roclee2692/hermes-agent/pull/1) remains intentionally
open and unmerged.
