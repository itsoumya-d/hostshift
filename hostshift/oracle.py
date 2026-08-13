"""State-based success oracle.

The single most important design decision in HostShift: success is judged
against *application state*, never against pixels and never by an LLM judge.

Pixel and MLLM-judge oracles (ArtifactsBench, and the visual half of
Design2Code) cannot be used here, because the whole question is whether the
same task succeeds on hosts that legitimately look nothing like each other. A
SwiftUI form and a terminal form should score identically when both record the
contact. Only a state oracle can say that.

Every host adapter must therefore expose one method: dump the declared state and
collections as JSON after the operator agent finishes. That is a small ask of a
host and it is what makes the comparison fair.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class CriterionResult:
    kind: str
    passed: bool
    detail: str = ""


def _get(state: dict, path: str) -> Any:
    cur: Any = state
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _rows(state: dict, collection: str) -> list[dict]:
    v = (state.get("collections") or {}).get(collection)
    if v is None:
        v = state.get(collection)
    return v if isinstance(v, list) else []


def _matches(row: dict, match: dict) -> bool:
    for k, want in match.items():
        got = row.get(k)
        if isinstance(want, str) and isinstance(got, str):
            if want.strip().lower() != got.strip().lower():
                return False
        elif isinstance(want, (int, float)) and isinstance(got, (int, float)):
            if abs(float(want) - float(got)) > 1e-9:
                return False
        elif got != want:
            return False
    return True


_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
}


def check(criterion: dict, state: dict, ui_facts: dict | None = None) -> CriterionResult:
    """Evaluate one criterion against a post-run state snapshot.

    `ui_facts` carries the few observations that genuinely cannot live in
    application state -- whether an error was perceivable, whether an empty
    state was shown, whether a control was disabled. These come from the host's
    accessibility tree, not from a screenshot, so they remain host-fair.
    """
    kind = criterion.get("kind", "")
    ui_facts = ui_facts or {}

    if kind == "state_equals":
        got = _get(state, criterion["path"])
        want = criterion["value"]
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            eq = abs(float(want) - float(got)) < 1e-9
        elif isinstance(want, str) and isinstance(got, str):
            eq = want.strip().lower() == got.strip().lower()
        else:
            eq = got == want
        return CriterionResult(kind, eq, f"{criterion['path']}={got!r} want {want!r}")


    if kind == "state_truthy":
        got = _get(state, criterion["path"])
        return CriterionResult(kind, bool(got), f"{criterion['path']}={got!r}")

    if kind == "collection_contains":
        rows = _rows(state, criterion["collection"])
        hit = any(_matches(r, criterion["match"]) for r in rows)
        return CriterionResult(kind, hit, f"{len(rows)} rows, match={criterion['match']}")

    if kind == "collection_count":
        rows = _rows(state, criterion["collection"])
        op = _OPS[criterion.get("op", "eq")]
        return CriterionResult(kind, op(len(rows), criterion["value"]),
                               f"count={len(rows)} {criterion.get('op','eq')} {criterion['value']}")

    if kind == "collection_field_equals":
        rows = [r for r in _rows(state, criterion["collection"])
                if _matches(r, criterion.get("where", {}))]
        if not rows:
            return CriterionResult(kind, False, "no row matched `where`")
        ok = all(r.get(criterion["field"]) == criterion["value"] for r in rows)
        return CriterionResult(kind, ok, f"{len(rows)} matched; field={criterion['field']}")

    if kind == "collection_field_unchanged":
        rows = _rows(state, criterion["collection"])
        excl = criterion.get("where_not", {})
        others = [r for r in rows if not _matches(r, excl)]
        seeded = criterion.get("seed_values")
        if seeded is None:
            # Fail loudly rather than pass vacuously. A criterion that silently
            # succeeds when it was written wrong is worse than no criterion at
            # all: it inflates the score and nothing in the pipeline complains.
            return CriterionResult(
                kind, False,
                "misconfigured: collection_field_unchanged requires `seed_values`",
            )
        ok = all(r.get(criterion["field"]) == seeded.get(str(i))
                 for i, r in enumerate(others))
        return CriterionResult(kind, ok, "collateral mutation check")

    if kind == "visible_row_count":
        got = (ui_facts.get("visible_rows") or {}).get(criterion["collection"])
        if got is None:
            return CriterionResult(kind, False, "host did not report visible row counts")
        op = _OPS[criterion.get("op", "eq")]
        return CriterionResult(kind, op(got, criterion["value"]), f"visible={got}")

    if kind == "error_visible":
        return CriterionResult(kind, bool(ui_facts.get("error_visible")), "a11y-tree alert/status")

    if kind == "empty_state_visible":
        return CriterionResult(kind, bool(ui_facts.get("empty_state_visible")), "a11y-tree status")

    if kind == "enabled_state":
        states = ui_facts.get("enabled") or {}
        want = criterion.get("expect") == "enabled"
        targets = criterion.get("targets", [])
        missing = [t for t in targets if t not in states]
        if missing:
            return CriterionResult(kind, False, f"host did not report enablement for {missing}")
        ok = all(states[t] == want for t in targets)
        return CriterionResult(kind, ok, f"{targets} expect {criterion.get('expect')}")

    if kind == "field_value_equals":
        vals = ui_facts.get("field_values") or {}
        got = vals.get(criterion["field"])
        return CriterionResult(kind, got == criterion["value"], f"field={got!r}")

    if kind == "options_contain":
        opts = (ui_facts.get("options") or {}).get(criterion["field"], [])
        bad = [o for o in criterion.get("not_contains", []) if o in opts]
        need = [o for o in criterion.get("contains", []) if o not in opts]
        return CriterionResult(kind, not bad and not need, f"stale={bad} missing={need}")

    return CriterionResult(kind, False, f"unknown criterion kind {kind!r}")


def grade(task: dict, state: dict, ui_facts: dict | None = None) -> dict:
    """Grade a whole task. Success requires every criterion and every negative
    criterion to hold. Probes are reported but do not gate success -- they are
    diagnostic, and folding them into the pass/fail would conflate 'the task was
    achieved' with 'the interface behaved well along the way'.
    """
    results = [check(c, state, ui_facts) for c in task.get("criteria", [])]
    negatives = [check(c, state, ui_facts) for c in task.get("negative_criteria", [])]
    probes = [check(c, state, ui_facts) for c in task.get("probes", [])]

    hard = results + negatives
    met = sum(1 for r in hard if r.passed)
    return {
        "task_id": task["id"],
        "success": all(r.passed for r in hard) and bool(hard),
        "criteria_met": met,
        "criteria_total": len(hard),
        "probes_passed": sum(1 for p in probes if p.passed),
        "probes_total": len(probes),
        "failures": [f"{r.kind}: {r.detail}" for r in hard if not r.passed],
        "probe_failures": [f"{p.kind}: {p.detail}" for p in probes if not p.passed],
    }


def load_suite(path: str) -> list[dict]:
    tasks = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("//"):
                tasks.append(json.loads(line))
    ids = [t["id"] for t in tasks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate task ids: {sorted(dupes)}")
    return tasks


def validate_suite(tasks: list[dict]) -> list[str]:
    """Lint the suite. Run this before every experiment.

    A benchmark whose tasks are subtly malformed produces confident nonsense,
    and the reviewer who finds it will be right to reject.
    """
    problems: list[str] = []
    known = {
        "state_equals", "state_truthy", "collection_contains", "collection_count",
        "collection_field_equals", "collection_field_unchanged", "visible_row_count",
        "error_visible", "empty_state_visible", "enabled_state", "field_value_equals",
        "options_contain",
    }
    for t in tasks:
        tid = t.get("id", "<no id>")
        if not re.match(r"^[a-z]+-\d{3}$", tid):
            problems.append(f"{tid}: id should look like 'form-001'")
        for fieldname in ("prompt", "goal", "category"):
            if not t.get(fieldname):
                problems.append(f"{tid}: missing {fieldname}")
        if not t.get("criteria"):
            problems.append(f"{tid}: no criteria -- task is ungradeable")
        for c in t.get("criteria", []) + t.get("probes", []) + t.get("negative_criteria", []):
            if c.get("kind") not in known:
                problems.append(f"{tid}: unknown criterion kind {c.get('kind')!r}")
            if c.get("kind") == "collection_field_unchanged" and "seed_values" not in c:
                problems.append(f"{tid}: collection_field_unchanged without `seed_values`")
        hard = t.get("criteria", []) + t.get("negative_criteria", [])
        if len(hard) < 2 and t.get("difficulty") == "hard":
            problems.append(f"{tid}: difficulty=hard with a single criterion looks thin")
        if t.get("max_steps", 0) < 4:
            problems.append(f"{tid}: max_steps looks too small")
        if t.get("goal") and t.get("prompt") and t["goal"].strip() == t["prompt"].strip():
            problems.append(f"{tid}: goal must differ from prompt (leakage)")
    return problems
