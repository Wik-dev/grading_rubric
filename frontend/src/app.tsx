// DR-UI-02 — top-level screen-state machine.
//
// The SPA exposes exactly the three screens locked in `ui-draft.md` § 4 —
// *Input*, *Running*, *Review* — and the navigation between them is
// one-way: Input → Running → Review, with the *× (close)* affordance on
// Review returning to a fresh empty Input screen and discarding the
// current `runId`. There is no router with deep links, no nested routes,
// and no modal stack beyond the *Why?* expand-in-place panel of DR-UI-08.
//
// State held here is intentionally tiny per DR-UI-03:
//   1. the current screen enum
//   2. the current Validance `runId` (or `null` on the Input screen)
// Everything else lives in TanStack Query's in-memory cache or in the
// Validance instance the SPA polls. There is no `localStorage`, no
// `sessionStorage`, no `IndexedDB`, no service worker.

import { useState } from "react";

import { InputScreen } from "@/screens/input-screen";
import { RunningScreen } from "@/screens/running-screen";
import { ReviewScreen } from "@/screens/review-screen";

export type ReviewMode = "approval" | "completed";
type ScreenName = "input" | "running" | "review";

export function App() {
  const [screen, setScreen] = useState<ScreenName>("input");
  const [runId, setRunId] = useState<string | null>(null);
  const [reviewMode, setReviewMode] = useState<ReviewMode>("completed");

  const handleRunStarted = (newRunId: string) => {
    setRunId(newRunId);
    setScreen("running");
  };

  const handleRunReady = (mode: ReviewMode) => {
    setReviewMode(mode);
    setScreen("review");
  };

  const handleApprovalSubmitted = () => {
    // After teacher submits decisions, go back to Running to wait for
    // score + render to complete.
    setScreen("running");
  };

  const handleClose = () => {
    setRunId(null);
    setScreen("input");
  };

  if (screen === "input" || runId === null) {
    return <InputScreen onRunStarted={handleRunStarted} />;
  }

  if (screen === "running") {
    return (
      <RunningScreen
        runId={runId}
        onRunReady={handleRunReady}
        onCancel={handleClose}
      />
    );
  }

  return (
    <ReviewScreen
      runId={runId}
      mode={reviewMode}
      onApprovalSubmitted={handleApprovalSubmitted}
      onClose={handleClose}
    />
  );
}
