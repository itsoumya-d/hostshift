# TED kernel performance study

The experiment `research/MOJO.md` prescribes: benchmark the tree-edit-distance
kernel that powers Render Parity, keep Python as the reference oracle, and let
a compiled port earn its way in — or write it up and stop.

## Protocol

1. **Structural distance only.** Both implementations measure kind/shape TED:
   accessible-name drift is charged at 0.5 by the production metric
   (`hostshift.widgettree.default_relabel_cost`) but is out of scope here,
   because the file-fixture protocol carries no strings. The production
   number is a strict superset of this one.
2. **Realistic workloads.** A synthetic scaling ladder (n = 16 → 256 nodes,
   seeded RNG, structural perturbations of ~10% of leaves — the shape of
   divergence real host realizations produce) plus genuine pairs drawn from
   `tasks/reference_specs`.
3. **Correctness before timing.** Symmetry, self-distance zero, and normalized
   parity bounds are asserted over every pair before any number is recorded.
   Any Mojo build must agree with the Python oracle to 1e-4 on every fixture
   case before it is timed for the record.
4. **Medians, pinned toolchain.** 15 repetitions per cell, median reported.
   The Mojo side pins toolchain >= 1.0; nightly breakage is expected.

## Python baseline (measured 2026-08-21, Apple Silicon, Python 3.14)

| pair | \|a\| | \|b\| | TED | median ms |
|---|---:|---:|---:|---:|
| synthetic-n16 | 16 | 16 | 1.0 | 0.41 |
| synthetic-n64 | 64 | 60 | 5.0 | 24.22 |
| synthetic-n128 | 128 | 126 | 7.0 | 63.01 |
| synthetic-n256 | 256 | 247 | 18.0 | 497.92 |
| ref-first-vs-last | 7 | 5 | 2.0 | 0.04 |
| ref-mid-vs-last | 4 | 5 | 1.0 | 0.02 |

Reading: real spec-derived trees are tiny (≤ ~40 nodes) and cost **micro- to
sub-milliseconds**; even a pathological 250-node near-miss costs half a
second *once*, while the experiment's dominant cost remains ~7,200 operator
API calls at seconds each. This is the profile behind the "no rewrite"
verdict in `research/MOJO.md`.

## Mojo port

`ted.mojo` is source-complete against the fixture protocol:

```bash
python3 benchmark.py --emit fixtures/
cd experiments/ted_benchmark
mojo build ted.mojo -o ted_bench        # pin >= 1.0; record the version
python3 benchmark.py --with-mojo ted_bench
```

The runner cross-checks every case against the Python oracle before timing.
**The Mojo column stays empty until someone runs those three commands on a
pinned toolchain and commits the output** — an unverified timing claim is
worse than none.

Reproduce the Python table:

```bash
python3 experiments/ted_benchmark/benchmark.py
```
