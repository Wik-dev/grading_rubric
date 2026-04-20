import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn-style class-name combinator. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

import type { Rubric, RubricCriterion } from "@/lib/types";

/**
 * Build a map from criterion UUID to human-readable name from one or more
 * rubrics. The map includes composite "parent>child" keys so that the
 * path notation used in finding observations can be resolved too.
 */
export function buildCriterionNameMap(
  ...rubrics: (Rubric | null | undefined)[]
): Map<string, string> {
  const map = new Map<string, string>();

  function walk(criteria: RubricCriterion[], parentId?: string) {
    for (const c of criteria) {
      map.set(c.id, c.name);
      if (parentId) {
        map.set(`${parentId}>${c.id}`, `${map.get(parentId) ?? parentId} > ${c.name}`);
      }
      walk(c.sub_criteria ?? [], c.id);
    }
  }

  for (const rubric of rubrics) {
    if (rubric) walk(rubric.criteria);
  }
  return map;
}

/** UUID v4 pattern (8-4-4-4-12 hex). */
const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;

/**
 * Replace raw criterion UUIDs (and "uuid>uuid" path notation) in a
 * human-facing string with their criterion names.
 */
export function humanizeObservation(
  text: string,
  nameMap: Map<string, string>,
): string {
  // First replace composite "uuid>uuid" paths
  const compositeRe =
    /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})>([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/g;
  let result = text.replace(compositeRe, (_match, parentId, childId) => {
    const compositeKey = `${parentId}>${childId}`;
    return nameMap.get(compositeKey) ?? `${nameMap.get(parentId) ?? parentId} > ${nameMap.get(childId) ?? childId}`;
  });
  // Then replace any remaining standalone UUIDs
  result = result.replace(UUID_RE, (id) => nameMap.get(id) ?? id);
  return result;
}
