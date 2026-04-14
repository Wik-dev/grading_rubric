"""Scorer compatibility surfaces.

The main score stage now derives quality scores from shared grader simulation
statistics. This module keeps the historical protocol/factory names available
for imports and the trained-scorer placeholder.
"""

from __future__ import annotations

from typing import Protocol

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.scorer.models import (
    ScorerArtefactMissingError,
    ScoringEvidence,
    ScoringResult,
)


class Scorer(Protocol):
    scorer_id: str
    scorer_version: str

    def score_rubric(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult: ...


class LlmPanelScorer:
    """Deprecated compatibility shell.

    Direct LLM rubric-quality scoring was removed from the main path. Use
    `score_stage`, which runs grader simulation and computes statistics.
    """

    scorer_id = "llm_panel.deprecated"
    scorer_version = "0.0.0"

    def score_rubric(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult:
        raise RuntimeError(
            "LlmPanelScorer is deprecated; score_stage now derives quality "
            "scores from grader simulation traces."
        )


class TrainedModelScorer:
    """Declared but not shipped trained scorer: DR-SCR-03."""

    scorer_id = "trained_model.v0"
    scorer_version = "0.0.0"

    def __init__(self, artefact_path: str | None) -> None:
        raise ScorerArtefactMissingError(
            f"no trained scorer artefact present at "
            f"{artefact_path or '<unset>'} - run "
            f"`grading-rubric-cli train-scorer` to produce one"
        )

    def score_rubric(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult:  # pragma: no cover
        raise NotImplementedError(
            "TrainedModelScorer is declared but no model is shipped in v1"
        )


def make_scorer(settings: Settings) -> Scorer:
    """Compatibility factory. The simulation score stage no longer calls this."""

    if settings.scorer_backend == "trained_model":
        return TrainedModelScorer(settings.trained_scorer_artefact_path)
    return LlmPanelScorer()
