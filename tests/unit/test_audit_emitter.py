"""Unit tests — DR-OBS-01 audit-event emitter.

The `JsonLineEmitter` and `NullEmitter` are the producer side of the
structured audit-event stream. Tests verify event structure, ordering,
and JSON-line serialization.
"""

from __future__ import annotations

import io
import json

from grading_rubric.audit.emitter import JsonLineEmitter, NullEmitter


class TestJsonLineEmitter:
    """DR-OBS-01: JsonLineEmitter writes structured JSON lines."""

    def test_stage_start_emits_one_event(self) -> None:
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        emitter.stage_start("assess")
        assert len(emitter.events) == 1
        event = emitter.events[0]
        assert event.event_kind == "stage.start"
        assert event.stage_id == "assess"

    def test_stage_end_records_status(self) -> None:
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        emitter.stage_end("assess", status="success")
        event = emitter.events[0]
        assert event.event_kind == "stage.end"
        assert event.payload["status"] == "success"

    def test_stage_end_with_error(self) -> None:
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        err = {"code": "TIMEOUT", "message": "LLM call timed out"}
        emitter.stage_end("assess", status="failed", error=err)
        event = emitter.events[0]
        assert event.payload["error"]["code"] == "TIMEOUT"

    def test_record_operation(self) -> None:
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        payload = {"stage_id": "assess", "kind": "llm_call", "model": "stub"}
        emitter.record_operation(payload)
        event = emitter.events[0]
        assert event.event_kind == "operation"
        assert event.stage_id == "assess"
        assert event.payload["model"] == "stub"

    def test_json_line_output(self) -> None:
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        emitter.stage_start("ingest")
        lines = sink.getvalue().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event_kind"] == "stage.start"
        assert "event_id" in parsed
        assert "emitted_at" in parsed

    def test_multiple_events_ordered(self) -> None:
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        emitter.stage_start("assess")
        emitter.record_operation({"stage_id": "assess", "kind": "llm_call"})
        emitter.stage_end("assess", status="success")
        assert len(emitter.events) == 3
        assert emitter.events[0].event_kind == "stage.start"
        assert emitter.events[1].event_kind == "operation"
        assert emitter.events[2].event_kind == "stage.end"
        # Monotonic timestamp ordering.
        for i in range(1, len(emitter.events)):
            assert emitter.events[i].emitted_at >= emitter.events[i - 1].emitted_at

    def test_event_ids_are_unique(self) -> None:
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        emitter.stage_start("a")
        emitter.stage_start("b")
        ids = {e.event_id for e in emitter.events}
        assert len(ids) == 2


class TestNullEmitter:
    """DR-ARC-11: NullEmitter discards output but still collects events."""

    def test_collects_events(self) -> None:
        emitter = NullEmitter()
        emitter.stage_start("assess")
        emitter.record_operation({"stage_id": "assess"})
        emitter.stage_end("assess", status="success")
        assert len(emitter.events) == 3

    def test_no_side_effects(self) -> None:
        emitter = NullEmitter()
        emitter.stage_start("test")
        # NullEmitter has no sink — the test is that it doesn't raise.
