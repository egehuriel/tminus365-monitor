# T-Minus365 OneDrive Handoff Design

## Goal

Deliver each newly extracted T-Minus365 transcript from GitHub Actions to the
user's company OneDrive for Business. A Power Automate receiver flow will accept
the transcript over HTTPS and create one machine-readable JSON file per video in
`/TMinus365/Transcripts`. Downstream Power Automate processing begins from that
folder and remains outside this implementation phase.

## Scope

This phase includes:

- one Power Automate HTTP receiver flow;
- one OneDrive for Business destination folder;
- a versioned JSON payload contract;
- GitHub Actions delivery through a secret webhook URL;
- duplicate-safe file creation;
- retry-safe processed-video state;
- a manual force-delivery option for testing and recovery; and
- local and cloud verification of a real OneDrive file.

This phase does not include classification, summarization, Teams delivery,
email delivery, or replacement of the existing downstream Power Automate flow.

## Architecture

The existing GitHub Actions monitor remains responsible for RSS polling and
Supadata transcript extraction. For a new video, it builds a JSON payload and
posts it to a separate Power Automate flow whose trigger is **When an HTTP
request is received**.

The receiver flow validates the request shape, derives a deterministic filename,
checks the OneDrive target folder for that filename, and creates the file only
when it is absent. It then sends an explicit success response to GitHub Actions.
The monitor writes `state/last_video_id.txt` only after that success response.

```text
YouTube RSS
    -> GitHub Actions
    -> Supadata transcript
    -> HTTPS JSON POST
    -> Power Automate receiver
    -> OneDrive for Business /TMinus365/Transcripts
    -> downstream Power Automate flow (later phase)
```

## OneDrive Layout

The user creates this folder once in the company OneDrive for Business account:

```text
/TMinus365/Transcripts/
```

Each video produces one file with this deterministic pattern:

```text
YYYY-MM-DD_VIDEO_ID.json
```

Example:

```text
2026-08-12_OoqeMllPjQk.json
```

The publication date comes from the YouTube RSS entry. The video ID prevents
same-day filename collisions and supplies a stable idempotency key.

## Payload Contract

GitHub Actions sends UTF-8 JSON with `Content-Type: application/json`:

```json
{
  "schemaVersion": 1,
  "videoId": "OoqeMllPjQk",
  "title": "Video title",
  "published": "2026-08-12T08:00:00+00:00",
  "link": "https://www.youtube.com/watch?v=OoqeMllPjQk",
  "description": "Video description",
  "transcript": "Full English transcript"
}
```

All seven fields are required. `schemaVersion` is the integer `1`; the remaining
fields are strings. `videoId`, `title`, `published`, `link`, and `transcript` must
be nonempty. An empty description is allowed.

The Power Automate request trigger uses a JSON schema matching this contract.
The OneDrive file content is the complete received JSON object rather than only
the transcript, so the downstream flow can use metadata without reparsing text.

## Power Automate Receiver

Create a separate flow named `TMinus365 Transcript Receiver` with these logical
steps:

1. Trigger on **When an HTTP request is received** using the payload schema.
2. Compose the filename from the UTC publication date and video ID.
3. Inspect `/TMinus365/Transcripts` for the deterministic filename.
4. If the file already exists, do not overwrite it; return HTTP 200 with
   `{"status":"already_exists","videoId":"...","fileName":"..."}`.
5. If the file does not exist, create it with the complete request body as its
   content; return HTTP 200 with
   `{"status":"created","videoId":"...","fileName":"..."}`.

The receiver flow is solely a secure ingestion boundary. The existing RSS flow
will later be replaced or adapted into a OneDrive **When a file is created** flow
that reads these JSON files.

## GitHub Actions Delivery

The generated Power Automate callback URL is stored in the repository secret
`POWER_AUTOMATE_WEBHOOK_URL`. It is never committed, printed, or included in an
error message. GitHub Actions supplies it to the Python process as an environment
variable.

The monitor sends the payload after transcript extraction. It accepts only an
HTTP 2xx response whose JSON status is `created` or `already_exists`, whose
video ID matches the request, and whose filename matches the deterministic
filename. Network errors, timeouts, non-2xx responses, or malformed success
responses fail the workflow and leave `state/last_video_id.txt` unchanged so a
later scheduled run retries delivery.

After successful delivery, logs contain the video ID, title, OneDrive delivery
status, and filename. They do not contain the webhook URL, API keys, or full
transcript.

The scheduled workflow uses normal duplicate prevention. Manual dispatch exposes
a boolean `force_delivery` input, defaulting to false. When true, the workflow
re-fetches and re-delivers the current latest video even if its ID matches the
state file. The deterministic OneDrive filename makes this recovery operation
safe: an existing file returns success without being overwritten.

## Error Handling and Idempotency

There are two independent duplicate guards:

- GitHub skips videos whose ID matches `state/last_video_id.txt` during normal
  scheduled runs.
- Power Automate treats an existing deterministic filename as a successful
  no-op.

This handles retries after ambiguous network outcomes: if OneDrive creation
succeeds but GitHub never receives the response, the next delivery sees the
existing file, returns success, and then advances GitHub state.

The OneDrive file must not be overwritten automatically. A corrected transcript
can be resent only after a deliberate file removal or a future versioned update
feature, neither of which is part of this phase.

## Security

- The Power Automate callback URL is a credential and is stored only as a GitHub
  Actions secret.
- The public repository contains no Microsoft credentials, tenant identifiers,
  webhook query parameters, or transcript files.
- The receiver writes only to the company OneDrive folder selected in its
  authenticated OneDrive for Business connection.
- The workflow grants only the existing repository-content permission needed to
  persist the processed-video state.
- Action logs exclude the full transcript after handoff is enabled.

If the callback URL is exposed, rotate it by replacing the Power Automate HTTP
trigger or regenerating its URL and updating the GitHub secret.

## Testing and Acceptance

Implementation uses test-driven development with network-free unit tests for:

- exact JSON serialization;
- required webhook configuration;
- successful 2xx delivery;
- non-2xx, timeout, and malformed-response failures;
- state persistence only after confirmed delivery;
- forced delivery despite matching state; and
- redacted output that excludes transcript and credentials.

End-to-end acceptance requires:

1. the receiver flow saves successfully and exposes its callback URL;
2. `POWER_AUTOMATE_WEBHOOK_URL` exists as a GitHub Actions secret;
3. a manual `force_delivery` run succeeds on the pushed `main` commit;
4. exactly one correctly named JSON file appears in the company OneDrive folder;
5. the file contains all payload fields and a nonempty English transcript;
6. a second forced run returns `already_exists` without changing the file; and
7. a normal scheduled run skips the already processed video without consuming a
   Supadata transcript credit.
