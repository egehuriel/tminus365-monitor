# T-Minus365 OneDrive Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver each new T-Minus365 transcript from GitHub Actions to a duplicate-safe JSON file in the user's company OneDrive for Business.

**Architecture:** GitHub Actions continues to read YouTube RSS and fetch the English transcript through Supadata. A focused Python handoff module posts a versioned JSON payload to a Power Automate HTTP receiver, which creates a deterministic file in `/TMinus365/Transcripts`; GitHub persists the processed video ID only after a validated success response.

**Tech Stack:** Python 3.12 standard library, `unittest`, GitHub Actions, Power Automate Request trigger, OneDrive for Business connector.

## Global Constraints

- Keep RSS URL `https://www.youtube.com/feeds/videos.xml?channel_id=UCePaXDDk5kl3g7FcJ5gH5AQ`.
- Keep Supadata in `mode=native` with preferred language `en`.
- Store the Power Automate callback URL only in GitHub secret `POWER_AUTOMATE_WEBHOOK_URL`.
- Write files only to company OneDrive for Business folder `/TMinus365/Transcripts`.
- Use filename format `YYYY-MM-DD_VIDEO_ID.json` and never overwrite an existing file.
- Persist `state/last_video_id.txt` only after validated handoff success.
- Scheduled runs skip a matching processed video; manual `force_delivery` may resend it.
- Do not log the callback URL, API keys, or full transcript after handoff is enabled.
- Do not add classification, summarization, Teams delivery, or email delivery in this phase.

## File Map

- Create `src/handoff.py`: payload construction, deterministic filename, HTTP delivery, and response validation.
- Create `tests/test_handoff.py`: network-free contract and HTTP-boundary tests.
- Modify `src/check_feed.py`: orchestrate transcript delivery, force mode, state ordering, and redacted log output.
- Modify `tests/test_check_feed.py`: delivery/state/force/redaction tests.
- Modify `.github/workflows/check-videos.yml`: callback secret and manual force input.
- Modify `docs/superpowers/specs/2026-08-12-onedrive-handoff-design.md`: record verified run/file evidence after acceptance.

---

### Task 1: Power Automate Receiver and OneDrive Folder

**Files:**
- No repository files.
- External: company OneDrive for Business `/TMinus365/Transcripts`.
- External: Power Automate flow `TMinus365 Transcript Receiver`.

**Interfaces:**
- Consumes: HTTP `POST` with the exact request schema below.
- Produces: HTTP 200 JSON `status`, `videoId`, and `fileName`; one immutable OneDrive JSON file when absent.

- [ ] **Step 1: Create the OneDrive destination folders**

Sign in to the company OneDrive for Business account and create:

```text
/TMinus365/Transcripts
```

Expected: the empty `Transcripts` folder is visible in the company-owned drive.

- [ ] **Step 2: Create the receiver flow and request trigger**

In Power Automate, create an **Instant cloud flow** named:

```text
TMinus365 Transcript Receiver
```

Select **When an HTTP request is received** and paste this request-body schema:

```json
{
  "type": "object",
  "properties": {
    "schemaVersion": {
      "type": "integer",
      "enum": [1]
    },
    "videoId": {
      "type": "string",
      "minLength": 1
    },
    "title": {
      "type": "string",
      "minLength": 1
    },
    "published": {
      "type": "string",
      "minLength": 1
    },
    "link": {
      "type": "string",
      "minLength": 1
    },
    "description": {
      "type": "string"
    },
    "transcript": {
      "type": "string",
      "minLength": 1
    }
  },
  "required": [
    "schemaVersion",
    "videoId",
    "title",
    "published",
    "link",
    "description",
    "transcript"
  ]
}
```

Expected: the trigger accepts only schema version 1 payloads with all seven fields.

- [ ] **Step 3: Compose the deterministic filename**

Add **Data Operations → Compose**, rename it `Compose file name`, and use this expression:

```text
concat(
  formatDateTime(triggerBody()?['published'], 'yyyy-MM-dd'),
  '_',
  triggerBody()?['videoId'],
  '.json'
)
```

Expected for the test video: `2026-08-12_OoqeMllPjQk.json`.

- [ ] **Step 4: List and filter existing files**

Add **OneDrive for Business → List files in folder**, rename it `List destination files`, and select:

```text
/TMinus365/Transcripts
```

Open the action settings, enable pagination, and set the threshold to `5000`.

