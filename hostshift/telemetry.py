"""Environment infrastructure telemetry and host health monitoring for HostShift.

Provides structured telemetry capture, multi-host metric evaluation, threshold-based
degradation analysis, and deterministic status serialization across benchmark execution hosts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NodeTelemetrySample:
    """Individual infrastructure node metrics sample captured during benchmark execution."""

    node_id: str
    timestamp_utc: str
    cpu_percent: float
    memory_percent: float
    latency_ms: float
    active_workers: int
    error_count: int


@dataclass(frozen=True)
class HealthThresholds:
    """Configurable health thresholds for operational infrastructure nodes."""

    max_cpu_percent: float = 85.0
    max_memory_percent: float = 90.0
    max_latency_ms: float = 120.0
    max_error_rate: float = 0.05


@dataclass(frozen=True)
class NodeHealthEvaluation:
    """Evaluated operational health status for a specific node."""

    node_id: str
    status: str  # "HEALTHY", "WARNING", "CRITICAL"
    is_available: bool
    breached_metrics: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class ClusterTelemetryReport:
    """Aggregated infrastructure health report across all monitored nodes."""

    total_nodes: int
    healthy_nodes: int
    degraded_nodes: int
    overall_availability_ratio: float
    evaluations: dict[str, NodeHealthEvaluation]


def evaluate_node_telemetry(
    sample: NodeTelemetrySample,
    thresholds: HealthThresholds | None = None,
) -> NodeHealthEvaluation:
    """Evaluate an individual node telemetry sample against operational thresholds.

    Raises:
        ValueError: If telemetry metric values fall outside valid physical bounds.
    """
    if not sample.node_id or not sample.node_id.strip():
        raise ValueError("node_id cannot be empty or whitespace")
    if not (0.0 <= sample.cpu_percent <= 100.0):
        raise ValueError(
            f"cpu_percent must be within [0.0, 100.0], got {sample.cpu_percent}"
        )
    if not (0.0 <= sample.memory_percent <= 100.0):
        raise ValueError(
            f"memory_percent must be within [0.0, 100.0], got {sample.memory_percent}"
        )
    if sample.latency_ms < 0.0:
        raise ValueError(f"latency_ms cannot be negative, got {sample.latency_ms}")
    if sample.active_workers < 0:
        raise ValueError(
            f"active_workers cannot be negative, got {sample.active_workers}"
        )
    if sample.error_count < 0:
        raise ValueError(f"error_count cannot be negative, got {sample.error_count}")

    cfg = thresholds or HealthThresholds()
    breaches: list[str] = []

    if sample.cpu_percent >= cfg.max_cpu_percent:
        breaches.append("CPU")
    if sample.memory_percent >= cfg.max_memory_percent:
        breaches.append("MEMORY")
    if sample.latency_ms >= cfg.max_latency_ms:
        breaches.append("LATENCY")
    if (
        sample.active_workers > 0
        and (sample.error_count / sample.active_workers) >= cfg.max_error_rate
    ):
        breaches.append("ERROR_RATE")
    elif sample.active_workers == 0 and sample.error_count > 0:
        breaches.append("ERROR_RATE")

    penalty = len(breaches) * 0.35
    score = max(0.0, min(1.0, round(1.0 - penalty, 4)))

    if len(breaches) >= 2 or sample.cpu_percent >= 98.0 or sample.memory_percent >= 98.0:
        status = "CRITICAL"
        is_available = False
    elif len(breaches) == 1:
        status = "WARNING"
        is_available = True
    else:
        status = "HEALTHY"
        is_available = True

    return NodeHealthEvaluation(
        node_id=sample.node_id,
        status=status,
        is_available=is_available,
        breached_metrics=tuple(breaches),
        score=score,
    )


def aggregate_cluster_telemetry(
    samples: list[NodeTelemetrySample],
    thresholds: HealthThresholds | None = None,
) -> ClusterTelemetryReport:
    """Aggregate telemetry samples across multiple nodes into an infrastructure status report.

    Raises:
        ValueError: If samples list is empty.
    """
    if not samples:
        raise ValueError("Cannot aggregate telemetry for empty sample list")

    evaluations: dict[str, NodeHealthEvaluation] = {}
    for sample in samples:
        evaluations[sample.node_id] = evaluate_node_telemetry(sample, thresholds)

    total = len(evaluations)
    healthy = sum(1 for ev in evaluations.values() if ev.status == "HEALTHY")
    degraded = total - healthy
    availability = round(healthy / total, 4) if total > 0 else 0.0

    return ClusterTelemetryReport(
        total_nodes=total,
        healthy_nodes=healthy,
        degraded_nodes=degraded,
        overall_availability_ratio=availability,
        evaluations=evaluations,
    )


def detect_degraded_nodes(report: ClusterTelemetryReport) -> list[str]:
    """Return identifiers of nodes currently in WARNING or CRITICAL state."""
    return sorted(
        node_id
        for node_id, ev in report.evaluations.items()
        if ev.status in ("WARNING", "CRITICAL")
    )


def summarize_telemetry_json(report: ClusterTelemetryReport) -> str:
    """Serialize cluster telemetry report into deterministic JSON string."""
    data = asdict(report)
    return json.dumps(data, indent=2, sort_keys=True)
