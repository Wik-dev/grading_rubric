"""Unit tests — DR-INT-04 proposal-payload mapping (L3).

`validance_integration/proposals.py` is a pure mapping module with no I/O and no SDK
calls. Forward direction: L1 ProposedChange → JSON-safe payload. Inverse
direction: approval resolution → TeacherDecision patching.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from grading_rubric.models.findings import (
    ConfidenceIndicator,
    ConfidenceLevel,
    QualityCriterion,
)
from grading_rubric.models.proposed_change import (
    ApplicationStatus,
    ReplaceFieldChange,
    TeacherDecision,
    UpdatePointsChange,
)
from grading_rubric.models.rubric import RubricFieldName, RubricTarget

from tests.conftest import CHANGE_1_ID, CHANGE_2_ID, CRIT_A_ID, FINDING_1_ID

# Import L3 mapping module — the only place validance vocabulary appears.
from validance_integration.proposals import (
    apply_approval_resolution,
    proposed_change_to_payload,
    proposed_changes_to_payload,
)


def _make_change(change_id, criterion=QualityCriterion.AMBIGUITY):
    return ReplaceFieldChange(
        id=change_id,
        primary_criterion=criterion,
        source_findings=[FINDING_1_ID],
        rationale="Test rationale",
        confidence=ConfidenceIndicator(
            score=0.6, level=ConfidenceLevel.MEDIUM, rationale="r"
        ),
        application_status=ApplicationStatus.APPLIED,
        target=RubricTarget(
            criterion_path=[CRIT_A_ID], field=RubricFieldName.DESCRIPTION
        ),
        before="old",
        after="new",
    )


class TestForwardMapping:
    """DR-INT-04 forward: ProposedChange → proposal payload."""

    def test_single_change(self) -> None:
        change = _make_change(CHANGE_1_ID)
        payload = proposed_change_to_payload(change)
        assert payload["id"] == str(CHANGE_1_ID)
        assert payload["operation"] == "REPLACE_FIELD"
        assert payload["primary_criterion"] == "ambiguity"
        assert payload["rationale"] == "Test rationale"
        assert "confidence" in payload
        assert payload["before"] == "old"
        assert payload["after"] == "new"

    def test_batch_envelope(self) -> None:
        changes = [_make_change(CHANGE_1_ID), _make_change(CHANGE_2_ID)]
        envelope = proposed_changes_to_payload(changes)
        assert envelope["kind"] == "grading_rubric.proposed_changes"
        assert envelope["version"] == "1"
        assert envelope["count"] == 2
        assert len(envelope["changes"]) == 2

    def test_update_points_variant(self) -> None:
        change = UpdatePointsChange(
            id=CHANGE_1_ID,
            primary_criterion=QualityCriterion.APPLICABILITY,
            source_findings=[],
            rationale="Rebalance",
            confidence=ConfidenceIndicator.from_score(0.8, rationale="r"),
            application_status=ApplicationStatus.APPLIED,
            target=RubricTarget(
                criterion_path=[CRIT_A_ID], field=RubricFieldName.POINTS
            ),
            before=10.0,
            after=15.0,
        )
        payload = proposed_change_to_payload(change)
        assert payload["operation"] == "UPDATE_POINTS"
        assert payload["before"] == 10.0
        assert payload["after"] == 15.0

    def test_source_findings_serialized_as_strings(self) -> None:
        change = _make_change(CHANGE_1_ID)
        payload = proposed_change_to_payload(change)
        assert all(isinstance(fid, str) for fid in payload["source_findings"])


class TestInverseMapping:
    """DR-INT-04 inverse: approval resolution → patched ProposedChange."""

    def test_list_shape_accepted(self) -> None:
        changes = [_make_change(CHANGE_1_ID)]
        resolution = {
            "decisions": [{"id": str(CHANGE_1_ID), "decision": "accepted"}]
        }
        patched = apply_approval_resolution(changes, resolution)
        assert len(patched) == 1
        assert patched[0].teacher_decision == TeacherDecision.ACCEPTED

    def test_dict_shape_accepted(self) -> None:
        changes = [_make_change(CHANGE_1_ID)]
        resolution = {str(CHANGE_1_ID): "accepted"}
        patched = apply_approval_resolution(changes, resolution)
        assert patched[0].teacher_decision == TeacherDecision.ACCEPTED

    def test_rejected(self) -> None:
        changes = [_make_change(CHANGE_1_ID)]
        resolution = {
            "decisions": [{"id": str(CHANGE_1_ID), "decision": "rejected"}]
        }
        patched = apply_approval_resolution(changes, resolution)
        assert patched[0].teacher_decision == TeacherDecision.REJECTED

    def test_synonym_forms(self) -> None:
        """Multiple synonyms map to the same TeacherDecision."""
        changes = [_make_change(CHANGE_1_ID), _make_change(CHANGE_2_ID)]
        resolution = {
            "decisions": [
                {"id": str(CHANGE_1_ID), "decision": "approved"},
                {"id": str(CHANGE_2_ID), "decision": "denied"},
            ]
        }
        patched = apply_approval_resolution(changes, resolution)
        assert patched[0].teacher_decision == TeacherDecision.ACCEPTED
        assert patched[1].teacher_decision == TeacherDecision.REJECTED

    def test_unmatched_change_left_unpatched(self) -> None:
        """Changes whose ID is not in the resolution keep teacher_decision=None."""
        changes = [_make_change(CHANGE_1_ID)]
        resolution = {"decisions": []}  # No decisions
        patched = apply_approval_resolution(changes, resolution)
        assert patched[0].teacher_decision is None

    def test_original_not_mutated(self) -> None:
        """apply_approval_resolution returns new list; originals are untouched."""
        changes = [_make_change(CHANGE_1_ID)]
        resolution = {
            "decisions": [{"id": str(CHANGE_1_ID), "decision": "accepted"}]
        }
        patched = apply_approval_resolution(changes, resolution)
        assert changes[0].teacher_decision is None  # unchanged
        assert patched[0].teacher_decision == TeacherDecision.ACCEPTED
