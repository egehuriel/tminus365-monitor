# T-Minus365 Local Update Classifier Design

## Goal

Classify each newly exported T-Minus365 transcript without AI Builder, paid HTTP
connectors, or a hosted LLM API. GitHub Actions must publish a self-contained JSON
document that Power Automate can route directly to Teams.

## Architecture

The existing transcript collector remains the first stage and continues to emit
the strict schema-version-1 document. A second Python program runs only when the
collector changed `outbox/latest.json` (or a manual force-export was requested).
It loads Qwen2.5-1.5B-Instruct Q4_K_M through `llama-cpp-python`, asks for a strict
JSON decision, validates the response, and atomically upgrades the document to
schema version 2.

Schema version 2 preserves all version-1 fields and appends:

- `decision`: exactly `POST` or `SKIP`;
- `message`: the final Teams message for `POST`, otherwise an empty string.

The official GGUF model is cached by GitHub Actions. Model dependencies and the
model file are downloaded only when classification is required, so ordinary
30-minute checks that find no new video remain lightweight.

## Classification Rules

The transcript is the primary source. Title and description are supporting
context only. Tutorials, how-to guides, best-practice walkthroughs, business
advice, comparisons, opinion, reaction, marketing, speculation, and content
without an explicit Microsoft 365 or Azure change produce `SKIP`.

An eligible product update produces `POST` and a plain professional message with
the title, publication date, source link, product tag, what changed, why it
matters, and a rollout line only when the source explicitly states one.

## Failure Behavior

Malformed input, missing required source fields, an unavailable model, inference
failure, malformed model JSON, or an invalid decision fails the workflow. It must
never silently convert an analysis error into `SKIP`. Because the state file is
committed only after the whole job succeeds, the next run can retry the video.

## Power Automate Boundary

Power Automate no longer calls AI Builder. It parses schema version 2, checks
`decision == POST`, and sends `message` to Teams. Transcript acquisition and
OneDrive deduplication remain unchanged.
