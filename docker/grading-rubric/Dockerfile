# DR-DEP-03 — L2 task image for the L1 grading_rubric package + CLI.
#
# Self-contained: copies in only the L1 source tree, installs L1 via
# `pip install .`, and sets `grading-rubric-cli` as the entrypoint. No
# Validance imports, no host bind-mounts, no scripts copied at runtime.
# `docker run grading-rubric:latest <stage> --input … --output …` is the
# unit of single-stage invocation on Path A (§ 3.11).
#
# Build from the repository root:
#   docker build -t grading-rubric:latest -f docker/grading-rubric/Dockerfile .

FROM python:3.12-slim AS base

# Avoid stale .pyc files and buffered stdout/stderr in containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# System libraries needed by pdfplumber / pypdf / python-docx / Pillow.
# `libxml2` and `libxslt1.1` cover the python-docx XML stack; `libjpeg62-turbo`
# and `zlib1g` cover Pillow's image decoders for OCR-routed paths.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for the runtime stage. The image runs as `worker` so a
# misconfigured bind mount cannot trivially escalate to root.
RUN useradd --create-home --uid 1000 worker

WORKDIR /app

# Copy only the L1 surface — pyproject.toml, README, and the package itself.
# Tests, frontend, and the validance/ directory (when added by L3) are
# excluded via the .dockerignore at the build-context root.
COPY pyproject.toml README.md ./
COPY grading_rubric ./grading_rubric

# Install L1. `pip install .` consults pyproject.toml; per DR-DEP-02 the
# manifest does not depend on validance-sdk so the image is Validance-free.
RUN pip install .

# Default working directory for the CLI's --input / --output paths. Callers
# bind-mount their host workdir here when they want to read/write outside
# the image.
RUN mkdir -p /work && chown worker:worker /work
USER worker
WORKDIR /work

# DR-DEP-03: the CLI is installed as an executable.
# In Validance's ephemeral mode the worker runs `sleep infinity` then exec's
# `grading-rubric-cli <stage> …` via docker exec. Avoid ENTRYPOINT so the
# worker's startup command is not prefixed by the CLI binary.
# Direct invocation: `docker run grading-rubric:latest grading-rubric-cli <stage> …`
CMD ["grading-rubric-cli", "--help"]
