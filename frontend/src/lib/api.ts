// DR-UI-01 — the Validance REST API client. The SPA never imports
// `validance-sdk`; it talks to the running Validance instance over HTTP.
//
// All endpoints here are mapped to the actual Validance REST surface.
// Validance uses `workflow_hash` as the run identifier throughout:
//
//   Status:   GET  /api/workflows/{name}/status?workflow_hash=...
//   Approval: GET  /api/approvals?status=pending  (find by workflow_hash)
//             POST /api/approvals/{approval_id}/resolve
//   Files:    GET  /api/files/{workflow_hash}/download?task_name=...&file_name=...
//   Audit:    GET  /api/audit/{workflow_hash}
//
// This file adapts the Validance response shapes into the `ValidanceRunState`
// and `ExplainedRubricFile` types the SPA screens consume.

import type {
  ExplainedRubricFile,
  ValidanceRunState,
  ValidanceTaskState,
  ValidanceTaskStatus,
} from "@/lib/types";

const BASE_URL =
  (import.meta.env.VITE_VALIDANCE_BASE_URL as string | undefined)?.replace(
    /\/$/,
    "",
  ) || "https://api.validance.io";

const WORKFLOW_NAME = "grading_rubric.assess_and_improve";

// ── Types ─────────────────────────────────────────────────────────────────

/** A role-tagged file the teacher selected in the Input screen. */
export interface RoleFile {
  role: "exam_question" | "teaching_material" | "student_copy" | "starting_rubric";
  file: File;
}

/** Response from POST /api/files/upload. */
interface UploadResponse {
  uri: string;
  file_hash: string;
  file_size: number;
}

/** ADR-007 structured trigger input file entry. */
interface TriggerInputFile {
  role: string;
  name: string;
  uri: string;
}

export interface StartRunResponse {
  workflow_hash: string;
  workflow_name: string;
  status: string;
}

// ── Validance API response shapes (internal mapping layer) ──────────────

interface VTaskStatus {
  task_hash: string;
  task_name: string;
  status: string; // uppercase: RUNNING, PENDING, SUCCESS, FAILED
  start_time: string | null;
  end_time: string | null;
}

interface VWorkflowStatus {
  workflow_hash: string;
  workflow_name: string;
  status: string;
  tasks: VTaskStatus[];
}

interface VApprovalEntry {
  approval_id: string;
  workflow_hash: string;
  status: string;
  proposal: Record<string, unknown>;
}

// ── Low-level helpers ─────────────────────────────────────────────────────

async function jsonFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `Validance API ${path} failed: ${response.status} ${response.statusText}${
        text ? ` — ${text.slice(0, 200)}` : ""
      }`,
    );
  }
  return (await response.json()) as T;
}

// ── File upload ───────────────────────────────────────────────────────────

/**
 * Upload a single file to Azure Blob Storage via the Validance upload proxy.
 *
 * Returns an `azure://` URI suitable for use in trigger `input_files`.
 */
export async function uploadFile(
  file: File,
  container?: string,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (container) {
    formData.append("container", container);
  }

  const response = await fetch(`${BASE_URL}/api/files/upload`, {
    method: "POST",
    body: formData,
    // No Content-Type header — browser sets multipart boundary automatically
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `File upload failed for ${file.name}: ${response.status} ${response.statusText}${
        text ? ` — ${text.slice(0, 200)}` : ""
      }`,
    );
  }
  return (await response.json()) as UploadResponse;
}

// ── Public API ────────────────────────────────────────────────────────────

/**
 * Health check — used by the Input screen to surface a "backend is up" badge.
 *
 * Validance returns `{ checks: {...}, overall: "healthy"|"unhealthy" }`.
 * We map `overall` to the `status` field the SPA expects.
 */
export async function getHealth(): Promise<{ status: string }> {
  const data = await jsonFetch<{ status?: string; overall?: string }>("/api/health");
  return { status: data.status ?? data.overall ?? "unknown" };
}

/**
 * DR-UI-04 — start one `grading_rubric.assess_and_improve` workflow run.
 *
 * 1. Uploads each browser-selected file to Azure via POST /api/files/upload.
 * 2. Triggers the workflow with ADR-007 structured `input_files` carrying
 *    the `azure://` URIs and role tags.
 *
 * The Validance engine stages these files into `inputs/<role>/<filename>`
 * in the ingest task's working directory. The L1 CLI then scans them with
 * `--input-root inputs`.
 */
export async function startAssessAndImproveRun(
  roleFiles: RoleFile[],
  startingRubricInline?: string,
): Promise<StartRunResponse> {
  // Upload all files in parallel
  const uploads = await Promise.all(
    roleFiles.map(async (rf) => {
      const result = await uploadFile(rf.file);
      return {
        role: rf.role,
        name: rf.file.name,
        uri: result.uri,
      } satisfies TriggerInputFile;
    }),
  );

  // If there's inline starting rubric text (no file), create a text blob
  // and upload it so it appears as a file in the staged directory.
  if (startingRubricInline?.trim()) {
    const blob = new Blob([startingRubricInline], { type: "text/plain" });
    const inlineFile = new File([blob], "starting_rubric.inline.txt", {
      type: "text/plain",
    });
    const result = await uploadFile(inlineFile);
    uploads.push({
      role: "starting_rubric",
      name: inlineFile.name,
      uri: result.uri,
    });
  }

  return jsonFetch<StartRunResponse>(
    `/api/workflows/${WORKFLOW_NAME}/trigger`,
    {
      method: "POST",
      body: JSON.stringify({
        input_files: uploads,
      }),
    },
  );
}

