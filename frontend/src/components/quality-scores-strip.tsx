// DR-UI-06 — *Quality scores* strip on the Review screen.
//
// Surfaces the three headline `CriterionScore` values produced by the
// score stage (DR-SCR-01 / DR-SCR-02), with confidence indicators
// rendered as filled dots and *was: …* annotations from
// `ExplainedRubricFile.previous_quality_scores` shown only when a
// previous iteration exists.

import { ConfidenceDots } from "@/components/confidence-dots";
import { Card, CardContent } from "@/components/ui/card";
import { CRITERION_LABEL } from "@/lib/labels";
import type { CriterionScore } from "@/lib/types";

interface QualityScoresStripProps {
  scores: CriterionScore[];
  previousScores: CriterionScore[] | null;
}

const CRITERION_DESCRIPTION: Record<string, string> = {
  ambiguity:
    "How clear and unambiguous is the rubric language? Higher = less room for grader interpretation.",
  applicability:
    "Can graders consistently apply this rubric to student work? Higher = more self-contained and actionable.",
  discrimination_power:
    "Can the rubric distinguish different levels of student performance? Higher = better grade spread.",
};

const CONFIDENCE_DESCRIPTION: Record<string, string> = {
  low: "Low confidence \u2014 based on automated heuristics only, no LLM verification. Results are indicative, not definitive.",
  medium:
    "Medium confidence \u2014 based on grounded measurement with some evidence.",
  high: "High confidence \u2014 based on LLM panel agreement with multiple samples.",
};

export function QualityScoresStrip({
  scores,
  previousScores,
}: QualityScoresStripProps) {
  const previousByCriterion = new Map(
    (previousScores ?? []).map((s) => [s.criterion, s] as const),
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {scores.map((score) => {
          const previous = previousByCriterion.get(score.criterion);
          const confDesc =
            CONFIDENCE_DESCRIPTION[score.confidence.level] ??
            score.confidence.rationale;
          return (
            <Card key={score.criterion}>
              <CardContent className="pt-4">
                <p
                  className="text-xs uppercase tracking-wide text-slate-500"
                  title={CRITERION_DESCRIPTION[score.criterion]}
                >
                  {CRITERION_LABEL[score.criterion]}
                </p>
                <div className="mt-1 flex items-baseline justify-between">
                  <span
                    className="text-2xl font-semibold text-slate-900"
                    title="Quality score for the improved rubric (0 = many issues, 100 = no issues found)"
                  >
                    {(score.score * 100).toFixed(0)}
                    <span className="text-sm text-slate-400">/100</span>
                  </span>
                  <span title={confDesc}>
                    <ConfidenceDots level={score.confidence.level} />
                  </span>
                </div>
                {previous && (
                  <p className="mt-1 text-xs text-slate-400">
                    was: {(previous.score * 100).toFixed(0)}/100
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
      <p className="text-xs text-slate-400">
        Scores reflect the <strong>improved</strong> rubric&apos;s quality.
        Dots indicate measurement confidence (
        <span className="inline-flex items-center gap-0.5 align-middle">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-800" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-300" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-300" />
        </span>{" "}
        low,{" "}
        <span className="inline-flex items-center gap-0.5 align-middle">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-800" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-800" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-300" />
        </span>{" "}
        medium,{" "}
        <span className="inline-flex items-center gap-0.5 align-middle">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-800" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-800" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-800" />
        </span>{" "}
        high).
      </p>
    </div>
  );
}
