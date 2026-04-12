// DR-UI-01 — the Validance REST API client. The SPA never imports
// `validance-sdk`; it talks to the running Validance instance over HTTP.
//
// All endpoints here are conventions consistent with the Validance REST
// surface used by the rest of the ecosystem (e.g. mining_optimization's
// orchestrators). When the surface drifts, change this file in lockstep
// with `validance/harvester.py`'s `ValidanceRunClient` Protocol.

import type { ExplainedRubricFile, ValidanceRunState } from "@/lib/types";

const BASE_URL =
  (import.meta.env.VITE_VALIDANCE_BASE_URL as string | undefined)?.replace(
    /\/$/,
    "",
  ) || "http://localhost:8001";

export interface AssessAndImproveInputs {
  exam_question_text?: string;
  exam_question_filename?: string;
  teaching_material_text?: string;
  teaching_material_filename?: string;
  starting_rubric_text?: string;
  starting_rubric_filename?: string;
  student_copies: { filename: string; text: string }[];
}

export interface StartRunResponse {
  run_id: string;
  workflow_name: string;
}

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

/** Health check — used by the Input screen to surface a "backend is up" badge. */
export async function getHealth(): Promise<{ status: string }> {
  return jsonFetch<{ status: string }>("/api/health");
}

/**
 * DR-UI-04 — start one `grading_rubric.assess_and_improve` workflow run.
 *
 * The SPA serialises the four input fields into the L1 `IngestInputs`
 * Pydantic shape, POSTs them as a Validance proposal/run, and returns
 * the run_id which is held in memory only (DR-UI-03).
 */
export async function startAssessAndImproveRun(
  inputs: AssessAndImproveInputs,
): Promise<StartRunResponse> {
  return jsonFetch<StartRunResponse>("/api/runs", {
    method: "POST",
    body: JSON.stringify({
      workflow_name: "grading_rubric.assess_and_improve",
      parameters: {
        ingest_inputs: serialiseIngestInputs(inputs),
      },
    }),
  });
}

/** DR-INT-06 — fetch the current run state for polling. */
export async function getRunState(runId: string): Promise<ValidanceRunState> {
  return jsonFetch<ValidanceRunState>(`/api/runs/${runId}/state`);
}

/**
 * DR-UI-07 — POST a per-change accept/reject resolution back to the
 * Validance ApprovalGate. The SPA sends one batched resolution covering
 * every change the teacher has decided on.
 */
export async function resolveApproval(
  runId: string,
  decisions: { id: string; decision: "accepted" | "rejected" }[],
): Promise<void> {
  await jsonFetch<unknown>(`/api/runs/${runId}/approval`, {
    method: "POST",
    body: JSON.stringify({ decisions }),
  });
}

/**
 * DR-UI-06 — fetch the rendered ExplainedRubricFile after the run reaches
 * the terminal `success` state. The endpoint returns the parsed JSON of
 * the render task's `explained_rubric` output.
 */
export async function getExplainedRubric(
  runId: string,
): Promise<ExplainedRubricFile> {
  return jsonFetch<ExplainedRubricFile>(
    `/api/runs/${runId}/outputs/explained_rubric`,
  );
}

/** SR-OBS-03 — *View audit bundle* link target (DR-INT-05 harvester). */
export function auditBundleUrl(runId: string): string {
  return `${BASE_URL}/api/runs/${runId}/audit_bundle`;
}

// ── Internal: shape the four SPA fields into the L1 IngestInputs JSON ────

function serialiseIngestInputs(inputs: AssessAndImproveInputs) {
  // The L1 IngestInputs model carries role-tagged InputSource records.
  // We forward them as a JSON-friendly dict; Validance writes the dict to
  // /work/ingest_inputs.json which the L1 ingest stage then validates via
  // pydantic strict mode (DR-DAT-02).
  return {
    exam_question: inputs.exam_question_text
      ? {
          kind: "inline_text",
          text: inputs.exam_question_text,
          marker: inputs.exam_question_filename ?? "exam_question.txt",
        }
      : null,
    teaching_material: inputs.teaching_material_text
      ? [
          {
            kind: "inline_text",
            text: inputs.teaching_material_text,
            marker:
              inputs.teaching_material_filename ?? "teaching_material.txt",
          },
        ]
      : [],
    starting_rubric: inputs.starting_rubric_text
      ? {
          kind: "inline_text",
          text: inputs.starting_rubric_text,
          marker: inputs.starting_rubric_filename ?? "starting_rubric.txt",
        }
      : null,
    student_copies: inputs.student_copies.map((copy) => ({
      kind: "inline_text",
      text: copy.text,
      marker: copy.filename,
    })),
  };
}
