"""Stage-local input/output and helper shapes for the `score` stage.

Per DR-DAT-01: stage-local shapes live next to the stage that owns them.
The headline `CriterionScore` lives in `grading_rubric.models.deliverable`
because it is part of the published deliverable contract (§ 4.9).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from grading_rubric.assess.simulation import SimulationEvidence
from grading_rubric.improve.models import ProposeOutputs
from grading_rubric.models.deliverable import CriterionScore
from grading_rubric.models.findings import AssessmentFinding
from grading_rubric.models.rubric import Rubric


class ScoringEvidence(BaseModel):
    """The evidence a `Scorer` consumes (DR-SCR-01).

    Mirrors the `parse_inputs` outputs the rest of the pipeline carries plus
    the assessment findings produced by the `assess` stage. Kept stage-local
    because no other code outside `scorer` constructs or reads it.
    """

    model_config = ConfigDict(strict=True)

    rubric: Rubric
    exam_question_text: str
    teaching_material_text: str
    student_copies_text: list[str]
    findings: list[AssessmentFinding]


class ScoringResult(BaseModel):
    """The output of one `Scorer.score_rubric(...)` call (DR-SCR-01)."""

    model_config = ConfigDict(strict=True)

    quality_scores: list[CriterionScore]
    scorer_id: str
    scorer_version: str


class ScoreInputs(BaseModel):
    model_config = ConfigDict(strict=True)

    proposed: ProposeOutputs


class ScoreOutputs(BaseModel):
    """Result of `score`: improved rubric + headline scores + carry-through."""

    model_config = ConfigDict(strict=True)

    proposed: ProposeOutputs
    quality_scores: list[CriterionScore]
    previous_quality_scores: list[CriterionScore] | None = None
    scorer_id: str
    scorer_version: str
    simulation_evidence: SimulationEvidence | None = None


# ── Train-button stub shapes (DR-SCR-05) ─────────────────────────────────


class GroundTruthGrade(BaseModel):
    model_config = ConfigDict(strict=True)

    student_copy_index: int
    grade: float


class TrainingEvidence(BaseModel):
    model_config = ConfigDict(strict=True)

    rubric: Rubric
    exam_question_text: str
    teaching_material_text: str
    student_copies_text: list[str]
    findings: list[AssessmentFinding]
    ground_truth_grades: list[GroundTruthGrade] = Field(default_factory=list)


class TrainedScorerArtefact(BaseModel):
    model_config = ConfigDict(strict=True)

    artefact_path: Path
    training_run_id: str
    scorer_id: str
    metrics: dict[str, float] = Field(default_factory=dict)


class ScorerArtefactMissingError(RuntimeError):
    """Raised by `TrainedModelScorer` when no artefact is on disk (DR-SCR-03)."""
