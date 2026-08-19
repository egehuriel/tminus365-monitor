from pathlib import Path
import json
import subprocess
import unittest


WORKFLOW_PATH = Path(".github/workflows/check-videos.yml")


def load_workflow():
    ruby = r'''
require "json"
require "yaml"
workflow = YAML.load_file(ARGV.fetch(0))
workflow["on"] = workflow.delete(true) if workflow.key?(true)
puts JSON.generate(workflow)
'''
    result = subprocess.run(
        ["ruby", "-e", ruby, str(WORKFLOW_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = load_workflow()

    def steps(self):
        return self.workflow["jobs"]["check-video"]["steps"]

    def step_named(self, name):
        return next(step for step in self.steps() if step.get("name") == name)

    def test_manual_dispatch_exposes_boolean_force_export(self):
        force_export = self.workflow["on"]["workflow_dispatch"]["inputs"][
            "force_export"
        ]

        self.assertEqual(force_export["type"], "boolean")
        self.assertFalse(force_export["default"])
        self.assertFalse(force_export["required"])

    def test_export_step_receives_force_flag_and_supadata_secret(self):
        export_step = self.step_named("Export latest video transcript")

        self.assertEqual(
            export_step["env"]["SUPADATA_API_KEY"],
            "${{ secrets.SUPADATA_API_KEY }}",
        )
        self.assertIn("inputs.force_export", export_step["env"]["FORCE_EXPORT"])
        self.assertEqual(export_step["run"], "python src/check_feed.py")

    def test_publication_step_handles_missing_initial_outbox(self):
        publish_step = self.step_named(
            "Publish transcript JSON and processed video ID"
        )
        script = publish_step["run"]

        self.assertIn("git add state/last_video_id.txt", script)
        self.assertIn("if [ -f outbox/latest.json ]; then", script)
        self.assertIn("git add outbox/latest.json", script)
        self.assertIn('git commit -m "Publish T-Minus365 transcript"', script)

    def test_workflow_has_no_power_automate_webhook_environment(self):
        environment_names = {
            name
            for step in self.steps()
            for name in step.get("env", {})
        }

        self.assertNotIn("POWER_AUTOMATE_WEBHOOK_URL", environment_names)

    def test_model_setup_runs_only_when_classification_is_required(self):
        detect_step = self.step_named("Detect transcript requiring analysis")
        self.assertEqual(detect_step["id"], "analysis")
        self.assertIn("should_run=true", detect_step["run"])

        gated_steps = (
            "Cache local model",
            "Install local inference runtime",
            "Download local model",
            "Classify Microsoft 365 update",
        )
        for name in gated_steps:
            with self.subTest(step=name):
                self.assertEqual(
                    self.step_named(name)["if"],
                    "steps.analysis.outputs.should_run == 'true'",
                )

    def test_classification_uses_local_model_without_new_secret(self):
        classify_step = self.step_named("Classify Microsoft 365 update")

        self.assertIn("src/classify_update.py", classify_step["run"])
        self.assertIn("outbox/latest.json", classify_step["run"])
        self.assertIn(".cache/models", classify_step["run"])
        self.assertEqual(classify_step.get("env", {}), {})

    def test_local_inference_runtime_is_built_for_the_runner(self):
        install_step = self.step_named("Install local inference runtime")
        command = install_step["run"]

        self.assertIn("--no-binary=llama-cpp-python", command)
        # --no-cache-dir was removed on purpose: it disabled pip's wheel
        # cache for this install, forcing a full source recompile on every
        # single run (10+ minutes each time) even though the compiled
        # wheel for an unchanged llama-cpp-python version could otherwise
        # be reused via actions/setup-python's pip cache.
        self.assertNotIn("--no-cache-dir", command)
        self.assertNotIn("abetlen.github.io", command)

    def test_python_setup_caches_both_requirement_files(self):
        setup_step = self.step_named("Set up Python")
        cache_path = setup_step["with"]["cache-dependency-path"]

        self.assertIn("requirements.txt", cache_path)
        self.assertIn("requirements-ai.txt", cache_path)


if __name__ == "__main__":
    unittest.main()
