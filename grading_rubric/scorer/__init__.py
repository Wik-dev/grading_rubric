"""Scorer sub-package — `score` stage (DR-SCR-01..02)."""

from grading_rubric.scorer.models import (
    ScoreInputs,
    ScoreOutputs,
)
from grading_rubric.scorer.score_stage import score_stage

__all__ = [
    "score_stage",
    "ScoreInputs",
    "ScoreOutputs",
]
