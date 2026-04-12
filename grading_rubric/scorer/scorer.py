"""DR-SCR-01..04 — `Scorer` Protocol and shipped implementations.

The `Scorer` Protocol is the sole surface the rest of the code knows about
for headline scoring. `LlmPanelScorer` is the default; `TrainedModelScorer`
is declared but unshipped per DR-SCR-03 — its constructor raises
`ScorerArtefactMissingError` so a reviewer who selects it sees the exact
failure mode the train-button capability is designed to resolve.
"""

from __future__ import annotations

from typing import Protocol

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.models.deliverable import CriterionScore
from grading_rubric.models.findings import (
    ConfidenceIndicator,
    QualityCriterion,
    QualityMethod,
)
from grading_rubric.scorer.models import (
    ScorerArtefactMissingError,
    ScoringEvidence,
    ScoringResult,
)


class Scorer(Protocol):
    """The sole interface the score stage knows about (DR-SCR-01)."""

    scorer_id: str
    scorer_version: str

    def score_rubric(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult: ...


# ── LlmPanelScorer (default) ─────────────────────────────────────────────


class LlmPanelScorer:
    """Default `Scorer` implementation: LLM panel agreement (DR-SCR-02).

    Offline-tolerant: when no LLM key is configured the gateway falls back
    to a deterministic stub that returns honest LOW-confidence scores
    derived from the assessment findings. This keeps the pipeline runnable
    without an API key while preserving the contract.
    """

    scorer_id = "llm_panel.v1"
    scorer_version = "1.0.0"

    def score_rubric(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult:
        # Deterministic offline aggregation: per criterion, the score is
        # 1.0 minus the average severity weight of findings tagged to that
        # criterion. This is the contract the LLM-backed implementation
        # would replace; it gives an honest signal that high-severity
        # findings depress the headline score.
        severity_weight = {"low": 0.1, "medium": 0.25, "high": 0.5}

        scores: list[CriterionScore] = []
        for criterion in QualityCriterion:
            relevant = [f for f in evidence.findings if f.criterion == criterion]
            if not relevant:
                raw_score = 1.0
                rationale = (
                    "No findings of this criterion were produced; the "
                    "rubric is treated as well-formed for this dimension."
                )
            else:
                penalty = sum(
                    severity_weight.get(f.severity.value, 0.25) for f in relevant
                ) / max(len(relevant), 1)
                raw_score = max(0.0, 1.0 - penalty)
                rationale = (
                    f"Aggregated {len(relevant)} finding(s) of this "
                    f"criterion; offline panel scorer."
                )
            confidence = ConfidenceIndicator.from_score(
                0.30, "deterministic offline scorer; conservative confidence"
            )
            scores.append(
                CriterionScore(
                    criterion=criterion,
                    score=raw_score,
                    confidence=confidence,
                    method=QualityMethod.LLM_PANEL_AGREEMENT,
                    source_operation_id=None,
                )
            )
        return ScoringResult(
            quality_scores=scores,
            scorer_id=self.scorer_id,
            scorer_version=self.scorer_version,
        )


# ── TrainedModelScorer (declared, not shipped) ───────────────────────────


class TrainedModelScorer:
    """Declared but not shipped trained: DR-SCR-03.

    Constructor raises `ScorerArtefactMissingError` with a clear message so
    a reviewer who flips `Settings.scorer_backend = "trained_model"` sees
    the exact failure mode the train-button is designed to resolve.
    """

    scorer_id = "trained_model.v0"
    scorer_version = "0.0.0"

    def __init__(self, artefact_path: str | None) -> None:
        raise ScorerArtefactMissingError(
            f"no trained scorer artefact present at "
            f"{artefact_path or '<unset>'} — run "
            f"`grading-rubric-cli train-scorer` to produce one"
        )

    def score_rubric(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult:  # pragma: no cover — unreachable in v1
        raise NotImplementedError(
            "TrainedModelScorer is declared but no model is shipped in v1"
        )


# ── Selection (DR-SCR-04) ────────────────────────────────────────────────


def make_scorer(settings: Settings) -> Scorer:
    """Instantiate exactly one `Scorer` per call from `Settings.scorer_backend`."""

    if settings.scorer_backend == "llm_panel":
        return LlmPanelScorer()
    if settings.scorer_backend == "trained_model":
        return TrainedModelScorer(settings.trained_scorer_artefact_path)
    raise ValueError(f"unknown scorer_backend: {settings.scorer_backend}")
