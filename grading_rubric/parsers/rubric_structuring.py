"""LLM-assisted structuring for teacher-provided free-text rubrics."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.gateway import Gateway
from grading_rubric.models.rubric import Rubric, RubricCriterion
from grading_rubric.parsers.llm_schemas import (
    DecomposedCriterion,
    DecomposedRubric,
    DecomposeRubricInput,
)

STAGE_ID = "parse-inputs"


class RubricStructurer(Protocol):
    def structure_rubric(
        self,
        text: str,
        *,
        exam_question_text: str,
        teaching_material_text: str,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> Rubric | None: ...


def _to_criterion(node: DecomposedCriterion) -> RubricCriterion:
    children = [_to_criterion(child) for child in node.sub_criteria]
    child_sum = sum((child.points or 0.0) for child in children)
    points = max(0.0, node.points if node.points is not None else child_sum)
    additive = not children or abs(child_sum - points) <= 1e-6
    return RubricCriterion(
        id=uuid4(),
        name=node.name.strip() or "Criterion",
        description=node.description.strip(),
        scoring_guidance=node.scoring_guidance.strip() if node.scoring_guidance else None,
        points=points,
        additive=additive,
        sub_criteria=children,
    )


def rubric_from_structured_output(
    output: DecomposedRubric,
    *,
    fallback_title: str,
    fallback_total_points: float,
) -> Rubric | None:
    criteria = [
        _to_criterion(c)
        for c in output.criteria
        if c.name.strip() and not c.is_penalty
    ]
    if not criteria:
        return None

    penalty_notes = [
        f"{p.name}: {p.description}"
        + (f" Trigger: {p.penalty_trigger}" if p.penalty_trigger else "")
        + f" Deduction: {p.points}."
        for p in output.penalizations
    ]
    if penalty_notes:
        penalty_guidance = "Penalizations: " + " ".join(penalty_notes)
        if len(criteria) == 1:
            current = criteria[0].scoring_guidance or ""
            criteria[0].scoring_guidance = (
                f"{current}\n\n{penalty_guidance}".strip()
            )

    root_sum = sum((c.points or 0.0) for c in criteria)
    total = output.total_points if output.total_points is not None else fallback_total_points
    if total <= 0.0 or abs(total - root_sum) > 1e-6:
        total = root_sum
    if total <= 0.0:
        return None

    return Rubric(
        id=uuid4(),
        schema_version="1.0.0",
        title=output.title.strip() or fallback_title,
        total_points=total,
        criteria=criteria,
        metadata={
            "structured_from_free_text": True,
            "parsing_notes": output.parsing_notes,
            "penalizations": [p.model_dump(mode="json") for p in output.penalizations],
        },
    )


class GatewayRubricStructurer:
    def __init__(self, *, gateway: Gateway | None = None) -> None:
        self._gateway = gateway

    def structure_rubric(
        self,
        text: str,
        *,
        exam_question_text: str,
        teaching_material_text: str,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> Rubric | None:
        if not settings.llm_available:
            return None

        gateway = self._gateway or Gateway()
        result = gateway.measure(
            prompt_id="decompose_rubric",
            inputs=DecomposeRubricInput(
                rubric_text=text,
                exam_question_text=exam_question_text,
                teaching_material_text=teaching_material_text,
            ),
            output_schema=DecomposedRubric,
            samples=1,
            model=settings.reasoning_model,
            settings=settings,
            audit_emitter=audit_emitter,
            stage_id=STAGE_ID,
        )
        if result.aggregate is None:
            return None

        first_line = text.strip().split("\n", 1)[0][:80]
        return rubric_from_structured_output(
            result.aggregate,
            fallback_title=f"teacher-provided rubric: {first_line}",
            fallback_total_points=0.0,
        )

