"""Operator calibration tests.

These guard the fix for the most serious objection against the benchmark: that
Interaction Parity conflates interface portability with operator competence.
The normalization is only trustworthy if it behaves correctly in the two cases
that matter -- when the operator is uniformly weak on a host, and when it is
perfectly capable there.
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.calibration import (  # noqa: E402
    CALIBRATION_TASKS, CORPUS_REF, FIXTURE_PATHS, HOST_FIXTURE,
    CalibrationRun, CalibrationStore, report,
)
from hostshift.metrics import (  # noqa: E402
    OperatorCeiling, TaskOutcome, host_lock_index, normalized_host_lock,
)


def _outcomes(spec: dict[str, list[bool]]) -> list[TaskOutcome]:
    return [TaskOutcome(f"t{i}", host, ok)
            for host, res in spec.items() for i, ok in enumerate(res)]


# ------------------------------------------------------------- ceilings

def test_ceiling_is_a_completion_rate():
    c = OperatorCeiling("compose", attempted=10, completed=7)
    assert c.ceiling == 0.7
    assert OperatorCeiling("x", 0, 0).ceiling == 0.0


def test_calibration_run_accumulates_a_ceiling():
    run = CalibrationRun(host="compose", fixture="fixtures/compose", operator="cu-model")
    for t in CALIBRATION_TASKS[:8]:
        run.record(t.id, success=t.id != "cal-sheet")
    c = run.ceiling()
    assert c.attempted == 8 and c.completed == 7
    assert CORPUS_REF in c.corpus


# -------------------------------------------------------- normalization

def test_normalization_removes_a_pure_operator_deficit():
    """The case the whole control exists for.

    The operator is half as effective on the terminal even on hand-written
    code. Raw host-lock reads 0.5 and would be reported as a portability
    failure; after normalization it is zero, because the interfaces were
    equally good and the operator simply could not drive that host.
    """
    outcomes = _outcomes({
        "web": [True, True, True, True],
        "tui": [True, True, False, False],
    })
    raw = host_lock_index(outcomes)
    assert raw.hli == 0.5

    ceilings = {
        "web": OperatorCeiling("web", 10, 10),
        "tui": OperatorCeiling("tui", 10, 5),
    }
    norm = normalized_host_lock(outcomes, ceilings)
    assert norm.hli == 0.0, norm.as_row()


def test_normalization_preserves_a_genuine_portability_failure():
    """When the operator is equally capable on both hosts, a gap in generated
    output must survive normalization untouched."""
    outcomes = _outcomes({
        "web": [True, True, True, True],
        "compose": [True, False, False, False],
    })
    ceilings = {
        "web": OperatorCeiling("web", 10, 10),
        "compose": OperatorCeiling("compose", 10, 10),
    }
    raw = host_lock_index(outcomes)
    norm = normalized_host_lock(outcomes, ceilings)
    assert norm.hli == raw.hli == 0.75


def test_normalized_parity_is_clamped_at_one():
    """A host where generated output beats the hand-written ceiling must not
    exceed 1.0, or it would drag the best-host denominator upward and deflate
    every other host's apparent lock."""
    outcomes = _outcomes({"web": [True] * 4, "compose": [True] * 4})
    ceilings = {"web": OperatorCeiling("web", 10, 10),
                "compose": OperatorCeiling("compose", 10, 5)}
    norm = normalized_host_lock(outcomes, ceilings)
    assert all(v <= 1.0 for v in norm.per_host_ip.values())


def test_hosts_with_a_zero_ceiling_are_dropped_not_scored():
    """If the operator cannot work on a host at all, nothing about the
    interface is observable through it. Including it would attribute an
    operator failure to the generator."""
    outcomes = _outcomes({"web": [True, True], "tui": [False, False]})
    ceilings = {"web": OperatorCeiling("web", 10, 10),
                "tui": OperatorCeiling("tui", 10, 0)}
    norm = normalized_host_lock(outcomes, ceilings)
    assert "tui" not in norm.per_host_ip
    assert norm.hli == 0.0


def test_per_task_lock_is_carried_through_unrescaled():
    """Per-task lock counts hosts rather than measuring a rate, so dividing it
    by a ceiling would produce a number with no meaning."""
    outcomes = _outcomes({"web": [True, False], "compose": [False, True]})
    ceilings = {"web": OperatorCeiling("web", 10, 8),
                "compose": OperatorCeiling("compose", 10, 6)}
    assert (normalized_host_lock(outcomes, ceilings).per_task_lock
            == host_lock_index(outcomes).per_task_lock)


# ------------------------------------------------------------- reporting

def test_report_refuses_to_normalize_without_a_ceiling():
    """An uncalibrated run must say so loudly rather than emit a bare number a
    reader would take for a measurement."""
    with tempfile.TemporaryDirectory() as d:
        out = report(_outcomes({"web": [True], "tui": [False]}), CalibrationStore(d))
    assert out["normalized_hli"] is None
    assert "UNCALIBRATED" in out["status"]


def test_report_flags_partially_calibrated_runs():
    with tempfile.TemporaryDirectory() as d:
        store = CalibrationStore(d)
        run = CalibrationRun(host="compose", fixture="fixtures/compose", operator="cu")
        for t in CALIBRATION_TASKS:
            run.record(t.id, True)
        store.save(run)

        out = report(_outcomes({"compose": [True, True], "tui": [False, True]}), store)
    assert out["uncalibrated_hosts"] == ["tui"]
    assert "no operator ceiling" in out["warning"]


def test_report_quantifies_what_the_operator_accounts_for():
    with tempfile.TemporaryDirectory() as d:
        store = CalibrationStore(d)
        for host, completed in (("web", 10), ("compose", 5)):
            run = CalibrationRun(host=host, fixture=f"fixtures/{host}", operator="cu")
            for i in range(10):
                run.record(f"cal-{i}", i < completed)
            store.save(run)

        out = report(_outcomes({"web": [True] * 4, "compose": [True, True, False, False]}),
                     store)
    assert out["raw_hli"] == 0.5
    assert out["normalized_hli"] == 0.0
    assert out["attributable_to_operator"] == 0.5


def test_store_round_trips():
    with tempfile.TemporaryDirectory() as d:
        store = CalibrationStore(d)
        run = CalibrationRun(host="swiftui", fixture="fixtures/swiftui", operator="cu")
        run.record("cal-entry", True, steps=6)
        store.save(run)
        back = store.load_all()["swiftui"]
    assert back.host == "swiftui"
    assert back.outcomes[0]["steps"] == 6


# --------------------------------------------------------------- corpus

def test_corpus_mapping_is_explicit_about_what_it_cannot_calibrate():
    """A native corpus cannot calibrate a browser or a terminal. Saying so in
    the mapping is better than silently borrowing a native ceiling."""
    assert HOST_FIXTURE["compose"] == "compose"
    assert HOST_FIXTURE["swiftui"] == "swiftui"
    assert HOST_FIXTURE["web"] is None
    assert HOST_FIXTURE["tui"] is None


def test_calibration_tasks_cover_the_interaction_classes_in_the_suite():
    surfaces = {t.surface for t in CALIBRATION_TASKS}
    for needed in ("entry", "list", "detail", "form", "settings", "sheet",
                   "async", "navigation"):
        assert needed in surfaces, f"no calibration task exercises {needed}"
    assert len({t.id for t in CALIBRATION_TASKS}) == len(CALIBRATION_TASKS)


def test_all_four_fixtures_are_declared():
    assert set(FIXTURE_PATHS) == {"flutter", "react-native", "swiftui", "compose"}


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
