from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import os
import xml.etree.ElementTree as ElementTree


FEED_URL = (
    "https://www.youtube.com/feeds/videos.xml"
    "?channel_id=UCePaXDDk5kl3g7FcJ5gH5AQ"
)
SUPADATA_TRANSCRIPT_URL = "https://api.supadata.ai/v1/transcript"
DEFAULT_STATE_PATH = Path("state/last_video_id.txt")
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
MEDIA_NAMESPACE = "http://search.yahoo.com/mrss/"
YOUTUBE_NAMESPACE = "http://www.youtube.com/xml/schemas/2015"


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    published: str
    link: str
    description: str


def parse_feed(
    feed_url: str,
    opener: Callable[..., Any] = urlopen,
) -> Any:
    request = Request(
        feed_url,
        headers={"User-Agent": "tminus365-monitor/1.0"},
    )
    try:
        with opener(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            document = response.read()
    except HTTPError as error:
        return SimpleNamespace(status=error.code, entries=[])
    except (URLError, OSError) as error:
        raise RuntimeError(f"YouTube feed request failed: {error}") from error

    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise RuntimeError(f"YouTube feed returned invalid XML: {error}") from error

    entries = []
    for element in root.findall(f"{{{ATOM_NAMESPACE}}}entry"):
        link = next(
            (
                item.get("href", "")
                for item in element.findall(f"{{{ATOM_NAMESPACE}}}link")
                if item.get("rel") == "alternate"
            ),
            "",
        )
        entries.append(
            {
                "yt_videoid": element.findtext(
                    f"{{{YOUTUBE_NAMESPACE}}}videoId",
                    default="",
                ),
                "title": element.findtext(
                    f"{{{ATOM_NAMESPACE}}}title",
                    default="",
                ),
                "published": element.findtext(
                    f"{{{ATOM_NAMESPACE}}}published",
                    default="",
                ),
                "link": link,
                "summary": element.findtext(
                    f"{{{MEDIA_NAMESPACE}}}group/"
                    f"{{{MEDIA_NAMESPACE}}}description",
                    default="",
                ),
            }
        )

    return SimpleNamespace(status=status, entries=entries)


def get_latest_video(
    feed_url: str = FEED_URL,
    parser: Callable[[str], Any] = parse_feed,
) -> Video:
    feed = parser(feed_url)
    status = getattr(feed, "status", None)
    if status is not None and status >= 400:
        raise RuntimeError(f"YouTube feed request failed with HTTP {status}.")

    entries = getattr(feed, "entries", None) or []
    if not entries:
        raise RuntimeError("No videos found in the T-Minus365 feed.")

    entry = entries[0]
    video_id = str(entry.get("yt_videoid", "")).strip()
    title = str(entry.get("title", "")).strip()
    published = str(entry.get("published", "")).strip()
    link = str(entry.get("link", "")).strip()

    if not video_id:
        raise RuntimeError("Latest feed entry has no YouTube video ID.")
    if not title or not published or not link:
        raise RuntimeError("Latest feed entry is missing required metadata.")

    return Video(
        id=video_id,
        title=title,
        published=published,
        link=link,
        description=str(entry.get("summary", "")).strip(),
    )


def _get_json(
    request: Request,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    try:
        with opener(request, timeout=30) as response:
            payload = response.read()
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace").strip()
        suffix = f": {details}" if details else ""
        raise RuntimeError(
            f"Supadata transcript request failed with HTTP {error.code}{suffix}"
        ) from error
    except (URLError, OSError) as error:
        raise RuntimeError(f"Supadata transcript request failed: {error}") from error

    try:
        result = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("Supadata returned invalid JSON.") from error
    if not isinstance(result, dict):
        raise RuntimeError("Supadata returned an unexpected response.")
    return result


def get_transcript(
    video_id: str,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> str:
    resolved_api_key = (api_key or os.environ.get("SUPADATA_API_KEY", "")).strip()
    if not resolved_api_key:
        raise RuntimeError("SUPADATA_API_KEY is not configured.")

    query = urlencode(
        {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "lang": "en",
            "text": "true",
            "mode": "native",
        }
    )
    request = Request(
        f"{SUPADATA_TRANSCRIPT_URL}?{query}",
        headers={
            "Accept": "application/json",
            "x-api-key": resolved_api_key,
        },
    )
    result = _get_json(request, opener)
    content = result.get("content", "")
    if isinstance(content, list):
        transcript = " ".join(
            text
            for item in content
            if isinstance(item, dict)
            and (text := str(item.get("text", "")).strip())
        )
    else:
        transcript = str(content).strip()

    if not transcript:
        if result.get("jobId"):
            raise RuntimeError(
                "Supadata returned an asynchronous transcript job; "
                "polling is not implemented yet."
            )
        raise RuntimeError(f"Transcript is empty for video {video_id}.")
    return transcript


def format_output(video: Video, transcript: str) -> str:
    return "\n\n".join(
        [
            f"TITLE:\n{video.title}",
            f"PUBLISHED:\n{video.published}",
            f"LINK:\n{video.link}",
            f"VIDEO ID:\n{video.id}",
            f"DESCRIPTION:\n{video.description}",
            f"TRANSCRIPT:\n{transcript}",
        ]
    )


def format_already_processed(video: Video) -> str:
    return "\n\n".join(
        [
            "STATUS:\nALREADY PROCESSED",
            f"TITLE:\n{video.title}",
            f"PUBLISHED:\n{video.published}",
            f"LINK:\n{video.link}",
            f"VIDEO ID:\n{video.id}",
        ]
    )


def run(
    feed_url: str = FEED_URL,
    parser: Callable[[str], Any] = parse_feed,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
    state_path: Path | str | None = DEFAULT_STATE_PATH,
) -> str:
    video = get_latest_video(feed_url=feed_url, parser=parser)
    resolved_state_path = Path(state_path) if state_path is not None else None
    if resolved_state_path is not None and resolved_state_path.is_file():
        processed_video_id = resolved_state_path.read_text(
            encoding="utf-8"
        ).strip()
        if processed_video_id == video.id:
            return format_already_processed(video)

    transcript = get_transcript(video.id, api_key=api_key, opener=opener)
    if resolved_state_path is not None:
        resolved_state_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_state_path.write_text(f"{video.id}\n", encoding="utf-8")
    return format_output(video, transcript)


def main(runner: Callable[[], str] = run) -> None:
    print(runner())


if __name__ == "__main__":
    main()
