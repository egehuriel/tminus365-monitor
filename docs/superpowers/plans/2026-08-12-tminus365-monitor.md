# T-Minus365 Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that a GitHub-hosted Actions runner can read the latest T-Minus365 YouTube feed item and print its nonempty English transcript.

**Architecture:** A small Python module parses one fixed YouTube Atom feed into a validated `Video`, fetches captions through `youtube-transcript-api`, and formats stable log output. A GitHub Actions workflow runs unit tests first, then runs the live feed/transcript check manually and every 30 minutes.

**Tech Stack:** Python 3.12, standard-library `unittest`, feedparser 6.0.14, youtube-transcript-api 1.2.4, GitHub Actions.

## Global Constraints

- Feed URL: `https://www.youtube.com/feeds/videos.xml?channel_id=UCePaXDDk5kl3g7FcJ5gH5AQ`.
- Channel ID: `UCePaXDDk5kl3g7FcJ5gH5AQ`.
- Use Python 3.12 on GitHub Actions.
- Pin `feedparser==6.0.14` and `youtube-transcript-api==1.2.4`.
- Use no API keys, credentials, repository secrets, paid proxies, or Power Automate connectors.
- Fail the process when feed parsing, video-ID validation, or transcript extraction fails.
- Defer Power Automate handoff, processed-video state, duplicate prevention, proxy support, AI classification, and Teams delivery.

## File Map

- `requirements.txt`: pinned runtime dependencies.
- `src/check_feed.py`: feed parsing, validation, transcript extraction, formatting, and CLI entry point.
- `tests/test_check_feed.py`: network-free unit tests for all Python behavior.
- `.github/workflows/check-videos.yml`: manual/scheduled cloud execution.

---

### Task 1: Feed and Transcript Python Module

**Files:**
- Create: `requirements.txt`
- Create: `src/check_feed.py`
- Create: `tests/test_check_feed.py`

**Interfaces:**
- Produces: `Video(id: str, title: str, published: str, link: str, description: str)`.
- Produces: `get_latest_video(feed_url: str = FEED_URL, parser: Callable = feedparser.parse) -> Video`.
- Produces: `get_transcript(video_id: str, api_factory: Callable = YouTubeTranscriptApi) -> str`.
- Produces: `format_output(video: Video, transcript: str) -> str`.
- Produces: `run(feed_url: str = FEED_URL, parser: Callable = feedparser.parse, api_factory: Callable = YouTubeTranscriptApi) -> str`.
- Produces: `main(runner: Callable[[], str] = run) -> None`.

- [ ] **Step 1: Pin and install runtime dependencies**

Create `requirements.txt`:

```text
feedparser==6.0.14
youtube-transcript-api==1.2.4
```

Run: `python3 -m pip install -r requirements.txt`

Expected: both pinned packages install successfully.

- [ ] **Step 2: Write the first failing test for module creation**

Create `tests/test_check_feed.py`:

```python
from pathlib import Path
import unittest


class CheckFeedTests(unittest.TestCase):
    def test_check_feed_module_exists(self):
        module_path = Path(__file__).parents[1] / "src" / "check_feed.py"
        self.assertTrue(module_path.is_file())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test and verify the expected failure**

Run: `python3 -m unittest discover -s tests -v`

Expected: FAIL because `src/check_feed.py` does not exist.

- [ ] **Step 4: Create the minimal module and re-run the test**

Create an empty `src/check_feed.py`.

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS, 1 test.

- [ ] **Step 5: Add a failing test for latest-video normalization**

Add these imports and helper at the top of `tests/test_check_feed.py`:

```python
from types import SimpleNamespace

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
```

Add this test method:

```python
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
```

- [ ] **Step 6: Run the normalization test and verify the expected failure**

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: FAIL because `get_latest_video` is absent.

- [ ] **Step 7: Implement the video model and happy-path feed parser**

Add to `src/check_feed.py`:

```python
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
    entry = feed.entries[0]
    return Video(
        id=str(entry.get("yt_videoid", "")).strip(),
        title=str(entry.get("title", "")).strip(),
        published=str(entry.get("published", "")).strip(),
        link=str(entry.get("link", "")).strip(),
        description=str(entry.get("summary", "")).strip(),
    )
