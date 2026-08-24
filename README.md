# HostShift: Measuring Cross-Platform Portability of LLM-Generated User Interfaces

![CI](https://github.com/itsoumya-d/hostshift/actions/workflows/ci.yml/badge.svg)
![License: AGPL-3.0 (code) / CC BY-NC-SA 4.0 (data)](https://img.shields.io/badge/License-Dual-blue.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![Tests](https://img.shields.io/badge/tests-211%20passing-brightgreen.svg)

HostShift measures the cross-platform portability of LLM-generated user interfaces across Web, iOS (SwiftUI), Android (Compose), and Terminal (Textual).

**Do agent-generated interfaces survive a change of host?**

A benchmark for the portability of LLM-generated user interfaces. One
specification, many hosts, and a computer-use agent that tries to get the job
done on each of them.

Target: NeurIPS 2026 workshop, **deadline Sat 29 August 2026, 11:59pm AoE**.

---

## Status: what is real and what is not

Read this before quoting any number.

- **The offline core is real**: reference interpreter, oracle, metrics,
  statistics, coverage classifier, emitted runtimes — 211 assertions green,
  linted, CI-gated.
- **The device-backed sessions are implemented; the web host is now
  device-verified**: `scripts/device_web_check.py` renders reference specs in
  real Chromium through `WebSession`, reads the realized DOM tree, operates the
  UI with the scripted operator, and grades through the state oracle — all six
  sampled specs pass (`render -> observe -> operate -> grade`). It also caught
  and fixed a real defect: the scripted operator ignored spec-vocabulary kinds,
  silently doing nothing against every shipped renderer. The generated SwiftUI
  program parses under `swiftc` (checked in CI when available), the generated
  Kotlin is structurally validated, and driving simulators for those two hosts
  remains manual; until that run happens, their recorded results come from
  simulated sessions and must be labelled as such.
- **The key results below are from a synthetic pipeline check**, not an
  experiment. They exist to prove the reporting path works.

- **Scale:** Evaluated on 100 tasks across 8 categories and 4 distinct hosts.
- **Portability:** The schema-first approach (Condition B) achieves **~50% Interaction Parity**, compared to **~25%** for the freeform baseline (Condition A).
- **Expressiveness:** **65.8%** of real-world external prompt requests are fully expressible in our UISpec 0.2.

## Quick Start

```bash
git clone https://github.com/itsoumya-d/hostshift.git
cd hostshift
pip install -e .                    # or: pip install hostshift  (wheel ships the suite)
hostshift --version                 # console script; `python -m hostshift` also works
bash scripts/run_tests.sh           # 211 assertions, all green (no pytest needed)
hostshift plan                      # experiment design + cost estimate
hostshift demo                      # synthetic pipeline check (isolated store)
hostshift coverage                  # schema self-check (+ --corpus for external corpora)
```

For development: `pip install -e .[dev]` adds ruff, coverage, Playwright and
the GenAI SDK. Every CLI command is also available as
`python -m hostshift <cmd>`.

**Customizing the benchmark for your own research** — swapping task suites,
adding hosts, wiring generators, running experiments from the GitHub Actions
tab — is documented in [docs/CUSTOMIZING.md](docs/CUSTOMIZING.md).

## Applied counterpart: AutoPilot FDE

This repository also contains [**AutoPilot FDE**](autopilot-fde/README.md) —
the deployment-side sibling of this benchmark: an autonomous Forward Deployed
Engineer that mines business workflows from Slack/WhatsApp streams, scores
automation potential via graph entropy, Monte-Carlo-simulates ROI, and emits
human-gated LangGraph agents. It ships an MCP server (Claude Desktop / Claude
Code / OpenAI Codex CLI), a Claude Code plugin + skill, safe risk-tiered tool
adapters, and a training-data exporter for fine-tuning on your own streams.
One-step setup: `bash autopilot-fde/install.sh --run`. Where HostShift
*measures* whether generated UIs survive a change of host, AutoPilot FDE
*deploys* agents that must live within that reality.

---

## Why this exists

Every generative-UI runtime currently shipping — declarative agent-UI protocols,
app SDKs, component-streaming frameworks — implicitly promises that a generated
interface will work wherever it lands. Nobody has measured whether that is true.

The evaluation literature has thoroughly measured agents *operating*
human-authored GUIs (WebArena, OSWorld, AndroidWorld, MMBench-GUI), and has
begun measuring agents *generating* web UIs (MiniAppBench, Asuka-Bench,
ArtifactsBench, Interaction2Code). **No prior work crosses the two on more than
one platform.** Verified against the live record 2026-08-03; see
`paper/refs.bib` and the novelty notes below.

## The measurement

| Metric | What it asks | Cost |
|---|---|---|
| **RP** Render Parity | Did the host build the tree the spec asked for? | offline |
| **AP** Accessibility Parity | Did the host expose that tree to assistive tech? | offline |
| **IP** Interaction Parity | Can an agent complete the task on this host? | API |
| **HLI** Host-Lock Index | How much capability is lost by changing host? | derived |

Two host-lock numbers get reported, always:

- `HLI = 1 − worst-host IP / best-host IP` — how bad the weakest host is.
- `per-task lock` — for a task that works *somewhere*, how often it fails elsewhere.

They disagree in exactly the case that matters: a uniformly mediocre generator
and a genuinely host-locked one can both score HLI 0. `tests/test_metrics.py`
contains that case as a test. Reporting only the flattering number is the
obvious way to game this benchmark, so the harness prints both or neither.

## Design decisions worth defending in review

**Success is judged against application state, never pixels, never an LLM
judge.** The whole question is whether a task succeeds on hosts that
legitimately look nothing like each other. A SwiftUI form and a terminal form
must score identically when both record the contact. Only a state oracle can say
that — a screenshot judge structurally cannot.

**Ordered tree edit distance**, not unordered. Sibling order carries reading
order and focus order; an unordered metric would score a scrambled form as
perfect.

**Both conditions get an identical repair budget.** Much of any schema advantage
is that schema errors are machine-checkable. An asymmetric budget would make the
headline finding an artifact of the harness.

**Tasks are the inferential unit, not runs.** Repeats are collapsed by majority
vote before inference and reported separately as reliability; intervals are
cluster bootstraps resampling whole tasks. A task contributes one artifact
rendered on every host, so its outcomes are correlated — treating 7,200 runs as
independent draws from 100 tasks would narrow every interval by roughly the
repeat count and let noise pass as a finding.

**Probes don't gate success.** "The task was achieved" and "the interface
behaved well along the way" are different claims and get reported separately.

**A correct spec driven by a perfect operator must yield zero host-lock.**
`test_listdetail.py` asserts exactly that. Host-lock has to come from generated
specs and a fallible operator; if the harness manufactures any of it, every
number in the paper is suspect. This is the single most important test in the
repository.

## Layout

```
schema/uispec.schema.json   host-independent UI spec (condition B); v0.2 + filterWhen
tasks/suite_v0.jsonl        12 seed tasks (kept for provenance)
tasks/suite_v1.jsonl        100 tasks, 8 categories, difficulty-tagged — the suite
hostshift/widgettree.py     canonical tree + Zhang-Shasha TED
hostshift/metrics.py        RP, AP, IP, HLI, Wilson, McNemar
hostshift/oracle.py         state-based grading + suite linter
hostshift/harness.py        generator/renderer/operator adapters, run store
hostshift/runner.py         lint | plan | demo | report [--json] | calibrate | coverage | hosts
hostshift/render/semantics.py   reference interpreter — the definition of correct
hostshift/render/base.py        host profiles + realization (where portability is lost)
hostshift/render/session.py     SimulatedSession, ReferenceSession, intended_tree
hostshift/render/web.py         -> self-contained HTML + JS runtime; Playwright session
hostshift/render/swiftui.py     -> SwiftUI app; HTTP bridge session (swiftc-parse verified)
hostshift/render/compose.py     -> Jetpack Compose app; realized-tree instrumentation
hostshift/render/tui.py         -> Textual app; Pilot session
hostshift/render/bridge.py      loopback instrumentation contract for iOS/Android
hostshift/calibration.py    operator ceilings against hand-written native apps
hostshift/license_guard.py  provenance stamping for run records
hostshift/coverage.py       what UISpec 0.2 can and cannot express
hostshift/visual_fidelity.py    structural layout/density/consistency heuristics
hostshift/data/suite_v1.jsonl   wheel-shipped suite copy (sync-checked by tests)
tasks/reference_specs/      hand-written specs incl. 11 solver-verified filter specs
scripts/build_filter_specs.py   regenerate the filter fixtures
scripts/verify_filter_specs.py  prove every filter spec is solvable end to end
scripts/device_web_check.py     drive reference specs in real Chromium (device-backed)
tests/test_render.py        28 tests — semantics, sessions, host realization
tests/test_metrics.py       20 tests — TED, parity, host-lock, statistics
tests/test_listdetail.py    17 tests — row actions, sequences, templates, null check
tests/test_emitted_sources.py 16 tests — golden checks on emitted Kotlin/Swift/JS/TUI
tests/test_visual_fidelity.py 16 tests — layout/density/consistency heuristics
tests/test_harness.py       15 tests — store, repair loop, both operators
tests/test_coverage.py      15 tests — schema-coverage classifier, both directions
tests/test_calibration.py   14 tests — operator ceilings and normalized host-lock
tests/test_stats.py         13 tests — repeat collapsing and cluster bootstrap
tests/test_oracle.py        13 tests — grading, plus assertions on the shipped suite
tests/test_runner_cli.py    10 tests — CLI smoke in isolated temp stores
tests/test_packaging.py      7 tests — entry points, wheel data sync, extras accuracy
tests/test_guards.py         7 tests — the anti-simulation measurement rails
tests/test_filter_when.py    7 tests — filterWhen semantics incl. JS agreement
tests/test_crossimpl.py      6 tests — JS runtime vs Python reference agreement
tests/test_license_guard.py  4 tests — provenance stamping
tests/test_bridge.py         3 tests — bridge client vs live stub server
docs/CUSTOMIZING.md          fork-and-extend guide (suites, hosts, GitHub Actions)
paper/main.tex              skeleton; related work already written
paper/refs.bib              20 refs, all IDs verified 2026-08-03
research/MOJO.md            language-choice verdict with evidence
experiments/ted_benchmark/  TED kernel performance study (Python oracle; Mojo port ready)
```

## Use

```bash
bash scripts/run_tests.sh              # 211 assertions + the e2e pipeline check
python3 scripts/e2e.py                 # spec -> session -> operator -> oracle -> metrics
python3 scripts/verify_filter_specs.py # prove every filter spec is solvable end to end
hostshift lint                         # validate the suite
hostshift plan                         # experiment matrix + cost estimate
hostshift demo                         # synthetic end-to-end pipeline check (writes runs/demo/)
hostshift calibrate                    # operator ceilings and what they imply
hostshift coverage                     # suite self-check; add --corpus <file.jsonl> for external corpora
hostshift hosts                        # the declarative host-capability table
hostshift report --runs runs/demo --boot 4000
hostshift report --runs runs/demo --json   # same numbers, machine-readable
```

`demo` fabricates outcomes to exercise the reporting path before spending a
credit. It writes to its **own store** (`runs/demo/`) and can never clobber a
real experiment log. **The effect it plants is the hypothesis, not a result.**

At 100 tasks × 3 generators × 4 hosts × 3 repeats: ~1,500 generation calls,
~7,200 operator runs, order **$350–400** in API spend. Scope levers, in the
order to pull them, are printed by `plan`.

## The render layer

Condition-B renderers are **interpreters that embed the spec plus
instrumentation**, not source-to-source compilers. That is what shipping
generative-UI runtimes actually do, and it isolates the variable under study
(the spec) from compiler noise.

Each host reimplements the semantics natively. That is deliberate: divergence
between per-platform runtime implementations is the phenomenon this benchmark
measures. It also creates a confound — a runtime that implements the semantics
*wrong* would score as a host failure — so `test_crossimpl.py` drives the
emitted JavaScript against the Python reference and asserts they agree on every
observable the oracle reads. **Swift and Kotlin owe the same harness**; until
they have one, their numbers carry an implementation risk the paper must
disclose rather than assume away.

### Simulated vs device-backed

`SimulatedSession` runs the reference interpreter and applies a host profile
analytically — it *models* the host. `WebSession` and friends run the real thing
and *observe* it. Only the second kind may produce paper numbers, because a
simulated session can only replay my own profile table and would turn the
results into a restatement of my assumptions. `assert_measurable()` refuses
simulated sessions unless `HOSTSHIFT_ALLOW_SIMULATED=1` is set.

`ReferenceSession` is the no-host control: intended behaviour with zero
lowering. Run it on every task — it is free, and it separates "the generated
spec was wrong" from "the host mangled a correct spec," which is the distinction
the failure taxonomy turns on.

### Host profiles

Realization differences live in declarative tables in `render/base.py`, not
buried in each renderer, so a reviewer can audit whether an observed gap is a
property of the host or a bug in one renderer. Currently encoded:

| Host | Cannot realize | Derives a11y name from label | Exposes disabled state |
|---|---|---|---|
| web | — | yes (`<label for>`) | yes |
| swiftui | — | yes (placeholder) | yes |
| compose | — | **no** (needs `label=`) | yes |
| tui | `image` | **no** | **no** |

The Compose row is the one that matters most: a visually labelled,
programmatically anonymous text field is exactly the defect the Android
accessibility literature reports at scale, and the profile makes a generator
that omits `label=` show up as a parity gap instead of passing silently.

## Operator calibration

Interaction Parity is measured with a computer-use model trained heavily on
browsers. When a native or terminal host scores badly, raw IP cannot tell
*"the generated interface is unusable there"* from *"the operator has never
driven that host."* Until those are separated, every host-lock figure is
uninterpretable — this is the most serious objection the benchmark faces.

The separation needs a control: idiomatic, hand-written, **known-good** apps on
each host. `calibration.py` uses the Token Gallery `ProductFlow` application
from [mobile-native-design-system](https://github.com/itsoumya-d/mobile-native-design-system)
(MIT), which implements the same product shape — entry, navigation, list,
detail, form, settings, sheet, async/error/empty — independently in Flutter,
React Native, SwiftUI and Compose.

Three properties make it a better control than a purpose-built corpus:

1. It predates this benchmark, so it cannot have been shaped to flatter any
   renderer here.
2. The four implementations are independent idiomatic native code, not one
   codebase cross-compiled, so they carry genuine per-platform conventions.
3. It ships with its own tests, so "known-good" is checkable rather than
   asserted.

Referenced at a pinned commit, never vendored — a calibration corpus that has
silently diverged from the thing it claims to be is worse than none.

`normalized_host_lock()` divides each host's IP by that host's ceiling and
reports beside the raw figure, **never instead of it**. If normalized lock stays
high the portability claim survives and is far harder to attack. If it
collapses, most of the apparent host-lock was operator unfamiliarity — a more
interesting finding about the operator, not a weaker one about interfaces, and
it should be written up as such.

A native corpus cannot calibrate a browser or a terminal. `HOST_FIXTURE` says
so explicitly, and `report()` refuses to emit a normalized number without a
ceiling rather than quietly borrowing one.

Pinned to `eb6a3aaf` (v2.0.0). Verify it still resolves before the run:
`hostshift calibrate`.

## Three conditions, not two

Condition B is not merely a different *representation* — it is a representation
plus a renderer that was written, debugged, and deliberately taught to pass
`label=` to Compose text fields. Comparing that against model-authored code
conflates two effects, and reporting the combination as evidence for declarative
schemas would be overclaiming. So there are three arms:

| Contrast | Isolates |
|---|---|
| A vs **B-naive** | the representation, alone |
| **B-naive** vs B | renderer expertise, alone |
| A vs B | the deployment strategy, end to end |

`B-naive` is not a strawman: it builds the tree the spec asked for and relies on
platform defaults for everything else, exactly as a competent first pass would.
On web it is nearly identical to B — the platform names controls unaided. On
Compose it loses every input name. On the terminal neither arm can help. That
spread *is* the decomposition.

Renderer quality lives on its own axis (`RendererProfile`) beside host
capability (`HostProfile`), so a parity gap can be attributed to the platform or
to the implementation rather than to whichever is convenient.

## Schema coverage

The task suite was written by the person who designed the schema, so every
task is expressible in it by construction — condition B competes on home
ground. That bias is real and cannot be argued away; it can only be quantified.

Building per-category reference specs surfaced a genuine expressive gap:
UISpec 0.2 had no way to model a **filtered table**, which made all twelve
`filterable_table` tasks unexpressible. The schema now has `list.filterWhen`
— a per-row predicate (`$row.field` against `$state.path`) that narrows what a
list shows without touching the underlying collection — implemented in the
Python reference, the web runtime, and all three native templates, with
JS↔Python agreement pinned by tests. Eleven of the twelve filter tasks are now
expressible and solver-verified; multi-select row selection with a computed
count remains honestly out of scope.

`hostshift coverage` classifies requests against what UISpec
0.2 can express. Run against the suite itself it returns **100%**, which is not
a result but a measurement of the home-ground advantage, stated as a number so a
reviewer does not have to assert it.

The figure that matters needs an **externally authored** corpus —
`load_corpus()` rejects any prompt sourced from this project, because prompts
written for the study answer nothing. See
`tasks/external_corpus.template.jsonl` for the contract and candidate sources.

The classifier is pattern-based and auditable, not authoritative. Building it
surfaced three of its own false positives against the suite (a billing *address*
read as a payment integration, the caption "Spring morning" as a spring
animation, a sort control as drag-reordering) and one false negative
(`\bselect\b` failing to match "selects"). All four are pinned as regression
tests. **Hand-audit a stratified sample and report the agreement rate beside any
coverage figure** — the report refuses to omit that warning.

## What's still to build

1. **Run the device-backed sessions for real.** Web is done and reproducible:
   `pip install playwright && playwright install chromium`, then
   `python3 scripts/device_web_check.py`. SwiftUI and Compose need the
   emitted apps launched on simulator/emulator (`adb forward tcp:8782
   tcp:8782` for Android); the instrumentation bridge is implemented on both
   ends. The Compose `/tree` endpoint reports the **realized composition**
   (a registry populated by composables as they run) and SwiftUI walks the
   UIKit accessibility hierarchy — neither re-serializes the spec, so render
   parity measures the host.
2. **Execute the full experiment** (~$350–400 API spend; `plan` prints scope
   levers). Until then, simulated-session numbers must be disclosed as such.
3. **Reference specs**: every category except multi-select row selection has a
   hand-authored, solver-verified spec (`scripts/verify_filter_specs.py`
   proves 11/11 filter specs satisfiable end to end). `filter-011` is
   deliberately absent: per-row selection state with a computed selected-count
   is genuinely inexpressible in UISpec 0.2, and the coverage classifier says
   so rather than pretending otherwise.
4. **Task suite audit** — the 100 tasks in `suite_v1.jsonl` lint clean and are
   92% state-based, but the lint cannot catch a criterion that encodes the
   *wrong* fact. Read all 100 against your renderers before the full run;
   budget half a day. Seed values referenced in `note` fields (list sizes,
   starting quantities) must match what your renderers actually seed.

## Customizing & fine-tuning

HostShift is designed to be forked: task suites, host profiles, renderer
arms, operators and generators are all declarative tables or single files,
and **docs/CUSTOMIZING.md** walks through each — including the GitHub-native
workflow (Actions secrets, the credit-free *Experiment pipeline check*
workflow you can run from the Actions tab, branch protection for traceable
results).

Common adjustments:

```bash
export HOSTSHIFT_SUITE=tasks/my_suite.jsonl   # run YOUR suite everywhere
hostshift lint && hostshift plan              # validate it + price the matrix
hostshift demo --seed 42                      # verify plumbing before spending
```

CI never needs API keys by design. The two workflows:

- **ci.yml** — lint, wheel-build smoke test (the console script must work
  installed), full assertion suite, filter-spec solvability, ≥80% coverage,
  Python 3.11–3.14.
- **experiment.yml** — manual `workflow_dispatch` dry run: synthetic pipeline
  check + report artifacts, zero credits, runnable from the Actions tab on
  any fork.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `hostshift coverage` prints only the self-check | That is its honest no-corpus behavior. Add `--corpus tasks/external_corpus.jsonl` (see its template) |
| `RenderError ... is simulated` | You asked for paper-grade measurement but got a modelled session. Use a device-backed session or set `HOSTSHIFT_ALLOW_SIMULATED=1` for pipeline work only |
| `open_session` says install Playwright | `pip install -e .[web] && playwright install chromium` |
| Operator raises about `GEMINI_API_KEY` | Expected without a key: export one or use the deterministic `AccessibilityTreeOperator` |
| Suite not found after wheel install | The wheel ships a synced copy; override with `--suite` or `HOSTSHIFT_SUITE` if you moved it |

## Schedule to 29 August

| | |
|---|---|
| **Aug 4–8** | Renderers for web + Compose + SwiftUI. Session adapters exposing state and a11y tree. Get *one* task green end-to-end on all three before touching anything else. |
| **Aug 9–12** | Audit all 100 criteria against the live renderers and reconcile seed values. Wire the computer-use operator; validate on 10 tasks; hand-check a stratified 10% and record the agreement number — the paper needs it. |
| **Aug 13–17** | Full run, both conditions. Expect a re-run; budget for it. Freeze model versions and write them down. |
| **Aug 18–20** | Ablations: repair on/off, critic modality, small-model arm if time. Cut the small-model arm first if squeezed. |
| **Aug 21–24** | Failure taxonomy — hand-code a stratified sample. This is the section people will quote and the one that makes the paper useful to a runtime builder rather than just a scorer. |
| **Aug 25–27** | Write. Related work is already drafted. Results and taxonomy are the new prose. |
| **Aug 28** | Repo public, README, run logs committed. arXiv (cs.HC primary, cs.AI cross-list). |
| **Aug 29** | Submit to two workshops — non-archival, so this is allowed and you should. |

Then: ICLR 2027 abstract **18 Sep**, paper **25 Sep**. Note ICLR 2027 caps
authors with no prior accepted publication at **one submission**; make it this
one. Fallback IUI 2027 Posters, **10 Nov**.

## Novelty position

Verified 2026-08-03. State the claim precisely and it holds:

**Novel** — the triad of (a) LLM-generated UI spec, (b) rendered on multiple
hosts, (c) with an operating agent measuring functional task-completion
equivalence. No paper defines a portability, host-lock, or rendering-equivalence
metric for generated interfaces. No paper uses a computer-use agent on generated
native mobile UI.

**Do not claim** first agent-operation of generated UI (MiniAppBench,
Asuka-Bench got there, and both use goal-directed agentic evaluation, not
scripted replay — describe them accurately). Do not claim first multi-platform
GUI agent benchmarking (MMBench-GUI). Do not claim first generation of native
code from specs (DeclarUI). Do not claim first accessibility measurement of
generated UI (Portal UX Agent includes a11y checks; the Android study
catalogued 702 issues) — you are first to measure it *comparatively across
hosts*.

**Watch:** the `vpbydesign/ame` repo has cross-runtime parity conformance tests
across Compose/SwiftUI/Flutter. It's an engineering artifact with no paper, but
it's the nearest competitor if its authors write one. Check it before you
submit.

## Citation

```bibtex
@inproceedings{debnath2026hostshift,
  title={HostShift: Measuring Cross-Platform Portability of LLM-Generated User Interfaces},
  author={Debnath, Soumya},
  booktitle={NeurIPS 2026 Workshop on Agentic AI Benchmarks},
  year={2026}
}
```

## License

This repository is dual-licensed:
- **Data/Benchmark Artifacts:** [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- **Code:** [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html)
