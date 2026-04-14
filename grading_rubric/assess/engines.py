"""Simulation-backed assessment engines.

The engines do not call the LLM. They compute rubric-quality findings and
scores from grader simulation traces produced by `assess.simulation`.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

import krippendorff
import numpy as np

from grading_rubric.assess.simulation import (
    CriterionGradeEntry,
    SimulationEvidence,
)
from grading_rubric.config.settings import Settings
from grading_rubric.models.deliverable import CriterionScore
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    Measurement,
    QualityCriterion,
    QualityMethod,
    Severity,
)
from grading_rubric.models.rubric import Rubric, RubricFieldName, RubricTarget


class MeasurementEngine(Protocol):
    criterion: QualityCriterion

    def measure_from_simulation(
        self, sim: SimulationEvidence, *, rubric: Rubric, settings: Settings
    ) -> list[AssessmentFinding]: ...


def _target_for(sim: SimulationEvidence, criterion_id: str) -> RubricTarget | None:
    path = sim.criterion_path_index.get(criterion_id)
    if not path:
        return None
    return RubricTarget(criterion_path=path, level_id=None, field=RubricFieldName.DESCRIPTION)


def _make_finding(
    criterion: QualityCriterion,
    severity: Severity,
    target: RubricTarget | None,
    observation: str,
    evidence_text: str,
    method: QualityMethod,
    confidence: ConfidenceIndicator,
    rubric: Rubric,
    *,
    samples: int,
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
        measured_against_rubric_id=rubric.id,
        iteration=0,
        source_operations=source_operations or [],
        linked_finding_ids=linked_finding_ids or [],
    )


def _entries_by_criterion(sim: SimulationEvidence) -> dict[str, list[CriterionGradeEntry]]:
    grouped: dict[str, list[CriterionGradeEntry]] = defaultdict(list)
    for entry in sim.grade_entries:
        grouped[entry.criterion_id].append(entry)
    return grouped


@dataclass
class ResponseCriterionSignal:
    criterion_id: str
    response_idx: int
    entries: list[CriterionGradeEntry]
    mean_grade: float
    stdev: float
    extremity: float
    ambiguity_weight: float = 0.0
    applicability_weight: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _grade_matrix_signals(sim: SimulationEvidence) -> dict[str, list[ResponseCriterionSignal]]:
    """Infer ambiguity/applicability signals from grade shape only."""

    by_response_and_criterion: dict[int, dict[str, list[CriterionGradeEntry]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for entry in sim.grade_entries:
        by_response_and_criterion[entry.response_idx][entry.criterion_id].append(entry)

    criterion_means_by_response: dict[int, dict[str, float]] = {}
    overall_mean_by_response: dict[int, float] = {}
    for response_idx, by_criterion in by_response_and_criterion.items():
        criterion_means = {
            criterion_id: statistics.mean(entry.grade for entry in entries)
            for criterion_id, entries in by_criterion.items()
            if entries
        }
        criterion_means_by_response[response_idx] = criterion_means
        if criterion_means:
            overall_mean_by_response[response_idx] = statistics.mean(
                criterion_means.values()
            )

    signals: dict[str, list[ResponseCriterionSignal]] = defaultdict(list)
    for response_idx, by_criterion in by_response_and_criterion.items():
        for criterion_id, entries in by_criterion.items():
            grades = [entry.grade for entry in entries]
            mean_grade = statistics.mean(grades)
            stdev = statistics.stdev(grades) if len(grades) >= 2 else 0.0
            extremity = abs((2.0 * mean_grade) - 1.0)
            signal = ResponseCriterionSignal(
                criterion_id=criterion_id,
                response_idx=response_idx,
                entries=entries,
                mean_grade=mean_grade,
                stdev=stdev,
                extremity=extremity,
            )

            at_floor = sum(1 for grade in grades if grade <= 0.10)
            at_ceiling = sum(1 for grade in grades if grade >= 0.90)
            if len(grades) >= 2 and at_floor >= 1 and at_ceiling >= 1:
                signal.applicability_weight = max(signal.applicability_weight, 1.0)
                signal.reasons.append(
                    f"bimodal edge grades floor={at_floor}, ceiling={at_ceiling}"
                )
            elif stdev >= 0.10:
                if extremity < 0.40:
                    signal.ambiguity_weight = max(signal.ambiguity_weight, 1.0)
                    signal.reasons.append(
                        f"midscale disagreement stdev={stdev:.2f}, extremity={extremity:.2f}"
                    )
                elif extremity > 0.60:
                    signal.applicability_weight = max(signal.applicability_weight, 1.0)
                    signal.reasons.append(
                        f"edge disagreement stdev={stdev:.2f}, extremity={extremity:.2f}"
                    )
                else:
                    signal.ambiguity_weight = max(signal.ambiguity_weight, 0.5)
                    signal.applicability_weight = max(signal.applicability_weight, 0.5)
                    signal.reasons.append(
                        f"grey-zone disagreement stdev={stdev:.2f}, extremity={extremity:.2f}"
                    )

            overall_mean = overall_mean_by_response.get(response_idx)
            criterion_mean = criterion_means_by_response.get(response_idx, {}).get(
                criterion_id
            )
            if (
                overall_mean is not None
                and criterion_mean is not None
                and criterion_mean < 0.15
                and overall_mean > 0.50
            ):
                signal.applicability_weight = max(signal.applicability_weight, 1.0)
                signal.reasons.append(
                    f"criterion-response orphan criterion_mean={criterion_mean:.2f}, overall_mean={overall_mean:.2f}"
                )

            signals[criterion_id].append(signal)
    return signals


def _signal_problem_rate(
    rows: list[ResponseCriterionSignal], attr: str
) -> tuple[float, list[ResponseCriterionSignal]]:
    signal_rows = [row for row in rows if getattr(row, attr) > 0.0]
    if not signal_rows:
        return 0.0, []
    # Rate over ALL rows so 1 problematic response out of 10 gives 0.1, not 1.0
    return (
        max(0.0, min(1.0, statistics.mean(getattr(row, attr) for row in rows))),
        signal_rows,
    )


def _midscale_response_count(rows: list[ResponseCriterionSignal]) -> int:
    return sum(1 for row in rows if row.extremity < 0.40)


def _signal_evidence(rows: list[ResponseCriterionSignal]) -> str:
    lines: list[str] = []
    for row in rows[:6]:
        lines.append(
            f"response={row.response_idx}, mean={row.mean_grade:.2f}, "
            f"stdev={row.stdev:.2f}, extremity={row.extremity:.2f}: "
            f"{'; '.join(row.reasons)}"
        )
        for entry in row.entries[:2]:
            lines.append(
                f"  persona={entry.persona_idx}, grade={entry.grade:.2f}: "
                f"{entry.justification[:180]}"
            )
    return "\n".join(lines)


def _krippendorff_alpha(
    entries: list[CriterionGradeEntry],
    n_personas: int,
    n_responses: int,
) -> float:
    """Compute Krippendorff's α for one criterion from grade entries."""
    matrix = np.full((n_personas, n_responses), np.nan)
    for entry in entries:
        if 0 <= entry.persona_idx < n_personas and 0 <= entry.response_idx < n_responses:
            matrix[entry.persona_idx, entry.response_idx] = entry.grade
    non_nan = matrix[~np.isnan(matrix)]
    if len(non_nan) < 2 or len(set(non_nan.tolist())) <= 1:
        return 1.0  # perfect agreement or degenerate
    try:
        alpha = krippendorff.alpha(
            reliability_data=matrix, level_of_measurement="ordinal"
        )
        return max(0.0, min(1.0, alpha))
    except Exception:
        return 1.0