Add **Data Operations → Filter array**, rename it `Filter matching file`, set **From** to:

```text
body('List_destination_files')?['value']
```

Use advanced mode with:

```text
@equals(item()?['Name'], outputs('Compose_file_name'))
```

Expected: the filter is empty before the test file exists and contains one item afterward.

- [ ] **Step 5: Add the duplicate branch**

Add a Condition named `File already exists?` with this expression:

```text
@greater(length(body('Filter_matching_file')), 0)
```

In the **True/Yes** branch, add **Request → Response**:

```text
Status Code: 200
Header Content-Type: application/json
```

Body:

```json
{
  "status": "already_exists",
  "videoId": "@{triggerBody()?['videoId']}",
  "fileName": "@{outputs('Compose_file_name')}"
}
```

Expected: duplicates return success without changing the existing file.

- [ ] **Step 6: Add the create branch**

In the **False/No** branch, add **OneDrive for Business → Create file**:

```text
Folder Path: /TMinus365/Transcripts
File Name: outputs('Compose_file_name')
File Content: string(triggerBody())
```

After it, add **Request → Response**:

```text
Status Code: 200
Header Content-Type: application/json
```

Body:

```json
{
  "status": "created",
  "videoId": "@{triggerBody()?['videoId']}",
  "fileName": "@{outputs('Compose_file_name')}"
}
```

Expected: a new request creates one JSON file and responds only after creation succeeds.

- [ ] **Step 7: Save and protect the callback URL**

Save the flow, copy the generated HTTP POST URL, and add it directly in GitHub:

```text
Repository → Settings → Secrets and variables → Actions
Name: POWER_AUTOMATE_WEBHOOK_URL
Value: generated HTTP POST URL
```

Do not paste the URL into chat, source files, shell history, screenshots, or Action logs.

Run:

```bash
gh api repos/egehuriel/tminus365-monitor/actions/secrets --jq '.secrets[].name'
```

Expected: output includes `POWER_AUTOMATE_WEBHOOK_URL` without revealing its value.

---

### Task 2: Payload and Delivery Boundary

**Files:**
- Create: `src/handoff.py`
- Create: `tests/test_handoff.py`

**Interfaces:**
- Produces: `DeliveryReceipt(status: str, video_id: str, file_name: str)`.
- Produces: `file_name_for(published: str, video_id: str) -> str`.
- Produces: `build_payload(*, video_id: str, title: str, published: str, link: str, description: str, transcript: str) -> dict[str, object]`.
- Produces: `deliver(payload: dict[str, object], webhook_url: str | None = None, opener: Callable = urlopen) -> DeliveryReceipt`.

- [ ] **Step 1: Write failing filename and payload tests**

Create `tests/test_handoff.py`:

```python
import unittest

from src import handoff


class HandoffTests(unittest.TestCase):
    def test_file_name_uses_publication_date_and_video_id(self):
        self.assertEqual(
            handoff.file_name_for(
                "2026-08-12T08:00:00+00:00",
                "OoqeMllPjQk",
            ),
            "2026-08-12_OoqeMllPjQk.json",
        )

    def test_build_payload_returns_versioned_contract(self):
        payload = handoff.build_payload(
            video_id="OoqeMllPjQk",
            title="T-Minus365 update",
            published="2026-08-12T08:00:00+00:00",
            link="https://www.youtube.com/watch?v=OoqeMllPjQk",
            description="Microsoft 365 news",
            transcript="Cloud transcript works",
        )

        self.assertEqual(
            payload,
            {
                "schemaVersion": 1,
                "videoId": "OoqeMllPjQk",
                "title": "T-Minus365 update",
                "published": "2026-08-12T08:00:00+00:00",
                "link": "https://www.youtube.com/watch?v=OoqeMllPjQk",
                "description": "Microsoft 365 news",
                "transcript": "Cloud transcript works",
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3.12 -m unittest tests.test_handoff -v
```

Expected: import failure because `src/handoff.py` does not exist.

- [ ] **Step 3: Implement filename and payload construction**

Create `src/handoff.py` with these production interfaces and validation:

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os


@dataclass(frozen=True)
class DeliveryReceipt:
    status: str
    video_id: str
    file_name: str


def file_name_for(published: str, video_id: str) -> str:
    try:
        instant = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("Published timestamp is not valid ISO 8601.") from error
    clean_video_id = video_id.strip()
    if not clean_video_id:
        raise RuntimeError("Video ID is required for handoff.")
    return f"{instant.date().isoformat()}_{clean_video_id}.json"


