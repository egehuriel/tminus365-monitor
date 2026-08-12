from pathlib import Path
import json
import tempfile
import unittest

from src import transcript_export


class TranscriptExportTests(unittest.TestCase):
    def sample_payload(self, **overrides):
        values = {
            "video_id": "abc123xyz89",
            "title": "Latest T-Minus365 video",
            "published": "2026-08-12T08:00:00+00:00",
            "link": "https://www.youtube.com/watch?v=abc123xyz89",
            "description": "A useful description.",
            "transcript": "Cloud transcript works",
        }
        values.update(overrides)
        return transcript_export.build_payload(**values)

    def test_file_name_uses_publication_date_and_video_id(self):
        self.assertEqual(
            transcript_export.file_name_for(
                "2026-08-12T08:00:00+00:00",
                "abc123xyz89",
            ),
            "2026-08-12_abc123xyz89.json",
        )

    def test_build_payload_returns_exact_contract(self):
        self.assertEqual(
            self.sample_payload(),
            {
                "schemaVersion": 1,
                "videoId": "abc123xyz89",
                "fileName": "2026-08-12_abc123xyz89.json",
                "title": "Latest T-Minus365 video",
                "published": "2026-08-12T08:00:00+00:00",
                "link": "https://www.youtube.com/watch?v=abc123xyz89",
                "description": "A useful description.",
                "transcript": "Cloud transcript works",
            },
        )

    def test_build_payload_rejects_empty_required_text(self):
        for field in ("video_id", "title", "published", "link", "transcript"):
            with self.subTest(field=field):
                values = {
                    "video_id": "abc123xyz89",
                    "title": "Latest T-Minus365 video",
                    "published": "2026-08-12T08:00:00+00:00",
                    "link": "https://www.youtube.com/watch?v=abc123xyz89",
                    "description": "",
                    "transcript": "Cloud transcript works",
                }
                values[field] = "   "
                with self.assertRaisesRegex(RuntimeError, "empty fields"):
                    transcript_export.build_payload(**values)

    def test_file_name_rejects_invalid_timestamp(self):
        with self.assertRaisesRegex(RuntimeError, "ISO 8601"):
            transcript_export.file_name_for("not-a-date", "abc123xyz89")

    def test_serialize_payload_is_utf8_stable_json(self):
        payload = self.sample_payload(title="Microsoft 365 – Güncelleme")

        serialized = transcript_export.serialize_payload(payload)

        self.assertTrue(serialized.endswith("\n"))
        self.assertIn("Microsoft 365 – Güncelleme", serialized)
        self.assertNotIn("\\u2013", serialized)
        self.assertEqual(json.loads(serialized), payload)

    def test_write_latest_creates_parent_and_returns_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outbox" / "latest.json"

            result = transcript_export.write_latest(self.sample_payload(), path)

            self.assertEqual(result, path)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                transcript_export.serialize_payload(self.sample_payload()),
            )
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_write_latest_rejects_extra_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            payload = self.sample_payload()
            payload["secret"] = "must-not-be-published"

            with self.assertRaisesRegex(RuntimeError, "exact fields"):
                transcript_export.write_latest(payload, path)

            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
