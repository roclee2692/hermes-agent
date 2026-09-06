# Project Status

Status snapshot: 2026-09-06

## Current baseline

The portability Core is frozen at `portability-harness v0.1.0`. The stable
contract is:

```text
scan -> fix --safe -> verify --plan -> render-github -> collect-github -> aggregate
```

The Core is model-independent and does not own GitHub write operations. The
Skill supplies orchestration and decision policy; Hermes' bundled
`portability-execution-guard` enforces the active workspace and mutation policy
through native `pre_tool_call` hooks and a session sandbox/runtime.

No new Scanner rules, Safe Fixer rules, model API, MCP integration, automatic CI
repair, automatic push, PR comments, or merge behavior is planned for the
frozen baseline. A real defect found during use should open a new versioned
change with a regression test rather than silently expanding v0.1.0.

## Acceptance cases

| Area | Current result | Evidence / qualification |
|---|---|---|
| Harness golden E2E | `TRI_PLATFORM_VERIFIED` | GitHub run [33734562738](https://github.com/roclee2692/portability-harness/actions/runs/33734562738); Windows, macOS, and Linux passed with one Plan/source identity |
| Flight-management golden E2E | `TRI_PLATFORM_VERIFIED` | GitHub run [33734027984](https://github.com/roclee2692/flight-management-system/actions/runs/33734027984); mandatory `3/3` and CTest `5/5` per applicable platform |
| GC-MS runtime-enforcement safety benchmark | Safety properties `PASS`; final verification `BLOCKED` | [benchmark-result.json](</Users/raelon/Drives/D-DevWorkspace/portability-sessions/gc-ms-safety-2r-enforced/benchmark-result.json>) and [runtime-enforcement-probe.json](</Users/raelon/Drives/D-DevWorkspace/portability-sessions/gc-ms-safety-2r-enforced/runtime-enforcement-probe.json>) |
| MEDIUM semantic benchmark | Exercised on GC-MS `gpu.acceleration`; not a clean portability success | The isolated worktree remained safe and evidence-bound; dependency installation timed out, so no `TRI_PLATFORM_VERIFIED` claim is made |
| HIGH architectural benchmark | Policy covered; real benchmark not yet run | GC-MS scan had no HIGH findings. The Skill requires a stop/proposal for COM, DirectX, Registry, GUI, driver, CUDA-kernel, and equivalent architecture bindings |
| Phase 2.3 CI failure loop | Protocol frozen; real Case A/B run pending | See [ci-failure-repair-loop.md](optional-skills/migration/cross-platform-porting/references/ci-failure-repair-loop.md) |

## 2.2R closure

The GC-MS regression established the following safety facts:

- the workspace identity remained bound to the isolated GC-MS worktree;
- resume and provider-retry paths reloaded the manifest instead of trusting the
  old cwd;
- the Harness repository, original GC-MS repository, and other protected
  repositories had zero unauthorized writes;
- session virtualenv, caches, bytecode, and temporary paths stayed under the
  session artifact root;
- the native guard blocked forbidden writes, Git mutation, shell mutators,
  application interpreters, and unsandboxed `execute_code`;
- the final `BLOCKED` result is honest: the Python dependency-install step
  reached its 90-second timeout, and no successful verification was fabricated.

The closure implementation was committed in `43c8b8a01`; the Phase 2.3
protocol documentation is committed locally in `9a1733c85` and is being carried
in the same open PR.

## Known limitations

- The local machine cannot substitute for a real multi-OS CI run. Only the two
  recorded golden runs support `TRI_PLATFORM_VERIFIED`.
- The GC-MS safety rerun is an execution-safety acceptance, not proof that the
  ML workload is portable or that its dependency installation completed.
- The Phase 2.3 Case A (platform code failure) and Case B (infrastructure
  failure) benchmark runs have not yet been executed against remote CI.
- A HIGH architecture benchmark has not been executed; the safe outcome is a
  stop/proposal, not an autonomous rewrite.
- Dependency installation remains explicit, session-only, and subject to
  external network/registry availability.
- GitHub collection requires an authenticated read-only `gh` adapter. Git
  writes remain outside the Core's authority.

## Future Work

Phase 2.4 and Phase 2.5 are future work only and do not affect V1 acceptance:

- **Phase 2.4 — Hermes E2E benchmark:** run the real Case A/B CI failure-loop
  corpus, collect repair metrics, and exercise bounded failed-lane repair.
- **Phase 2.5 — upstream preparation:** polish the thin Skill for open-source
  community submission, packaging, examples, and contributor documentation.

Neither phase authorizes changes to the frozen Core contract or turns a green
job into evidence. Any Core change discovered during real use must be proposed
as a new version with focused regression evidence.

## Pull request state

PR [#1](https://github.com/roclee2692/hermes-agent/pull/1) remains open and
unmerged. Keeping it open is intentional while the Skill and runtime guard are
used in real repositories and any follow-up issues are evaluated for a future
version.
