"""§ 3.4 System integration tests — Validance running (dev instance).

IT-SYS-01 through IT-SYS-08.  Exercises the grading_rubric workflow through
the live Validance dev instance REST API.  Requires:

  - Validance dev API at http://localhost:8001  (healthy)
  - ``grading_rubric.assess_and_improve`` workflow registered
  - ``grading-rubric:latest`` Docker image available locally
  - Test fixture files at ``/project/data/grading_rubric_fixtures/``

These tests are **not** run in the standard ``pytest`` suite — they require
a running Validance instance and Docker.  Mark them with ``@pytest.mark.system``
and run explicitly::

    pytest tests/integration/test_system_integration.py -m system -v

Traces to: DR-INT-02 (workflow registration), DR-INT-05 (audit bundle),
           DR-INT-06 (status polling), SR-PRF-02 (pipeline completes).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
import requests

# ── Configuration ──────────────────────────────────────────────────────────

VALIDANCE_BASE = "http://localhost:8001"
WORKFLOW_NAME = "grading_rubric.assess_and_improve"
FIXTURES_DIR = Path("/home/Wik-dev/repos/validance-workflow/data/grading_rubric_fixtures")

# Maximum wait for a full pipeline run (offline / stub — no LLM calls).
MAX_WAIT_SECONDS = 60
POLL_INTERVAL = 2


# ── Helpers ────────────────────────────────────────────────────────────────


def _is_validance_healthy() -> bool:
    try:
        r = requests.get(f"{VALIDANCE_BASE}/api/health", timeout=5)
        return r.ok and r.json().get("status") == "healthy"
    except Exception:
        return False


def _unique_session_hash() -> str:
    """Generate a unique session hash to bypass duplicate trigger detection."""
    return hashlib.sha256(f"test:{time.monotonic_ns()}".encode()).hexdigest()[:16]


def _trigger_workflow(
    workflow_name: str,
    parameters: dict | None = None,
) -> dict:
    """POST /api/workflows/{name}/trigger and return the response dict."""
    params = dict(parameters or {})
    # Add a unique nonce to bypass Validance's duplicate trigger detection
    # (keyed on workflow_name + parameters within a 10s window).
    params["_test_nonce"] = _unique_session_hash()
    r = requests.post(
        f"{VALIDANCE_BASE}/api/workflows/{workflow_name}/trigger",
        json={
            "parameters": params,
            "session_hash": _unique_session_hash(),
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _poll_until_terminal(
    workflow_name: str,
    *,
    max_wait: int = MAX_WAIT_SECONDS,
) -> dict:
    """Poll workflow status until it reaches a terminal state."""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        r = requests.get(
            f"{VALIDANCE_BASE}/api/workflows/{workflow_name}/status",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "").lower()
        if status in ("success", "failed", "completed"):
            return data
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Workflow {workflow_name} did not complete within {max_wait}s")


def _get_workflow_files(workflow_hash: str) -> list[dict]:
    r = requests.get(f"{VALIDANCE_BASE}/api/files/{workflow_hash}", timeout=10)
    r.raise_for_status()
    return r.json().get("files", [])


def _download_file(workflow_hash: str, task_name: str, file_name: str) -> dict:
    r = requests.get(
        f"{VALIDANCE_BASE}/api/files/{workflow_hash}/download",
        params={"task_name": task_name, "file_name": file_name},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ── Fixtures ───────────────────────────────────────────────────────────────


skip_if_no_validance = pytest.mark.skipif(
    not _is_validance_healthy(),
    reason="Validance dev instance not available at localhost:8001",
)

pytestmark = [pytest.mark.system, skip_if_no_validance]


@pytest.fixture(scope="module")
def successful_run() -> dict:
    """Trigger the assess_and_improve workflow and wait for completion.

    This fixture is module-scoped so the workflow runs once and all tests
    in this module share the result.
    """
    trigger = _trigger_workflow(
        WORKFLOW_NAME,
        parameters={
            "ingest_inputs_path": str(FIXTURES_DIR / "ingest_inputs.json"),
        },
    )
    assert trigger["status"] == "triggered"
    result = _poll_until_terminal(WORKFLOW_NAME)
    result["workflow_hash"] = trigger["workflow_hash"]
    return result


# ── IT-SYS-01: Workflow registration ──────────────────────────────────────


class TestWorkflowRegistration:
    """IT-SYS-01: The grading_rubric workflow is registered."""

    def test_assess_and_improve_registered(self) -> None:
        r = requests.get(f"{VALIDANCE_BASE}/api/workflows", timeout=10)
        r.raise_for_status()
        names = [w["name"] for w in r.json().get("workflows", [])]
        assert WORKFLOW_NAME in names


# ── IT-SYS-02: Workflow trigger ───────────────────────────────────────────


class TestWorkflowTrigger:
    """IT-SYS-02: Trigger returns workflow_hash and session_hash."""

    def test_trigger_returns_expected_fields(self) -> None:
        trigger = _trigger_workflow(
            WORKFLOW_NAME,
            parameters={
                "ingest_inputs_path": str(FIXTURES_DIR / "ingest_inputs.json"),
            },
        )
        assert "workflow_hash" in trigger
        assert "session_hash" in trigger
        assert trigger["status"] == "triggered"
        # Wait for it to finish to avoid polluting later tests
        _poll_until_terminal(WORKFLOW_NAME)


# ── IT-SYS-03: Tasks execute in sequence ──────────────────────────────────


class TestTaskSequence:
    """IT-SYS-03: All six pipeline stages execute in order."""

    def test_all_six_tasks_succeed(self, successful_run: dict) -> None:
        tasks = successful_run.get("tasks", [])
        task_names = [t["task_name"] for t in tasks]
        assert task_names == [
            "ingest",
            "parse_inputs",
            "assess",
            "propose",
            "score",
            "render",
        ]
        for t in tasks:
            assert t["status"] == "SUCCESS", (
                f"Task {t['task_name']} failed: {t.get('error_message')}"
            )

    def test_workflow_completes_successfully(self, successful_run: dict) -> None:
        assert successful_run["status"] == "success"


# ── IT-SYS-04: Status polling ─────────────────────────────────────────────


class TestStatusPolling:
    """IT-SYS-04: DR-INT-06 status endpoint returns valid run state."""

    def test_status_endpoint_returns_tasks(self, successful_run: dict) -> None:
        r = requests.get(
            f"{VALIDANCE_BASE}/api/workflows/{WORKFLOW_NAME}/status",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        assert "tasks" in data
        assert "status" in data
        assert data["workflow_name"] == WORKFLOW_NAME


# ── IT-SYS-05: Output file retrieval ─────────────────────────────────────


class TestOutputRetrieval:
    """IT-SYS-05: The rendered ExplainedRubricFile is downloadable."""

    def test_explained_rubric_downloadable(self, successful_run: dict) -> None:
        wh = successful_run["workflow_hash"]
        erf = _download_file(wh, "render", "explained_rubric.json")
        assert erf["schema_version"] == "1.0.0"
        assert erf["improved_rubric"]["title"] == "Bad Actors Strategy Assessment"
        assert len(erf["quality_scores"]) == 3

    def test_intermediate_outputs_available(self, successful_run: dict) -> None:
        wh = successful_run["workflow_hash"]
        files = _get_workflow_files(wh)
        output_files = [f for f in files if f.get("file_type") == "output"]
        output_names = {f["file_name"] for f in output_files}
        expected = {
            "ingest_outputs.json",
            "parsed_inputs.json",
            "assess_outputs.json",
            "propose_outputs.json",
            "score_outputs.json",
            "explained_rubric.json",
        }
        assert expected.issubset(output_names), (
            f"Missing outputs: {expected - output_names}"
        )


# ── IT-SYS-06: Audit events in task logs ─────────────────────────────────


class TestAuditEvents:
    """IT-SYS-06: Each task emits stage.start / stage.end audit events."""

    def test_ingest_emits_stage_events(self, successful_run: dict) -> None:
        wh = successful_run["workflow_hash"]
        files = _get_workflow_files(wh)
        ingest_logs = [
            f for f in files
            if f.get("task_name") == "ingest" and f["file_name"] == "stdout.log"
        ]
        assert len(ingest_logs) >= 1

        # Download and parse the log — each line is a JSON audit event
        r = requests.get(
            f"{VALIDANCE_BASE}/api/files/{wh}/download",
            params={"task_name": "ingest", "file_name": "stdout.log"},
            timeout=10,
        )
        r.raise_for_status()
        content = r.text if hasattr(r, "text") else r.content.decode()

        events = []
        for line in content.strip().splitlines():
            line = line.strip()
            if line.startswith("{"):
                events.append(json.loads(line))

        event_kinds = [e.get("event_kind") for e in events]
        assert "stage.start" in event_kinds
        assert "stage.end" in event_kinds


# ── IT-SYS-07: Run listing ───────────────────────────────────────────────


class TestRunListing:
    """IT-SYS-07: The completed run appears in the run listing endpoint."""

    def test_run_appears_in_listing(self, successful_run: dict) -> None:
        wh = successful_run["workflow_hash"]
        r = requests.get(
            f"{VALIDANCE_BASE}/api/runs",
            params={"workflow_name": WORKFLOW_NAME, "limit": 10},
            timeout=10,
        )
        r.raise_for_status()
        runs = r.json().get("runs", [])
        hashes = [run["workflow_hash"] for run in runs]
        assert wh in hashes


# ── IT-SYS-08: Error handling — invalid parameters ───────────────────────


class TestErrorHandling:
    """IT-SYS-08: Workflow handles missing/invalid input gracefully."""

    def test_missing_input_file_fails_task(self) -> None:
        """Trigger with a non-existent input file path → ingest task fails."""
        trigger = _trigger_workflow(
            WORKFLOW_NAME,
            parameters={
                "ingest_inputs_path": "/nonexistent/path/inputs.json",
            },
        )
        assert trigger["status"] == "triggered"
        result = _poll_until_terminal(WORKFLOW_NAME)
        # The workflow should complete (Validance doesn't crash) but
        # the ingest task should fail.
        tasks = result.get("tasks", [])
        ingest = next((t for t in tasks if t["task_name"] == "ingest"), None)
        assert ingest is not None
        assert ingest["status"] == "FAILED"
