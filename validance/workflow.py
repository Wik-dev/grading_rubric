"""DR-INT-02 — Validance workflow definitions for the grading rubric pipeline.

Defines two workflows registered against a Validance instance:

  ``grading_rubric.assess_and_improve``
      The full assessment pipeline as one Validance task per L1 stage:

          ingest → parse_inputs → assess → propose → [gate] → score → render

      Where ``[gate]`` is an ``ApprovalGate`` (gate="human-confirm" on the
      preceding ``propose`` task per DR-INT-06) that pauses the run until the
      teacher accepts or rejects each ``ProposedChange`` in the L4 SPA.
      Each task wraps one L2 image CLI subcommand:
      ``docker run grading-rubric:latest <subcommand> --input … --output …``.
      The ``parse_inputs`` task uses ``trigger_inputs=True`` (ADR-007 § 9
      amendment) so it receives the staged PDFs/images for OCR alongside
      the structured ``ingest_outputs.json`` from the ``ingest`` task.

  ``grading_rubric.train_scorer``
      The standalone train-button capability per DR-SCR-06 / DR-DEP-06. One
      task wrapping ``grading-rubric-cli train-scorer``. Explicitly **not**
      chained into ``assess_and_improve`` because training has a different
      input contract (``TrainingEvidence``).

Per DR-INT-02 the Validance workflow definitions never call any L1 Python
function in-process. The only contact surface between L1 and L3 is:

  1. The CLI subcommand exit code.
  2. The structured ``--output`` file (a Pydantic model dumped to JSON).
  3. The structured stderr operation events (DR-OBS-01) which the harvester
     of DR-INT-05 consumes to build the typed ``AuditBundle`` view.
"""

from __future__ import annotations

from validance import Task, Workflow

# ── L2 image registry ──────────────────────────────────────────────────────
#
# The image must be built and pushed (or made locally available to the
# Validance worker) before ``register.py`` is run. See DR-DEP-03 + the
# Makefile ``images`` target. The tag is intentionally a single constant so
# that bumping the image is a one-line change.

TASK_IMAGE = "grading-rubric:latest"

# Model split:
#   Claude Sonnet 4 → OCR, planner (structured extraction at T=0.0)
#   Claude Opus 4.6 → rubric decomposition (hardest parsing task)
#   GPT-5.4 → grading simulation only (via GR_ASSESS_LLM_* override)
#
# Main defaults (anthropic + claude-sonnet-4-20250514 + claude-opus-4-6)
# come from Settings.from_env() with no override needed. The assess stage
# uses a separate backend/model so the measurement work runs on GPT-5.4.
LLM_ENV: dict[str, str] = {
    "GR_ASSESS_LLM_BACKEND": "openai",
    "GR_ASSESS_LLM_MODEL": "gpt-5.4",
}
LLM_SECRET_REFS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]

# ── Filename conventions inside each task's working directory ──────────────
#
# Validance mounts a fresh per-task work dir at ``/work``. Each task reads
# its inputs from ``/work/<filename>`` and writes its outputs there. The
# names are stable across the workflow so that ``inputs={...}`` declarations
# can use ``@previous_task:varname`` references symmetrically.
#
# The ingest task is special: it reads from ``inputs/`` (the ADR-007 staged
# directory populated by Validance from trigger ``input_files``) rather than
# a single JSON file.

INGEST_OUTPUTS_FILE = "ingest_outputs.json"
PARSED_INPUTS_FILE = "parsed_inputs.json"
ASSESS_OUTPUTS_FILE = "assess_outputs.json"
PROPOSE_OUTPUTS_FILE = "propose_outputs.json"
SCORE_OUTPUTS_FILE = "score_outputs.json"
EXPLAINED_RUBRIC_FILE = "explained_rubric.json"

TRAINING_EVIDENCE_FILE = "training_evidence.json"
TRAINED_ARTEFACT_FILE = "trained_scorer.json"


# ── grading_rubric.assess_and_improve ──────────────────────────────────────


