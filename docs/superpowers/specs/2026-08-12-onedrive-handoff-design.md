# T-Minus365 Standard-Only OneDrive Handoff Design

## Goal

Deliver each newly extracted T-Minus365 transcript from GitHub Actions to the
user's company OneDrive for Business without Power Automate Premium, an Azure
application registration, or another paid relay service.

The public repository may contain transcript JSON because every exported field
comes from the public T-Minus365 YouTube video. Credentials and company account
details remain private.

## Decision and Superseded Design

The earlier design used Power Automate's **When an HTTP request is received**
trigger. The user's tenant identified that trigger as Premium, so that receiver
flow is intentionally abandoned. No implementation may depend on a Power
Automate webhook or the `POWER_AUTOMATE_WEBHOOK_URL` secret.

The replacement inverts the handoff:

1. GitHub Actions publishes a stable public JSON file in this repository.
2. A scheduled Power Automate flow pulls that file into OneDrive using only the
   Standard OneDrive for Business connector.
3. The flow creates an immutable, deterministic transcript file only when it
   does not already exist.

## Scope

This phase includes:

- producing `outbox/latest.json` from the latest T-Minus365 video;
- committing that file from GitHub Actions together with processed-video state;
- a scheduled Standard-only Power Automate flow;
- OneDrive staging and transcript folders;
- duplicate-safe transcript file creation;
- retry behavior for temporary GitHub or OneDrive failures;
- a manual force-export option for testing and recovery; and
- end-to-end verification of one real OneDrive transcript file.

This phase does not include summarization, classification, Teams delivery,
email delivery, or downstream business processing.

## Architecture

```text
YouTube RSS
    -> GitHub Actions
    -> Supadata transcript extraction
    -> public outbox/latest.json in GitHub
    -> scheduled Power Automate flow (Standard only)
    -> OneDrive /TMinus365/Staging/latest.json
    -> duplicate check
    -> OneDrive /TMinus365/Transcripts/YYYY-MM-DD_VIDEO_ID.json
    -> downstream Power Automate flow (later phase)
```

No inbound webhook, HTTP connector, custom connector, Azure application, or
Premium Power Automate capability is part of this architecture.

## Public JSON Contract

GitHub Actions writes UTF-8 JSON to:

```text
outbox/latest.json
```

The document uses this versioned contract:

```json
{
  "schemaVersion": 1,
  "videoId": "OoqeMllPjQk",
  "fileName": "2026-08-12_OoqeMllPjQk.json",
  "title": "Video title",
  "published": "2026-08-12T08:00:00+00:00",
  "link": "https://www.youtube.com/watch?v=OoqeMllPjQk",
  "description": "Video description",
  "transcript": "Full English transcript"
}
```

All eight fields are required. `schemaVersion` is the integer `1`; the remaining
fields are strings. `description` may be empty. `fileName` is derived from the
publication date and video ID using:

```text
YYYY-MM-DD_VIDEO_ID.json
```

The JSON must not contain the Supadata key, GitHub credentials, Microsoft
account information, OneDrive identifiers, environment variables, workflow
URLs, or other secrets.

## GitHub Actions Behavior

The existing monitor continues to poll the YouTube RSS feed every 30 minutes.
For a new latest video it:

1. fetches the English transcript through Supadata;
2. builds the exact JSON contract;
3. writes `outbox/latest.json` with stable formatting and a trailing newline;
4. updates `state/last_video_id.txt`; and
5. commits both files in the same workflow commit.

The state file and JSON output are written only after transcript extraction and
payload validation succeed. A failure before the commit leaves the previously
published JSON and state unchanged so the next scheduled run can retry.

A normal run skips a video whose ID matches `state/last_video_id.txt` and does
not consume another Supadata transcript request. Manual dispatch exposes a
boolean force option that regenerates `outbox/latest.json` for the current video
even when the state matches. Logs show metadata and the output filename but not
the transcript or any secret.

