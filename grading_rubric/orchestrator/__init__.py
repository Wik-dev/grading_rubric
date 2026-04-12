"""DR-ARC-04 — thin in-process stage chain (tests / `run-pipeline` only).

The in-process orchestrator is **not** a production execution surface; production
runs use Validance via the L3 integration directory. It exists so the V-model
unit / integration test layer (and the `run-pipeline` CLI subcommand for stage-
level inspection) can chain stages without spinning up Validance.
"""

from grading_rubric.orchestrator.pipeline import (
    PipelineInputs,
    PipelineOutputs,
    run_pipeline,
)
from grading_rubric.orchestrator.stage import Stage

__all__ = ["Stage", "PipelineInputs", "PipelineOutputs", "run_pipeline"]
