"""DR-INT-05 — Validance audit-chain → typed `AuditBundle` harvester.

The harvester is the **sole** producer of the audit-view bundle on Path B
(DR-DAT-07a). It is the only place where Validance vocabulary meets L1
vocabulary; the L4 SPA never sees raw Validance audit-chain rows because
this module's output is what Validance's REST API exposes through
``GET /api/runs/{run_id}/audit_bundle``.

Public surface:

    harvest_audit_bundle(run_id, validance_client) -> AuditBundle

Inputs (read via ``validance_client``):

  1. Per-task captured stderr operation events for every task in the
     workflow run (validated against ``schemas/audit_event.v1.schema.json``,
     DR-OBS-01 / DR-INT-03).
  2. The Validance audit-chain rows for the same run.
  3. The workflow-level start/end timestamps and status.
  4. The ingest task's input declarations (for ``input_provenance``).
  5. The render task's output JSON (for the ``ExplainedRubricFile``-derived
     fields: findings, proposed_changes, evidence_profile).

The harvester is intentionally tolerant: if a task is still running, or if
a stage has not produced any operation events yet, the corresponding
``StageRecord`` / ``OperationSummary`` lists are empty rather than missing,
so a partially-complete run still produces a valid (if sparse)
``AuditBundle``. Validity errors in the captured event stream are logged to
the bundle's ``errors`` list rather than raised — the harvester is a view
builder, not a validator.

Note on the ``validance_client`` parameter: this is the only piece of the
L3 surface that requires a live Validance instance, and it is intentionally
typed as ``Any`` so unit tests can pass a fake without depending on the
``validance-sdk`` import. The protocol it must satisfy is documented in the
``ValidanceRunClient`` Protocol below.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Protocol
from uuid import UUID

from grading_rubric.models.audit import (
    AuditBundle,
    ErrorRecord,
    InputProvenance,
    InputSource,
    InputSourceKind,
    OperationKind,
    OperationStatus,
    OperationSummary,
    StageRecord,
    StageStatus,
)
from grading_rubric.models.deliverable import ExplainedRubricFile
from grading_rubric.models.rubric import EvidenceProfile
from grading_rubric.models.types import OperationId, RunId


# ── ValidanceRunClient Protocol ───────────────────────────────────────────


class ValidanceRunClient(Protocol):
    """Minimal surface the harvester needs from a Validance client.

    A real implementation lives outside this module — typically a thin
    wrapper around ``requests`` calling Validance's REST API. Unit tests
    pass a fake (e.g. an in-memory ``StubRunClient``).
    """

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Return the workflow-run header (status, started_at, ended_at, tasks)."""

    def get_task_stderr_events(self, run_id: str, task_name: str) -> list[dict[str, Any]]:
        """Return the parsed stderr operation events for one task."""

    def get_task_inputs(self, run_id: str, task_name: str) -> dict[str, str]:
        """Return the resolved ``inputs`` mapping for one task (filename → source URI)."""

    def get_task_output(
        self, run_id: str, task_name: str, output_name: str
    ) -> dict[str, Any] | None:
        """Return the parsed JSON of one of a task's outputs (or ``None`` if missing)."""


# ── Harvester ─────────────────────────────────────────────────────────────


_STAGE_TASK_NAMES: tuple[str, ...] = (
    "ingest",
    "parse_inputs",
    "assess",
    "propose",
    "score",
    "render",
)


_STATUS_TO_STAGE_STATUS: dict[str, StageStatus] = {
    "success": StageStatus.SUCCESS,
    "completed": StageStatus.SUCCESS,
    "skipped": StageStatus.SKIPPED,
    "failed": StageStatus.FAILED,
    "error": StageStatus.FAILED,
}


_STATUS_TO_OP_STATUS: dict[str, OperationStatus] = {
    "success": OperationStatus.SUCCESS,
    "completed": OperationStatus.SUCCESS,
    "skipped": OperationStatus.SKIPPED,
    "failed": OperationStatus.FAILED,
    "error": OperationStatus.FAILED,
}


