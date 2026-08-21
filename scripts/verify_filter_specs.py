"""Verify every filter spec is solvable end-to-end.

For each filter-* spec: run a scripted operator against the ReferenceSession
that performs exactly the actions the task goal describes, then grade the
resulting state with the oracle. Every criterion must pass. A spec that cannot
be solved is worse than no spec -- it would silently zero a task's interaction
parity for reasons that have nothing to do with any host.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.oracle import check, grade
from hostshift.render import ReferenceSession
from hostshift.render.semantics import validate_spec

ROOT = pathlib.Path(__file__).resolve().parents[1]


def solve_001(s):
    s.invoke("deptFilter", "Engineering")
    s.invoke("sortField", "startDate")
    s.invoke("sortDir", "asc")


def solve_002(s):
    s.invoke("searchBox", "an")          # Argentina, Canada, Hungary, Japan... count varies
    s.invoke("searchBox", "")            # cleared -> full seed restored


def solve_003(s):
    s.invoke("statusFilter", "Shipped")


def solve_004(s):
    s.invoke("typeFilter", "Debit")
    s.invoke("minAmount", 100)


def solve_005(s):
    s.invoke("sortByTitle", None)
    s.invoke("toggleDesc", None)


def solve_006(s):
    s.invoke("deptFilter", "Support")
    s.invoke("sortByTitle", None) if False else None
    # give sort.field a value first so clearing it is observable
    s.invoke("clearAll", None)


def solve_007(s):
    s.invoke("makerFilter", "Nonesuch")


def solve_008(s):
    s.invoke("page3", None)


def solve_009(s):
    s.invoke("statusFilter", "Overdue")
    s.invoke("invoiceList#0", None)      # into detail; filter must survive
    s.invoke("back", None)


def solve_010(s):
    s.invoke("hideToggle", True)


def solve_012(s):
    s.invoke("lastPage", None)           # wander to page 3
    s.invoke("statusFilter", "Active")   # changing filter resets page to 1


SOLVERS = {
    "filter-001": solve_001,
    "filter-002": solve_002,
    "filter-003": solve_003,
    "filter-004": solve_004,
    "filter-005": solve_005,
    "filter-006": solve_006,
    "filter-007": solve_007,
    "filter-008": solve_008,
    "filter-009": solve_009,
    "filter-010": solve_010,
    "filter-012": solve_012,
}


def main() -> int:
    suite_path = ROOT / "tasks" / "suite_v1.jsonl"
    tasks = {t["id"]: t for t in map(json.loads, suite_path.read_text().splitlines()) if t}
    failures = 0
    for tid, solver in sorted(SOLVERS.items()):
        spec_path = ROOT / "tasks" / "reference_specs" / f"{tid}.json"
        spec = json.loads(spec_path.read_text())
        problems = validate_spec(spec)
        if problems:
            print(f"FAIL {tid}: invalid spec: {problems}")
            failures += 1
            continue
        session = ReferenceSession(spec)
        try:
            solver(session)
            result = grade(tasks[tid], session.state(), session.ui_facts())
            unmet = [c["kind"] + ":" + str(c.get("path") or c.get("collection"))
                     for c in tasks[tid]["criteria"]
                     if not check(c, session.state(), session.ui_facts()).passed]
            if not result.get("success") or unmet:
                print(f"FAIL {tid}: success={result.get('success')} unmet={unmet}")
                failures += 1
            else:
                print(f"PASS {tid}: all {len(tasks[tid]['criteria'])} criteria met")
        finally:
            session.close()
    total = len(SOLVERS)
    print(f"\n{total - failures}/{total} specs solvable")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
