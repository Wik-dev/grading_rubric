"""DR-OBS-01 / DR-LLM-11 audit-event emitter.

The `audit` sub-package is a passive in-memory subscriber and the **producer**
of structured operation events. It is **not** the writer of any cross-run
audit chain (DR-ARC-06). Stages and the gateway emit lifecycle and operation
events through the injected `AuditEmitter`. The emitted events are written as
structured-JSON lines to a sink (default: `stderr`); on Path B the L3 harvester
parses the same stream and folds the events into the typed `AuditBundle` view.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import IO, Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel

from grading_rubric.audit.hashing import _canonical


class AuditEvent(BaseModel):
    """One line on the audit-event wire (the `audit_event.v1.schema.json` shape)."""

    event_id: UUID
    event_kind: str  # "stage.start" | "stage.end" | "operation"
    emitted_at: datetime
    stage_id: str | None = None
    payload: dict[str, Any] = {}


class AuditEmitter(Protocol):
    """The interface stages and the gateway use to emit lifecycle events."""

    def stage_start(self, stage_id: str) -> None: ...

    def stage_end(
        self, stage_id: str, status: str, error: dict[str, Any] | None = None
    ) -> None: ...

    def record_operation(self, payload: dict[str, Any]) -> None: ...


class JsonLineEmitter:
    """Default `AuditEmitter` implementation: writes JSON lines to a sink.

    Holds the events in-memory too so single-stage CLI invocations and tests
    can inspect them after the stage has run. The collected events list is
    *also* the producer side of the audit-event stream the L3 harvester reads.
    """

    def __init__(self, sink: IO[str] | None = None) -> None:
        self._sink: IO[str] = sink if sink is not None else sys.stderr
        self.events: list[AuditEvent] = []

    # ── Public surface ─────────────────────────────────────────────────────
    def stage_start(self, stage_id: str) -> None:
        self._emit(
            AuditEvent(
                event_id=uuid4(),
                event_kind="stage.start",
                emitted_at=datetime.now(UTC),
                stage_id=stage_id,
                payload={},
            )
        )

    def stage_end(
        self, stage_id: str, status: str, error: dict[str, Any] | None = None
    ) -> None:
        self._emit(
            AuditEvent(
                event_id=uuid4(),
                event_kind="stage.end",
                emitted_at=datetime.now(UTC),
                stage_id=stage_id,
                payload={"status": status, "error": error},
            )
        )

    def record_operation(self, payload: dict[str, Any]) -> None:
        self._emit(
            AuditEvent(
                event_id=uuid4(),
                event_kind="operation",
                emitted_at=datetime.now(UTC),
                stage_id=payload.get("stage_id"),
                payload=payload,
            )
        )

    # ── Internal ───────────────────────────────────────────────────────────
    def _emit(self, event: AuditEvent) -> None:
        self.events.append(event)
        line = json.dumps(_canonical(event.model_dump()), ensure_ascii=False)
        self._sink.write(line + "\n")
        try:
            self._sink.flush()
        except (AttributeError, ValueError):
            pass


class NullEmitter:
    """Discards all events. Useful for hermetic stage tests."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def stage_start(self, stage_id: str) -> None:
        self.events.append(
            AuditEvent(
                event_id=uuid4(),
                event_kind="stage.start",
                emitted_at=datetime.now(UTC),
                stage_id=stage_id,
            )
        )

    def stage_end(
        self, stage_id: str, status: str, error: dict[str, Any] | None = None
    ) -> None:
        self.events.append(
            AuditEvent(
                event_id=uuid4(),
                event_kind="stage.end",
                emitted_at=datetime.now(UTC),
                stage_id=stage_id,
                payload={"status": status, "error": error},
            )
        )

    def record_operation(self, payload: dict[str, Any]) -> None:
        self.events.append(
            AuditEvent(
                event_id=uuid4(),
                event_kind="operation",
                emitted_at=datetime.now(UTC),
                stage_id=payload.get("stage_id"),
                payload=payload,
            )
        )