/**
 * DR-INT-06 — fetch the current run state for polling.
 *
 * Merges two Validance endpoints:
 *   GET /api/workflows/{name}/status?workflow_hash=...  (task progress)
 *   GET /api/approvals?status=pending                   (approval gate)
 *
 * If the workflow is "running" but has a pending approval, we surface the
 * `awaiting_approval` status so the Running screen can transition to Review.
 */
export async function getRunState(runId: string): Promise<ValidanceRunState> {
  const [wfStatus, approvals] = await Promise.all([
    jsonFetch<VWorkflowStatus>(
      `/api/workflows/${WORKFLOW_NAME}/status?workflow_hash=${encodeURIComponent(runId)}`,
    ),
    jsonFetch<{ approvals: VApprovalEntry[] }>(
      "/api/approvals?status=pending",
    ).catch(() => ({ approvals: [] as VApprovalEntry[] })),
  ]);

  // Map Validance uppercase task statuses to SPA lowercase enum
  const tasks: ValidanceTaskState[] = wfStatus.tasks.map((t) => ({
    name: t.task_name,
    status: t.status.toLowerCase() as ValidanceTaskStatus,
    started_at: t.start_time,
    ended_at: t.end_time,
  }));

  // Detect approval gate: if there's a pending approval for this workflow
  // and the workflow is still running, the propose task's human-confirm
  // gate has fired. Override the status so the Running screen transitions.
  const pendingApproval = approvals.approvals.find(
    (a) => a.workflow_hash === runId,
  );

  let status = wfStatus.status.toLowerCase() as ValidanceRunState["status"];
  if (pendingApproval && status === "running") {
    status = "awaiting_approval";
  }

  return {
    run_id: wfStatus.workflow_hash,
    workflow_name: wfStatus.workflow_name,
    status,
    tasks,
    pending_approval: pendingApproval
      ? { task_name: "propose", proposal_payload: null }
      : null,
  };
}

/**
 * DR-UI-07 — POST per-change accept/reject resolutions back to the
 * Validance ApprovalGate.
 *
 * Finds the pending approval for this workflow and resolves it as
 * "approved", encoding the teacher's per-change decisions in the
 * `reason` field so downstream tasks can read them.
 *
 * If no pending approval exists (workflow already completed), the
 * decisions are a no-op — they are recorded client-side for the
 * re-assessment trigger.
 */
export async function resolveApproval(
  runId: string,
  decisions: { id: string; decision: "accepted" | "rejected" }[],
): Promise<void> {
  // Find the pending approval for this workflow
  const { approvals } = await jsonFetch<{ approvals: VApprovalEntry[] }>(
    "/api/approvals?status=pending",
  );
  const approval = approvals.find((a) => a.workflow_hash === runId);

  if (approval) {
    await jsonFetch<unknown>(
      `/api/approvals/${approval.approval_id}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({
          decision: "approved",
          decided_by: "teacher",
          reason: JSON.stringify({ decisions }),
        }),
      },
    );
  }
}

/**
 * DR-UI-06 — fetch the rendered ExplainedRubricFile after the run reaches
 * the terminal `success` state.
 *
 * Downloads the render task's `explained_rubric.json` output file via the
 * Validance file download endpoint.
 */
export async function getExplainedRubric(
  runId: string,
): Promise<ExplainedRubricFile> {
  return jsonFetch<ExplainedRubricFile>(
    `/api/files/${encodeURIComponent(runId)}/download?task_name=render&file_name=explained_rubric.json`,
  );
}

/**
 * Fetch the propose stage output during the approval gate phase.
 *
 * Returns a partial ExplainedRubricFile assembled from propose_outputs.json
 * so the Review screen can show proposed changes for accept/reject before
 * score + render have run.
 */
export async function getProposedChangesForReview(
  runId: string,
): Promise<ExplainedRubricFile> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const raw = await jsonFetch<any>(
    `/api/files/${encodeURIComponent(runId)}/download?task_name=propose&file_name=propose_outputs.json`,
  );

  const evidenceProfile = raw.assessed?.parsed?.ingest?.evidence_profile ?? {
    starting_rubric_present: false,
    exam_question_present: false,
    teaching_material_present: false,
    student_copies_present: false,
    synthetic_responses_used: false,
  };

  return {
    schema_version: "1.0.0",
    generated_at: new Date().toISOString(),
    run_id: runId,
    starting_rubric: raw.starting_rubric ?? null,
    improved_rubric: raw.improved_rubric ?? { id: "", title: "", total_points: 0, criteria: [] },
    findings: raw.findings ?? [],
    proposed_changes: raw.proposed_changes ?? [],
    explanation: { by_criterion: {} as ExplainedRubricFile["explanation"]["by_criterion"] },
    quality_scores: [],
    previous_quality_scores: null,
    evidence_profile: evidenceProfile,
  };
}

/** SR-OBS-03 — *View audit bundle* link target (DR-INT-05 harvester). */
export function auditBundleUrl(runId: string): string {
  return `${BASE_URL}/api/audit/${encodeURIComponent(runId)}`;
}