def build_payload(
    *,
    video_id: str,
    title: str,
    published: str,
    link: str,
    description: str,
    transcript: str,
) -> dict[str, object]:
    required = {
        "videoId": video_id.strip(),
        "title": title.strip(),
        "published": published.strip(),
        "link": link.strip(),
        "transcript": transcript.strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Handoff payload has empty fields: {', '.join(missing)}")
    file_name_for(required["published"], required["videoId"])
    return {
        "schemaVersion": 1,
        **required,
        "description": description.strip(),
    }
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run:

```bash
python3.12 -m unittest tests.test_handoff -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Write failing delivery-contract tests**

Add to `tests/test_handoff.py`:

```python
from urllib.parse import urlparse
from urllib.error import URLError
import json


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
```

Add these methods to `HandoffTests`:

```python
    def sample_payload(self):
        return handoff.build_payload(
            video_id="OoqeMllPjQk",
            title="T-Minus365 update",
            published="2026-08-12T08:00:00+00:00",
            link="https://www.youtube.com/watch?v=OoqeMllPjQk",
            description="Microsoft 365 news",
            transcript="Cloud transcript works",
        )

    def test_deliver_posts_json_and_validates_receipt(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeHttpResponse(
                {
                    "status": "created",
                    "videoId": "OoqeMllPjQk",
                    "fileName": "2026-08-12_OoqeMllPjQk.json",
                }
            )

        receipt = handoff.deliver(
            self.sample_payload(),
            webhook_url="https://example.test/power-automate-secret-path",
            opener=opener,
        )

        self.assertEqual(
            receipt,
            handoff.DeliveryReceipt(
                status="created",
                video_id="OoqeMllPjQk",
                file_name="2026-08-12_OoqeMllPjQk.json",
            ),
        )
        request, timeout = requests[0]
        self.assertEqual(urlparse(request.full_url).hostname, "example.test")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), self.sample_payload())
        self.assertEqual(timeout, 60)

    def test_deliver_requires_webhook_url(self):
        with self.assertRaisesRegex(RuntimeError, "POWER_AUTOMATE_WEBHOOK_URL"):
            handoff.deliver(self.sample_payload(), webhook_url="")

    def test_deliver_rejects_mismatched_receipt(self):
        def opener(_request, timeout):
            return FakeHttpResponse(
                {
                    "status": "created",
                    "videoId": "wrongVideo1",
                    "fileName": "2026-08-12_wrongVideo1.json",
                }
            )

        with self.assertRaisesRegex(RuntimeError, "invalid delivery receipt"):
            handoff.deliver(
                self.sample_payload(),
                webhook_url="https://example.test/receiver",
                opener=opener,
            )

    def test_deliver_rejects_non_2xx_response(self):
        def opener(_request, timeout):
            return FakeHttpResponse({"error": "unavailable"}, status=503)

        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            handoff.deliver(
                self.sample_payload(),
                webhook_url="https://example.test/receiver",
                opener=opener,
            )

    def test_deliver_rejects_malformed_json_response(self):
        def opener(_request, timeout):
            return FakeRawResponse(b"not-json")

        with self.assertRaisesRegex(RuntimeError, "invalid delivery receipt"):
            handoff.deliver(
                self.sample_payload(),
                webhook_url="https://example.test/receiver",
                opener=opener,
            )

    def test_deliver_hides_url_when_connection_fails(self):
        def opener(_request, timeout):
            raise URLError("temporary DNS failure")

        secret_url = "https://example.test/sensitive-callback-signature"
        with self.assertRaises(RuntimeError) as raised:
            handoff.deliver(
                self.sample_payload(),
                webhook_url=secret_url,
                opener=opener,
            )
        self.assertNotIn(secret_url, str(raised.exception))
