# Grading Rubric Studio — make targets (DR-DEP-05).
# The Makefile is the single entry-point surface for installing, building,
# registering, and exercising the deliverable. There is no `run` target —
# there is no custom HTTP server in the L1 deliverable (DR-ARC-10).

PY ?= python3
DOCKER ?= docker
IMAGE_NAME ?= grading-rubric:latest
VALIDANCE_BASE_URL ?= http://localhost:8001

.PHONY: help install images register schemas build dev test lint clean

help:
	@echo "Targets:"
	@echo "  install    pip install -e .[dev]                              (L1)"
	@echo "  images     build all L2 Docker images                        (DR-DEP-03)"
	@echo "  register   register L3 workflows against VALIDANCE_BASE_URL  (DR-INT-07)"
	@echo "  schemas    regenerate schemas/*.json + TS codegen            (DR-DAT-03/04)"
	@echo "  build      build the L4 SPA (frontend/)"
	@echo "  dev        run the L4 SPA dev server"
	@echo "  test       run the unit / integration suites                 (DR-DEP-09)"
	@echo "  lint       run ruff check"
	@echo "  clean      remove caches"

install:
	$(PY) -m pip install -e .[dev]

images:
	$(DOCKER) build -t $(IMAGE_NAME) -f docker/grading-rubric/Dockerfile .

register:
	VALIDANCE_BASE_URL=$(VALIDANCE_BASE_URL) $(PY) -m validance.register

schemas:
	$(PY) -m grading_rubric.models.codegen schemas/

build:
	cd frontend && npm run build

dev:
	cd frontend && npm run dev

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check grading_rubric tests

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
