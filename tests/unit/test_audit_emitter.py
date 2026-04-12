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


# ── UT-AUD-03: LLM call event logging ────────────────────────────────────


class TestLlmCallEventLogging:
    """DR-LLM-08, DR-LLM-11: LLM call events record purpose, prompt ID, outcome."""

    def test_llm_call_event_records_required_fields(self) -> None:
        """UT-AUD-03: record_operation with an LLM call payload captures
        purpose, prompt_id, and outcome."""
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        payload = {
            "stage_id": "assess",
            "kind": "llm_call",
            "purpose": "ambiguity_panel_grading",
            "prompt_id": "ambiguity.panel.v1",
            "model": "claude-sonnet-4-20250514",
            "outcome": "success",
            "tokens_in": 1200,
            "tokens_out": 350,
        }
        emitter.record_operation(payload)

        assert len(emitter.events) == 1
        event = emitter.events[0]
        assert event.event_kind == "operation"
        assert event.stage_id == "assess"
        assert event.payload["kind"] == "llm_call"
        assert event.payload["purpose"] == "ambiguity_panel_grading"
        assert event.payload["prompt_id"] == "ambiguity.panel.v1"
        assert event.payload["outcome"] == "success"
        assert event.payload["tokens_in"] == 1200
        assert event.payload["tokens_out"] == 350

    def test_llm_call_event_serializes_to_jsonl(self) -> None:
        """The LLM call event appears as a valid JSON line in the sink."""
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        emitter.record_operation({
            "stage_id": "propose",
            "kind": "llm_call",
            "purpose": "planner",
            "prompt_id": "propose.planner.v1",
            "outcome": "success",
        })
        line = sink.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["event_kind"] == "operation"
        assert parsed["payload"]["purpose"] == "planner"
        assert parsed["payload"]["prompt_id"] == "propose.planner.v1"

    def test_llm_call_failure_outcome_recorded(self) -> None:
        """A failed LLM call records the failure outcome."""
        sink = io.StringIO()
        emitter = JsonLineEmitter(sink=sink)
        emitter.record_operation({
            "stage_id": "assess",
            "kind": "llm_call",
            "purpose": "discrimination_panel_grading",
            "prompt_id": "discrimination.panel.v1",
            "outcome": "error",
            "error": {"code": "RATE_LIMIT", "message": "429 Too Many Requests"},
        })
        event = emitter.events[0]
        assert event.payload["outcome"] == "error"
        assert event.payload["error"]["code"] == "RATE_LIMIT"