## Power Automate Flow

Create a scheduled cloud flow named:

```text
TMinus365 Transcript Importer
```

It runs every 30 minutes and uses only built-in controls and the Standard
OneDrive for Business connector:

1. **Recurrence** triggers the flow.
2. **Upload file from URL** downloads the public raw GitHub URL for
   `outbox/latest.json` to `/TMinus365/Staging/latest.json` with overwrite
   enabled. A timestamp query parameter is added to the source URL to avoid a
   stale CDN response.
3. **Delay** waits 30 seconds because the OneDrive upload-from-URL operation can
   report success before the transfer has finished.
4. **Get file content using path** reads the staging file.
5. **Parse JSON** validates the eight-field version 1 contract.
6. **List files in folder** reads `/TMinus365/Transcripts` and an exact-name
   filter compares each item with the payload's `fileName`.
7. If an exact match exists, the flow ends successfully without changing it.
8. If no match exists, **Create file** writes the complete staging JSON to
   `/TMinus365/Transcripts/<fileName>`.

The staging folder is an implementation detail. Downstream automation watches
only `/TMinus365/Transcripts`, so refreshing `Staging/latest.json` does not
produce a downstream event.

## OneDrive Layout

The company OneDrive account owns these folders:

```text
/TMinus365/
├── Staging/
│   └── latest.json
└── Transcripts/
    └── YYYY-MM-DD_VIDEO_ID.json
```

Files in `Transcripts` are immutable for this phase. A forced GitHub export may
refresh the staging file, but the importer never overwrites an existing
deterministic transcript file.

## Error Handling and Idempotency

- A GitHub extraction or serialization failure leaves both outbox and state
  unchanged and causes the workflow to fail.
- A Power Automate download, read, parse, or OneDrive failure causes that run to
  fail. The next 30-minute recurrence retries automatically.
- If an upload-from-URL run leaves the previous staging file in place, the exact
  filename check makes processing that stale file a harmless no-op.
- A raw GitHub caching delay is handled by the timestamp query parameter and the
  later scheduled retry.
- The deterministic filename makes repeated Power Automate runs idempotent.
- The importer never sends status back to GitHub; GitHub state represents
  successful transcript publication, while OneDrive retries independently.

The current monitor already handles only the latest RSS entry. This design does
not add a multi-video backlog queue; that is outside the present scope.

## Security and Cost

- Transcript JSON is public by explicit user approval and contains only public
  YouTube-derived content.
- `SUPADATA_API_KEY` remains a GitHub Actions secret and is never serialized or
  logged.
- Microsoft credentials stay inside the authenticated OneDrive for Business
  connection in Power Automate.
- No Power Automate callback URL or Microsoft token is stored in GitHub.
- The Power Automate flow contains only Standard connector actions and built-in
  controls; it must save without a Premium license warning.
- The existing Premium HTTP receiver flow is not used and may be deleted by the
  user after the replacement passes acceptance testing.

## Testing and Acceptance

Implementation uses test-driven development with network-free tests for:

- deterministic filename generation;
- the exact version 1 JSON contract;
- stable UTF-8 JSON serialization;
- rejection of an empty transcript or required metadata;
- normal duplicate skip behavior;
- forced regeneration when state already matches; and
- console output that excludes transcript text and secrets.

End-to-end acceptance requires:

1. all local unit tests pass;
2. a manual forced GitHub Actions run succeeds on pushed `main`;
3. `outbox/latest.json` is publicly readable through its raw GitHub URL;
4. the Power Automate importer saves with no Premium license warning;
5. a manual importer run creates exactly one correctly named JSON file in
   `/TMinus365/Transcripts`;
6. the OneDrive file contains all eight fields and a nonempty English
   transcript;
7. a second importer run creates no duplicate and does not overwrite the file;
   and
8. a normal GitHub Actions run skips the already processed video without
   consuming another Supadata transcript request.
