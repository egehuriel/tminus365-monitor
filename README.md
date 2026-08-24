# T-Minus365 Monitor

T-Minus365 Monitor watches the T-Minus365 YouTube channel for new videos,
exports their English transcripts, and creates structured Turkish summaries for
Microsoft Teams. It runs every 30 minutes in GitHub Actions and uses a local
GGUF model for classification, so the only external API credential it needs is
a Supadata key for transcript retrieval.

## How it works

```text
YouTube Atom feed
        |
        v
Newest video + Supadata transcript
        |
        v
outbox/latest.json (schema v1)
        |
        v
Local Qwen model classification
        |
        v
Teams-ready Turkish message (schema v2)
        |
        v
Git commit -> optional Power Automate / OneDrive handoff
```

The monitor stores the last processed YouTube video ID in
`state/last_video_id.txt`. If the newest feed entry has already been processed,
the next run exits without requesting the transcript again. Every newly
processed video receives a `POST` decision. Videos without a confirmed
Microsoft 365 or Azure update get the `Yok` tag and a standard no-update
message.

The local model is allowed three attempts to produce valid, contract-compliant
JSON. If all attempts fail, the classifier creates a deterministic fallback
message so the video is still published.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/check_feed.py` | Reads the YouTube feed, retrieves a transcript, and writes schema v1 JSON |
| `src/transcript_export.py` | Validates and serializes transcript payloads |
| `src/classify_update.py` | Runs local inference and enriches the payload to schema v2 |
| `.github/workflows/check-videos.yml` | Scheduled and manually triggered automation |
| `state/last_video_id.txt` | ID of the most recently processed video |
| `outbox/latest.json` | Latest transcript and Teams-ready result |
| `docs/power-automate-standard-importer.md` | OneDrive and Teams handoff instructions |
| `tests/` | Unit and workflow-contract tests |

## GitHub Actions setup

1. Fork or clone the repository.
2. In **Settings -> Secrets and variables -> Actions**, add a repository secret
   named `SUPADATA_API_KEY`.
3. Ensure GitHub Actions has permission to write repository contents. The
   workflow commits updated state and output files back to the current branch.
4. Open **Actions -> Check T-Minus365 videos -> Run workflow** to verify the
   setup.

The workflow also runs automatically every 30 minutes. A manual run exposes a
`force_export` option that regenerates the latest video's transcript even when
its ID matches the saved state.

On a new video, GitHub Actions:

1. installs the Python dependencies and runs the test suite;
2. fetches the feed and transcript;
3. builds and caches `llama-cpp-python`;
4. downloads and caches Qwen2.5 1.5B Instruct Q4_K_M;
5. creates the Turkish Teams message; and
6. commits `outbox/latest.json` and `state/last_video_id.txt`.

No model API key is required; inference runs on the GitHub-hosted runner.

> [!IMPORTANT]
> `outbox/latest.json` contains the complete transcript and is committed to the
> repository. In a public repository, that file is publicly accessible.

## Run locally

Python 3.12 is the supported runtime.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export SUPADATA_API_KEY="your-supadata-key"
python src/check_feed.py
```

The feed and transcript exporter use only Python's standard library, so
`requirements.txt` intentionally contains no third-party runtime package.

To classify the exported file locally, install the optional inference runtime
and supply a GGUF model:

```bash
python -m pip install -r requirements-ai.txt
python src/classify_update.py outbox/latest.json \
  --model /path/to/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Set `FORCE_EXPORT=true` when running `check_feed.py` to ignore the saved video
ID. This can consume another Supadata transcript request.

## Output format

After classification, `outbox/latest.json` uses schema version 2:

```json
{
  "schemaVersion": 2,
  "videoId": "youtube-video-id",
  "fileName": "2026-08-24_youtube-video-id.json",
  "title": "Original video title",
  "published": "2026-08-24T10:00:00+00:00",
  "link": "https://www.youtube.com/watch?v=youtube-video-id",
  "description": "Video description",
  "transcript": "English transcript",
  "decision": "POST",
  "message": "Turkish Teams-ready message"
}
```

The classifier preserves the original title, publication timestamp, product
names, and video URL. It derives its summary primarily from the transcript and
does not add unstated rollout, licensing, or availability details.

## Tests

Run the complete network-free test suite with:

```bash
python -m unittest discover -s tests -v
```

## Power Automate and Teams

The generated JSON can be imported into OneDrive and posted to Teams using only
standard Power Automate connectors. See
[the Power Automate setup guide](docs/power-automate-standard-importer.md) for
the importer, deduplication, and Teams delivery flow.

