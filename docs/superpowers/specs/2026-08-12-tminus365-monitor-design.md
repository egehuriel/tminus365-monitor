# T-Minus365 Monitor: First Cloud Transcript Test

## Goal

Build the smallest public GitHub repository that proves a GitHub-hosted Actions runner can read the T-Minus365 YouTube feed, identify its latest video, and extract that video's English transcript without Power Automate or paid infrastructure.

## Scope

The first version will contain the requested runtime files:

- `requirements.txt`
- `src/check_feed.py`
- `.github/workflows/check-videos.yml`

It will also contain focused automated tests for the Python behavior. Power Automate handoff, processed-video state, duplicate prevention, proxy support, AI classification, and Teams delivery are explicitly deferred.

## Inputs and Dependencies

- YouTube feed: `https://www.youtube.com/feeds/videos.xml?channel_id=UCePaXDDk5kl3g7FcJ5gH5AQ`
- Channel ID: `UCePaXDDk5kl3g7FcJ5gH5AQ`
- Python: 3.12 on GitHub Actions
- `feedparser==6.0.14`
- `youtube-transcript-api==1.2.4`

No API keys, credentials, repository secrets, paid proxy, or Power Automate connector will be used in this phase.

## Architecture and Data Flow

The workflow runs on manual dispatch and every 30 minutes. It checks out the repository, installs the pinned Python dependencies, runs the automated tests, and then executes `src/check_feed.py`.

The script performs one linear operation:

1. Parse the configured YouTube feed.
2. Reject an unreadable or empty feed with a clear error.
3. Select the first feed entry as the latest video.
4. Extract and validate its YouTube video ID and metadata.
5. Fetch an English transcript using `YouTubeTranscriptApi().fetch(video_id, languages=["en"])`.
6. Join transcript snippets into plain text.
7. Print the title, publication date, link, video ID, description, and transcript to the Action log.

The script exits nonzero when feed parsing, video-ID extraction, or transcript retrieval fails. Transcript failures must not be converted into successful workflow runs because cloud transcript extraction is the behavior this phase is intended to prove.

## Components and Boundaries

`requirements.txt` pins reproducible runtime dependencies. Tests use Python's standard-library `unittest` runner and add no test-only package.

`src/check_feed.py` owns feed parsing, latest-video normalization, transcript extraction, text formatting, and the command-line entry point. Network-facing functions accept injectable collaborators or parsed data so unit tests can exercise behavior without making real internet requests.

`tests/test_check_feed.py` verifies latest-video normalization, empty-feed rejection, missing-video-ID rejection, transcript joining, and the command-line success path using representative feed/transcript objects.

`.github/workflows/check-videos.yml` owns cloud scheduling and execution only. It does not contain business logic.

## Error Handling and Observability

Errors identify the failed phase and include the underlying exception where useful. Successful output uses stable labels so the Action log is easy to inspect. The full transcript is intentionally logged for this first test; later phases may replace this with an artifact or external handoff.

The transcript library uses an undocumented YouTube interface and warns that YouTube may block cloud-provider IPs. A `RequestBlocked` or `IpBlocked` result from the GitHub-hosted runner is therefore a valid test finding, not something this phase will hide or work around.

## Verification

Completion requires all of the following:

1. Automated tests pass locally on Python 3.12-compatible code.
2. The workflow YAML is syntactically valid and exposes `workflow_dispatch` plus the 30-minute schedule.
3. The files are committed and pushed to `egehuriel/tminus365-monitor` on `main`.
4. A manually dispatched GitHub Actions run completes successfully.
5. The cloud-run log contains the latest video's nonempty video ID, title, link, and nonempty English transcript.

If the Action reaches YouTube but receives an IP-blocking exception, the implementation is complete but the cloud transcript acceptance criterion is not met; the next design decision would be whether to add a proxy or change the execution platform.
