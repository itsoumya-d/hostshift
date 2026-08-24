# Customizing HostShift

HostShift is built to be forked and pointed at *your* question. Everything a
fork needs to touch lives in declarative files, not buried code. This guide
covers the local knobs and the GitHub-native workflow (Actions, secrets,
repository variables) for running your own variant of the benchmark.

---

## 1. The five customization surfaces

| What you want to change | Where | How |
|---|---|---|
| The tasks | `tasks/suite_v1.jsonl` (or your own file + `--suite`) | Add/replace JSONL rows |
| The interface contract | `schema/uispec.schema.json` + `hostshift/render/semantics.py` | Extend the spec language; implement in the reference interpreter first |
| Host capabilities | `hostshift/render/base.py` (`HostProfile`) | Edit the declarative table |
| Renderer behavior | `hostshift/render/<host>.py` (`RendererProfile`, templates) | Careful vs naive arms |
| Operators & generators | `hostshift/harness.py` adapters | Implement the Protocol |

### Swap the task suite

```bash
hostshift lint --suite tasks/my_suite.jsonl     # validate before spending anything
hostshift plan --suite tasks/my_suite.jsonl     # cost estimate for YOUR matrix
```

Or set it once for a session: `export HOSTSHIFT_SUITE=tasks/my_suite.jsonl`.
Every task must satisfy the linter (`hostshift/oracle.validate_suite`):
unique `<category>-<number>` id, state-based criteria, resolvable
`reference_spec`. Run `python3 scripts/e2e.py` after adding tasks — it proves
a correct spec driven by a perfect operator yields zero host-lock on your new
rows.

### Tune the experiment scope

`hostshift plan` prints its levers with your flags:

```bash
hostshift plan --generators gemini,claude --hosts web,compose,tui \
               --repeats 2 --avg-steps 10 --cost-per-step 0.003
```

The defaults reproduce the paper's 100×3×4×3 matrix (~$350–400); the levers
exist so you can buy back feasibility without silently weakening inference.

### Add a host

1. Renderer emitting source files: `hostshift/render/<host>.py`
2. Session class implementing the `Session` protocol (device-backed — see
   `assert_measurable`; simulated sessions cannot produce paper numbers)
3. A row in `PROFILES` (`render/base.py`)
4. Cross-implementation agreement tests like `tests/test_crossimpl.py`
5. Register in `HOSTS` (`render/__init__.py`) and `harness.HOSTS`
6. **Conformance gates (mandatory)**: a hostile-spec fixture in
   `tests/test_embedding_roundtrip.py`, an entry in
   `native_conformance.embedding_roundtrip()`, and a toolchain check in
   `compile_native()` — see CONTRIBUTING.md's *Renderer embedding rule*.
   `flutter.py` is the worked example, added end-to-end in one cycle.

### Change scoring or reporting

All aggregation is pure functions over run records:
`metrics.py` (IP/HLI/bootstrap/McNemar), then `_compute_tables()` in
`runner.py`. `hostshift report --json` gives you the same numbers as data for
your own analysis; prefer extending that path over editing the printers.

---

## 2. Fine-tuning inside GitHub

### Repository variables vs secrets

Set these under **Settings → Secrets and variables → Actions**:

| Name | Type | Used by | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | secret | computer-use operator | Only needed when running real operator loops — never used by CI |
| `AUTOPILOT_*` / host creds | secret | your forks' device jobs | Simulator/emulator credentials if you add device jobs |

Secrets are **not** needed by this repository's CI; keep it that way. The
default workflows are credit-free by construction.

### Workflows shipped

- `.github/workflows/ci.yml` — lint, wheel-build smoke, 200+-assertion suite,
  filter-spec solvability, ≥80% coverage gate, Python 3.11–3.14 matrix.
- `.github/workflows/experiment.yml` — **Run workflow** button in the Actions
  tab runs the synthetic pipeline check (`demo`) end-to-end and uploads
  `runs/demo/runs.jsonl` plus `report.json` as artifacts. Zero API spend;
  use it to verify a fork's plumbing before your first real dollar.

To add a real-experiment job, start from `experiment.yml`, gate it behind
`workflow_dispatch` + an environment with required reviewers, and read
`GEMINI_API_KEY` from that environment — never from a broader scope.

### Suggested branch protection

- Require the `test` job (CI) before merge.
- Require linear history; benchmark numbers must stay traceable to one commit.
- Tag releases `vX.Y.Z`; `stamp_provenance` watermarks run logs with the
  harness fingerprint, so published results name their exact code.

### Fork-and-extend checklist

1. Fork; enable Actions.
2. Run **Experiment pipeline check** once — green means your fork's pipeline
   is sound.
3. Replace `tasks/suite_v1.jsonl` (keep `suite_v0.jsonl` for provenance).
4. Adjust `HostProfile` rows only if you have measured the divergence.
5. Re-run `hostshift demo` locally; commit both suites so reviewers can diff.
6. Publish runs with `report --json` output committed alongside raw records.

---

## 3. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `HOSTSHIFT_SUITE` | auto-resolved | Absolute path to your task suite |
| `HOSTSHIFT_ALLOW_SIMULATED` | unset | `1` permits simulated sessions for pipeline work. Never set it in production runs. |

Missing Playwright browsers? `pip install playwright && playwright install
chromium`. Missing `GEMINI_API_KEY`? The computer-use operator raises with
instructions instead of degrading silently.

---

## 4. Performance notes

- The offline core (interpreter, oracle, TED metrics) is pure Python and fast;
  `run_tests.sh` completes in ~25 s including golden-source checks.
- Bootstrap intervals dominate `report` time at high `--boot`; drop to
  `--boot 1000` for iteration and reserve 4000+ for final numbers.
- Device-backed web sessions reuse one Chromium instance per process via
  `WebSession`; launch cost is paid once per session, not per action.