def harvest_audit_bundle(
    run_id: str,
    validance_client: ValidanceRunClient,
) -> AuditBundle:
    """Build a typed `AuditBundle` view of one Validance workflow run.

    See module docstring for the contract. The function is total: any input
    that fails validation is recorded in ``bundle.errors`` rather than
    raised, so a partially-complete or partially-broken run still produces
    a renderable bundle.
    """

    errors: list[ErrorRecord] = []

    run_header = validance_client.get_run(run_id)
    workflow_status = _coerce_workflow_status(run_header.get("status"))
    started_at = _coerce_datetime(run_header.get("started_at")) or datetime.now(UTC)
    ended_at = _coerce_datetime(run_header.get("ended_at")) or started_at

    # Stage records and operation index, derived from per-task stderr events.
    stages: list[StageRecord] = []
    operations: list[OperationSummary] = []
    for task_name in _STAGE_TASK_NAMES:
        try:
            raw_events = validance_client.get_task_stderr_events(run_id, task_name)
        except Exception as exc:  # noqa: BLE001 — view builder, not validator
            errors.append(
                ErrorRecord(
                    code="HARVEST_STDERR_READ_FAILED",
                    message=f"{task_name}: {exc}",
                    stage_id=task_name,
                )
            )
            raw_events = []

        stage_record = _build_stage_record(task_name, raw_events)
        stages.append(stage_record)

        for op in _build_operation_summaries(task_name, raw_events, errors):
            operations.append(op)

    # Input provenance lifted from the ingest task's resolved inputs.
    input_provenance = _build_input_provenance(run_id, validance_client, errors)

    # The render task's output gives us findings + proposed_changes + evidence_profile.
    explained = _read_explained_rubric(run_id, validance_client, errors)
    if explained is not None:
        evidence_profile = explained.evidence_profile
        findings = list(explained.findings)
        proposed_changes = list(explained.proposed_changes)
    else:
        evidence_profile = _empty_evidence_profile()
        findings = []
        proposed_changes = []
    output_file_path: str | None = None

    return AuditBundle(
        run_id=_coerce_run_id(run_id),
        schema_version="1.0.0",
        started_at=started_at,
        ended_at=ended_at,
        status=workflow_status,
        input_provenance=input_provenance,
        evidence_profile=evidence_profile,
        stages=stages,
        operations=operations,
        findings=findings,
        proposed_changes=proposed_changes,
        iteration_history=[],
        output_file_path=output_file_path,
        errors=errors,
    )


# ── Internal helpers ──────────────────────────────────────────────────────


def _coerce_run_id(run_id: str) -> RunId:
    try:
        return UUID(run_id)
    except (TypeError, ValueError):
        # Validance run ids are not always UUIDs in dev — fall back to a
        # deterministic UUID5 in the URL namespace so the AuditBundle still
        # validates under Pydantic strict mode.
        from uuid import NAMESPACE_URL, uuid5

        return uuid5(NAMESPACE_URL, f"validance://run/{run_id}")


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _coerce_workflow_status(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"success", "completed", "succeeded"}:
        return "success"
    if text in {"failed", "error"}:
        return "failed"
    return "partial"


