from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import feedparser
from youtube_transcript_api import YouTubeTranscriptApi


FEED_URL = (
    "https://www.youtube.com/feeds/videos.xml"
    "?channel_id=UCePaXDDk5kl3g7FcJ5gH5AQ"
)


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    published: str
    link: str
    description: str


def get_latest_video(
    feed_url: str = FEED_URL,
    parser: Callable[[str], Any] = feedparser.parse,
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


def get_transcript(
    video_id: str,
    api_factory: Callable[[], Any] = YouTubeTranscriptApi,
) -> str:
    snippets = api_factory().fetch(video_id, languages=["en"])
    transcript = " ".join(
        text
        for snippet in snippets
        if (text := str(snippet.text).strip())
    )
    if not transcript:
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


def run(
    feed_url: str = FEED_URL,
    parser: Callable[[str], Any] = feedparser.parse,
    api_factory: Callable[[], Any] = YouTubeTranscriptApi,
) -> str:
    video = get_latest_video(feed_url=feed_url, parser=parser)
    transcript = get_transcript(video.id, api_factory=api_factory)
    return format_output(video, transcript)


def main(runner: Callable[[], str] = run) -> None:
    print(runner())


if __name__ == "__main__":
    main()
