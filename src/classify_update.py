from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import json
import os


SOURCE_FIELDS = (
    "schemaVersion",
    "videoId",
    "fileName",
    "title",
    "published",
    "link",
    "description",
    "transcript",
)
REQUIRED_SOURCE_TEXT = (
    "videoId",
    "fileName",
    "title",
    "published",
    "link",
    "transcript",
)
OUTPUT_FIELDS = SOURCE_FIELDS + ("decision", "message")


@dataclass(frozen=True)
class Analysis:
    decision: str
    message: str


def _validate_source(payload: dict[str, object]) -> None:
    if tuple(payload) != SOURCE_FIELDS:
        raise RuntimeError("Transcript input must contain the exact schema v1 fields.")
    if payload["schemaVersion"] != 1:
        raise RuntimeError("Transcript input schemaVersion must be 1.")
    empty = [
        name
        for name in REQUIRED_SOURCE_TEXT
        if not isinstance(payload[name], str) or not payload[name].strip()
    ]
    if empty:
        raise RuntimeError(
            f"Transcript input has empty fields: {', '.join(empty)}"
        )
    if not isinstance(payload["description"], str):
        raise RuntimeError("Transcript input description must be a string.")


def build_prompt(payload: dict[str, object]) -> str:
    _validate_source(payload)
    return f"""You review one T-Minus365 YouTube video.

Determine whether it reports an actual Microsoft 365 or Azure product update,
feature announcement, rollout, retirement, deprecation, policy change, licensing
change, or roadmap change. The transcript is the primary source of truth. Use the
title and description only as supporting context.

Return SKIP for tutorials, how-to guides, security best-practice walkthroughs,
troubleshooting, MSP business advice, comparisons, commentary, opinion, reaction,
marketing, speculation, predictions, or content without a specific confirmed
Microsoft 365 or Azure change.

Use only facts explicitly stated in the supplied source. Do not invent dates,
availability, licensing, or details. If evidence is insufficient, choose SKIP.

Return exactly one JSON object and no other text:
- Eligible: {{"decision":"POST","message":"<final Teams message>"}}
- Ineligible: {{"decision":"SKIP","message":""}}

For POST, the message must use this structure:
📌 [Title]
🎥 T-Minus365 | 📅 [Published] | 🔗 [Link]
🏷️ Tag: [Microsoft 365, Azure, or Both]

Summary:
- [what changed — one line]
- [why it matters — one line]
- [availability/rollout — include this line only if explicitly stated]

No introduction, conclusion, hype, or mention of a transcript.

SOURCE
Title: {payload['title']}
Published: {payload['published']}
Link: {payload['link']}
Description: {payload['description']}
Transcript: {payload['transcript']}
"""


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def parse_model_output(raw: str) -> Analysis:
    try:
        value = json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError("Local model did not return valid JSON.") from error
    if not isinstance(value, dict):
        raise RuntimeError("Local model output must be a JSON object.")
    if tuple(value) != ("decision", "message"):
        raise RuntimeError("Local model output must contain decision and message only.")

    decision = value.get("decision")
    message = value.get("message")
    if decision not in {"POST", "SKIP"}:
        raise RuntimeError("Local model decision must be POST or SKIP.")
    if not isinstance(message, str):
        raise RuntimeError("Local model message must be a string.")
    message = message.strip()
    if decision == "POST" and not message:
        raise RuntimeError("Local model POST requires a message.")
    if decision == "SKIP" and message:
        raise RuntimeError("Local model SKIP message must be empty.")
    return Analysis(decision=decision, message=message)


def enrich_payload(
    payload: dict[str, object],
    analysis: Analysis,
) -> dict[str, object]:
    _validate_source(payload)
    if analysis.decision not in {"POST", "SKIP"}:
        raise RuntimeError("Analysis decision must be POST or SKIP.")
    if analysis.decision == "POST" and not analysis.message.strip():
        raise RuntimeError("Analysis POST requires a message.")
    if analysis.decision == "SKIP" and analysis.message:
        raise RuntimeError("Analysis SKIP message must be empty.")
    enriched = dict(payload)
    enriched["schemaVersion"] = 2
    enriched["decision"] = analysis.decision
    enriched["message"] = analysis.message.strip()
    if tuple(enriched) != OUTPUT_FIELDS:
        raise RuntimeError("Analysis output does not match schema v2.")
    return enriched


def _extract_chat_text(response: Any) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("Local model returned an unexpected response.") from error
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Local model returned an empty response.")
    return content


def predict_local(prompt: str, model_path: Path | str) -> str:
    try:
        from llama_cpp import Llama
    except ImportError as error:
        raise RuntimeError("llama-cpp-python is not installed.") from error

    resolved_model = Path(model_path)
    if not resolved_model.is_file():
        raise RuntimeError(f"Local model file does not exist: {resolved_model}")
    threads = max(1, min(os.cpu_count() or 1, 4))
    model = Llama(
        model_path=str(resolved_model),
        n_ctx=16384,
        n_threads=threads,
        n_batch=256,
        verbose=False,
    )
    response = model.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": "Follow the output JSON contract exactly.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    return _extract_chat_text(response)


def classify_file(
    path: Path | str,
    predictor: Callable[[str], str],
) -> Path:
    resolved_path = Path(path)
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read transcript JSON: {resolved_path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Transcript input must be a JSON object.")

    prompt = build_prompt(payload)
    analysis = parse_model_output(predictor(prompt))
    enriched = enrich_payload(payload, analysis)
    serialized = json.dumps(enriched, ensure_ascii=False, indent=2) + "\n"
    temporary_path = resolved_path.with_suffix(f"{resolved_path.suffix}.tmp")
    temporary_path.write_text(serialized, encoding="utf-8")
    temporary_path.replace(resolved_path)
    return resolved_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    arguments = parser.parse_args()
    result = classify_file(
        arguments.input,
        predictor=lambda prompt: predict_local(prompt, arguments.model),
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    print(f"ANALYSIS: {payload['decision']}")


if __name__ == "__main__":
    main()
