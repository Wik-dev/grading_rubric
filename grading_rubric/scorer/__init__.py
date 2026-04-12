"""Scorer sub-package — DR-SCR-01..07 (`score` stage + train-button)."""

from grading_rubric.scorer.models import (
    GroundTruthGrade,
    ScoreInputs,
    ScoreOutputs,
    ScorerArtefactMissingError,
    ScoringEvidence,
    ScoringResult,
    TrainedScorerArtefact,
    TrainingEvidence,
)
from grading_rubric.scorer.score_stage import score_stage
from grading_rubric.scorer.scorer import (
    LlmPanelScorer,
    Scorer,
    TrainedModelScorer,
    make_scorer,
)
from grading_rubric.scorer.train_scorer import train_scorer

__all__ = [
    "score_stage",
    "train_scorer",
    "Scorer",
    "LlmPanelScorer",
    "TrainedModelScorer",
    "make_scorer",
    "ScoringEvidence",
    "ScoringResult",
    "ScoreInputs",
    "ScoreOutputs",
    "TrainingEvidence",
    "TrainedScorerArtefact",
    "GroundTruthGrade",
    "ScorerArtefactMissingError",
]
