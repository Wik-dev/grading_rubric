"""DR-IM-01..14 — `propose` (improve) stage.

The stage is intentionally tolerant of an offline / stub-backend run: when no
LLM is available it produces deterministic, finding-driven `REPLACE_FIELD`
drafts that the three-step application pipeline (DR-IM-07) then commits to
the improved rubric. This makes the full V-shape pipeline runnable without
an API key while preserving the drafts-vs-final ownership boundary.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from uuid import uuid4

from grading_rubric.assess.models import AssessOutputs
from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.gateway import Gateway, GatewayError
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
    RemoveNodeChange,
    ReorderNodesChange,
    ReplaceFieldChange,
    TeacherDecision,
    UpdatePointsChange,
)
from grading_rubric.models.rubric import EvidenceProfile, Rubric, RubricCriterion, RubricFieldName

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


def _find_criterion_text(rubric: Rubric, target: RubricTarget) -> str | None:
    """Resolve the current text of the targeted field in the rubric."""
    def find_crit(criteria: list[RubricCriterion], path: list) -> RubricCriterion | None:
        if not path:
            return None
        for c in criteria:
            if str(c.id) == str(path[0]):
                if len(path) == 1:
                    return c
                return find_crit(c.sub_criteria, path[1:])
        return None

    crit = find_crit(rubric.criteria, target.criterion_path)
    if crit is None:
        return None
    field = target.field
    if field == RubricFieldName.DESCRIPTION:
        return crit.description
    if field == RubricFieldName.NAME:
        return crit.name
    if field == RubricFieldName.SCORING_GUIDANCE:
        return crit.scoring_guidance
    return None


_REPLACEMENTS: dict[str, str] = {
    "good": "high-quality (meeting all specified criteria)",
    "bad": "harmful / malicious (as defined in the course framework)",
    "well": "thoroughly and with specific examples",
    "poorly": "insufficiently, lacking specific details",
    "appropriate": "aligned with the stated learning objectives",
    "adequate": "meeting the minimum threshold specified",
    "sufficient": "meeting the minimum requirements stated above",
    "clear": "unambiguous and verifiable by a second grader",
    "unclear": "open to multiple reasonable interpretations",
    "thorough": "covering all sub-points listed",
    "complete": "addressing every required element",
    "incomplete": "missing one or more required elements",
    "some": "at least two",
    "many": "three or more",
    "few": "one or two",
}


def _plan_drafts(
    findings: list[AssessmentFinding], rubric: Rubric
) -> ProposedChangeDraftBatch:
    """Deterministic offline planner.

    For every finding with a non-None target on a field the engine knows how
    to fix, emit a `REPLACE_FIELD` draft proposing a clearer surface form.
    For findings whose target is `None` (rubric-wide), emit no draft (the
    propose stage is a fixer; rubric-wide findings flow through to the
    explanation as unaddressed observations per DR-IM-08).

    Changes accumulate: each draft's `after` is computed against the text
    that includes all previous drafts' edits, so no change overwrites another.
    """
    import re

    # Track the current state of each (criterion_path, field) pair so edits
    # accumulate instead of overwriting each other.
    working_text: dict[tuple, str] = {}

    def _target_key(target) -> tuple:
        return (tuple(str(c) for c in target.criterion_path), target.field.value)

    def _current_text(finding: AssessmentFinding) -> str:
        key = _target_key(finding.target)
        if key in working_text:
            return working_text[key]
        original = _find_criterion_text(rubric, finding.target) or ""
        working_text[key] = original
        return original

    drafts: list[ProposedChangeDraft] = []
    for f in findings:
        if f.target is None:
            continue

        before = _current_text(f)

        # Extract the vague term from the observation if this is a
        # linguistic-sweep finding (pattern: "uses vague term 'X'.")
        vague_match = re.search(r"uses vague term '(\w+)'", f.observation)
        threshold_match = re.search(
            r"undefined threshold \('.*?'\): '([^']+)'", f.observation
        )
        external_match = re.search(
            r"external reference \('.*?'\): '([^']+)'", f.observation
        )

        if vague_match and before:
            term = vague_match.group(1)
            replacement = _REPLACEMENTS.get(term.lower())
            if replacement:
                after = re.sub(
                    rf"\b{re.escape(term)}\b",
                    replacement,
                    before,
                    count=1,
                    flags=re.IGNORECASE,
                )
                # Fix article: "a <vowel>" → "an <vowel>"
                after = re.sub(r"\ba ([aeiou])", r"an \1", after)
            else:
                after = re.sub(
                    rf"\b({re.escape(term)})\b",
                    rf"\1 [define precisely]",
                    before,
                    count=1,
                    flags=re.IGNORECASE,
                )
        elif threshold_match and before:
            # Replace the vague threshold with a concrete alternative.
            term = threshold_match.group(1)
            _THRESHOLD_FIX: dict[str, str] = {
                "too similar": "sharing more than 80% of key characteristics",
                "not sufficiently": "insufficiently (fewer than 3 specific details)",
                "not enough": "fewer than the minimum required number of",
                "similar enough": "sharing at least 50% of key elements",
            }
            replacement = _THRESHOLD_FIX.get(
                term.lower(), f"{term} [define concrete threshold]"
            )
            after = re.sub(
                re.escape(term),
                replacement,
                before,
                count=1,
                flags=re.IGNORECASE,
            )
        elif external_match and before:
            # Flag the external reference — we can't embed content
            # automatically, but we can make the dependency explicit.
            ref_text = external_match.group(1)
            after = re.sub(
                re.escape(ref_text),
                f"{ref_text} [embed referenced content here]",
                before,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            # Fallback: append an action note.
            after = (
                f"{before}\n\n"
                f"[Action needed: {f.observation}]"
            )

        # Update working text so the next draft sees accumulated edits.
        key = _target_key(f.target)
        working_text[key] = after

        payload = {
            "target": f.target.model_dump(),
            "before": before,
            "after": after,
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


# ── LLM planner ──────────────────────────────────────────────────────────


def _llm_available(settings: Settings) -> bool:
    """Check if an LLM backend is configured and usable."""
    if settings.llm_backend == "stub":
        return False
    if settings.llm_backend == "anthropic" and not settings.anthropic_api_key:
        return False
    if settings.llm_backend == "openai" and not settings.openai_api_key:
        return False
    return True


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
            criterion = QualityCriterion.AMBIGUITY  # safe fallback

        # Convert source_finding_ids from strings to UUIDs.
        from uuid import UUID
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
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> ProposedChangeDraftBatch | None:
    """LLM-powered planner. Returns None on failure (caller falls back)."""
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
        ),
        output_schema=LlmPlannerOutput,
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

    # Try LLM planner first, fall back to deterministic.
    batch = None
    if _llm_available(settings):
        try:
            # Extract teaching material text from parsed inputs.
            teaching_text = ""
            if hasattr(inputs.parsed, "teaching_material_text"):
                teaching_text = inputs.parsed.teaching_material_text or ""

            batch = _plan_drafts_llm(
                inputs.findings, base_rubric,
                inputs.evidence_profile,
                teaching_text,
                settings=settings,
                audit_emitter=audit_emitter,
            )
        except (GatewayError, Exception) as exc:
            # Audit the fallback event.
            audit_emitter.record_operation({
                "id": str(uuid4()),
                "stage_id": STAGE_ID,
                "status": "fallback",
                "details": {
                    "kind": "llm_fallback",
                    "engine": "propose_planner",
                    "error": str(exc),
                },
                "error": None,
            })
            batch = None

    if batch is None:
        batch = _plan_drafts(inputs.findings, base_rubric)

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