```

- [ ] **Step 6: Run the delivery tests and verify RED**

Run:

```bash
python3.12 -m unittest tests.test_handoff.HandoffTests.test_deliver_posts_json_and_validates_receipt tests.test_handoff.HandoffTests.test_deliver_requires_webhook_url tests.test_handoff.HandoffTests.test_deliver_rejects_mismatched_receipt tests.test_handoff.HandoffTests.test_deliver_rejects_non_2xx_response tests.test_handoff.HandoffTests.test_deliver_rejects_malformed_json_response tests.test_handoff.HandoffTests.test_deliver_hides_url_when_connection_fails -v
```

Expected: errors because `deliver` does not exist.

- [ ] **Step 7: Implement HTTP delivery and strict receipt validation**

Add to `src/handoff.py`:

```python
def deliver(
    payload: dict[str, object],
    webhook_url: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> DeliveryReceipt:
    resolved_url = (
        webhook_url or os.environ.get("POWER_AUTOMATE_WEBHOOK_URL", "")
    ).strip()
    if not resolved_url:
        raise RuntimeError("POWER_AUTOMATE_WEBHOOK_URL is not configured.")

    expected_video_id = str(payload.get("videoId", "")).strip()
    expected_file_name = file_name_for(
        str(payload.get("published", "")),
        expected_video_id,
    )
    request = Request(
        resolved_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=60) as response:
            status_code = getattr(response, "status", 200)
            response_body = response.read()
    except HTTPError as error:
        raise RuntimeError(
            f"Power Automate handoff failed with HTTP {error.code}."
        ) from error
    except (URLError, OSError) as error:
        raise RuntimeError("Power Automate handoff could not connect.") from error

    if not 200 <= status_code < 300:
        raise RuntimeError(
            f"Power Automate handoff failed with HTTP {status_code}."
        )
    try:
        result = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError("Power Automate returned invalid delivery receipt.") from error

    receipt = DeliveryReceipt(
        status=str(result.get("status", "")),
        video_id=str(result.get("videoId", "")),
        file_name=str(result.get("fileName", "")),
    )
    if (
        receipt.status not in {"created", "already_exists"}
        or receipt.video_id != expected_video_id
        or receipt.file_name != expected_file_name
    ):
        raise RuntimeError("Power Automate returned invalid delivery receipt.")
    return receipt
```

- [ ] **Step 8: Run all handoff tests and commit**

Run:

```bash
python3.12 -m unittest tests.test_handoff -v
python3.12 -m compileall -q src tests
git diff --check
```

Expected: all handoff tests pass and checks exit zero.

Commit:

```bash
git add src/handoff.py tests/test_handoff.py
git commit -m "Add Power Automate handoff client"
```

---

### Task 3: Delivery Ordering, Force Mode, and Redacted Output

**Files:**
- Modify: `src/check_feed.py`
- Modify: `tests/test_check_feed.py`

**Interfaces:**
- Consumes: `handoff.build_payload`, `handoff.deliver`, and `handoff.DeliveryReceipt` from Task 2.
- Produces: `run(..., webhook_url: str | None = None, deliverer: Callable = handoff.deliver, force_delivery: bool = False) -> str`.
- Produces: log output containing `DELIVERY STATUS` and `FILE`, never the full transcript.

- [ ] **Step 1: Write the failing successful-delivery/state test**

Replace the current successful `run` test with a fake delivery function that captures the payload:

```python
    def test_run_delivers_before_persisting_video_id(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])
        delivered = []

        def deliverer(payload, webhook_url):
            delivered.append((payload, webhook_url))
            return check_feed.handoff.DeliveryReceipt(
                status="created",
                video_id="abc123xyz89",
                file_name="2026-08-12_abc123xyz89.json",
            )

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state" / "last_video_id.txt"
            output = check_feed.run(
                parser=lambda _: parsed_feed,
                api_key="supadata-secret",
                opener=lambda _request, timeout: FakeHttpResponse(
                    {"content": "Cloud transcript works"}
                ),
                state_path=state_path,
                webhook_url="https://example.test/receiver",
                deliverer=deliverer,
            )

            self.assertEqual(
                state_path.read_text(encoding="utf-8"),
                "abc123xyz89\n",
            )

        self.assertEqual(delivered[0][0]["transcript"], "Cloud transcript works")
        self.assertEqual(delivered[0][1], "https://example.test/receiver")
        self.assertIn("DELIVERY STATUS:\ncreated", output)
        self.assertIn("FILE:\n2026-08-12_abc123xyz89.json", output)
        self.assertNotIn("Cloud transcript works", output)
        self.assertNotIn("supadata-secret", output)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3.12 -m unittest tests.test_check_feed.CheckFeedTests.test_run_delivers_before_persisting_video_id -v
