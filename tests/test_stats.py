"""Inferential statistics.

The benchmark produces roughly 7,200 runs from 100 tasks. Treating those runs as
independent observations would inflate the effective sample by an order of
magnitude and narrow every confidence interval accordingly -- which is grounds
for rejection at any serious venue, and worse, would let noise masquerade as a
finding.

Two corrections are tested here: collapsing repeats before inference, and
resampling whole tasks rather than individual runs.
"""

import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.metrics import (  # noqa: E402
    TaskOutcome, bootstrap_hli, bootstrap_ip, cluster_bootstrap,
    collapse_repeats, host_lock_index, interaction_parity, repeat_reliability,
    wilson_interval,
)


def _cells(spec: dict[tuple[str, str], list[bool]]) -> list[TaskOutcome]:
    return [TaskOutcome(t, h, ok) for (t, h), res in spec.items() for ok in res]


# ------------------------------------------------------- collapsing repeats

def test_collapse_reduces_repeats_to_one_observation_per_cell():
    outs = _cells({("t1", "web"): [True, True, False],
                   ("t1", "tui"): [False, False, False],
                   ("t2", "web"): [True, False, True]})
    col = collapse_repeats(outs)
    assert len(col) == 3
    assert {(o.task_id, o.host): o.success for o in col} == {
        ("t1", "web"): True, ("t1", "tui"): False, ("t2", "web"): True}


def test_collapse_uses_a_strict_majority():
    """A 1-of-2 cell is not a success. Ties resolving to success would bias
    every cell with an even repeat count upward."""
    assert collapse_repeats(_cells({("t", "web"): [True, False]}))[0].success is False
    assert collapse_repeats(_cells({("t", "web"): [True, True, False]}))[0].success is True


def test_collapse_is_idempotent():
    outs = _cells({("t1", "web"): [True], ("t2", "web"): [False]})
    assert len(collapse_repeats(collapse_repeats(outs))) == len(collapse_repeats(outs))


def test_repeat_reliability_detects_flapping_cells():
    """Cells that flip between attempts are reporting operator variance, not a
    property of the interface. The paper has to disclose the rate."""
    stable = _cells({("t1", "web"): [True, True, True],
                     ("t2", "web"): [False, False, False]})
    assert repeat_reliability(stable)["flip_rate"] == 0.0

    flappy = _cells({("t1", "web"): [True, False, True],
                     ("t2", "web"): [False, True, False]})
    assert repeat_reliability(flappy)["flip_rate"] == 1.0


def test_repeat_reliability_reports_nothing_when_there_are_no_repeats():
    assert repeat_reliability(_cells({("t", "web"): [True]}))["unanimous_rate"] is None


def test_collapsing_unscoped_outcomes_would_merge_conditions():
    """Regression.

    `TaskOutcome` carries no generator or condition. Collapsing outcomes drawn
    from several of either, without a wider key, silently merges them -- which
    would pool condition A and condition B into one cell and destroy the
    comparison the whole experiment exists to make. The default is documented
    as (task, host); this pins the behaviour so a caller cannot be surprised.
    """
    mixed = [TaskOutcome("t1", "web", True), TaskOutcome("t1", "web", False)]
    assert len(collapse_repeats(mixed)) == 1, "default cell is (task, host)"

    # With the condition folded into the id, the two stay separate.
    scoped = [TaskOutcome("t1|A", "web", True), TaskOutcome("t1|B", "web", False)]
    assert len(collapse_repeats(scoped)) == 2


def test_reliability_on_unscoped_cells_overstates_the_attempt_count():
    """The bug this caught: pooling generators and conditions reported a mean
    of 18 attempts per cell when the experiment ran 3 repeats."""
    pooled, scoped = [], []
    for gen in ("g1", "g2", "g3"):
        for cond in ("A", "B"):
            for _ in range(3):
                pooled.append(TaskOutcome("t1", "web", True))
                scoped.append(TaskOutcome(f"t1|{gen}|{cond}", "web", True))
    assert repeat_reliability(pooled)["mean_repeats"] == 18.0
    assert repeat_reliability(scoped)["mean_repeats"] == 3.0


# ------------------------------------------------------- cluster bootstrap

def test_bootstrap_interval_brackets_the_point_estimate():
    outs = [TaskOutcome(f"t{i}", "web", i % 3 != 0) for i in range(60)]
    point = interaction_parity(outs)
    lo, hi = bootstrap_ip(outs, n_resamples=600)
    assert lo <= point <= hi
    assert 0.0 <= lo and hi <= 1.0


def test_bootstrap_is_deterministic_under_a_fixed_seed():
    outs = [TaskOutcome(f"t{i}", "web", i % 2 == 0) for i in range(40)]
    assert bootstrap_ip(outs, n_resamples=400, seed=7) == \
           bootstrap_ip(outs, n_resamples=400, seed=7)


def test_bootstrap_is_wider_than_wilson_when_outcomes_cluster_by_task():
    """The correction that matters.

    Task difficulty is shared across every host and repeat of that task. Wilson
    assumes those are independent draws; the cluster bootstrap does not, and
    must report a wider interval as a result.
    """
    rng = random.Random(11)
    outs = []
    for t in range(80):
        p = rng.choice([0.05, 0.95])          # strong clustering by task
        for h in ("web", "swiftui", "compose", "tui"):
            outs.append(TaskOutcome(f"t{t}", h, rng.random() < p))

    wlo, whi = wilson_interval(sum(1 for o in outs if o.success), len(outs))
    blo, bhi = bootstrap_ip(outs, n_resamples=1500)
    assert (bhi - blo) > (whi - wlo), (
        f"cluster bootstrap {bhi - blo:.3f} should exceed Wilson {whi - wlo:.3f}"
    )


def test_bootstrap_degenerates_gracefully_on_a_single_task():
    outs = [TaskOutcome("only", "web", True), TaskOutcome("only", "tui", False)]
    lo, hi = bootstrap_ip(outs, n_resamples=100)
    assert lo == hi == interaction_parity(outs)


def test_bootstrap_handles_an_arbitrary_statistic():
    outs = _cells({("t1", "web"): [True], ("t1", "tui"): [False],
                   ("t2", "web"): [True], ("t2", "tui"): [True],
                   ("t3", "web"): [True], ("t3", "tui"): [False]})
    lo, hi = cluster_bootstrap(outs, lambda o: host_lock_index(o).per_task_lock,
                               n_resamples=400)
    assert 0.0 <= lo <= hi <= 1.0


def test_bootstrap_hli_produces_a_usable_interval():
    rng = random.Random(3)
    outs = []
    for t in range(50):
        outs.append(TaskOutcome(f"t{t}", "web", rng.random() < 0.85))
        outs.append(TaskOutcome(f"t{t}", "tui", rng.random() < 0.35))
    lo, hi = bootstrap_hli(outs, n_resamples=800)
    point = host_lock_index(outs).hli
    assert lo <= point <= hi
    assert hi - lo > 0, "a real interval, not a degenerate point"


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
