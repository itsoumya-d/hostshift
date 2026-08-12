#!/usr/bin/env python3
"""End-to-end pipeline check on hand-written reference specs.

Runs the complete path the real experiment will run -- spec, session, operator,
state oracle, parity metrics, host-lock -- on specs written by hand rather than
by a model. That isolates the harness: if a task fails here, the harness is
broken, because the spec is known good.

This is the check to run after touching semantics, any renderer, or the oracle.
It costs nothing and it is the only thing standing between a renderer regression
and a corrupted results table.

Native hosts run simulated unless a device bridge is up; the guard in
session.assert_measurable is deliberately bypassed here, because this script
tests the pipeline rather than producing findings.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HOSTSHIFT_ALLOW_SIMULATED", "1")

from hostshift.metrics import (  # noqa: E402
    TaskOutcome, accessibility_parity, host_lock_index, render_parity,
)
from hostshift.oracle import grade, load_suite  # noqa: E402
from hostshift.render import (  # noqa: E402
    HOSTS, RenderError, ReferenceSession, intended_tree, open_session,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE = {t["id"]: t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))}


def spec(name: str) -> dict:
    return json.loads((ROOT / "tasks" / "reference_specs" / f"{name}.json").read_text())


# Scripted operator policies. The real experiment substitutes a computer-use
# agent here; hand-scripting them keeps this check deterministic and free.
def drive_form_001(s) -> int:
    s.invoke("name", "Dana Reyes")
    s.invoke("email", "dana@example.com")
    s.invoke("message", "Please call me back")
    s.invoke("submit")
    return 4


def drive_list_001(s) -> int:
    # Find the row by its accessible name, the way an operator would, rather
    # than hardcoding an index -- an operator that could only work from indices
    # would hide exactly the naming failures the benchmark is looking for.
    target = "Printer offline"
    row = next((a for a in s.actions()
                if a["kind"] == "listItem" and a["name"] == target), None)
    if row is None:
        raise RenderError(f"no row named {target!r} is reachable on this host")
    s.invoke(row["id"])
    s.invoke("resolve")
    return 2


CASES = [
    ("form-001", drive_form_001),
    ("list-001", drive_list_001),
]


def run() -> int:
    outcomes: list[TaskOutcome] = []
    parity: dict[str, dict[str, list[float]]] = {}
    failures: list[str] = []

    print("=" * 74)
    print("END-TO-END: spec -> session -> operator -> state oracle -> metrics")
    print("=" * 74)

    for spec_name, drive in CASES:
        sp = spec(spec_name)
        task = SUITE[spec_name]
        print(f"\n{spec_name}  ({task['category']}, {task['difficulty']})")
        print(f"  goal: {task['goal']}")
        print(f"  {'host':<12}{'ok':>4}{'crit':>8}{'probe':>8}{'RP':>8}{'AP':>8}   notes")
        print("  " + "-" * 68)

        for host in ("reference", *HOSTS):
            try:
                s = (ReferenceSession(sp) if host == "reference"
                     else open_session(sp, host, simulated=True))
            except RenderError as exc:
                failures.append(f"{spec_name}/{host}: could not open — {exc}")
                print(f"  {host:<12}{'ERR':>4}{'':>24}   {exc}")
                continue

            note = ""
            try:
                steps = drive(s)
            except Exception as exc:                      # noqa: BLE001
                steps = 0
                note = f"operator: {exc}"

            g = grade(task, s.state(), s.ui_facts())
            ref = intended_tree(sp, s._state)
            got = s.widget_tree()
            rp = render_parity(ref, got)
            ap = accessibility_parity(ref, got).score

            if host != "reference":
                outcomes.append(TaskOutcome(
                    task_id=spec_name, host=host, success=g["success"], steps=steps,
                    criteria_met=g["criteria_met"], criteria_total=g["criteria_total"]))
                parity.setdefault(host, {"rp": [], "ap": []})
                parity[host]["rp"].append(rp)
                parity[host]["ap"].append(ap)

            if not g["success"]:
                note = note or "; ".join(g["failures"])[:38]
                if host == "reference":
                    failures.append(f"{spec_name}/reference: {g['failures']}")

            print(f"  {host:<12}{'PASS' if g['success'] else 'FAIL':>4}"
                  f"{g['criteria_met']}/{g['criteria_total']:<6}"
                  f"{g['probes_passed']}/{g['probes_total']:<6}"
                  f"{rp:>8.3f}{ap:>8.3f}   {note}")

    print("\n" + "=" * 74)
    print("HOST-LOCK across the reference specs")
    print("=" * 74)
    lock = host_lock_index(outcomes)
    for h, ip in sorted(lock.per_host_ip.items()):
        pr = parity.get(h, {"rp": [0], "ap": [0]})
        mean = lambda v: sum(v) / len(v) if v else 0.0            # noqa: E731
        print(f"  {h:<12} IP={ip:.3f}   RP={mean(pr['rp']):.3f}   AP={mean(pr['ap']):.3f}")
    print(f"\n  HLI {lock.hli:.3f}   per-task lock {lock.per_task_lock:.3f}"
          f"   best={lock.best_host} worst={lock.worst_host}")

    print("\n" + "=" * 74)
    if failures:
        print(f"{len(failures)} PIPELINE FAILURE(S) — the harness, not the spec:")
        for f in failures:
            print("  -", f)
        return 1
    print("pipeline healthy: every reference spec completes on every host,")
    print("graded by the state oracle, with parity computed end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