```

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: PASS.

- [ ] **Step 8: Add failing feed error tests**

Add these test methods:

```python
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
```

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: the three new tests fail because the happy-path-only implementation does not yet translate these invalid feeds into the required `RuntimeError` messages.

- [ ] **Step 9: Implement feed and metadata validation**

Replace `get_latest_video` with:

```python
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
```

Run:

`python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: PASS, 5 tests.

- [ ] **Step 10: Add a failing transcript joining test**

Add this helper:

```python
class FakeTranscriptApi:
    def __init__(self, snippets):
        self.snippets = snippets
        self.calls = []

    def fetch(self, video_id, languages):
        self.calls.append((video_id, languages))
        return self.snippets
```

Add this test method:

```python
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

```

- [ ] **Step 11: Run transcript tests and verify the expected failure**

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: FAIL because `get_transcript` is absent.

- [ ] **Step 12: Implement transcript joining**

Add to `src/check_feed.py`:

```python
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
    return transcript
```

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: PASS, 6 tests.

- [ ] **Step 13: Add a failing empty-transcript test**

Add this test method:

```python
    def test_get_transcript_rejects_empty_text(self):
        api = FakeTranscriptApi([SimpleNamespace(text="  ")])

        with self.assertRaisesRegex(RuntimeError, "Transcript is empty"):
            check_feed.get_transcript(
                "abc123xyz89",
                api_factory=lambda: api,
            )
```

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: FAIL because `get_transcript` returns an empty string.

- [ ] **Step 14: Reject empty transcripts**

Add before the return in `get_transcript`:

```python
    if not transcript:
        raise RuntimeError(f"Transcript is empty for video {video_id}.")
```

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: PASS, 7 tests.

- [ ] **Step 15: Add a failing end-to-end formatting test**

Add this test method:

```python
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
```

Run: `python3 -m unittest discover -s tests -p 'test_check_feed.py' -v`

Expected: FAIL because `run` is absent.

- [ ] **Step 16: Implement output formatting and orchestration**

Add to `src/check_feed.py`:

```python
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
```

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS, 8 tests.

- [ ] **Step 17: Add a failing CLI entry-point test**

Add these imports to `tests/test_check_feed.py`:

```python
from contextlib import redirect_stdout
from io import StringIO
```

Add this test method:

```python
    def test_main_prints_runner_output(self):
        self.assertTrue(hasattr(check_feed, "main"))
        output = StringIO()

        with redirect_stdout(output):
            check_feed.main(runner=lambda: "Cloud transcript works")

        self.assertEqual(output.getvalue(), "Cloud transcript works\n")
```

Run: `python3 -m unittest discover -s tests -v`

Expected: FAIL because `main` is absent.

- [ ] **Step 18: Implement the CLI entry point**

Add to `src/check_feed.py`:

```python
def main(runner: Callable[[], str] = run) -> None:
    print(runner())


if __name__ == "__main__":
    main()
```

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS, 9 tests.

- [ ] **Step 19: Verify Python syntax and commit the task**

Run: `python3 -m compileall -q src tests`

Expected: exit 0 with no output.

Run: `git diff --check`

Expected: exit 0 with no output.

Commit:

```bash
git add requirements.txt src/check_feed.py tests/test_check_feed.py
git commit -m "feat: extract latest T-Minus365 transcript"
```

---

### Task 2: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/check-videos.yml`

**Interfaces:**
- Consumes: `requirements.txt` and the `src/check_feed.py` command-line entry point from Task 1.
- Produces: manual `workflow_dispatch` and scheduled `cron` execution on GitHub-hosted Ubuntu.

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/check-videos.yml`:

```yaml
name: Check T-Minus365 videos

