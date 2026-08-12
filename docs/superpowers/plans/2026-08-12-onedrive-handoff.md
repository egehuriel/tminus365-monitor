# T-Minus365 Standard-Only OneDrive Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the latest public T-Minus365 transcript as versioned JSON in GitHub and import it into company OneDrive without a Power Automate Premium feature.

**Architecture:** GitHub Actions writes `outbox/latest.json` atomically and commits it with processed-video state. A scheduled Power Automate flow uses built-in controls plus the Standard OneDrive for Business connector to pull, validate, deduplicate, and save the JSON.

**Tech Stack:** Python 3.12 standard library, `unittest`, GitHub Actions, GitHub raw content, Power Automate scheduled cloud flow, OneDrive for Business Standard connector.

## Global Constraints

- Keep RSS URL `https://www.youtube.com/feeds/videos.xml?channel_id=UCePaXDDk5kl3g7FcJ5gH5AQ`.
- Keep Supadata mode `native`, language `en`, and text response enabled.
- Keep `SUPADATA_API_KEY` only in GitHub Actions secrets; never serialize or log it.
- JSON has exactly `schemaVersion`, `videoId`, `fileName`, `title`, `published`, `link`, `description`, and `transcript`; schema version is integer `1`.
- Use filename `YYYY-MM-DD_VIDEO_ID.json` and stable UTF-8 JSON with two-space indentation and one trailing newline.
- Normal runs skip matching state before Supadata; manual `force_export` may regenerate it.
- Do not print transcript content after export is enabled.
- Commit `outbox/latest.json` and `state/last_video_id.txt` together.
- Use no HTTP trigger/action, custom connector, webhook, Azure app, or Premium connector.
- Use `/TMinus365/Staging` and `/TMinus365/Transcripts`; never overwrite a deterministic transcript file.
- Do not add summarization, classification, Teams/email delivery, or downstream processing.

## File Map

- Create `src/transcript_export.py`: payload validation, filename derivation, serialization, atomic write.
- Create `tests/test_transcript_export.py`: export contract and filesystem tests.
- Modify `src/check_feed.py`: export orchestration, force mode, state ordering, redacted output.
- Modify `tests/test_check_feed.py`: orchestration and redaction tests.
- Modify `.github/workflows/check-videos.yml`: force input and joint publication commit.
- Create `tests/test_workflow.py`: workflow contract tests.
- Create `docs/power-automate-standard-importer.md`: exact Standard-only flow instructions.
- Modify the design spec only after end-to-end verification to record evidence.

---

### Task 1: Transcript JSON Export Boundary

**Files:**
- Create: `src/transcript_export.py`
- Create: `tests/test_transcript_export.py`

**Interfaces:**
- Produces `DEFAULT_OUTBOX_PATH = Path("outbox/latest.json")`.
- Produces `file_name_for(published: str, video_id: str) -> str`.
- Produces `build_payload(*, video_id: str, title: str, published: str, link: str, description: str, transcript: str) -> dict[str, object]`.
- Produces `serialize_payload(payload: dict[str, object]) -> str`.
- Produces `write_latest(payload: dict[str, object], path: Path | str = DEFAULT_OUTBOX_PATH) -> Path`.

- [ ] **Step 1: Write failing contract tests**

Create tests covering these exact assertions:

```python
self.assertEqual(
    transcript_export.file_name_for(
        "2026-08-12T08:00:00+00:00", "abc123xyz89"
    ),
    "2026-08-12_abc123xyz89.json",
)
self.assertEqual(transcript_export.build_payload(
    video_id="abc123xyz89",
    title="Latest T-Minus365 video",
    published="2026-08-12T08:00:00+00:00",
    link="https://www.youtube.com/watch?v=abc123xyz89",
    description="A useful description.",
    transcript="Cloud transcript works",
), {
    "schemaVersion": 1,
    "videoId": "abc123xyz89",
    "fileName": "2026-08-12_abc123xyz89.json",
    "title": "Latest T-Minus365 video",
    "published": "2026-08-12T08:00:00+00:00",
    "link": "https://www.youtube.com/watch?v=abc123xyz89",
    "description": "A useful description.",
    "transcript": "Cloud transcript works",
})
```

Add table-driven empty-field tests for `video_id`, `title`, `published`, `link`,
and `transcript`, plus invalid ISO timestamp, extra payload field, UTF-8 title,
trailing newline, parent directory creation, and absence of `.json.tmp` after a
successful atomic write.

