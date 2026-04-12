"""Grading Rubric Studio — L1 hermetic Python package.

DR-ARC-12: the public Python surface is exactly what this `__init__` re-exports —
the in-process orchestrator entry point, the per-stage callables, the public
`models`, and the `Settings` class. Anything else is internal and may change
without a schema-version bump. The L3 integration directory imports only this
public surface (and `validance-sdk`).
"""

from grading_rubric import models
from grading_rubric.config.settings import Settings

__all__ = ["models", "Settings", "__version__"]
__version__ = "0.1.0"
