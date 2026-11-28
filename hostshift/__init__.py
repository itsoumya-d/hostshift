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

from .workflows import (
    FinancialWorkflowConfig,
    WorkflowStep,
    execute_workflow_transition,
    synthesize_workflow_uispec,
)

__version__ = "0.2.0"

__all__ = [
    "FinancialWorkflowConfig",
    "WorkflowStep",
    "__version__",
    "execute_workflow_transition",
    "synthesize_workflow_uispec",
]