- [ ] **Step 2: Run tests and verify RED**

Run `python3 -m unittest tests.test_transcript_export -v`.

Expected: import failure because `src/transcript_export.py` does not exist.

- [ ] **Step 3: Implement filename and exact payload validation**

Create the module with these constants and core functions:

```python
DEFAULT_OUTBOX_PATH = Path("outbox/latest.json")
EXACT_FIELDS = (
    "schemaVersion", "videoId", "fileName", "title",
    "published", "link", "description", "transcript",
)

def file_name_for(published: str, video_id: str) -> str:
    clean_id = video_id.strip()
    if not clean_id:
        raise RuntimeError("Video ID is required for transcript export.")
    try:
        instant = datetime.fromisoformat(published.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("Published timestamp is not valid ISO 8601.") from error
    return f"{instant.date().isoformat()}_{clean_id}.json"
```

`build_payload` strips required text, allows an empty description, rejects an
empty required field, derives `fileName`, and returns fields in `EXACT_FIELDS`
order. `_validate_payload` requires the exact ordered keys, schema version `1`,
string types, nonempty required text, and a filename matching metadata.

- [ ] **Step 4: Implement stable serialization and atomic write**

```python
def serialize_payload(payload: dict[str, object]) -> str:
    _validate_payload(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

def write_latest(payload, path=DEFAULT_OUTBOX_PATH) -> Path:
    resolved = Path(path)
    serialized = serialize_payload(payload)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(f"{resolved.suffix}.tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(resolved)
    return resolved
```

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
python3 -m unittest tests.test_transcript_export -v
python3 -m compileall -q src tests
git diff --check
git add src/transcript_export.py tests/test_transcript_export.py
git commit -m "Add public transcript JSON export"
```

Expected: all export tests pass and the commit contains only the module/tests.

---

### Task 2: Monitor Orchestration, Force Mode, and Redaction

**Files:**
- Modify: `src/check_feed.py`
- Modify: `tests/test_check_feed.py`

**Interfaces:**
- Consumes Task 1's `build_payload` and `write_latest`.
- Produces `run(..., output_path=DEFAULT_OUTBOX_PATH, force_export=False, exporter=write_latest) -> str`.
- Produces `environment_flag(name: str, environ: Mapping[str, str] = os.environ) -> bool`.

- [ ] **Step 1: Write failing orchestration tests**

Replace the current transcript-printing test with one that runs into a temporary
outbox and asserts:

```python
payload = json.loads(output_path.read_text(encoding="utf-8"))
self.assertEqual(payload["transcript"], "Cloud transcript works")
self.assertIn("STATUS:\nEXPORTED", output)
self.assertIn("FILE:\n2026-08-12_abc123xyz89.json", output)
self.assertNotIn("Cloud transcript works", output)
self.assertNotIn("TRANSCRIPT:", output)
```

Add tests proving: matching state skips export and Supadata; `force_export=True`
ignores matching state; a failing injected exporter leaves state unchanged;
`environment_flag` accepts case-insensitive `true` only; `main()` passes the
environment flag to `run`.

- [ ] **Step 2: Run focused tests and verify RED**

Run the five new tests with `python3 -m unittest ... -v`.

Expected: failures for missing `output_path`, `force_export`, `exporter`, and
`environment_flag`, and for transcript still appearing in output.

- [ ] **Step 3: Implement redacted output and export ordering**

Import `Mapping` and `src.transcript_export`. Replace `format_output` with:

```python
def format_exported(video: Video, file_name: str, output_path: Path) -> str:
    return "\n\n".join([
        "STATUS:\nEXPORTED",
        f"TITLE:\n{video.title}",
        f"PUBLISHED:\n{video.published}",
        f"LINK:\n{video.link}",
        f"VIDEO ID:\n{video.id}",
        f"FILE:\n{file_name}",
        f"OUTBOX:\n{output_path.as_posix()}",
    ])
```

Guard the state skip with `not force_export`. After transcript extraction,
build the payload and call the injected exporter. Write state only after that
call returns, then return `format_exported`. This ordering is required so a
serialization/write failure is retried.

- [ ] **Step 4: Implement executable force parsing**

```python
def environment_flag(name: str, environ: Mapping[str, str] = os.environ) -> bool:
    return environ.get(name, "").strip().lower() == "true"

def main(runner: Callable[[], str] | None = None) -> None:
    resolved_runner = runner or (
        lambda: run(force_export=environment_flag("FORCE_EXPORT"))
    )
    print(resolved_runner())
