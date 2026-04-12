// DR-UI-05 — *Running* screen.
//
// Polls Validance's REST API for the current workflow run state with
// TanStack Query at a `refetchInterval` of 2000 ms (the same polling
// cadence locked by DR-PER-07 and DR-INT-06). Polling stops as soon as
// the workflow advances to a terminal state (`completed` / `failed` /
// `cancelled`) or to the `awaiting_approval` state of the ApprovalGate
// (DR-INT-06), at which point the SPA transitions to *Review*.
//
// The mapping from internal Validance task names to teacher-facing step
// labels lives in `lib/labels.ts` (DR-UI-08) and is the **only** place
// internal stage names appear in the SPA — every status string is
// funnelled through that table before it reaches the DOM.

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getRunState } from "@/lib/api";
import { STAGE_LABEL, STAGE_ORDER } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { ValidanceTaskStatus } from "@/lib/types";

interface RunningScreenProps {
  runId: string;
  onRunReady: () => void;
  onCancel: () => void;
}

const TERMINAL_STATUSES = new Set<string>([
  "success",
  "failed",
  "cancelled",
  "completed",
]);

export function RunningScreen({
  runId,
  onRunReady,
  onCancel,
}: RunningScreenProps) {
  const runState = useQuery({
    queryKey: ["runState", runId],
    queryFn: () => getRunState(runId),
    // DR-UI-05: 2000 ms polling cadence, locked.
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2000;
      if (TERMINAL_STATUSES.has(data.status)) return false;
      if (data.status === "awaiting_approval") return false;
      return 2000;
    },
  });

  // Transition to *Review* as soon as the workflow run reaches a state the
  // review screen can render: either it's complete (the success path), or
  // it's parked at the ApprovalGate after the propose stage (the
  // human-confirm path of DR-INT-06).
  useEffect(() => {
    if (!runState.data) return;
    const status = runState.data.status;
    if (status === "success" || status === "awaiting_approval") {
      onRunReady();
    }
  }, [runState.data, onRunReady]);

  const tasksByName = new Map(
    (runState.data?.tasks ?? []).map((task) => [task.name, task] as const),
  );

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header className="flex items-start justify-between">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold text-slate-900">
            Building your improved rubric
          </h1>
          <p className="text-sm text-slate-500">
            This usually takes a minute or two. You can leave the page open;
            results appear automatically.
          </p>
        </div>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Progress</CardTitle>
        </CardHeader>
        <CardContent>
          {runState.isLoading && !runState.data ? (
            <p className="text-sm text-slate-500">Connecting to the backend…</p>
          ) : runState.isError ? (
            <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
              Could not read run state: {(runState.error as Error).message}
            </p>
          ) : (
            <ol className="space-y-3">
              {STAGE_ORDER.map((stageName) => {
                const task = tasksByName.get(stageName);
                const status: ValidanceTaskStatus = (task?.status ??
                  "pending") as ValidanceTaskStatus;
                return (
                  <li key={stageName} className="flex items-center gap-3">
                    <StatusDot status={status} />
                    <span
                      className={cn(
                        "text-sm",
                        status === "success"
                          ? "text-slate-500 line-through"
                          : status === "running"
                            ? "font-medium text-slate-900"
                            : status === "failed"
                              ? "font-medium text-red-700"
                              : "text-slate-700",
                      )}
                    >
                      {STAGE_LABEL[stageName] ?? stageName}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>

      <p className="text-center text-xs text-slate-400">
        Run id <code className="font-mono">{runId}</code>
      </p>
    </div>
  );
}

function StatusDot({ status }: { status: ValidanceTaskStatus }) {
  const palette: Record<ValidanceTaskStatus, string> = {
    pending: "bg-slate-300",
    running: "bg-amber-400 animate-pulse",
    success: "bg-emerald-500",
    failed: "bg-red-500",
    skipped: "bg-slate-300",
    awaiting_approval: "bg-sky-500 animate-pulse",
  };
  return (
    <span
      className={cn("h-2.5 w-2.5 shrink-0 rounded-full", palette[status])}
      aria-label={`status ${status}`}
    />
  );
}
