// DR-UI-06 — *Rubric view*: a flat read-only renderer for one `Rubric`.
//
// The component is intentionally a **pure render function** with no
// internal state — it reads the `Rubric` once on mount, walks the
// recursive criterion tree, and emits a side-by-side card layout. Any
// node-level highlighting is driven by the optional `highlightedFieldIds`
// set, populated by the parent screen from the `ProposedChange`
// discriminated union of § 4.6 (RubricDiffComponent below).
//
// The component knows nothing about Validance, polling, or accept/reject
// state — it is the SPA's only renderer of the L1 `Rubric` shape.

import { Fragment } from "react";

import { cn } from "@/lib/utils";
import type { Rubric, RubricCriterion, RubricLevel } from "@/lib/types";

interface RubricViewProps {
  rubric: Rubric | null;
  highlightedNodeIds?: Set<string>;
  emptyLabel?: string;
  className?: string;
}

export function RubricView({
  rubric,
  highlightedNodeIds,
  emptyLabel = "No starting rubric was provided.",
  className,
}: RubricViewProps) {
  if (!rubric) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[12rem] items-center justify-center rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400",
          className,
        )}
      >
        {emptyLabel}
      </div>
    );
  }

  return (
    <div className={cn("space-y-3", className)}>
      <h3 className="text-base font-semibold text-slate-900">{rubric.name}</h3>
      {rubric.criteria.map((criterion) => (
        <CriterionNode
          key={criterion.id}
          criterion={criterion}
          depth={0}
          highlightedNodeIds={highlightedNodeIds}
        />
      ))}
    </div>
  );
}

interface CriterionNodeProps {
  criterion: RubricCriterion;
  depth: number;
  highlightedNodeIds?: Set<string>;
}

function CriterionNode({
  criterion,
  depth,
  highlightedNodeIds,
}: CriterionNodeProps) {
  const isHighlighted = highlightedNodeIds?.has(criterion.id) ?? false;

  return (
    <div
      className={cn(
        "rounded-md border border-slate-200 bg-white p-3",
        depth > 0 && "ml-4",
        isHighlighted && "border-amber-400 bg-amber-50",
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h4 className="text-sm font-medium text-slate-900">{criterion.name}</h4>
        <span className="text-xs text-slate-500">
          {criterion.points != null ? `${criterion.points} pts` : "—"}
        </span>
      </div>
      {criterion.description && (
        <p className="mt-1 text-xs text-slate-600">{criterion.description}</p>
      )}
      {criterion.levels && criterion.levels.length > 0 && (
        <ul className="mt-2 space-y-1">
          {criterion.levels.map((level) => (
            <Fragment key={level.id}>
              <LevelRow
                level={level}
                isHighlighted={
                  highlightedNodeIds?.has(level.id) ?? false
                }
              />
            </Fragment>
          ))}
        </ul>
      )}
      {criterion.sub_criteria && criterion.sub_criteria.length > 0 && (
        <div className="mt-2 space-y-2">
          {criterion.sub_criteria.map((child) => (
            <CriterionNode
              key={child.id}
              criterion={child}
              depth={depth + 1}
              highlightedNodeIds={highlightedNodeIds}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LevelRow({
  level,
  isHighlighted,
}: {
  level: RubricLevel;
  isHighlighted: boolean;
}) {
  return (
    <li
      className={cn(
        "flex items-baseline gap-2 rounded px-2 py-1 text-xs",
        isHighlighted ? "bg-amber-100 text-amber-900" : "text-slate-600",
      )}
    >
      <span className="font-medium text-slate-800">{level.label}</span>
      <span className="text-slate-400">— {level.descriptor}</span>
      <span className="ml-auto text-slate-500">{level.points} pts</span>
    </li>
  );
}
