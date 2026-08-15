# Project Osho YouTube Publishing

## Publishing boundary

Project Osho treats rendering and publishing as separate concerns.

A successfully rendered clip is **not** considered published until the YouTube publisher returns a successful platform response and Osho records durable evidence of that success.

## Ready-to-upload state

A completed production job can enter:

```text
ready_to_upload
```

At this point:

- the render exists;
- metadata is complete;
- QA has passed;
- the publisher has not yet proven success.

The dashboard may show 100% processing progress while the job remains in this state.

## Publishing flow

Recommended sequence:

```text
ready_to_upload
      |
      v
idempotency / receipt check
      |
      v
uploading
      |
      +--- API error ---> failed/retryable
      |
      v
YouTube returns video ID
      |
      v
write durable receipt
      |
      v
update job state
      |
      v
published
```

The receipt should be written before the system treats the job as safely complete.

## Upload receipts

Durable receipt location:

```text
/srv/osho/youtube/receipts
```

A receipt should capture enough information to reconcile state after a crash, including:

```json
{
  "source_id": "000001",
  "job_id": "OSHO-...",
  "video_id": "example",
  "youtube_url": "https://www.youtube.com/watch?v=example",
  "uploaded_at": "ISO-8601 timestamp",
  "title": "...",
  "render_file": "...",
  "privacy": "public",
  "pipeline_version": "..."
}
```

Do not store OAuth credentials in receipt files.

## Proven publishing behavior

Project Osho has produced successful YouTube video IDs during development, including:

```text
WZKMoBtfreM
crS_KjpMI-U
LAbpetJoUKo
```

The autopilot has also demonstrated reconciliation behavior such as:

```text
000009 RECONCILED AS PUBLISHED: LAbpetJoUKo
```

This is an important safety property: if an upload succeeded before a local state update completed, Osho should reconcile the known video ID instead of creating a duplicate upload.

## Privacy mode

The zero-touch configuration has been observed with:

```text
AUTO_UPLOAD: true
PRIVACY: public
```

Because `public` publishing is irreversible from the perspective of audience exposure, production mode should require all QA gates and idempotency checks to pass.

Test mode must never inherit public auto-upload behavior accidentally.

## OAuth and credential policy

YouTube publishing requires secrets that **must not be committed to GitHub**.

Never commit:

```text
client_secret.json
credentials.json
token.json
refresh tokens
access tokens
API keys
browser cookies
service-account secrets
```

Recommended storage approach:

- store secrets only on the publishing/control-plane host;
- restrict file permissions to the service account/user;
- keep secret paths outside the Git checkout;
- reference those paths through environment variables or systemd credentials;
- keep only `.env.example` or sanitized sample configuration in Git.

Example non-secret configuration:

```text
OSHO_AUTO_UPLOAD=true
OSHO_YOUTUBE_PRIVACY=public
OSHO_RECEIPT_DIR=/srv/osho/youtube/receipts
OSHO_YOUTUBE_TOKEN_FILE=/path/outside/git/token.json
```

The real token path may be documented, but the token content must not be.

## Duplicate prevention

Before every upload:

1. Check whether the source/job already has a successful receipt.
2. Check whether local job state already contains a YouTube video ID.
3. If available, reconcile external platform state from known receipts/IDs.
4. Only upload when no durable success evidence exists.

After upload:

1. Validate that a non-empty video ID was returned.
2. Write the receipt atomically.
3. Update job state to published.
4. Update dashboard/latest-upload state.

## Failure scenarios

### API call fails before YouTube accepts upload

Mark the job failed/retryable with the API error. Do not create a success receipt.

### YouTube accepts upload but process dies before local state update

On restart, reconcile using the receipt or other durable upload evidence. Do not blindly upload again.

### Receipt exists but queue says `ready_to_upload`

Receipt wins. Reconcile the queue/job to `published` after validating the receipt.

### Metadata generation fails

Do not upload a render with placeholder or empty metadata. Leave the render intact and fail the metadata/publishing stage.

## Scheduling direction

The intended long-term controller on `compute-02` should decide **when** completed clips publish, while worker nodes focus on producing them.

The scheduler should eventually support:

- minimum spacing between uploads;
- daily publication caps;
- timezone-aware posting windows;
- backlog management;
- priority overrides;
- paused publishing without stopping production;
- retry backoff after platform/API failures.

## Audit trail

For every published clip, Osho should be able to answer:

```text
Which source produced this video?
Which transcript was used?
Which ranker/pipeline version selected it?
What timestamps were rendered?
Which worker rendered it?
What metadata was submitted?
When was it uploaded?
What YouTube video ID was returned?
```

That traceability is essential for debugging automation and improving content selection using real performance data.
