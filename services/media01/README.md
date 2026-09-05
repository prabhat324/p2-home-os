# media-01 4K production node

`media-01` is the automated rendering and quality-control node for BeSquare by pSquare. It produces review candidates; publication remains blocked until automated and manual gates pass.

## Permanent editorial rules

- Preserve the complete frame unless a motivated crop has been reviewed. Never crop faces, captions, documents, or existing on-screen lettering.
- Captions stay low in the bottom safe area, use at most two lines, and never cover important content.
- Zooms are slow, eased, subtle, and motivated. Abrupt punch-ins are prohibited.
- Never place childish or physically implausible inserts between the presenter and the set/wall.
- Never use lines or decorative shapes as a graph. A graph must encode real labeled data and display its source.
- Detect and reject repeated footage or repeated spoken sections.
- Lists may use a restrained word-throw/question-mark treatment; effects must support comprehension.
- Financial graphics require source labels. Concepts and examples use the exact disclaimer text in the quality profile.
- Verify spelling, especially `Wasaga Beach`, and manually verify names, numbers, dates, quotations, and time-sensitive claims.
- Political content must remain neutral. Candidate interviews are published essentially in full and never edited as gotchas.
- Return to the presenter between chapters; introduce useful B-roll or primary documents after roughly 20–30 seconds of uninterrupted talking head.

## Directory contract

Place each project in `/srv/media-production/inbox/<project>/` with a source video and a project manifest. Work products, review exports, approved output, archives, failures, logs, assets, and profiles remain in their corresponding directories under `/srv/media-production`.

The QA gate deliberately cannot approve editorial truth, taste, or political fairness by itself. It creates a machine report and a mandatory human checklist; both are required before an export is marked publish-ready.

## Per-project analysis products

For normal jobs the worker transcribes before rendering with `faster-whisper` and the
`large-v3-turbo` model. It writes `transcript.txt`, `transcript.json`, `captions.srt`,
and `content-report.json` beneath the project's review `analysis/` directory. Captions
are limited to two lines and seven words per line. Probable duplicated spoken passages
block the render for investigation; numbers, dates, currency, and percentages are
flagged for source verification. The first run downloads the speech model and therefore
takes longer. A CUDA initialization failure falls back to CPU inference rather than
discarding the analysis.

Optional `project.json` fields are `language` (default `en`), `transcription_model`
(default `large-v3-turbo`), and `content_analysis` (default `true`). Acceptance-test
jobs skip transcription so hardware validation remains deterministic.
