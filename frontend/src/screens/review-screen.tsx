// DR-UI-06 / DR-UI-07 / DR-UI-08 — *Review* screen.
//
// Renders the original and improved rubric side by side from the
// `ExplainedRubricFile` produced by the render stage, surfaces the three
// quality scores, lists the suggested changes with Accept / Reject /
// *Why?* controls, and exposes the *Re-assess after my edits* loop wired
// through Validance's `ApprovalGate` (DR-INT-04 / DR-INT-06). Also exposes
// the *Download JSON* button (UR-09 / SR-OUT-05) and the quiet *View
// audit bundle* link (SR-OBS-03, DR-INT-05).
//
// Per DR-UI-03 the screen has no persistent state — teacher decisions
// live in component state for the lifetime of the session and are
// flushed to Validance via `resolveApproval` when the teacher commits.

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { ChangeCard } from "@/components/change-card";
import { QualityScoresStrip } from "@/components/quality-scores-strip";
import { RubricView } from "@/components/rubric-view";
import {
  auditBundleUrl,
  getExplainedRubric,
  getProposedChangesForReview,
  resolveApproval,
} from "@/lib/api";
import { CRITERION_LABEL } from "@/lib/labels";
import { buildCriterionNameMap } from "@/lib/utils";
import type { ProposedChange, TeacherDecision } from "@/lib/types";
import type { ReviewMode } from "@/app";

interface ReviewScreenProps {
  runId: string;
  mode: ReviewMode;
  onApprovalSubmitted: () => void;
  onClose: () => void;
}

// DR-UI-07: the safety bound surfaced as a disabled state on
// *Re-assess after my edits*. Mirrors `Settings.max_iterations` (default
// 3, the bound of DR-AS-12 / DR-IM-11 / DR-INT-06). The SPA does not
// receive iteration counters from the backend in this build — the bound
// is informational only and the button stays enabled until the teacher
// closes the run.
const MAX_ITERATIONS = 3;