```

Expected: `run` rejects the new `webhook_url` or `deliverer` argument.

- [ ] **Step 3: Implement delivery before state persistence**

Import the module:

```python
from src import handoff
```

Change `run` to accept:

```python
    webhook_url: str | None = None,
    deliverer: Callable[..., handoff.DeliveryReceipt] = handoff.deliver,
    force_delivery: bool = False,
```

Keep the existing state check only when `force_delivery` is false. After
transcript extraction, build and deliver the payload, then write state:

```python
    payload = handoff.build_payload(
        video_id=video.id,
        title=video.title,
        published=video.published,
        link=video.link,
        description=video.description,
        transcript=transcript,
    )
    receipt = deliverer(payload, webhook_url=webhook_url)
    if resolved_state_path is not None:
        resolved_state_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_state_path.write_text(f"{video.id}\n", encoding="utf-8")
    return format_delivered_output(video, receipt)
```

Delete the old `format_output`, which includes the full transcript. Replace it
with:

```python
def format_delivered_output(
    video: Video,
    receipt: handoff.DeliveryReceipt,
) -> str:
    return "\n\n".join(
        [
            "STATUS:\nDELIVERED",
            f"DELIVERY STATUS:\n{receipt.status}",
            f"FILE:\n{receipt.file_name}",
            f"TITLE:\n{video.title}",
            f"PUBLISHED:\n{video.published}",
            f"LINK:\n{video.link}",
            f"VIDEO ID:\n{video.id}",
        ]
    )
```

- [ ] **Step 4: Add failing delivery-failure and force-delivery tests**

Add:

```python
    def test_run_does_not_persist_when_delivery_fails(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])

        def failed_delivery(_payload, webhook_url):
            raise RuntimeError("Power Automate handoff failed")

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state" / "last_video_id.txt"
            with self.assertRaisesRegex(RuntimeError, "handoff failed"):
                check_feed.run(
                    parser=lambda _: parsed_feed,
                    api_key="supadata-secret",
                    opener=lambda _request, timeout: FakeHttpResponse(
                        {"content": "Cloud transcript works"}
                    ),
                    state_path=state_path,
                    webhook_url="https://example.test/receiver",
                    deliverer=failed_delivery,
                )
            self.assertFalse(state_path.exists())

    def test_force_delivery_bypasses_matching_state(self):
        parsed_feed = SimpleNamespace(status=200, entries=[sample_entry()])
        calls = []

        def deliverer(payload, webhook_url):
            calls.append(payload["videoId"])
            return check_feed.handoff.DeliveryReceipt(
                status="already_exists",
                video_id="abc123xyz89",
                file_name="2026-08-12_abc123xyz89.json",
            )

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "last_video_id.txt"
            state_path.write_text("abc123xyz89\n", encoding="utf-8")
            output = check_feed.run(
                parser=lambda _: parsed_feed,
                api_key="supadata-secret",
                opener=lambda _request, timeout: FakeHttpResponse(
                    {"content": "Cloud transcript works"}
                ),
                state_path=state_path,
                webhook_url="https://example.test/receiver",
                deliverer=deliverer,
                force_delivery=True,
            )

        self.assertEqual(calls, ["abc123xyz89"])
        self.assertIn("DELIVERY STATUS:\nalready_exists", output)
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```bash
python3.12 -m unittest tests.test_check_feed.CheckFeedTests.test_run_delivers_before_persisting_video_id tests.test_check_feed.CheckFeedTests.test_run_does_not_persist_when_delivery_fails tests.test_check_feed.CheckFeedTests.test_force_delivery_bypasses_matching_state -v
```

Expected: all three tests pass.

- [ ] **Step 6: Wire environment-based force mode without breaking test injection**

Keep `main(runner=run)` unchanged. Change only the executable entry point:

```python
if __name__ == "__main__":
    main(
        runner=lambda: run(
            force_delivery=os.environ.get("FORCE_DELIVERY", "false").lower()
            == "true"
        )
    )
```

Run:

```bash
python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
git diff --check
```

Expected: all tests pass; no transcript appears in successful run output tests.

- [ ] **Step 7: Commit the orchestration change**

```bash
git add src/check_feed.py tests/test_check_feed.py
git commit -m "Deliver transcripts before recording state"
```

---

### Task 4: GitHub Actions Secret and Manual Force Input

**Files:**
- Modify: `.github/workflows/check-videos.yml`

