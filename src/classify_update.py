from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import json
import os
import sys


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

# Some T-Minus365 feed entries are long-form streams rather than short update
# videos (68k+ characters of transcript observed in practice). At the old
# n_ctx=16384, a transcript that size alone tokenizes to ~20-21k tokens,
# which overflows the model's context window before the system prompt,
# instructions, and JSON contract are even considered. llama.cpp evicts from
# the *front* of the prompt when that happens, so the instructions are what
# get dropped -- the model is left freeform-completing off the tail of the
# transcript with no idea it's supposed to classify anything or answer in
# Turkish. Capping the transcript keeps the full instructions inside the
# window regardless of video length; predict_local() also raises n_ctx for
# extra headroom. See the 2026-08-19 "Above the Stack" incident.
MAX_TRANSCRIPT_CHARS = 80_000

# Retries give the model a second/third chance when it returns malformed
# JSON or an off-contract message, instead of failing the whole GitHub
# Actions job (which previously produced a red X for nearly every run where
# the small local model hiccuped even slightly).
MAX_ATTEMPTS = 3

# A POST message that actually followed the prompt contract will always
# contain these Turkish structural markers and the real video link. If any
# are missing, the model drifted off-format (e.g. it hallucinated freeform
# English text instead of a structured Turkish summary) and the message
# must not be trusted, regardless of what "decision" it claimed.
REQUIRED_POST_MARKERS = ("📌", "🎥 T-Minus365", "🏷️ Etiket", "Özet:")


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


