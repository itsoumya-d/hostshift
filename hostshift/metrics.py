"""HostShift metrics.

Four numbers, in increasing order of what they cost to obtain:

  RP  Render Parity        -- structural: did the host build the tree the spec asked for?
  AP  Accessibility Parity -- did the host expose that tree to assistive technology?
  IP  Interaction Parity   -- functional: can an agent complete the task on this host?
  HLI Host-Lock Index      -- the headline: how much capability is lost by changing host?

RP and AP are cheap and run offline. IP requires the operator oracle. HLI is a
function of IP and is the number the paper is named after.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .widgettree import Widget, normalized_ted

# ---------------------------------------------------------------------------
# Render Parity
# ---------------------------------------------------------------------------


def render_parity(intended: Widget, realized: Widget) -> float:
    """1 - normalized tree edit distance. In [0, 1]; 1.0 is a perfect match."""
    return 1.0 - normalized_ted(intended, realized)


# ---------------------------------------------------------------------------
# Accessibility Parity
# ---------------------------------------------------------------------------


@dataclass
class A11yReport:
    named: int = 0
    unnamed: int = 0
    focusable_named: int = 0
    focusable_total: int = 0
    role_correct: int = 0
    role_total: int = 0

    @property
    def name_coverage(self) -> float:
        total = self.named + self.unnamed
        return self.named / total if total else 1.0

    @property
    def focusable_coverage(self) -> float:
        return self.focusable_named / self.focusable_total if self.focusable_total else 1.0

    @property
    def role_fidelity(self) -> float:
        return self.role_correct / self.role_total if self.role_total else 1.0

    @property
    def score(self) -> float:
        """Weighted toward focusable elements.

        An unnamed decorative container is a cosmetic defect. An unnamed button
        is an element a screen-reader user cannot invoke -- it is the difference
        between an ugly interface and an unusable one, and the metric should say
        so.
        """
        return round(
            0.2 * self.name_coverage
            + 0.5 * self.focusable_coverage
            + 0.3 * self.role_fidelity,
            4,
        )


def accessibility_parity(intended: Widget, realized: Widget) -> A11yReport:
    """Measure how much of the intended semantics survived into the host's
    accessibility tree.

    Roles are checked positionally against the intended tree's focusable nodes,
    matched by spec `node_id` where the host preserved it and by (kind, order)
    otherwise -- hosts differ in whether they propagate identifiers, and we do
    not want to punish a host for that alone.
    """
    rep = A11yReport()

    for node in realized.walk():
        if node.name and node.name.strip():
            rep.named += 1
        else:
            rep.unnamed += 1
        if node.focusable:
            rep.focusable_total += 1
            if node.name and node.name.strip():
                rep.focusable_named += 1

    intended_focusable = [n for n in intended.walk() if n.focusable]
    realized_focusable = [n for n in realized.walk() if n.focusable]

    by_id = {n.node_id: n for n in realized_focusable if n.node_id}
    used: set[int] = set()
    leftovers = [n for n in realized_focusable if not n.node_id]

    for want in intended_focusable:
        rep.role_total += 1
        got = by_id.get(want.node_id) if want.node_id else None
        if got is None:
            for k, cand in enumerate(leftovers):
                if k in used:
                    continue
                if cand.kind == want.kind:
                    got, _ = cand, used.add(k)
                    break
        if got is not None and got.kind == want.kind:
            rep.role_correct += 1

    return rep


# ---------------------------------------------------------------------------
# Interaction Parity
# ---------------------------------------------------------------------------


@dataclass
class TaskOutcome:
    task_id: str
    host: str
    success: bool
    steps: int = 0
    criteria_met: int = 0
    criteria_total: int = 0
    error: str | None = None

    @property
    def partial(self) -> float:
        return self.criteria_met / self.criteria_total if self.criteria_total else 0.0


def interaction_parity(outcomes: list[TaskOutcome]) -> float:
    """Fraction of attempted tasks the operator agent completed on this host."""
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.success) / len(outcomes)


# ---------------------------------------------------------------------------
# Host-Lock Index
# ---------------------------------------------------------------------------


@dataclass
class HostLock:
    per_host_ip: dict[str, float]
    hli: float
    best_host: str
    worst_host: str
    spread: float
    per_task_lock: float
    n_tasks: int = 0

    def as_row(self) -> dict:
        return {
            "hli": round(self.hli, 4),
            "per_task_lock": round(self.per_task_lock, 4),
            "best_host": self.best_host,
            "worst_host": self.worst_host,
            "spread": round(self.spread, 4),
            "n_tasks": self.n_tasks,
            **{f"ip_{h}": round(v, 4) for h, v in sorted(self.per_host_ip.items())},
        }


def host_lock_index(outcomes: list[TaskOutcome]) -> HostLock:
    """The headline metric.

    Two views, and the paper should report both because they answer different
    questions:

      aggregate HLI = 1 - (worst-host IP / best-host IP)
          "How much worse is the weakest host overall?" Sensitive to a single
          systematically broken host, which is what a deployer cares about.

      per-task lock = mean over tasks of (1 - #hosts-succeeding / #hosts-tried)
          "For a task that works somewhere, how often does it fail elsewhere?"
          Robust to a host that is uniformly mediocre, and it is the quantity a
          *user* of a generative-UI runtime actually experiences.

    A generator can score well on one and badly on the other; reporting only the
    flattering one would be the obvious way to cheat this benchmark.
    """
    if not outcomes:
        return HostLock({}, 0.0, "", "", 0.0, 0.0, 0)

    hosts = sorted({o.host for o in outcomes})
    per_host = {h: interaction_parity([o for o in outcomes if o.host == h]) for h in hosts}

    best_host = max(per_host, key=lambda h: per_host[h])
    worst_host = min(per_host, key=lambda h: per_host[h])
    best, worst = per_host[best_host], per_host[worst_host]

    hli = 0.0 if best <= 0 else 1.0 - (worst / best)

    by_task: dict[str, list[TaskOutcome]] = {}
    for o in outcomes:
        by_task.setdefault(o.task_id, []).append(o)

    locks = []
    for _tid, rows in by_task.items():
        tried = len(rows)
        won = sum(1 for r in rows if r.success)
        if won == 0:
            continue  # a task no host can do measures generator failure, not lock
        locks.append(1.0 - won / tried)

    return HostLock(
        per_host_ip=per_host,
        hli=hli,
        best_host=best_host,
        worst_host=worst_host,
        spread=best - worst,
        per_task_lock=statistics.mean(locks) if locks else 0.0,
        n_tasks=len(by_task),
    )


# ---------------------------------------------------------------------------
# Operator calibration
# ---------------------------------------------------------------------------


@dataclass
class OperatorCeiling:
    """How well the operator does on *known-good, human-authored* software.

    Without this, host-lock is uninterpretable. A computer-use model trained
    predominantly on browsers may fail a terminal task because the interface is
    bad or because it has never driven a terminal, and raw interaction parity
    cannot tell those apart. Measuring the operator against hand-written
    idiomatic apps on each host separates the two: whatever the operator cannot
    do on software a competent engineer wrote is the operator's limit, not the
    generated interface's.
    """

    host: str
    attempted: int
    completed: int
    corpus: str = ""

    @property
    def ceiling(self) -> float:
        return self.completed / self.attempted if self.attempted else 0.0


def normalized_host_lock(
    outcomes: list[TaskOutcome], ceilings: dict[str, OperatorCeiling]
) -> HostLock:
    """Host-lock with each host's interaction parity divided by the operator's
    ceiling on that host.

    Report this beside the raw figure, never instead of it. If normalized lock
    stays high, the portability claim survives and is far harder to attack. If
    it collapses, the honest finding is that most of the apparent host-lock was
    operator unfamiliarity -- which is a more interesting result about the
    operator than a weaker one about interfaces, and should be written up as
    such rather than buried.

    Hosts with a zero ceiling are dropped: the operator cannot work there at
    all, so nothing about the interface is observable through it, and including
    the host would silently attribute an operator failure to the generator.
    """
    if not outcomes:
        return HostLock({}, 0.0, "", "", 0.0, 0.0, 0)

    usable = {h: c for h, c in ceilings.items() if c.ceiling > 0}
    kept = [o for o in outcomes if o.host in usable]
    if not kept:
        return HostLock({}, 0.0, "", "", 0.0, 0.0, 0)

    raw = host_lock_index(kept)
    per_host = {
        h: min(1.0, ip / usable[h].ceiling) for h, ip in raw.per_host_ip.items()
    }

    best_host = max(per_host, key=lambda h: per_host[h])
    worst_host = min(per_host, key=lambda h: per_host[h])
    best, worst = per_host[best_host], per_host[worst_host]
    hli = 0.0 if best <= 0 else 1.0 - (worst / best)

    # Per-task lock is a count of hosts, not a rate, so it cannot be rescaled by
    # a ceiling. Carry the raw figure through and say so rather than inventing a
    # normalized version that would not mean anything.
    return HostLock(
        per_host_ip=per_host,
        hli=hli,
        best_host=best_host,
        worst_host=worst_host,
        spread=best - worst,
        per_task_lock=raw.per_task_lock,
        n_tasks=raw.n_tasks,
    )


def calibration_report(
    ceilings: dict[str, OperatorCeiling], raw: HostLock, normalized: HostLock
) -> dict:
    """The table that answers 'is this the interface or your operator?'"""
    return {
        "ceilings": {h: round(c.ceiling, 4) for h, c in sorted(ceilings.items())},
        "raw_hli": round(raw.hli, 4),
        "normalized_hli": round(normalized.hli, 4),
        "attributable_to_operator": round(max(0.0, raw.hli - normalized.hli), 4),
        "per_task_lock": round(raw.per_task_lock, 4),
        "note": (
            "per-task lock counts hosts and is not rescalable by a ceiling; "
            "the raw value is carried through unchanged"
        ),
    }


# ---------------------------------------------------------------------------
# Significance
# ---------------------------------------------------------------------------


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Used instead of the normal approximation because per-host, per-condition
    cells in this benchmark are small (n ~ 100) and success rates run close to
    the boundaries, where the normal approximation misbehaves.
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _cell_key(o: TaskOutcome) -> tuple:
    return (o.task_id, o.host)


def collapse_repeats(outcomes: list[TaskOutcome], key=_cell_key) -> list[TaskOutcome]:
    """Reduce repeats of the same cell to one observation.

    Repeats exist to measure operator reliability, not to enlarge the sample.
    Three attempts at the same task on the same host are near-perfectly
    correlated; counting them as three independent trials inflates the apparent
    sample threefold and narrows every interval accordingly. Majority vote
    first, then do inference on the collapsed cells.

    The default cell is (task, host). `TaskOutcome` carries no generator or
    condition, so passing outcomes drawn from several of either without a
    matching `key` would silently merge them and destroy the comparison the
    experiment exists to make. Scope the input, or supply a wider key.
    """
    cells: dict[tuple, list[TaskOutcome]] = {}
    for o in outcomes:
        cells.setdefault(key(o), []).append(o)

    out = []
    for _k, rows in sorted(cells.items(), key=lambda kv: str(kv[0])):
        wins = sum(1 for r in rows if r.success)
        out.append(TaskOutcome(
            task_id=rows[0].task_id, host=rows[0].host,
            success=wins * 2 > len(rows),
            steps=round(statistics.mean(r.steps for r in rows)) if rows else 0,
            criteria_met=max(r.criteria_met for r in rows),
            criteria_total=rows[0].criteria_total,
        ))
    return out


def repeat_reliability(outcomes: list[TaskOutcome], key=_cell_key) -> dict:
    """How often repeats of the same cell disagree.

    This is what the repeats are actually for, and it belongs in the paper: a
    benchmark whose cells flip between attempts is reporting operator variance
    as though it were a property of the interface.

    Same warning as `collapse_repeats`: the cell must be scoped to one
    generator and one condition, or this measures cross-generator disagreement
    and reports it as unreliability.
    """
    cells: dict[tuple, list[bool]] = {}
    for o in outcomes:
        cells.setdefault(key(o), []).append(o.success)

    repeated = {k: v for k, v in cells.items() if len(v) > 1}
    if not repeated:
        return {"cells_with_repeats": 0, "unanimous_rate": None}

    unanimous = sum(1 for v in repeated.values() if all(v) or not any(v))
    return {
        "cells_with_repeats": len(repeated),
        "unanimous_rate": round(unanimous / len(repeated), 4),
        "flip_rate": round(1 - unanimous / len(repeated), 4),
        "mean_repeats": round(statistics.mean(len(v) for v in repeated.values()), 2),
    }


def cluster_bootstrap(
    outcomes: list[TaskOutcome],
    statistic,
    n_resamples: int = 10000,
    seed: int = 20260829,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval, resampling whole tasks.

    Tasks are the independent unit here, not runs. A task contributes one
    generated artifact rendered on every host, so its outcomes are correlated
    across hosts and conditions; resampling runs would treat that shared
    artifact as several independent draws. Resampling task clusters preserves
    the dependence structure and yields intervals that are honest about the
    effective sample size -- which is closer to the task count than to the run
    count, and materially smaller than a naive Wilson interval implies.

    `statistic` takes a list of outcomes and returns a float.
    """
    import random as _random

    by_task: dict[str, list[TaskOutcome]] = {}
    for o in outcomes:
        by_task.setdefault(o.task_id, []).append(o)
    tasks = sorted(by_task)
    if len(tasks) < 2:
        v = statistic(outcomes)
        return (v, v)

    rng = _random.Random(seed)
    vals = []
    for _ in range(n_resamples):
        drawn = [by_task[rng.choice(tasks)] for _ in tasks]
        flat = [o for group in drawn for o in group]
        try:
            vals.append(statistic(flat))
        except (ZeroDivisionError, ValueError):
            continue

    if not vals:
        return (0.0, 0.0)
    vals.sort()
    lo = vals[int((alpha / 2) * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return (lo, hi)


def bootstrap_hli(outcomes: list[TaskOutcome], **kw) -> tuple[float, float]:
    """Cluster-bootstrap interval for the headline metric."""
    return cluster_bootstrap(outcomes, lambda o: host_lock_index(o).hli, **kw)


def bootstrap_ip(outcomes: list[TaskOutcome], **kw) -> tuple[float, float]:
    return cluster_bootstrap(outcomes, interaction_parity, **kw)


def mcnemar(pairs: list[tuple[bool, bool]]) -> dict:
    """Exact McNemar test over paired success/failure.

    The right test for "does condition B beat condition A" here, because every
    task is attempted under both conditions -- the observations are paired, and
    an unpaired test would throw away that structure and understate power.
    """
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if y and not x)
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "p_value": 1.0, "note": "no discordant pairs"}

    # two-sided exact binomial against p=0.5
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / (2**n)
    return {"b": b, "c": c, "n_discordant": n, "p_value": min(1.0, 2 * tail)}


# ---------------------------------------------------------------------------
# Roll-up
# ---------------------------------------------------------------------------


@dataclass
class ConditionResult:
    condition: str            # "A-freeform" | "B-schema"
    generator: str            # model id
    outcomes: list[TaskOutcome] = field(default_factory=list)
    rp: dict[str, list[float]] = field(default_factory=dict)
    ap: dict[str, list[float]] = field(default_factory=dict)

    def summary(self) -> dict:
        lock = host_lock_index(self.outcomes)
        succ = sum(1 for o in self.outcomes if o.success)
        lo, hi = wilson_interval(succ, len(self.outcomes))
        return {
            "condition": self.condition,
            "generator": self.generator,
            "n_trials": len(self.outcomes),
            "overall_ip": round(succ / len(self.outcomes), 4) if self.outcomes else 0.0,
            "overall_ip_ci95": [round(lo, 4), round(hi, 4)],
            "mean_rp": {h: round(statistics.mean(v), 4) for h, v in self.rp.items() if v},
            "mean_ap": {h: round(statistics.mean(v), 4) for h, v in self.ap.items() if v},
            **lock.as_row(),
        }