**Interfaces:**
- Consumes: repository secrets `SUPADATA_API_KEY` and `POWER_AUTOMATE_WEBHOOK_URL`.
- Produces: manual boolean input `force_delivery`; environment string `FORCE_DELIVERY`.

- [ ] **Step 1: Add the manual input and webhook environment**

Update the trigger:

```yaml
on:
  workflow_dispatch:
    inputs:
      force_delivery:
        description: Re-deliver the latest video even if it was processed
        required: false
        type: boolean
        default: false
  schedule:
    - cron: "*/30 * * * *"
```

Update **Check latest video transcript**:

```yaml
      - name: Check latest video transcript
        env:
          SUPADATA_API_KEY: ${{ secrets.SUPADATA_API_KEY }}
          POWER_AUTOMATE_WEBHOOK_URL: ${{ secrets.POWER_AUTOMATE_WEBHOOK_URL }}
          FORCE_DELIVERY: ${{ github.event_name == 'workflow_dispatch' && inputs.force_delivery == true && 'true' || 'false' }}
        run: python src/check_feed.py
```

- [ ] **Step 2: Validate YAML and the full local suite**

Run:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/check-videos.yml"); puts "workflow yaml parses"'
python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
git diff --check
```

Expected: YAML parses, every test passes, compilation and diff checks exit zero.

- [ ] **Step 3: Commit and push the implementation**

```bash
git add .github/workflows/check-videos.yml
git commit -m "Send transcripts to Power Automate"
git push origin main
```

Expected: `main` and `origin/main` point to the same implementation commit.

---

### Task 5: End-to-End OneDrive Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-12-onedrive-handoff-design.md`

**Interfaces:**
- Consumes: pushed workflow, both GitHub secrets, saved Power Automate receiver flow.
- Produces: verified OneDrive file and acceptance evidence recorded in the design spec.

- [ ] **Step 1: Confirm secret names without reading values**

Run:

```bash
gh api repos/egehuriel/tminus365-monitor/actions/secrets --jq '.secrets[].name'
```

Expected: output contains both:

```text
POWER_AUTOMATE_WEBHOOK_URL
SUPADATA_API_KEY
```

- [ ] **Step 2: Run the first forced cloud delivery**

Run:

```bash
gh workflow run check-videos.yml --repo egehuriel/tminus365-monitor --ref main -f force_delivery=true
tminus_run_id=$(gh run list --repo egehuriel/tminus365-monitor --workflow check-videos.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$tminus_run_id" --repo egehuriel/tminus365-monitor --exit-status
```

Expected: unit tests, transcript extraction, Power Automate handoff, and state persistence all pass.

- [ ] **Step 3: Verify the created OneDrive file**

In company OneDrive, open `/TMinus365/Transcripts`.

Expected:

```text
Exactly one YYYY-MM-DD_VIDEO_ID.json file for the latest feed video.
```

Open it and verify:

```text
schemaVersion = 1
videoId is nonempty
title is nonempty
published is nonempty
link is a YouTube URL
description exists
transcript is nonempty English text
```

- [ ] **Step 4: Verify duplicate-safe forced delivery**

Dispatch and watch a second `force_delivery=true` run using the same commands.

Expected Action log labels:

```text
STATUS:
DELIVERED

DELIVERY STATUS:
already_exists
```

Expected OneDrive result: still exactly one file, with unchanged content and modification time.

- [ ] **Step 5: Verify normal duplicate skip**

Dispatch without the force input:

```bash
gh workflow run check-videos.yml --repo egehuriel/tminus365-monitor --ref main
```

Watch the run. Expected log labels:

```text
STATUS:
ALREADY PROCESSED
```

Expected: no Supadata or Power Automate request is made and no OneDrive file changes.

- [ ] **Step 6: Record evidence and run final verification**

Append the three GitHub run URLs and verified OneDrive filename to the design spec without adding the callback URL or transcript content.

Run:

```bash
python3.12 -m unittest discover -s tests -v
python3.12 -m compileall -q src tests
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/check-videos.yml"); puts "workflow yaml parses"'
git diff --check
git status --short --branch
```

Expected: all tests pass, YAML parses, checks exit zero, and only the evidence document is modified.

- [ ] **Step 7: Commit and push acceptance evidence**

```bash
git add docs/superpowers/specs/2026-08-12-onedrive-handoff-design.md
git commit -m "Document OneDrive handoff verification"
git push origin main
```

Expected: clean worktree with `main` synchronized to `origin/main`.
