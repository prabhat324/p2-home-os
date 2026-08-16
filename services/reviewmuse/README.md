# Project ReviewMuse

**Turn real experiences into reviews worth reading.**

ReviewMuse is a locally hosted B2B review-writing assistant. A business shares a ReviewMuse link with a customer. The customer can write independently or answer a short, neutral experience questionnaire. Local AI converts only the supplied experience into an editable draft. The customer approves the wording, copies it, and continues to the business's official Google review page to post it themselves.

## Product principles

- Honest sentiment is preserved at every rating.
- No review gating: negative, mixed, and positive customers receive the same Google handoff.
- AI must not invent names, products, events, prices, wait times, or other facts.
- Nothing is posted to Google automatically.
- AI generation runs through the local Ollama service on compute-04.
- Basic funnel events are stored locally in SQLite at `data/reviewmuse.db`.

## V1 routes

- `/` — B2B landing page
- `/r/demo` — customer review assistant demo
- `/health` — service health
- `/api/generate` — local review drafting
- `/api/event` — local funnel event logging

## Runtime

The application is deployed to compute-04 under `/srv/compose/reviewmuse` and listens on port `8794` using host networking so it can reach the host-only Ollama endpoint.

Default model: `qwen3:4b`.
