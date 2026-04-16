from __future__ import annotations

from uuid import uuid4

from grading_rubric.assess.simulation import _rubric_to_text
from grading_rubric.improve.llm_schemas import LlmDraftEntry
from grading_rubric.improve.stage import _collect_criterion_paths, _convert_and_ground
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    Measurement,
    QualityCriterion,
    QualityMethod,
    Severity,
)
from grading_rubric.models.rubric import RubricFieldName, RubricTarget
from tests.conftest import CRIT_A_ID, FINDING_1_ID, RUBRIC_ID


def _finding() -> AssessmentFinding:
    return AssessmentFinding(
        id=FINDING_1_ID,
        criterion=QualityCriterion.AMBIGUITY,
        severity=Severity.MEDIUM,
        target=RubricTarget(criterion_path=[CRIT_A_ID], field=RubricFieldName.DESCRIPTION),
        observation="graders disagreed",
        evidence="simulation trace",
        measurement=Measurement(
            method=QualityMethod.LLM_PANEL_AGREEMENT,
            samples=4,
            agreement=0.4,
        ),
        confidence=ConfidenceIndicator.from_score(0.6, "test"),
        measured_against_rubric_id=RUBRIC_ID,
    )


def test_rubric_to_text_contains_criterion_names(minimal_rubric) -> None:
    text = _rubric_to_text(minimal_rubric)
    assert "Criterion A" in text
    assert "criterion_id:" in text


def test_collect_criterion_paths(minimal_rubric) -> None:
    paths = _collect_criterion_paths(minimal_rubric)
    assert any(str(CRIT_A_ID) in p["criterion_path"] for p in paths)


def test_convert_and_ground_valid_draft(minimal_rubric) -> None:
    entry = LlmDraftEntry(
        operation="REPLACE_FIELD",
        primary_criterion="ambiguity",
        source_finding_ids=[str(FINDING_1_ID)],
        rationale="clarify",
        confidence_score=0.8,
        payload={
            "target": {
                "criterion_path": [str(CRIT_A_ID)],
                "field": "description",
            },
            "before": "old",
            "after": "new",
        },
    )
    drafts = _convert_and_ground([entry], [_finding()], minimal_rubric, uuid4())
    assert len(drafts) == 1
    assert drafts[0].operation == "REPLACE_FIELD"


def test_convert_and_ground_drops_unknown_finding(minimal_rubric) -> None:
    entry = LlmDraftEntry(
        operation="REPLACE_FIELD",
        primary_criterion="ambiguity",
        source_finding_ids=[str(uuid4())],
        rationale="clarify",
        confidence_score=0.8,
        payload={
            "target": {
                "criterion_path": [str(CRIT_A_ID)],
                "field": "description",
            }
        },
    )
    drafts = _convert_and_ground([entry], [_finding()], minimal_rubric, uuid4())
    assert drafts == []
