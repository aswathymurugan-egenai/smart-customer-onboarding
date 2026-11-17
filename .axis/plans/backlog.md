# Backlog

The single work index for this repository. Position is grouping and the marker is status: `[ ]` open, `[~]` active, `[x]` done, `[–]` dropped. Append a new entry to the section it fits; never move, rewrite, or re-sort existing entries.

## Customer onboarding

- [~] **Customer registration API** ([plan](customer-registration-api.md)): a FastAPI service, a Next.js signup form, and an ADK assistant that register customers in BigQuery. Deterministic checks return 201, 409, or 422, and Gemini adds only typo and likely-duplicate warnings.
  It gives people clear signup errors and gives reporting a deduplicated customer table. Offline steps built; the live platform check is blocked until a dev GCP project is available, Gemini 2.5's retirement needs a model decision, and eight questions are open.