```

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
rg -n "TRANSCRIPT:|format_output" src tests || true
git diff --check
git add src/check_feed.py tests/test_check_feed.py
git commit -m "Export transcripts without logging content"
```

Expected: all tests pass and production code never prints transcript content.

---

### Task 3: GitHub Actions Publication Contract

**Files:**
- Modify: `.github/workflows/check-videos.yml`
- Create: `tests/test_workflow.py`

**Interfaces:**
- Consumes `FORCE_EXPORT` and `src/check_feed.py`.
- Produces boolean workflow input `force_export`, default `false`.
- Produces one commit containing outbox plus state.

- [ ] **Step 1: Write failing workflow text tests**

Create `tests/test_workflow.py` that reads the workflow and asserts:

```python
self.assertIn("force_export:", workflow)
self.assertIn("type: boolean", workflow)
self.assertIn("default: false", workflow)
self.assertIn("FORCE_EXPORT:", workflow)
self.assertIn("inputs.force_export", workflow)
self.assertIn("git add state/last_video_id.txt", workflow)
self.assertIn("if [ -f outbox/latest.json ]; then", workflow)
self.assertIn("git add outbox/latest.json", workflow)
self.assertNotIn("POWER_AUTOMATE_WEBHOOK_URL", workflow)
```

- [ ] **Step 2: Run tests and verify RED**

Run `python3 -m unittest tests.test_workflow -v`.

Expected: force/joint-publication assertions fail.

- [ ] **Step 3: Update workflow trigger and monitor step**

```yaml
workflow_dispatch:
  inputs:
    force_export:
      description: Regenerate the latest transcript JSON
      required: false
      type: boolean
      default: false
```

Set monitor environment:

```yaml
SUPADATA_API_KEY: ${{ secrets.SUPADATA_API_KEY }}
FORCE_EXPORT: ${{ github.event_name == 'workflow_dispatch' && inputs.force_export == true && 'true' || 'false' }}
```

- [ ] **Step 4: Commit outbox and state together**

Replace the final step with:

```yaml
- name: Publish transcript JSON and processed video ID
  run: |
    git add state/last_video_id.txt
    if [ -f outbox/latest.json ]; then
      git add outbox/latest.json
    fi
    if git diff --cached --quiet; then
      echo "Latest video was already published."
      exit 0
    fi
    git config user.name "github-actions[bot]"
    git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
    git commit -m "Publish T-Minus365 transcript"
    git push
```

- [ ] **Step 5: Verify workflow and commit**

```bash
python3 -m unittest discover -s tests -v
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/check-videos.yml"); puts "workflow yaml parses"'
git diff --check
git add .github/workflows/check-videos.yml tests/test_workflow.py
git commit -m "Publish transcript JSON from GitHub Actions"
```

Expected: all tests pass and YAML parses.

---

### Task 4: Standard-Only Power Automate Guide

**Files:**
- Create: `docs/power-automate-standard-importer.md`

**Interfaces:**
- Consumes `https://raw.githubusercontent.com/egehuriel/tminus365-monitor/main/outbox/latest.json`.
- Produces flow `TMinus365 Transcript Importer` and immutable OneDrive transcript file.

- [ ] **Step 1: Write the exact guide**

Document these cards and values in order:

1. **Recurrence**, every 30 minutes.
2. **OneDrive for Business → Upload file from URL**, renamed `Download latest JSON`.
   Source expression:

   ```text
   concat(
     'https://raw.githubusercontent.com/egehuriel/tminus365-monitor/main/outbox/latest.json?ts=',
     ticks(utcNow())
   )
   ```

   Destination `/TMinus365/Staging/latest.json`, overwrite `Yes`.
3. **Delay**, 30 seconds.
4. **Get file content using path**, `/TMinus365/Staging/latest.json`.
5. **Parse JSON** with file content and this schema:

   ```json
   {
     "type": "object",
     "properties": {
       "schemaVersion": {"type": "integer", "enum": [1]},
       "videoId": {"type": "string", "minLength": 1},
       "fileName": {"type": "string", "minLength": 1},
       "title": {"type": "string", "minLength": 1},
       "published": {"type": "string", "minLength": 1},
       "link": {"type": "string", "minLength": 1},
       "description": {"type": "string"},
       "transcript": {"type": "string", "minLength": 1}
     },
     "required": ["schemaVersion", "videoId", "fileName", "title",
       "published", "link", "description", "transcript"],
     "additionalProperties": false
   }
   ```

