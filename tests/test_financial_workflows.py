from __future__ import annotations

import pytest

from hostshift.workflows import (
    FinancialWorkflowConfig,
    WorkflowStep,
    WorkflowTransitionError,
    WorkflowValidationError,
    execute_workflow_transition,
    synthesize_workflow_uispec,
    validate_workflow_config,
)


@pytest.fixture
def default_config() -> FinancialWorkflowConfig:
    return FinancialWorkflowConfig(
        workflow_id="wf_card_approval",
        title="Corporate Card Spend Approval",
        currency="CAD",
        spending_limit=5000.0,
        require_receipt=True,
        steps=[
            WorkflowStep(step_id="manager_review", name="Manager Review", required_role="manager"),
            WorkflowStep(step_id="finance_audit", name="Finance Audit", required_role="finance"),
        ],
    )


def test_workflow_execution_normal_approval(default_config: FinancialWorkflowConfig) -> None:
    """Normal execution through all sequential approval stages."""
    # Step 1: manager approves
    res1 = execute_workflow_transition(
        current_state="manager_review",
        action="approve",
        amount=1250.0,
        user_role="manager",
        config=default_config,
        has_receipt=True,
    )
    assert res1.success is True
    assert res1.current_state == "manager_review"
    assert res1.next_state == "finance_audit"

    # Step 2: finance approves -> completed
    res2 = execute_workflow_transition(
        current_state="finance_audit",
        action="approve",
        amount=1250.0,
        user_role="finance",
        config=default_config,
        has_receipt=True,
    )
    assert res2.success is True
    assert res2.current_state == "finance_audit"
    assert res2.next_state == "COMPLETED"


def test_workflow_empty_steps_rejected() -> None:
    """Empty or missing workflow steps must fail validation."""
    cfg = FinancialWorkflowConfig(
        workflow_id="empty_wf",
        title="Empty Workflow",
        currency="CAD",
        spending_limit=1000.0,
        steps=[],
    )
    with pytest.raises(WorkflowValidationError, match="at least one step"):
        validate_workflow_config(cfg)

    cfg_empty_id = FinancialWorkflowConfig(
        workflow_id="",
        title="Valid Title",
        steps=[WorkflowStep(step_id="s1", name="Step 1", required_role="lead")],
    )
    with pytest.raises(WorkflowValidationError, match="workflow_id cannot be empty"):
        validate_workflow_config(cfg_empty_id)

    cfg_empty_title = FinancialWorkflowConfig(
        workflow_id="w1",
        title="",
        steps=[WorkflowStep(step_id="s1", name="Step 1", required_role="lead")],
    )
    with pytest.raises(WorkflowValidationError, match="title cannot be empty"):
        validate_workflow_config(cfg_empty_title)


def test_workflow_malformed_currency_rejected() -> None:
    """Malformed or unsupported currency strings must be rejected."""
    cfg = FinancialWorkflowConfig(
        workflow_id="bad_curr",
        title="Invalid Currency",
        currency="XYZ",
        steps=[WorkflowStep(step_id="s1", name="Step 1", required_role="lead")],
    )
    with pytest.raises(WorkflowValidationError, match="Unsupported or malformed currency"):
        validate_workflow_config(cfg)


def test_workflow_spending_limit_boundary_enforcement(
    default_config: FinancialWorkflowConfig,
) -> None:
    """Boundary checking: exactly at limit succeeds; strictly above limit is rejected."""
    # Boundary: exactly at limit (5000.0) -> allowed
    res_at_limit = execute_workflow_transition(
        current_state="manager_review",
        action="approve",
        amount=5000.0,
        user_role="manager",
        config=default_config,
    )
    assert res_at_limit.success is True
    assert res_at_limit.next_state == "finance_audit"

    # Strictly above limit (5000.01) -> rejected
    res_over = execute_workflow_transition(
        current_state="manager_review",
        action="approve",
        amount=5000.01,
        user_role="manager",
        config=default_config,
    )
    assert res_over.success is False
    assert res_over.next_state == "REJECTED"
    assert "exceeds workflow limit" in res_over.message


def test_workflow_unauthorized_role_raises_error(
    default_config: FinancialWorkflowConfig,
) -> None:
    """Unauthorized role attempting approval must raise WorkflowTransitionError."""
    with pytest.raises(WorkflowTransitionError, match="Unauthorized: role 'analyst'"):
        execute_workflow_transition(
            current_state="manager_review",
            action="approve",
            amount=500.0,
            user_role="analyst",
            config=default_config,
        )


def test_workflow_invalid_transition_action_rejected(
    default_config: FinancialWorkflowConfig,
) -> None:
    """Invalid actions or unknown current states must be cleanly rejected with errors."""
    with pytest.raises(WorkflowTransitionError, match="Invalid workflow action"):
        execute_workflow_transition(
            current_state="manager_review",
            action="cancel_invalid",
            amount=500.0,
            user_role="manager",
            config=default_config,
        )

    with pytest.raises(WorkflowTransitionError, match="Unknown or invalid current workflow state"):
        execute_workflow_transition(
            current_state="nonexistent_step",
            action="approve",
            amount=500.0,
            user_role="manager",
            config=default_config,
        )

    # Negative amount error
    with pytest.raises(WorkflowTransitionError, match="must be positive"):
        execute_workflow_transition(
            current_state="manager_review",
            action="approve",
            amount=-10.0,
            user_role="manager",
            config=default_config,
        )


def test_workflow_missing_receipt_blocked(default_config: FinancialWorkflowConfig) -> None:
    """Missing required receipt halts transition and keeps current state."""
    res = execute_workflow_transition(
        current_state="manager_review",
        action="approve",
        amount=150.0,
        user_role="manager",
        config=default_config,
        has_receipt=False,
    )
    assert res.success is False
    assert res.current_state == "manager_review"
    assert res.next_state == "manager_review"
    assert "Receipt attachment required" in res.message


def test_workflow_synthesize_uispec_structure(default_config: FinancialWorkflowConfig) -> None:
    """Synthesizing UISpec produces valid 0.2 structure matching HostShift standards."""
    spec = synthesize_workflow_uispec(default_config)
    assert spec["version"] == "0.2"
    assert spec["title"] == default_config.title
    assert spec["entry"] == "screen_manager_review"
    assert len(spec["screens"]) == 2
    assert "amount" in spec["state"]
    assert "currency" in spec["state"]
    assert spec["state"]["currency"]["default"] == "CAD"
