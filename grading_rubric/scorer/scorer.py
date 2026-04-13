"""DR-SCR-01..04 — `Scorer` Protocol and shipped implementations.

The `Scorer` Protocol is the sole surface the rest of the code knows about
for headline scoring. `LlmPanelScorer` is the default; `TrainedModelScorer`
is declared but unshipped per DR-SCR-03 — its constructor raises
`ScorerArtefactMissingError` so a reviewer who selects it sees the exact
failure mode the train-button capability is designed to resolve.

When an LLM backend is available, `LlmPanelScorer` uses the gateway to get
calibrated 0-100 scores per criterion with panel diversity via temperature.
When the LLM is unavailable, it falls back to the deterministic offline
penalty formula.
"""

from __future__ import annotations

import json
import logging
import statistics
from typing import Protocol
from uuid import uuid4

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.gateway import Gateway, GatewayError
from grading_rubric.models.deliverable import CriterionScore
from grading_rubric.models.findings import (
    ConfidenceIndicator,
    QualityCriterion,
    QualityMethod,
)
from grading_rubric.scorer.models import (
    LlmScorerInput,
    LlmScorerOutput,
    ScorerArtefactMissingError,
    ScoringEvidence,
    ScoringResult,
)

logger = logging.getLogger(__name__)

STAGE_ID = "score"


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


# ── Helpers ──────────────────────────────────────────────────────────────


def _llm_available(settings: Settings) -> bool:
    """Check if an LLM backend is configured and usable."""
    if settings.llm_backend == "stub":
        return False
    if settings.llm_backend == "anthropic" and not settings.anthropic_api_key:
        return False
    if settings.llm_backend == "openai" and not settings.openai_api_key:
        return False
    return True


def _trimmed_mean(scores: list[int]) -> float:
    """DR-SCR-04: drop lowest + highest, mean of the rest."""
    if len(scores) <= 2:
        return statistics.mean(scores)
    return statistics.mean(sorted(scores)[1:-1])


def _confidence_from_stdev(stdev: float, panel_size: int) -> ConfidenceIndicator:
    """DR-SCR-05: map stdev to confidence level."""
    if stdev < 10:
        score, rationale = 0.85, f"high panel agreement (σ={stdev:.1f}, n={panel_size})"
    elif stdev <= 20:
        score, rationale = 0.55, f"moderate panel agreement (σ={stdev:.1f}, n={panel_size})"
    else:
        score, rationale = 0.25, f"low panel agreement (σ={stdev:.1f}, n={panel_size})"
    return ConfidenceIndicator.from_score(score, rationale)


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
        if _llm_available(settings):
            try:
                return self._score_with_llm_panel(
                    evidence, settings=settings, audit_emitter=audit_emitter,
                )
            except Exception as exc:
                # Audit the fallback.
                audit_emitter.record_operation({
                    "id": str(uuid4()),
                    "stage_id": STAGE_ID,
                    "status": "fallback",
                    "details": {
                        "kind": "llm_fallback",
                        "engine": "scorer",
                        "error": str(exc),
                    },
                    "error": None,
                })
        return self._score_deterministic(
            evidence, settings=settings, audit_emitter=audit_emitter,
        )

    def _score_with_llm_panel(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult:
        """DR-SCR-02: LLM panel scoring with trimmed mean."""
        gateway = Gateway()
        panel_size = settings.scorer_panel_size
        rubric_json = evidence.rubric.model_dump_json(indent=2)

        scores: list[CriterionScore] = []
        for criterion in QualityCriterion:
            relevant_findings = [f for f in evidence.findings if f.criterion == criterion]
            findings_json = json.dumps(
                [f.model_dump(mode="json") for f in relevant_findings],
                indent=2, default=str,
            )

            result = gateway.measure(
                prompt_id="score_criterion",
                inputs=LlmScorerInput(
                    rubric_json=rubric_json,
                    criterion=criterion.value,
                    findings_json=findings_json,
                    exam_question_text=evidence.exam_question_text,
                    teaching_material_text=evidence.teaching_material_text,
                ),
                output_schema=LlmScorerOutput,
                samples=panel_size,
                settings=settings,
                audit_emitter=audit_emitter,
                stage_id=STAGE_ID,
            )

            raw_scores = [max(0, min(100, s.score)) for s in result.samples]
            trimmed = _trimmed_mean(raw_scores)
            stdev = statistics.stdev(raw_scores) if len(raw_scores) > 1 else 0.0
            confidence = _confidence_from_stdev(stdev, panel_size)

            # Normalize 0-100 to 0.0-1.0 for CriterionScore.
            normalized_score = trimmed / 100.0

            scores.append(
                CriterionScore(
                    criterion=criterion,
                    score=normalized_score,
                    confidence=confidence,
                    method=QualityMethod.LLM_PANEL_AGREEMENT,
                    source_operation_id=result.operation_id,
                )
            )

        return ScoringResult(
            quality_scores=scores,
            scorer_id=self.scorer_id,
            scorer_version=self.scorer_version,
        )

    def _score_deterministic(
        self,
        evidence: ScoringEvidence,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> ScoringResult:
        """Deterministic offline aggregation: per criterion, score =
        1 − (sum_of_severity_weights / normalizer), clamped to [0, 1].
        The normalizer (2.5) means ~3 high-severity findings per criterion
        would drive the score to zero. This is monotone: removing any
        finding always improves the score (no average-paradox).
        """
        severity_weight = {"low": 0.1, "medium": 0.2, "high": 0.4}
        _NORMALIZER = 2.5

        scores: list[CriterionScore] = []
        for criterion in QualityCriterion:
            relevant = [f for f in evidence.findings if f.criterion == criterion]
            if not relevant:
                raw_score = 1.0
            else:
                total_penalty = sum(
                    severity_weight.get(f.severity.value, 0.2)
                    for f in relevant
                )
                raw_score = max(0.0, min(1.0, 1.0 - total_penalty / _NORMALIZER))
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
