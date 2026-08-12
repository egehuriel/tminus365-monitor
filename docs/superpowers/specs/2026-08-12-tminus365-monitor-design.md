# T-Minus365 Monitor: Cloud Transcript Design

## Goal

Run entirely in GitHub Actions while the user's computer is off: read the latest
T-Minus365 YouTube feed item and obtain its English transcript. Power Automate
handoff remains out of scope until this cloud proof succeeds.

## Architecture

The Python 3.12 script uses only the standard library. It parses the YouTube Atom
feed, validates the newest video's metadata, and requests the existing English
caption track from Supadata's transcript endpoint with `mode=native` and
`text=true`.

The Supadata key is supplied only through the GitHub Actions repository secret
`SUPADATA_API_KEY`. It is never stored in source control or printed to logs.

The first Supadata workflow revision is manual-only. After one successful cloud
run, processed-video state is added before restoring the 30-minute schedule so
repeated checks do not spend one transcript credit on the same video.

## Failure Behavior

Feed HTTP failures, invalid XML, missing video metadata, missing API-key
configuration, Supadata HTTP failures, invalid JSON, and empty transcripts all
fail the process with a phase-specific error. The API key is not included in
error messages.

## Verification Gate

The cloud proof is complete only when a manually dispatched GitHub Actions run:

1. passes all network-free unit tests;
2. reads the configured T-Minus365 RSS feed;
3. prints a nonempty video ID, title, link, and English transcript; and
4. does not expose `SUPADATA_API_KEY`.

Only after that proof will duplicate prevention and scheduled execution be
enabled. Power Automate integration remains deferred.