export function ReviewScreen({ runId, mode, onApprovalSubmitted, onClose }: ReviewScreenProps) {
  const [decisions, setDecisions] = useState<Record<string, TeacherDecision>>(
    {},
  );

  const explained = useQuery({
    queryKey: ["explained", runId, mode],
    queryFn: () =>
      mode === "approval"
        ? getProposedChangesForReview(runId)
        : getExplainedRubric(runId),
  });

  const resolve = useMutation({
    mutationFn: (entries: { id: string; decision: "accepted" | "rejected" }[]) =>
      resolveApproval(runId, entries),
  });

  // Build a criterion-ID → human-readable-name map from both rubrics so
  // that raw UUIDs in finding observations can be replaced before display.
  const criterionNameMap = useMemo(
    () =>
      buildCriterionNameMap(
        explained.data?.starting_rubric,
        explained.data?.improved_rubric,
      ),
    [explained.data],
  );

  // DR-UI-06: pure derivation of the highlight set from the
  // `ProposedChange` discriminated union. Each variant contributes the
  // ids of the rubric nodes the change touches; the rubric view uses the
  // set to paint the touched cards in the amber palette.
  const { highlightedOriginal, highlightedImproved } = useMemo(() => {
    const original = new Set<string>();
    const improved = new Set<string>();
    for (const change of explained.data?.proposed_changes ?? []) {
      collectHighlightedIds(change, original, improved);
    }
    return { highlightedOriginal: original, highlightedImproved: improved };
  }, [explained.data]);

  if (explained.isLoading) {
    return (
      <div className="mx-auto max-w-5xl p-6 text-sm text-slate-500">
        Loading your improved rubric…
      </div>
    );
  }

  if (explained.isError || !explained.data) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-6">
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load the explained rubric:{" "}
          {(explained.error as Error | undefined)?.message ?? "unknown error"}
        </p>
        <Button variant="outline" onClick={onClose}>
          Back to start
        </Button>
      </div>
    );
  }

  const explainedFile = explained.data;

  const handleAccept = (id: string) =>
    setDecisions((prev) => ({ ...prev, [id]: "accepted" }));

  const handleReject = (id: string) =>
    setDecisions((prev) => ({ ...prev, [id]: "rejected" }));

  const handleSubmitApproval = () => {
    // DR-UI-07: resolve the approval gate with the teacher's per-change
    // decisions, then return to the Running screen to wait for score + render.
    const entries = explainedFile.proposed_changes.map((c) => ({
      id: c.id,
      decision: (decisions[c.id] ?? "accepted") as "accepted" | "rejected",
    }));
    resolve.mutate(entries, {
      onSuccess: () => onApprovalSubmitted(),
    });
  };

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(explainedFile, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `explained_rubric_${runId.slice(0, 8)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleReassess = () => {
    // DR-UI-07: starts a fresh assess_and_improve run using the current
    // improved rubric as the new starting rubric input. In this build the
    // SPA delegates the re-trigger to the user (the *Build my rubric*
    // affordance on the Input screen) by closing the current run and
    // returning to the Input screen — the simplest realization of the
    // re-measurement loop that does not invent new backend endpoints.
    onClose();
  };

  const findings = explainedFile.findings;
  const evidenceProfile = explainedFile.evidence_profile;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold text-slate-900">
            {mode === "approval"
              ? "Review proposed changes"
              : "Your improved rubric"}
          </h1>
          <p className="text-sm text-slate-500">
            {mode === "approval"
              ? "Accept or reject each change, then submit your decisions to continue."
              : "Review the changes below. Accept what you like, reject the rest, then download your rubric."}
          </p>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="Close">
          ×
        </Button>
      </header>

      {mode === "completed" && explainedFile.quality_scores.length > 0 && (
        <QualityScoresStrip
          scores={explainedFile.quality_scores}
          previousScores={explainedFile.previous_quality_scores}
        />
      )}

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <h2 className="text-sm font-medium uppercase tracking-wide text-slate-500">
            Original rubric
          </h2>
          <RubricView
            rubric={explainedFile.starting_rubric}
            highlightedNodeIds={highlightedOriginal}
          />
        </div>
        <div className="space-y-2">
          <h2 className="text-sm font-medium uppercase tracking-wide text-slate-500">
            Improved rubric
          </h2>
          <RubricView
            rubric={explainedFile.improved_rubric}
            highlightedNodeIds={highlightedImproved}
          />
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-slate-900">
          Suggested changes
        </h2>
        {explainedFile.proposed_changes.length === 0 ? (
          <p className="rounded-md border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-500">
            No changes were proposed — your rubric already looks healthy
            against{" "}
            {Object.values(CRITERION_LABEL).join(", ").toLowerCase()}.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {explainedFile.proposed_changes.map((change) => (
              <ChangeCard
                key={change.id}
                change={change}
                findings={findings}
                evidenceProfile={evidenceProfile}
                criterionNameMap={criterionNameMap}
                decision={decisions[change.id] ?? null}
                onAccept={() => handleAccept(change.id)}
                onReject={() => handleReject(change.id)}
              />
            ))}
          </div>
        )}
      </section>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
        <a
          className="text-xs text-slate-400 underline hover:text-slate-600"
          href={auditBundleUrl(runId)}
          target="_blank"
          rel="noreferrer"
        >
          View audit bundle
        </a>
        {mode === "approval" ? (
          <Button
            onClick={handleSubmitApproval}
            disabled={resolve.isPending}
          >
            {resolve.isPending ? "Submitting…" : "Submit decisions & continue"}
          </Button>
        ) : (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={handleReassess}
              disabled={MAX_ITERATIONS <= 1}
              title={`Re-assess after my edits (limited to ${MAX_ITERATIONS} iterations)`}
            >
              Re-assess after my edits
            </Button>
            <Button onClick={handleDownload}>Download JSON</Button>
          </div>
        )}
      </footer>
    </div>
  );
}

// ── Highlight derivation ────────────────────────────────────────────────
//
// DR-UI-06: the diff highlighting is **driven by the `ProposedChange`
// discriminated union** of § 4.6. Each variant tells us which rubric
// nodes the change touches on the original column and on the improved
// column. We deliberately do **not** branch on a fallback "unknown
// operation" case — the union is closed and the SPA's TypeScript types
// reflect that.

function collectHighlightedIds(
  change: ProposedChange,
  original: Set<string>,
  improved: Set<string>,
): void {
  switch (change.operation) {
    case "REPLACE_FIELD":
    case "UPDATE_POINTS": {
      // Field-level edit on a known target on both columns.
      const target = (change as { target?: { criterion_path?: string[] } })
        .target;
      const last = target?.criterion_path?.[target.criterion_path.length - 1];
      if (last) {
        original.add(last);
        improved.add(last);
      }
      const levelId = (change as { target?: { level_id?: string | null } })
        .target?.level_id;
      if (levelId) {
        original.add(levelId);
        improved.add(levelId);
      }
      break;
    }
    case "ADD_NODE": {
      // Painted only on the improved column.
      const node = (change as { node?: { id?: string } }).node;
      if (node?.id) improved.add(node.id);
      break;
    }
    case "REMOVE_NODE": {
      // Struck through only on the original column.
      const snapshot = (change as { removed_snapshot?: { id?: string } })
        .removed_snapshot;
      if (snapshot?.id) original.add(snapshot.id);
      const levelId = (change as { level_id?: string | null }).level_id;
      if (levelId) original.add(levelId);
      break;
    }
    case "REORDER_NODES": {
      // Reorder is signalled on both columns by the parent path.
      const parent = (change as { parent_path?: string[] }).parent_path;
      const last = parent?.[parent.length - 1];
      if (last) {
        original.add(last);
        improved.add(last);
      }
      break;
    }
  }
}
