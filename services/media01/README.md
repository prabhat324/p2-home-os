# media-01 4K production node

`media-01` is the automated rendering and quality-control node for BeSquare by pSquare. It produces review candidates; publication remains blocked until automated and manual gates pass.

## Production modes

Each `project.json` must declare a production mode:

- `podcast`: preserve the conversation essentially in full. Do not add cutaways by default. Generate speaker-aware captions using fixed left/right mouth-motion analysis. Speaker names, colors, font, outline, shadow and caption density are configured in `podcast_captions`.
- `explainer` (default): automatically build a creative timeline from the transcript/content report, verified facts and project-provided assets. Fill long talking-head gaps with restrained eased zooms. Sourced assets may be `image`, `document`, `newspaper`, or `broll`; sourced fact cards and graphs are supported. Creative QA rejects editorially empty timelines.

Example podcast manifest fragment:

```json
{
  "ready": true,
  "mode": "podcast",
  "podcast_captions": {
    "enabled": true,
    "left": {"name": "Guest", "color": "#7DFF95"},
    "right": {"name": "Host", "color": "#83D9FF"},
    "font_size": 78,
    "outline": 2.2,
    "shadow": 3.2,
    "words_per_caption": 12
  }
}
```

## Fresh-video readiness contract

A fresh job is not considered successfully processed merely because FFmpeg and technical QA pass. The worker must also produce a mode-appropriate creative plan and pass `creative_qa.py`.

For `podcast`, the required creative artifact is a two-speaker ASS caption track plus speaker assignments for both left and right speakers. For `explainer`, the required creative artifact is a non-empty timed visual plan whose density satisfies the generated creative policy. If either condition is missing, the job stops in `CREATIVE_REVIEW_REQUIRED` instead of being presented as a finished review candidate.

The system deliberately does not fabricate visual evidence. Newspaper clippings, documents, photos and B-roll are rendered automatically when listed in `visual_assets`, with source/license metadata. Numeric claims only become fact cards when a matching entry exists in `verified_sources`. Without those inputs, the planner uses restrained zooms rather than inventing supporting material.

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
- Return to the presenter between chapters; introduce useful B-roll or primary documents after roughly 20–30 seconds of uninterrupted talking head in explainer mode.

## Directory contract

Place each project in `/srv/media-production/inbox/<project>/` with a source video and a project manifest. Work products, review exports, approved output, archives, failures, logs, assets, and profiles remain in their corresponding directories under `/srv/media-production`.

The QA gate deliberately cannot approve editorial truth, taste, or political fairness by itself. It creates a machine report and a mandatory human checklist; both are required before an export is marked publish-ready. `creative_qa.py` is an additional mandatory gate: a technically valid but creatively empty render must not be promoted to final review.

## Per-project analysis products

For normal jobs the worker transcribes before rendering with `faster-whisper` and the `large-v3-turbo` model. It writes `transcript.txt`, `transcript.json`, `captions.srt`, and `content-report.json` beneath the project's review `analysis/` directory. Captions are limited to two lines and seven words per line. Probable duplicated spoken passages block the render for investigation; numbers, dates, currency, and percentages are flagged for source verification. The first run downloads the speech model and therefore takes longer. A CUDA initialization failure falls back to CPU inference rather than discarding the analysis.

Podcast mode additionally writes `speaker-captions.ass` and `speaker-assignments.json`. The caption engine samples the two visible faces and compares mouth-region motion during each transcript cue. The left and right speaker styles are independently configurable.

Explainer mode writes an automatically generated `timeline.auto.json`. Verified claims only become fact cards when a source is supplied in `verified_sources`; numeric claims are never promoted to graphics without provenance. Optional `visual_assets` specify project-provided images, documents, newspaper clippings or B-roll with timing and source/license metadata.

Model downloads and application caches are stored below `/srv/media-production/work/.cache`; the hardened worker does not write into the service account's home directory.