_AMBIGUITY_BANDS = [
    (0.90, "excellent", "Graders consistently agree. Your rubric criteria are clear."),
    (0.80, "good", "Graders mostly agree, with occasional differences on borderline answers."),
    (0.67, "moderate", "Graders disagree often enough that some students would get different grades depending on who marks them."),
    (0.50, "weak", "Graders frequently disagree. The rubric language needs clarification."),
    (0.00, "poor", "Graders disagree more than they agree. The rubric needs significant revision."),
]


def _ambiguity_band(alpha: float) -> tuple[str, str]:
    """Return (label, narrative) for an α value."""
    for threshold, label, narrative in _AMBIGUITY_BANDS:
        if alpha >= threshold:
            return label, narrative
    return "poor", _AMBIGUITY_BANDS[-1][2]


_TIER_ORDER = {
    "very_poor": 0,
    "poor": 0,
    "very_weak": 0,
    "weak": 1,
    "below_average": 2,
    "average": 3,
    "above_average": 4,
    "good": 4,
    "strong": 5,
    "very_strong": 5,
    "excellent": 6,
}


def _tier_separation(
    means: dict[int, float], sim: SimulationEvidence
) -> float | None:
    tiered: list[tuple[int, float]] = []
    for response_idx, mean_grade in means.items():
        tier = sim.response_set[response_idx].quality_tier
        if tier:
            tiered.append((_TIER_ORDER.get(tier.lower(), 3), mean_grade))
    if len(tiered) < 2:
        return None

    low_rank = min(rank for rank, _ in tiered)
    high_rank = max(rank for rank, _ in tiered)
    if low_rank == high_rank:
        return None

    low_scores = [score for rank, score in tiered if rank == low_rank]
    high_scores = [score for rank, score in tiered if rank == high_rank]
    return statistics.mean(high_scores) - statistics.mean(low_scores)


