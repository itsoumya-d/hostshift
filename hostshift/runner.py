"""Experiment driver and reporting.

`hostshift plan`                      -- show the experiment matrix and its cost
`python -m hostshift lint`            -- validate the task suite
`hostshift report --runs runs/demo`   -- roll up runs.jsonl into paper tables
`hostshift demo`                      -- synthetic end-to-end check of the pipeline

(The same commands work as `python -m hostshift.runner <cmd>`.)
"""

from __future__ import annotations

import argparse
import json as _json
import os
import random
import statistics
import sys
from pathlib import Path

from . import __version__
from .calibration import CalibrationStore, corpus_provenance
from .calibration import report as calibration_summary
from .harness import (
    CONDITION_A,
    CONDITION_B,
    CONDITION_B_NAIVE,
    CONDITIONS,
    HOSTS,
    RunRecord,
    Store,
)
from .metrics import (
    TaskOutcome,
    bootstrap_hli,
    bootstrap_ip,
    collapse_repeats,
    host_lock_index,
    mcnemar,
    repeat_reliability,
)
from .oracle import load_suite, validate_suite


def _default_suite() -> str:
    """Resolve the task suite without assuming a repository checkout.

    Order: $HOSTSHIFT_SUITE, then the repo checkout layout, then the copy
    shipped inside installed wheels (kept in sync by tests/test_packaging.py).
    """
    env = os.environ.get("HOSTSHIFT_SUITE")
    if env:
        return env
    here = Path(__file__).resolve().parent
    checkout = here.parents[1] / "tasks" / "suite_v1.jsonl"
    if checkout.exists():
        return str(checkout)
    return str(here / "data" / "suite_v1.jsonl")


SUITE = _default_suite()


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
    data = _compute_tables(runs, boot=getattr(args, "boot", 4000))
    if getattr(args, "json", False):
        print(_json.dumps(data, indent=2))
    else:
        _emit_tables(data)
    return 0


def _compute_tables(runs: list[RunRecord], boot: int = 4000) -> dict:
    """Roll run records up into the five paper tables.

    Pure computation, no printing: `report` renders it for humans and
    `report --json` serializes it for scripts, notebooks, and CI artifacts.
    """
    generators = sorted({r.generator for r in runs})
    hosts = sorted({r.host for r in runs})

    # Scope the cell to one generator and one condition. Keying only by
    # (task, host) would pool every generator and both conditions into one
    # cell and report their disagreement as operator unreliability.
    rel = repeat_reliability(
        [TaskOutcome(f"{r.task_id}|{r.generator}|{r.condition}", r.host, r.success)
         for r in runs])

    cells: dict[tuple[str, str], list[RunRecord]] = {}
    for r in runs:
        cells.setdefault((r.generator, r.condition), []).append(r)

    table1 = []
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
            table1.append({
                "generator": gen, "condition": cond,
                "ip": round(ip, 6), "ip_ci95": [round(lo, 4), round(hi, 4)],
                "hli": round(lock.hli, 6),
                "hli_ci95": [round(hlo, 4), round(hhi, 4)],
                "per_task_lock": round(lock.per_task_lock, 6),
            })

    table2 = []
    for gen in generators:
        for cond in CONDITIONS:
            rows = cells.get((gen, cond), [])
            if not rows:
                continue
            per_host = {}
            for h in hosts:
                hr = [r for r in rows if r.host == h]
                per_host[h] = round(
                    sum(1 for r in hr if r.success) / len(hr) if hr else 0.0, 6)
            table2.append({"generator": gen, "condition": cond, "ip_by_host": per_host})

    table3 = []
    for h in hosts:
        hr = [r for r in runs if r.host == h]
        rp = [r.render_parity for r in hr if r.render_parity is not None]
        ap = [r.a11y_parity for r in hr if r.a11y_parity is not None]
        table3.append({
            "host": h,
            "mean_render_parity": round(statistics.mean(rp), 6) if rp else None,
            "mean_a11y_parity": round(statistics.mean(ap), 6) if ap else None,
            "n_runs": len(hr),
        })

    index: dict[tuple, dict[str, bool]] = {}
    for r in collapse_repeats_by_condition(runs):
        index.setdefault((r.task_id, r.host, r.generator), {})[r.condition] = r.success

    contrasts = [
        ("representation alone", CONDITION_A, CONDITION_B_NAIVE),
        ("renderer expertise", CONDITION_B_NAIVE, CONDITION_B),
        ("end to end", CONDITION_A, CONDITION_B),
    ]
    table4 = []
    for label, lhs, rhs in contrasts:
        pairs = [(v[lhs], v[rhs]) for v in index.values() if lhs in v and rhs in v]
        if not pairs:
            table4.append({"contrast": label, "n": 0})
            continue
        res = mcnemar(pairs)
        verdict = ("later arm helps" if res["c"] > res["b"] else
                   "later arm hurts" if res["b"] > res["c"] else "no difference")
        table4.append({
            "contrast": label, "n": len(pairs), "gained": res["c"], "lost": res["b"],
            "p_value": res["p_value"], "verdict": verdict,
        })

    summary = calibration_summary(
        collapse_repeats([TaskOutcome(r.task_id, r.host, r.success) for r in runs]))

    return {
        "meta": {
            "runs": len(runs), "generators": generators, "hosts": hosts,
            "bootstrap_resamples": boot,
            "repeat_reliability": rel,
            "note": "Repeats collapsed by majority vote before inference; "
                    "intervals are cluster bootstraps resampling whole tasks.",
        },
        "interaction_parity_and_host_lock": table1,
        "per_host_interaction_parity": table2,
        "structural_and_accessibility_parity": table3,
        "condition_contrasts_mcnemar": table4,
        "operator_calibration": summary,
    }


