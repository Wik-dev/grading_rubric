// DR-UI-06 / DR-UI-07 / DR-UI-08 — *Suggested change* card.
//
// One card per `ProposedChange`. Shows the primary criterion as a coloured
// tag, the rationale text as the headline, and the per-change confidence
// indicator as filled dots. Exposes Accept / Reject controls (DR-UI-07)
// and the *Why?* affordance (DR-UI-08), which expands an in-place panel
// containing exactly three pieces of information:
//
//   (a) the originating finding(s) paraphrased — taken from the linked
//       findings' rationales, never the finding `id`;
//   (b) the evidence type — *real student copies* or *synthetic responses*,
//       with the synthetic flag taken from `EvidenceProfile`;
//   (c) the per-finding confidence rationale text from the
//       `ConfidenceIndicator` envelope.

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfidenceDots } from "@/components/confidence-dots";
import { CRITERION_LABEL } from "@/lib/labels";
import { cn, humanizeObservation } from "@/lib/utils";
import type {
  AssessmentFinding,
  EvidenceProfile,
  ProposedChange,
  TeacherDecision,
} from "@/lib/types";

interface ChangeCardProps {
  change: ProposedChange;
  findings: AssessmentFinding[];
  evidenceProfile: EvidenceProfile;
  criterionNameMap: Map<string, string>;
  decision: TeacherDecision | null;
  onAccept: () => void;
  onReject: () => void;
}

export function ChangeCard({
  change,
  findings,
  evidenceProfile,
  criterionNameMap,
  decision,
  onAccept,
  onReject,
}: ChangeCardProps) {
  const [whyOpen, setWhyOpen] = useState(false);

  const linkedFindings = findings.filter((f) =>
    change.source_findings.includes(f.id),
  );

  return (
    <Card
      className={cn(
        decision === "accepted" && "border-emerald-300 bg-emerald-50/40",
        decision === "rejected" && "border-slate-300 bg-slate-100 opacity-70",
      )}
    >
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <Badge variant="secondary">
              {CRITERION_LABEL[change.primary_criterion]}
            </Badge>
            <p className="text-sm text-slate-800">{change.rationale}</p>
          </div>
          <ConfidenceDots level={change.confidence.level} />
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={decision === "accepted" ? "default" : "outline"}
            onClick={onAccept}
          >
            Accept
          </Button>
          <Button
            size="sm"
            variant={decision === "rejected" ? "destructive" : "outline"}
            onClick={onReject}
          >
            Reject
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setWhyOpen((open) => !open)}
            aria-expanded={whyOpen}
          >
            {whyOpen ? "Hide why" : "Why?"}
          </Button>
        </div>

        {whyOpen && (
          <div className="space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
            <WhySection title="What we noticed">
              {linkedFindings.length > 0 ? (
                <ul className="list-disc space-y-1 pl-4">
                  {linkedFindings.map((f) => (
                    <li key={f.id}>{humanizeObservation(f.observation, criterionNameMap)}</li>
                  ))}
                </ul>
              ) : (
                <p className="italic text-slate-500">
                  No linked findings recorded for this change.
                </p>
              )}
            </WhySection>
            <WhySection title="Evidence">
              {evidenceProfile.synthetic_responses_used ? (
                <p>
                  Based on{" "}
                  <span className="font-medium text-amber-700">
                    synthetic responses
                  </span>{" "}
                  generated to probe the rubric — no real student copies were
                  available.
                </p>
              ) : (
                <p>Based on the real student copies you uploaded.</p>
              )}
            </WhySection>
            <WhySection title="Confidence">
              <p>{change.confidence.rationale}</p>
            </WhySection>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function WhySection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </p>
      <div className="mt-1">{children}</div>
    </div>
  );
}
