# Research note: should HostShift (or AutoPilot FDE) be written in Mojo?

*Evaluated 2026-08-21 against Mojo 1.0 (stable, released 2026-08-11, Apache-2.0 stdlib).*
*Second pass: incorporates the v1.0.0 release notes, the SC'25 independent kernel
evaluation (Oak Ridge / U. Tennessee), and 2026 ecosystem audits.*

## Verdict

**No rewrite — for either codebase.** Python remains the right implementation
language for every component shipped here. An isolated experimental port of the
tree-edit distance kernel is welcome as a performance study (`experiments/`),
but it is not part of the benchmark, changes no published number, and should be
treated as a write-up-and-stop exercise unless it clears a real bar.

## The question, stated precisely

Mojo 1.0 is a compiled systems language with Python-like syntax, ownership
semantics, SIMD-first numerics, CPython interop, and CPU/GPU targets. It left
beta on 2026-08-11 with a stability commitment ("mostly additive through 1.x")
and an open-source standard library; the compiler toolchain itself is committed
to open-sourcing during 2026. "Should this be Mojo?" therefore decomposes into:
*which component has a measured hot path that compiled, specialized code would
make meaningfully faster, and would survive the ecosystem and integration
costs?*

## Where the time actually goes (HostShift)

| Component | Cost profile | Bottleneck |
|---|---|---|
| Generation (LLM API) | ~1,500 calls, seconds each | **network + vendor latency** |
| Operator runs (LLM API) | ~7,200 runs, multiple steps each | **network + vendor latency** |
| Zhang–Shasha TED | O(n²·min-depth²) on UI-scale trees (n ≈ 10–200) | microseconds per pair |
| Cluster bootstrap | resamples of precomputed task outcomes (4k draws × ~800 rows in `report`) | tens of milliseconds |
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
queries). Every remaining request path is I/O-bound — SQLite round-trips,
Slack/WhatsApp HTTP, LLM enrichment — which is precisely the workload class
where compiled-language gains round to zero. Mojo's web/API ecosystem
readiness is roughly 3/10 today: there is no FastAPI-equivalent framework, no
production async-I/O story, and no native OpenTelemetry/observability layer.
A rewrite would trade solved problems for unsolved ones.

## What the independent evidence says about Mojo 1.0

**Where Mojo genuinely wins (third-party verified):**

- Memory-bound GPU kernels approach or match CUDA/HIP on H100 and MI300A
  (SC'25 poster, Oak Ridge NL & U. Tennessee: BabelStream operations at or
  above CUDA baseline; seven-point stencil at ~87% of CUDA on H100, 100% of
  HIP on MI300A).
- Compute-bound kernels still lag: fast-math gaps and immature atomics,
  orders-of-magnitude deficits on AMD for atomic-heavy workloads.
- Native SIMD/numerics are production-grade (`SIMD[DType.f32, width]`,
  buffer/tensor packages), and MAX serving is production-ready.

**Where it does not, yet:**

- No first-party data-processing stack (no pandas/polars equivalent), thin
  stdlib beyond math/tensor/GPU layers, packaging via pixi with real CI
  friction, limited debugging/observability tooling.
- The CPython bridge is a migration crutch, not an architecture: every
  crossing pays GIL/marshal/refcount overhead. Mojo 1.0 made interop hot
  paths ~12× faster than before — but that optimizes a boundary you only
  tolerate, not one you build on. Teams repeatedly report end-to-end latency
  unchanged after porting because the boundary eats the kernel win.
- Compile-time specialization (layouts/types known statically) is a poor fit
  for our trees: UISpec documents are dynamic, heterogeneous, runtime-shaped
  data. Fighting that in a systems language buys nothing a dict walk doesn't
  already give us.

## What a Mojo experiment should look like (if pursued)

1. Port `widgettree.tree_edit_distance` to a standalone Mojo package.
2. Drive it from Python via a small C ABI or file-fixture harness; keep the
   Python version as the reference oracle. Budget for the boundary: marshal
   both trees once per batch, never per node.
3. Benchmark on realistic trees drawn from `tasks/reference_specs` at several
   depths, report medians, publish both implementations.
4. Pin the Mojo toolchain version; treat breakage on nightly bumps as expected.

Success criterion: a measurable kernel-level win worth having *after* IPC
overhead, with zero change to any benchmark number. If the win is only visible
in microbenchmarks, the correct action is to write it up and stop.

## Revisit triggers

The verdict flips when any of these becomes true:

1. A measured profile shows >10% wall time in offline compute (it is <1% today).
2. Mojo ships a maintained asyncio-grade networking story plus a
   web framework ecosystem (Phase 2 of its roadmap, currently in progress).
3. The compiler lands fully open source and distro-packaged, removing the
   closed-toolchain audit risk.
4. This project's scale changes by orders of magnitude (e.g., streaming
   parity measurement over live device sessions at thousands of ops/sec).

## Sources consulted

- mojolang.org — Mojo 1.0 announcement, roadmap (Phase 2 "systems application
  programming" in progress), v1.0.0 release notes (stability policy, 12×
  interop hot-path gain, shared-library runtime init), llms.txt doc index.
- Modular 26.5 blog — 1.0 rationale, compiler open-source commitment for 2026.
- SC'25 poster (Melnichenko, Godoy, Valero-Lara — ORNL / U. Tennessee),
  "Mojo: Python-like MLIR-based GPU portable science kernels" — H100/MI300A
  measurements cited above.
- KruN ecosystem audits (2026): readiness table (math/tensor 9/10, inference
  8/10, web/networking 3/10, data processing 4/10); CPython-bridge overhead
  measurements; adoption-cost guidance.
- The Consensus (2026-03): "Mojo's not (yet) Python" — practical syntax/
  toolchain gaps against Python compatibility expectations.
- Independent comparisons: adopt Mojo for measured hot paths / GPU kernels;
  keep workflow orchestration in Python.
