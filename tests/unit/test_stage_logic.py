"""Unit tests — stage logic with stub gateway / canned responses.

UT-STG-01 through UT-STG-09. Exercises each stage's deterministic offline
path. No LLM calls, no network, no Validance.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from grading_rubric.assess.engines import AmbiguityEngine, ApplicabilityEngine, DiscriminationEngine
from grading_rubric.assess.models import AssessOutputs
from grading_rubric.assess.stage import assess_stage
from grading_rubric.audit.emitter import NullEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.improve.models import PlannerDecision, ProposeOutputs
from grading_rubric.improve.stage import (
    _plan_drafts,
    _step1_conflict_resolution,
    _step2_canonical_order,
    _step3_apply_and_wrap,
    propose_stage,
)
from grading_rubric.models.deliverable import ExplainedRubricFile
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    ConfidenceLevel,
    Measurement,
    QualityCriterion,
    QualityMethod,
    Severity,
)
from grading_rubric.models.proposed_change import ApplicationStatus, TeacherDecision
from grading_rubric.models.rubric import (
    EvidenceProfile,
    Rubric,
    RubricCriterion,
    RubricFieldName,
    RubricLevel,
    RubricTarget,
)
from grading_rubric.parsers.models import IngestInputs, IngestOutputs, ParsedInputs
from grading_rubric.models.audit import InputProvenance, InputSource, InputSourceKind

from tests.conftest import CRIT_A_ID, CRIT_B_ID, LEVEL_A1_ID, LEVEL_A2_ID, RUBRIC_ID


# ── Helpers ─────────────────────────────────────────────────────────────────


def _stub_settings() -> Settings:
    return Settings(llm_backend="stub", llm_model_pinned="stub-test-model")


def _evidence(*, copies: bool = False, synthetic: bool = True) -> EvidenceProfile:
    return EvidenceProfile(
        starting_rubric_present=True,
        exam_question_present=True,
        teaching_material_present=False,
        student_copies_present=copies,
        student_copies_count=3 if copies else 0,
        synthetic_responses_used=synthetic,
    )


def _rubric_with_vague_terms() -> Rubric:
    """A rubric whose criterion descriptions contain vague terms."""
    return Rubric(
        id=RUBRIC_ID,
        schema_version="1.0.0",
        title="Vague Rubric",
        total_points=20.0,
        criteria=[
            RubricCriterion(
                id=CRIT_A_ID,
                name="Criterion A",
                description="Student demonstrates appropriate understanding of the topic",
                points=10.0,
                levels=[
                    RubricLevel(id=LEVEL_A1_ID, label="Good", descriptor="d", points=10.0),
                    RubricLevel(id=LEVEL_A2_ID, label="Poor", descriptor="d", points=0.0),
                ],
            ),
            RubricCriterion(
                id=CRIT_B_ID,
                name="Criterion B",
                description="Identifies all relevant stakeholders in the case study and analyses their interactions",
                points=10.0,
                scoring_guidance="Look for at least 3 stakeholders mentioned by name with role descriptions",
                levels=[
                    RubricLevel(id=uuid4(), label="Excellent", descriptor="d", points=10.0),
                    RubricLevel(id=uuid4(), label="Weak", descriptor="d", points=0.0),
                ],
            ),
        ],
    )


def _make_parsed_inputs(rubric: Rubric | None, evidence: EvidenceProfile) -> ParsedInputs:
    """Build a ParsedInputs with an inline exam question (no real files)."""
    from pathlib import Path

    exam_hash = "a" * 64
    ingest_out = IngestOutputs(
        input_provenance=InputProvenance(
            exam_question=InputSource(
                kind=InputSourceKind.INLINE_TEXT,
                path=None,
                marker="<inline:exam>",
                hash=exam_hash,
            ),
            teaching_material=[],
            starting_rubric=None,
            student_copies=[],
        ),
        evidence_profile=evidence,
        inputs=IngestInputs(exam_question_path=Path("/dev/null")),
    )
    return ParsedInputs(
        ingest=ingest_out,
        exam_question_text="Describe the bad actors strategy.",
        teaching_material_text="",
        starting_rubric=rubric,
        synthetic_rubric_for_from_scratch=(
            Rubric(id=uuid4(), schema_version="1.0.0", title="<from-scratch>", total_points=0.0, criteria=[])
            if rubric is None
            else None
        ),
        student_copies_text=[],
    )


# ── UT-STG-01: assess stage — canned findings assembled ────────────────────


class TestAssessStage:
    """UT-STG-01 / UT-STG-02: assess stage deterministic path."""

    def test_assess_produces_findings(self) -> None:
        """UT-STG-01: assess with a vague rubric → findings assembled."""
        rubric = _rubric_with_vague_terms()
        parsed = _make_parsed_inputs(rubric, _evidence())
        result = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())

        assert isinstance(result, AssessOutputs)
        assert len(result.findings) >= 1
        # At least one ambiguity finding for the vague term "appropriate"
        ambiguity_findings = [f for f in result.findings if f.criterion == QualityCriterion.AMBIGUITY]
        assert len(ambiguity_findings) >= 1
        assert all(f.measurement.method == QualityMethod.LINGUISTIC_SWEEP for f in ambiguity_findings)

    def test_assess_empty_rubric_degenerate(self) -> None:
        """UT-STG-02: empty rubric → degenerate AssessOutputs with HIGH APPLICABILITY."""
        parsed = _make_parsed_inputs(None, _evidence())
        result = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())

        assert len(result.findings) == 1
        f = result.findings[0]
        assert f.criterion == QualityCriterion.APPLICABILITY
        assert f.severity == Severity.HIGH
        assert f.target is None  # rubric-wide


# ── UT-STG-03/04/05: propose stage — three paths ───────────────────────────


class TestProposeStage:
    """UT-STG-03..05: propose stage deterministic paths."""

    def test_modify_existing_path(self) -> None:
        """UT-STG-03: findings with targets → drafts → APPLIED changes."""
        rubric = _rubric_with_vague_terms()
        parsed = _make_parsed_inputs(rubric, _evidence())
        assessed = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())

        result = propose_stage(assessed, settings=_stub_settings(), audit_emitter=NullEmitter())
        assert isinstance(result, ProposeOutputs)
        assert len(result.proposed_changes) >= 1
        applied = [c for c in result.proposed_changes if c.application_status == ApplicationStatus.APPLIED]
        assert len(applied) >= 1
        assert all(c.teacher_decision == TeacherDecision.PENDING for c in result.proposed_changes)

    def test_generate_from_scratch_path(self) -> None:
        """UT-STG-04: no starting rubric → generator path (degenerate assess → propose)."""
        parsed = _make_parsed_inputs(None, _evidence())
        assessed = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())

        result = propose_stage(assessed, settings=_stub_settings(), audit_emitter=NullEmitter())
        assert isinstance(result, ProposeOutputs)
        # The from-scratch path produces no targeted findings (the single finding
        # has target=None), so the offline planner emits no drafts.
        # This is the expected behavior — the LLM planner would emit ADD_NODE drafts.

    def test_empty_improvement_path(self) -> None:
        """UT-STG-05: rubric with no issues → NO_CHANGES_NEEDED."""
        # A rubric with long descriptions and scoring guidance → no findings
        rubric = Rubric(
            id=RUBRIC_ID,
            schema_version="1.0.0",
            title="Perfect Rubric",
            total_points=20.0,
            criteria=[
                RubricCriterion(
                    id=CRIT_A_ID,
                    name="Stakeholder Identification",
                    description="Identifies and analyses all relevant stakeholders in the case study with explicit role descriptions and interaction patterns",
                    points=15.0,
                    scoring_guidance="Award full marks when 3+ stakeholders are named with roles. Deduct 3 points per missing stakeholder.",
                    levels=[
                        RubricLevel(id=LEVEL_A1_ID, label="Excellent", descriptor="d", points=15.0),
                        RubricLevel(id=LEVEL_A2_ID, label="Poor", descriptor="d", points=0.0),
                    ],
                ),
                RubricCriterion(
                    id=CRIT_B_ID,
                    name="Strategic Analysis",
                    description="Evaluates the strategic implications of identified adversarial behaviours using economic reasoning and game theory concepts",
                    points=5.0,
                    scoring_guidance="Full marks for causal chain from actors to systemic risk. Half marks for descriptive listing only.",
                    levels=[
                        RubricLevel(id=uuid4(), label="Excellent", descriptor="d", points=5.0),
                        RubricLevel(id=uuid4(), label="Weak", descriptor="d", points=0.0),
                    ],
                ),
            ],
        )
        parsed = _make_parsed_inputs(rubric, _evidence(copies=True, synthetic=False))
        assessed = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())

        result = propose_stage(assessed, settings=_stub_settings(), audit_emitter=NullEmitter())
        # No targeted findings → planner returns NO_CHANGES_NEEDED → empty changes
        assert len(result.proposed_changes) == 0


# ── UT-STG-06: score stage ─────────────────────────────────────────────────


class TestScoreStage:
    """UT-STG-06: score stage — severity-weighted criterion scores."""

    def test_score_produces_three_criteria(self) -> None:
        """Score stage always produces exactly three CriterionScore entries."""
        from grading_rubric.scorer.score_stage import score_stage

        rubric = _rubric_with_vague_terms()
        parsed = _make_parsed_inputs(rubric, _evidence())
        assessed = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())
        proposed = propose_stage(assessed, settings=_stub_settings(), audit_emitter=NullEmitter())

        result = score_stage(proposed, settings=_stub_settings(), audit_emitter=NullEmitter())
        criteria_in_scores = {s.criterion for s in result.quality_scores}
        assert criteria_in_scores == set(QualityCriterion)


# ── UT-STG-07: render stage ────────────────────────────────────────────────


class TestRenderStage:
    """UT-STG-07: render stage assembles ExplainedRubricFile."""

    def test_render_produces_valid_deliverable(self, tmp_path) -> None:
        from grading_rubric.output.render_stage import render_stage
        from grading_rubric.scorer.score_stage import score_stage

        rubric = _rubric_with_vague_terms()
        parsed = _make_parsed_inputs(rubric, _evidence())
        assessed = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())
        proposed = propose_stage(assessed, settings=_stub_settings(), audit_emitter=NullEmitter())
        scored = score_stage(proposed, settings=_stub_settings(), audit_emitter=NullEmitter())

        out_path = tmp_path / "output.json"
        result = render_stage(
            scored,
            output_path=out_path,
            settings=_stub_settings(),
            audit_emitter=NullEmitter(),
        )
        assert out_path.exists()
        # The ExplainedRubricFile model validates its own invariants on construction
        erf = result.explained_rubric
        assert isinstance(erf, ExplainedRubricFile)
        assert len(erf.quality_scores) == 3
        assert erf.improved_rubric is not None


# ── UT-STG-08: source_findings traceability ─────────────────────────────────


class TestSourceFindingsTraceability:
    """UT-STG-08: each draft's source_findings traces back to an AssessmentFinding.id."""

    def test_source_findings_valid(self) -> None:
        rubric = _rubric_with_vague_terms()
        parsed = _make_parsed_inputs(rubric, _evidence())
        assessed = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())
        proposed = propose_stage(assessed, settings=_stub_settings(), audit_emitter=NullEmitter())

        finding_ids = {f.id for f in proposed.findings}
        for change in proposed.proposed_changes:
            for sf_id in change.source_findings:
                assert sf_id in finding_ids, (
                    f"ProposedChange {change.id} references finding {sf_id} "
                    f"not in the assessment findings set"
                )


