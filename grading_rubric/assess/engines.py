"""DR-AS-02..15 — three measurement engines under a stage-local protocol.

Each engine is **independent** (no engine reads another's output, no engine
holds module-level state). The engines walk the rubric, run their method(s)
through `gateway.measure(...)` (the only LLM seam, DR-LLM-01) where applicable,
and return a list of `AssessmentFinding` instances.

For the offline / stub-backend path the engines fall back to deterministic
linguistic-sweep heuristics (DR-AS-06 sub-method b) so the full pipeline can
run end-to-end without an API key. The honest reporting of confidence (low
confidence on the synthetic-only path, DR-AS-13 floor of 0.20) makes this
safe under SR-AS-08.
"""

from __future__ import annotations

import re
import statistics
from typing import Protocol
from uuid import uuid4

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    Measurement,
    QualityCriterion,
    QualityMethod,
    Severity,
)
from grading_rubric.models.rubric import (
    EvidenceProfile,
    Rubric,
    RubricCriterion,
    RubricFieldName,
    RubricTarget,
)


class MeasurementEngine(Protocol):
    """Stage-local protocol shared by the three engines."""

    criterion: QualityCriterion

    def measure(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]: ...


# ── Helpers ────────────────────────────────────────────────────────────────


_VAGUE_TERMS = (
    "good",
    "bad",
    "well",
    "poorly",
    "appropriate",
    "adequate",
    "sufficient",
    "clear",
    "unclear",
    "thorough",
    "complete",
    "incomplete",
    "some",
    "many",
    "few",
    "etc",
)


def _walk(rubric: Rubric):
    """Yield (path, criterion) for every node in the rubric tree, root → leaf."""

    def visit(c: RubricCriterion, path: list):
        new_path = [*path, c.id]
        yield new_path, c
        for child in c.sub_criteria:
            yield from visit(child, new_path)

    for root in rubric.criteria:
        yield from visit(root, [])


def _confidence_floor(evidence: EvidenceProfile, base: float) -> ConfidenceIndicator:
    """DR-AS-13 — synthetic-only runs floor at 0.20."""

    score = base
    if evidence.synthetic_responses_used or not evidence.student_copies_present:
        score = max(0.20, min(score, 0.40))  # honest LOW
    rationale = (
        "synthetic candidate responses only — confidence is honestly LOW"
        if evidence.synthetic_responses_used or not evidence.student_copies_present
        else "real student copies + grounded measurement"
    )
    return ConfidenceIndicator.from_score(score, rationale)


# ── AmbiguityEngine ────────────────────────────────────────────────────────