def _build_stage_record(task_name: str, events: list[dict[str, Any]]) -> StageRecord:
    """Build one StageRecord from the captured stderr stream of one task."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    status = StageStatus.SUCCESS
    operation_ids: list[OperationId] = []

    for event in events:
        kind = str(event.get("event", ""))
        if kind == "stage.start":
            started_at = _coerce_datetime(event.get("at")) or started_at
        elif kind == "stage.end":
            ended_at = _coerce_datetime(event.get("at")) or ended_at
            status = _STATUS_TO_STAGE_STATUS.get(
                str(event.get("status", "success")), StageStatus.SUCCESS
            )
        elif kind == "operation":
            op_id = event.get("operation_id") or event.get("id")
            if op_id is not None:
                try:
                    operation_ids.append(UUID(str(op_id)))
                except ValueError:
                    pass

    fallback = datetime.now(UTC)
    return StageRecord(
        stage_id=task_name,
        started_at=started_at or fallback,
        ended_at=ended_at or started_at or fallback,
        status=status,
        operation_ids=operation_ids,
    )


def _build_operation_summaries(
    stage_id: str,
    events: list[dict[str, Any]],
    errors: list[ErrorRecord],
) -> Iterable[OperationSummary]:
    """Translate the operation events of one task into OperationSummary index entries."""

    for event in events:
        if str(event.get("event", "")) != "operation":
            continue
        try:
            yield _operation_summary_from_event(stage_id, event)
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(
                ErrorRecord(
                    code="HARVEST_OPERATION_EVENT_INVALID",
                    message=f"{stage_id}: {exc}",
                    stage_id=stage_id,
                )
            )


def _operation_summary_from_event(
    stage_id: str, event: dict[str, Any]
) -> OperationSummary:
    op_id = UUID(str(event["operation_id"]))
    started_at = _coerce_datetime(event.get("started_at")) or datetime.now(UTC)
    ended_at = _coerce_datetime(event.get("ended_at")) or started_at
    status = _STATUS_TO_OP_STATUS.get(
        str(event.get("status", "success")), OperationStatus.SUCCESS
    )
    kind_value = str(event.get("kind", "deterministic"))
    try:
        kind = OperationKind(kind_value)
    except ValueError:
        kind = OperationKind.DETERMINISTIC

    error_payload = event.get("error")
    error_record: ErrorRecord | None = None
    if isinstance(error_payload, dict):
        error_record = ErrorRecord(
            code=str(error_payload.get("code", "UNKNOWN")),
            message=str(error_payload.get("message", "")),
            stage_id=stage_id,
            operation_id=op_id,
        )

    return OperationSummary(
        id=op_id,
        stage_id=stage_id,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        attempt=int(event.get("attempt", 1)),
        retry_of=_optional_uuid(event.get("retry_of")),
        inputs_digest=str(event.get("inputs_digest", "")),
        outputs_digest=event.get("outputs_digest"),
        details_kind=kind,
        details_path=f"operations/{op_id}.json",
        error=error_record,
    )


def _optional_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _build_input_provenance(
    run_id: str,
    client: ValidanceRunClient,
    errors: list[ErrorRecord],
) -> InputProvenance:
    """Read the ingest task's input declarations and lift them into InputProvenance.

    The Validance task model exposes ``inputs`` as a mapping of
    ``filename → source URI``; we don't have a typed view of which file
    plays which role here, so we read the ingest task's *output* JSON
    (which is itself an ``IngestOutputs`` carrying ``input_provenance`` per
    DR-IO-07) when available, and fall back to a single empty placeholder
    when not.
    """

    try:
        ingest_output = client.get_task_output(run_id, "ingest", "ingest_outputs")
    except Exception as exc:  # noqa: BLE001
        errors.append(
            ErrorRecord(
                code="HARVEST_INGEST_OUTPUT_READ_FAILED",
                message=str(exc),
                stage_id="ingest",
            )
        )
        ingest_output = None

    if ingest_output is not None and "input_provenance" in ingest_output:
        try:
            return InputProvenance.model_validate(ingest_output["input_provenance"])
        except Exception as exc:  # noqa: BLE001
            errors.append(
                ErrorRecord(
                    code="HARVEST_INPUT_PROVENANCE_INVALID",
                    message=str(exc),
                    stage_id="ingest",
                )
            )

    return InputProvenance(
        exam_question=InputSource(
            kind=InputSourceKind.FILE,
            path=None,
            marker="<unavailable>",
            hash="",
        )
    )


def _read_explained_rubric(
    run_id: str,
    client: ValidanceRunClient,
    errors: list[ErrorRecord],
) -> ExplainedRubricFile | None:
    try:
        raw = client.get_task_output(run_id, "render", "explained_rubric")
    except Exception as exc:  # noqa: BLE001
        errors.append(
            ErrorRecord(
                code="HARVEST_RENDER_OUTPUT_READ_FAILED",
                message=str(exc),
                stage_id="render",
            )
        )
        return None

    if raw is None:
        return None

    try:
        return ExplainedRubricFile.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        errors.append(
            ErrorRecord(
                code="HARVEST_EXPLAINED_RUBRIC_INVALID",
                message=str(exc),
                stage_id="render",
            )
        )
        return None


def _empty_evidence_profile() -> EvidenceProfile:
    """Build a minimal `EvidenceProfile` for runs with no usable render output."""

    return EvidenceProfile(
        starting_rubric_present=False,
        exam_question_present=False,
        teaching_material_present=False,
        student_copies_present=False,
    )


__all__ = [
    "ValidanceRunClient",
    "harvest_audit_bundle",
]
