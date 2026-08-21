# Research note: should HostShift be written in Mojo?

*Evaluated 2026-08-21 against Mojo 1.0 (stable, released 2026-08-11, Apache-2.0).*

## Verdict

**No rewrite.** Python remains the right implementation language for every
component in this repository. An isolated experimental port of the tree-edit
distance kernel is welcome as a performance study (`experiments/`), but it is
not part of the benchmark and not required for any published number.

## The question, stated precisely

Mojo is a compiled systems language with Python syntax, ownership semantics,
SIMD-first numerics, and CPython interop. "Should this be Mojo?" therefore
decomposes into: *which component has a measured hot path that compiled,
specialized code would make meaningfully faster, and would survive the
ecosystem cost?*

## Where the time actually goes

| Component | Cost profile | Bottleneck |
|---|---|---|
| Generation (LLM API) | ~1,500 calls, seconds each | **network + vendor latency** |
| Operator runs (LLM API) | ~7,200 runs, multiple steps each | **network + vendor latency** |
| Zhang–Shasha TED | O(n²·min-depth²) on UI-scale trees (n ≈ 10–200) | microseconds per pair |
| Cluster bootstrap | resamples of precomputed task outcomes | milliseconds |
| Oracle grading | dict walks over criteria | negligible |

The full planned experiment costs **$350–400 of model API spend and hours of
vendor latency**; the entire offline compute core contributes well under a
second end to end. A 100× speedup of the TED kernel would change the total
runtime by less than the variance between two API calls. Profiling before
porting is the whole lesson, and the profile here points at the network.

## Why not autopilot-fde either

AutoPilot FDE is a FastAPI + Next.js service. Its measured inefficiencies
(fixed in this repository) were architectural, not linguistic: blocking CPU
work inside async handlers, a SQLite connection opened per operation, N+1
Slack API calls, load-everything aggregation. All are fixed with standard
Python tooling (`asyncio.to_thread`, WAL mode + connection reuse, direct
queries). Mojo's web/API ecosystem readiness is roughly 3/10 today — there is
no FastAPI-equivalent framework — so a rewrite would trade solved problems for
unsolved ones.

## What a Mojo experiment should look like (if pursued)

1. Port `widgettree.tree_edit_distance` to a standalone Mojo package.
2. Drive it from Python via a small C ABI or file-fixture harness; keep the
   Python version as the reference oracle.
3. Benchmark on realistic trees drawn from `tasks/reference_specs` at several
   depths, report medians, publish both implementations.
4. Pin the Mojo toolchain version; treat breakage on nightly bumps as expected.

Success criterion: a measurable kernel-level win worth having *after* IPC
overhead, with zero change to any benchmark number. If the win is only visible
in microbenchmarks, the correct action is to write it up and stop.

## Sources consulted

- mojolang.org — Mojo 1.0 announcement, roadmap (Phase 2 "systems application
  programming" still in progress), Python interop docs.
- Ecosystem audits (2026): math/tensor layer production-ready; web/networking
  low-level only; CPython bridge characterized as a migration crutch, not an
  architecture; packaging via pixi (Magic deprecated).
- Independent comparisons: adopt Mojo for measured hot paths / GPU kernels;
  keep workflow orchestration in Python.