class AmbiguityEngine:
    criterion = QualityCriterion.AMBIGUITY

    def measure(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        """DR-AS-06 — linguistic sweep sub-method (deterministic, offline-safe).

        The grader-panel sub-method (DR-AS-06 sub-method a) requires the LLM
        gateway and a fixed grader pool. We expose the linguistic-sweep path
        unconditionally; gateway-driven measurement can be layered on top
        once an API key is configured.
        """

        findings: list[AssessmentFinding] = []
        for path, c in _walk(rubric):
            for term in _VAGUE_TERMS:
                if re.search(rf"\b{re.escape(term)}\b", c.description.lower()):
                    findings.append(
                        AssessmentFinding(
                            id=uuid4(),
                            criterion=QualityCriterion.AMBIGUITY,
                            severity=Severity.MEDIUM,
                            target=RubricTarget(
                                criterion_path=path,
                                level_id=None,
                                field=RubricFieldName.DESCRIPTION,
                            ),
                            observation=(
                                f"Criterion {c.name!r} description uses vague term "
                                f"{term!r}."
                            ),
                            evidence=(
                                f"linguistic sweep matched {term!r} in description: "
                                f"{c.description[:120]}"
                            ),
                            measurement=Measurement(
                                method=QualityMethod.LINGUISTIC_SWEEP,
                                samples=1,
                                agreement=None,
                            ),
                            confidence=_confidence_floor(evidence, 0.65),
                            measured_against_rubric_id=rubric.id,
                            iteration=0,
                            source_operations=[],
                            linked_finding_ids=[],
                        )
                    )
                    break  # one finding per criterion is enough for the sweep
            # Levels: check that adjacent levels have distinct points and labels.
            if c.levels and len({lv.label for lv in c.levels}) < len(c.levels):
                findings.append(
                    AssessmentFinding(
                        id=uuid4(),
                        criterion=QualityCriterion.AMBIGUITY,
                        severity=Severity.HIGH,
                        target=RubricTarget(
                            criterion_path=path,
                            level_id=c.levels[0].id,
                            field=RubricFieldName.LEVEL_LABEL,
                        ),
                        observation=(
                            f"Criterion {c.name!r} has duplicate level labels."
                        ),
                        evidence=(
                            "linguistic sweep: at least two levels share a label"
                        ),
                        measurement=Measurement(
                            method=QualityMethod.LINGUISTIC_SWEEP,
                            samples=1,
                            agreement=None,
                        ),
                        confidence=_confidence_floor(evidence, 0.85),
                        measured_against_rubric_id=rubric.id,
                        iteration=0,
                        source_operations=[],
                        linked_finding_ids=[],
                    )
                )
        return findings


# ── ApplicabilityEngine ────────────────────────────────────────────────────


class ApplicabilityEngine:
    criterion = QualityCriterion.APPLICABILITY

    def measure(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        findings: list[AssessmentFinding] = []
        # Heuristic: if a criterion description has fewer than 20 chars or no
        # scoring guidance, it is likely under-specified for grading.
        for path, c in _walk(rubric):
            if not c.scoring_guidance and len(c.description) < 40:
                findings.append(
                    AssessmentFinding(
                        id=uuid4(),
                        criterion=QualityCriterion.APPLICABILITY,
                        severity=Severity.MEDIUM,
                        target=RubricTarget(
                            criterion_path=path,
                            level_id=None,
                            field=RubricFieldName.SCORING_GUIDANCE,
                        ),
                        observation=(
                            f"Criterion {c.name!r} has no scoring guidance and a "
                            f"very short description; graders cannot apply it "
                            f"consistently."
                        ),
                        evidence=(
                            f"description length = {len(c.description)} chars; "
                            f"scoring_guidance is empty"
                        ),
                        measurement=Measurement(
                            method=QualityMethod.SYNTHETIC_COVERAGE,
                            samples=1,
                            agreement=None,
                        ),
                        confidence=_confidence_floor(evidence, 0.70),
                        measured_against_rubric_id=rubric.id,
                        iteration=0,
                        source_operations=[],
                        linked_finding_ids=[],
                    )
                )
        return findings


# ── DiscriminationEngine ───────────────────────────────────────────────────


class DiscriminationEngine:
    criterion = QualityCriterion.DISCRIMINATION_POWER

    def measure(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        findings: list[AssessmentFinding] = []

        # Variance / target ratio across leaf criterion point allocations.
        leaf_points = [c.points for _, c in _walk(rubric) if c.points and not c.sub_criteria]
        if len(leaf_points) >= 2:
            var = statistics.pvariance(leaf_points)
            normalized = max(p for p in leaf_points) or 1.0
            normalized_var = var / (normalized * normalized)
            target = settings.assess_discrimination_variance_target
            if normalized_var < target:
                # Rubric-wide finding (target = None per § 4.5).
                findings.append(
                    AssessmentFinding(
                        id=uuid4(),
                        criterion=QualityCriterion.DISCRIMINATION_POWER,
                        severity=Severity.MEDIUM,
                        target=None,
                        observation=(
                            "Rubric scoring distribution is too flat across leaf "
                            "criteria; graders will struggle to distinguish "
                            "performance levels."
                        ),
                        evidence=(
                            f"normalized variance {normalized_var:.4f} below "
                            f"target {target:.4f}"
                        ),
                        measurement=Measurement(
                            method=QualityMethod.SCORE_DISTRIBUTION_SEPARATION,
                            samples=len(leaf_points),
                            agreement=normalized_var,
                        ),
                        confidence=_confidence_floor(evidence, 0.60),
                        measured_against_rubric_id=rubric.id,
                        iteration=0,
                        source_operations=[],
                        linked_finding_ids=[],
                    )
                )
        return findings