def _emit_tables(data: dict) -> None:
    rel = data["meta"]["repeat_reliability"]
    cells1 = data["interaction_parity_and_host_lock"]

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
    header = (f"{'generator':<20}{'cond':<12}{'IP':>7}{'95% CI':>16}"
              f"{'HLI':>7}{'HLI CI':>16}{'lock':>7}")
    print(header)
    print("-" * 78)
    for row in cells1:
        lo, hi = row["ip_ci95"]
        hlo, hhi = row["hli_ci95"]
        print(f"{row['generator']:<20}{row['condition']:<12}{row['ip']:>7.3f}"
              f"{f'[{lo:.2f},{hi:.2f}]':>16}{row['hli']:>7.3f}"
              f"{f'[{hlo:.2f},{hhi:.2f}]':>16}{row['per_task_lock']:>7.3f}")

    print()
    print("=" * 78)
    print("TABLE 2  Per-host Interaction Parity  (the portability picture)")
    print("=" * 78)
    hosts = data["meta"]["hosts"]
    print(f"{'generator':<22}{'cond':<12}" + "".join(f"{h:>10}" for h in hosts))
    print("-" * 78)
    for row in data["per_host_interaction_parity"]:
        line = f"{row['generator']:<22}{row['condition']:<12}"
        for h in hosts:
            line += f"{row['ip_by_host'][h]:>10.3f}"
        print(line)

    print()
    print("=" * 78)
    print("TABLE 3  Structural and accessibility parity, by host")
    print("=" * 78)
    print(f"{'host':<12}{'mean RP':>10}{'mean AP':>10}{'n':>8}")
    print("-" * 78)
    for row in data["structural_and_accessibility_parity"]:
        rp = row["mean_render_parity"]
        ap = row["mean_a11y_parity"]
        print(f"{row['host']:<12}{(rp if rp is not None else float('nan')):>10.3f}"
              f"{(ap if ap is not None else float('nan')):>10.3f}{row['n_runs']:>8}")

    print()
    print("=" * 78)
    print("TABLE 4  Decomposition: representation vs renderer expertise  [McNemar]")
    print("=" * 78)
    print("A vs B-naive isolates the representation. B-naive vs B isolates the")
    print("renderer. Reporting only A vs B would credit the schema with work the")
    print("runtime did, which is the sharpest objection to this comparison.")
    print()
    print(f"{'contrast':<22}{'n':>7}{'gained':>8}{'lost':>7}{'p':>12}   verdict")
    print("-" * 78)
    for row in data["condition_contrasts_mcnemar"]:
        if row.get("n", 0) == 0 or "p_value" not in row:
            print(f"{row['contrast']:<22}{'--':>7}   (condition absent from this run)")
            continue
        print(f"{row['contrast']:<22}{row['n']:>7}{row['gained']:>8}{row['lost']:>7}"
              f"{row['p_value']:>12.1e}   {row['verdict']}")

    print()
    print("=" * 78)
    print("TABLE 5  Operator calibration")
    print("=" * 78)
    summary = data["operator_calibration"]
    if summary.get("normalized_hli") is None:
        print("  " + summary["status"])
        print("  Run `hostshift calibrate` first.")
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
        print("that answers the objection. See tasks/external_corpus.template.jsonl")
        print("for the contract and candidate sources.")
        print()
        print("To measure one:")
        print("  hostshift coverage --corpus <your-corpus.jsonl>")
        return 0

    print(format_report(analyse(load_corpus(args.corpus))))
    return 0


