"""DR-AS-02..15 — three measurement engines under a stage-local protocol.

Each engine is **independent** (no engine reads another's output, no engine
holds module-level state). The engines walk the rubric, run their method(s)
through `gateway.measure(...)` (the only LLM seam, DR-LLM-01) where applicable,
and return a list of `AssessmentFinding` instances.

When an LLM backend is available, each engine uses `_measure_llm()` for deeper
analysis. When the LLM is unavailable or fails, the engine falls back to the
deterministic `_measure_deterministic()` path (DR-AS-06 sub-method b) so the
full pipeline can run end-to-end without an API key. The honest reporting of
confidence (low confidence on the synthetic-only path, DR-AS-13 floor of 0.20)
makes this safe under SR-AS-08.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import statistics
from typing import Protocol
from uuid import UUID, uuid4

from grading_rubric.assess.llm_schemas import (
    CoverageInputs,
    CoverageVerdict,
    GraderPanelInputs,
    GradingResult,
    LinguisticSweepInputs,
    LinguisticSweepReport,
    PairwiseInputs,
    PairwiseVerdict,
    RubricScoring,
    ScoringInputs,
)
from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.gateway import Gateway, GatewayError
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

logger = logging.getLogger(__name__)

STAGE_ID = "assess"


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

# Phrases that indicate undefined thresholds — graders cannot apply them
# consistently because the boundary between pass/fail is subjective.
_VAGUE_THRESHOLD_PATTERNS = [
    (r"\btoo\s+\w+", "undefined threshold ('too …')"),
    (r"\bnot\s+sufficient\w*", "undefined threshold ('not sufficient…')"),
    (r"\bnot\s+enough", "undefined threshold ('not enough')"),
    (r"\bsimilar\s+enough", "undefined threshold ('similar enough')"),
]

# References to external documents the rubric doesn't embed.
_EXTERNAL_REF_PATTERNS = [
    (r"\bcheck\s+the\b", "external reference ('check the …')"),
    (r"\bsee\s+(?:the\s+)?(?:appendix|annex|table|sheet|document)\b", "external reference"),
    (r"\brefer\s+to\b", "external reference ('refer to …')"),
]

# Fixed persona pool for grader panel agreement (DR-AS-06).
_GRADER_PERSONAS = [
    "Strict grader: focuses on technical precision, penalises missing details, expects complete answers.",
    "Lenient grader: emphasises effort and partial understanding, gives benefit of the doubt.",
    "Domain expert: deep subject knowledge, evaluates conceptual accuracy over presentation.",
    "Novice TA: first-time grader, follows rubric literally, struggles with ambiguous criteria.",
    "Experienced educator: 20 years of teaching, balances fairness with rigour, interprets rubric holistically.",
    "Quantitative grader: focuses on measurable, observable evidence; ignores subjective impressions.",
]


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


def _make_finding(
    criterion: QualityCriterion,
    severity: Severity,
    target: RubricTarget | None,
    observation: str,
    evidence_text: str,
    method: QualityMethod,
    confidence: ConfidenceIndicator,
    rubric_id,
    *,
    samples: int = 1,
    agreement: float | None = None,
    source_operations: list | None = None,
    linked_finding_ids: list | None = None,
) -> AssessmentFinding:
    return AssessmentFinding(
        id=uuid4(),
        criterion=criterion,
        severity=severity,
        target=target,
        observation=observation,
        evidence=evidence_text,
        measurement=Measurement(method=method, samples=samples, agreement=agreement),
        confidence=confidence,
        measured_against_rubric_id=rubric_id,
        iteration=0,
        source_operations=source_operations or [],
        linked_finding_ids=linked_finding_ids or [],
    )


def _llm_available(settings: Settings) -> bool:
    """Check if an LLM backend is configured and usable."""
    if settings.llm_backend == "stub":
        return False
    if settings.llm_backend == "anthropic" and not settings.anthropic_api_key:
        return False
    if settings.llm_backend == "openai" and not settings.openai_api_key:
        return False
    return True


def _emit_fallback(audit_emitter: AuditEmitter, engine: str, exc: Exception) -> None:
    """Record an audit event when the LLM path fails and we fall back."""
    audit_emitter.record_operation({
        "id": str(uuid4()),
        "stage_id": STAGE_ID,
        "status": "fallback",
        "details": {
            "kind": "llm_fallback",
            "engine": engine,
            "error": str(exc),
        },
        "error": None,
    })


def _rubric_to_text(rubric: Rubric) -> str:
    """Human-readable serialization of a rubric for LLM prompts."""
    lines: list[str] = [f"# {rubric.title} (total: {rubric.total_points} points)\n"]

    def _render_criterion(c: RubricCriterion, depth: int = 0) -> None:
        indent = "  " * depth
        pts = f" ({c.points} pts)" if c.points else ""
        lines.append(f"{indent}## {c.name}{pts}")
        lines.append(f"{indent}ID path: {c.id}")
        lines.append(f"{indent}Description: {c.description}")
        if c.scoring_guidance:
            lines.append(f"{indent}Scoring guidance: {c.scoring_guidance}")
        for lv in c.levels:
            lines.append(f"{indent}  - [{lv.label}] ({lv.points} pts): {lv.descriptor}")
        for child in c.sub_criteria:
            _render_criterion(child, depth + 1)

    for root in rubric.criteria:
        _render_criterion(root)
    return "\n".join(lines)


def _criterion_names(rubric: Rubric) -> str:
    """List of criterion names with IDs for prompt injection."""
    names: list[str] = []
    for path, c in _walk(rubric):
        path_str = " > ".join(str(p) for p in path)
        names.append(f"- {c.name} (path: [{path_str}])")
    return "\n".join(names)


def _severity_from_str(s: str) -> Severity:
    """Parse severity string from LLM output."""
    s_lower = s.lower().strip()
    if s_lower in ("high", "critical"):
        return Severity.HIGH
    if s_lower in ("medium", "moderate"):
        return Severity.MEDIUM
    return Severity.LOW


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
        if _llm_available(settings):
            try:
                return self._measure_llm(
                    rubric=rubric, evidence=evidence, student_texts=student_texts,
                    settings=settings, audit_emitter=audit_emitter,
                )
            except Exception as exc:
                _emit_fallback(audit_emitter, self.criterion.value, exc)
        return self._measure_deterministic(
            rubric=rubric, evidence=evidence, student_texts=student_texts,
            settings=settings, audit_emitter=audit_emitter,
        )

    def _measure_llm(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        """LLM path: linguistic sweep + grader panel agreement."""
        gateway = Gateway()
        findings: list[AssessmentFinding] = []

        # (a) Linguistic sweep — 1 gateway call.
        rubric_text = _rubric_to_text(rubric)
        sweep_result = gateway.measure(
            prompt_id="ambiguity_linguistic_sweep",
            inputs=LinguisticSweepInputs(
                rubric_text=rubric_text,
                vague_term_seed_list=", ".join(_VAGUE_TERMS),
            ),
            output_schema=LinguisticSweepReport,
            samples=1,
            settings=settings,
            audit_emitter=audit_emitter,
            stage_id=STAGE_ID,
        )
        sweep_op_id = sweep_result.operation_id
        if sweep_result.aggregate:
            for hit in sweep_result.aggregate.hits:
                severity = _severity_from_str(hit.severity)
                target = None
                if hit.criterion_path:
                    try:
                        criterion_path = [UUID(p) if isinstance(p, str) else p for p in hit.criterion_path]
                        target = RubricTarget(
                            criterion_path=criterion_path,
                            level_id=None,
                            field=RubricFieldName(hit.field) if hit.field in RubricFieldName.__members__.values() else RubricFieldName.DESCRIPTION,
                        )
                    except (ValueError, KeyError, Exception):
                        target = None
                findings.append(_make_finding(
                    QualityCriterion.AMBIGUITY, severity, target,
                    observation=f"LLM sweep: {hit.problematic_phrase!r} — {hit.explanation}",
                    evidence_text=f"issue_type={hit.issue_type}, field={hit.field}",
                    method=QualityMethod.LINGUISTIC_SWEEP,
                    confidence=ConfidenceIndicator.from_score(
                        0.75, "LLM linguistic sweep with structured output",
                    ),
                    rubric_id=rubric.id,
                    source_operations=[sweep_op_id],
                ))

        # (b) Grader panel agreement — k calls per response.
        if student_texts:
            k = settings.assess_panel_size
            personas = _GRADER_PERSONAS[:k]
            criterion_names_str = _criterion_names(rubric)

            # Collect per-criterion grades: {criterion_path_str: list[float]}
            all_grades: dict[str, list[float]] = {}

            for response_text in student_texts:
                for persona in personas:
                    panel_result = gateway.measure(
                        prompt_id="ambiguity_grade_with_rubric",
                        inputs=GraderPanelInputs(
                            rubric_text=rubric_text,
                            response_text=response_text,
                            persona_description=persona,
                            criterion_names=criterion_names_str,
                        ),
                        output_schema=GradingResult,
                        samples=1,
                        settings=settings,
                        audit_emitter=audit_emitter,
                        stage_id=STAGE_ID,
                    )
                    if panel_result.aggregate:
                        for cg in panel_result.aggregate.grades:
                            key = ">".join(str(p) for p in cg.criterion_path)
                            all_grades.setdefault(key, []).append(cg.grade)

            # Compute agreement per criterion. Low α → ambiguity finding.
            for key, grades in all_grades.items():
                if len(grades) < 2:
                    continue
                # Simple proxy for inter-rater agreement: stdev-based.
                # True Krippendorff's α requires the krippendorff library;
                # we use coefficient of variation as a lightweight proxy.
                mean_grade = statistics.mean(grades)
                stdev = statistics.stdev(grades) if len(grades) > 1 else 0.0
                # α proxy: 1 - (stdev / max(0.01, range_possible))
                alpha_proxy = max(0.0, 1.0 - (stdev / 0.5))

                if alpha_proxy < 0.67:
                    severity = Severity.HIGH if alpha_proxy < 0.40 else Severity.MEDIUM
                    path_parts = key.split(">")
                    findings.append(_make_finding(
                        QualityCriterion.AMBIGUITY, severity, None,
                        observation=(
                            f"Grader panel disagreement on criterion path [{key}]: "
                            f"agreement proxy α={alpha_proxy:.2f} (stdev={stdev:.3f} "
                            f"across {len(grades)} grades). This suggests the rubric "
                            f"is ambiguous on this criterion."
                        ),
                        evidence_text=(
                            f"panel_size={k}, responses={len(student_texts)}, "
                            f"grades_collected={len(grades)}, mean={mean_grade:.3f}"
                        ),
                        method=QualityMethod.LLM_PANEL_AGREEMENT,
                        confidence=ConfidenceIndicator.from_score(
                            0.65, "LLM grader panel agreement measurement",
                        ),
                        rubric_id=rubric.id,
                        samples=len(grades),
                        agreement=alpha_proxy,
                    ))

        return findings

    def _measure_deterministic(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        """DR-AS-06 — linguistic sweep sub-method (deterministic, offline-safe).

        Checks for: vague terms, undefined thresholds, external references
        without embedded content, and duplicate level labels.
        """

        findings: list[AssessmentFinding] = []
        conf = _confidence_floor(evidence, 0.65)

        for path, c in _walk(rubric):
            desc_lower = c.description.lower()
            target = RubricTarget(
                criterion_path=path, level_id=None, field=RubricFieldName.DESCRIPTION,
            )

            # 1. Vague terms — report ALL matches, not just the first.
            matched_terms = [
                t for t in _VAGUE_TERMS
                if re.search(rf"\b{re.escape(t)}\b", desc_lower)
            ]
            for term in matched_terms:
                findings.append(_make_finding(
                    QualityCriterion.AMBIGUITY, Severity.MEDIUM, target,
                    observation=(
                        f"Criterion {c.name!r} uses vague term '{term}'. "
                        f"Graders may interpret this differently — replace with "
                        f"specific, observable language."
                    ),
                    evidence_text=(
                        f"linguistic sweep matched '{term}' in: "
                        f"{c.description[:120]}"
                    ),
                    method=QualityMethod.LINGUISTIC_SWEEP,
                    confidence=conf, rubric_id=rubric.id,
                ))

            # 2. Undefined thresholds (e.g. "too similar", "not sufficient").
            for pattern, label in _VAGUE_THRESHOLD_PATTERNS:
                m = re.search(pattern, desc_lower)
                if m:
                    findings.append(_make_finding(
                        QualityCriterion.AMBIGUITY, Severity.HIGH, target,
                        observation=(
                            f"Criterion {c.name!r} uses an {label}: "
                            f"'{m.group()}'. Without a concrete threshold "
                            f"(e.g. '≥80% overlap'), graders will disagree "
                            f"on the boundary."
                        ),
                        evidence_text=(
                            f"pattern '{pattern}' matched '{m.group()}' in: "
                            f"{c.description[:120]}"
                        ),
                        method=QualityMethod.LINGUISTIC_SWEEP,
                        confidence=conf, rubric_id=rubric.id,
                    ))

            # 3. External references without embedded content.
            for pattern, label in _EXTERNAL_REF_PATTERNS:
                m = re.search(pattern, desc_lower)
                if m:
                    findings.append(_make_finding(
                        QualityCriterion.AMBIGUITY, Severity.HIGH, target,
                        observation=(
                            f"Criterion {c.name!r} contains an {label}: "
                            f"'{m.group()}'. The referenced material is not "
                            f"embedded in the rubric — graders without access "
                            f"to it cannot apply this criterion."
                        ),
                        evidence_text=(
                            f"pattern '{pattern}' matched '{m.group()}' in: "
                            f"{c.description[:120]}"
                        ),
                        method=QualityMethod.LINGUISTIC_SWEEP,
                        confidence=conf, rubric_id=rubric.id,
                    ))

            # 4. Duplicate level labels.
            if c.levels and len({lv.label for lv in c.levels}) < len(c.levels):
                findings.append(_make_finding(
                    QualityCriterion.AMBIGUITY, Severity.HIGH,
                    RubricTarget(
                        criterion_path=path, level_id=c.levels[0].id,
                        field=RubricFieldName.LEVEL_LABEL,
                    ),
                    observation=f"Criterion {c.name!r} has duplicate level labels.",
                    evidence_text="at least two levels share a label",
                    method=QualityMethod.LINGUISTIC_SWEEP,
                    confidence=_confidence_floor(evidence, 0.85),
                    rubric_id=rubric.id,
                ))

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
        if _llm_available(settings):
            try:
                return self._measure_llm(
                    rubric=rubric, evidence=evidence, student_texts=student_texts,
                    settings=settings, audit_emitter=audit_emitter,
                )
            except Exception as exc:
                _emit_fallback(audit_emitter, self.criterion.value, exc)
        return self._measure_deterministic(
            rubric=rubric, evidence=evidence, student_texts=student_texts,
            settings=settings, audit_emitter=audit_emitter,
        )

    def _measure_llm(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        """LLM path: coverage check per student response."""
        gateway = Gateway()
        findings: list[AssessmentFinding] = []
        rubric_text = _rubric_to_text(rubric)
        evidence_ctx = (
            f"Evidence: {evidence.student_copies_count} student copies, "
            f"exam_question={'present' if evidence.exam_question_present else 'absent'}, "
            f"teaching_material={'present' if evidence.teaching_material_present else 'absent'}"
        )

        for response_text in student_texts:
            result = gateway.measure(
                prompt_id="applicability_cover_response",
                inputs=CoverageInputs(
                    rubric_text=rubric_text,
                    response_text=response_text,
                    evidence_context=evidence_ctx,
                ),
                output_schema=CoverageVerdict,
                samples=1,
                settings=settings,
                audit_emitter=audit_emitter,
                stage_id=STAGE_ID,
            )
            if result.aggregate and result.aggregate.status in ("uncovered", "partial"):
                severity = Severity.HIGH if result.aggregate.status == "uncovered" else Severity.MEDIUM
                findings.append(_make_finding(
                    QualityCriterion.APPLICABILITY, severity, None,
                    observation=(
                        f"Rubric coverage is {result.aggregate.status.upper()} for a student response. "
                        f"{result.aggregate.missing_dimension}"
                    ),
                    evidence_text=(
                        f"LLM coverage verdict: {result.aggregate.status}. "
                        f"Covered criteria: {', '.join(result.aggregate.covered_criteria)}. "
                        f"{result.aggregate.evidence}"
                    ),
                    method=QualityMethod.SYNTHETIC_COVERAGE,
                    confidence=ConfidenceIndicator.from_score(
                        0.70, "LLM coverage analysis with structured output",
                    ),
                    rubric_id=rubric.id,
                    source_operations=[result.operation_id],
                ))

        return findings

    def _measure_deterministic(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        findings: list[AssessmentFinding] = []
        conf = _confidence_floor(evidence, 0.70)

        for path, c in _walk(rubric):
            target_desc = RubricTarget(
                criterion_path=path, level_id=None, field=RubricFieldName.DESCRIPTION,
            )
            target_guidance = RubricTarget(
                criterion_path=path, level_id=None,
                field=RubricFieldName.SCORING_GUIDANCE,
            )

            # 1. No scoring guidance — regardless of description length.
            if not c.scoring_guidance:
                findings.append(_make_finding(
                    QualityCriterion.APPLICABILITY, Severity.MEDIUM, target_guidance,
                    observation=(
                        f"Criterion {c.name!r} has no scoring guidance. "
                        f"Graders need explicit instructions on how to apply "
                        f"this criterion to student work."
                    ),
                    evidence_text=(
                        f"scoring_guidance is empty; description alone may be "
                        f"insufficient for consistent grading"
                    ),
                    method=QualityMethod.SYNTHETIC_COVERAGE,
                    confidence=conf, rubric_id=rubric.id,
                ))

            # 2. No performance levels defined.
            if not c.levels and not c.sub_criteria:
                findings.append(_make_finding(
                    QualityCriterion.APPLICABILITY, Severity.MEDIUM, target_desc,
                    observation=(
                        f"Criterion {c.name!r} has no performance levels "
                        f"(e.g. Excellent / Good / Fair / Poor). Without levels, "
                        f"graders must interpret quality thresholds themselves."
                    ),
                    evidence_text=(
                        f"criterion has {len(c.levels)} levels and "
                        f"{len(c.sub_criteria)} sub-criteria"
                    ),
                    method=QualityMethod.SYNTHETIC_COVERAGE,
                    confidence=conf, rubric_id=rubric.id,
                ))

            # 3. External references that make the rubric non-self-contained.
            desc_lower = c.description.lower()
            for pattern, label in _EXTERNAL_REF_PATTERNS:
                if re.search(pattern, desc_lower):
                    findings.append(_make_finding(
                        QualityCriterion.APPLICABILITY, Severity.HIGH, target_desc,
                        observation=(
                            f"Criterion {c.name!r} depends on an external "
                            f"document ({label}). Graders without access to "
                            f"it cannot apply the criterion. Embed the "
                            f"relevant content directly in the rubric."
                        ),
                        evidence_text=f"detected {label} in description",
                        method=QualityMethod.SYNTHETIC_COVERAGE,
                        confidence=conf, rubric_id=rubric.id,
                    ))
                    break  # one finding per external-ref pattern is enough

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
        if _llm_available(settings):
            try:
                return self._measure_llm(
                    rubric=rubric, evidence=evidence, student_texts=student_texts,
                    settings=settings, audit_emitter=audit_emitter,
                )
            except Exception as exc:
                _emit_fallback(audit_emitter, self.criterion.value, exc)
        return self._measure_deterministic(
            rubric=rubric, evidence=evidence, student_texts=student_texts,
            settings=settings, audit_emitter=audit_emitter,
        )

    def _measure_llm(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        """LLM path: score distribution + pairwise consistency."""
        gateway = Gateway()
        findings: list[AssessmentFinding] = []
        rubric_text = _rubric_to_text(rubric)
        criterion_names_str = _criterion_names(rubric)

        # (a) Score distribution — 1 call per response.
        per_criterion_scores: dict[str, list[float]] = {}
        for response_text in student_texts:
            result = gateway.measure(
                prompt_id="discrimination_score_response",
                inputs=ScoringInputs(
                    rubric_text=rubric_text,
                    response_text=response_text,
                    criterion_names=criterion_names_str,
                ),
                output_schema=RubricScoring,
                samples=1,
                settings=settings,
                audit_emitter=audit_emitter,
                stage_id=STAGE_ID,
            )
            if result.aggregate:
                for cs in result.aggregate.criterion_scores:
                    key = ">".join(str(p) for p in cs.criterion_path)
                    per_criterion_scores.setdefault(key, []).append(cs.score)

        # Low variance across responses → finding.
        for key, scores in per_criterion_scores.items():
            if len(scores) >= 2:
                var = statistics.pvariance(scores)
                if var < settings.assess_discrimination_variance_target:
                    findings.append(_make_finding(
                        QualityCriterion.DISCRIMINATION_POWER, Severity.MEDIUM, None,
                        observation=(
                            f"LLM-scored distribution on criterion [{key}] has low "
                            f"variance ({var:.4f}) across {len(scores)} responses. "
                            f"The rubric may not discriminate well on this dimension."
                        ),
                        evidence_text=(
                            f"scores={[f'{s:.2f}' for s in scores]}, variance={var:.4f}"
                        ),
                        method=QualityMethod.SCORE_DISTRIBUTION_SEPARATION,
                        confidence=ConfidenceIndicator.from_score(
                            0.65, "LLM score distribution analysis",
                        ),
                        rubric_id=rubric.id,
                        samples=len(scores),
                    ))

        # (b) Pairwise consistency — sample pairs.
        if len(student_texts) >= 2:
            all_pairs = list(itertools.combinations(range(len(student_texts)), 2))
            sample_size = min(settings.assess_pairwise_sample_size, len(all_pairs))
            sampled_pairs = all_pairs[:sample_size]

            for i, j in sampled_pairs:
                result = gateway.measure(
                    prompt_id="discrimination_pairwise_compare",
                    inputs=PairwiseInputs(
                        rubric_text=rubric_text,
                        response_a_text=student_texts[i],
                        response_b_text=student_texts[j],
                    ),
                    output_schema=PairwiseVerdict,
                    samples=1,
                    settings=settings,
                    audit_emitter=audit_emitter,
                    stage_id=STAGE_ID,
                )
                if result.aggregate and result.aggregate.ambiguity_attributed:
                    # Dual finding: DISCRIMINATION + linked AMBIGUITY.
                    disc_finding = _make_finding(
                        QualityCriterion.DISCRIMINATION_POWER, Severity.MEDIUM, None,
                        observation=(
                            f"Pairwise comparison of responses {i+1} vs {j+1} "
                            f"attributed difficulty to rubric ambiguity. "
                            f"Winner: {result.aggregate.winner}. "
                            f"{result.aggregate.reason}"
                        ),
                        evidence_text=(
                            f"confidence={result.aggregate.confidence:.2f}, "
                            f"ambiguity_attributed=True"
                        ),
                        method=QualityMethod.PAIRWISE_CONSISTENCY,
                        confidence=ConfidenceIndicator.from_score(
                            0.60, "LLM pairwise comparison with ambiguity attribution",
                        ),
                        rubric_id=rubric.id,
                        source_operations=[result.operation_id],
                    )
                    amb_finding = _make_finding(
                        QualityCriterion.AMBIGUITY, Severity.MEDIUM, None,
                        observation=(
                            f"Rubric ambiguity detected via pairwise comparison "
                            f"(responses {i+1} vs {j+1}): {result.aggregate.reason}"
                        ),
                        evidence_text="dual signal from pairwise discrimination test",
                        method=QualityMethod.PAIRWISE_CONSISTENCY,
                        confidence=ConfidenceIndicator.from_score(
                            0.55, "ambiguity signal from pairwise discrimination test",
                        ),
                        rubric_id=rubric.id,
                        linked_finding_ids=[disc_finding.id],
                        source_operations=[result.operation_id],
                    )
                    disc_finding.linked_finding_ids.append(amb_finding.id)
                    findings.append(disc_finding)
                    findings.append(amb_finding)

        return findings

    def _measure_deterministic(
        self,
        *,
        rubric: Rubric,
        evidence: EvidenceProfile,
        student_texts: list[str],
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> list[AssessmentFinding]:
        findings: list[AssessmentFinding] = []
        conf = _confidence_floor(evidence, 0.60)

        all_nodes = list(_walk(rubric))
        leaf_nodes = [(p, c) for p, c in all_nodes if not c.sub_criteria]

        # 1. Single-criterion rubric — can't discriminate performance.
        if len(rubric.criteria) <= 1 and not any(
            c.sub_criteria for c in rubric.criteria
        ):
            findings.append(_make_finding(
                QualityCriterion.DISCRIMINATION_POWER, Severity.HIGH, None,
                observation=(
                    "The rubric has only a single criterion with no "
                    "sub-criteria. It cannot distinguish between students "
                    "who succeed on different dimensions of the task."
                ),
                evidence_text=(
                    f"rubric has {len(rubric.criteria)} root criterion(s) "
                    f"and {len(leaf_nodes)} leaf node(s) total"
                ),
                method=QualityMethod.SCORE_DISTRIBUTION_SEPARATION,
                confidence=conf, rubric_id=rubric.id,
            ))

        # 2. No levels on leaf criteria — binary pass/fail reduces spread.
        for path, c in leaf_nodes:
            if not c.levels:
                findings.append(_make_finding(
                    QualityCriterion.DISCRIMINATION_POWER, Severity.MEDIUM,
                    RubricTarget(
                        criterion_path=path, level_id=None,
                        field=RubricFieldName.DESCRIPTION,
                    ),
                    observation=(
                        f"Criterion {c.name!r} has no performance levels. "
                        f"Without graded levels (e.g. 0 / 0.5 / 1), scoring "
                        f"becomes binary and limits the spread of student grades."
                    ),
                    evidence_text=(
                        f"0 levels defined on leaf criterion {c.name!r}"
                    ),
                    method=QualityMethod.SCORE_DISTRIBUTION_SEPARATION,
                    confidence=conf, rubric_id=rubric.id,
                ))

        # 3. Flat point distribution across leaf criteria.
        leaf_points = [c.points for _, c in leaf_nodes if c.points and not c.sub_criteria]
        if len(leaf_points) >= 2:
            var = statistics.pvariance(leaf_points)
            normalized = max(p for p in leaf_points) or 1.0
            normalized_var = var / (normalized * normalized)
            target = settings.assess_discrimination_variance_target
            if normalized_var < target:
                findings.append(_make_finding(
                    QualityCriterion.DISCRIMINATION_POWER, Severity.MEDIUM, None,
                    observation=(
                        "Rubric scoring distribution is too flat across leaf "
                        "criteria; graders will struggle to distinguish "
                        "performance levels."
                    ),
                    evidence_text=(
                        f"normalized variance {normalized_var:.4f} below "
                        f"target {target:.4f}"
                    ),
                    method=QualityMethod.SCORE_DISTRIBUTION_SEPARATION,
                    confidence=conf, rubric_id=rubric.id,
                ))

        return findings
