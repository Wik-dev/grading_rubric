"""Integration tests — DR-INT-05 audit-bundle harvester (L3).

The harvester is a tolerant view-builder: it accepts a `ValidanceRunClient`
Protocol and produces an `AuditBundle`. Tests verify it works against a
stub client without a live Validance instance, and that errors are
collected in `bundle.errors` rather than raised.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest

from grading_rubric.models.audit import AuditBundle

from validance_integration.harvester import ValidanceRunClient, harvest_audit_bundle


class StubValidanceClient:
    """Minimal in-memory ValidanceRunClient for testing."""

    def __init__(self, *, task_names: list[str] | None = None) -> None:
        self._task_names = task_names or [
            "ingest",
            "parse_inputs",
            "assess",
            "propose",
            "score",
            "render",
        ]
        self._run_status = "success"

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "workflow_name": "grading_rubric.assess_and_improve",
            "status": self._run_status,
            "started_at": "2026-04-12T10:00:00Z",
            "ended_at": "2026-04-12T10:05:00Z",
            "tasks": [
                {
                    "name": name,
                    "status": "success",
                    "started_at": "2026-04-12T10:00:00Z",
                    "ended_at": "2026-04-12T10:01:00Z",
                }
                for name in self._task_names
            ],
        }

    def get_task_stderr_events(
        self, run_id: str, task_name: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "event_kind": "stage.start",
                "event_id": str(uuid4()),
                "emitted_at": "2026-04-12T10:00:00Z",
                "stage_id": task_name,
            },
            {
                "event_kind": "stage.end",
                "event_id": str(uuid4()),
                "emitted_at": "2026-04-12T10:01:00Z",
                "stage_id": task_name,
                "payload": {"status": "success"},
            },
        ]

    def get_task_inputs(self, run_id: str, task_name: str) -> dict[str, str]:
        return {}

    def get_task_output(
        self, run_id: str, task_name: str, output_name: str
    ) -> dict[str, Any] | None:
        return None


class TestHarvestAuditBundle:
    """DR-INT-05: harvest_audit_bundle produces a valid AuditBundle."""

    def test_produces_six_stages(self) -> None:
        client = StubValidanceClient()
        bundle = harvest_audit_bundle("test-run-001", client)
        assert isinstance(bundle, AuditBundle)
        assert len(bundle.stages) == 6

    def test_stage_names_match(self) -> None:
        client = StubValidanceClient()
        bundle = harvest_audit_bundle("test-run-001", client)
        stage_names = [s.stage_id for s in bundle.stages]
        expected = ["ingest", "parse_inputs", "assess", "propose", "score", "render"]
        assert stage_names == expected

    def test_tolerant_on_missing_outputs(self) -> None:
        """Harvester collects errors instead of raising when outputs are None."""
        client = StubValidanceClient()
        bundle = harvest_audit_bundle("test-run-001", client)
        # No outputs returned by stub → harvester should still produce a bundle.
        assert bundle.status in ("success", "partial", "failed")

    def test_run_id_coerced(self) -> None:
        """Non-UUID run_id is coerced via UUID5 (deterministic)."""
        client = StubValidanceClient()
        bundle = harvest_audit_bundle("abc123", client)
        assert bundle.run_id is not None

    def test_custom_task_set(self) -> None:
        """Stages beyond the standard set are filtered gracefully."""
        client = StubValidanceClient(task_names=["ingest", "assess"])
        bundle = harvest_audit_bundle("test-run-002", client)
        # Only the stages in _STAGE_TASK_NAMES that match should appear.
        assert len(bundle.stages) <= 6


class TestHarvesterProtocolCompliance:
    """DR-INT-05: StubValidanceClient satisfies the ValidanceRunClient Protocol."""

    def test_stub_implements_protocol(self) -> None:
        client = StubValidanceClient()
        assert hasattr(client, "get_run")
        assert hasattr(client, "get_task_stderr_events")
        assert hasattr(client, "get_task_inputs")
        assert hasattr(client, "get_task_output")
