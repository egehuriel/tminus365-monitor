from datetime import datetime
from pathlib import Path
import json


DEFAULT_OUTBOX_PATH = Path("outbox/latest.json")
EXACT_FIELDS = (
    "schemaVersion",
    "videoId",
    "fileName",
    "title",
    "published",
    "link",
    "description",
    "transcript",
)
REQUIRED_TEXT_FIELDS = (
    "videoId",
    "fileName",
    "title",
    "published",
    "link",
    "transcript",
)


def file_name_for(published: str, video_id: str) -> str:
    clean_video_id = video_id.strip()
    if not clean_video_id:
        raise RuntimeError("Video ID is required for transcript export.")
    try:
        instant = datetime.fromisoformat(published.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("Published timestamp is not valid ISO 8601.") from error
    return f"{instant.date().isoformat()}_{clean_video_id}.json"


def build_payload(
    *,
    video_id: str,
    title: str,
    published: str,
    link: str,
    description: str,
    transcript: str,
) -> dict[str, object]:
    values = {
        "videoId": video_id.strip(),
        "title": title.strip(),
        "published": published.strip(),
        "link": link.strip(),
        "transcript": transcript.strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            f"Transcript export has empty fields: {', '.join(missing)}"
        )
    return {
        "schemaVersion": 1,
        "videoId": values["videoId"],
        "fileName": file_name_for(values["published"], values["videoId"]),
        "title": values["title"],
        "published": values["published"],
        "link": values["link"],
        "description": description.strip(),
        "transcript": values["transcript"],
    }


def _validate_payload(payload: dict[str, object]) -> None:
    if tuple(payload.keys()) != EXACT_FIELDS:
        raise RuntimeError("Transcript export must contain the exact fields in order.")
    if payload["schemaVersion"] != 1:
        raise RuntimeError("Transcript export schemaVersion must be 1.")
    empty = [
        name
        for name in REQUIRED_TEXT_FIELDS
        if not isinstance(payload[name], str) or not payload[name].strip()
    ]
    if empty:
        raise RuntimeError(
            f"Transcript export has empty fields: {', '.join(empty)}"
        )
    if not isinstance(payload["description"], str):
        raise RuntimeError("Transcript export description must be a string.")
    expected_file_name = file_name_for(
        str(payload["published"]),
        str(payload["videoId"]),
    )
    if payload["fileName"] != expected_file_name:
        raise RuntimeError("Transcript export fileName does not match its metadata.")


def serialize_payload(payload: dict[str, object]) -> str:
    _validate_payload(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write_latest(
    payload: dict[str, object],
    path: Path | str = DEFAULT_OUTBOX_PATH,
) -> Path:
    resolved_path = Path(path)
    serialized = serialize_payload(payload)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = resolved_path.with_suffix(f"{resolved_path.suffix}.tmp")
    temporary_path.write_text(serialized, encoding="utf-8")
    temporary_path.replace(resolved_path)
    return resolved_path
