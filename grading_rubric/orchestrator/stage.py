"""DR-ARC-03 *Stage protocol*.

Every pipeline stage exposes a single callable entry point conforming to:

    (stage_inputs, settings, audit_emitter) -> stage_outputs

Stage entry points are pure with respect to global state — no module-level
mutable state, no implicit caches, no environment reads outside the injected
`settings`. Filesystem I/O is restricted to (a) reading paths declared on
`stage_inputs` (with the `parsers` carve-out for reading user-supplied input
files at well-known locations) and (b) writing through the `audit_emitter`
or to the per-stage CLI `--output` path that the caller specifies.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings

I = TypeVar("I", bound=BaseModel, contravariant=True)
O = TypeVar("O", bound=BaseModel, covariant=True)


class Stage(Protocol, Generic[I, O]):
    """The shape every stage callable conforms to."""

    stage_id: str

    def __call__(
        self,
        stage_inputs: I,
        *,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> O: ...