# ── UT-STG-09: grounding contradiction ──────────────────────────────────────


class TestGroundingContradiction:
    """UT-STG-09: teaching-material grounding pass (offline stub path).

    The offline planner does not implement a full grounding pass (that requires
    LLM calls). This test verifies the structural contract: the propose stage
    runs without error when teaching material is present, and the output shape
    is correct. True grounding contradiction detection is tested via the LLM
    gateway in the system integration tests (§ 3.4).
    """

    def test_propose_with_teaching_material_present(self) -> None:
        rubric = _rubric_with_vague_terms()
        evidence = EvidenceProfile(
            starting_rubric_present=True,
            exam_question_present=True,
            teaching_material_present=True,
            student_copies_present=False,
            synthetic_responses_used=True,
        )
        parsed = _make_parsed_inputs(rubric, evidence)
        assessed = assess_stage(parsed, settings=_stub_settings(), audit_emitter=NullEmitter())
        proposed = propose_stage(assessed, settings=_stub_settings(), audit_emitter=NullEmitter())

        assert isinstance(proposed, ProposeOutputs)
        # All changes should have valid source_findings
        finding_ids = {f.id for f in proposed.findings}
        for change in proposed.proposed_changes:
            for sf_id in change.source_findings:
                assert sf_id in finding_ids
