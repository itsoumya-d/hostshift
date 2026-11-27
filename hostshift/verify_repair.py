"""hostshift.verify_repair - Verify-and-repair quality loop for HostShift UISpec artifacts.

Evaluates generated UISpecs against a declarative rubric (rubric.json), applies mechanical
repairs across up to 3 rounds, logs each evaluation round to a ledger, and preserves semantic
or non-mechanical faults for human review without guessing.
"""

from __future__ import annotations

import copy
import datetime
import json
import pathlib
from typing import Any

DEFAULT_RUBRIC_PATH = pathlib.Path(__file__).resolve().parent / "data" / "rubric.json"
ROOT_RUBRIC_PATH = pathlib.Path(__file__).resolve().parents[1] / "rubric.json"

VALID_WIDGET_KINDS = {
    "heading",
    "field",
    "button",
    "banner",
    "text",
    "image",
    "row",
    "column",
    "card",
    "list",
    "table",
    "picker",
    "switch",
    "checkbox",
    "stepper",
    "dialog",
    "spacer",
    "divider",
}


def load_rubric(path: str | pathlib.Path | None = None) -> dict[str, Any]:
    """Load rubric definition from JSON file."""
    candidate = None
    if path:
        candidate = pathlib.Path(path)
    elif DEFAULT_RUBRIC_PATH.exists():
        candidate = DEFAULT_RUBRIC_PATH
    elif ROOT_RUBRIC_PATH.exists():
        candidate = ROOT_RUBRIC_PATH
    else:
        raise FileNotFoundError("rubric.json not found in hostshift/data or project root")

    with open(candidate, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data.get("checks"), list):
        raise ValueError("rubric.json must define a 'checks' array")
    return data


def _collect_widgets(node: Any) -> list[dict[str, Any]]:
    """Traverse screens or widget containers and collect all widget dicts."""
    widgets: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "kind" in node:
            widgets.append(node)
        for val in node.values():
            widgets.extend(_collect_widgets(val))
    elif isinstance(node, list):
        for item in node:
            widgets.extend(_collect_widgets(item))
    return widgets


