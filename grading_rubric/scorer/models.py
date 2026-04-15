"""Stage-local input/output shapes for the `score` stage.

Per DR-DAT-01: stage-local shapes live next to the stage that owns them.
The headline `CriterionScore` lives in `grading_rubric.models.deliverable`
because it is part of the published deliverable contract (§ 4.9).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from grading_rubric.assess.simulation import SimulationEvidence
from grading_rubric.improve.models import ProposeOutputs
from grading_rubric.models.deliverable import CriterionScore


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