def cmd_hosts(args) -> int:
    """Print the declarative host-capability profile table.

    These tables are where realization differences live, so they get a
    first-class command: a reviewer auditing whether an observed parity gap is
    a property of the host or a bug in one renderer starts here.
    """
    from .render import HOSTS as RENDER_HOSTS
    from .render import PROFILES
    from .render.base import _FULL

    print(f"{'host':<10}{'cannot realize':<16}{'names from label':<18}"
          f"{'disabled state':<16}{'degrades to'}")
    print("-" * 78)
    for h in RENDER_HOSTS:
        p = PROFILES[h]
        missing = ", ".join(sorted(set(_FULL) - set(p.realizes))) or "-"
        name_src = "yes" if p.derives_name_from_label else "no"
        disabled = "exposed" if p.exposes_enabled_state else "dimmed only"
        print(f"{h:<10}{missing:<16}{name_src:<18}{disabled:<16}{p.degrade_to}")
    print()
    print("Source of truth: hostshift/render/base.py. A parity gap explained by a")
    print("row above is a host property; anything else indicts the renderer.")
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


def cmd_render_check(args) -> int:
    """Compile-gate emitted Swift/Kotlin with local toolchains + differential
    semantic checks against each host profile. Exit 0 only if everything that
    ran passed; skips are reported but never counted as passes."""
    from .native_conformance import (
        compile_native,
        differential_report,
        embedding_roundtrip,
        summary,
    )

    specs: dict[str, dict] = {}
    p = Path(args.specs)
    texts: list[str] = []
    if p.is_dir():
        texts = sorted(x.read_text() for x in p.glob("*.json"))
    else:
        texts = [p.read_text()]
    for text in texts:
        stripped = text.strip()
        if not stripped:
            continue
        # Pretty-printed single-spec JSON files are the common case; JSONL
        # suites also work. Try whole-file first, then per-line.
        try:
            rec = _json.loads(stripped)
            specs[str(rec.get("id", len(specs)))] = rec.get("spec", rec)
            continue
        except _json.JSONDecodeError:
            pass
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            rec = _json.loads(line)
            specs[str(rec.get("id", len(specs)))] = rec.get("spec", rec)

    checks = compile_native(specs)
    findings = differential_report(specs) + embedding_roundtrip(specs)
    print(summary(checks, findings))
    failed = any(c.ok is False for c in checks) or any(not f.ok for f in findings)
    return 1 if failed else 0


def cmd_demo(args) -> int:
    """Synthetic end-to-end check.

    Fabricates plausible outcomes so the whole reporting path can be exercised
    before a single API credit is spent. The planted effect -- schema output
    degrading less on native hosts -- is the hypothesis, NOT a result. Nothing
    here is evidence of anything.

    Writes to its own store (default runs/demo/), so it can never clobber a
    real experiment log in runs/runs.jsonl.
    """
    rng = random.Random(args.seed)
    tasks = load_suite(args.suite)
    store = Store(args.out)

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
    _emit_tables(_compute_tables(runs))
    print()
    print("!! SYNTHETIC DATA -- pipeline check only. This is not a result.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="hostshift",
        description="Cross-platform portability benchmark for LLM-generated UIs.",
    )
    ap.add_argument("--version", action="version", version=f"hostshift {__version__}")
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
    # Also accepted after the subcommand: `report --runs runs/demo` is the
    # natural spelling and the only way to report a non-default store.
    # SUPPRESS keeps a subcommand-level omission from clobbering a value
    # given at the top level (argparse subparser defaults would otherwise win).
    rp.add_argument("--runs", default=argparse.SUPPRESS,
                    help="run store to report on (default: runs/runs.jsonl)")
    rp.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of text tables "
                         "(same numbers; for scripts, notebooks, and CI)")
    rp.set_defaults(fn=cmd_report)

    cal = sub.add_parser("calibrate")
    cal.add_argument("--runs", default=argparse.SUPPRESS,
                     help="run store for the raw/normalized comparison "
                          "(default: runs/runs.jsonl)")
    cal.set_defaults(fn=cmd_calibrate)

    cov = sub.add_parser("coverage")
    cov.add_argument("--corpus", default=None,
                     help="JSONL of externally-authored application requests")
    cov.set_defaults(fn=cmd_coverage)

    d = sub.add_parser("demo")
    d.add_argument("--repeats", type=int, default=2)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--out", default="runs/demo",
                   help="separate store for synthetic runs (never the real log)")
    d.set_defaults(fn=cmd_demo)

    h = sub.add_parser("hosts")
    h.set_defaults(fn=cmd_hosts)

    rc = sub.add_parser(
        "render-check",
        help="compile-gate emitted Swift/Kotlin + differential semantic checks",
    )
    rc.add_argument("--specs",
                    default="tasks/reference_specs/filter-001.json",
                    help="JSONL of UISpec fixtures (or a single JSON file)")
    rc.set_defaults(fn=cmd_render_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
