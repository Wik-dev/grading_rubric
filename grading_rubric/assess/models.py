"""Stage-local input/output shapes for `assess`. Per DR-DAT-01."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from grading_rubric.assess.simulation import SimulationEvidence
from grading_rubric.models.deliverable import CriterionScore
from grading_rubric.models.findings import AssessmentFinding
from grading_rubric.models.rubric import EvidenceProfile, Rubric
from grading_rubric.parsers.models import ParsedInputs


class AssessInputs(BaseModel):
    model_config = ConfigDict(strict=True)

    parsed: ParsedInputs


class AssessOutputs(BaseModel):
    """`assess` produces only findings + a refined evidence_profile (DR-AS-01).

    The headline `CriterionScore` records are produced downstream by `score`.
    """

    model_config = ConfigDict(strict=True)

    parsed: ParsedInputs
    rubric_under_assessment: Rubric  # the snapshot the engines measured
    findings: list[AssessmentFinding]
    evidence_profile: EvidenceProfile  # refined (synthetic_responses_used set)
    quality_scores: list[CriterionScore] = Field(default_factory=list)
    simulation_summary: str = ""
    simulation_evidence: SimulationEvidence | None = None
