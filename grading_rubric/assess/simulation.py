"""Shared grader simulation for rubric assessment.

The LLM only acts as a grader: it applies the teacher rubric to student
responses. Rubric quality is computed in Python from the resulting traces.
"""

from __future__ import annotations

import itertools
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from grading_rubric.assess.llm_schemas import (
    GraderPanelInputs,
    GradingResult,
    PairwiseInputs,
    PairwiseVerdict,
    SynthesizedResponseSet,
    SynthesizeInputs,
)
from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.gateway import Gateway
from grading_rubric.models.findings import ConfidenceIndicator
from grading_rubric.models.rubric import EvidenceProfile, Rubric, RubricCriterion
from grading_rubric.models.types import OperationId

STAGE_ID = "assess"


class ResponseSource(StrEnum):
    REAL = "real"
    SYNTHETIC = "synthetic"


class SimulationResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    text: str
    source: ResponseSource
    quality_tier: str = ""
    intended_score: float | None = None


class CriterionGradeEntry(BaseModel):
    model_config = ConfigDict(strict=True)

    criterion_id: str
    response_idx: int
    persona_idx: int
    grade: float
    justification: str
    source_operation_id: OperationId | None = None


class PairwiseComparisonEntry(BaseModel):
    model_config = ConfigDict(strict=True)

    response_a_idx: int
    response_b_idx: int
    winner: str
    confidence: float
    reason: str
    ambiguity_attributed: bool = False
    affected_criterion_ids: list[str] = Field(default_factory=list)
    source_operation_id: OperationId | None = None


class SimulationEvidence(BaseModel):
    model_config = ConfigDict(strict=True)

    rubric_id: UUID
    response_set: list[SimulationResponse] = Field(default_factory=list)
    personas_used: list[str] = Field(default_factory=list)
    criterion_path_index: dict[str, list[UUID]] = Field(default_factory=dict)
    grade_entries: list[CriterionGradeEntry] = Field(default_factory=list)
    pairwise_results: list[PairwiseComparisonEntry] = Field(default_factory=list)
    source_operations: list[OperationId] = Field(default_factory=list)
    criterion_ids: list[str] = Field(default_factory=list)


_GRADER_PERSONAS = [
    # Persona 0: Bottom-up strict
    "Start every criterion at 0 points. Add credit ONLY for elements "
    "you can explicitly verify in the response text. If the rubric says "
    "'specific to SmartCity' and the response says 'harmful to people' "
    "without naming a SmartCity component, award 0 for that element. "
    "Partial credit is 0 unless the rubric defines a partial level. "
    "When uncertain, round DOWN.",
    # Persona 1: Top-down generous
    "Start every criterion at full credit. Subtract ONLY for elements "
    "that are clearly missing or demonstrably wrong. If the response "
    "addresses the spirit of a criterion but misses a detail, keep "
    "full credit. Give benefit of the doubt on borderline cases. "
    "When uncertain, round UP.",
    # Persona 2: Rubric-literal
    "Grade exactly and only what the rubric text says. If the rubric "
    "references a document you don't have, mark the criterion as "
    "partially applicable. If the rubric says '0.5 points' with no "
    "partial level, award either 0.5 or 0. Do not infer criteria "
    "the rubric does not state. Do not reward qualities the rubric "
    "does not ask for.",
    # Persona 3: Student-intent
    "Try to understand what the student meant, not just what they "
    "wrote. If the student clearly understands the concept but "
    "expresses it poorly, give substantial credit. If the student "
    "uses the wrong terminology but describes the right mechanism, "
    "treat it as correct. Penalise only when the student's "
    "understanding is genuinely wrong, not when their writing is "
    "unclear.",
]


_PAIR_TIER_SCORES = {
    "very_poor": 0.10,
    "poor": 0.15,
    "very_weak": 0.10,
    "weak": 0.25,
    "below_average": 0.40,
    "average": 0.55,
    "above_average": 0.70,
    "good": 0.80,
    "strong": 0.85,
    "very_strong": 0.90,
    "excellent": 0.95,
}


def _pair_response_score(response: SimulationResponse) -> float:
    if response.intended_score is not None:
        return max(0.0, min(1.0, response.intended_score))
    return _PAIR_TIER_SCORES.get(response.quality_tier.lower(), 0.50)


