# Project Osho Pipeline

## Purpose

Project Osho converts authorized long-form media into short vertical clips and prepares those clips for automated publishing. The pipeline is designed to be inspectable, restartable, and increasingly autonomous.

## Source identity

Source items use stable zero-padded IDs such as:

```text
000001
000008
000009
000011
```

Those IDs should be carried through transcripts, work directories, candidate results, renders, metadata, logs, and publishing receipts. A stable source ID makes retries and duplicate detection practical.

## Processing stages

### 1. Source discovery

The pipeline identifies source media that has not yet completed the production/publishing lifecycle.

Checks should include:

- source exists and is readable;
- source ID is valid;
- source is authorized for processing and publishing;
- a successful publishing receipt does not already exist;
- no conflicting active job owns the same source.

### 2. Transcript lookup and reuse

Before running transcription, Osho checks for an existing transcript artifact.

Preferred behavior:

1. Use an existing valid transcript.
2. Only transcribe if the transcript is missing, corrupt, or known to be stale.
3. Preserve word/segment timestamps needed by downstream clip extraction.

This stage saves significant GPU/CPU time and allows ranking experiments to be rerun without repeating speech recognition.

### 3. Transcript generation

When required, generate a timestamped transcript using the configured transcription stack.

The output should contain enough temporal resolution for downstream candidate windows to be converted into exact video cuts.

### 4. Candidate extraction

The transcript is scanned for possible short-form moments. Candidate windows should be long enough to form a complete thought but short enough for the target platform.

The current V5 ranking invocation has been observed with:

```bash
hook_ranker_v5.py 000011 \
  --min-seconds 25 \
  --max-seconds 55 \
  --anchor-global 24 \
  --anchor-survivors 12 \
  --top 6
```

This reflects a target candidate duration of roughly **25–55 seconds**.

## Hook ranking V5

`hook_ranker_v5.py` is the principal candidate-ranking stage in the current zero-touch pipeline.

The ranking process narrows a larger candidate set into a small number of high-potential clips for further QA.

Observed configuration concepts:

- `--min-seconds 25` — reject clips that are too short to deliver sufficient context.
- `--max-seconds 55` — keep output within a strong short-form duration range.
- `--anchor-global 24` — build a broader initial anchor/candidate pool.
- `--anchor-survivors 12` — retain the stronger half for deeper evaluation.
- `--top 6` — return a small final set for downstream QA.

These values are tuning parameters, not permanent invariants. Changes should be recorded in the changelog or experiment notes because they directly affect creative selection.

## Safe candidate gating

The autopilot can reject an entire source when the ranking/QA stages do not find a suitable clip.

Observed production log behavior:

```text
000008 NO SAFE V5 CANDIDATES
000008 0 GENUINE APPROVALS — SKIPPED
```

This is correct behavior. A zero-touch system must prefer **skipping** a weak or unsafe source over publishing a questionable clip merely to keep throughput high.

## Retention QA

After ranking, candidate clips pass retention-oriented QA.

The QA layer should evaluate at least:

- strength of the first seconds;
- whether the clip begins intelligibly without missing context;
- whether the central idea develops quickly enough;
- whether the ending feels complete rather than arbitrarily cut;
- excessive pauses or dead air;
- duplicate/redundant content;
- obvious transcript/timecode errors;
- policy/safety constraints appropriate to the publishing account.

A candidate is not a publishable clip merely because it scored well in ranking.

## Genuine approvals

The autopilot differentiates generated candidates from genuine approvals. Only candidates that survive the required gates should proceed.

If zero genuine approvals remain, the source is skipped rather than forcing an output.

## Rendering

Approved candidates are rendered into vertical short-form output.

Target presentation:

```text
1080 × 1920
9:16 vertical
```

The render stage may include:

- exact source trim using transcript-derived timecodes;
- crop/reframe for vertical presentation;
- subtitle/caption burn-in where enabled;
- loudness/audio normalization;
- intro/outro-free presentation suitable for Shorts;
- encode settings compatible with YouTube upload.

Render output must be validated before metadata/publishing stages treat it as ready.

## Metadata generation

For each completed clip, generate structured publishing metadata such as:

- title;
- description;
- hashtags/tags;
- source ID;
- source start/end timestamps;
- pipeline/ranker version;
- render filename;
- any QA/ranking scores required for later analysis.

Metadata should be stored beside the durable job/output artifacts, not only kept in process memory.

## Ready-to-upload state

The dashboard has exposed jobs with states similar to:

```text
status: ready_to_upload
stage: ready_to_upload
progress: 100.0
```

This state means production work is complete, but publishing is not yet proven. A job should only transition to a published/uploaded state after the publisher records a successful platform response.

## Publishing and reconciliation

The autopilot includes reconciliation logic for previously uploaded content.

Observed log behavior:

```text
000009 RECONCILED AS PUBLISHED: LAbpetJoUKo
```

Reconciliation is important when:

- an upload succeeded but the process died before updating local job state;
- the controller restarts;
- receipt files exist but queue metadata is stale;
- a source is encountered again during recovery.

The system should always prefer reconciling from durable evidence over re-uploading.

## Skip vs fail

These states must remain distinct:

### Skipped

The system intentionally chose not to publish the source, for example:

- no safe candidates;
- zero genuine approvals;
- duplicate content;
- content fails QA.

### Failed

The system intended to continue but encountered an error, for example:

- source unreadable;
- transcription crashed;
- renderer failed;
- worker disappeared;
- upload API failed unexpectedly.

A skipped item usually should **not** be blindly retried. A failed item often should be retryable after the underlying problem is corrected.

## Idempotency requirements

Every stage should be safe to restart where possible.

Before doing expensive/destructive work:

- check whether the stage artifact already exists and is valid;
- never overwrite a successful upload receipt casually;
- use atomic writes or temporary files for important JSON/state files;
- prevent two workers from claiming the same source concurrently;
- reconcile successful prior work after restarts.

## Versioning experiments

Ranking and QA logic are expected to evolve. Keep version identifiers in filenames, metadata, or logs (for example `V5`) so output quality can be traced back to the code/tuning that produced it.

A future experiment record should capture:

```text
source_id
pipeline_version
ranker_version
model
ranker_parameters
selected_start
selected_end
scores
qa_result
published_video_id
```

That dataset will make it possible to improve Osho using actual publishing/retention results instead of intuition alone.