def create_assess_and_improve_workflow() -> Workflow:
    """Build the six-stage pipeline as six Validance tasks.

    Task graph (linear, single critical path):

        ingest → parse_inputs → assess → propose → score → render

    Each task wraps one L1 CLI subcommand. The ``parse_inputs`` task uses
    ``trigger_inputs=True`` (ADR-007 § 9 amendment) so it receives the
    staged PDFs/images alongside the ``ingest_outputs.json`` from ingest.

    The ``propose`` task carries ``gate="human-confirm"`` per DR-INT-06: the
    Validance engine pauses the run after ``propose`` succeeds, surfaces the
    list of ``ProposedChange`` items to the L4 SPA via the polling endpoint
    of DR-INT-06, and only resumes ``score`` once the teacher has resolved
    every change. The teacher's accept/reject decisions are written back
    onto the ``ProposedChange.teacher_decision`` field by ``proposals.py``
    so the downstream ``render`` stage can reflect them in the explanation.

    Ingest files are provided through ADR-007 structured trigger
    ``input_files`` and staged under ``inputs/`` by the Validance engine.
    The ingest task uses ``--input-root inputs`` to scan the staged
    directory layout (``inputs/exam_question/*``, ``inputs/student_copy/*``,
    etc.) and build the L1 ``IngestInputs`` model internally. No workflow
    parameters are required — the SPA (DR-UI-04) uploads files and passes
    them as role-tagged ``input_files`` entries on the trigger payload.
    """

    wf = Workflow("grading_rubric.assess_and_improve")

    ingest = Task(
        name="ingest",
        docker_image=TASK_IMAGE,
        command=(
            "grading-rubric-cli ingest "
            "--input-root inputs "
            f"--output {INGEST_OUTPUTS_FILE}"
        ),
        inputs={},
        output_files={"ingest_outputs": INGEST_OUTPUTS_FILE},
        timeout=900,
    )

    # ADR-007 § 9 amendment: trigger_inputs=True so parse_inputs receives
    # the staged PDFs/images for OCR alongside the ingest_outputs.json.
    parse_inputs = Task(
        name="parse_inputs",
        docker_image=TASK_IMAGE,
        command=(
            "grading-rubric-cli parse-inputs "
            f"--input {INGEST_OUTPUTS_FILE} "
            f"--output {PARSED_INPUTS_FILE}"
        ),
        inputs={INGEST_OUTPUTS_FILE: "@ingest:ingest_outputs"},
        output_files={"parsed_inputs": PARSED_INPUTS_FILE},
        depends_on=["ingest"],
        trigger_inputs=True,
        timeout=1800,
        environment=LLM_ENV,
        secret_refs=LLM_SECRET_REFS,
    )

    assess = Task(
        name="assess",
        docker_image=TASK_IMAGE,
        command=(
            f"grading-rubric-cli assess "
            f"--input {PARSED_INPUTS_FILE} "
            f"--output {ASSESS_OUTPUTS_FILE}"
        ),
        inputs={PARSED_INPUTS_FILE: "@parse_inputs:parsed_inputs"},
        output_files={"assess_outputs": ASSESS_OUTPUTS_FILE},
        depends_on=["parse_inputs"],
        timeout=1800,
        environment=LLM_ENV,
        secret_refs=LLM_SECRET_REFS,
    )

    propose = Task(
        name="propose",
        docker_image=TASK_IMAGE,
        command=(
            f"grading-rubric-cli propose "
            f"--input {ASSESS_OUTPUTS_FILE} "
            f"--output {PROPOSE_OUTPUTS_FILE}"
        ),
        inputs={ASSESS_OUTPUTS_FILE: "@assess:assess_outputs"},
        output_files={"propose_outputs": PROPOSE_OUTPUTS_FILE},
        depends_on=["assess"],
        timeout=1800,
        environment=LLM_ENV,
        secret_refs=LLM_SECRET_REFS,
    )

    # DR-INT-06: ``gate="human-confirm"`` on score (not propose) because
    # the Validance engine fires the gate at task-start time, before the
    # CLI runs. Placing the gate on score means propose has already
    # completed and its output files are downloadable — the SPA can fetch
    # ``propose_outputs.json`` to show the teacher the proposed changes
    # during the approval phase. The teacher still reviews at the same
    # pipeline point (after propose, before scoring).
    score = Task(
        name="score",
        docker_image=TASK_IMAGE,
        command=(
            f"grading-rubric-cli score "
            f"--input {PROPOSE_OUTPUTS_FILE} "
            f"--output {SCORE_OUTPUTS_FILE}"
        ),
        inputs={PROPOSE_OUTPUTS_FILE: "@propose:propose_outputs"},
        output_files={"score_outputs": SCORE_OUTPUTS_FILE},
        depends_on=["propose"],
        timeout=1800,
        gate="human-confirm",
        gate_timeout=3600,
        environment=LLM_ENV,
        secret_refs=LLM_SECRET_REFS,
    )

    render = Task(
        name="render",
        docker_image=TASK_IMAGE,
        command=(
            f"grading-rubric-cli render "
            f"--input {SCORE_OUTPUTS_FILE} "
            f"--output {EXPLAINED_RUBRIC_FILE}"
        ),
        inputs={SCORE_OUTPUTS_FILE: "@score:score_outputs"},
        output_files={"explained_rubric": EXPLAINED_RUBRIC_FILE},
        depends_on=["score"],
        timeout=300,
    )

    for task in (ingest, parse_inputs, assess, propose, score, render):
        wf.add_task(task)

    return wf


# ── grading_rubric.train_scorer ────────────────────────────────────────────


def create_train_scorer_workflow() -> Workflow:
    """Build the standalone train-button workflow.

    A single task wrapping ``grading-rubric-cli train-scorer``. The L1 stub
    of DR-SCR-05 emits one ``ml_inference`` operation event with
    ``error.code = STUB_NOT_TRAINED`` and writes a placeholder
    ``TrainedScorerArtefact`` JSON. Wired as a separate workflow so the main
    demo path (DR-DEP-06) is unaffected.
    """

    wf = Workflow("grading_rubric.train_scorer")

    train = Task(
        name="train_scorer",
        docker_image=TASK_IMAGE,
        command=(
            f"grading-rubric-cli train-scorer "
            f"--input {TRAINING_EVIDENCE_FILE} "
            f"--output {TRAINED_ARTEFACT_FILE}"
        ),
        inputs={},  # training evidence provided via trigger input_files
        output_files={"trained_artefact": TRAINED_ARTEFACT_FILE},
        timeout=3600,
    )

    wf.add_task(train)
    return wf


# ── Registry ───────────────────────────────────────────────────────────────
#
# The registration script in ``register.py`` consumes this dict; keep it in
# sync when adding/removing workflows.

WORKFLOWS: dict[str, callable] = {
    "assess_and_improve": create_assess_and_improve_workflow,
    "train_scorer": create_train_scorer_workflow,
}


WORKFLOW_DESCRIPTIONS: dict[str, str] = {
    "assess_and_improve": (
        "Six-stage rubric assessment + improvement pipeline (6 Validance tasks) "
        "with a human-confirm approval gate after the propose stage "
        "(DR-INT-02 / DR-INT-06)."
    ),
    "train_scorer": (
        "Standalone train-button capability — DR-SCR-06 stub (does not call "
        "the LLM gateway; emits STUB_NOT_TRAINED and writes a placeholder "
        "TrainedScorerArtefact)."
    ),
}
