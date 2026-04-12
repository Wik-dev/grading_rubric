"""Integration tests — DR-INT-02 / DR-INT-07 Validance workflow definitions.

Tests verify that the SDK Workflow objects validate cleanly and have the
expected structure. These tests do NOT require a live Validance instance;
they exercise the `validance-sdk` API locally.
"""

from __future__ import annotations

import pytest

from validance.workflow import (
    WORKFLOWS,
    WORKFLOW_DESCRIPTIONS,
    create_assess_and_improve_workflow,
    create_train_scorer_workflow,
)


class TestAssessAndImproveWorkflow:
    """DR-INT-02: grading_rubric.assess_and_improve has 6 tasks."""

    def test_creates_valid_workflow(self) -> None:
        wf = create_assess_and_improve_workflow()
        wf.validate()  # raises on invalid structure

    def test_has_six_tasks(self) -> None:
        wf = create_assess_and_improve_workflow()
        assert len(wf.tasks) == 6

    def test_task_names(self) -> None:
        wf = create_assess_and_improve_workflow()
        names = list(wf.tasks.keys())
        expected = ["ingest", "parse_inputs", "assess", "propose", "score", "render"]
        assert names == expected

    def test_propose_has_human_confirm_gate(self) -> None:
        """DR-INT-06: the propose task carries a human-confirm gate."""
        wf = create_assess_and_improve_workflow()
        propose = wf.tasks["propose"]
        assert propose.gate == "human-confirm"

    def test_assess_has_api_key_secret(self) -> None:
        wf = create_assess_and_improve_workflow()
        assess = wf.tasks["assess"]
        assert "ANTHROPIC_API_KEY" in (assess.secret_refs or [])

    def test_task_chain_dependencies(self) -> None:
        """Task dependencies form a linear chain."""
        wf = create_assess_and_improve_workflow()
        t = wf.tasks
        assert t["ingest"].depends_on == []
        assert t["parse_inputs"].depends_on == ["ingest"]
        assert t["assess"].depends_on == ["parse_inputs"]
        assert t["propose"].depends_on == ["assess"]
        assert t["score"].depends_on == ["propose"]
        assert t["render"].depends_on == ["score"]

    def test_definition_hash_is_stable(self) -> None:
        """DR-INT-07: same definition → same hash (idempotency)."""
        h1 = create_assess_and_improve_workflow().definition_hash
        h2 = create_assess_and_improve_workflow().definition_hash
        assert h1 == h2


class TestTrainScorerWorkflow:
    """DR-INT-02: grading_rubric.train_scorer has 1 task."""

    def test_creates_valid_workflow(self) -> None:
        wf = create_train_scorer_workflow()
        wf.validate()

    def test_has_one_task(self) -> None:
        wf = create_train_scorer_workflow()
        assert len(wf.tasks) == 1
        assert "train_scorer" in wf.tasks

    def test_definition_hash_is_stable(self) -> None:
        h1 = create_train_scorer_workflow().definition_hash
        h2 = create_train_scorer_workflow().definition_hash
        assert h1 == h2


class TestWorkflowRegistry:
    """DR-INT-02: the WORKFLOWS dict exports both workflow factories."""

    def test_both_workflows_registered(self) -> None:
        assert "assess_and_improve" in WORKFLOWS
        assert "train_scorer" in WORKFLOWS

    def test_descriptions_present(self) -> None:
        assert "assess_and_improve" in WORKFLOW_DESCRIPTIONS
        assert "train_scorer" in WORKFLOW_DESCRIPTIONS
