from pathlib import Path
import json
import tempfile
import unittest

from src import classify_update


class ClassifyUpdateTests(unittest.TestCase):
    def sample_payload(self, **overrides):
        payload = {
            "schemaVersion": 1,
            "videoId": "abc123xyz89",
            "fileName": "2026-08-12_abc123xyz89.json",
            "title": "A Microsoft 365 change",
            "published": "2026-08-12T08:00:00+00:00",
            "link": "https://www.youtube.com/watch?v=abc123xyz89",
            "description": "Microsoft announced a change.",
            "transcript": "Microsoft announced the feature and starts rollout Monday.",
        }
        payload.update(overrides)
        return payload

    def test_build_prompt_contains_source_and_requires_strict_json(self):
        prompt = classify_update.build_prompt(self.sample_payload())

        self.assertIn("A Microsoft 365 change", prompt)
        self.assertIn("starts rollout Monday", prompt)
        self.assertIn('"decision":"POST"', prompt)
        self.assertIn('"decision":"SKIP"', prompt)
        self.assertIn("transcript is the primary source", prompt.lower())

    def test_build_prompt_requires_turkish_message_with_original_title(self):
        prompt = classify_update.build_prompt(
            self.sample_payload(title="Original English Video Title")
        )

        self.assertIn("write the Teams message in Turkish", prompt)
        self.assertIn("Keep the video title exactly as", prompt)
        self.assertIn("supplied in SOURCE; do not translate", prompt)
        self.assertIn("Original English Video Title", prompt)
        self.assertIn("🏷️ Etiket:", prompt)
        self.assertIn("Özet:", prompt)

    def test_build_prompt_rejects_wrong_source_schema(self):
        with self.assertRaisesRegex(RuntimeError, "schemaVersion must be 1"):
            classify_update.build_prompt(self.sample_payload(schemaVersion=2))

    def test_parse_model_output_accepts_skip_json(self):
        analysis = classify_update.parse_model_output(
            '{"decision":"SKIP","message":""}'
        )

        self.assertEqual(analysis.decision, "SKIP")
        self.assertEqual(analysis.message, "")

    def test_parse_model_output_accepts_fenced_post_json(self):
        analysis = classify_update.parse_model_output(
            "```json\n"
            '{"decision":"POST","message":"📌 Feature\\nSummary:\\n- Changed"}'
            "\n```"
        )

        self.assertEqual(analysis.decision, "POST")
        self.assertEqual(analysis.message, "📌 Feature\nSummary:\n- Changed")

    def test_parse_model_output_accepts_fields_in_any_json_order(self):
        analysis = classify_update.parse_model_output(
            '{"message":"📌 Feature\\nSummary:\\n- Changed","decision":"POST"}'
        )

        self.assertEqual(analysis.decision, "POST")
        self.assertEqual(analysis.message, "📌 Feature\nSummary:\n- Changed")

    def test_parse_model_output_ignores_additional_model_fields(self):
        analysis = classify_update.parse_model_output(
            '{"decision":"POST","message":"📌 Feature",'
            '"explanation":"Confirmed from the supplied source."}'
        )

        self.assertEqual(analysis.decision, "POST")
        self.assertEqual(analysis.message, "📌 Feature")

    def test_parse_model_output_rejects_invalid_decision(self):
        with self.assertRaisesRegex(RuntimeError, "decision must be POST or SKIP"):
            classify_update.parse_model_output(
                '{"decision":"MAYBE","message":"uncertain"}'
            )

    def test_parse_model_output_rejects_post_without_message(self):
        with self.assertRaisesRegex(RuntimeError, "POST requires a message"):
            classify_update.parse_model_output(
                '{"decision":"POST","message":"  "}'
            )

    def test_parse_model_output_rejects_skip_with_message(self):
        with self.assertRaisesRegex(RuntimeError, "SKIP message must be empty"):
            classify_update.parse_model_output(
                '{"decision":"SKIP","message":"do not send"}'
            )

    def test_enrich_payload_returns_exact_v2_contract(self):
        enriched = classify_update.enrich_payload(
            self.sample_payload(),
            classify_update.Analysis("POST", "📌 Final message"),
        )

        self.assertEqual(
            tuple(enriched),
            (
                "schemaVersion",
                "videoId",
                "fileName",
                "title",
                "published",
                "link",
                "description",
                "transcript",
                "decision",
                "message",
            ),
        )
        self.assertEqual(enriched["schemaVersion"], 2)
        self.assertEqual(enriched["decision"], "POST")
        self.assertEqual(enriched["message"], "📌 Final message")

    def test_classify_file_writes_valid_json_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(
                json.dumps(self.sample_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            result = classify_update.classify_file(
                path,
                predictor=lambda _prompt: '{"decision":"SKIP","message":""}',
            )
            written = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(result, path)
            self.assertEqual(written["schemaVersion"], 2)
            self.assertEqual(written["decision"], "SKIP")
            self.assertEqual(written["message"], "")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_classify_file_retries_before_giving_up(self):
        calls = []

        def flaky_predictor(_prompt):
            calls.append(1)
            if len(calls) < 3:
                return "not-json"
            return '{"decision":"SKIP","message":""}'

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(
                json.dumps(self.sample_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            classify_update.classify_file(path, predictor=flaky_predictor)
            written = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(len(calls), 3)
            self.assertEqual(written["decision"], "SKIP")

    def test_classify_file_falls_back_to_skip_when_model_repeatedly_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(
                json.dumps(self.sample_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            result = classify_update.classify_file(
                path,
                predictor=lambda _prompt: "not-json",
            )
            written = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(result, path)
            self.assertEqual(written["schemaVersion"], 2)
            self.assertEqual(written["decision"], "SKIP")
            self.assertEqual(written["message"], "")

    def test_classify_file_downgrades_off_contract_post_message_to_skip(self):
        # Reproduces the 2026-08-19 incident: syntactically valid JSON,
        # decision claimed POST, but the message is unrelated freeform
        # English text with none of the required Turkish structure.
        off_contract = (
            '{"decision":"POST","message":"Welcome to Above the Stack, '
            'where business meets technical and security becomes your '
            'differentiator. Signing off."}'
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(
                json.dumps(self.sample_payload(), ensure_ascii=False),
                encoding="utf-8",
            )

            classify_update.classify_file(
                path,
                predictor=lambda _prompt: off_contract,
            )
            written = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(written["decision"], "SKIP")
            self.assertEqual(written["message"], "")

    def test_classify_file_accepts_on_contract_post_message(self):
        payload = self.sample_payload()
        on_contract = (
            '{"decision":"POST","message":"📌 A Microsoft 365 change\\n'
            f'🎥 T-Minus365 | 📅 {payload["published"]} | 🔗 {payload["link"]}\\n'
            '🏷️ Etiket: Microsoft 365\\n\\nÖzet:\\n- Değişiklik uygulandı."}'
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            classify_update.classify_file(
                path,
                predictor=lambda _prompt: on_contract,
            )
            written = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(written["decision"], "POST")
            self.assertIn("📌", written["message"])

    def test_build_prompt_truncates_overlong_transcript(self):
        payload = self.sample_payload(transcript="word " * 40_000)
        prompt = classify_update.build_prompt(payload)

        self.assertLessEqual(
            len(prompt), classify_update.MAX_TRANSCRIPT_CHARS + 2_000
        )
        self.assertIn("[transcript truncated for length", prompt)


if __name__ == "__main__":
    unittest.main()
