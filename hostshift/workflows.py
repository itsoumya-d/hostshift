"""Financial workflow pipeline for multi-stage expense, limit, and approval modeling.

Provides declarative configuration, boundary validation, state-transition rules,
and synthesis into cross-platform HostShift UI specs (Web, Native Mobile, TUI).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class WorkflowValidationError(ValueError):
    """Raised when a financial workflow specification violates integrity constraints."""


class WorkflowTransitionError(RuntimeError):
    """Raised when a requested workflow state transition is invalid or unauthorized."""


@dataclass(frozen=True)
class WorkflowStep:
    """A single stage in an approval or processing pipeline."""

    step_id: str
    name: str
    required_role: str
    auto_approve_under: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinancialWorkflowConfig:
    """Configuration for an end-to-end financial operational workflow."""

    workflow_id: str
    title: str
    currency: str = "CAD"
    spending_limit: float = 10000.0
    require_receipt: bool = True
    steps: list[WorkflowStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "title": self.title,
            "currency": self.currency,
            "spending_limit": self.spending_limit,
            "require_receipt": self.require_receipt,
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass(frozen=True)
class TransitionResult:
    """Outcome of attempting a workflow state transition."""

    success: bool
    current_state: str
    next_state: str
    amount: float
    actor_role: str
    message: str


def validate_workflow_config(config: FinancialWorkflowConfig) -> bool:
    """Validate a financial workflow configuration against business and schema constraints.

    Raises:
        WorkflowValidationError: If any constraint is violated.
    """
    if not config.workflow_id or not config.workflow_id.strip():
        raise WorkflowValidationError("Workflow workflow_id cannot be empty.")
    if not config.title or not config.title.strip():
        raise WorkflowValidationError("Workflow title cannot be empty.")
    if config.currency not in {"CAD", "USD", "EUR", "GBP"}:
        raise WorkflowValidationError(f"Unsupported or malformed currency: {config.currency}")
    if config.spending_limit <= 0.0:
        raise WorkflowValidationError(
            f"Spending limit must be strictly positive, got {config.spending_limit}"
        )
    if not config.steps:
        raise WorkflowValidationError("Workflow must contain at least one step.")

    seen_steps: set[str] = set()
    for s in config.steps:
        if not s.step_id or not s.step_id.strip():
            raise WorkflowValidationError("Step step_id cannot be empty.")
        if s.step_id in seen_steps:
            raise WorkflowValidationError(f"Duplicate step ID found: {s.step_id}")
        seen_steps.add(s.step_id)
        if not s.required_role or not s.required_role.strip():
            raise WorkflowValidationError(f"Step '{s.step_id}' must specify a required role.")
        if s.auto_approve_under < 0.0:
            raise WorkflowValidationError(
                f"Step '{s.step_id}' auto_approve_under cannot be negative, "
                f"got {s.auto_approve_under}"
            )
    return True


def execute_workflow_transition(
    current_state: str,
    action: str,
    amount: float,
    user_role: str,
    config: FinancialWorkflowConfig,
    has_receipt: bool = True,
) -> TransitionResult:
    """Execute a guarded state transition in a financial workflow.

    Enforces currency limits, receipt mandates, role authorization, and valid states.
    """
    validate_workflow_config(config)

    if amount <= 0.0:
        raise WorkflowTransitionError(f"Transaction amount must be positive, got {amount}")
    if amount > config.spending_limit:
        return TransitionResult(
            success=False,
            current_state=current_state,
            next_state="REJECTED",
            amount=amount,
            actor_role=user_role,
            message=(
                f"Amount {amount:.2f} {config.currency} exceeds workflow "
                f"limit {config.spending_limit:.2f}"
            ),
        )
    if config.require_receipt and not has_receipt:
        return TransitionResult(
            success=False,
            current_state=current_state,
            next_state=current_state,
            amount=amount,
            actor_role=user_role,
            message="Receipt attachment required before workflow transition can proceed.",
        )

    valid_actions = {"approve", "reject", "escalate"}
    if action not in valid_actions:
        raise WorkflowTransitionError(
            f"Invalid workflow action '{action}'; must be one of {valid_actions}"
        )

    if action == "reject":
        return TransitionResult(
            success=True,
            current_state=current_state,
            next_state="REJECTED",
            amount=amount,
            actor_role=user_role,
            message="Workflow rejected by reviewer.",
        )

    # Find step corresponding to current state
    step_map = {s.step_id: s for s in config.steps}
    current_step = step_map.get(current_state)
    if not current_step:
        raise WorkflowTransitionError(
            f"Unknown or invalid current workflow state: {current_state}"
        )

    if user_role != current_step.required_role and user_role != "admin":
        raise WorkflowTransitionError(
            f"Unauthorized: role '{user_role}' cannot approve step '{current_state}' "
            f"(requires '{current_step.required_role}')"
        )

    step_ids = [s.step_id for s in config.steps]
    idx = step_ids.index(current_state)
    if idx + 1 < len(step_ids):
        next_st = step_ids[idx + 1]
    else:
        next_st = "COMPLETED"

    return TransitionResult(
        success=True,
        current_state=current_state,
        next_state=next_st,
        amount=amount,
        actor_role=user_role,
        message="Workflow transition completed successfully.",
    )


def synthesize_workflow_uispec(config: FinancialWorkflowConfig) -> dict[str, Any]:
    """Generate a valid HostShift 0.2 UISpec representation of the financial workflow."""
    validate_workflow_config(config)

    screens = []
    for step in config.steps:
        screens.append(
            {
                "id": f"screen_{step.step_id}",
                "title": f"{config.title} - {step.name}",
                "widgets": [
                    {
                        "type": "heading",
                        "text": f"{step.name} ({config.currency})",
                    },
                    {
                        "type": "field_input",
                        "bind": "amount",
                        "label": f"Amount in {config.currency}",
                    },
                    {
                        "type": "action_button",
                        "label": "Approve",
                        "action": f"approve_{step.step_id}",
                    },
                    {
                        "type": "action_button",
                        "label": "Reject",
                        "action": f"reject_{step.step_id}",
                    },
                ],
            }
        )

    return {
        "version": "0.2",
        "title": config.title,
        "entry": f"screen_{config.steps[0].step_id}",
        "state": {
            "amount": {"type": "number", "default": 0.0},
            "currency": {"type": "string", "default": config.currency},
            "current_step": {"type": "string", "default": config.steps[0].step_id},
            "status": {"type": "string", "default": "PENDING"},
        },
        "screens": screens,
    }
