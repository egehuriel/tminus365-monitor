# Local Update Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich each new transcript with a validated local-model `POST`/`SKIP` decision and final Teams message.

**Architecture:** Keep transcript export as schema v1, then run a separate classifier only for a changed/forced export. The classifier calls a cached Qwen GGUF through llama.cpp and atomically writes schema v2; any model or validation error fails closed.

**Tech Stack:** Python 3.12, `llama-cpp-python` 0.3.19, Qwen2.5-1.5B-Instruct Q4_K_M GGUF, GitHub Actions, `unittest`.

## Global Constraints

- No AI Builder, hosted LLM API, paid HTTP connector, or new secret.
- Preserve the existing transcript fields and public-repository behavior.
- Run model setup only for a new or manually forced export.
- Never turn an inference error into `SKIP`.
- Output only `POST` or `SKIP`; `SKIP` has an empty `message`.

---

### Task 1: Classifier contract and parser

**Files:**
- Create: `src/classify_update.py`
- Create: `tests/test_classify_update.py`

**Interfaces:**
- Consumes: schema-version-1 `dict[str, object]` and raw model text.
- Produces: `build_prompt(payload) -> str`, `parse_model_output(raw) -> Analysis`, and `enrich_payload(payload, analysis) -> dict[str, object]`.

- [ ] **Step 1: Write failing tests** for strict input validation, `SKIP`, `POST`, malformed model JSON, exact v2 fields, and atomic file output.
- [ ] **Step 2: Run `python3 -m unittest tests.test_classify_update -v`** and confirm import/symbol failures.
- [ ] **Step 3: Implement the minimal pure functions and CLI**; import llama.cpp only inside the real predictor so unit tests remain network-free.
- [ ] **Step 4: Run `python3 -m unittest tests.test_classify_update -v`** and confirm all classifier tests pass.

### Task 2: Conditional GitHub Actions inference

**Files:**
- Create: `requirements-ai.txt`
- Modify: `.github/workflows/check-videos.yml`
- Modify: `tests/test_workflow.py`

**Interfaces:**
- Consumes: whether `outbox/latest.json` changed or `force_export` is true.
- Produces: cached model setup plus `python src/classify_update.py outbox/latest.json --model ...` before publication.

- [ ] **Step 1: Write failing workflow behavior tests** that load YAML and assert the detection output gates cache, dependency install, model download, and classification.
- [ ] **Step 2: Run `python3 -m unittest tests.test_workflow -v`** and confirm the new assertions fail.
- [ ] **Step 3: Add the cache/setup/download/classification steps**, pin model and Python dependency versions, and raise the job timeout to 20 minutes.
- [ ] **Step 4: Run `python3 -m unittest discover -s tests -v`** and confirm the full suite passes.

### Task 3: Cloud proof and Power Automate handoff

**Files:**
- Modify: `docs/power-automate-standard-importer.md`

**Interfaces:**
- Consumes: committed schema-version-2 `outbox/latest.json`.
- Produces: exact Power Automate schema and `decision`/`message` mappings.

- [ ] **Step 1: Document the v2 schema and replacement of AI Builder** with a simple condition plus Teams action.
- [ ] **Step 2: Run syntax checks and the full unit suite**, then inspect `git diff --check`.
- [ ] **Step 3: Commit and push the implementation**, manually dispatch with `force_export=true`, and watch the run to completion.
- [ ] **Step 4: Inspect the committed JSON** and verify `schemaVersion`, `decision`, and `message` without exposing secrets.
