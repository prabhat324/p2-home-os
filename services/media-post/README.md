# BeSquare by pSquare — automated post-production

This package turns a master video, verified captions, approved source images, and optional brand assets into a review-ready editorial package on `compute-01`.

## Safety and editorial rules

- Neutral, independent election-series framing.
- Every factual visual is labelled `CONFIRMED`, `PROPOSED`, or `QUESTION`.
- Source name and date remain visible on document/headline cards.
- No unlicensed news video is downloaded or republished.
- Generic illustrative footage must be labelled as such.
- Nothing is published automatically. Output is a review proxy plus an edit manifest.

## Input layout on compute-01

```text
/srv/media-production/inbox/wasaga-report-2026/
  master.mp4
  captions.srt
  brand/logo.png                 # optional
  sources/                       # approved screenshots/photos
```

## Run

```bash
python3 pipeline.py \
  --project project.json \
  --master /srv/media-production/inbox/wasaga-report-2026/master.mp4 \
  --captions /srv/media-production/inbox/wasaga-report-2026/captions.srt \
  --output /srv/media-production/output/wasaga-report-2026
```

The first pass creates transparent motion overlays, headline/document cards, a timeline CSV, a provenance report, and—when a master is present—a watermarked review render. Missing approved source images produce placeholders, never silent substitutions.