def _is_borderline_response(response: SimulationResponse) -> bool:
    score = _pair_response_score(response)
    return 0.20 <= score <= 0.80


def _stratified_pair_indices(
    responses: list[SimulationResponse], sample_size: int
) -> list[tuple[int, int]]:
    """Pick high-information pairs instead of taking lexicographic prefixes."""

    if sample_size <= 0 or len(responses) < 2:
        return []

    all_pairs = list(itertools.combinations(range(len(responses)), 2))
    if len(all_pairs) <= sample_size:
        return all_pairs

    selected: list[tuple[int, int]] = []
    selected_set: set[tuple[int, int]] = set()

    def add(pair: tuple[int, int]) -> bool:
        if pair in selected_set or len(selected) >= sample_size:
            return False
        selected.append(pair)
        selected_set.add(pair)
        return True

    def score_gap(pair: tuple[int, int]) -> float:
        a_idx, b_idx = pair
        return abs(
            _pair_response_score(responses[a_idx])
            - _pair_response_score(responses[b_idx])
        )

    synthetic_adjacent = [
        pair
        for pair in all_pairs
        if responses[pair[0]].source == ResponseSource.SYNTHETIC
        and responses[pair[1]].source == ResponseSource.SYNTHETIC
        and _is_borderline_response(responses[pair[0]])
        and _is_borderline_response(responses[pair[1]])
        and 0.0 < score_gap(pair) <= 0.20
    ]
    synthetic_adjacent_target = min(sample_size, max(3, sample_size // 3))
    for pair in sorted(synthetic_adjacent, key=lambda p: (score_gap(p), p)):
        add(pair)
        if len(selected) >= synthetic_adjacent_target:
            break

    borderline = [
        pair
        for pair in all_pairs
        if _is_borderline_response(responses[pair[0]])
        and _is_borderline_response(responses[pair[1]])
    ]
    borderline_target = min(sample_size, synthetic_adjacent_target + max(2, sample_size // 4))
    for pair in sorted(borderline, key=lambda p: (score_gap(p), p)):
        add(pair)
        if len(selected) >= borderline_target:
            break

    high_contrast = [
        pair
        for pair in all_pairs
        if (
            min(_pair_response_score(responses[pair[0]]), _pair_response_score(responses[pair[1]]))
            <= 0.35
            and max(_pair_response_score(responses[pair[0]]), _pair_response_score(responses[pair[1]]))
            >= 0.75
        )
    ]
    for pair in sorted(high_contrast, key=lambda p: (-score_gap(p), p)):
        add(pair)
        if len(selected) >= borderline_target + max(2, sample_size // 4):
            break

    adjacent_tiers = [
        pair
        for pair in all_pairs
        if 0.0 < score_gap(pair) <= 0.20
    ]
    for pair in sorted(adjacent_tiers, key=lambda p: (score_gap(p), p)):
        add(pair)
        if len(selected) >= sample_size:
            break

    real_vs_synthetic = [
        pair
        for pair in all_pairs
        if responses[pair[0]].source != responses[pair[1]].source
    ]
    for pair in sorted(real_vs_synthetic, key=lambda p: (-score_gap(p), p)):
        add(pair)
        if len(selected) >= sample_size:
            break

    for pair in sorted(all_pairs, key=lambda p: (-score_gap(p), p)):
        add(pair)
        if len(selected) >= sample_size:
            break

    return selected


def _walk(rubric: Rubric):
    """Yield (path, criterion) for every node in the rubric tree."""

    def visit(c: RubricCriterion, path: list[UUID]):
        new_path = [*path, c.id]
        yield new_path, c
        for child in c.sub_criteria:
            yield from visit(child, new_path)

    for root in rubric.criteria:
        yield from visit(root, [])


def _walk_gradeable(rubric: Rubric):
    """Yield leaf criteria that the grader should score directly.

    Parent criteria provide context and scoring guidance, but grading both a
    parent and its children double-counts the same rubric structure.
    """

    for path, criterion in _walk(rubric):
        if not criterion.sub_criteria:
            yield path, criterion


def _criterion_key(path: list[UUID | str]) -> str:
    return ">".join(str(p) for p in path)


def _build_criterion_path_index(rubric: Rubric) -> dict[str, list[UUID]]:
    """Map the string criterion key used in LLM traces to RubricTarget paths."""

    return {_criterion_key(path): path for path, _ in _walk_gradeable(rubric)}


def _rubric_to_text(rubric: Rubric) -> str:
    """Human-readable serialization of a rubric for LLM prompts."""

    lines: list[str] = [f"# {rubric.title} (total: {rubric.total_points} points)\n"]

    def render(c: RubricCriterion, path: list[UUID], depth: int = 0) -> None:
        indent = "  " * depth
        key = _criterion_key(path)
        points = c.points if c.points is not None else rubric.total_points
        lines.append(f"{indent}## {c.name} ({points} pts)")
        lines.append(f"{indent}criterion_id: {key}")
        lines.append(f"{indent}criterion_path: {[str(p) for p in path]}")
        lines.append(f"{indent}description: {c.description}")
        if c.scoring_guidance:
            lines.append(f"{indent}scoring_guidance: {c.scoring_guidance}")
        if c.levels:
            lines.append(f"{indent}levels:")
            for lv in c.levels:
                lines.append(
                    f"{indent}  - {lv.label} ({lv.points} pts): {lv.descriptor}"
                )
        for child in c.sub_criteria:
            render(child, [*path, child.id], depth + 1)

    for root in rubric.criteria:
        render(root, [root.id])
    return "\n".join(lines)


def _criterion_names(rubric: Rubric) -> str:
    lines = []
    for path, c in _walk_gradeable(rubric):
        key = _criterion_key(path)
        points = c.points if c.points is not None else rubric.total_points
        lines.append(f"- {key}: {c.name} ({points} pts)")
    return "\n".join(lines)


def _confidence_floor(evidence: EvidenceProfile, base: float) -> ConfidenceIndicator:
    score = base
    if evidence.synthetic_responses_used or not evidence.student_copies_present:
        score = max(0.20, min(score, 0.40))
    rationale = (
        "synthetic candidate responses only"
        if evidence.synthetic_responses_used or not evidence.student_copies_present
        else "real student copies + grounded measurement"
    )
    return ConfidenceIndicator.from_score(score, rationale)


def _require_llm(settings: Settings) -> None:
    if settings.ocr_backend == "stub":
        raise RuntimeError(
            "grader simulation requires a real LLM backend; set GR_OCR_BACKEND=anthropic "
            "and ANTHROPIC_API_KEY, or inject a Gateway in tests"
        )
    if settings.ocr_backend == "anthropic" and not settings.anthropic_api_key:
        raise RuntimeError("grader simulation requires ANTHROPIC_API_KEY")
    if settings.ocr_backend == "openai" and not settings.openai_api_key:
        raise RuntimeError("grader simulation requires OPENAI_API_KEY")


def _simulation_settings(settings: Settings) -> Settings:
    # When the main backend is stub, honour it — no real LLM calls.
    if settings.ocr_backend == "stub":
        return settings
    backend = settings.simulation_backend
    model = settings.simulation_model
    updates: dict[str, str] = {}
    if backend is not None:
        updates["ocr_backend"] = backend
    if model:
        updates["ocr_model"] = model
    if not updates:
        return settings
    return settings.model_copy(update=updates)


def _normalise_key(path: list[str], index: dict[str, list[UUID]]) -> str | None:
    key = _criterion_key(path)
    if key in index:
        return key
    if len(path) == 1:
        suffix = str(path[0])
        for known in index:
            if known.split(">")[-1] == suffix:
                return known
    return None


def run_grader_simulation(
    rubric: Rubric,
    exam_question_text: str,
    teaching_material_text: str,
    student_texts: list[str],
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
    gateway: Gateway | None = None,
    response_set: list[SimulationResponse] | None = None,
    stage_id: str = STAGE_ID,
) -> SimulationEvidence:
    injected_gateway = gateway is not None
    simulation_settings = _simulation_settings(settings)
    if gateway is None:
        _require_llm(simulation_settings)
        gateway = Gateway()

    rubric_text = _rubric_to_text(rubric)
    criterion_names = _criterion_names(rubric)
    criterion_path_index = _build_criterion_path_index(rubric)

    if response_set is not None:
        responses = [r.model_copy(deep=True) for r in response_set]
    else:
        responses = [
            SimulationResponse(text=t, source=ResponseSource.REAL)
            for t in student_texts
            if t.strip()
        ]

    source_operations: list[OperationId] = []
    target_count = max(settings.simulation_target_responses, len(responses))
    needed = target_count - len(responses)
    if response_set is None and needed > 0 and exam_question_text.strip():
        synth = gateway.measure(
            prompt_id="assess_synthesize_responses",
            inputs=SynthesizeInputs(
                rubric_text=rubric_text,
                exam_question_text=exam_question_text,
                teaching_material_text=teaching_material_text,
                tier_count=str(needed),
            ),
            output_schema=SynthesizedResponseSet,
            samples=1,
            temperature=0.4,
            settings=simulation_settings,
            audit_emitter=audit_emitter,
            stage_id=stage_id,
        )
        source_operations.append(synth.operation_id)
        if synth.aggregate:
            for item in synth.aggregate.responses[:needed]:
                responses.append(
                    SimulationResponse(
                        text=item.text,
                        source=ResponseSource.SYNTHETIC,
                        quality_tier=item.tier,
                        intended_score=item.intended_score,
                    )
                )

    personas = _GRADER_PERSONAS[: max(1, settings.simulation_panel_size)]
    llm_concurrency = max(1, settings.simulation_concurrency)

    def call_gateway() -> Gateway:
        return gateway if injected_gateway else Gateway()

    grade_entries: list[CriterionGradeEntry] = []

    def grade_one(
        response_idx: int,
        response: SimulationResponse,
        persona_idx: int,
        persona: str,
    ) -> tuple[int, int, OperationId, list[CriterionGradeEntry]]:
        result = call_gateway().measure(
            prompt_id="ambiguity_grade_with_rubric",
            inputs=GraderPanelInputs(
                rubric_text=rubric_text,
                teaching_material_text=teaching_material_text,
                response_text=response.text,
                persona_description=persona,
                criterion_names=criterion_names,
            ),
            output_schema=GradingResult,
            samples=1,
            temperature=0.3,
            settings=simulation_settings,
            audit_emitter=audit_emitter,
            stage_id=stage_id,
        )
        entries: list[CriterionGradeEntry] = []
        if not result.aggregate:
            return response_idx, persona_idx, result.operation_id, entries
        for grade in result.aggregate.grades:
            criterion_id = _normalise_key(grade.criterion_path, criterion_path_index)
            if criterion_id is None:
                audit_emitter.record_operation(
                    {
                        "stage_id": stage_id,
                        "kind": "simulation_unmapped_criterion",
                        "criterion_path": grade.criterion_path,
                    }
                )
                continue
            entries.append(
                CriterionGradeEntry(
                    criterion_id=criterion_id,
                    response_idx=response_idx,
                    persona_idx=persona_idx,
                    grade=max(0.0, min(1.0, grade.grade)),
                    justification=grade.justification,
                    source_operation_id=result.operation_id,
                )
            )
        return response_idx, persona_idx, result.operation_id, entries

    grading_jobs = [
        (response_idx, response, persona_idx, persona)
        for response_idx, response in enumerate(responses)
        for persona_idx, persona in enumerate(personas)
    ]
    if llm_concurrency == 1 or len(grading_jobs) <= 1:
        graded = [grade_one(*job) for job in grading_jobs]
    else:
        graded = []
        with ThreadPoolExecutor(max_workers=llm_concurrency) as executor:
            futures = [executor.submit(grade_one, *job) for job in grading_jobs]
            for future in as_completed(futures):
                graded.append(future.result())

    for _response_idx, _persona_idx, operation_id, entries in sorted(
        graded, key=lambda item: (item[0], item[1])
    ):
        source_operations.append(operation_id)
        grade_entries.extend(entries)

    pairwise_results: list[PairwiseComparisonEntry] = []
    if len(responses) >= 2:
        pairs = _stratified_pair_indices(responses, settings.simulation_pairwise_pairs)

        def compare_one(
            pair_idx: int,
            a_idx: int,
            b_idx: int,
        ) -> tuple[int, OperationId, PairwiseComparisonEntry | None]:
            result = call_gateway().measure(
                prompt_id="discrimination_pairwise_compare",
                inputs=PairwiseInputs(
                    rubric_text=rubric_text,
                    teaching_material_text=teaching_material_text,
                    response_a_text=responses[a_idx].text,
                    response_b_text=responses[b_idx].text,
                ),
                output_schema=PairwiseVerdict,
                samples=1,
                temperature=0.2,
                settings=simulation_settings,
                audit_emitter=audit_emitter,
                stage_id=stage_id,
            )
            if not result.aggregate:
                return pair_idx, result.operation_id, None
            affected = []
            for raw_id in result.aggregate.affected_criterion_ids:
                key = _normalise_key([raw_id], criterion_path_index)
                if key is None and raw_id in criterion_path_index:
                    key = raw_id
                if key is None:
                    audit_emitter.record_operation(
                        {
                            "stage_id": stage_id,
                            "kind": "simulation_unmapped_pairwise_criterion",
                            "criterion_id": raw_id,
                        }
                    )
                    continue
                affected.append(key)
            return (
                pair_idx,
                result.operation_id,
                PairwiseComparisonEntry(
                    response_a_idx=a_idx,
                    response_b_idx=b_idx,
                    winner=result.aggregate.winner,
                    confidence=max(0.0, min(1.0, result.aggregate.confidence)),
                    reason=result.aggregate.reason,
                    ambiguity_attributed=result.aggregate.ambiguity_attributed,
                    affected_criterion_ids=affected,
                    source_operation_id=result.operation_id,
                ),
            )

        pairwise_jobs = [
            (pair_idx, a_idx, b_idx) for pair_idx, (a_idx, b_idx) in enumerate(pairs)
        ]
        if llm_concurrency == 1 or len(pairwise_jobs) <= 1:
            compared = [compare_one(*job) for job in pairwise_jobs]
        else:
            compared = []
            with ThreadPoolExecutor(max_workers=llm_concurrency) as executor:
                futures = [executor.submit(compare_one, *job) for job in pairwise_jobs]
                for future in as_completed(futures):
                    compared.append(future.result())

        for _pair_idx, operation_id, entry in sorted(compared, key=lambda item: item[0]):
            source_operations.append(operation_id)
            if entry is not None:
                pairwise_results.append(entry)

    return SimulationEvidence(
        rubric_id=rubric.id,
        response_set=responses,
        personas_used=personas,
        criterion_path_index=criterion_path_index,
        grade_entries=grade_entries,
        pairwise_results=pairwise_results,
        source_operations=source_operations,
        criterion_ids=list(criterion_path_index.keys()),
    )


def _format_simulation_summary(sim: SimulationEvidence) -> str:
    lines = [
        f"responses={len(sim.response_set)}",
        f"personas={len(sim.personas_used)}",
        f"grade_entries={len(sim.grade_entries)}",
        f"pairwise_results={len(sim.pairwise_results)}",
    ]
    for criterion_id in sim.criterion_ids:
        entries = [e for e in sim.grade_entries if e.criterion_id == criterion_id]
        if not entries:
            continue
        grades = [e.grade for e in entries]
        by_response: dict[int, list[float]] = {}
        for entry in entries:
            by_response.setdefault(entry.response_idx, []).append(entry.grade)
        response_spread = ", ".join(
            f"r{idx}=mean:{statistics.mean(values):.2f}/stdev:{(statistics.stdev(values) if len(values) >= 2 else 0.0):.2f}"
            for idx, values in sorted(by_response.items())
        )
        lines.append(
            f"criterion {criterion_id}: mean_grade={statistics.mean(grades):.2f}, "
            f"min={min(grades):.2f}, max={max(grades):.2f}, "
            f"response_count={len(by_response)}"
        )
        lines.append(f"  response_grade_spread: {response_spread}")
    if sim.pairwise_results:
        lines.append("pairwise comparisons:")
        for pair in sim.pairwise_results[:10]:
            lines.append(
                f"  r{pair.response_a_idx} vs r{pair.response_b_idx}: "
                f"winner={pair.winner}, confidence={pair.confidence:.2f}, "
                f"ambiguity_attributed={pair.ambiguity_attributed}, "
                f"affected_criteria={pair.affected_criterion_ids}; {pair.reason[:260]}"
            )
    return "\n".join(lines)
