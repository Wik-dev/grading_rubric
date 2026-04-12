"""Unit tests — L1 data models (§ 4, DR-DAT-01 / DR-DAT-02).

Each test traces to a specific DR or model invariant. Tests run without
any network access, LLM, or Validance instance.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grading_rubric.models.deliverable import CriterionScore, ExplainedRubricFile
from grading_rubric.models.explanation import CriterionSection, Explanation
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
    AddNodeChange,
    ApplicationStatus,
    NodeKind,
    RemoveNodeChange,
    ReplaceFieldChange,
    ReorderNodesChange,
    TeacherDecision,
    UpdatePointsChange,
)
from grading_rubric.models.rubric import (
    EvidenceProfile,
    Rubric,
    RubricCriterion,
    RubricFieldName,
    RubricLevel,
    RubricTarget,
)

from tests.conftest import (
    CHANGE_1_ID,
    CRIT_A_ID,
    CRIT_B_ID,
    FINDING_1_ID,
    LEVEL_A1_ID,
    LEVEL_A2_ID,
    RUBRIC_ID,
)


# ── § 4.5 ConfidenceIndicator thresholds ─────────────────────────────────


class TestConfidenceIndicator:
    """DR-AS-05 / DR-DAT-02: confidence thresholds are locked at § 4.5."""

    def test_low_threshold(self) -> None:
        ci = ConfidenceIndicator(score=0.20, level=ConfidenceLevel.LOW, rationale="r")
        assert ci.level == ConfidenceLevel.LOW

    def test_medium_threshold_boundary(self) -> None:
        ci = ConfidenceIndicator(
            score=0.40, level=ConfidenceLevel.MEDIUM, rationale="r"
        )
        assert ci.level == ConfidenceLevel.MEDIUM

    def test_high_threshold_boundary(self) -> None:
        ci = ConfidenceIndicator(
            score=0.75, level=ConfidenceLevel.HIGH, rationale="r"
        )
        assert ci.level == ConfidenceLevel.HIGH

    def test_inconsistent_level_rejected(self) -> None:
        with pytest.raises(ValidationError, match="inconsistent"):
            ConfidenceIndicator(score=0.20, level=ConfidenceLevel.HIGH, rationale="r")

    def test_score_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not in \\[0, 1\\]"):
            ConfidenceIndicator(score=1.5, level=ConfidenceLevel.HIGH, rationale="r")

    def test_from_score_factory(self) -> None:
        ci = ConfidenceIndicator.from_score(0.55, rationale="medium evidence")
        assert ci.level == ConfidenceLevel.MEDIUM
        assert ci.score == 0.55

    def test_rationale_is_required(self) -> None:
        with pytest.raises(ValidationError, match="rationale"):
            ConfidenceIndicator(score=0.5, level=ConfidenceLevel.MEDIUM)  # type: ignore[call-arg]


# ── § 4.3 RubricTarget validation ────────────────────────────────────────


class TestRubricTarget:
    """DR-DAT-02: RubricTarget validates criterion_path + level_id rules."""

    def test_level_field_requires_level_id(self) -> None:
        with pytest.raises(ValidationError, match="requires level_id"):
            RubricTarget(
                criterion_path=[CRIT_A_ID],
                field=RubricFieldName.LEVEL_LABEL,
            )

    def test_non_level_field_rejects_level_id(self) -> None:
        with pytest.raises(ValidationError, match="only valid for level"):
            RubricTarget(
                criterion_path=[CRIT_A_ID],
                level_id=LEVEL_A1_ID,
                field=RubricFieldName.NAME,
            )

    def test_empty_criterion_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            RubricTarget(
                criterion_path=[],
                field=RubricFieldName.NAME,
            )

    def test_valid_criterion_field_target(self) -> None:
        target = RubricTarget(
            criterion_path=[CRIT_A_ID],
            field=RubricFieldName.DESCRIPTION,
        )
        assert target.level_id is None

    def test_valid_level_field_target(self) -> None:
        target = RubricTarget(
            criterion_path=[CRIT_A_ID],
            level_id=LEVEL_A1_ID,
            field=RubricFieldName.LEVEL_DESCRIPTOR,
        )
        assert target.level_id == LEVEL_A1_ID


# ── § 4.2 Rubric tree invariants ─────────────────────────────────────────


class TestRubricInvariants:
    """DR-DAT-02: Rubric validates additive sums and unique IDs."""

    def test_valid_rubric(self, minimal_rubric: Rubric) -> None:
        assert minimal_rubric.total_points == 20.0
        assert len(minimal_rubric.criteria) == 2

    def test_total_points_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="total_points"):
            Rubric(
                id=RUBRIC_ID,
                schema_version="1.0.0",
                title="Bad",
                total_points=999.0,
                criteria=[
                    RubricCriterion(
                        id=CRIT_A_ID,
                        name="A",
                        description="d",
                        points=10.0,
                        levels=[],
                    )
                ],
            )

    def test_duplicate_criterion_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            Rubric(
                id=RUBRIC_ID,
                schema_version="1.0.0",
                title="Dup",
                total_points=20.0,
                criteria=[
                    RubricCriterion(
                        id=CRIT_A_ID, name="A", description="d", points=10.0
                    ),
                    RubricCriterion(
                        id=CRIT_A_ID, name="B", description="d", points=10.0
                    ),
                ],
            )

    def test_level_points_exceed_criterion_points_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not in"):
            Rubric(
                id=RUBRIC_ID,
                schema_version="1.0.0",
                title="Overshoot",
                total_points=10.0,
                criteria=[
                    RubricCriterion(
                        id=CRIT_A_ID,
                        name="A",
                        description="d",
                        points=10.0,
                        levels=[
                            RubricLevel(
                                id=LEVEL_A1_ID,
                                label="L",
                                descriptor="d",
                                points=15.0,  # > 10
                            ),
                        ],
                    ),
                ],
            )


# ── § 4.2 Rubric JSON round-trip ─────────────────────────────────────────


class TestRubricRoundTrip:
    """DR-DAT-02: Rubric survives JSON serialization round-trip."""

    def test_round_trip(self, minimal_rubric: Rubric) -> None:
        json_str = minimal_rubric.model_dump_json()
        restored = Rubric.model_validate_json(json_str)
        assert restored == minimal_rubric

    def test_recursive_round_trip(self) -> None:
        """Rubric with nested sub-criteria round-trips correctly."""
        child_id = uuid4()
        rubric = Rubric(
            id=RUBRIC_ID,
            schema_version="1.0.0",
            title="Nested",
            total_points=10.0,
            criteria=[
                RubricCriterion(
                    id=CRIT_A_ID,
                    name="Parent",
                    description="d",
                    points=10.0,
                    additive=True,
                    sub_criteria=[
                        RubricCriterion(
                            id=child_id,
                            name="Child",
                            description="d",
                            points=10.0,
                        )
                    ],
                )
            ],
        )
        json_str = rubric.model_dump_json()
        restored = Rubric.model_validate_json(json_str)
        assert restored.criteria[0].sub_criteria[0].id == child_id


# ── § 4.6 ProposedChange discriminated union ──────────────────────────────


class TestProposedChangeUnion:
    """DR-DAT-02 / DR-IM-01: discriminated union dispatches correctly."""

    def test_replace_field(self, sample_replace_change: ReplaceFieldChange) -> None:
        assert sample_replace_change.operation == "REPLACE_FIELD"

    def test_update_points(self) -> None:
        change = UpdatePointsChange(
            id=CHANGE_1_ID,
            primary_criterion=QualityCriterion.APPLICABILITY,
            source_findings=[FINDING_1_ID],
            rationale="Rebalance points",
            confidence=ConfidenceIndicator.from_score(0.8, rationale="r"),
            application_status=ApplicationStatus.APPLIED,
            target=RubricTarget(
                criterion_path=[CRIT_A_ID], field=RubricFieldName.POINTS
            ),
            before=10.0,
            after=15.0,
        )
        assert change.operation == "UPDATE_POINTS"

    def test_add_node(self) -> None:
        change = AddNodeChange(
            id=CHANGE_1_ID,
            primary_criterion=QualityCriterion.APPLICABILITY,
            source_findings=[],
            rationale="Add missing level",
            confidence=ConfidenceIndicator.from_score(0.5, rationale="r"),
            application_status=ApplicationStatus.APPLIED,
            parent_path=[CRIT_A_ID],
            insert_index=2,
            node_kind=NodeKind.LEVEL,
            node=RubricLevel(
                id=uuid4(), label="Good", descriptor="Above average", points=7.5
            ),
        )
        assert change.operation == "ADD_NODE"

    def test_remove_node(self) -> None:
        change = RemoveNodeChange(
            id=CHANGE_1_ID,
            primary_criterion=QualityCriterion.DISCRIMINATION_POWER,
            source_findings=[],
            rationale="Remove redundant criterion",
            confidence=ConfidenceIndicator.from_score(0.85, rationale="r"),
            application_status=ApplicationStatus.APPLIED,
            criterion_path=[CRIT_B_ID],
            node_kind=NodeKind.CRITERION,
            removed_snapshot=RubricCriterion(
                id=CRIT_B_ID, name="B", description="d", points=10.0
            ),
        )
        assert change.operation == "REMOVE_NODE"

    def test_reorder_nodes(self) -> None:
        change = ReorderNodesChange(
            id=CHANGE_1_ID,
            primary_criterion=QualityCriterion.APPLICABILITY,
            source_findings=[],
            rationale="Reorder for clarity",
            confidence=ConfidenceIndicator.from_score(0.6, rationale="r"),
            application_status=ApplicationStatus.NOT_APPLIED,
            parent_path=[CRIT_A_ID],
            node_kind=NodeKind.LEVEL,
            before_order=[LEVEL_A1_ID, LEVEL_A2_ID],
            after_order=[LEVEL_A2_ID, LEVEL_A1_ID],
        )
        assert change.operation == "REORDER_NODES"


# ── § 4.4 EvidenceProfile ────────────────────────────────────────────────


class TestEvidenceProfile:
    """DR-DAT-02: EvidenceProfile captures input provenance."""

    def test_minimal_valid(self, empty_evidence_profile: EvidenceProfile) -> None:
        assert empty_evidence_profile.synthetic_responses_used is True
        assert empty_evidence_profile.student_copies_present is False

    def test_with_student_copies(self) -> None:
        ep = EvidenceProfile(
            starting_rubric_present=True,
            exam_question_present=True,
            teaching_material_present=False,
            student_copies_present=True,
            student_copies_count=3,
        )
        assert ep.synthetic_responses_used is False
        assert ep.student_copies_count == 3


# ── § 4.7 Explanation invariant ───────────────────────────────────────────


class TestExplanation:
    """DR-DAT-02: Explanation requires one section per QualityCriterion."""

    def test_valid_explanation(self) -> None:
        explanation = Explanation(
            summary="All three criteria were assessed.",
            by_criterion={
                QualityCriterion.AMBIGUITY: CriterionSection(
                    criterion=QualityCriterion.AMBIGUITY, narrative="OK"
                ),
                QualityCriterion.APPLICABILITY: CriterionSection(
                    criterion=QualityCriterion.APPLICABILITY, narrative="OK"
                ),
                QualityCriterion.DISCRIMINATION_POWER: CriterionSection(
                    criterion=QualityCriterion.DISCRIMINATION_POWER, narrative="OK"
                ),
            },
        )
        assert len(explanation.by_criterion) == 3

    def test_missing_criterion_rejected(self) -> None:
        with pytest.raises(ValidationError, match="missing"):
            Explanation(
                summary="Missing one",
                by_criterion={
                    QualityCriterion.AMBIGUITY: CriterionSection(
                        criterion=QualityCriterion.AMBIGUITY, narrative="OK"
                    ),
                    QualityCriterion.APPLICABILITY: CriterionSection(
                        criterion=QualityCriterion.APPLICABILITY, narrative="OK"
                    ),
                    # DISCRIMINATION_POWER intentionally missing
                },
            )