def verify_spec(
    spec: dict[str, Any], rubric: dict[str, Any] | None = None
) -> tuple[float, list[dict[str, Any]]]:
    """Score a UISpec from 0 to 100 against rubric rules.

    Returns:
        (total_score, list_of_failed_check_diagnostics)
    """
    if rubric is None:
        rubric = load_rubric()

    checks = {c["id"]: c for c in rubric.get("checks", [])}
    diagnostics: list[dict[str, Any]] = []
    total_score = 0.0

    # 1. valid_schema_root
    check_root = checks.get("valid_schema_root", {"weight": 25.0})
    has_version = str(spec.get("version", "")).strip() == "0.2"
    has_title = bool(spec.get("title"))
    has_entry = bool(str(spec.get("entry", "")).strip())
    screens_raw = spec.get("screens")
    has_screens = isinstance(screens_raw, (list, dict)) and len(screens_raw) > 0

    if has_version and has_title and has_entry and has_screens:
        total_score += check_root["weight"]
    else:
        failures = []
        if not has_version:
            failures.append("version is missing or not '0.2'")
        if not has_title:
            failures.append("title is missing or empty")
        if not has_entry:
            failures.append("entry screen identifier is missing")
        if not has_screens:
            failures.append("screens mapping is missing or empty")
        diagnostics.append({
            "check_id": "valid_schema_root",
            "description": check_root.get("description", ""),
            "reasons": failures,
            "mechanical": True,
        })

    # Normalize screens mapping for subsequent checks
    screen_list: list[dict[str, Any]] = []
    screen_ids: set[str] = set()
    if isinstance(screens_raw, list):
        for s in screens_raw:
            if isinstance(s, dict):
                screen_list.append(s)
                if "id" in s:
                    screen_ids.add(str(s["id"]).strip())
    elif isinstance(screens_raw, dict):
        for k, v in screens_raw.items():
            if isinstance(v, dict):
                item = dict(v)
                item.setdefault("id", str(k).strip())
                screen_list.append(item)
                screen_ids.add(str(k).strip())

    # 2. entry_screen_exists
    check_entry = checks.get("entry_screen_exists", {"weight": 25.0})
    raw_entry = str(spec.get("entry", "")).strip()
    if raw_entry and raw_entry in screen_ids:
        total_score += check_entry["weight"]
    else:
        id_list = sorted(screen_ids)
        diagnostics.append({
            "check_id": "entry_screen_exists",
            "description": check_entry.get("description", ""),
            "reasons": [f"entry '{raw_entry}' does not match any declared screen in {id_list}"],
            "mechanical": len(screen_ids) == 1 or spec.get("entry") != raw_entry,
        })

    # 3. widget_kinds_valid
    check_kinds = checks.get("widget_kinds_valid", {"weight": 20.0})
    all_widgets = _collect_widgets(screen_list)
    invalid_kinds = [w.get("kind") for w in all_widgets if w.get("kind") not in VALID_WIDGET_KINDS]

    if not invalid_kinds:
        total_score += check_kinds["weight"]
    else:
        diagnostics.append({
            "check_id": "widget_kinds_valid",
            "description": check_kinds.get("description", ""),
            "reasons": [f"unrecognized widget kinds: {invalid_kinds}"],
            "mechanical": False,  # Non-mechanical: semantic intention cannot be guessed
        })

    # 4. state_binding_integrity
    check_state = checks.get("state_binding_integrity", {"weight": 15.0})
    declared_state = set((spec.get("state") or {}).keys())
    missing_bindings: list[str] = []
    for w in all_widgets:
        bind_target = w.get("bind")
        if bind_target and isinstance(bind_target, str):
            clean_bind = bind_target.strip().split(".")[0]
            if clean_bind not in declared_state:
                missing_bindings.append(bind_target)

    if not missing_bindings:
        total_score += check_state["weight"]
    else:
        diagnostics.append({
            "check_id": "state_binding_integrity",
            "description": check_state.get("description", ""),
            "reasons": [f"bind targets not found in declared state: {missing_bindings}"],
            "mechanical": False,  # Non-mechanical: missing business state cannot be guessed
        })

    # 5. screen_has_children
    check_children = checks.get("screen_has_children", {"weight": 15.0})
    screens_without_children: list[str] = []
    for s in screen_list:
        children = s.get("children")
        if not isinstance(children, list) or len(children) == 0:
            screens_without_children.append(s.get("id", "unnamed"))

    if not screens_without_children and len(screen_list) > 0:
        total_score += check_children["weight"]
    else:
        diagnostics.append({
            "check_id": "screen_has_children",
            "description": check_children.get("description", ""),
            "reasons": [f"screens lacking children: {screens_without_children}"],
            "mechanical": True,
        })

    return round(total_score, 2), diagnostics