6. **List files in folder**, `/TMinus365/Transcripts`.
7. **Filter array** over the list `value`, advanced expression:

   ```text
   @equals(item()?['Name'], body('Parse_transcript_JSON')?['fileName'])
   ```

8. **Condition**:

   ```text
   @greater(length(body('Filter_matching_file')), 0)
   ```

   Yes: no action. No: **Create file** in `/TMinus365/Transcripts`, name from
   parsed `fileName`, content from the staging file-content action.

Include manual first-run and duplicate-run checks. State explicitly that Flow
checker must show zero errors and no Premium warning.

- [ ] **Step 2: Validate and commit the guide**

```bash
rg -n "Upload file from URL|Get file content using path|List files in folder|Create file|additionalProperties" docs/power-automate-standard-importer.md
if rg -n "When an HTTP request is received|POWER_AUTOMATE_WEBHOOK_URL|custom connector" docs/power-automate-standard-importer.md; then exit 1; fi
git diff --check
git add docs/power-automate-standard-importer.md
git commit -m "Document Standard-only OneDrive importer"
```

Expected: required Standard steps exist and forbidden Premium architecture does not.

---

### Task 5: Cloud and OneDrive Acceptance

**Files:**
- Modify after observation: `docs/superpowers/specs/2026-08-12-onedrive-handoff-design.md`

**Interfaces:**
- Produces public `outbox/latest.json`, successful forced and skip run URLs, saved Standard-only importer, and one immutable OneDrive file.

- [ ] **Step 1: Verify locally and push**

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/check-videos.yml"); puts "workflow yaml parses"'
git diff --check
gh api repos/egehuriel/tminus365-monitor/actions/secrets --jq '.secrets[].name'
git push origin main
```

Expected: tests/checks pass, output includes `SUPADATA_API_KEY`, and branches synchronize.

- [ ] **Step 2: Force and watch public export**

```bash
gh workflow run check-videos.yml --repo egehuriel/tminus365-monitor --ref main -f force_export=true
tminus_run_id=$(gh run list --repo egehuriel/tminus365-monitor --workflow check-videos.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$tminus_run_id" --repo egehuriel/tminus365-monitor --exit-status
```

Expected: success and a commit containing outbox plus state.

- [ ] **Step 3: Verify public contract without printing transcript**

```bash
curl -fL "https://raw.githubusercontent.com/egehuriel/tminus365-monitor/main/outbox/latest.json?ts=$(date +%s)" -o /tmp/tminus365-latest.json
jq '{keys:(keys|sort),schemaVersion,videoId,fileName,title,published,link,descriptionLength:(.description|length),transcriptLength:(.transcript|length)}' /tmp/tminus365-latest.json
if rg -n "SUPADATA_API_KEY|POWER_AUTOMATE_WEBHOOK_URL|x-api-key" /tmp/tminus365-latest.json; then exit 1; fi
```

Expected: exactly eight keys, schema `1`, nonempty metadata, transcript length above zero, no credentials.

- [ ] **Step 4: Verify normal duplicate skip**

Dispatch without force and watch as above. Expected log `STATUS: ALREADY PROCESSED`, no Supadata request, no new commit.

- [ ] **Step 5: Build and license-check Power Automate flow**

Follow `docs/power-automate-standard-importer.md`. Confirm folders exist, save
the flow, and require Flow checker results:

```text
Errors: 0
Premium license warnings: 0
```

Turn off the abandoned Premium receiver; do not copy its URL or add a webhook secret.

- [ ] **Step 6: Verify creation and duplicate safety**

Run importer once: exactly one `/TMinus365/Transcripts/<fileName>` exists with
all eight fields and nonempty English transcript. Record filename, byte size,
and modification time without transcript text. Run again: succeeded, still one
file, unchanged modification time.

- [ ] **Step 7: Record evidence, verify, commit, and push**

Append observed GitHub run URLs, actual OneDrive filename/size, no-Premium check,
and duplicate result to the design spec. Do not record secrets, tenant details,
connection IDs, or transcript text.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/check-videos.yml")'
git diff --check
git add docs/superpowers/specs/2026-08-12-onedrive-handoff-design.md
git commit -m "Document Standard-only OneDrive verification"
git push origin main
git status --short --branch
```

Expected: clean worktree, synchronized `main`, passing checks, and complete end-to-end evidence.
