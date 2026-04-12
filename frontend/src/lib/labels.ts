// DR-UI-05 / DR-UI-08 — the **only** place internal stage / criterion
// names are translated into teacher-facing language. Keep this table
// short, audited, and free of system vocabulary.

import type { QualityCriterion } from "@/lib/types";

export const CRITERION_LABEL: Record<QualityCriterion, string> = {
  ambiguity: "Ambiguity",
  applicability: "Applicability",
  discrimination_power: "Discrimination power",
};

/** Stage-name → teacher-facing step label (Running screen). */
export const STAGE_LABEL: Record<string, string> = {
  ingest: "Reading your exam question",
  parse_inputs: "Reading teaching material",
  assess: "Checking the rubric against the three quality criteria",
  propose: "Building the improved rubric",
  score: "Scoring the improved rubric",
  render: "Preparing your results",
};

/** The order in which the running screen displays the steps. */
export const STAGE_ORDER: string[] = [
  "ingest",
  "parse_inputs",
  "assess",
  "propose",
  "score",
  "render",
];
