"""Shared fixtures for the Grading Rubric Studio test suite.

Convention: every fixture documents the DR / SR it supports so the
reviewer can follow the V-shape traceability chain.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from grading_rubric.config.settings import Settings
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    ConfidenceLevel,
    Measurement,
    QualityCriterion,
    QualityMethod,
    Severity,
)
from grading_rubric.models.proposed_change import (
    ApplicationStatus,
    ReplaceFieldChange,
)
from grading_rubric.models.rubric import (
    EvidenceProfile,
    Rubric,
    RubricCriterion,
    RubricFieldName,
    RubricLevel,
    RubricTarget,
)

# ── Deterministic UUIDs for test stability ────────────────────────────────

RUBRIC_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
CRIT_A_ID = UUID("cccccccc-0000-0000-0000-000000000001")
CRIT_B_ID = UUID("cccccccc-0000-0000-0000-000000000002")
LEVEL_A1_ID = UUID("11111111-0000-0000-0000-000000000001")
LEVEL_A2_ID = UUID("11111111-0000-0000-0000-000000000002")
LEVEL_B1_ID = UUID("11111111-0000-0000-0000-000000000003")
LEVEL_B2_ID = UUID("11111111-0000-0000-0000-000000000004")
FINDING_1_ID = UUID("ffffffff-0000-0000-0000-000000000001")
FINDING_2_ID = UUID("ffffffff-0000-0000-0000-000000000002")
CHANGE_1_ID = UUID("dddddddd-0000-0000-0000-000000000001")
CHANGE_2_ID = UUID("dddddddd-0000-0000-0000-000000000002")
CHANGE_3_ID = UUID("dddddddd-0000-0000-0000-000000000003")


@pytest.fixture()
def stub_settings() -> Settings:
    """DR-ARC-09 — minimal valid Settings for tests (no real API keys)."""
    return Settings(
        ocr_backend="stub",
        ocr_model="stub-test-model",
    )


@pytest.fixture()
def minimal_rubric() -> Rubric:
    """DR-DAT-02 — a minimal two-criterion rubric for model tests."""
    return Rubric(
        id=RUBRIC_ID,
        schema_version="1.0.0",
        title="Test Rubric",
        total_points=20.0,
        criteria=[
            RubricCriterion(
                id=CRIT_A_ID,
                name="Criterion A",
                description="First criterion",
                points=10.0,
                levels=[
                    RubricLevel(
                        id=LEVEL_A1_ID,
                        label="Excellent",
                        descriptor="Top marks",
                        points=10.0,
                    ),
                    RubricLevel(
                        id=LEVEL_A2_ID,
                        label="Poor",
                        descriptor="Bottom marks",
                        points=0.0,
                    ),
                ],
            ),
            RubricCriterion(
                id=CRIT_B_ID,
                name="Criterion B",
                description="Second criterion",
                points=10.0,
                levels=[
                    RubricLevel(
                        id=LEVEL_B1_ID,
                        label="Excellent",
                        descriptor="Top marks",
                        points=10.0,
                    ),
                    RubricLevel(
                        id=LEVEL_B2_ID,
                        label="Poor",
                        descriptor="Bottom marks",
                        points=0.0,
                    ),
                ],
            ),
        ],
    )


@pytest.fixture()
def sample_finding() -> AssessmentFinding:
    """DR-AS-01 — a minimal assessment finding."""
    return AssessmentFinding(
        id=FINDING_1_ID,
        criterion=QualityCriterion.AMBIGUITY,
        severity=Severity.MEDIUM,
        target=RubricTarget(
            criterion_path=[CRIT_A_ID],
            field=RubricFieldName.DESCRIPTION,
        ),
        observation="Criterion A description is ambiguous",
        evidence="Graders disagreed on interpretation in 3 of 4 samples",
        measurement=Measurement(
            method=QualityMethod.LLM_PANEL_AGREEMENT,
            samples=4,
            agreement=0.45,
        ),
        confidence=ConfidenceIndicator(
            score=0.6,
            level=ConfidenceLevel.MEDIUM,
            rationale="Panel agreement below threshold",
        ),
        measured_against_rubric_id=RUBRIC_ID,
    )


@pytest.fixture()
def sample_replace_change() -> ReplaceFieldChange:
    """DR-IM-01 — a REPLACE_FIELD proposed change."""
    return ReplaceFieldChange(
        id=CHANGE_1_ID,
        primary_criterion=QualityCriterion.AMBIGUITY,
        source_findings=[FINDING_1_ID],
        rationale="Clarify criterion A description to reduce ambiguity",
        confidence=ConfidenceIndicator(
            score=0.7,
            level=ConfidenceLevel.MEDIUM,
            rationale="Moderate confidence based on panel evidence",
        ),
        application_status=ApplicationStatus.APPLIED,
        teacher_decision=None,
        target=RubricTarget(
            criterion_path=[CRIT_A_ID],
            field=RubricFieldName.DESCRIPTION,
        ),
        before="First criterion",
        after="Evaluates the student's ability to identify stakeholders",
    )


@pytest.fixture()
def empty_evidence_profile() -> EvidenceProfile:
    """DR-AS-01 — minimal evidence profile (no evidence provided)."""
    return EvidenceProfile(
        starting_rubric_present=False,
        exam_question_present=True,
        teaching_material_present=False,
        student_copies_present=False,
        synthetic_responses_used=True,
    )
