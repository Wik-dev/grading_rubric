"""Stage-local input/output and draft shapes for the `propose` (improve) stage.

Per DR-DAT-01: these live next to the stage that owns them, **not** in
`grading_rubric.models`. They are the LLM-owned draft schemas (DR-IM-03) used
internally by the planner and the generator; the system-owned fields
(`id`, `application_status`, `teacher_decision`, `source_operations`) are
assigned by the wrap step in DR-IM-07, never by the LLM.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from grading_rubric.assess.models import AssessOutputs
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    QualityCriterion,
)
from grading_rubric.models.proposed_change import ProposedChange
from grading_rubric.models.rubric import Rubric
from grading_rubric.models.types import FindingId


class PlannerDecision(StrEnum):
    CHANGES_PROPOSED = "changes_proposed"
    NO_CHANGES_NEEDED = "no_changes_needed"
    PLANNER_FAILURE = "planner_failure"


class ProposedChangeDraft(BaseModel):
    """LLM-owned draft of a single proposed change. DR-IM-03."""

    model_config = ConfigDict(strict=True)

    operation: str  # the literal of the final ProposedChange variant
    payload: dict[str, Any]
    primary_criterion: QualityCriterion
    source_findings: list[FindingId]
    rationale: str
    confidence: ConfidenceIndicator


class ProposedChangeDraftBatch(BaseModel):
    """Planner output: a batch of drafts + a closed-enum decision."""

    model_config = ConfigDict(strict=True)

    decision: PlannerDecision
    drafts: list[ProposedChangeDraft] = []
    failure_reason: str | None = None


class ProposeInputs(BaseModel):
    model_config = ConfigDict(strict=True)

    assessed: AssessOutputs


class ProposeOutputs(BaseModel):
    """Result of `propose`: starting + improved rubric + final ProposedChange records."""

    model_config = ConfigDict(strict=True)

    assessed: AssessOutputs
    starting_rubric: Rubric | None
    improved_rubric: Rubric
    proposed_changes: list[ProposedChange]
    findings: list[AssessmentFinding]
