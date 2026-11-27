"""Tests for hostshift.verify_repair verify-and-repair quality loop."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.verify_repair import (
    load_rubric,
    repair_spec,
    run_verify_repair_loop,
    verify_spec,
)


def test_rubric_load_and_sum():
    rubric = load_rubric()
    assert rubric["version"] == "0.2"
    assert rubric["threshold"] == 80.0
    total_weight = sum(c["weight"] for c in rubric["checks"])
    assert total_weight == 100.0
    print("  PASS test_rubric_load_and_sum")


def test_verify_clean_spec():
    sample_spec = {
        "version": "0.2",
        "title": "Clean Form",
        "entry": "home",
        "state": {"name": {"type": "string", "default": ""}},
        "screens": [
            {
                "id": "home",
                "title": "Home Screen",
                "children": [
                    {"kind": "heading", "id": "h1", "label": "Title"},
                    {"kind": "field", "id": "f1", "label": "Name", "bind": "name"},
                ],
            }
        ],
    }
    score, diagnostics = verify_spec(sample_spec)
    assert score == 100.0
    assert len(diagnostics) == 0
    print("  PASS test_verify_clean_spec")


def test_verify_broken_spec_scores_low():
    broken_spec = {
        "version": "0.1",  # invalid version
        "screens": [],      # empty screens
    }
    score, diagnostics = verify_spec(broken_spec)
    assert score < 80.0
    assert len(diagnostics) >= 2
    print("  PASS test_verify_broken_spec_scores_low")


def test_repair_mechanical_faults():
    broken_spec = {
        "version": "0.1",
        "title": "Auto Repair",
        "entry": " home ",  # whitespace
        "state": {"user": {"type": "string"}},
        "screens": [
            {
                "id": "home",
                "title": "Home Screen",
                "children": [],  # empty children
            }
        ],
    }
    initial_score, diagnostics = verify_spec(broken_spec)
    assert initial_score < 80.0

    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl") as tmp:
        final_spec, final_score, remaining = run_verify_repair_loop(
            broken_spec, ledger_path=tmp.name, max_rounds=3
        )
        assert final_score >= 80.0
        assert final_spec["version"] == "0.2"
        assert final_spec["entry"] == "home"
        assert len(final_spec["screens"][0]["children"]) > 0

        # Validate ledger output
        tmp.seek(0)
        lines = [json.loads(line) for line in tmp if line.strip()]
        assert len(lines) >= 1
        assert lines[0]["score_after"] >= lines[0]["score_before"]
        assert lines[0]["status"] == "passed"

    print("  PASS test_repair_mechanical_faults")


def test_non_mechanical_fault_reported_not_guessed():
    semantic_fault_spec = {
        "version": "0.2",
        "title": "Semantic Error",
        "entry": "main",
        "state": {"declared_var": {"type": "string"}},
        "screens": [
            {
                "id": "main",
                "title": "Main Screen",
                "children": [
                    {
                        "kind": "custom_quantum_widget",  # invalid widget kind
                        "id": "w1",
                        "bind": "undeclared_target_var",  # undeclared state binding
                    }
                ],
            }
        ],
    }
    score, diagnostics = verify_spec(semantic_fault_spec)
    assert score < 80.0

    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl") as tmp:
        final_spec, final_score, remaining = run_verify_repair_loop(
            semantic_fault_spec, ledger_path=tmp.name, max_rounds=3
        )
        # Should not guess or delete the unknown binding or unknown widget
        assert final_score < 80.0
        widget = final_spec["screens"][0]["children"][0]
        assert widget["kind"] == "custom_quantum_widget"
        assert widget["bind"] == "undeclared_target_var"

        tmp.seek(0)
        lines = [json.loads(line) for line in tmp if line.strip()]
        assert len(lines) >= 1
        assert lines[0]["status"] in ("repaired", "manual_review_needed")
        assert len(lines[0]["unresolved"]) > 0

    print("  PASS test_non_mechanical_fault_reported_not_guessed")


def test_repair_max_rounds_boundary():
    hopeless_spec = {
        "screens": [
            {
                "id": "unfixable",
                "children": [{"kind": "unsupported_device", "bind": "ghost_state"}],
            }
        ]
    }
    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl") as tmp:
        final_spec, final_score, remaining = run_verify_repair_loop(
            hopeless_spec, ledger_path=tmp.name, max_rounds=3
        )
        assert final_score < 80.0

        tmp.seek(0)
        lines = [json.loads(line) for line in tmp if line.strip()]
        assert 1 <= len(lines) <= 3

    print("  PASS test_repair_max_rounds_boundary")


if __name__ == "__main__":
    test_rubric_load_and_sum()
    test_verify_clean_spec()
    test_verify_broken_spec_scores_low()
    test_repair_mechanical_faults()
    test_non_mechanical_fault_reported_not_guessed()
    test_repair_max_rounds_boundary()
    print("all verify_repair tests passed cleanly")
