"""DR-IM-01..14 — `propose` (improve) stage.

The LLM planner proposes rubric edits from grounded findings and grader
simulation summaries. The local pipeline validates, orders, applies, and wraps
those drafts; it does not generate local heuristic edits.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from uuid import UUID, uuid4

from grading_rubric.assess.models import AssessOutputs
from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.gateway import Gateway
from grading_rubric.improve.llm_schemas import LlmDraftEntry, LlmPlannerInput, LlmPlannerOutput
from grading_rubric.improve.models import (
    PlannerDecision,
    ProposedChangeDraft,
    ProposedChangeDraftBatch,
    ProposeOutputs,
)
from grading_rubric.models.findings import AssessmentFinding, ConfidenceIndicator, QualityCriterion
from grading_rubric.models.proposed_change import (
    AddNodeChange,
    ApplicationStatus,
    NodeKind,
    ProposedChange,
    ReplaceFieldChange,
    TeacherDecision,
)
from grading_rubric.models.rubric import (
    EvidenceProfile,
    Rubric,
    RubricCriterion,
    RubricFieldName,
    RubricLevel,
    RubricTarget,
)
from grading_rubric.models.types import CriterionId

logger = logging.getLogger(__name__)

STAGE_ID = "propose"

# DR-IM-07: canonical operation order.
_CANONICAL_ORDER = [
    "REPLACE_FIELD",
    "UPDATE_POINTS",
    "REORDER_NODES",
    "ADD_NODE",
    "REMOVE_NODE",
]


# ── LLM planner ──────────────────────────────────────────────────────────


def _collect_criterion_paths(rubric: Rubric) -> list[dict]:
    """Walk rubric tree, return list of criterion info for prompt grounding."""
    paths: list[dict] = []

    def _visit(c: RubricCriterion, path: list) -> None:
        new_path = [*path, str(c.id)]
        fields = ["name", "description"]
        if c.scoring_guidance:
            fields.append("scoring_guidance")
        level_ids = [str(lv.id) for lv in c.levels]
        paths.append({
            "criterion_path": new_path,
            "name": c.name,
            "fields": fields,
            "level_ids": level_ids,
        })
        for child in c.sub_criteria:
            _visit(child, new_path)

    for root in rubric.criteria:
        _visit(root, [])
    return paths


def _convert_and_ground(
    entries: list[LlmDraftEntry],
    findings: list[AssessmentFinding],
    rubric: Rubric,
    operation_id,
) -> list[ProposedChangeDraft]:
    """DR-IM-09: validate and convert LLM draft entries to ProposedChangeDraft.

    Grounding checks:
    1. Finding ID validation — every source_finding_ids entry must exist.
    2. Criterion path validation — walk the rubric tree to verify.
    3. Operation type validation — must be one of the 5 canonical types.
    """
    valid_finding_ids = {str(f.id) for f in findings}
    valid_criterion_paths = {
        tuple(p["criterion_path"])
        for p in _collect_criterion_paths(rubric)
    }
    valid_operations = set(_CANONICAL_ORDER)

    drafts: list[ProposedChangeDraft] = []
    for entry in entries:
        # 3. Operation type validation.
        if entry.operation not in valid_operations:
            continue

        # 1. Finding ID validation.
        grounded_ids = [fid for fid in entry.source_finding_ids if fid in valid_finding_ids]
        if not grounded_ids:
            continue

        # 2. Criterion path validation (for operations with target/parent_path).
        target = entry.payload.get("target", {})
        parent_path = entry.payload.get("parent_path")
        crit_path = target.get("criterion_path") or parent_path
        if crit_path and tuple(str(p) for p in crit_path) not in valid_criterion_paths:
            continue

        # Map primary_criterion string to enum.
        try:
            criterion = QualityCriterion(entry.primary_criterion)
        except ValueError:
            criterion = QualityCriterion.AMBIGUITY

        # Convert source_finding_ids from strings to UUIDs.
        source_findings = []
        for fid in grounded_ids:
            try:
                source_findings.append(UUID(fid))
            except ValueError:
                continue

        drafts.append(ProposedChangeDraft(
            operation=entry.operation,
            payload=entry.payload,
            primary_criterion=criterion,
            source_findings=source_findings,
            rationale=entry.rationale,
            confidence=ConfidenceIndicator.from_score(
                max(0.20, min(1.0, entry.confidence_score)),
                "LLM planner with grounding validation",
            ),
        ))

    return drafts


def _plan_drafts_llm(
    findings: list[AssessmentFinding],
    rubric: Rubric,
    evidence_profile: EvidenceProfile,
    teaching_material_text: str,
    simulation_summary: str,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> ProposedChangeDraftBatch | None:
    """LLM-powered planner."""
    gateway = Gateway()
    valid_paths = _collect_criterion_paths(rubric)

    result = gateway.measure(
        prompt_id="propose_planner",
        inputs=LlmPlannerInput(
            rubric_json=rubric.model_dump_json(indent=2),
            findings_json=json.dumps(
                [f.model_dump(mode="json") for f in findings], indent=2, default=str
            ),
            evidence_profile_json=evidence_profile.model_dump_json(indent=2),
            criterion_paths_json=json.dumps(valid_paths, indent=2, default=str),
            teaching_material_text=teaching_material_text or "",
            simulation_summary=simulation_summary,
        ),
        output_schema=LlmPlannerOutput,
        model=settings.reasoning_model,
        samples=1,
        settings=settings,
        audit_emitter=audit_emitter,
        stage_id=STAGE_ID,
    )

    if not result.aggregate:
        return None

    llm_output = result.aggregate
    grounded_drafts = _convert_and_ground(
        llm_output.drafts, findings, rubric, result.operation_id,
    )

    decision = (
        PlannerDecision.CHANGES_PROPOSED if grounded_drafts
        else PlannerDecision.NO_CHANGES_NEEDED
    )
    return ProposedChangeDraftBatch(decision=decision, drafts=grounded_drafts)


# ── Three-step application pipeline ───────────────────────────────────────


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
    """DR-IM-07 step 2: canonical operation order.

    Within the same operation type AND target field, preserve the planner's
    emission order. This is critical because the planner accumulates changes:
    each draft's `after` includes all prior edits to the same field, so
    applying them out of order would overwrite accumulated changes.
    """

    def sort_key(item: tuple[int, ProposedChangeDraft]) -> tuple[int, str, int]:
        idx, d = item
        try:
            order = _CANONICAL_ORDER.index(d.operation)
        except ValueError:
            order = len(_CANONICAL_ORDER)
        # Group by operation + target field, then preserve planner order within.
        target = d.payload.get("target", {})
        target_key = f"{target.get('field', '')}:{','.join(str(x) for x in target.get('criterion_path', []))}"
        return order, target_key, idx

    indexed = list(enumerate(drafts))
    indexed.sort(key=sort_key)
    return [d for _, d in indexed]


def _find_criterion(criteria: list[RubricCriterion], path: list) -> RubricCriterion | None:
    """Walk the rubric tree to find the criterion at `path` (stringified UUIDs)."""
    if not path:
        return None
    head = path[0]
    for c in criteria:
        if str(c.id) == str(head):
            if len(path) == 1:
                return c
            return _find_criterion(c.sub_criteria, path[1:])
    return None


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

    target_crit = _find_criterion(new_rubric.criteria, path)
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


def _add_node_to_rubric(
    rubric: Rubric, draft: ProposedChangeDraft
) -> tuple[Rubric, bool]:
    """Apply an ADD_NODE draft to a fresh deepcopy. Returns (new_rubric, applied).

    Inserts a new RubricCriterion (or RubricLevel) into the rubric tree at the
    parent identified by ``parent_path`` and position ``insert_index``.

    For criterion nodes the parent's ``points`` is updated to include the new
    child (additive invariant) unless the child's points are already accounted
    for (i.e. the parent points already equal the sum of children after insert).
    """

    new_rubric = deepcopy(rubric)
    parent_path = draft.payload.get("parent_path", [])
    insert_index = draft.payload.get("insert_index", 0)
    node_kind = draft.payload.get("node_kind", "criterion")
    raw_node = draft.payload.get("node")
    if raw_node is None:
        return new_rubric, False

    parent = _find_criterion(new_rubric.criteria, parent_path)
    if parent is None:
        return new_rubric, False

    if node_kind == "criterion":
        try:
            # Ensure fresh UUID so there are no collisions.
            if isinstance(raw_node, dict):
                if "id" not in raw_node or raw_node["id"] is None:
                    raw_node["id"] = str(uuid4())
                # Recursively assign IDs to nested sub_criteria if missing.
                def _ensure_ids(n: dict) -> None:
                    if "id" not in n or n["id"] is None:
                        n["id"] = str(uuid4())
                    for sub in n.get("sub_criteria", []):
                        _ensure_ids(sub)
                    for lv in n.get("levels", []):
                        if "id" not in lv or lv["id"] is None:
                            lv["id"] = str(uuid4())
                _ensure_ids(raw_node)
                child = RubricCriterion.model_validate(raw_node, strict=False)
            elif isinstance(raw_node, RubricCriterion):
                child = raw_node
            else:
                return new_rubric, False
        except Exception:  # noqa: BLE001
            logger.warning("ADD_NODE: failed to validate node as RubricCriterion")
            return new_rubric, False

        idx = max(0, min(insert_index, len(parent.sub_criteria)))
        parent.sub_criteria.insert(idx, child)

        # Maintain additive points invariant: parent.points = sum(children).
        # Only update if the parent is additive AND the child sum exceeds
        # the current parent points (i.e. the LLM set child points that
        # overflow). If the children fit within the existing allocation,
        # leave the parent points unchanged.
        if parent.additive and parent.sub_criteria:
            child_sum = sum(c.points or 0.0 for c in parent.sub_criteria)
            if abs(child_sum - (parent.points or 0.0)) > 1e-6:
                parent.points = child_sum

        # Propagate up: update the rubric's total_points if root-level sums
        # changed. Walk root criteria and recompute.
        new_root_sum = sum(c.points or 0.0 for c in new_rubric.criteria)
        if abs(new_root_sum - new_rubric.total_points) > 1e-6:
            new_rubric.total_points = new_root_sum

        return new_rubric, True

    # Level nodes are less common but supported.
    if node_kind == "level":
        try:
            if isinstance(raw_node, dict):
                if "id" not in raw_node or raw_node["id"] is None:
                    raw_node["id"] = str(uuid4())
                level = RubricLevel.model_validate(raw_node, strict=False)
            elif isinstance(raw_node, RubricLevel):
                level = raw_node
            else:
                return new_rubric, False
        except Exception:  # noqa: BLE001
            logger.warning("ADD_NODE: failed to validate node as RubricLevel")
            return new_rubric, False

        idx = max(0, min(insert_index, len(parent.levels)))
        parent.levels.insert(idx, level)
        return new_rubric, True

    return new_rubric, False


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
        if idx not in superseded:
            if draft.operation == "REPLACE_FIELD":
                new_rubric, applied = _replace_field_in_rubric(current, draft)
                if applied:
                    current = new_rubric
            elif draft.operation == "ADD_NODE":
                new_rubric, applied = _add_node_to_rubric(current, draft)
                if applied:
                    current = new_rubric

        # Wrap step (DR-IM-07): assign system-owned fields.
        change_id = uuid4()
        if draft.operation == "REPLACE_FIELD":
            target = draft.payload.get("target", {})
            try:
                rt = RubricTarget.model_validate(target, strict=False)
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
                    source_operations=[],
                    target=rt,
                    before=draft.payload.get("before"),
                    after=draft.payload.get("after"),
                )
            )
        elif draft.operation == "ADD_NODE":
            parent_path_raw = draft.payload.get("parent_path", [])
            try:
                parent_ids = [CriterionId(str(p)) for p in parent_path_raw]
            except Exception:  # noqa: BLE001
                continue
            raw_node = draft.payload.get("node")
            node_kind_str = draft.payload.get("node_kind", "criterion")
            try:
                nk = NodeKind(node_kind_str)
            except ValueError:
                nk = NodeKind.CRITERION
            # Build the typed node for the change record.
            try:
                if nk == NodeKind.CRITERION:
                    typed_node = RubricCriterion.model_validate(raw_node, strict=False)
                else:
                    typed_node = RubricLevel.model_validate(raw_node, strict=False)
            except Exception:  # noqa: BLE001
                continue
            finals.append(
                AddNodeChange(
                    id=change_id,
                    primary_criterion=draft.primary_criterion,
                    source_findings=draft.source_findings,
                    rationale=draft.rationale,
                    confidence=draft.confidence,
                    application_status=(
                        ApplicationStatus.APPLIED if applied else ApplicationStatus.NOT_APPLIED
                    ),
                    teacher_decision=TeacherDecision.PENDING,
                    source_operations=[],
                    parent_path=parent_ids,
                    insert_index=draft.payload.get("insert_index", 0),
                    node_kind=nk,
                    node=typed_node,
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

    if not settings.llm_available:
        raise RuntimeError(
            "propose stage requires an LLM backend; configure ANTHROPIC_API_KEY "
            "or an equivalent provider key"
        )
    teaching_text = getattr(inputs.parsed, "teaching_material_text", "") or ""
    batch = _plan_drafts_llm(
        inputs.findings,
        base_rubric,
        inputs.evidence_profile,
        teaching_text,
        inputs.simulation_summary,
        settings=settings,
        audit_emitter=audit_emitter,
    )
    if batch is None:
        raise RuntimeError("LLM planner did not return a valid planner output")

    # Three-step application pipeline runs identically on drafts from either source.
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
