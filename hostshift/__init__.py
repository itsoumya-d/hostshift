"""HostShift: measuring cross-platform portability of LLM-generated UIs.

    from hostshift import runner
    from hostshift.render import open_session
    from hostshift.workflows import (
        FinancialWorkflowConfig,
        WorkflowStep,
        execute_workflow_transition,
        synthesize_workflow_uispec,
    )

The command line is the primary interface:

    hostshift --version
    hostshift plan | lint | demo | report | calibrate | coverage
"""

from __future__ import annotations

from .telemetry import (
    ClusterTelemetryReport,
    HealthThresholds,
    NodeHealthEvaluation,
    NodeTelemetrySample,
    aggregate_cluster_telemetry,
    detect_degraded_nodes,
    evaluate_node_telemetry,
    summarize_telemetry_json,
)
from .workflows import (
    FinancialWorkflowConfig,
    WorkflowStep,
    execute_workflow_transition,
    synthesize_workflow_uispec,
)

__version__ = "0.2.0"

__all__ = [
    "ClusterTelemetryReport",
    "FinancialWorkflowConfig",
    "HealthThresholds",
    "NodeHealthEvaluation",
    "NodeTelemetrySample",
    "WorkflowStep",
    "__version__",
    "aggregate_cluster_telemetry",
    "detect_degraded_nodes",
    "evaluate_node_telemetry",
    "execute_workflow_transition",
    "summarize_telemetry_json",
    "synthesize_workflow_uispec",
]
