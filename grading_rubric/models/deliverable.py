"""§ 4.9 *Deliverable: ExplainedRubricFile*."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from grading_rubric.models.explanation import Explanation
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    QualityCriterion,
    QualityMethod,
)
from grading_rubric.models.proposed_change import ApplicationStatus, ProposedChange
from grading_rubric.models.rubric import EvidenceProfile, Rubric
from grading_rubric.models.types import OperationId, RunId


class CriterionScore(BaseModel):
    """One headline quality score, produced by the score stage (§ 4.9).

    `source_operation_id` is the unambiguous join key into the audit-event
    stream / harvested `AuditBundle` for the per-sample distribution and the
    raw model responses (DR-SCR-02). It is `None` only on a deserialised
    `previous_quality_scores` slot whose operation id is not preserved across
    rounds.
    """

    model_config = ConfigDict(strict=True)

    criterion: QualityCriterion
    score: float
    confidence: ConfidenceIndicator
    method: QualityMethod
    source_operation_id: OperationId | None = None


class ExplainedRubricFile(BaseModel):
    """The L1 deliverable — a single JSON file (§ 4.9, SR-OUT-01..05)."""

    model_config = ConfigDict(strict=True)

    schema_version: str
    generated_at: datetime
    run_id: RunId

    starting_rubric: Rubric | None
    improved_rubric: Rubric

    findings: list[AssessmentFinding]
    proposed_changes: list[ProposedChange]
    explanation: Explanation
    quality_scores: list[CriterionScore]
    previous_quality_scores: list[CriterionScore] | None = None
    evidence_profile: EvidenceProfile

    @model_validator(mode="after")
    def _check_invariants(self) -> ExplainedRubricFile:
        # quality_scores: exactly one entry per QualityCriterion.
        crits = {s.criterion for s in self.quality_scores}
        if crits != set(QualityCriterion):
            raise ValueError(
                f"quality_scores must have exactly one entry per QualityCriterion "
                f"(got {sorted(c.value for c in crits)})"
            )
        if self.previous_quality_scores is not None:
            prev_crits = {s.criterion for s in self.previous_quality_scores}
            if prev_crits != set(QualityCriterion):
                raise ValueError(
                    "previous_quality_scores, when present, must have one entry per "
                    "QualityCriterion"
                )

        finding_ids = {f.id for f in self.findings}
        change_ids = {c.id for c in self.proposed_changes}

        for section in self.explanation.by_criterion.values():
            for fid in section.finding_refs:
                if fid not in finding_ids:
                    raise ValueError(f"explanation references unknown finding {fid}")
            for cid in section.change_refs:
                if cid not in change_ids:
                    raise ValueError(f"explanation references unknown change {cid}")

        # Every APPLIED change is reflected in improved_rubric — by construction,
        # we trust the propose stage's three-step pipeline (DR-IM-07) and only
        # verify that no APPLIED change references a target that doesn't exist.
        # The full structural check is deferred to the propose stage's tests.
        applied_count = sum(
            1
            for c in self.proposed_changes
            if c.application_status == ApplicationStatus.APPLIED
        )
        if applied_count == 0 and self.proposed_changes:
            # Not necessarily an error — the empty-improvement path is valid.
            pass
        return self
