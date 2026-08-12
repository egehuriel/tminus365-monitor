from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_check_feed_imports_when_src_is_the_script_directory(self):
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys; sys.path.insert(0, 'src'); import check_feed",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_run_exports_payload_and_redacts_transcript(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "outbox" / "latest.json"
            output = check_feed.run(
                parser=lambda _: parsed_feed,
                api_key="secret-value",
                opener=lambda _request, timeout: FakeHttpResponse(
                    {"content": "Cloud transcript works"}
                ),
                state_path=None,
                output_path=output_path,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["videoId"], "abc123xyz89")
        self.assertEqual(payload["transcript"], "Cloud transcript works")
        self.assertEqual(payload["fileName"], "2026-08-12_abc123xyz89.json")
        self.assertIn("STATUS:\nEXPORTED", output)
        self.assertIn("FILE:\n2026-08-12_abc123xyz89.json", output)
        self.assertNotIn("Cloud transcript works", output)
        self.assertNotIn("TRANSCRIPT:", output)

    def test_run_skips_transcript_for_processed_video(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        def unexpected_opener(_request, timeout):
            self.fail(
                f"Supadata must not be called for a processed video (timeout={timeout})"
            )

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "last_video_id.txt"
            output_path = Path(directory) / "outbox" / "latest.json"
            state_path.write_text("abc123xyz89\n", encoding="utf-8")

            output = check_feed.run(
                parser=lambda _: parsed_feed,
                api_key="secret-value",
                opener=unexpected_opener,
                state_path=state_path,
                output_path=output_path,
            )

            self.assertFalse(output_path.exists())

        self.assertIn("STATUS:\nALREADY PROCESSED", output)
        self.assertIn("VIDEO ID:\nabc123xyz89", output)
        self.assertNotIn("TRANSCRIPT:", output)

    def test_run_persists_video_id_after_transcript_success(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state" / "last_video_id.txt"
            output_path = Path(directory) / "outbox" / "latest.json"
            check_feed.run(
                parser=lambda _: parsed_feed,
                api_key="secret-value",
                opener=lambda _request, timeout: FakeHttpResponse(
                    {"content": "Cloud transcript works"}
                ),
                state_path=state_path,
                output_path=output_path,
            )

            self.assertEqual(
                state_path.read_text(encoding="utf-8"),
                "abc123xyz89\n",
            )

    def test_run_does_not_persist_video_id_when_transcript_fails(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state" / "last_video_id.txt"
            with self.assertRaisesRegex(RuntimeError, "Transcript is empty"):
                check_feed.run(
                    parser=lambda _: parsed_feed,
                    api_key="secret-value",
                    opener=lambda _request, timeout: FakeHttpResponse(
                        {"content": ""}
                    ),
                    state_path=state_path,
                )

            self.assertFalse(state_path.exists())

    def test_run_force_export_ignores_matching_state(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state" / "last_video_id.txt"
            output_path = Path(directory) / "outbox" / "latest.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text("abc123xyz89\n", encoding="utf-8")

            output = check_feed.run(
                parser=lambda _: parsed_feed,
                api_key="secret-value",
                opener=lambda _request, timeout: FakeHttpResponse(
                    {"content": "Forced transcript"}
                ),
                state_path=state_path,
                output_path=output_path,
                force_export=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["transcript"], "Forced transcript")
        self.assertIn("STATUS:\nEXPORTED", output)

    def test_run_does_not_persist_state_when_export_fails(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        def failing_exporter(payload, path):
            self.assertEqual(payload["videoId"], "abc123xyz89")
            raise OSError("disk unavailable")

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state" / "last_video_id.txt"
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                check_feed.run(
                    parser=lambda _: parsed_feed,
                    api_key="secret-value",
                    opener=lambda _request, timeout: FakeHttpResponse(
                        {"content": "Cloud transcript works"}
                    ),
                    state_path=state_path,
                    output_path=Path(directory) / "outbox" / "latest.json",
                    exporter=failing_exporter,
                )

            self.assertFalse(state_path.exists())

    def test_environment_flag_accepts_only_true(self):
        self.assertTrue(
            check_feed.environment_flag("FORCE_EXPORT", {"FORCE_EXPORT": "TRUE"})
        )
        self.assertFalse(
            check_feed.environment_flag("FORCE_EXPORT", {"FORCE_EXPORT": "false"})
        )
        self.assertFalse(check_feed.environment_flag("FORCE_EXPORT", {}))

    def test_main_uses_force_export_environment(self):
        with patch.object(check_feed, "run", return_value="EXPORTED") as runner:
            with patch.dict(check_feed.os.environ, {"FORCE_EXPORT": "true"}):
                output = StringIO()
                with redirect_stdout(output):
                    check_feed.main()

        runner.assert_called_once_with(force_export=True)
        self.assertEqual(output.getvalue(), "EXPORTED\n")

    def test_main_prints_runner_output(self):
        self.assertTrue(hasattr(check_feed, "main"))
        output = StringIO()

        with redirect_stdout(output):
            check_feed.main(runner=lambda: "Cloud transcript works")

        self.assertEqual(output.getvalue(), "Cloud transcript works\n")


if __name__ == "__main__":
    unittest.main()
