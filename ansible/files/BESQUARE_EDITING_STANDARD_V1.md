# BeSquare Editing Standard V1

## Purpose

This is the production standard for BeSquare by pSquare knowledge-led videos: explainers, researched reports, issue breakdowns, civic/election explainers, business/technology explainers, and similar authored videos. The Wasaga Report 2026 V6.1 master is the gold reference for overall editorial feel.

This standard does **not** force V6.1 pacing onto podcasts or candidate interviews. Podcast mode retains its own speaker/caption and completeness rules.

## Gold reference

Canonical media-01 path:

`/srv/media-production/standards/besquare-knowledge-v1/reference/wasaga-report-2026-V6.1-youtube-master.mp4`

Expected SHA-256:

`c7ab41d20af7c760f4e9f13a4b955bb4f78775d202827ca22aea6bbf1366a860`

The reference is accompanied by the V6/V6.1 camera plan, easing commands, timeline, captions, render scripts, QC stills, QC metrics, logs, and the V6 YouTube-ready rubric. Those support files are part of the benchmark and should be consulted when a numeric rule does not fully describe the desired feel.

## Non-negotiable editorial guardrails

1. Source media is read-only. Never destructively edit or replace the source.
2. No cropped faces, cropped source text, accidental edge crops, or reframing that compromises the subject.
3. No abrupt zooms. Camera motion must be slow, eased, motivated by the spoken idea, and visually comfortable. V6.1 camera motion is the reference.
4. No repeated spoken or visual segments unless the repetition is an intentional, documented treatment.
5. No meaningless/decorative charts. A graph must explain a specific claim, comparison, trend, allocation, or trade-off that exists in the narration.
6. Factual visualizations require a source/context label and traceable evidence.
7. Do not cover faces or essential source material with graphics or captions.
8. Captions stay in the bottom safe area, are readable, and use at most two lines. Protected names/terms must be spell-checked.
9. Visual changes should follow the spoken idea. Avoid effect spam and generic B-roll simply to create movement.
10. Prefer fewer, high-value visual interventions over many weak overlays.
11. Every final render passes technical QA, creative QA, and manual review before publication.
12. Political/civic material must remain fact-based and politically neutral in presentation.

## Pacing and visual language

The default refresh target is around 25 seconds and uninterrupted talking-head stretches should normally remain under 35 seconds, but these are editorial guides rather than a command to add arbitrary visuals. A strong uninterrupted section is preferable to an irrelevant animation.

Use slow push-ins, reframing, sourced images/documents, maps, evidence cards, meaningful diagrams and charts, and occasional full-frame visual explainers. Avoid frequent hard zooms, rapid corner zooms, excessive flying panels, repetitive stat cards, or graphics that feel detached from the narration.

## Graph and data rules

A chart must answer a question the viewer is currently hearing. Every number must have context. Never show bars/lines simply because numbers were mentioned. Label units clearly, identify the source when appropriate, use comparable scales honestly, and keep the visual on screen long enough to understand.

## OpenMontage production policy

OpenMontage is **not the primary editor** for BeSquare production videos.

Its approved role is **asset-only**. It may generate standalone graphics, charts, diagrams, lower thirds, title treatments, source cards, short animations, transition elements, and other visual components that are later reviewed and inserted by the main BeSquare editing pipeline.

OpenMontage must never:

- replace the primary editorial timeline;
- render or overwrite the production master;
- determine the full-video pacing;
- modify source media;
- apply global production captions;
- automatically insert generated assets into the final video without BeSquare guardrail review.

OpenMontage asset requests live at:

`/srv/media-production/inbox/<job>/openmontage-assets.json`

Generated assets live only under:

`/srv/media-production/work/<job>/openmontage-assets/`

and review previews under:

`/srv/media-production/review/<job>/openmontage-assets/`

The main editor chooses if, where, and how an approved OpenMontage asset is used.

## Benchmark precedence

Automated thresholds are safety rails, not a substitute for editorial judgment. If a new knowledge video technically passes a heuristic but feels materially worse than the V6.1 reference in pacing, camera movement, clarity, graphic usefulness, or polish, it is not publish-ready.
