"""DR-INT-04 — `ProposedChange` ↔ Validance proposal-payload mapping.

A pure module: no I/O, no SDK calls, no Validance imports. The forward
direction (`proposed_changes_to_payload`) translates the L1 discriminated
union of § 4.6 to a JSON-serialisable shape that fits Validance's
``proposal_payload`` field on ``POST /api/proposals``. The inverse direction
(`apply_approval_resolution`) takes Validance's per-change accept/reject
decisions and writes them back onto the L1 ``ProposedChange.teacher_decision``
field so the next ``render`` invocation reflects the teacher's choices.

The forward payload carries enough context for Validance's reviewer UI (or
the L4 SPA, which calls the same REST API) to render exactly the same view
the L4 SPA renders from the L1 model: criterion tag, target path, change
kind, before/after snippet, rationale, confidence. We deliberately do **not**
serialise the full ``RubricCriterion`` / ``RubricLevel`` payloads onto the
proposal — the SPA already has the full ``Rubric`` snapshot and looks the
nodes up by id.

Unit-testable without a Validance instance.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from grading_rubric.models.proposed_change import (
    AddNodeChange,
    ProposedChange,
    RemoveNodeChange,
    ReorderNodesChange,
    ReplaceFieldChange,
    TeacherDecision,
    UpdatePointsChange,
)


# ── Forward direction: L1 → Validance payload ─────────────────────────────


def proposed_change_to_payload(change: ProposedChange) -> dict[str, Any]:
    """Translate one ``ProposedChange`` into a JSON-safe dict.

    The shape is intentionally flat and operation-tagged so a generic
    review UI can render every variant without special-casing on Pydantic
    model classes:

        {
          "id": "<uuid>",
          "operation": "REPLACE_FIELD" | "UPDATE_POINTS" | ...,
          "primary_criterion": "ambiguity" | "applicability" | "discrimination_power",
          "rationale": "<human-readable reason>",
          "confidence": {"score": 0.42, "level": "medium", ...},
          "source_findings": ["<finding-uuid>", ...],
          "target": {...},          # operation-specific
          "before": ...,            # operation-specific (optional)
          "after": ...,             # operation-specific (optional)
        }
    """

    payload: dict[str, Any] = {
        "id": str(change.id),
        "operation": change.operation,
        "primary_criterion": change.primary_criterion.value,
        "rationale": change.rationale,
        "confidence": change.confidence.model_dump(mode="json"),
        "source_findings": [str(fid) for fid in change.source_findings],
    }

    if isinstance(change, ReplaceFieldChange):
        payload["target"] = change.target.model_dump(mode="json")
        payload["before"] = change.before
        payload["after"] = change.after
    elif isinstance(change, UpdatePointsChange):
        payload["target"] = change.target.model_dump(mode="json")
        payload["before"] = change.before
        payload["after"] = change.after
    elif isinstance(change, AddNodeChange):
        payload["parent_path"] = [str(cid) for cid in change.parent_path]
        payload["insert_index"] = change.insert_index
        payload["node_kind"] = change.node_kind.value
        payload["node"] = change.node.model_dump(mode="json")
    elif isinstance(change, RemoveNodeChange):
        payload["criterion_path"] = [str(cid) for cid in change.criterion_path]
        payload["level_id"] = (
            str(change.level_id) if change.level_id is not None else None
        )
        payload["node_kind"] = change.node_kind.value
        payload["removed_snapshot"] = change.removed_snapshot.model_dump(mode="json")
    elif isinstance(change, ReorderNodesChange):
        payload["parent_path"] = [str(cid) for cid in change.parent_path]
        payload["node_kind"] = change.node_kind.value
        payload["before_order"] = [str(uid) for uid in change.before_order]
        payload["after_order"] = [str(uid) for uid in change.after_order]
    else:  # pragma: no cover — discriminated union is exhaustive
        raise TypeError(f"unknown ProposedChange variant: {type(change).__name__}")

    return payload


def proposed_changes_to_payload(
    changes: list[ProposedChange],
) -> dict[str, Any]:
    """Build the full ``proposal_payload`` for the approval gate.

    The wrapping object exists so the SPA can render a stable header
    (``"<N> proposed changes"``) above the per-change list and so the
    Validance approval-resolution endpoint has a single document to act on.
    """

    return {
        "kind": "grading_rubric.proposed_changes",
        "version": "1",
        "count": len(changes),
        "changes": [proposed_change_to_payload(c) for c in changes],
    }


# ── Inverse direction: Validance approval → L1 ProposedChange.teacher_decision


_DECISION_MAP: dict[str, TeacherDecision] = {
    "accepted": TeacherDecision.ACCEPTED,
    "accept": TeacherDecision.ACCEPTED,
    "approved": TeacherDecision.ACCEPTED,
    "rejected": TeacherDecision.REJECTED,
    "reject": TeacherDecision.REJECTED,
    "denied": TeacherDecision.REJECTED,
}


def _normalise_decision(value: str) -> TeacherDecision:
    key = value.strip().lower()
    if key not in _DECISION_MAP:
        raise ValueError(
            f"unknown teacher decision {value!r}; "
            f"expected one of {sorted(set(_DECISION_MAP))}"
        )
    return _DECISION_MAP[key]


def apply_approval_resolution(
    changes: list[ProposedChange],
    resolution: dict[str, Any],
) -> list[ProposedChange]:
    """Write teacher decisions from a Validance approval payload back onto changes.

    ``resolution`` is the decoded body of Validance's approval-resolution
    callback. We accept either of two shapes so the mapping is robust to
    minor schema drift on the Validance side:

      ``{"decisions": [{"id": "<uuid>", "decision": "accepted"}, ...]}``
      ``{"<uuid>": "accepted", ...}``

    Any change whose id does not appear in the resolution keeps its prior
    ``teacher_decision`` (typically ``None`` or ``PENDING``). Returned list
    has the same order as the input.
    """

    decisions_by_id: dict[UUID, TeacherDecision] = {}

    raw_decisions = resolution.get("decisions")
    if isinstance(raw_decisions, list):
        for entry in raw_decisions:
            if not isinstance(entry, dict):
                continue
            change_id = entry.get("id")
            decision = entry.get("decision")
            if change_id is None or decision is None:
                continue
            try:
                decisions_by_id[UUID(str(change_id))] = _normalise_decision(
                    str(decision)
                )
            except ValueError:
                continue
    else:
        for key, value in resolution.items():
            if key in {"kind", "version", "count", "changes", "decisions"}:
                continue
            try:
                decisions_by_id[UUID(str(key))] = _normalise_decision(str(value))
            except ValueError:
                continue

    updated: list[ProposedChange] = []
    for change in changes:
        decision = decisions_by_id.get(change.id)
        if decision is None:
            updated.append(change)
        else:
            updated.append(change.model_copy(update={"teacher_decision": decision}))
    return updated
