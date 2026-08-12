# T-Minus365 Standard-Only Power Automate Importer

This flow imports the public transcript JSON produced by GitHub Actions into the
company OneDrive account. It uses only built-in controls and the Standard
OneDrive for Business connector.

## Prerequisites

Create these folders in the connected company OneDrive:

```text
/TMinus365/Staging
/TMinus365/Transcripts
```

The public source is:

```text
https://raw.githubusercontent.com/egehuriel/tminus365-monitor/main/outbox/latest.json
```

## Create the Flow

Create a **Scheduled cloud flow** named `TMinus365 Transcript Importer`. Set it
to run every 30 minutes.

### 1. Download latest JSON

Add **OneDrive for Business → Upload file from URL** and rename it
`Download latest JSON`.

Enter Source URL as an expression:

```text
concat(
  'https://raw.githubusercontent.com/egehuriel/tminus365-monitor/main/outbox/latest.json?ts=',
  ticks(utcNow())
)
```

Set:

```text
Destination File Path: /TMinus365/Staging/latest.json
Overwrite: Yes
```

### 2. Wait for the download

Add **Schedule → Delay**, rename it `Wait for download`, and set:

```text
Count: 30
Unit: Second
```

The wait is required because the OneDrive URL upload can report success before
the transfer has finished.

### 3. Read staging JSON

Add **OneDrive for Business → Get file content using path**, rename it
`Read latest JSON`, and set:

```text
File Path: /TMinus365/Staging/latest.json
```

### 4. Parse the payload

Add **Data Operations → Parse JSON**, rename it `Parse transcript JSON`, and
select the file content from `Read latest JSON` as Content. Use this schema:

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
    "fileName": {
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
    "fileName",
    "title",
    "published",
    "link",
    "description",
    "transcript"
  ],
  "additionalProperties": false
}
```

### 5. Find an existing transcript

Add **OneDrive for Business → List files in folder**, rename it
`List transcript files`, and select:

```text
/TMinus365/Transcripts
```

Add **Data Operations → Filter array**, rename it `Filter matching file`.
For **From**, select the `value` output from `List transcript files`. Use
advanced mode with:

```text
@equals(item()?['Name'], body('Parse_transcript_JSON')?['fileName'])
```

### 6. Create only when absent

Add a **Condition**, rename it `Transcript already exists`, and enter:

```text
@greater(length(body('Filter_matching_file')), 0)
```

Leave the **Yes** branch empty.

In the **No** branch, add **OneDrive for Business → Create file**, rename it
`Create transcript file`, and set:

```text
Folder Path: /TMinus365/Transcripts
File Name: fileName from Parse transcript JSON
File Content: File content from Read latest JSON
```

Save the flow and open **Flow checker**. It must show zero errors and no Premium
license warning.

## Manual Verification

1. Confirm the public raw GitHub URL returns schema version 1 JSON.
2. Run `TMinus365 Transcript Importer` manually.
3. Confirm `/TMinus365/Transcripts/<fileName>` exists and contains all eight
   fields with a nonempty English transcript.
4. Record the file modification time.
5. Run the importer again.
6. Confirm no duplicate appears and the existing file modification time is
   unchanged.