def repair_spec(
    spec: dict[str, Any], diagnostics: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Fix mechanical faults (format, missing field, whitespace, out-of-range value).

    Non-mechanical faults (e.g. unknown state bindings or unknown widget kinds)
    are reported for a human and left untouched.
    """
    fixed: list[str] = []
    unresolved: list[str] = []
    repaired = copy.deepcopy(spec)

    for diag in diagnostics:
        cid = diag["check_id"]
        if cid == "valid_schema_root":
            if repaired.get("version") != "0.2":
                repaired["version"] = "0.2"
                fixed.append("normalized version to '0.2'")
            if not repaired.get("title") and repaired.get("id"):
                repaired["title"] = str(repaired["id"]).replace("-", " ").title()
                fixed.append(f"derived title from id: {repaired['title']}")
            entry_val = repaired.get("entry")
            if isinstance(entry_val, str) and entry_val != entry_val.strip():
                repaired["entry"] = entry_val.strip()
                fixed.append("trimmed whitespace from entry id")

        elif cid == "entry_screen_exists":
            raw_entry = str(repaired.get("entry", "")).strip()
            screens = repaired.get("screens")
            screen_ids = []
            if isinstance(screens, list):
                screen_ids = [str(s.get("id", "")).strip() for s in screens if isinstance(s, dict)]
            elif isinstance(screens, dict):
                screen_ids = [str(k).strip() for k in screens.keys()]

            if screen_ids and (not raw_entry or raw_entry not in screen_ids):
                if len(screen_ids) == 1:
                    repaired["entry"] = screen_ids[0]
                    fixed.append(f"set single declared screen '{screen_ids[0]}' as entry")
                elif raw_entry != repaired.get("entry"):
                    repaired["entry"] = raw_entry
                    fixed.append(f"trimmed whitespace on entry '{raw_entry}'")
                else:
                    unresolved.append(f"ambiguous entry target '{raw_entry}' among {screen_ids}")
            else:
                repaired["entry"] = raw_entry
                fixed.append(f"trimmed whitespace on entry '{raw_entry}'")

        elif cid == "screen_has_children":
            screens = repaired.get("screens")
            if isinstance(screens, list):
                for s in screens:
                    needs_children = isinstance(s, dict) and (
                        not isinstance(s.get("children"), list) or len(s["children"]) == 0
                    )
                    if needs_children:
                        sid = s.get("id", "main")
                        stitle = s.get("title") or sid.replace("-", " ").title()
                        s["children"] = [
                            {"kind": "heading", "id": f"heading_{sid}", "label": stitle}
                        ]
                        fixed.append(f"initialized default heading widget for screen '{sid}'")
            elif isinstance(screens, dict):
                for sid, s in screens.items():
                    needs_children = isinstance(s, dict) and (
                        not isinstance(s.get("children"), list) or len(s["children"]) == 0
                    )
                    if needs_children:
                        stitle = s.get("title") or sid.replace("-", " ").title()
                        s["children"] = [
                            {"kind": "heading", "id": f"heading_{sid}", "label": stitle}
                        ]
                        fixed.append(f"initialized default heading widget for screen '{sid}'")

        else:
            # Non-mechanical fault: report for human review, never guess
            for r in diag.get("reasons", []):
                unresolved.append(f"{cid}: {r}")

    return repaired, fixed, unresolved


def run_verify_repair_loop(
    spec: dict[str, Any],
    rubric_path: str | pathlib.Path | None = None,
    ledger_path: str | pathlib.Path | None = None,
    max_rounds: int = 3,
) -> tuple[dict[str, Any], float, list[dict[str, Any]]]:
    """Execute up to 3 rounds of verify-repair, logging each round in JSONL ledger.

    Returns:
        (final_spec, final_score, remaining_diagnostics)
    """
    rubric = load_rubric(rubric_path)
    threshold = float(rubric.get("threshold", 80.0))
    current_spec = copy.deepcopy(spec)

    score, diagnostics = verify_spec(current_spec, rubric)
    round_num = 1

    while round_num <= max_rounds:
        repaired_spec, fixed, unresolved = repair_spec(current_spec, diagnostics)
        new_score, new_diagnostics = verify_spec(repaired_spec, rubric)

        # Log round to ledger
        status_label = "manual_review_needed"
        if new_score >= threshold:
            status_label = "passed"
        elif fixed:
            status_label = "repaired"

        record = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "round": round_num,
            "spec_title": current_spec.get("title", current_spec.get("id", "untitled")),
            "score_before": score,
            "score_after": new_score,
            "repaired": fixed,
            "unresolved": unresolved,
            "status": status_label,
        }

        if ledger_path:
            out_file = pathlib.Path(ledger_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")

        current_spec = repaired_spec
        score = new_score
        diagnostics = new_diagnostics

        if score >= threshold or not fixed:
            break

        round_num += 1

    return current_spec, score, diagnostics
