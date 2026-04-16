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
)


class TestAssessAndImproveWorkflow:
    """DR-INT-02: grading_rubric.assess_and_improve — 6 stages, 6 Validance tasks."""

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

    def test_score_has_human_confirm_gate(self) -> None:
        """DR-INT-06: human-confirm gate on score (fires before scoring, after propose outputs are available)."""
        wf = create_assess_and_improve_workflow()
        score = wf.tasks["score"]
        assert score.gate == "human-confirm"

    def test_assess_has_api_key_secrets(self) -> None:
        """Both API keys in secret_refs; no hardcoded backend in environment."""
        wf = create_assess_and_improve_workflow()
        assess = wf.tasks["assess"]
        assert "ANTHROPIC_API_KEY" in (assess.secret_refs or [])
        assert "OPENAI_API_KEY" in (assess.secret_refs or [])
        # Backend is not hardcoded — Settings.from_env() defaults apply
        assert "GR_OCR_BACKEND" not in (assess.environment or {})

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

    def test_ingest_uses_input_root(self) -> None:
        """ADR-007: ingest task scans the staged input directory."""
        wf = create_assess_and_improve_workflow()
        ingest = wf.tasks["ingest"]
        assert "--input-root inputs" in ingest.command
        assert ingest.inputs == {}
        assert "ingest_outputs" in ingest.output_files

    def test_parse_inputs_task(self) -> None:
        """ADR-007 § 9: parse_inputs receives staged files via trigger_inputs."""
        wf = create_assess_and_improve_workflow()
        parse = wf.tasks["parse_inputs"]
        assert "parse-inputs" in parse.command
        assert parse.trigger_inputs is True
        assert parse.depends_on == ["ingest"]
        assert "ingest_outputs.json" in parse.inputs
        assert parse.inputs["ingest_outputs.json"] == "@ingest:ingest_outputs"
        assert "parsed_inputs" in parse.output_files
        assert "ANTHROPIC_API_KEY" in (parse.secret_refs or [])
        assert "OPENAI_API_KEY" in (parse.secret_refs or [])

    def test_definition_hash_is_stable(self) -> None:
        """DR-INT-07: same definition → same hash (idempotency)."""
        h1 = create_assess_and_improve_workflow().definition_hash
        h2 = create_assess_and_improve_workflow().definition_hash
        assert h1 == h2


class TestWorkflowRegistry:
    """DR-INT-02: the WORKFLOWS dict exports the workflow factory."""

    def test_workflow_registered(self) -> None:
        assert "assess_and_improve" in WORKFLOWS

    def test_descriptions_present(self) -> None:
        assert "assess_and_improve" in WORKFLOW_DESCRIPTIONS
