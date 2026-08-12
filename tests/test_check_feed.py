from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
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


class FakeTranscriptApi:
    def __init__(self, snippets):
        self.snippets = snippets
        self.calls = []

    def fetch(self, video_id, languages):
        self.calls.append((video_id, languages))
        return self.snippets


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
        self.assertTrue(hasattr(check_feed, "get_transcript"))
        api = FakeTranscriptApi(
            [
                SimpleNamespace(text=" First line "),
                SimpleNamespace(text=""),
                SimpleNamespace(text="Second line"),
            ]
        )

        transcript = check_feed.get_transcript(
            "abc123xyz89",
            api_factory=lambda: api,
        )

        self.assertEqual(transcript, "First line Second line")
        self.assertEqual(api.calls, [("abc123xyz89", ["en"])])

    def test_get_transcript_rejects_empty_text(self):
        api = FakeTranscriptApi([SimpleNamespace(text="  ")])

        with self.assertRaisesRegex(RuntimeError, "Transcript is empty"):
            check_feed.get_transcript(
                "abc123xyz89",
                api_factory=lambda: api,
            )

    def test_run_formats_video_metadata_and_transcript(self):
        self.assertTrue(hasattr(check_feed, "run"))
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])
        api = FakeTranscriptApi([SimpleNamespace(text="Cloud transcript works")])

        output = check_feed.run(
            parser=lambda _: parsed_feed,
            api_factory=lambda: api,
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
