import { cn } from "@/lib/utils";
import type { ConfidenceLevel } from "@/lib/types";

const FILLED_BY_LEVEL: Record<ConfidenceLevel, number> = {
  low: 1,
  medium: 2,
  high: 3,
};

interface ConfidenceDotsProps {
  level: ConfidenceLevel;
  className?: string;
}

/** ui-draft.md § 4.3 — confidence indicator rendered as filled dots. */
export function ConfidenceDots({ level, className }: ConfidenceDotsProps) {
  const filled = FILLED_BY_LEVEL[level];
  return (
    <span
      className={cn("inline-flex items-center gap-0.5", className)}
      aria-label={`confidence ${level}`}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={cn(
            "h-2 w-2 rounded-full",
            i < filled ? "bg-slate-800" : "bg-slate-300",
          )}
        />
      ))}
    </span>
  );
}
