"""Experiment driver and reporting.

`python -m hostshift.runner plan`    -- show the experiment matrix and its cost
`python -m hostshift.runner lint`    -- validate the task suite
`python -m hostshift.runner report`  -- roll up runs.jsonl into paper tables
`python -m hostshift.runner demo`    -- synthetic end-to-end check of the pipeline
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

from .calibration import CalibrationStore, corpus_provenance
from .calibration import report as calibration_summary
from .harness import (
    CONDITION_A, CONDITION_B, CONDITION_B_NAIVE, CONDITIONS, HOSTS, RunRecord, Store,
)
from .metrics import (
    TaskOutcome, bootstrap_hli, bootstrap_ip, collapse_repeats, host_lock_index,
    mcnemar, repeat_reliability,
)
from .oracle import load_suite, validate_suite

SUITE = str(Path(__file__).resolve().parents[1] / "tasks" / "suite_v1.jsonl")


def cmd_lint(args) -> int:
    tasks = load_suite(args.suite)
    problems = validate_suite(tasks)
    cats: dict[str, int] = {}
    for t in tasks:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    print(f"{len(tasks)} tasks, {len(cats)} categories")
    for c, n in sorted(cats.items()):
        print(f"  {c:22s} {n}")
    if problems:
        print("\nproblems:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nsuite is well formed")
    return 0


def cmd_plan(args) -> int:
    tasks = load_suite(args.suite)
    gens = args.generators.split(",")
    hosts = args.hosts.split(",")
    n = len(tasks)

    gen_A = n * len(gens) * len(hosts)      # one generation per host
    gen_B = n * len(gens)                   # one spec, rendered everywhere
    runs = n * len(gens) * len(hosts) * 2 * args.repeats

    print(f"tasks            {n}")
    print(f"generators       {len(gens)}  ({', '.join(gens)})")
    print(f"hosts            {len(hosts)}  ({', '.join(hosts)})")
    print(f"repeats          {args.repeats}")
    print()
    print(f"generation calls {gen_A + gen_B}   (A={gen_A}, B={gen_B})")
    print(f"operator runs    {runs}")
    print()
    est = runs * args.avg_steps * args.cost_per_step + (gen_A + gen_B) * args.cost_per_gen
    print(f"rough API cost   ${est:,.0f}"
          f"   ({args.avg_steps} steps/run @ ${args.cost_per_step}/step)")
    print()
    print("scope levers if that is too much, in the order you should pull them:")
    print("  1. drop `tui` host          -> -25% runs, claim survives on 3 hosts")
    print("  2. repeats 3 -> 2           -> -33% runs, widens CIs")
    print("  3. use a11y-scripted operator for ablations only, keep computer-use for the")
    print("     headline table -> cuts most of the cost without weakening the main claim")
    return 0


def cmd_report(args) -> int:
    store = Store(args.runs)
    runs = store.all_runs()
    if not runs:
        print("no runs recorded yet; run the experiment or try `demo`")
        return 1
    _emit_tables(runs, boot=getattr(args, "boot", 4000))
    return 0


def _emit_tables(runs: list[RunRecord], boot: int = 4000) -> None:
    generators = sorted({r.generator for r in runs})

    # Scope the cell to one generator and one condition. Keying only by
    # (task, host) would pool every generator and both conditions into one
    # cell and report their disagreement as operator unreliability.
    rel = repeat_reliability(
        [TaskOutcome(f"{r.task_id}|{r.generator}|{r.condition}", r.host, r.success)
         for r in runs])
    print("=" * 78)
    print("TABLE 1  Interaction Parity and Host-Lock, by condition")
    print("=" * 78)
    print("Repeats collapsed by majority vote before inference; intervals are")
    print("cluster bootstraps resampling whole tasks, not runs. Treating runs as")
    print("independent would understate every interval by roughly the repeat count.")
    if rel.get("unanimous_rate") is not None:
        print(f"Repeat reliability: {rel['unanimous_rate']:.3f} unanimous "
              f"({rel['cells_with_repeats']} cells, mean {rel['mean_repeats']} attempts)")
    print()
    header = f"{'generator':<20}{'cond':<12}{'IP':>7}{'95% CI':>16}{'HLI':>7}{'HLI CI':>16}{'lock':>7}"
    print(header)
    print("-" * 78)

    cells: dict[tuple[str, str], list[RunRecord]] = {}
    for r in runs:
        cells.setdefault((r.generator, r.condition), []).append(r)

    for gen in generators:
        for cond in CONDITIONS:
            rows = cells.get((gen, cond), [])
            if not rows:
                continue
            outcomes = collapse_repeats(
                [TaskOutcome(r.task_id, r.host, r.success) for r in rows])
            ip = sum(1 for o in outcomes if o.success) / len(outcomes)
            lo, hi = bootstrap_ip(outcomes, n_resamples=boot)
            lock = host_lock_index(outcomes)
            hlo, hhi = bootstrap_hli(outcomes, n_resamples=boot)
            print(f"{gen:<20}{cond:<12}{ip:>7.3f}{f'[{lo:.2f},{hi:.2f}]':>16}"
                  f"{lock.hli:>7.3f}{f'[{hlo:.2f},{hhi:.2f}]':>16}"
                  f"{lock.per_task_lock:>7.3f}")

    print()
    print("=" * 78)
    print("TABLE 2  Per-host Interaction Parity  (the portability picture)")
    print("=" * 78)
    hosts = sorted({r.host for r in runs})
    print(f"{'generator':<22}{'cond':<12}" + "".join(f"{h:>10}" for h in hosts))
    print("-" * 78)
    for gen in generators:
        for cond in CONDITIONS:
            rows = cells.get((gen, cond), [])
            if not rows:
                continue
            line = f"{gen:<22}{cond:<12}"
            for h in hosts:
                hr = [r for r in rows if r.host == h]
                line += f"{(sum(1 for r in hr if r.success)/len(hr) if hr else 0):>10.3f}"
            print(line)

    print()
    print("=" * 78)
    print("TABLE 3  Structural and accessibility parity, by host")
    print("=" * 78)
    print(f"{'host':<12}{'mean RP':>10}{'mean AP':>10}{'n':>8}")
    print("-" * 78)
    for h in hosts:
        hr = [r for r in runs if r.host == h]
        rp = [r.render_parity for r in hr if r.render_parity is not None]
        ap = [r.a11y_parity for r in hr if r.a11y_parity is not None]
        print(f"{h:<12}{(statistics.mean(rp) if rp else float('nan')):>10.3f}"
              f"{(statistics.mean(ap) if ap else float('nan')):>10.3f}{len(hr):>8}")

    print()
    print("=" * 78)
    print("TABLE 4  Decomposition: representation vs renderer expertise  [McNemar]")
    print("=" * 78)
    print("A vs B-naive isolates the representation. B-naive vs B isolates the")
    print("renderer. Reporting only A vs B would credit the schema with work the")
    print("runtime did, which is the sharpest objection to this comparison.")
    print()
    index: dict[tuple, dict[str, bool]] = {}
    for r in collapse_repeats_by_condition(runs):
        index.setdefault((r.task_id, r.host, r.generator), {})[r.condition] = r.success

    contrasts = [
        ("representation alone", CONDITION_A, CONDITION_B_NAIVE),
        ("renderer expertise  ", CONDITION_B_NAIVE, CONDITION_B),
        ("end to end          ", CONDITION_A, CONDITION_B),
    ]
    print(f"{'contrast':<22}{'n':>7}{'gained':>8}{'lost':>7}{'p':>12}   verdict")
    print("-" * 78)
    for label, lhs, rhs in contrasts:
        pairs = [(v[lhs], v[rhs]) for v in index.values() if lhs in v and rhs in v]
        if not pairs:
            print(f"{label:<22}{'--':>7}   (condition absent from this run)")
            continue
        res = mcnemar(pairs)
        verdict = ("later arm helps" if res["c"] > res["b"] else
                   "later arm hurts" if res["b"] > res["c"] else "no difference")
        print(f"{label:<22}{len(pairs):>7}{res['c']:>8}{res['b']:>7}"
              f"{res['p_value']:>12.1e}   {verdict}")

    print()
    print("=" * 78)
    print("TABLE 5  Operator calibration")
    print("=" * 78)
    summary = calibration_summary(
        collapse_repeats([TaskOutcome(r.task_id, r.host, r.success) for r in runs]))
    if summary.get("normalized_hli") is None:
        print("  " + summary["status"])
        print("  Run `python -m hostshift.runner calibrate` first.")
    else:
        print(f"  operator ceilings   {summary['ceilings']}")
        print(f"  raw HLI             {summary['raw_hli']:.3f}")
        print(f"  normalized HLI      {summary['normalized_hli']:.3f}")
        print(f"  attributable to the operator, not the interface: "
              f"{summary['attributable_to_operator']:.3f}")
        if summary.get("warning"):
            print(f"  WARNING  {summary['warning']}")

    print()
    print("Report both HLI and per-task lock. They disagree in exactly the case that")
    print("matters -- a uniformly mediocre generator scores HLI 0 while genuinely")
    print("host-locked output also scores HLI 0. See tests/test_metrics.py.")


def collapse_repeats_by_condition(runs: list[RunRecord]) -> list[RunRecord]:
    """Majority-vote repeats within each (task, host, generator, condition) cell.

    The paired McNemar test needs one observation per cell per condition;
    feeding it raw repeats would count the same comparison several times and
    manufacture significance.
    """
    cells: dict[tuple, list[RunRecord]] = {}
    for r in runs:
        cells.setdefault((r.task_id, r.host, r.generator, r.condition), []).append(r)
    out = []
    for (task_id, host, gen, cond), rows in cells.items():
        wins = sum(1 for r in rows if r.success)
        out.append(RunRecord(task_id=task_id, condition=cond, generator=gen, host=host,
                             operator=rows[0].operator, success=wins * 2 > len(rows)))
    return out


def cmd_coverage(args) -> int:
    """What fraction of real requests can the schema express?"""
    from .coverage import analyse, format_report, load_corpus, suite_self_check

    self_check = suite_self_check(args.suite)
    print("Self-check: HostShift's own task suite")
    print(f"  {self_check['expressible']}/{self_check['n']} fully expressible "
          f"({self_check['self_coverage']:.0%})")
    print("  Expected. The suite was written against the schema, so this is not a")
    print("  result -- it is the size of the home-ground advantage, stated as a")
    print("  number so a reviewer does not have to assert it.")
    print()

    if not args.corpus:
        print("No external corpus supplied.")
        print("Coverage against an independently-authored corpus is the only thing")
        print("that answers the objection. See tasks/external_corpus.template.jsonl.")
        return 1

    print(format_report(analyse(load_corpus(args.corpus))))
    return 0


def cmd_calibrate(args) -> int:
    """Show operator ceilings and what they imply for the headline metric."""
    store = CalibrationStore(args.calibration)
    prov = corpus_provenance()

    print("Calibration corpus")
    print(f"  {prov['repo']}")
    print(f"  commit {prov['commit']}  ({prov['tag']}, {prov['license']})")
    print(f"  role: {prov['role']}")
    print()

    ceilings = store.ceilings()
    if not ceilings:
        print("No calibration runs recorded.")
        print()
        print("Until a ceiling exists for a host, that host's interaction parity")
        print("conflates interface portability with operator competence, and its")
        print("host-lock figure must not be reported as a finding.")
        print()
        print("To record one: clone the corpus at the pinned commit with")
        print("calibration.fetch_corpus(), drive the operator through")
        print("CALIBRATION_TASKS on each fixture, and save a CalibrationRun.")
        return 1

    print(f"{'host':<12}{'ceiling':>9}{'done':>7}{'tried':>7}   corpus")
    print("-" * 78)
    for host, c in sorted(ceilings.items()):
        print(f"{host:<12}{c.ceiling:>9.3f}{c.completed:>7}{c.attempted:>7}   "
              f"{c.corpus.rsplit(':', 1)[-1]}")

    runs = Store(args.runs).all_runs()
    if runs:
        summary = calibration_summary(
            collapse_repeats([TaskOutcome(r.task_id, r.host, r.success) for r in runs]))
        print()
        print(f"raw HLI {summary['raw_hli']:.3f}  ->  normalized "
              f"{summary['normalized_hli']:.3f}")
        print(f"{summary['attributable_to_operator']:.3f} of the apparent host-lock "
              f"is operator competence, not interface portability")
        if summary.get("warning"):
            print(f"WARNING  {summary['warning']}")
    return 0


def cmd_demo(args) -> int:
    """Synthetic end-to-end check.

    Fabricates plausible outcomes so the whole reporting path can be exercised
    before a single API credit is spent. The planted effect -- schema output
    degrading less on native hosts -- is the hypothesis, NOT a result. Nothing
    here is evidence of anything.
    """
    rng = random.Random(args.seed)
    tasks = load_suite(args.suite)
    store = Store(args.runs)
    if Path(store.runlog).exists():
        Path(store.runlog).unlink()

    profile = {
        # host: (A-freeform, B-naive, B-schema)
        # The middle arm is deliberately close to B on web (where the platform
        # names controls unaided) and far from it on Compose (where only the
        # renderer can). That is the hypothesis the decomposition tests.
        "web":     (0.78, 0.79, 0.80),
        "swiftui": (0.44, 0.66, 0.71),
        "compose": (0.49, 0.55, 0.73),
        "tui":     (0.21, 0.58, 0.62),
    }
    generators = ["model-x", "model-y", "model-z"]

    for gen in generators:
        skill = rng.uniform(-0.06, 0.06)
        for t in tasks:
            difficulty = rng.uniform(-0.12, 0.12)
            for host, (pa, pn, pb) in profile.items():
                for cond, base in ((CONDITION_A, pa), (CONDITION_B_NAIVE, pn),
                                   (CONDITION_B, pb)):
                    for _ in range(args.repeats):
                        p = min(0.97, max(0.03, base + skill + difficulty))
                        ok = rng.random() < p
                        total = len(t.get("criteria", [])) + len(t.get("negative_criteria", []))
                        store.record(RunRecord(
                            task_id=t["id"], condition=cond, generator=gen, host=host,
                            operator="synthetic", success=ok,
                            steps=rng.randint(6, t.get("max_steps", 18)),
                            criteria_met=total if ok else rng.randint(0, max(0, total - 1)),
                            criteria_total=total,
                            render_parity=min(1.0, max(0.0, rng.gauss(
                                {CONDITION_A: 0.81, CONDITION_B_NAIVE: 0.91,
                                 CONDITION_B: 0.93}[cond], 0.07))),
                            a11y_parity=min(1.0, max(0.0, rng.gauss(
                                {CONDITION_A: 0.64, CONDITION_B_NAIVE: 0.66,
                                 CONDITION_B: 0.88}[cond], 0.11))),
                        ))

    runs = store.all_runs()
    print(f"wrote {len(runs)} synthetic runs to {store.runlog}\n")
    _emit_tables(runs)
    print()
    print("!! SYNTHETIC DATA -- pipeline check only. Delete runs/ before real runs.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hostshift")
    ap.add_argument("--suite", default=SUITE)
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--calibration", default="runs/calibration")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("lint").set_defaults(fn=cmd_lint)

    p = sub.add_parser("plan")
    p.add_argument("--generators", default="gemini,claude,gpt")
    p.add_argument("--hosts", default=",".join(HOSTS))
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--avg-steps", type=int, default=12)
    p.add_argument("--cost-per-step", type=float, default=0.004)
    p.add_argument("--cost-per-gen", type=float, default=0.02)
    p.set_defaults(fn=cmd_plan)

    rp = sub.add_parser("report")
    rp.add_argument("--boot", type=int, default=4000)
    rp.set_defaults(fn=cmd_report)

    cal = sub.add_parser("calibrate")
    cal.set_defaults(fn=cmd_calibrate)

    cov = sub.add_parser("coverage")
    cov.add_argument("--corpus", default=None,
                     help="JSONL of externally-authored application requests")
    cov.set_defaults(fn=cmd_coverage)

    d = sub.add_parser("demo")
    d.add_argument("--repeats", type=int, default=2)
    d.add_argument("--seed", type=int, default=7)
    d.set_defaults(fn=cmd_demo)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
