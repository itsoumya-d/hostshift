"""Tests for environment infrastructure telemetry and host health monitoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure hostshift package root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hostshift.telemetry import (
    ClusterTelemetryReport,
    HealthThresholds,
    NodeTelemetrySample,
    aggregate_cluster_telemetry,
    detect_degraded_nodes,
    evaluate_node_telemetry,
    summarize_telemetry_json,
)


def test_telemetry_normal_sample_evaluation():
    """Verify healthy telemetry sample correctly evaluates with positive score."""
    sample = NodeTelemetrySample(
        node_id="node-alpha",
        timestamp_utc="2026-11-28T12:00:00Z",
        cpu_percent=45.0,
        memory_percent=55.0,
        latency_ms=25.0,
        active_workers=8,
        error_count=0,
    )
    res = evaluate_node_telemetry(sample)
    assert res.node_id == "node-alpha"
    assert res.status == "HEALTHY"
    assert res.is_available is True
    assert res.score == 1.0
    assert len(res.breached_metrics) == 0


def test_telemetry_empty_sample_list_rejected():
    """Verify empty sample list raises ValueError during cluster aggregation."""
    threw = False
    try:
        aggregate_cluster_telemetry([])
    except ValueError as err:
        threw = True
        assert "empty sample list" in str(err)
    assert threw, "Expected ValueError on empty sample list"


def test_telemetry_malformed_metric_bounds_raises_error():
    """Verify malformed inputs with out-of-bounds metrics raise informative ValueErrors."""
    # Malformed cpu percent (> 100)
    sample_bad_cpu = NodeTelemetrySample(
        node_id="node-bad-cpu",
        timestamp_utc="2026-11-28T12:00:00Z",
        cpu_percent=125.0,
        memory_percent=50.0,
        latency_ms=20.0,
        active_workers=2,
        error_count=0,
    )
    threw_cpu = False
    try:
        evaluate_node_telemetry(sample_bad_cpu)
    except ValueError:
        threw_cpu = True
    assert threw_cpu, "Expected ValueError on malformed cpu_percent > 100"

    # Malformed negative latency
    sample_bad_latency = NodeTelemetrySample(
        node_id="node-bad-latency",
        timestamp_utc="2026-11-28T12:00:00Z",
        cpu_percent=50.0,
        memory_percent=50.0,
        latency_ms=-12.5,
        active_workers=2,
        error_count=0,
    )
    threw_latency = False
    try:
        evaluate_node_telemetry(sample_bad_latency)
    except ValueError:
        threw_latency = True
    assert threw_latency, "Expected ValueError on negative latency_ms"

    # Malformed empty node_id
    sample_empty_id = NodeTelemetrySample(
        node_id="   ",
        timestamp_utc="2026-11-28T12:00:00Z",
        cpu_percent=50.0,
        memory_percent=50.0,
        latency_ms=10.0,
        active_workers=2,
        error_count=0,
    )
    threw_id = False
    try:
        evaluate_node_telemetry(sample_empty_id)
    except ValueError:
        threw_id = True
    assert threw_id, "Expected ValueError on whitespace node_id"


def test_telemetry_boundary_threshold_triggers_alert():
    """Verify boundary values exactly matching threshold limits trigger warning status."""
    thresholds = HealthThresholds(max_cpu_percent=80.0, max_memory_percent=85.0)
    sample = NodeTelemetrySample(
        node_id="node-boundary",
        timestamp_utc="2026-11-28T12:00:00Z",
        cpu_percent=80.0,  # Exactly at threshold
        memory_percent=50.0,
        latency_ms=40.0,
        active_workers=4,
        error_count=0,
    )
    res = evaluate_node_telemetry(sample, thresholds=thresholds)
    assert res.status == "WARNING"
    assert "CPU" in res.breached_metrics
    assert res.is_available is True
    assert res.score < 1.0


def test_telemetry_missing_node_or_degraded_cluster_detection():
    """Verify multi-node aggregation detects missing/degraded hosts and flags availability."""
    s1 = NodeTelemetrySample("host-1", "2026-11-28T12:00:00Z", 30.0, 40.0, 20.0, 4, 0)
    s2 = NodeTelemetrySample("host-2", "2026-11-28T12:00:00Z", 92.0, 95.0, 40.0, 4, 1)  # Critical
    s3 = NodeTelemetrySample("host-3", "2026-11-28T12:00:00Z", 40.0, 40.0, 150.0, 4, 0)  # Warning

    report = aggregate_cluster_telemetry([s1, s2, s3])
    assert report.total_nodes == 3
    assert report.healthy_nodes == 1
    assert report.degraded_nodes == 2
    assert report.overall_availability_ratio == round(1 / 3, 4)

    degraded = detect_degraded_nodes(report)
    assert degraded == ["host-2", "host-3"]
    assert report.evaluations["host-2"].status == "CRITICAL"
    assert report.evaluations["host-2"].is_available is False
    assert report.evaluations["host-3"].status == "WARNING"
    assert report.evaluations["host-3"].is_available is True


def test_telemetry_property_availability_ratio_bounded():
    """Property invariant: overall availability ratio must strictly be in [0.0, 1.0]."""
    samples = [
        NodeTelemetrySample(f"worker-{i}", "2026-11-28T12:00:00Z", i * 10.0, 50.0, 20.0, 2, 0)
        for i in range(10)
    ]
    report = aggregate_cluster_telemetry(samples)
    assert 0.0 <= report.overall_availability_ratio <= 1.0
    assert report.healthy_nodes + report.degraded_nodes == report.total_nodes
    assert isinstance(report, ClusterTelemetryReport)


def test_telemetry_invalid_json_serialization_roundtrip():
    """Verify cluster summary produces valid, parseable JSON data."""
    s = NodeTelemetrySample("srv-test", "2026-11-28T12:00:00Z", 45.0, 45.0, 20.0, 2, 0)
    report = aggregate_cluster_telemetry([s])
    raw_json = summarize_telemetry_json(report)
    parsed = json.loads(raw_json)
    assert parsed["total_nodes"] == 1
    assert parsed["healthy_nodes"] == 1
    assert "srv-test" in parsed["evaluations"]
    assert parsed["evaluations"]["srv-test"]["status"] == "HEALTHY"


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = skipped = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    ran = len(fns) - failed - skipped
    print(f"\n{ran}/{len(fns)} passed, {skipped} skipped")
    sys.exit(1 if failed else 0)
