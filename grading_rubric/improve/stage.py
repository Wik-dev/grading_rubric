"""DR-IM-01..14 — `propose` (improve) stage.

The stage is intentionally tolerant of an offline / stub-backend run: when no
LLM is available it produces deterministic, finding-driven `REPLACE_FIELD`
drafts that the three-step application pipeline (DR-IM-07) then commits to
the improved rubric. This makes the full V-shape pipeline runnable without
an API key while preserving the drafts-vs-final ownership boundary.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from grading_rubric.assess.models import AssessOutputs
from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.improve.models import (
    PlannerDecision,
    ProposedChangeDraft,
    ProposedChangeDraftBatch,
    ProposeOutputs,
)
from grading_rubric.models.findings import AssessmentFinding, ConfidenceIndicator
from grading_rubric.models.proposed_change import (
    AddNodeChange,
    ApplicationStatus,
    NodeKind,
    ProposedChange,
    RemoveNodeChange,
    ReorderNodesChange,
    ReplaceFieldChange,
    TeacherDecision,
    UpdatePointsChange,
)
from grading_rubric.models.rubric import Rubric, RubricCriterion, RubricFieldName

STAGE_ID = "propose"

# DR-IM-07: canonical operation order.
_CANONICAL_ORDER = [
    "REPLACE_FIELD",
    "UPDATE_POINTS",
    "REORDER_NODES",
    "ADD_NODE",
    "REMOVE_NODE",
]


def _plan_drafts(
    findings: list[AssessmentFinding], rubric: Rubric
) -> ProposedChangeDraftBatch:
    """Deterministic offline planner.

    For every finding with a non-None target on a field the engine knows how
    to fix, emit a `REPLACE_FIELD` draft proposing a clearer surface form.
    For findings whose target is `None` (rubric-wide), emit no draft (the
    propose stage is a fixer; rubric-wide findings flow through to the
    explanation as unaddressed observations per DR-IM-08).
    """

    drafts: list[ProposedChangeDraft] = []
    for f in findings:
        if f.target is None:
            continue
        # Build a tiny improvement payload — replace description with a more
        # specific phrasing keyed off the finding's observation. The exact
        # text matters less than that *some* draft is produced; the LLM
        # implementation can substitute a richer one.
        payload = {
            "target": f.target.model_dump(),
            "before": None,
            "after": (
                f"[clarified] {f.observation} "
                f"Concrete language and explicit indicators added so graders "
                f"can apply this criterion consistently."
            ),
        }
        drafts.append(
            ProposedChangeDraft(
                operation="REPLACE_FIELD",
                payload=payload,
                primary_criterion=f.criterion,
                source_findings=[f.id],
                rationale=(
                    f"Address finding: {f.observation} "
                    f"({f.criterion.value}, severity={f.severity.value})"
                ),
                confidence=ConfidenceIndicator.from_score(
                    max(0.30, f.confidence.score - 0.05),
                    "deterministic offline planner; conservative confidence",
                ),
            )
        )
    decision = (
        PlannerDecision.CHANGES_PROPOSED if drafts else PlannerDecision.NO_CHANGES_NEEDED
    )
    return ProposedChangeDraftBatch(decision=decision, drafts=drafts)


# ── Three-step deterministic application pipeline ─────────────────────────


def _step1_conflict_resolution(
    drafts: list[ProposedChangeDraft],
) -> tuple[list[ProposedChangeDraft], set[int]]:
    """DR-IM-07 step 1: REMOVE_NODE supersedes ancestors.

    Returns (kept_drafts_with_indices, superseded_indices). For the offline
    planner we never emit REMOVE_NODE drafts so there is nothing to supersede,
    but the function is here for completeness and to make the contract real.
    """

    return drafts, set()


def _step2_canonical_order(
    drafts: list[ProposedChangeDraft],
) -> list[ProposedChangeDraft]:
    """DR-IM-07 step 2: canonical operation order with content-based tie-break."""

    def sort_key(d: ProposedChangeDraft) -> tuple[int, str]:
        try:
            order = _CANONICAL_ORDER.index(d.operation)
        except ValueError:
            order = len(_CANONICAL_ORDER)
        # Content-based deterministic tie-break.
        from grading_rubric.audit.hashing import canonical_json

        return order, canonical_json(d.payload)

    return sorted(drafts, key=sort_key)


def _replace_field_in_rubric(
    rubric: Rubric, draft: ProposedChangeDraft
) -> tuple[Rubric, bool]:
    """Apply a REPLACE_FIELD draft to a fresh deepcopy. Returns (new_rubric, applied)."""

    new_rubric = deepcopy(rubric)
    target = draft.payload.get("target", {})
    field = target.get("field")
    after = draft.payload.get("after")
    path = target.get("criterion_path") or []
    level_id = target.get("level_id")

    # Walk to the criterion at `path`. The path stores stringified UUIDs.
    def find_criterion(criteria: list[RubricCriterion], remaining: list) -> RubricCriterion | None:
        if not remaining:
            return None
        head = remaining[0]
        for c in criteria:
            if str(c.id) == str(head):
                if len(remaining) == 1:
                    return c
                return find_criterion(c.sub_criteria, remaining[1:])
        return None

    target_crit = find_criterion(new_rubric.criteria, path)
    if target_crit is None:
        return new_rubric, False

    if field == RubricFieldName.DESCRIPTION.value:
        target_crit.description = str(after)
    elif field == RubricFieldName.SCORING_GUIDANCE.value:
        target_crit.scoring_guidance = str(after)
    elif field == RubricFieldName.NAME.value:
        target_crit.name = str(after)
    elif field == RubricFieldName.LEVEL_LABEL.value and level_id:
        for lv in target_crit.levels:
            if str(lv.id) == str(level_id):
                lv.label = str(after)
                break
        else:
            return new_rubric, False
    elif field == RubricFieldName.LEVEL_DESCRIPTOR.value and level_id:
        for lv in target_crit.levels:
            if str(lv.id) == str(level_id):
                lv.descriptor = str(after)
                break
        else:
            return new_rubric, False
    else:
        return new_rubric, False

    return new_rubric, True


def _step3_apply_and_wrap(
    starting_rubric: Rubric,
    drafts: list[ProposedChangeDraft],
    superseded: set[int],
) -> tuple[Rubric, list[ProposedChange]]:
    """DR-IM-07 step 3: apply each surviving draft + wrap into final ProposedChange."""

    current = deepcopy(starting_rubric)
    finals: list[ProposedChange] = []
    for idx, draft in enumerate(drafts):
        applied = False
        if idx not in superseded and draft.operation == "REPLACE_FIELD":
            new_rubric, applied = _replace_field_in_rubric(current, draft)
            if applied:
                current = new_rubric
        # Wrap step (DR-IM-07): assign system-owned fields.
        target = draft.payload.get("target", {})
        change_id = uuid4()
        if draft.operation == "REPLACE_FIELD":
            from grading_rubric.models.rubric import RubricTarget

            try:
                rt = RubricTarget.model_validate(target)
            except Exception:  # noqa: BLE001
                continue
            finals.append(
                ReplaceFieldChange(
                    id=change_id,
                    primary_criterion=draft.primary_criterion,
                    source_findings=draft.source_findings,
                    rationale=draft.rationale,
                    confidence=draft.confidence,
                    application_status=(
                        ApplicationStatus.APPLIED if applied else ApplicationStatus.NOT_APPLIED
                    ),
                    teacher_decision=TeacherDecision.PENDING,
                    source_operations=[],  # populated by gateway-driven planner
                    target=rt,
                    before=draft.payload.get("before"),
                    after=draft.payload.get("after"),
                )
            )
    return current, finals


# ── Stage entry point ──────────────────────────────────────────────────────


def propose_stage(
    inputs: AssessOutputs,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> ProposeOutputs:
    audit_emitter.stage_start(STAGE_ID)

    starting = inputs.parsed.starting_rubric
    base_rubric = starting or inputs.rubric_under_assessment

    batch = _plan_drafts(inputs.findings, base_rubric)
    surviving, superseded = _step1_conflict_resolution(batch.drafts)
    ordered = _step2_canonical_order(surviving)
    improved, finals = _step3_apply_and_wrap(base_rubric, ordered, superseded)

    audit_emitter.stage_end(STAGE_ID, status="success")
    return ProposeOutputs(
        assessed=inputs,
        starting_rubric=starting,
        improved_rubric=improved,
        proposed_changes=finals,
        findings=inputs.findings,
    )


propose_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