on:
  workflow_dispatch:
  schedule:
    - cron: "*/30 * * * *"

permissions:
  contents: read

jobs:
  check-video:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: python -m pip install -r requirements.txt

      - name: Run unit tests
        run: python -m unittest discover -s tests -v

      - name: Check latest video transcript
        run: python src/check_feed.py
```

- [ ] **Step 2: Validate workflow syntax and required triggers**

Run:

```bash
ruby -e 'require "yaml"; YAML.parse_file(".github/workflows/check-videos.yml"); puts "YAML OK"'
```

Expected: `YAML OK`.

Run:

```bash
rg -n 'workflow_dispatch|cron: "\*/30 \* \* \* \*"|python src/check_feed.py' .github/workflows/check-videos.yml
```

Expected: one matching line for each required behavior.

- [ ] **Step 3: Re-run the complete local verification**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS, 9 tests.

Run: `python3 -m compileall -q src tests`

Expected: exit 0 with no output.

Run: `git diff --check`

Expected: exit 0 with no output.

- [ ] **Step 4: Commit the workflow**

```bash
git add .github/workflows/check-videos.yml
git commit -m "ci: check T-Minus365 videos in GitHub Actions"
```

---

### Task 3: Public Repo and Cloud Transcript Verification

**Files:**
- Verify only; no planned file changes.

**Interfaces:**
- Consumes: the commits from Tasks 1 and 2.
- Produces: a GitHub Actions run and log proving whether GitHub-hosted transcript extraction works.

- [ ] **Step 1: Verify the local commit and working-tree state**

Run: `git status --short --branch`

Expected: clean `main` branch ahead of `origin/main` by the implementation commits.

Run: `git log -3 --oneline`

Expected: design, Python implementation, and workflow commits are present.

- [ ] **Step 2: Push `main` to the public repository**

Run: `git push origin main`

Expected: push succeeds to `egehuriel/tminus365-monitor`.

- [ ] **Step 3: Start the manual workflow**

Preferred command when GitHub CLI authentication is valid:

```bash
gh workflow run check-videos.yml --repo egehuriel/tminus365-monitor --ref main
```

Expected: the dispatch request succeeds. If GitHub CLI authentication is unavailable, open the repository's Actions page, choose **Check T-Minus365 videos**, select **Run workflow**, and run `main`; this is the prepared manual test required by the task.

- [ ] **Step 4: Wait for and inspect the cloud run**

Run:

```bash
gh run list --repo egehuriel/tminus365-monitor --workflow check-videos.yml --limit 1
```

Capture the newest run ID:

```bash
run_id="$(gh run list --repo egehuriel/tminus365-monitor --workflow check-videos.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run_id" --repo egehuriel/tminus365-monitor --exit-status
```

Expected: the run completes successfully.

Run: `gh run view "$run_id" --repo egehuriel/tminus365-monitor --log`

Expected log evidence:

- All 9 unit tests pass.
- `VIDEO ID:` is followed by a nonempty value.
- `TITLE:` and `LINK:` are followed by nonempty values.
- `TRANSCRIPT:` is followed by nonempty English text.

- [ ] **Step 5: Diagnose and fix only evidenced failures**

If the run fails, read the exact failed step and exception. For code, dependency, feed, or workflow failures, first add a unit regression test that reproduces the observed behavior, verify it fails, implement the smallest fix, rerun all local verification, commit, push, and manually dispatch again.

If the exception is `RequestBlocked` or `IpBlocked`, record that the implementation ran correctly but GitHub-hosted IP access failed. Do not add a proxy, credentials, another hosting platform, or Power Automate handoff without a new user-approved design.

- [ ] **Step 6: Final acceptance check**

Run fresh:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
git status --short --branch
```

Expected: 9 tests pass, compilation exits 0, and the working tree is clean and synchronized with `origin/main`.

Confirm the latest GitHub Actions run conclusion is `success` and its log contains a nonempty transcript before reporting cloud extraction as verified.