def _bounded_transcript(transcript: str, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    stripped = transcript.strip()
    if len(stripped) <= limit:
        return stripped
    return (
        stripped[:limit].rstrip()
        + "\n\n[transcript truncated for length; base your answer on the "
        "evidence above]"
    )


def build_prompt(payload: dict[str, object]) -> str:
    _validate_source(payload)
    return f"""You review one T-Minus365 YouTube video and always produce a
Teams post for it. There is no SKIP option -- every video gets a message,
and that message must always summarize what the video actually covers.

First, determine whether the video reports specific, confirmed Microsoft 365
or Azure product updates, feature announcements, rollouts, retirements,
deprecations, policy changes, licensing changes, or roadmap changes, as
opposed to a tutorial, opinion piece, marketing, or unrelated business
content. The transcript is the primary source of truth for both this
determination and the summary below. Use the title and description only as
supporting context.

Use only facts explicitly stated in the supplied source. Do not invent dates,
availability, licensing, or details.

Return exactly one JSON object and no other text:
{{"decision":"POST","message":"<final Teams message>"}}

The "decision" field must always be the literal string "POST".

Write the Teams message in Turkish. Keep the video title exactly as
supplied in SOURCE; do not translate or rewrite it. Product names, the URL, and
the published date must also remain unchanged. Use this structure:
📌 [Original Title]
🎥 T-Minus365 | 📅 [Published] | 🔗 [Link]
🏷️ Etiket: [Microsoft 365, Azure, Her İkisi veya Yok]

Özet:
- [her zaman doldurulur: transkriptte anlatılan somut konuların/güncelleme-
   lerin Türkçe özeti. Bir video birden fazla ayrı konuyu/güncellemeyi
   kapsıyorsa, her biri kendi maddesinde yer almalı -- tek bir maddeye
   sıkıştırmayın]
- [belirtilmişse: kullanıma sunulma/yayın takvimi, hangi ürün/plan/rol için
   olduğu gibi ek somut detaylar, her biri ayrı bir maddede]

The "Özet" section must NEVER collapse to a single generic line just because
the video is a roundup of many small items, uses casual/imprecise language,
or is only loosely related to Microsoft 365. Summarize everything concrete
that is actually said, even when none of it amounts to one single official
announcement. Only leave "Özet" with nothing to report when the transcript
truly contains no discernible topic at all (e.g. it is empty or pure
filler).

If the video does NOT report a confirmed Microsoft 365 or Azure product
update, set the tag to "Yok" and make the FIRST bullet under "Özet:" this
exact line, then immediately continue with additional bullets summarizing
everything the video actually covers, exactly as you would for any other
video:
- M365 hakkında bir gelişme/bilgi yok
Do not stop after that line. Only that single line, with no further
bullets, is acceptable when the transcript genuinely has no content to
summarize.

Apart from the original title and unchanged proper nouns/data specified above,
all human-readable message text must be Turkish. Do not add an introduction,
conclusion, hype, or mention of a transcript.

SOURCE
Title: {payload['title']}
Published: {payload['published']}
Link: {payload['link']}
Description: {payload['description']}
Transcript: {_bounded_transcript(str(payload['transcript']))}
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
    if not {"decision", "message"}.issubset(value):
        raise RuntimeError("Local model output must contain decision and message.")

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


def _looks_like_contract_message(message: str, link: str) -> bool:
    """Defense-in-depth: confirm a POST message actually followed the
    required Turkish/structured format instead of drifting into unrelated
    freeform text. Catches cases where the model's JSON was syntactically
    valid (so parse_model_output happily accepted it) but the content
    itself ignored every instruction in the prompt.
    """
    if not all(marker in message for marker in REQUIRED_POST_MARKERS):
        return False
    if link not in message:
        return False
    return True


def _fallback_message(payload: dict[str, object]) -> str:
    """Every video must produce a POST now, with no exceptions. If the local
    model fails every retry attempt, this builds the message directly from
    the trusted payload fields instead of leaving the video unpublished --
    it can never hallucinate the title/date/link because it doesn't touch
    the model at all.

    It still surfaces the video's own YouTube description (when present)
    as a second bullet, so a repeated model failure doesn't silently
    discard every bit of information about what the video covers -- only
    the "is this a confirmed M365/Azure update" judgment call is skipped,
    since that genuinely requires reading the transcript.
    """
    description = str(payload.get("description", "")).strip()
    bullets = [
        "- M365 hakkında bir gelişme/bilgi yok "
        "(otomatik sınıflandırma başarısız oldu; video incelenemedi)"
    ]
    if description:
        bullets.append(f"- Video açıklaması (YouTube): {description}")
    return (
        f"📌 {payload['title']}\n"
        f"🎥 T-Minus365 | 📅 {payload['published']} | 🔗 {payload['link']}\n"
        "🏷️ Etiket: Yok\n\n"
        "Özet:\n" + "\n".join(bullets)
    )


def _validated_analysis(raw: str, link: str) -> Analysis:
    analysis = parse_model_output(raw)
    if analysis.decision != "POST":
        raise RuntimeError(
            "Every video must be posted; local model returned "
            f"{analysis.decision!r} instead of POST."
        )
    if not _looks_like_contract_message(analysis.message, link):
        raise RuntimeError(
            "Local model returned a POST message that did not follow the "
            "required Turkish/structured contract; discarding this attempt."
        )
    return analysis


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


def predict_local(
    prompt: str,
    model_path: Path | str,
    temperature: float = 0.0,
) -> str:
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
        n_ctx=32768,
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
        temperature=temperature,
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    return _extract_chat_text(response)


def classify_file(
    path: Path | str,
    predictor: Callable[[str], str],
    max_attempts: int = MAX_ATTEMPTS,
) -> Path:
    resolved_path = Path(path)
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read transcript JSON: {resolved_path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Transcript input must be a JSON object.")

    prompt = build_prompt(payload)
    link = str(payload.get("link", ""))

    analysis: Analysis | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            analysis = _validated_analysis(predictor(prompt), link)
            break
        except RuntimeError as error:
            print(
                f"WARNING: classification attempt {attempt}/{max_attempts} "
                f"failed: {error}",
                file=sys.stderr,
            )

    if analysis is None:
        print(
            "WARNING: local model failed every classification attempt for "
            f"{payload.get('videoId', '?')}; using a deterministic fallback "
            "message so the video is still published as required.",
            file=sys.stderr,
        )
        analysis = Analysis(decision="POST", message=_fallback_message(payload))

    enriched = enrich_payload(payload, analysis)
    serialized = json.dumps(enriched, ensure_ascii=False, indent=2) + "\n"
    temporary_path = resolved_path.with_suffix(f"{resolved_path.suffix}.tmp")
    temporary_path.write_text(serialized, encoding="utf-8")
    temporary_path.replace(resolved_path)
    return resolved_path


def _local_predictor(model_path: Path) -> Callable[[str], str]:
    call_count = 0

    def predict(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        # First attempt stays deterministic (temperature=0); if that
        # attempt's output gets rejected (bad JSON or off-contract
        # message), retries add a little randomness so the model has a
        # real chance of landing somewhere different instead of
        # regenerating byte-identical output.
        temperature = 0.0 if call_count == 1 else 0.4
        return predict_local(prompt, model_path, temperature=temperature)

    return predict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    arguments = parser.parse_args()
    result = classify_file(
        arguments.input,
        predictor=_local_predictor(arguments.model),
    )
    payload = json.loads(result.read_text(encoding="utf-8"))
    print(f"ANALYSIS: {payload['decision']}")


if __name__ == "__main__":
    main()