def _rank_values(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        rank = (cursor + 1 + end) / 2.0
        for original_idx, _ in ordered[cursor:end]:
            ranks[original_idx] = rank
        cursor = end
    return ranks


def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x <= 0 or denom_y <= 0:
        return None
    return max(-1.0, min(1.0, numerator / (denom_x * denom_y)))


def _spearman_rank_score(calibrated: list[tuple[int, float, float, str]]) -> float | None:
    if len(calibrated) < 2:
        return None
    intended_ranks = _rank_values([intended for _, intended, _, _ in calibrated])
    actual_ranks = _rank_values([actual for _, _, actual, _ in calibrated])
    corr = _pearson_correlation(intended_ranks, actual_ranks)
    if corr is None:
        return None
    return (corr + 1.0) / 2.0


def _synthetic_calibration(
    means: dict[int, float], sim: SimulationEvidence
) -> tuple[float | None, float | None, float | None, float | None, str]:
    """Score whether synthetic tiers received grades near their intended level.

    A coarse rubric can have a high max-min range while still collapsing most
    responses into full credit. Intended synthetic scores let us detect that
    ceiling effect without asking the LLM to judge rubric quality directly.
    """

    calibrated: list[tuple[int, float, float, str]] = []
    for response_idx, mean_grade in means.items():
        if response_idx >= len(sim.response_set):
            continue
        response = sim.response_set[response_idx]
        if response.intended_score is None:
            continue
        calibrated.append(
            (
                response_idx,
                max(0.0, min(1.0, response.intended_score)),
                max(0.0, min(1.0, mean_grade)),
                response.quality_tier,
            )
        )

    if len(calibrated) < 2:
        return None, None, None, None, ""

    mean_error = statistics.mean(abs(actual - intended) for _, intended, actual, _ in calibrated)
    calibration_score = max(0.0, min(1.0, 1.0 - (2.0 * mean_error)))
    rank_score = _spearman_rank_score(calibrated)

    ceiling_candidates = [
        (idx, intended, actual, tier)
        for idx, intended, actual, tier in calibrated
        if intended < 0.85
    ]
    if ceiling_candidates:
        ceiling_hits = [
            (idx, intended, actual, tier)
            for idx, intended, actual, tier in ceiling_candidates
            if actual >= 0.90
        ]
        ceiling_score = 1.0 - (len(ceiling_hits) / len(ceiling_candidates))
    else:
        ceiling_score = 1.0

    non_excellent = [
        (idx, intended, actual, tier)
        for idx, intended, actual, tier in calibrated
        if intended < 0.95 and tier.lower() != "excellent"
    ]
    if non_excellent:
        non_excellent_ceiling_rate = sum(
            1 for _, _, actual, _ in non_excellent if actual >= 0.90
        ) / len(non_excellent)
        ceiling_cap = 0.60 if non_excellent_ceiling_rate > 0.50 else None
    else:
        ceiling_cap = None

    detail = ", ".join(
        f"r{idx}:{tier or 'synthetic'} intended={intended:.2f} actual={actual:.2f}"
        for idx, intended, actual, tier in calibrated
    )
    return calibration_score, ceiling_score, rank_score, ceiling_cap, detail


def _weighted_average(parts: list[tuple[float, float | None]]) -> float:
    usable = [(weight, value) for weight, value in parts if value is not None]
    total_weight = sum(weight for weight, _ in usable)
    if total_weight <= 0:
        return 0.0
    return max(
        0.0,
        min(1.0, sum(weight * value for weight, value in usable) / total_weight),
    )


class AmbiguityEngine:
    """Ambiguity = inter-rater agreement measured by Krippendorff's α."""

    criterion = QualityCriterion.AMBIGUITY

    def measure_from_simulation(
        self, sim: SimulationEvidence, *, rubric: Rubric, settings: Settings
    ) -> list[AssessmentFinding]:
        findings: list[AssessmentFinding] = []
        entries_by_criterion = _entries_by_criterion(sim)
        n_personas = max((e.persona_idx for e in sim.grade_entries), default=-1) + 1
        n_responses = len(sim.response_set)
        signals = _grade_matrix_signals(sim)

        for criterion_id, entries in entries_by_criterion.items():
            alpha = _krippendorff_alpha(entries, n_personas, n_responses)
            if alpha >= 0.80:
                continue  # good or excellent agreement — no finding

            severity = Severity.HIGH if alpha < 0.67 else Severity.MEDIUM
            band_label, band_narrative = _ambiguity_band(alpha)
            signal_rows = signals.get(criterion_id, [])
            evidence_text = _signal_evidence(signal_rows) if signal_rows else ""

            findings.append(
                _make_finding(
                    QualityCriterion.AMBIGUITY,
                    severity,
                    _target_for(sim, criterion_id),
                    (
                        f"Inter-rater agreement on criterion {criterion_id} is "
                        f"{band_label} (α={alpha:.2f}). {band_narrative}"
                    ),
                    evidence_text,
                    QualityMethod.LLM_PANEL_AGREEMENT,
                    ConfidenceIndicator.from_score(
                        max(0.20, min(0.90, alpha)),
                        f"Krippendorff's α={alpha:.2f} ({band_label})",
                    ),
                    rubric,
                    samples=len(entries),
                    agreement=alpha,
                    source_operations=sim.source_operations,
                )
            )
        return findings


class ApplicabilityEngine:
    """Applicability = graders can apply the criterion while grading."""

    criterion = QualityCriterion.APPLICABILITY

    def measure_from_simulation(
        self, sim: SimulationEvidence, *, rubric: Rubric, settings: Settings
    ) -> list[AssessmentFinding]:
        findings: list[AssessmentFinding] = []
        signals = _grade_matrix_signals(sim)
        entries_by_criterion = _entries_by_criterion(sim)
        for criterion_id, rows in signals.items():
            problem_rate, signal_rows = _signal_problem_rate(rows, "applicability_weight")
            if problem_rate < 0.20:
                continue

            applicability_rate = 1.0 - problem_rate
            severity = Severity.HIGH if problem_rate >= 0.50 else Severity.MEDIUM
            findings.append(
                _make_finding(
                    QualityCriterion.APPLICABILITY,
                    severity,
                    _target_for(sim, criterion_id),
                    (
                        f"Grade matrix suggests an applicability gap on rubric criterion "
                        f"{criterion_id}; applicability_gap_signal={problem_rate:.2f}."
                    ),
                    _signal_evidence(signal_rows),
                    QualityMethod.SYNTHETIC_COVERAGE,
                    ConfidenceIndicator.from_score(
                        max(0.20, min(0.85, applicability_rate)),
                        "inferred from edge polarization and criterion-response orphaning",
                    ),
                    rubric,
                    samples=len(entries_by_criterion.get(criterion_id, [])),
                    agreement=None,
                    source_operations=sim.source_operations,
                )
            )
        return findings


class DiscriminationEngine:
    """Discrimination = score spread and pairwise consistency."""

    criterion = QualityCriterion.DISCRIMINATION_POWER

    def measure_from_simulation(
        self, sim: SimulationEvidence, *, rubric: Rubric, settings: Settings
    ) -> list[AssessmentFinding]:
        findings: list[AssessmentFinding] = []
        entries_by_criterion = _entries_by_criterion(sim)

        for criterion_id, entries in entries_by_criterion.items():
            by_response: dict[int, list[float]] = defaultdict(list)
            for entry in entries:
                by_response[entry.response_idx].append(entry.grade)
            means = {
                response_idx: statistics.mean(grades)
                for response_idx, grades in by_response.items()
                if grades
            }
            if len(means) < 2:
                continue

            separation = max(means.values()) - min(means.values())
            tier_sep = _tier_separation(means, sim)
            if tier_sep is not None:
                separation = tier_sep
            (
                calibration_score,
                ceiling_score,
                rank_score,
                ceiling_cap,
                calibration_detail,
            ) = _synthetic_calibration(means, sim)

            if separation < 0.25 or (
                calibration_score is not None and calibration_score < 0.60
            ) or (
                ceiling_score is not None and ceiling_score < 0.70
            ) or (
                rank_score is not None and rank_score < 0.60
            ) or (
                ceiling_cap is not None
            ):
                findings.append(
                    _make_finding(
                        QualityCriterion.DISCRIMINATION_POWER,
                        Severity.MEDIUM,
                        _target_for(sim, criterion_id),
                        (
                            f"Rubric criterion {criterion_id} produced weak discrimination "
                            f"across responses; separation={separation:.2f}, "
                            f"calibration={calibration_score if calibration_score is not None else 1.0:.2f}, "
                            f"ceiling={ceiling_score if ceiling_score is not None else 1.0:.2f}, "
                            f"rank={rank_score if rank_score is not None else 1.0:.2f}."
                        ),
                        "\n".join(
                            [
                                f"mean_scores={{{', '.join(f'{k}: {v:.2f}' for k, v in means.items())}}}",
                                calibration_detail,
                            ]
                        ).strip(),
                        QualityMethod.SCORE_DISTRIBUTION_SEPARATION,
                        ConfidenceIndicator.from_score(
                            0.65, "score spread from grader simulation traces"
                        ),
                        rubric,
                        samples=len(entries),
                        source_operations=sim.source_operations,
                    )
                )

        for pair in sim.pairwise_results:
            affected = pair.affected_criterion_ids or sim.criterion_ids
            for criterion_id in affected:
                entries = entries_by_criterion.get(criterion_id, [])
                by_response: dict[int, list[float]] = defaultdict(list)
                for entry in entries:
                    by_response[entry.response_idx].append(entry.grade)
                if pair.response_a_idx not in by_response or pair.response_b_idx not in by_response:
                    continue
                a_score = statistics.mean(by_response[pair.response_a_idx])
                b_score = statistics.mean(by_response[pair.response_b_idx])
                scores_equal = abs(a_score - b_score) < 0.10
                winner_is_tie = pair.winner.upper() in {"TIE", "EQUAL"}
                if not scores_equal or winner_is_tie:
                    continue

                disc = _make_finding(
                    QualityCriterion.DISCRIMINATION_POWER,
                    Severity.MEDIUM,
                    _target_for(sim, criterion_id),
                    (
                        f"Pairwise comparison found a winner for responses "
                        f"{pair.response_a_idx} and {pair.response_b_idx}, but criterion "
                        f"{criterion_id} gave near-equal scores."
                    ),
                    (
                        f"winner={pair.winner}, confidence={pair.confidence:.2f}, "
                        f"a_score={a_score:.2f}, b_score={b_score:.2f}; {pair.reason}"
                    ),
                    QualityMethod.PAIRWISE_CONSISTENCY,
                    ConfidenceIndicator.from_score(
                        0.60, "pairwise comparison against simulated criterion scores"
                    ),
                    rubric,
                    samples=1,
                    source_operations=[pair.source_operation_id] if pair.source_operation_id else [],
                )
                findings.append(disc)

                if pair.ambiguity_attributed:
                    amb = _make_finding(
                        QualityCriterion.AMBIGUITY,
                        Severity.MEDIUM,
                        _target_for(sim, criterion_id),
                        (
                            f"Pairwise comparison attributed the near-equal scoring on "
                            f"criterion {criterion_id} to rubric ambiguity."
                        ),
                        pair.reason,
                        QualityMethod.PAIRWISE_CONSISTENCY,
                        ConfidenceIndicator.from_score(
                            0.55, "ambiguity signal from pairwise grading comparison"
                        ),
                        rubric,
                        samples=1,
                        linked_finding_ids=[disc.id],
                        source_operations=[pair.source_operation_id] if pair.source_operation_id else [],
                    )
                    disc.linked_finding_ids.append(amb.id)
                    findings.append(amb)
        return findings


def scores_from_simulation(
    sim: SimulationEvidence,
    *,
    rubric: Rubric,
    settings: Settings,
    baseline_sim: SimulationEvidence | None = None,
) -> list[CriterionScore]:
    entries_by_criterion = _entries_by_criterion(sim)
    n_personas = max((e.persona_idx for e in sim.grade_entries), default=-1) + 1
    n_responses = len(sim.response_set)

    # Baseline grade matrix for paired scoring (score stage only)
    baseline_entries_by_criterion = (
        _entries_by_criterion(baseline_sim) if baseline_sim else {}
    )

    ambiguity_values: list[float] = []
    applicability_values: list[float] = []
    discrimination_values: list[float] = []
    signal_rows_by_criterion = _grade_matrix_signals(sim)

    for criterion_id in sim.criterion_ids:
        entries = entries_by_criterion.get(criterion_id, [])
        if not entries:
            continue

        # ── Ambiguity: Krippendorff's α ──────────────────────────────────
        alpha = _krippendorff_alpha(entries, n_personas, n_responses)

        # Paired scoring: if baseline available, compute paired α delta
        # and use it to ensure improvement is not swallowed by noise.
        if baseline_entries_by_criterion and criterion_id in baseline_entries_by_criterion:
            baseline_alpha = _krippendorff_alpha(
                baseline_entries_by_criterion[criterion_id], n_personas, n_responses,
            )
            # Paired grade deltas: same (persona, response) grading both rubrics
            paired_deltas = _paired_grade_deltas(
                baseline_entries_by_criterion[criterion_id], entries,
                n_personas, n_responses,
            )
            if paired_deltas:
                mean_delta = statistics.mean(paired_deltas)
                # If paired evidence shows reduced disagreement (mean grades
                # shift toward consensus), nudge α up proportionally.
                # This cancels correlated persona/response noise.
                paired_alpha = baseline_alpha + (alpha - baseline_alpha)
                # Use paired_alpha only if it's more favourable than
                # independent α AND supported by paired deltas variance
                # decreasing.
                baseline_var = _paired_grade_variance(
                    baseline_entries_by_criterion[criterion_id], n_personas, n_responses,
                )
                improved_var = _paired_grade_variance(entries, n_personas, n_responses)
                if improved_var < baseline_var:
                    # Variance decreased → agreement improved → trust α
                    alpha = max(alpha, paired_alpha)

        ambiguity_values.append(alpha)

        # ── Applicability ────────────────────────────────────────────────
        signal_rows = signal_rows_by_criterion.get(criterion_id, [])
        applicability_problem_rate, _ = _signal_problem_rate(
            signal_rows, "applicability_weight"
        )
        applicability_values.append(1.0 - applicability_problem_rate)

        # ── Discrimination ───────────────────────────────────────────────
        by_response: dict[int, list[float]] = defaultdict(list)
        for entry in entries:
            by_response[entry.response_idx].append(entry.grade)
        means = {
            response_idx: statistics.mean(grades)
            for response_idx, grades in by_response.items()
            if grades
        }
        if len(means) >= 2:
            tier_sep = _tier_separation(means, sim)
            if tier_sep is not None:
                separation = tier_sep
            else:
                separation = max(means.values()) - min(means.values())
        else:
            separation = 0.0
        calibration_score, ceiling_score, rank_score, ceiling_cap, _ = _synthetic_calibration(means, sim)

        relevant_pairs = [
            p
            for p in sim.pairwise_results
            if not p.affected_criterion_ids or criterion_id in p.affected_criterion_ids
        ]
        consistent = 0
        total = 0
        for pair in relevant_pairs:
            if pair.response_a_idx not in means or pair.response_b_idx not in means:
                continue
            total += 1
            a_score = means[pair.response_a_idx]
            b_score = means[pair.response_b_idx]
            margin = 0.10
            winner = pair.winner.upper()
            if winner == "A" and a_score > b_score + margin:
                consistent += 1
            elif winner == "B" and b_score > a_score + margin:
                consistent += 1
            elif winner in {"TIE", "EQUAL"} and abs(a_score - b_score) <= margin:
                consistent += 1
        pairwise_consistency = consistent / total if total else 1.0
        if calibration_score is not None:
            discrimination = _weighted_average(
                [
                    (0.25, calibration_score),
                    (0.20, rank_score),
                    (0.15, pairwise_consistency),
                    (0.40, ceiling_score),
                ]
            )
            if ceiling_cap is not None:
                discrimination = min(discrimination, ceiling_cap)
            discrimination_values.append(discrimination)
        else:
            discrimination_values.append(
                max(0.0, min(1.0, 0.5 * separation + 0.5 * pairwise_consistency))
            )

    def avg(values: list[float]) -> float:
        return max(0.0, min(1.0, statistics.mean(values))) if values else 0.0

    ambiguity_avg = avg(ambiguity_values)
    band_label, band_narrative = _ambiguity_band(ambiguity_avg)
    ambiguity_rationale = (
        f"Krippendorff's α={ambiguity_avg:.2f} ({band_label}). {band_narrative}"
    )
    ambiguity_confidence = max(0.20, min(0.90, ambiguity_avg)) if sim.response_set else 0.20

    def score(
        criterion: QualityCriterion,
        value: float,
        rationale: str,
        confidence_score: float | None = None,
    ) -> CriterionScore:
        return CriterionScore(
            criterion=criterion,
            score=value,
            confidence=ConfidenceIndicator.from_score(
                confidence_score
                if confidence_score is not None
                else 0.70
                if sim.response_set
                else 0.20,
                rationale,
            ),
            method=QualityMethod.GRADER_SIMULATION,
            source_operation_id=sim.source_operations[0] if sim.source_operations else None,
        )

    return [
        score(
            QualityCriterion.AMBIGUITY,
            ambiguity_avg,
            ambiguity_rationale,
            ambiguity_confidence,
        ),
        score(
            QualityCriterion.APPLICABILITY,
            avg(applicability_values),
            "computed from edge polarization and criterion-response orphaning",
        ),
        score(
            QualityCriterion.DISCRIMINATION_POWER,
            avg(discrimination_values),
            "computed from score separation and pairwise consistency",
        ),
    ]


def _paired_grade_deltas(
    baseline_entries: list[CriterionGradeEntry],
    improved_entries: list[CriterionGradeEntry],
    n_personas: int,
    n_responses: int,
) -> list[float]:
    """Compute per-(persona, response) grade deltas between two simulations."""
    baseline = {}
    for e in baseline_entries:
        baseline[(e.persona_idx, e.response_idx)] = e.grade
    deltas = []
    for e in improved_entries:
        key = (e.persona_idx, e.response_idx)
        if key in baseline:
            deltas.append(e.grade - baseline[key])
    return deltas


def _paired_grade_variance(
    entries: list[CriterionGradeEntry],
    n_personas: int,
    n_responses: int,
) -> float:
    """Average inter-persona variance per response for one criterion."""
    by_response: dict[int, list[float]] = defaultdict(list)
    for e in entries:
        by_response[e.response_idx].append(e.grade)
    variances = []
    for grades in by_response.values():
        if len(grades) >= 2:
            variances.append(statistics.variance(grades))
    return statistics.mean(variances) if variances else 0.0
