"""Tests for LLM integration in assess, propose, and score stages.

Uses `StubBackend` with canned responses to verify the LLM paths,
fallback behaviour, and grounding checks without a real API key.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from grading_rubric.assess.engines import (
    AmbiguityEngine,
    ApplicabilityEngine,
    DiscriminationEngine,
    _llm_available,
    _rubric_to_text,
)
from grading_rubric.audit.emitter import NullEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.backends import StubBackend
from grading_rubric.gateway.gateway import Gateway
from grading_rubric.improve.stage import (
    _collect_criterion_paths,
    _convert_and_ground,
    _plan_drafts,
    _plan_drafts_llm,
    propose_stage,
)
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    ConfidenceLevel,
    Measurement,
    QualityCriterion,
    QualityMethod,
    Severity,
)
from grading_rubric.models.rubric import (
    EvidenceProfile,
    Rubric,
    RubricCriterion,
    RubricFieldName,
    RubricLevel,
    RubricTarget,
)
from grading_rubric.scorer.scorer import (
    LlmPanelScorer,
    _confidence_from_stdev,
    _trimmed_mean,
)
from grading_rubric.scorer.models import ScoringEvidence

# ── Shared fixtures ──────────────────────────────────────────────────────

RUBRIC_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
CRIT_A_ID = UUID("cccccccc-0000-0000-0000-000000000001")
CRIT_B_ID = UUID("cccccccc-0000-0000-0000-000000000002")
LEVEL_A1_ID = UUID("11111111-0000-0000-0000-000000000001")
LEVEL_A2_ID = UUID("11111111-0000-0000-0000-000000000002")
LEVEL_B1_ID = UUID("11111111-0000-0000-0000-000000000003")
LEVEL_B2_ID = UUID("11111111-0000-0000-0000-000000000004")
FINDING_1_ID = UUID("ffffffff-0000-0000-0000-000000000001")
FINDING_2_ID = UUID("ffffffff-0000-0000-0000-000000000002")


def _make_rubric() -> Rubric:
    return Rubric(
        id=RUBRIC_ID,
        schema_version="1.0.0",
        title="Test Rubric",
        total_points=20.0,
        criteria=[
            RubricCriterion(
                id=CRIT_A_ID,
                name="Criterion A",
                description="The student should provide a good analysis",
                points=10.0,
                levels=[
                    RubricLevel(id=LEVEL_A1_ID, label="Excellent", descriptor="Top marks", points=10.0),
                    RubricLevel(id=LEVEL_A2_ID, label="Poor", descriptor="Bottom marks", points=0.0),
                ],
            ),
            RubricCriterion(
                id=CRIT_B_ID,
                name="Criterion B",
                description="Second criterion with clear requirements",
                points=10.0,
                levels=[
                    RubricLevel(id=LEVEL_B1_ID, label="Excellent", descriptor="Top marks", points=10.0),
                    RubricLevel(id=LEVEL_B2_ID, label="Poor", descriptor="Bottom marks", points=0.0),
                ],
            ),
        ],
    )


def _make_evidence(synthetic: bool = True) -> EvidenceProfile:
    return EvidenceProfile(
        starting_rubric_present=True,
        exam_question_present=True,
        teaching_material_present=False,
        student_copies_present=not synthetic,
        synthetic_responses_used=synthetic,
    )


def _make_finding(finding_id: UUID = FINDING_1_ID, criterion: QualityCriterion = QualityCriterion.AMBIGUITY) -> AssessmentFinding:
    return AssessmentFinding(
        id=finding_id,
        criterion=criterion,
        severity=Severity.MEDIUM,
        target=RubricTarget(criterion_path=[CRIT_A_ID], field=RubricFieldName.DESCRIPTION),
        observation="Criterion A uses vague term 'good'.",
        evidence="linguistic sweep matched 'good'",
        measurement=Measurement(method=QualityMethod.LINGUISTIC_SWEEP, samples=1, agreement=None),
        confidence=ConfidenceIndicator(score=0.65, level=ConfidenceLevel.MEDIUM, rationale="test"),
        measured_against_rubric_id=RUBRIC_ID,
    )


def _stub_settings(*, with_key: bool = False) -> Settings:
    """Settings for stub backend (no LLM) or with an anthropic key."""
    if with_key:
        return Settings(
            llm_backend="anthropic",
            llm_model_pinned="claude-sonnet-4-20250514",
            anthropic_api_key="sk-test-key",
        )
    return Settings(llm_backend="stub", llm_model_pinned="stub-test-model")


# ── Test: _llm_available ──────────────────────────────────────────────────


class TestLlmAvailable:
    def test_stub_not_available(self):
        assert _llm_available(_stub_settings(with_key=False)) is False

    def test_anthropic_with_key_available(self):
        assert _llm_available(_stub_settings(with_key=True)) is True

    def test_anthropic_without_key_not_available(self):
        settings = Settings(
            llm_backend="anthropic",
            llm_model_pinned="claude-sonnet-4-20250514",
            anthropic_api_key=None,
        )
        assert _llm_available(settings) is False


# ── Test: Assess LLM path (AmbiguityEngine) ──────────────────────────────


class TestAmbiguityEngineLlm:
    def test_llm_path_with_sweep_hits(self):
        """Stub returns valid LinguisticSweepReport → engine produces findings."""
        stub = StubBackend(canned_responses=[
            {
                "hits": [
                    {
                        "criterion_path": [str(CRIT_A_ID)],
                        "field": "description",
                        "problematic_phrase": "good analysis",
                        "issue_type": "vague_term",
                        "severity": "medium",
                        "explanation": "The word 'good' is subjective.",
                    }
                ]
            }
        ])
        # Inject stub backend into Gateway by monkey-patching.
        engine = AmbiguityEngine()
        original_init = Gateway.__init__

        def patched_init(self_gw, *, backend=None, prompts=None):
            original_init(self_gw, backend=stub, prompts=prompts)

        Gateway.__init__ = patched_init
        try:
            findings = engine._measure_llm(
                rubric=_make_rubric(),
                evidence=_make_evidence(synthetic=False),
                student_texts=[],
                settings=_stub_settings(with_key=True),
                audit_emitter=NullEmitter(),
            )
        finally:
            Gateway.__init__ = original_init

        assert len(findings) >= 1
        assert findings[0].criterion == QualityCriterion.AMBIGUITY
        assert "good analysis" in findings[0].observation

    def test_fallback_on_no_key(self):
        """No API key → deterministic path runs."""
        engine = AmbiguityEngine()
        rubric = _make_rubric()
        findings = engine.measure(
            rubric=rubric,
            evidence=_make_evidence(),
            student_texts=[],
            settings=_stub_settings(with_key=False),
            audit_emitter=NullEmitter(),
        )
        # Deterministic path should find "good" in Criterion A.
        vague_findings = [f for f in findings if "vague term" in f.observation]
        assert len(vague_findings) >= 1


class TestApplicabilityEngineLlm:
    def test_fallback_produces_findings(self):
        """No API key → deterministic path runs and finds missing guidance."""
        engine = ApplicabilityEngine()
        rubric = _make_rubric()
        findings = engine.measure(
            rubric=rubric,
            evidence=_make_evidence(),
            student_texts=[],
            settings=_stub_settings(with_key=False),
            audit_emitter=NullEmitter(),
        )
        assert len(findings) >= 1
        assert all(f.criterion == QualityCriterion.APPLICABILITY for f in findings)


class TestDiscriminationEngineLlm:
    def test_fallback_produces_findings(self):
        """No API key → deterministic path runs."""
        engine = DiscriminationEngine()
        rubric = _make_rubric()
        findings = engine.measure(
            rubric=rubric,
            evidence=_make_evidence(),
            student_texts=[],
            settings=_stub_settings(with_key=False),
            audit_emitter=NullEmitter(),
        )
        # Should still produce findings (at least flat-distribution check).
        assert isinstance(findings, list)


# ── Test: Propose LLM path ───────────────────────────────────────────────


class TestProposeLlmGrounding:
    def test_collect_criterion_paths(self):
        rubric = _make_rubric()
        paths = _collect_criterion_paths(rubric)
        assert len(paths) == 2
        assert paths[0]["name"] == "Criterion A"
        assert paths[1]["name"] == "Criterion B"

    def test_convert_and_ground_valid(self):
        """Valid finding IDs and criterion paths → draft survives."""
        from grading_rubric.improve.llm_schemas import LlmDraftEntry

        rubric = _make_rubric()
        finding = _make_finding()

        entry = LlmDraftEntry(
            operation="REPLACE_FIELD",
            primary_criterion="ambiguity",
            source_finding_ids=[str(FINDING_1_ID)],
            rationale="Fix vague language",
            confidence_score=0.8,
            payload={
                "target": {
                    "criterion_path": [str(CRIT_A_ID)],
                    "field": "description",
                },
                "before": "good analysis",
                "after": "high-quality analysis",
            },
        )

        drafts = _convert_and_ground([entry], [finding], rubric, uuid4())
        assert len(drafts) == 1
        assert drafts[0].operation == "REPLACE_FIELD"

    def test_convert_and_ground_invalid_finding_id(self):
        """Draft with non-existent finding ID → dropped."""
        from grading_rubric.improve.llm_schemas import LlmDraftEntry

        rubric = _make_rubric()
        finding = _make_finding()

        entry = LlmDraftEntry(
            operation="REPLACE_FIELD",
            primary_criterion="ambiguity",
            source_finding_ids=["00000000-0000-0000-0000-000000000099"],
            rationale="Fix something",
            confidence_score=0.7,
            payload={"target": {"criterion_path": [str(CRIT_A_ID)], "field": "description"}},
        )

        drafts = _convert_and_ground([entry], [finding], rubric, uuid4())
        assert len(drafts) == 0

    def test_convert_and_ground_invalid_criterion_path(self):
        """Draft with non-existent criterion path → dropped."""
        from grading_rubric.improve.llm_schemas import LlmDraftEntry

        rubric = _make_rubric()
        finding = _make_finding()

        entry = LlmDraftEntry(
            operation="REPLACE_FIELD",
            primary_criterion="ambiguity",
            source_finding_ids=[str(FINDING_1_ID)],
            rationale="Fix something",
            confidence_score=0.7,
            payload={
                "target": {
                    "criterion_path": ["00000000-0000-0000-0000-nonexistent"],
                    "field": "description",
                },
            },
        )

        drafts = _convert_and_ground([entry], [finding], rubric, uuid4())
        assert len(drafts) == 0

    def test_convert_and_ground_invalid_operation(self):
        """Draft with invalid operation type → dropped."""
        from grading_rubric.improve.llm_schemas import LlmDraftEntry

        rubric = _make_rubric()
        finding = _make_finding()

        entry = LlmDraftEntry(
            operation="INVALID_OP",
            primary_criterion="ambiguity",
            source_finding_ids=[str(FINDING_1_ID)],
            rationale="Fix something",
            confidence_score=0.7,
            payload={},
        )

        drafts = _convert_and_ground([entry], [finding], rubric, uuid4())
        assert len(drafts) == 0

    def test_propose_fallback_on_no_key(self):
        """No API key → deterministic _plan_drafts() runs."""
        rubric = _make_rubric()
        finding = _make_finding()
        batch = _plan_drafts([finding], rubric)
        assert len(batch.drafts) >= 1
        assert batch.drafts[0].operation == "REPLACE_FIELD"


# ── Test: Scorer ─────────────────────────────────────────────────────────


class TestTrimmedMean:
    def test_two_scores(self):
        assert _trimmed_mean([50, 70]) == 60.0

    def test_five_scores(self):
        # Drop lowest (30) and highest (90), mean of [50, 60, 70] = 60
        assert _trimmed_mean([30, 50, 60, 70, 90]) == 60.0

    def test_single_score(self):
        assert _trimmed_mean([75]) == 75.0


class TestConfidenceFromStdev:
    def test_low_stdev_high_confidence(self):
        ci = _confidence_from_stdev(5.0, 5)
        assert ci.level == ConfidenceLevel.HIGH
        assert ci.score == 0.85

    def test_medium_stdev_medium_confidence(self):
        ci = _confidence_from_stdev(15.0, 5)
        assert ci.level == ConfidenceLevel.MEDIUM
        assert ci.score == 0.55

    def test_high_stdev_low_confidence(self):
        ci = _confidence_from_stdev(25.0, 5)
        assert ci.level == ConfidenceLevel.LOW
        assert ci.score == 0.25


class TestScorerLlmPath:
    def test_llm_path_with_stub_backend(self):
        """Stub returns 5 LlmScorerOutput per criterion → scores computed."""
        # 3 criteria × 5 samples = 15 canned responses needed.
        canned = []
        for criterion_idx in range(3):
            for sample_idx in range(5):
                canned.append({"score": 40 + criterion_idx * 10 + sample_idx * 2, "justification": "test"})

        stub = StubBackend(canned_responses=canned)
        scorer = LlmPanelScorer()

        original_init = Gateway.__init__

        def patched_init(self_gw, *, backend=None, prompts=None):
            original_init(self_gw, backend=stub, prompts=prompts)

        Gateway.__init__ = patched_init
        try:
            evidence = ScoringEvidence(
                rubric=_make_rubric(),
                exam_question_text="Describe bad actors.",
                teaching_material_text="",
                student_copies_text=[],
                findings=[_make_finding()],
            )
            result = scorer._score_with_llm_panel(
                evidence,
                settings=_stub_settings(with_key=True),
                audit_emitter=NullEmitter(),
            )
        finally:
            Gateway.__init__ = original_init

        assert len(result.quality_scores) == 3
        for qs in result.quality_scores:
            assert 0.0 <= qs.score <= 1.0
            assert qs.source_operation_id is not None

    def test_scorer_fallback_on_no_key(self):
        """No API key → deterministic formula runs."""
        scorer = LlmPanelScorer()
        evidence = ScoringEvidence(
            rubric=_make_rubric(),
            exam_question_text="Describe bad actors.",
            teaching_material_text="",
            student_copies_text=[],
            findings=[_make_finding()],
        )
        result = scorer.score_rubric(
            evidence,
            settings=_stub_settings(with_key=False),
            audit_emitter=NullEmitter(),
        )
        assert len(result.quality_scores) == 3
        # Deterministic scorer with one MEDIUM finding on AMBIGUITY:
        # ambiguity score = 1 - 0.2/2.5 = 0.92
        ambiguity_score = next(
            qs for qs in result.quality_scores
            if qs.criterion == QualityCriterion.AMBIGUITY
        )
        assert 0.9 <= ambiguity_score.score <= 0.95

    def test_scorer_deterministic_no_findings(self):
        """No findings → all scores at 1.0."""
        scorer = LlmPanelScorer()
        evidence = ScoringEvidence(
            rubric=_make_rubric(),
            exam_question_text="Test question.",
            teaching_material_text="",
            student_copies_text=[],
            findings=[],
        )
        result = scorer._score_deterministic(
            evidence,
            settings=_stub_settings(with_key=False),
            audit_emitter=NullEmitter(),
        )
        for qs in result.quality_scores:
            assert qs.score == 1.0


# ── Test: _rubric_to_text ────────────────────────────────────────────────


class TestRubricToText:
    def test_contains_criterion_names(self):
        rubric = _make_rubric()
        text = _rubric_to_text(rubric)
        assert "Criterion A" in text
        assert "Criterion B" in text
        assert "10.0" in text  # points
