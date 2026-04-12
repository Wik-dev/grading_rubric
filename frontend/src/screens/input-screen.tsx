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
  type AssessAndImproveInputs,
  getHealth,
  startAssessAndImproveRun,
} from "@/lib/api";

interface FileLike {
  filename: string;
  text: string;
}

interface InputScreenProps {
  onRunStarted: (runId: string) => void;
}

async function readAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsText(file);
  });
}

/**
 * ui-draft.md § 4.1 — Input screen.
 *
 * Four input fields, three of them optional, one mandatory ("Exam
 * question"). On submit, the SPA assembles them into the L1 IngestInputs
 * shape and triggers `grading_rubric.assess_and_improve` via the Validance
 * REST API (DR-UI-04).
 */
export function InputScreen({ onRunStarted }: InputScreenProps) {
  const [examQuestion, setExamQuestion] = useState<FileLike | null>(null);
  const [teachingMaterial, setTeachingMaterial] = useState<FileLike | null>(
    null,
  );
  const [startingRubricFile, setStartingRubricFile] = useState<FileLike | null>(
    null,
  );
  const [startingRubricInline, setStartingRubricInline] = useState("");
  const [studentCopies, setStudentCopies] = useState<FileLike[]>([]);
  const [readError, setReadError] = useState<string | null>(null);

  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 10_000,
  });

  const startRun = useMutation({
    mutationFn: (inputs: AssessAndImproveInputs) =>
      startAssessAndImproveRun(inputs),
    onSuccess: (data) => onRunStarted(data.run_id),
  });

  const handleSingleFile = async (
    event: ChangeEvent<HTMLInputElement>,
    setter: (value: FileLike | null) => void,
  ) => {
    setReadError(null);
    const file = event.target.files?.[0];
    if (!file) {
      setter(null);
      return;
    }
    try {
      setter({ filename: file.name, text: await readAsText(file) });
    } catch (err) {
      setReadError(`Could not read ${file.name}: ${(err as Error).message}`);
    }
  };

  const handleMultiFile = async (event: ChangeEvent<HTMLInputElement>) => {
    setReadError(null);
    const files = Array.from(event.target.files ?? []);
    try {
      const out: FileLike[] = [];
      for (const file of files) {
        out.push({ filename: file.name, text: await readAsText(file) });
      }
      setStudentCopies(out);
    } catch (err) {
      setReadError(`Could not read student copies: ${(err as Error).message}`);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!examQuestion) {
      return;
    }
    const startingRubric: FileLike | null =
      startingRubricFile ??
      (startingRubricInline.trim()
        ? {
            filename: "starting_rubric.inline.txt",
            text: startingRubricInline,
          }
        : null);

    startRun.mutate({
      exam_question_text: examQuestion.text,
      exam_question_filename: examQuestion.filename,
      teaching_material_text: teachingMaterial?.text,
      teaching_material_filename: teachingMaterial?.filename,
      starting_rubric_text: startingRubric?.text,
      starting_rubric_filename: startingRubric?.filename,
      student_copies: studentCopies,
    });
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
              Drop a file or click to upload. Accepted: .txt .md .pdf
            </CardDescription>
          </CardHeader>
          <CardContent>
            <input
              type="file"
              accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
              onChange={(e) => handleSingleFile(e, setExamQuestion)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
            {examQuestion && (
              <p className="mt-2 text-xs text-slate-500">
                Loaded {examQuestion.filename} ({examQuestion.text.length} chars)
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
              accept=".txt,.md,.pdf"
              onChange={(e) => handleSingleFile(e, setTeachingMaterial)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
            {teachingMaterial && (
              <p className="mt-2 text-xs text-slate-500">
                Loaded {teachingMaterial.filename} (
                {teachingMaterial.text.length} chars)
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
              accept=".txt,.md,.pdf,application/json"
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
              accept=".txt,.md,.pdf,image/*"
              onChange={handleMultiFile}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
            {studentCopies.length > 0 && (
              <p className="mt-2 text-xs text-slate-500">
                {studentCopies.length} file
                {studentCopies.length === 1 ? "" : "s"} loaded
              </p>
            )}
          </CardContent>
        </Card>

        {readError && (
          <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {readError}
          </p>
        )}
        {startRun.isError && (
          <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            Could not start the run: {(startRun.error as Error).message}
          </p>
        )}

        <div className="flex justify-end">
          <Button type="submit" size="lg" disabled={!canSubmit}>
            {startRun.isPending ? "Starting…" : "Build my rubric"}
          </Button>
        </div>
      </form>
    </div>
  );
}
