from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import inspect
import json
import unittest

from src import check_feed


def sample_entry(**overrides):
    entry = {
        "yt_videoid": "abc123xyz89",
        "title": "Latest T-Minus365 video",
        "published": "2026-08-12T08:00:00+00:00",
        "link": "https://www.youtube.com/watch?v=abc123xyz89",
        "summary": "A useful description.",
    }
    entry.update(overrides)
    return entry


class FakeHttpResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class FakeRawResponse(FakeHttpResponse):
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status


class CheckFeedTests(unittest.TestCase):
    def test_check_feed_module_exists(self):
        module_path = Path(__file__).parents[1] / "src" / "check_feed.py"
        self.assertTrue(module_path.is_file())

    def test_get_latest_video_returns_normalized_video(self):
        self.assertTrue(hasattr(check_feed, "get_latest_video"))
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        video = check_feed.get_latest_video(
            parser=lambda _: parsed_feed,
        )

        self.assertEqual(video.id, "abc123xyz89")
        self.assertEqual(video.title, "Latest T-Minus365 video")
        self.assertEqual(video.published, "2026-08-12T08:00:00+00:00")
        self.assertEqual(
            video.link,
            "https://www.youtube.com/watch?v=abc123xyz89",
        )
        self.assertEqual(video.description, "A useful description.")

    def test_parse_feed_reads_youtube_atom_entry(self):
        document = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:media="http://search.yahoo.com/mrss/"
              xmlns:yt="http://www.youtube.com/xml/schemas/2015">
          <entry>
            <yt:videoId>abc123xyz89</yt:videoId>
            <title>Latest T-Minus365 video</title>
            <published>2026-08-12T08:00:00+00:00</published>
            <link rel="alternate"
                  href="https://www.youtube.com/watch?v=abc123xyz89" />
            <media:group>
              <media:description>A useful description.</media:description>
            </media:group>
          </entry>
        </feed>"""

        try:
            feed = check_feed.parse_feed(
                "https://example.test/feed.xml",
                opener=lambda _request, timeout: FakeRawResponse(document),
            )
        except Exception as error:
            self.fail(f"Expected a parsed YouTube feed, got {error!r}")
        video = check_feed.get_latest_video(parser=lambda _: feed)

        self.assertEqual(
            video,
            check_feed.Video(
                id="abc123xyz89",
                title="Latest T-Minus365 video",
                published="2026-08-12T08:00:00+00:00",
                link="https://www.youtube.com/watch?v=abc123xyz89",
                description="A useful description.",
            ),
        )

    def test_get_latest_video_rejects_http_failure(self):
        parsed_feed = SimpleNamespace(status=404, entries=[sample_entry()])

        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            check_feed.get_latest_video(parser=lambda _: parsed_feed)

    def test_get_latest_video_rejects_empty_feed(self):
        parsed_feed = SimpleNamespace(status=200, entries=[])

        try:
            check_feed.get_latest_video(parser=lambda _: parsed_feed)
        except Exception as error:
            self.assertIsInstance(error, RuntimeError)
            self.assertRegex(str(error), "No videos found")
        else:
            self.fail("Expected an empty feed to raise RuntimeError")

    def test_get_latest_video_rejects_missing_video_id(self):
        parsed_feed = SimpleNamespace(
            status=200,
            entries=[sample_entry(yt_videoid="")],
        )

        with self.assertRaisesRegex(RuntimeError, "no YouTube video ID"):
            check_feed.get_latest_video(parser=lambda _: parsed_feed)

    def test_get_transcript_joins_nonempty_snippets(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeHttpResponse(
                {"content": " First line  Second line ", "lang": "en"}
            )

        transcript = check_feed.get_transcript(
            "abc123xyz89",
            api_key="secret-value",
            opener=opener,
        )

        self.assertEqual(transcript, "First line  Second line")
        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(
            query,
            {
                "url": ["https://www.youtube.com/watch?v=abc123xyz89"],
                "lang": ["en"],
                "text": ["true"],
                "mode": ["native"],
            },
        )
        self.assertEqual(request.get_header("X-api-key"), "secret-value")
        self.assertEqual(timeout, 30)

    def test_get_transcript_accepts_supadata_collaborators(self):
        parameters = inspect.signature(check_feed.get_transcript).parameters

        self.assertIn("api_key", parameters)
        self.assertIn("opener", parameters)

    def test_get_transcript_rejects_empty_text(self):
        def opener(_request, timeout):
            self.assertEqual(timeout, 30)
            return FakeHttpResponse({"content": "  ", "lang": "en"})

        with self.assertRaisesRegex(RuntimeError, "Transcript is empty"):
            check_feed.get_transcript(
                "abc123xyz89",
                api_key="secret-value",
                opener=opener,
            )

    def test_get_transcript_requires_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "SUPADATA_API_KEY"):
            check_feed.get_transcript("abc123xyz89", api_key="")

    def test_run_formats_video_metadata_and_transcript(self):
        self.assertTrue(hasattr(check_feed, "run"))
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        def opener(_request, timeout):
            self.assertEqual(timeout, 30)
            return FakeHttpResponse({"content": "Cloud transcript works"})

        output = check_feed.run(
            parser=lambda _: parsed_feed,
            api_key="secret-value",
            opener=opener,
            state_path=None,
        )

        self.assertIn("TITLE:\nLatest T-Minus365 video", output)
        self.assertIn("VIDEO ID:\nabc123xyz89", output)
        self.assertIn(
            "LINK:\nhttps://www.youtube.com/watch?v=abc123xyz89",
            output,
        )
        self.assertIn("TRANSCRIPT:\nCloud transcript works", output)

    def test_main_prints_runner_output(self):
        self.assertTrue(hasattr(check_feed, "main"))
        output = StringIO()

        with redirect_stdout(output):
            check_feed.main(runner=lambda: "Cloud transcript works")

        self.assertEqual(output.getvalue(), "Cloud transcript works\n")


if __name__ == "__main__":
    unittest.main()
