// DR-UI-01 / DR-DAT-04 — TypeScript wire shapes mirroring the L1 Pydantic
// models in `grading_rubric/models/`. In a future iteration these would be
// emitted by `make schemas` from the L1 JSON Schemas; for now they are
// hand-typed against `design.md` § 4 to keep the SPA path runnable.
//
// Only the fields the SPA actually consumes are typed. The shapes are
// intentionally narrow — when the codegen path lands the file is
// regenerated wholesale and any drift surfaces as a TypeScript error.

// ── § 4.5 Findings ────────────────────────────────────────────────────────

export type QualityCriterion =
  | "ambiguity"
  | "applicability"
  | "discrimination_power";

export type ConfidenceLevel = "low" | "medium" | "high";

export interface ConfidenceIndicator {
  score: number;
  level: ConfidenceLevel;
  rationale: string;
}

export type Severity = "low" | "medium" | "high";

export interface AssessmentFinding {
  id: string;
  criterion: QualityCriterion;
  severity: Severity;
  target: { criterion_id: string; field?: string } | null;
  observation: string;
  evidence: string;
  measurement: { method: string; samples: number; agreement: number | null };
  confidence: ConfidenceIndicator;
  measured_against_rubric_id: string;
  iteration: number;
  source_operations: string[];
  linked_finding_ids: string[];
}

// ── § 4.6 ProposedChange (discriminated union) ────────────────────────────

export type ApplicationStatus = "applied" | "not_applied";
export type TeacherDecision = "pending" | "accepted" | "rejected";

export interface ProposedChangeBase {
  id: string;
  primary_criterion: QualityCriterion;
  source_findings: string[];
  rationale: string;
  confidence: ConfidenceIndicator;
  application_status: ApplicationStatus;
  teacher_decision: TeacherDecision | null;
}

export type ProposedChangeOperation =
  | "REPLACE_FIELD"
  | "UPDATE_POINTS"
  | "ADD_NODE"
  | "REMOVE_NODE"
  | "REORDER_NODES";

export interface ProposedChange extends ProposedChangeBase {
  operation: ProposedChangeOperation;
  // operation-specific fields are read opportunistically by the diff renderer
  [extra: string]: unknown;
}

// ── § 4.3 Rubric ──────────────────────────────────────────────────────────

export interface RubricLevel {
  id: string;
  label: string;
  descriptor: string;
  points: number;
}

export interface RubricCriterion {
  id: string;
  name: string;
  description: string;
  scoring_guidance: string;
  points: number;
  weight: number;
  levels: RubricLevel[];
  sub_criteria: RubricCriterion[];
}

export interface Rubric {
  id: string;
  title: string;
  total_points: number;
  criteria: RubricCriterion[];
}

// ── § 4.9 ExplainedRubricFile ────────────────────────────────────────────

export type QualityMethod =
  | "LLM_PANEL_AGREEMENT"
  | "PAIRWISE_CONSISTENCY"
  | "SYNTHETIC_COVERAGE"
  | "SCORE_DISTRIBUTION_SEPARATION"
  | "LINGUISTIC_SWEEP";

export interface CriterionScore {
  criterion: QualityCriterion;
  score: number;
  confidence: ConfidenceIndicator;
  method: QualityMethod;
}

export interface CriterionSection {
  criterion: QualityCriterion;
  narrative: string;
  finding_refs: string[];
  change_refs: string[];
  unaddressed_finding_refs: string[];
}

export interface Explanation {
  by_criterion: Record<QualityCriterion, CriterionSection>;
}

export interface EvidenceProfile {
  starting_rubric_present: boolean;
  exam_question_present: boolean;
  teaching_material_present: boolean;
  student_copies_present: boolean;
  synthetic_responses_used: boolean;
}

export interface ExplainedRubricFile {
  schema_version: string;
  generated_at: string;
  run_id: string;
  starting_rubric: Rubric | null;
  improved_rubric: Rubric;
  findings: AssessmentFinding[];
  proposed_changes: ProposedChange[];
  explanation: Explanation;
  quality_scores: CriterionScore[];
  previous_quality_scores: CriterionScore[] | null;
  evidence_profile: EvidenceProfile;
}

// ── Validance run state (DR-INT-06) ──────────────────────────────────────

export type ValidanceTaskStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "skipped"
  | "awaiting_approval";

export interface ValidanceTaskState {
  name: string;
  status: ValidanceTaskStatus;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface ValidanceRunState {
  run_id: string;
  workflow_name: string;
  status: "pending" | "running" | "awaiting_approval" | "success" | "failed";
  tasks: ValidanceTaskState[];
  pending_approval?: {
    task_name: string;
    /** Null when the approval payload shape is not yet known to the SPA. */
    proposal_payload: {
      kind: string;
      version: string;
      count: number;
      changes: ProposedChange[];
    } | null;
  } | null;
}
