"""DR-INT-07 — idempotent workflow registration script.

Reads the two workflow definitions from `validance/workflow.py`, serialises
each via the SDK's ``Workflow.to_dict()``, and POSTs them to the Validance
instance whose base URL is read from the ``VALIDANCE_BASE_URL`` environment
variable. Validance's ``POST /api/workflows`` endpoint is itself idempotent
on the workflow's content hash, so running ``make register`` twice produces
no duplicate registrations — the second call updates the existing record in
place.

Exit codes:

  0  — both workflows registered successfully
  1  — VALIDANCE_BASE_URL is unset, the instance is unreachable, or the
       Validance API returned a non-2xx for any registration

Usage:

    VALIDANCE_BASE_URL=http://localhost:8001 python validance/register.py

This script is the **sole** caller of ``requests`` in the L3 directory; the
rest of the package is pure (no I/O, no network).
"""

from __future__ import annotations

import os
import sys
from typing import Any

import requests

from validance.workflow import WORKFLOW_DESCRIPTIONS, WORKFLOWS


def _workflow_payload(wf, description: str) -> dict[str, Any]:
    """Translate an SDK Workflow into the JSON shape `POST /api/workflows` expects.

    Mirrors `mining_optimization/scripts/register_validance_workflows.py`'s
    ``workflow_to_api_json`` so the payload is interoperable with any
    Validance instance that already speaks that shape.
    """

    tasks: list[dict[str, Any]] = []
    for task in wf.tasks.values():
        entry: dict[str, Any] = {
            "name": task.name,
            "command": task.command,
            "docker_image": task.docker_image,
            "inputs": dict(task.inputs),
            "output_files": dict(task.output_files),
            "output_vars": dict(task.output_vars),
            "depends_on": list(task.depends_on),
            "environment": dict(task.environment) if task.environment else {},
            "timeout": task.timeout,
        }
        if getattr(task, "gate", "auto-approve") != "auto-approve":
            entry["gate"] = task.gate
        if getattr(task, "secret_refs", None):
            entry["secret_refs"] = list(task.secret_refs)
        if getattr(task, "persistent", False):
            entry["persistent"] = True
        tasks.append(entry)

    return {
        "name": wf.name,
        "description": description,
        "tasks": tasks,
        "version": "1.0",
    }


def _register_one(api_url: str, key: str) -> None:
    factory = WORKFLOWS[key]
    description = WORKFLOW_DESCRIPTIONS[key]
    wf = factory()
    payload = _workflow_payload(wf, description)

    response = requests.post(f"{api_url}/api/workflows", json=payload, timeout=30)
    response.raise_for_status()
    body = response.json()
    action = body.get("action", "registered")
    task_count = body.get("task_count", len(payload["tasks"]))
    definition_hash = (body.get("definition_hash") or "")[:12]
    print(
        f"  {wf.name}: {action} ({task_count} tasks, hash={definition_hash}...)",
        flush=True,
    )


def main() -> int:
    base_url = os.environ.get("VALIDANCE_BASE_URL")
    if not base_url:
        print(
            "ERROR: VALIDANCE_BASE_URL is not set. "
            "Set it to the Validance instance you want to register against, "
            "e.g. VALIDANCE_BASE_URL=http://localhost:8001",
            file=sys.stderr,
        )
        return 1

    base_url = base_url.rstrip("/")
    print(f"Registering grading rubric workflows against {base_url}...", flush=True)

    try:
        health = requests.get(f"{base_url}/api/health", timeout=5)
        health.raise_for_status()
    except requests.RequestException as exc:
        print(
            f"ERROR: cannot reach Validance API at {base_url}: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        for key in WORKFLOWS:
            _register_one(base_url, key)
    except requests.RequestException as exc:
        print(f"ERROR: registration failed: {exc}", file=sys.stderr)
        return 1

    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
