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

export function QualityScoresStrip({
  scores,
  previousScores,
}: QualityScoresStripProps) {
  const previousByCriterion = new Map(
    (previousScores ?? []).map((s) => [s.criterion, s] as const),
  );

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {scores.map((score) => {
        const previous = previousByCriterion.get(score.criterion);
        return (
          <Card key={score.criterion}>
            <CardContent className="pt-4">
              <p className="text-xs uppercase tracking-wide text-slate-500">
                {CRITERION_LABEL[score.criterion]}
              </p>
              <div className="mt-1 flex items-baseline justify-between">
                <span className="text-2xl font-semibold text-slate-900">
                  {(score.score * 100).toFixed(0)}
                  <span className="text-sm text-slate-400">/100</span>
                </span>
                <ConfidenceDots level={score.confidence.level} />
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
  );
}
