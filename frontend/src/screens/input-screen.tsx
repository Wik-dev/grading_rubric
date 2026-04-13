import { useState, type ChangeEvent, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  type RoleFile,
  getHealth,
  startAssessAndImproveRun,
} from "@/lib/api";

interface InputScreenProps {
  onRunStarted: (runId: string) => void;
}

/**
 * ui-draft.md § 4.1 — Input screen.
 *
 * Four input fields, three of them optional, one mandatory ("Exam
 * question"). On submit, the SPA uploads all selected files to Azure via
 * POST /api/files/upload, then triggers `grading_rubric.assess_and_improve`
 * with ADR-007 structured `input_files` carrying the `azure://` URIs and
 * role tags (DR-UI-04).
 */
export function InputScreen({ onRunStarted }: InputScreenProps) {
  const [examQuestion, setExamQuestion] = useState<File | null>(null);
  const [teachingMaterial, setTeachingMaterial] = useState<File | null>(null);
  const [startingRubricFile, setStartingRubricFile] = useState<File | null>(
    null,
  );
  const [startingRubricInline, setStartingRubricInline] = useState("");
  const [studentCopies, setStudentCopies] = useState<File[]>([]);

  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 10_000,
  });

  const startRun = useMutation({
    mutationFn: async ({
      roleFiles,
      inlineRubric,
    }: {
      roleFiles: RoleFile[];
      inlineRubric?: string;
    }) => startAssessAndImproveRun(roleFiles, inlineRubric),
    onSuccess: (data) => onRunStarted(data.workflow_hash),
  });

  const handleSingleFile = (
    event: ChangeEvent<HTMLInputElement>,
    setter: (value: File | null) => void,
  ) => {
    const file = event.target.files?.[0] ?? null;
    setter(file);
  };

  const handleMultiFile = (event: ChangeEvent<HTMLInputElement>) => {
    setStudentCopies(Array.from(event.target.files ?? []));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!examQuestion) return;

    const roleFiles: RoleFile[] = [];

    roleFiles.push({ role: "exam_question", file: examQuestion });

    if (teachingMaterial) {
      roleFiles.push({ role: "teaching_material", file: teachingMaterial });
    }

    if (startingRubricFile) {
      roleFiles.push({ role: "starting_rubric", file: startingRubricFile });
    }

    for (const copy of studentCopies) {
      roleFiles.push({ role: "student_copy", file: copy });
    }

    // Inline starting rubric text is passed separately — the API layer
    // converts it to a text file and uploads it.
    const inlineRubric =
      !startingRubricFile && startingRubricInline.trim()
        ? startingRubricInline
        : undefined;

    startRun.mutate({ roleFiles, inlineRubric });
  };

  const canSubmit = Boolean(examQuestion) && !startRun.isPending;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold text-slate-900">
          Grading Rubric Studio
        </h1>
        <p className="text-sm text-slate-500">
          Provide your exam materials. The application proposes an improved
          rubric; you decide which changes to keep.
        </p>
        <p className="text-xs text-slate-400">
          Backend:{" "}
          {health.isLoading
            ? "checking…"
            : health.isError
              ? "unreachable"
              : `healthy (${health.data?.status})`}
        </p>
      </header>

      <form onSubmit={handleSubmit} className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>
              Exam question{" "}
              <span className="text-xs font-normal text-slate-500">
                (required)
              </span>
            </CardTitle>
            <CardDescription>
              Drop a file or click to upload. Accepted: .txt .md .pdf .docx
            </CardDescription>
          </CardHeader>
          <CardContent>
            <input
              type="file"
              accept=".txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(e) => handleSingleFile(e, setExamQuestion)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
            {examQuestion && (
              <p className="mt-2 text-xs text-slate-500">
                Selected: {examQuestion.name} (
                {(examQuestion.size / 1024).toFixed(1)} KB)
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              Teaching material{" "}
              <span className="text-xs font-normal text-slate-500">
                (optional)
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <input
              type="file"
              accept=".txt,.md,.pdf,.docx"
              onChange={(e) => handleSingleFile(e, setTeachingMaterial)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
            {teachingMaterial && (
              <p className="mt-2 text-xs text-slate-500">
                Selected: {teachingMaterial.name} (
                {(teachingMaterial.size / 1024).toFixed(1)} KB)
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              Existing rubric or grading intentions{" "}
              <span className="text-xs font-normal text-slate-500">
                (optional)
              </span>
            </CardTitle>
            <CardDescription>
              Drop a file, paste text, or leave empty.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <input
              type="file"
              accept=".txt,.md,.pdf,.docx,application/json"
              onChange={(e) => handleSingleFile(e, setStartingRubricFile)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
            <textarea
              value={startingRubricInline}
              onChange={(e) => setStartingRubricInline(e.target.value)}
              placeholder="…or describe your grading intentions in a sentence."
              className="block min-h-[80px] w-full rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              Sample student copies{" "}
              <span className="text-xs font-normal text-slate-500">
                (optional)
              </span>
            </CardTitle>
            <CardDescription>
              Drop one or more files. With no copies the application uses
              synthetic responses (clearly labelled in the results).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <input
              type="file"
              multiple
              accept=".txt,.md,.pdf,.docx,image/*"
              onChange={handleMultiFile}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
            {studentCopies.length > 0 && (
              <p className="mt-2 text-xs text-slate-500">
                {studentCopies.length} file
                {studentCopies.length === 1 ? "" : "s"} selected
              </p>
            )}
          </CardContent>
        </Card>

        {startRun.isError && (
          <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            Could not start the run: {(startRun.error as Error).message}
          </p>
        )}

        <div className="flex justify-end">
          <Button type="submit" size="lg" disabled={!canSubmit}>
            {startRun.isPending ? "Uploading & starting…" : "Build my rubric"}
          </Button>
        </div>
      </form>
    </div>
  );
}
