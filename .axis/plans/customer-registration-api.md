# Plan: Customer registration API with rule-based outcomes and Gemini advice

**Slug:** `customer-registration-api` • **Created:** 2026-11-16 • **Git SHA:** none (`main` has no commits yet) • **Effort:** deep

This plan replaces the earlier plan under the same slug in full. None of its decisions carry forward: the inbox confirmation, the uniform 202 reply, the staff dashboard, the held and merge lifecycle, the policy-PDF corpus, the GPT exclusion, and IAP.

## Rationale

This plan was shaped through a `--grill` dialogue. Everything in this section is **user-provided** unless it carries another label.

- **Problem.** A public signup API and a conversational assistant that reject bad emails, block exact duplicates with 409, warn about likely duplicates, and write to BigQuery idempotently.
- **Who benefits.** People registering on the public form, and the team that reports on customers in BigQuery.

**Approaches considered**

| Criterion | A: rules decide, model advises (chosen) | B: the ADK agent decides | C: chat first, form as fallback |
| --- | --- | --- | --- |
| Who sets 201, 409, or 422 | Deterministic checks in code and the BigQuery transaction | The model, through tool calls | The model, through conversation |
| Model failure or timeout | The registration proceeds with no advisory | The registration fails or stalls | Onboarding stops |
| Same input twice | Same status | Can differ between runs | Can differ between runs |
| Offline testing | Unit and API tests with fakes | Model mocks for every outcome | Scripted conversations |
| Contract | Fixed OpenAPI operations with fixed outcomes | Fixed operations with model-chosen outcomes | No predictable contract |

- **Recommendation.** Approach A. Syntax, the disposable-domain list, the MX lookup, and an exact email, phone, or tax-ID match inside the BigQuery transaction decide 201, 409, or 422. Gemini only produces typo suggestions and likely-duplicate warnings. Those attach to a 201 or appear in the validate and check-duplicate responses, and the assistant panel explains them. Approach B lost because model mistakes would reach customers and outcomes would differ between runs. Approach C lost because it has no predictable contract and is the hardest to test offline.
- **Key tradeoff.** The status codes follow the brief: 201 Created, 409 Conflict on an exact duplicate, and 422 on an invalid or disposable email. The form can show the exact problem at once. The cost is that anyone can ask the API whether an email is registered, and the user accepted that explicitly. Per-client rate limits and a bot check slow probing down and do not stop it. **Derived:** phone numbers and tax IDs carry the same exposure, because both are exact-match keys on register and check-duplicate. Risks lists this.
- **Decided during shaping.**
  - No inbox confirmation. A customer exists as soon as the register call succeeds, and the `AGENTS.md` Overview is rewritten to say so.
  - Gemini 2.5 Flash and Pro through `google-genai` and ADK. The LiteLLM GPT-4o fallback is in scope as an option.
  - Next.js 15, React 19, TypeScript, Tailwind CSS v4, shadcn/ui, and Lucide icons. One neutral palette with one accent color, light and dark themes through CSS tokens, and the form alignment rules under Frontend.
  - The brief's two endpoint lists become one contract, stated under API contract.

**Open questions.** The first four came out of shaping. The rest are **derived** from evidence found while planning.

1. **Disposable list source.** Which source feeds the disposable-domain list? The plan vendors a copy of a public list and refreshes it by script.
2. **Tax-ID formats.** Which government and tax-ID formats are validated, and does reporting need the raw value? The plan validates four types and stores a keyed hash plus the last four characters.
3. **Address collection.** Is a postal address collected? The plan collects an optional address, because likely-duplicate matching uses it.
4. **Abuse providers.** Which providers serve rate limiting and the bot check? The plan ships a per-instance limiter and a stub verifier that only local configuration can load.
5. **Gemini model.** Which Gemini model ids to pin? Google has deprecated Gemini 2.5 Flash and Pro (see Evidence status). Can the dev project still call them, and if not, which successor?
6. **Next.js major.** Next.js 15 as briefed, or Next.js 16? Next.js 15 is in maintenance support, with security releases through 2027-01-31. The plan recommends 16 if the brief allows it.
7. **Fallback data.** May a registrant's chat messages and form values go to OpenAI when the GPT-4o fallback is on? The plan ships the fallback switched off.
8. **Audit retention.** How long are audit rows kept? The audit table needs a partition expiration.

## Objective

A person fills in the Next.js form and gets one of three answers. A 201 carries any typo or likely-duplicate warnings. A 409 names which of email, phone, or tax ID already belongs to a customer. A 422 puts the error under the field it concerns. The assistant panel beside the form explains these results and can register the person after an explicit confirmation click. Concurrent registrations never leave two customers sharing an email, phone, or tax ID in `customer_ops.customers`. The work produces the demo outputs listed at the top of Steps, and the offline test suite passes with no GCP credentials.

## Context

**Repository state (observed).** `main` has no commits. The tree holds AXIS scaffolding (`AGENTS.md`, `CLAUDE.md`, `axis.json`, `.gitignore`, `.axis/`, `.claude/`) and four PDFs in `files/`, which this plan leaves alone. No application code, tests, or CI exist, so every path in Steps is new except `.gitignore`, `AGENTS.md`, and the backlog. `axis.json` protects `main`, so the work happens on a feature branch such as `feat/customer-registration-api`.

**Files involved:** `.gitignore:15` (append after the AXIS-managed block), `AGENTS.md:5-8` (the Overview paragraph), `.axis/plans/backlog.md:7-8`, and the new tree under Target layout.

**Evidence status.** Checked on 2026-11-16 against public docs and package registries.

| Claim the design rests on | Status | Source |
| --- | --- | --- |
| On the Gemini API, `gemini-2.5-flash` and `gemini-2.5-pro` are deprecated, access is limited to existing users, and from 2026-12-01 requests route to `gemini-3.5-flash-lite` and `gemini-3.8-flash` | VERIFIED | Gemini API deprecations page and changelog |
| Vertex AI lists both 2.5 models for retirement on 2026-10-20, a date already past | VERIFIED (the listing); **UNVERIFIED** (whether the endpoints still answer) | Vertex AI model versions page |
| A BigQuery multi-statement transaction that mutates a table takes a table-level lock. One mutating transaction runs per table, conflicting transactions are not queued, and the loser fails at once with "Transaction is aborted due to concurrent update against table". Google advises waiting at least 60 seconds before retrying. | VERIFIED | BigQuery transactions docs |
| Opening a transaction with `DELETE FROM <table> WHERE FALSE` makes every other transaction that mutates the table conflict and abort | VERIFIED | BigQuery transactions docs |
| A `MERGE` that only inserts does not conflict with concurrent DML, and matching uses the table state at statement start | VERIFIED | BigQuery DML docs |
| Two concurrent insert-only `MERGE` statements can therefore both insert the same email | **Derived** from the row above and unenforced keys; the platform check proves it | — |
| Key constraints exist only as `NOT ENFORCED` | VERIFIED | BigQuery primary and foreign keys docs |
| Rows written through streaming (`insertAll` or the REST Storage Write API) cannot be changed by DML for 30 minutes, and mutating DML inside a transaction against recently streamed rows is unsupported | VERIFIED | BigQuery DML and Write API docs |
| Named parameters use `@name`. Parameters cannot replace table names, and a parameter value cannot be NULL. | VERIFIED | BigQuery parameterized queries docs |
| A table takes up to four clustering columns, clustering combines with partitioning, and a TIMESTAMP column partitions daily | VERIFIED | BigQuery clustering and partitioning docs |
| `PARTITION BY DATE(created_at)` is accepted for a TIMESTAMP column | **UNVERIFIED** this session; the fetched pages show column partitioning only, and the platform check runs the DDL | BigQuery DDL reference (not fetched) |
| `google-adk` 2.14.1 (2026-11-12) requires Python 3.11 or later, has a `gcp` extra (BigQuery, Storage, Secret Manager, Agent Platform, OpenTelemetry exporters), pins `google-genai<3`, and brings `litellm>=1.84,<1.106.3` only through its `extensions`, `all`, and `test` extras | VERIFIED | PyPI |
| ADK `LlmAgent` accepts `output_schema` together with `tools` in Python, and the schema applies to the final response. Function tools take their schema from type hints and the docstring. `ToolContext` is injected by type annotation and hidden from the model. `Runner(agent=, app_name=, session_service=)` works with `InMemorySessionService` and `run_async(user_id=, session_id=, new_message=)`. `LiteLlm(model="openai/gpt-4o")` wraps GPT-4o. Model and tool callbacks exist. | VERIFIED | adk.dev |
| ADK documents no model fallback chain | VERIFIED (absent from the LiteLLM page) | adk.dev |
| LiteLLM 1.82.7 and 1.82.8 on PyPI contained unauthorized code | VERIFIED | adk.dev LiteLLM page |
| `BigQueryToolset` lives at `google.adk.tools.bigquery` | VERIFIED (class path); **UNVERIFIED** (whether `execute_sql` takes query parameters, and the `WriteMode` values) | adk.dev API reference |
| Per-turn session state through `Runner.run_async(..., state_delta=...)`, and the `Event.is_final_response()` shape | **UNVERIFIED** | Not covered by the fetched pages |
| The environment variable that points `google-genai` and ADK at Vertex AI: the current `google-genai` README names `GOOGLE_GENAI_USE_ENTERPRISE`; ADK's own handling is unknown | **UNVERIFIED** | google-genai README |
| Next.js 16 is Active LTS. Next.js 15 is Maintenance LTS with security releases through 2027-01-31, and it requires React 19. | VERIFIED | nextjs.org support policy and upgrade guide |
| shadcn/ui builds forms from the `Field` family (`Field`, `FieldLabel`, `FieldDescription`, `FieldError`, `FieldGroup`, `FieldSet`, `FieldLegend`, `FieldSeparator`) with react-hook-form `Controller` and `zodResolver`. Theme tokens sit under `:root` and `.dark`, and dark mode uses `next-themes` with `attribute="class"`. | VERIFIED | ui.shadcn.com |
| Tailwind CSS v4 on Next.js uses `@tailwindcss/postcss` and `@import "tailwindcss";` | VERIFIED | tailwindcss.com |
| Latest versions: fastapi 0.163.1, pydantic 2.14.3, google-cloud-bigquery 3.47.0, email-validator 2.4.0, dnspython 2.9.2, rapidfuzz 3.14.6, pytest-asyncio 1.5.0; react 19.3.1, lucide-react 1.73.0, shadcn 4.23.0, zod 4.6.7, react-hook-form 7.92.0, @tanstack/react-query 5.107.1, vitest 5.1.0, @playwright/test 1.65.1, openapi-typescript 7.13.0 | VERIFIED | PyPI, npm registry |
| The latest `next` 15.x, `tailwindcss`, and `typescript` versions, and the `phonenumbers`, `structlog`, `pydantic-settings`, `openapi-fetch`, and `@stoplight/spectral-cli` versions | **UNVERIFIED** (registry documents too large to fetch, or not checked) | Pinned at scaffold |

**Constraints**

- Only deterministic code sets 201, 409, or 422. A model failure, timeout, or invalid output removes the advisory and never changes the status.
- No model call receives a tax ID or a full phone number. Typo advice sends the email domain only.
- The public API never returns another customer's data. A 409 names the matched fields, and a likely-duplicate warning carries a confidence and reason codes.
- Customer rows are written only by DML query jobs, never by streaming inserts, so the transaction lock covers every write.
- Every request value reaches BigQuery as a query parameter. Project and dataset names come from validated configuration, because parameters cannot name tables.
- Layering follows the app-backend playbook. `app/domain` imports neither FastAPI nor the BigQuery client, each route calls one service method, and the service owns the transaction.
- Names, emails, phone numbers, tax IDs, addresses, client IPs, and chat text never appear in logs, metric labels, or error bodies.

**Assumptions to confirm (derived)**

- The dataset is `customer_ops` and the table is `customers`. The brief's "`customers` dataset" is read as the table inside `customer_ops`.
- An exact phone match blocks registration, because the brief lists phone among the exact-match keys. People sharing a household or office number are then refused; see Risks.
- Customers are individuals or businesses. A business adds a company name, which feeds corporate-alias matching.
- Gemini runs on Vertex AI in the same project as BigQuery, in a region inside the dataset's location.

**Dependencies (infrastructure outside this repository)**

| Resource | Requirement |
| --- | --- |
| One GCP project per environment | BigQuery dataset `customer_ops`, the Vertex AI API enabled, and Secret Manager |
| Service account `registration-api` | `roles/bigquery.dataEditor` on the `customer_ops` dataset only, `roles/bigquery.jobUser` on the project, `roles/aiplatform.user` on the project, and `roles/secretmanager.secretAccessor` on its own secrets. The default compute account is never attached. |
| Service account `registration-ui` | No data roles |
| Secrets | `pii-hash-key` (the HMAC key for tax-ID, email, and client hashes), the bot-check secret once a provider is chosen, and the OpenAI key only when the fallback is on |
| Platform-check access | A person or CI identity in the dev project with the API's grants plus create and delete on scratch datasets |

## Approach

**Chosen:** One FastAPI service holds three deterministic services (email validation, duplicate detection, registration), an advisor that makes single structured Gemini calls through `google-genai`, and an ADK `LlmAgent` assistant with three function tools. The register route runs the email rules, then the advisor within a 4-second budget, then one BigQuery multi-statement transaction. The transaction opens with `DELETE FROM customers WHERE FALSE` to take the table lock, checks the idempotency key, and runs the parameterized `MERGE`. The `MERGE` inserts the customer only when no row shares the email, phone, or tax-ID hash. A transaction that loses the lock race aborts at once, and the service retries it with jittered backoff before answering 503. A Next.js 15 page shows the form and the assistant panel side by side and calls the API directly, with CORS limited to configured origins.

**Alternatives considered:**

- **A bare `MERGE` for uniqueness, as the brief sketches.** An insert-only `MERGE` does not conflict with a concurrent one, and each sees the table as it was when it started. Two concurrent registrations of one email can then both insert. The lock statement ahead of the `MERGE` closes that gap.
- **ADK `BigQueryToolset`.** Its `execute_sql` tool runs SQL the model writes, which is the catch-all tool the agentic-development playbook bans, and this session could not confirm that it accepts query parameters. Custom tools call the same service methods as the REST routes.
- **Every model call through ADK.** Typo advice and fuzzy adjudication are one prompt and one structured output each. The agentic-development playbook says to skip the agent loop for that shape of task, so the advisor calls `google-genai` directly and ADK runs only the conversational assistant.
- **A Next.js proxy route in front of the API.** It would remove the need for CORS. It would also hide the client IP that rate limiting needs and add a network hop. Direct calls with an origin allow-list keep the brief's CORS middleware doing real work.

**Reasoning:**

- The register path depends on nothing a model produces. The offline suite covers every status with fakes, and Gemini's deprecation affects only advice.
- BigQuery's documented lock idiom gives exact-key uniqueness without a second datastore. At signup traffic, one registration at a time per table costs little.
- The data-mastering playbook's order applies to likely duplicates: normalize first, match exact keys deterministically, block before comparing, and score only the remainder. Rapidfuzz scores the blocked candidates, and the model sees at most five of them under opaque references.
- The register tool takes no customer fields from the model. It reads the form snapshot the API stored in session state, and only after the user clicks Confirm, so a hallucinated or injected tool call cannot register invented data.

**Left unbuilt:**

| Design set aside | What would make it worth building |
| --- | --- |
| A transactional store (Firestore, Spanner, or Cloud SQL) that owns the uniqueness claim, with BigQuery fed from it | Lock conflicts exceed 1% of registrations, or register p95 passes 8 seconds |
| A calibrated record-linkage model (Splink) in place of the rapidfuzz pre-score and Gemini's self-reported confidence | A few hundred labeled duplicate pairs exist for a stratified hold-out set |
| A staff review queue for likely duplicates | Likely-duplicate warnings pile up unresolved in the audit table |
| Shared storage for assistant sessions and rate limits (an ADK database session service, Memorystore) | The API runs more than one instance and conversations or limits must hold across them |
| An advisory cache keyed by request fingerprint | Callers routinely run check-duplicate and then register on the same data |
| An ADK evalset that gates prompt and model changes | Before production, or before the model id changes |
| A read-only `BigQueryToolset` analyst agent for the reporting team | Reporting asks for natural-language queries over customers |
| Matching across several HMAC key versions | The PII hash key has to rotate |

### Target layout

```
smart-customer-onboarding/
├── pyproject.toml, uv.lock, .python-version     uv project; ruff, mypy, pytest config
├── .env.example, Makefile, README.md
├── Dockerfile, docker-compose.yml               API image; local api + ui
├── .spectral.yaml
├── .github/workflows/ci.yml
├── contracts/openapi.yaml                       OpenAPI 3.1, generated and committed
├── sql/
│   ├── 001_customer_ops_schema.sql              CREATE SCHEMA and both tables
│   ├── register_customer.sql                    the transaction with the MERGE
│   ├── find_exact_matches.sql
│   ├── find_fuzzy_candidates.sql
│   ├── insert_audit_event.sql
│   └── checks/duplicate_keys.sql                must return zero rows
├── scripts/  apply_schema.py, export_openapi.py, refresh_disposable_domains.py
├── app/
│   ├── main.py                                  create_app(), lifespan, CORS, middleware
│   ├── config.py, logging.py
│   ├── api/       routes_customers.py, routes_agent.py, problems.py, dependencies.py, health.py
│   ├── models/    schemas.py                    Pydantic v2 wire models
│   ├── domain/    normalize.py, email_rules.py, matching.py, errors.py
│   ├── services/  ports.py, bq_repository.py, memory_repository.py, email_validation.py,
│   │              dns_mx.py, advisor.py, duplicate_detection.py, registration.py,
│   │              rate_limit.py, bot_check.py, pii.py
│   ├── agents/    registration_agent.py         LlmAgent, three tools, Runner wrapper
│   └── data/      disposable_domains.txt, free_mail_domains.txt
├── tests/
│   ├── conftest.py, fakes.py
│   ├── test_registration.py                     the API suite named in the brief
│   ├── test_contract.py
│   ├── unit/                                    domain, SQL templates, repository, advisor, agent tools
│   └── integration/                             platform check; needs a GCP project
├── ui/                                          Next.js 15 app
│   ├── package.json, package-lock.json, next.config.ts, postcss.config.mjs,
│   │   tsconfig.json, components.json, Dockerfile
│   ├── app/       layout.tsx, page.tsx, globals.css
│   ├── components/ui/                           shadcn components
│   ├── components/  theme-provider.tsx, theme-toggle.tsx
│   ├── features/registration/                   form, field groups, schema, result card
│   ├── features/assistant/                      panel, drawer, message list, confirm dialog
│   ├── lib/       api.ts, api-schema.d.ts (generated), runtime-config.tsx
│   └── tests/     unit (Vitest), e2e (Playwright)
└── docs/code-review-report.md
```

### API contract

One contract reconciles the brief's two endpoint lists. Register, validate, and check-duplicate are kept. The assistant takes `POST /api/v1/agent/chat`, and `agent/onboard` is dropped: under approach A the assistant explains and asks for confirmation, and the register route does the onboarding.

Every error body is RFC 9457 `application/problem+json` with `type` (`urn:smart-customer-onboarding:problem:<name>`), `title`, `status`, `detail`, `instance`, `request_id`, and `errors[]` (JSON pointer, code, message). Every response echoes `X-Request-Id`. Every operation documents 500 with a generic body.

| Operation | Statuses | Behavior |
| --- | --- | --- |
| `POST /api/v1/customers/register` | 201, 403, 409, 422, 429, 500, 503 | Body `CustomerInput`, optional `Idempotency-Key` header (UUID). 201 returns `RegistrationCreated`. 409 `customer-duplicate` carries `matched_on` (`email`, `phone`, `tax_id`). 422 is one of `email-invalid`, `email-disposable`, `email-domain-undeliverable`, `phone-invalid`, `tax-id-invalid`, `validation-error`, or `idempotency-key-reused`. 403 `bot-check-failed`. 429 `rate-limited` with `Retry-After`. 503 `registration-busy` with `Retry-After`. |
| `POST /api/v1/customers/validate` | 200, 422, 429, 500 | Body `{email}`. 200 carries the verdict, an invalid email included, because the validation result is the resource. 422 only for a malformed body. |
| `POST /api/v1/customers/check-duplicate` | 200, 403, 422, 429, 500 | Body `CustomerInput`; writes no customer. 200 returns `DuplicateCheckResult` with `exact_matches` and `possible_duplicate`. A found match is a successful check, so the status stays 200. |
| `POST /api/v1/agent/chat` | 200, 422, 429, 500, 503 | Body `ChatRequest`. 200 returns `AssistantReply`. 503 `assistant-unavailable` when the model fails and no fallback answers. |

- **201 without `Location`.** The app-api playbook pairs 201 with `Location`. This API has no customer read endpoint, because one would expose personal data with no sign-in. The 201 body carries `customer_id`, and the operation description records the deviation.
- **Probes.** Liveness at `/healthz/live` and readiness at `/healthz/ready`, excluded from the published spec.

**Wire models (`app/models/schemas.py`).** Every model sets `extra="forbid"`. Every field has a `description`, and every model has examples with fictional values only (`@example.test` addresses, 555-01xx numbers).

| Model | Fields |
| --- | --- |
| `AddressInput` | `line1` (1–200), `line2` (up to 200, optional), `city` (1–100), `region` (up to 100, optional), `postal_code` (up to 20, optional), `country_code` (ISO 3166-1 alpha-2) |
| `CustomerInput` | `customer_type` (`individual` or `business`, default `individual`), `given_name` (1–100), `family_name` (up to 100, optional), `company_name` (1–200, required for `business`), `email` (3–254), `phone` (up to 32, optional), `tax_id_type` (`us_ein`, `gb_vat`, `in_pan`, or `other`; optional), `tax_id` (up to 40, required with a type), `address` (optional), `bot_token` (up to 2048) |
| `TypoWarning` | `code="possible_typo"`, `message`, `suggested_email`, `source` (`rules` or `model`) |
| `DuplicateWarning` | `code="possible_duplicate"`, `message`, `confidence` (0–1), `reasons` (up to three of `name_variant`, `nickname`, `swapped_name_order`, `corporate_alias`, `address_variant`, `shared_business_domain`) |
| `RegistrationCreated` | `customer_id`, `status="created"`, `email` (canonical), `warnings` (a list of the two warning types), `advisory_status` (`ok`, `unavailable`, or `disabled`) |
| `EmailValidationResult` | `email_as_entered`, `normalized_email` (null when syntax fails), `is_valid`, `checks` (`syntax`, `disposable`, `mx`, each `pass`, `fail`, `unknown`, or `skipped`), `problems` (code and message), `suggestion` (`TypoWarning` or null) |
| `DuplicateCheckResult` | `exact_matches` (a subset of `email`, `phone`, `tax_id`), `possible_duplicate` (`DuplicateWarning` or null), `advisory_status` |
| `CustomerDraft` | `CustomerInput` with every field optional and no `bot_token`; the form snapshot sent with a chat turn |
| `ChatRequest` | `session_id` (UUID), `message` (1–2000), `form_snapshot` (`CustomerDraft`, optional), `last_result` (the status code, problem type, and warnings the form last received; optional), `action` (`confirm_registration` or null) |
| `AssistantReply` | `session_id`, `message` (up to 4000), `suggested_actions` (`apply_email_suggestion`, `confirm_registration`, `review_field`), `registration` (status, `customer_id`, `matched_on`; copied by code from the tool result), `model`, `used_fallback` |
| `ProblemDetails` | The RFC 9457 fields above, plus `matched_on` and `suggestion` where they apply |

### Register flow

1. Pydantic validates the body. FastAPI's default validation handler is replaced, so a shape error returns 422 `validation-error` as problem+json.
2. The per-client limiter (429) and the bot verifier (403) run.
3. Normalization builds the canonical values. Email goes through email-validator syntax, lowercasing, and IDNA domain encoding. The phone becomes E.164 through `phonenumbers`, with the address country as the default region. The tax ID loses spaces and dashes, is uppercased, and must match its type's pattern. The name yields `normalized_name` and `name_key`, and the address yields `normalized_address`. Failures return 422.
4. Email rules run next. A domain on the disposable list returns 422 `email-disposable`. Then the async MX lookup runs with a 2-second budget. No MX and no A record returns 422 `email-domain-undeliverable`, and a timeout continues with `mx_status = unknown`.
5. Typo advice and likely-duplicate advice run concurrently under one 4-second budget. Any failure sets `advisory_status = unavailable` and drops that half's warnings.
6. The transaction script below runs in a worker thread, because the BigQuery client is synchronous. On the "concurrent update" abort the service retries up to three times with full-jitter backoff starting at 500 ms, within 10 seconds in total. After that it answers 503 `registration-busy` with `Retry-After: 60`, which follows Google's 60-second guidance.
7. The script's outcome maps to the response. `created` returns 201. `replay` returns 201 with the original `customer_id` and the header `Idempotent-Replayed: true`. `fingerprint_mismatch` returns 422 `idempotency-key-reused`. `duplicate` returns 409.
8. Every outcome other than `created` appends an audit row through a standalone parameterized `INSERT`. The `created` row is written inside the transaction.

### BigQuery schema (`sql/001_customer_ops_schema.sql`)

`scripts/apply_schema.py` substitutes `${project}`, `${dataset}`, and `${location}` from validated configuration. Every statement uses `IF NOT EXISTS`, so a second run changes nothing.

```sql
CREATE SCHEMA IF NOT EXISTS `${project}.${dataset}`
OPTIONS (
  location = '${location}',
  description = 'Customer onboarding: registered customers and the registration audit trail.',
  labels = [('owner', 'customer-onboarding'), ('data-classification', 'pii')]
);

CREATE TABLE IF NOT EXISTS `${project}.${dataset}.customers` (
  customer_id STRING NOT NULL OPTIONS (description = 'UUIDv7 generated by the API.'),
  customer_type STRING NOT NULL OPTIONS (description = 'individual or business.'),
  given_name STRING NOT NULL,
  family_name STRING OPTIONS (description = 'Null when the person gave one name.'),
  company_name STRING OPTIONS (description = 'Null for individuals.'),
  normalized_name STRING NOT NULL OPTIONS (description = 'Company name for businesses, full name otherwise; casefolded, accents and punctuation removed, legal suffixes removed.'),
  name_key STRING NOT NULL OPTIONS (description = 'Tokens of normalized_name sorted alphabetically; matches swapped name order.'),
  email STRING NOT NULL OPTIONS (description = 'Canonical address: trimmed, lowercased, IDNA domain. Unique across customers.'),
  email_as_entered STRING NOT NULL,
  email_local_part STRING NOT NULL,
  email_domain STRING NOT NULL,
  mx_status STRING NOT NULL OPTIONS (description = 'pass or unknown at registration time.'),
  phone_e164 STRING OPTIONS (description = 'E.164. Null when not given. Unique across customers.'),
  tax_id_type STRING OPTIONS (description = 'Null when no tax ID was given.'),
  tax_id_hash STRING OPTIONS (description = 'Hex HMAC-SHA256 of the normalized tax ID; the raw value is never stored. Unique across customers.'),
  tax_id_last4 STRING,
  hash_key_version STRING NOT NULL OPTIONS (description = 'Version of the HMAC key behind tax_id_hash.'),
  address STRUCT<
    line1 STRING, line2 STRING, city STRING, region STRING,
    postal_code STRING, country_code STRING
  > OPTIONS (description = 'Null when no address was given.'),
  normalized_address STRING,
  source_channel STRING NOT NULL OPTIONS (description = 'form, assistant, or api.'),
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  PRIMARY KEY (customer_id) NOT ENFORCED
)
PARTITION BY DATE(created_at)
CLUSTER BY email, normalized_name
OPTIONS (
  description = 'One row per registered customer. sql/register_customer.sql enforces email, phone, and tax-ID uniqueness; sql/checks/duplicate_keys.sql detects any breach.',
  labels = [('data-classification', 'pii')]
);

CREATE TABLE IF NOT EXISTS `${project}.${dataset}.registration_audit_logs` (
  event_id STRING NOT NULL,
  request_id STRING NOT NULL,
  idempotency_key STRING,
  request_fingerprint STRING OPTIONS (description = 'SHA-256 of the canonical request body.'),
  channel STRING NOT NULL OPTIONS (description = 'form, assistant, or api.'),
  operation STRING NOT NULL OPTIONS (description = 'register or check_duplicate.'),
  outcome STRING NOT NULL OPTIONS (description = 'created, replay, duplicate, invalid_email, invalid_input, rate_limited, bot_check_failed, busy, checked, or error.'),
  http_status INT64 NOT NULL,
  customer_id STRING OPTIONS (description = 'Set when outcome is created or replay.'),
  email_hash STRING OPTIONS (description = 'Hex HMAC-SHA256 of the canonical email; links attempts without storing the address. Null when the email failed syntax.'),
  client_hash STRING NOT NULL OPTIONS (description = 'Hex HMAC-SHA256 of the client IP; shows probing patterns without storing the address.'),
  matched_on ARRAY<STRING>,
  problem_codes ARRAY<STRING>,
  mx_status STRING,
  advisory_status STRING,
  typo_suggested_domain STRING,
  fuzzy_candidate_ids ARRAY<STRING> OPTIONS (description = 'Existing customers the model judged likely or possibly the same person or company.'),
  fuzzy_max_confidence FLOAT64,
  advisory_model STRING,
  lock_retries INT64 NOT NULL,
  latency_ms INT64 NOT NULL OPTIONS (description = 'Milliseconds from request start to the write.'),
  created_at TIMESTAMP NOT NULL,
  PRIMARY KEY (event_id) NOT ENFORCED
)
PARTITION BY DATE(created_at)
CLUSTER BY outcome, email_hash
OPTIONS (
  description = 'Append-only record of every register and check-duplicate call. Holds no raw email, phone, tax ID, or IP address.',
  labels = [('data-classification', 'pii-pseudonymous')]
);
```

- Neither table sets `require_partition_filter`. Email lookups span every partition, and clustering on `email` keeps them cheap.
- The audit table's partition expiration waits for the retention answer.

### Registration transaction (`sql/register_customer.sql`)

```sql
-- Registers one customer or reports why not. The opening DELETE takes the table lock for the
-- whole transaction, so a concurrent registration aborts and retries; an insert-only MERGE on
-- its own would let both insert. Optional values arrive as '' (or -1.0) because query
-- parameters cannot be NULL.
DECLARE replay STRUCT<customer_id STRING, request_fingerprint STRING> DEFAULT NULL;
DECLARE inserted INT64 DEFAULT 0;
DECLARE matched_on ARRAY<STRING> DEFAULT [];
DECLARE outcome STRING DEFAULT 'duplicate';

BEGIN TRANSACTION;

DELETE FROM `${project}.${dataset}.customers` WHERE FALSE;

SET replay = (
  SELECT AS STRUCT customer_id, request_fingerprint
  FROM `${project}.${dataset}.registration_audit_logs`
  WHERE @idempotency_key != ''
    AND idempotency_key = @idempotency_key
    AND outcome = 'created'
    AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  LIMIT 1
);

IF replay IS NOT NULL THEN
  SET outcome = IF(replay.request_fingerprint = @request_fingerprint, 'replay', 'fingerprint_mismatch');
  ROLLBACK TRANSACTION;
ELSE
  MERGE `${project}.${dataset}.customers` AS t
  USING (
    SELECT
      @customer_id AS customer_id,
      @customer_type AS customer_type,
      @given_name AS given_name,
      NULLIF(@family_name, '') AS family_name,
      NULLIF(@company_name, '') AS company_name,
      @normalized_name AS normalized_name,
      @name_key AS name_key,
      @email AS email,
      @email_as_entered AS email_as_entered,
      @email_local_part AS email_local_part,
      @email_domain AS email_domain,
      @mx_status AS mx_status,
      NULLIF(@phone_e164, '') AS phone_e164,
      NULLIF(@tax_id_type, '') AS tax_id_type,
      NULLIF(@tax_id_hash, '') AS tax_id_hash,
      NULLIF(@tax_id_last4, '') AS tax_id_last4,
      @hash_key_version AS hash_key_version,
      IF(@has_address,
         STRUCT(@address_line1 AS line1, NULLIF(@address_line2, '') AS line2,
                @address_city AS city, NULLIF(@address_region, '') AS region,
                NULLIF(@address_postal_code, '') AS postal_code,
                @address_country_code AS country_code),
         NULL) AS address,
      NULLIF(@normalized_address, '') AS normalized_address,
      @source_channel AS source_channel
  ) AS s
  ON t.email = s.email
     OR (s.phone_e164 IS NOT NULL AND t.phone_e164 = s.phone_e164)
     OR (s.tax_id_hash IS NOT NULL AND t.tax_id_hash = s.tax_id_hash)
  WHEN NOT MATCHED THEN
    INSERT (customer_id, customer_type, given_name, family_name, company_name, normalized_name,
            name_key, email, email_as_entered, email_local_part, email_domain, mx_status,
            phone_e164, tax_id_type, tax_id_hash, tax_id_last4, hash_key_version, address,
            normalized_address, source_channel, created_at, updated_at)
    VALUES (s.customer_id, s.customer_type, s.given_name, s.family_name, s.company_name,
            s.normalized_name, s.name_key, s.email, s.email_as_entered, s.email_local_part,
            s.email_domain, s.mx_status, s.phone_e164, s.tax_id_type, s.tax_id_hash,
            s.tax_id_last4, s.hash_key_version, s.address, s.normalized_address,
            s.source_channel, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());
  SET inserted = @@row_count;

  IF inserted = 1 THEN
    INSERT INTO `${project}.${dataset}.registration_audit_logs`
      (event_id, request_id, idempotency_key, request_fingerprint, channel, operation, outcome,
       http_status, customer_id, email_hash, client_hash, matched_on, problem_codes, mx_status,
       advisory_status, typo_suggested_domain, fuzzy_candidate_ids, fuzzy_max_confidence,
       advisory_model, lock_retries, latency_ms, created_at)
    VALUES (@event_id, @request_id, NULLIF(@idempotency_key, ''), @request_fingerprint,
            @source_channel, 'register', 'created', 201, @customer_id, @email_hash, @client_hash,
            [], [], @mx_status, @advisory_status, NULLIF(@typo_suggested_domain, ''),
            @fuzzy_candidate_ids, NULLIF(@fuzzy_max_confidence, -1.0),
            NULLIF(@advisory_model, ''), @lock_retries, @latency_ms, CURRENT_TIMESTAMP());
    SET outcome = 'created';
    COMMIT TRANSACTION;
  ELSE
    SET matched_on = IFNULL((
      SELECT ARRAY_AGG(DISTINCT field ORDER BY field) FROM (
        SELECT 'email' AS field FROM `${project}.${dataset}.customers` WHERE email = @email
        UNION ALL
        SELECT 'phone' FROM `${project}.${dataset}.customers`
          WHERE @phone_e164 != '' AND phone_e164 = @phone_e164
        UNION ALL
        SELECT 'tax_id' FROM `${project}.${dataset}.customers`
          WHERE @tax_id_hash != '' AND tax_id_hash = @tax_id_hash
      )
    ), []);
    ROLLBACK TRANSACTION;
  END IF;
END IF;

SELECT
  outcome,
  IF(outcome = 'created', @customer_id, replay.customer_id) AS customer_id,
  matched_on;
```

- The `MERGE` `ON` clause is the uniqueness rule. The `matched_on` query only explains a refusal and never decides one.
- `sql/checks/duplicate_keys.sql` groups `customers` by `email`, `phone_e164`, and `tax_id_hash` and returns each key name with the customer ids that share a value. It returns zero rows while the rule holds and prints no key values.
- The platform check confirms the script shape: `ROLLBACK` inside `IF`, the `STRUCT` variable, and the final `SELECT`.

### Email validation and typo advice

- **Syntax.** `email_validator.validate_email(..., check_deliverability=False)` checks syntax and returns the normalized form. Failure is `email-invalid`.
- **Disposable.** The domain and each parent domain are looked up in `app/data/disposable_domains.txt`, loaded once at startup into a frozenset. A hit is `email-disposable`.
- **MX.** `dns.asyncresolver` with a 2-second lifetime looks for MX records, then A or AAAA records as the RFC 5321 implicit MX. NXDOMAIN or no records is `email-domain-undeliverable`. A timeout or SERVFAIL is `unknown`, and registration continues.
- **Typo rules.** When the domain is outside `free_mail_domains.txt` and within Damerau-Levenshtein distance 2 of a domain inside it, or its TLD is a known slip such as `.con` or `.cmo`, the rules suggest the corrected address with `source = rules`. `gmial.com` becomes `gmail.com` this way, with no model call.
- **Typo model.** When the rules find nothing, Gemini receives the domain alone and returns `{is_likely_typo, suggested_domain, confidence}`. Code accepts the suggestion only when the suggested domain differs from the input, is a free-mail domain or passes the MX lookup, and comes with confidence of at least 0.7. The warning then carries `source = model`.
- **Effect.** A typo suggestion is advice. An email that passes syntax, the disposable list, and MX registers with a `possible_typo` warning. The form calls validate when the email field loses focus, so the person usually sees the suggestion before submitting.

### Duplicate detection and fuzzy advice

1. **Exact match.** `find_exact_matches.sql` reports which of email, phone, and tax-ID hash already exist. Check-duplicate returns these as `exact_matches`. Register relies on the transaction, because a read outside the lock cannot be authoritative.
2. **Blocking.** `find_fuzzy_candidates.sql` returns up to 50 rows where `normalized_name` or `name_key` equals the applicant's, or the postal code and country match, or the business email domain matches (businesses only, free-mail domains excluded).
3. **Pre-score.** Rapidfuzz builds a comparison vector per candidate: name similarity (`token_sort_ratio`), address similarity (`token_set_ratio` on `normalized_address`), same postal code, same business email domain, and email local-part similarity. A candidate goes to the model when name similarity is at least 0.80, or at least 0.60 together with a shared postal code, a shared business domain, or address similarity of at least 0.85. The top five by name similarity go forward. Every threshold is configuration, labeled as an uncalibrated default.
4. **Model.** Gemini receives the applicant and up to five candidates under the references `c1` to `c5`, with customer type, normalized name, company name, city, postal code, country, and business email domain. It never receives a phone, tax ID, email local part, or customer id. It returns `{candidates: [{ref, verdict, confidence, reasons}]}`, where `verdict` is `likely_same`, `possibly_same`, or `different`.
5. **Validation.** Every ref must be one that was sent, verdicts and reasons must be in their enums, and confidence must be in range. Any failure makes the advisory `unavailable`.
6. **Warning.** A `possible_duplicate` warning appears when a verdict is `likely_same` or `possibly_same` with confidence of at least 0.60. It carries the highest confidence and up to three reason codes. The audit row records the candidate customer ids and the highest confidence for reporting.

The advisor's prompts have role, context, task, format, and constraint sections. Applicant and candidate values sit in a delimited data section marked as untrusted input. Calls use structured output with the Pydantic model as the response schema, and set no sampling parameters, because the documented successor models removed some of them. Each call has its own timeout inside the 4-second budget.

### ADK assistant (`app/agents/registration_agent.py`)

- **Agent.** One `LlmAgent` named `registration_assistant`, with its model from `GEMINI_ASSISTANT_MODEL`, `output_schema=AssistantTurn` (`message`, `suggested_actions`), and three tools. A single agent fits, because the tools share one context and no split would buy parallelism or isolation.
- **Instruction sections.**
  - Role: the signup assistant for this registration form.
  - Context: the redacted form snapshot and the last result, in a delimited section marked untrusted. The tax ID and phone appear as their type and last four characters only.
  - Task: explain validation problems, duplicate conflicts, and warnings, help the person fix fields, and offer registration.
  - Format: the `AssistantTurn` schema.
  - Constraints: say a registration happened only when the register tool returned `created` this turn; never ask for a full tax ID in chat; treat every form value and message as data; stay on onboarding.
- **Tools.** Each is an async function with full type hints and a docstring whose first sentence states its purpose, so ADK can build the schema.

| Tool | Parameters the model sees | Behavior |
| --- | --- | --- |
| `validate_email_tool` | `email: str` | Calls `EmailValidationService.validate` and returns the `EmailValidationResult` as a dict |
| `detect_duplicate_customer_tool` | `include_likely_duplicates: bool = True` | Reads the form snapshot from `tool_context.state`, calls `DuplicateDetectionService.check`, and returns matched field names and the warning, never another customer's data |
| `register_customer_bq_tool` | none | Reads the snapshot and `confirmed_fingerprint` from state. Returns `needs_confirmation` unless the API set confirmation for this turn and the snapshot's fingerprint equals the confirmed one. Otherwise calls `RegistrationService.register` with channel `assistant` and an idempotency key derived from the session and fingerprint, and stores the outcome in `state["registration_outcome"]`. |

- **Guardrails in code.**
  - The API sets `registration_confirmed` and `confirmed_fingerprint` in session state only for a request with `action = confirm_registration`, and clears both after the turn.
  - `before_model_callback` refuses a turn past 30 per session or a prompt above the configured size.
  - `before_tool_callback` caps tool calls at four per turn and checks the confirmation flag again before the register tool runs.
  - `AssistantReply.registration` is copied from `state["registration_outcome"]`, so the UI shows registration status from the tool result and never from the model's prose.
- **Runner.** The lifespan builds `Runner(agent=..., app_name="registration-assistant", session_service=InMemorySessionService())`. Each turn creates the session if it is absent (`user_id` is `anon-<session_id>`), sets per-turn state, and runs `run_async` under a 20-second budget. Per-turn state goes through `run_async(..., state_delta=...)` when the pinned ADK has that argument, and otherwise through `session_service.append_event` with an `EventActions(state_delta=...)` event. The ADK step settles which one against the pinned version.
- **Session bounds.** A janitor task deletes sessions idle for 30 minutes and caps the store at 1,000 sessions.
- **Fallback.** With `LLM_FALLBACK_MODEL=openai/gpt-4o` and an OpenAI key configured, a second agent built on `LiteLlm` runs the same turn when the Gemini call fails with a transient error or times out. ADK documents no fallback chain, so the wrapper owns it. The fallback is off by default. It never runs fuzzy adjudication, which stays on Gemini inside the duplicate service. `AssistantReply.used_fallback` and the log line record which model answered.

### Frontend (`ui/`)

- **Stack.** Next.js 15 (the latest 15.x at scaffold) on the App Router, React 19, strict TypeScript, Tailwind CSS v4 through `@tailwindcss/postcss`, shadcn/ui with the `Field` family, Lucide icons, react-hook-form with `zodResolver`, TanStack Query for the mutations, `next-themes`, and `openapi-typescript` types generated from `contracts/openapi.yaml`.
- **Runtime configuration.** `app/layout.tsx` renders dynamically, reads `API_BASE_URL` from the server environment at request time, and passes it to a client context. One build serves every environment.
- **Tokens.** shadcn's neutral base with one accent, a blue at Tailwind's blue-600 in light and blue-500 in dark, assigned to `--primary` and `--ring` only. Every other color is neutral. `.dark` overrides the same tokens, and no component names its own dark colors. Contrast is checked per token pair in both themes: 4.5:1 for text, 3:1 for the focus ring and input borders.
- **Layout.** A header holds the title and the theme toggle. From `lg` up, a two-column grid puts the form card on the left and the assistant panel on the right at 24rem, sticky. Below `lg` the form takes the full width, and a floating "Ask the assistant" button with a 44px target opens the same panel in a bottom `Sheet` drawer.
- **Form alignment.**
  - Labels sit above fields (`FieldLabel`). Help text sits under the control (`FieldDescription`), and the error directly under its control (`FieldError`), wired with `aria-describedby` and `aria-invalid`.
  - One spacing scale from Tailwind's 4px steps: `gap-2` inside a field, `gap-6` between fields, `gap-8` between groups, and `p-6` card padding (`p-4` on phones).
  - Groups are `FieldSet`s with a `FieldLegend`. Customer holds the type as a radio group, given and family name as a pair, and the company name for businesses. Contact holds the email at full width, then phone and tax ID as a pair, with a compact tax-ID type select joined to its input. Address holds line 1 and line 2 at full width, city and region as a pair, and postal code and country as a pair.
  - Pairs sit in two columns from `md` up and stack in one column below it.
  - The submit button is right-aligned from `sm` up and full width below. Focus states use the `--ring` token and are always visible.
- **Behavior.**
  - When the email field loses focus, the form calls validate. Problems show under the email field. A suggestion shows as "Did you mean …?" with a Use button that applies it.
  - Submit sends an `Idempotency-Key` generated once per form session.
  - A 201 shows a success card with the customer id and any warnings, each with an "Ask the assistant" button that sends the result to chat.
  - A 409 puts "Already registered to another customer" under each matched field. A 422 maps `errors[].pointer` onto fields. A 429 shows the wait time, and a 503 offers a retry.
- **Assistant panel.** A message list inside a polite live region mounted empty at load, a text input, and suggested-action buttons (apply suggestion, confirm registration). Each turn sends the form snapshot and the last result. Confirm registration opens a dialog naming the consequence, then sends `action = confirm_registration`. The session id lives in `sessionStorage`.
- **Privacy notice.** A short notice under the form says what is stored, that Gemini on Google Cloud checks for typos and possible duplicates, and that OpenAI is used only when the fallback is on.

### Security, privacy, and identity

- **SQL.** Templates load from files. The project name must match `^[a-z][a-z0-9-]{4,28}[a-z0-9]$` and the dataset name `^[A-Za-z0-9_]{1,1024}$` before substitution, and every value travels as a query parameter.
- **Hashing.** Tax IDs, audit emails, and client IPs are hashed with one HMAC-SHA256 key and a domain prefix per kind (`tax_id:`, `email:`, `client:`). Customers keep the tax ID's last four characters for display.
- **Secrets.** `pydantic-settings` reads `pii_hash_key`, `bot_check_secret`, and `openai_api_key` as `SecretStr` from a mounted secrets directory. Secret Manager mounts them on Cloud Run.
- **Logging.** structlog writes JSON to stdout through an allow-list processor with the keys `event`, `level`, `timestamp`, `request_id`, `route`, `status`, `outcome`, `duration_ms`, `problem_type`, `advisory_status`, `lock_retries`, `model`, `used_fallback`, and `error_type`. Uvicorn's access log is off, and a middleware logs the method, route template, status, and duration. ADK and google-genai loggers run at WARNING, and GenAI telemetry content capture is off.
- **CORS.** `CORSMiddleware` takes `allow_origins` from `CORS_ALLOW_ORIGINS`, with `allow_credentials=False`, methods `GET`, `POST`, and `OPTIONS`, request headers `Content-Type`, `Idempotency-Key`, and `X-Request-Id`, and exposed headers `X-Request-Id`, `Retry-After`, and `Idempotent-Replayed`. An empty value or `*` refuses to boot.
- **Local adapters.** The in-memory store and the stub bot verifier load only with `ALLOW_LOCAL_ADAPTERS=true`, which deployed configuration never sets. `ADVISOR_ENABLED` and `ASSISTANT_ENABLED` are kill switches that default to on, and their off paths are tested.
- **Client IP.** Rate limiting reads the first `X-Forwarded-For` hop only when `TRUST_PROXY_HEADERS=true` (Cloud Run), and the socket peer otherwise.

## Steps

Work on a feature branch. Each step's tests are written red first, alongside its code.

**Demo outputs**

| Output named in the brief | Produced by | Path |
| --- | --- | --- |
| API specification (OpenAPI 3.1 YAML) | Configuration and API contract | `contracts/openapi.yaml` |
| Database schema (BigQuery DDL and the `MERGE` template) | BigQuery schema and query templates | `sql/001_customer_ops_schema.sql`, `sql/register_customer.sql` |
| Python source code | Configuration and API contract through App assembly | `app/` |
| Frontend UI | UI scaffold, Registration form, Assistant panel | `ui/app/page.tsx`, `ui/features/` |
| Unit and integration tests | API test suite, plus the unit tests in each code step and the live platform check | `tests/test_registration.py`, `tests/unit/`, `tests/integration/` |
| Code review report | Code review report | `docs/code-review-report.md` |

1. **Workspace scaffold.** `[new file: pyproject.toml]` `[new file: uv.lock]` `[new file: .python-version]` `[new file: .env.example]` `[new file: Makefile]` `[.gitignore:15]`
   - Create a uv project with `requires-python = ">=3.11"`. Pin `.python-version` to 3.14 so `uuid.uuid7()` is in the standard library. If `uv sync` finds a dependency without 3.14 wheels, pin 3.13, add `uuid-utils`, and say why in the README.
   - Pin runtime dependencies exactly: `google-adk[gcp]==2.14.1`, `google-genai` (latest 2.x, since ADK requires `<3`), `google-cloud-bigquery==3.47.0`, `fastapi==0.163.1`, `uvicorn[standard]`, `pydantic==2.14.3`, `pydantic-settings`, `email-validator==2.4.0`, `dnspython==2.9.2`, `phonenumbers`, `rapidfuzz==3.14.6`, `structlog`, and `pyyaml`. Versions marked unverified in Context are pinned to the latest release on the day of scaffold.
   - Add an optional extra `fallback` with `litellm>=1.84,<1.106.3`, the bound ADK itself uses. Versions 1.82.7 and 1.82.8 were compromised and fall outside it.
   - Dev group: `pytest>=9,<10`, `pytest-asyncio==1.5.0`, `pytest-randomly`, `httpx`, `hypothesis`, `ruff`, and `mypy`. Configure ruff lint and format, `mypy --strict` on `app/`, `asyncio_mode = "auto"`, and an `integration` marker that the default run deselects.
   - `.env.example` lists every setting from `app/config.py` with placeholder values.
   - Makefile targets: `dev` (the API with reload on the in-memory store, plus `npm run dev`), `test`, `lint`, `spec`, `schema`, `integration`, `ui-test`, and `e2e`. Every target is safe to re-run.
   - After `.gitignore` line 15, outside the AXIS block, append `.venv/`, `__pycache__/`, `.env`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `ui/node_modules/`, `ui/.next/`, `ui/test-results/`, and `ui/playwright-report/`. Skip any line already present.
   - Tests: `make lint` passes on the empty package, and a second `uv sync` changes nothing.

2. **Configuration and API contract.** **Output: API specification.** `[new file: app/config.py]` `[new file: app/models/schemas.py]` `[new file: app/api/problems.py]` `[new file: app/api/routes_customers.py]` `[new file: app/api/routes_agent.py]` `[new file: app/api/dependencies.py]` `[new file: app/main.py]` `[new file: scripts/export_openapi.py]` `[new file: contracts/openapi.yaml]` `[new file: .spectral.yaml]` `[new file: tests/test_contract.py]`
   - `Settings` (pydantic-settings) holds the GCP project, `bq_dataset="customer_ops"`, `bq_location`, `customer_store` (`bigquery` or `memory`), `allow_local_adapters`, `cors_allow_origins`, `trust_proxy_headers`, `gemini_advisor_model`, `gemini_assistant_model`, `genai_location`, `advisor_enabled`, `assistant_enabled`, `llm_fallback_model`, the budgets (MX 2 s, advisory 4 s, chat 20 s, lock retries 10 s), the fuzzy thresholds, the per-operation rate limits, and the secrets directory. Both model ids default to `gemini-2.5-flash` as briefed, and `gemini-2.5-pro` is selectable for either.
   - Boot refuses: a missing project when the store is `bigquery`; the memory store or stub verifier without `ALLOW_LOCAL_ADAPTERS`; an empty or wildcard CORS list; an invalid project or dataset name.
   - Build the wire models from the table under API contract. `problems.py` maps each typed domain error to its problem type in one central handler, replaces FastAPI's validation handler, and maps any other exception to a generic 500.
   - Declare the four routes with `summary`, `operation_id` (`registerCustomer`, `validateEmail`, `checkDuplicateCustomer`, `chatWithAssistant`), tags (`customers`, `assistant`), a docstring, and a `responses=` map naming every status with its model and an example. Handlers take their service through `Depends` and call one method.
   - `scripts/export_openapi.py` writes `create_app().openapi()` to `contracts/openapi.yaml` in stable key order.
   - `.spectral.yaml` extends `spectral:oas` and requires an `operationId`, a description, and a problem+json body on every 4xx and 5xx.
   - Tests in `tests/test_contract.py`: the regenerated spec equals the committed file; every error response references `ProblemDetails`; every schema property has a description; register documents 201, 409, and 422; validate and check-duplicate document 200 and no 409.

3. **Domain rules.** `[new file: app/domain/normalize.py]` `[new file: app/domain/email_rules.py]` `[new file: app/domain/matching.py]` `[new file: app/domain/errors.py]` `[new file: app/data/disposable_domains.txt]` `[new file: app/data/free_mail_domains.txt]` `[new file: scripts/refresh_disposable_domains.py]` `[new file: tests/unit/test_normalize.py]` `[new file: tests/unit/test_email_rules.py]` `[new file: tests/unit/test_matching.py]`
   - `normalize.py` holds pure functions: `canonical_email`, `split_email`, `normalize_name` (NFKD accent removal, casefold, punctuation removal, and for businesses the legal suffixes `inc`, `incorporated`, `llc`, `ltd`, `limited`, `gmbh`, `plc`, `corp`, `corporation`, `co`, and `pvt`) returning `normalized_name` and `name_key`, `normalize_phone` returning E.164, `normalize_tax_id`, and `normalize_address`.
   - Tax-ID patterns, proposed until the tax-ID formats question is answered: `us_ein` is 9 digits; `gb_vat` is `GB` plus 9 or 12 digits; `in_pan` is 5 letters, 4 digits, and 1 letter; `other` is 4 to 30 letters and digits.
   - `email_rules.py` holds `is_disposable` (checking parent domains too) and `typo_suggestion` (rapidfuzz Damerau-Levenshtein distance up to 2, plus a TLD slip table).
   - `matching.py` holds `ComparisonVector`, `compare`, and `select_for_review`, with thresholds passed in.
   - `errors.py` holds `EmailInvalid`, `EmailDisposable`, `EmailUndeliverable`, `PhoneInvalid`, `TaxIdInvalid`, `DuplicateCustomer(matched_on)`, `IdempotencyKeyReused`, `RegistrationBusy`, `RateLimited(retry_after)`, `BotCheckFailed`, and `AssistantUnavailable`.
   - `disposable_domains.txt` opens with a comment naming its source URL, license, and fetch date. `refresh_disposable_domains.py` downloads from the configured source and rewrites the file, so a re-run with no upstream change leaves it identical.
   - Tests (parameterized): `Jane.Doe@Example.TEST` becomes `jane.doe@example.test`; malformed addresses are rejected; `Müller-Smith, Jane` and `jane muller smith` share a `name_key`; `Acme Inc.` and `ACME Incorporated` share a `normalized_name`; `(415) 555-0100` with `US` becomes `+14155550100`; each tax-ID type accepts one valid and rejects one invalid value; a subdomain of a disposable domain is disposable; `gmial.com` and `gmail.con` suggest `gmail.com`, and `example.test` suggests nothing. Hypothesis checks that normalization is idempotent and that `name_key` ignores token order.

4. **BigQuery schema and query templates.** **Output: database schema.** `[new file: sql/001_customer_ops_schema.sql]` `[new file: sql/register_customer.sql]` `[new file: sql/find_exact_matches.sql]` `[new file: sql/find_fuzzy_candidates.sql]` `[new file: sql/insert_audit_event.sql]` `[new file: sql/checks/duplicate_keys.sql]` `[new file: scripts/apply_schema.py]` `[new file: tests/unit/test_sql_templates.py]`
   - Write the DDL and the transaction exactly as specified in Approach, plus the three query templates and the check.
   - `apply_schema.py` validates identifiers, renders the DDL, runs each statement as a query job, and prints the tables it found or created. Re-running it changes nothing.
   - Tests in `tests/unit/test_sql_templates.py`: every template renders with valid identifiers and refuses invalid ones; no template contains Python format fields or `%` placeholders; every `@name` in a template has a parameter in the repository's builder for it, and the builder sends no parameter the template lacks; in `register_customer.sql` the lock `DELETE` comes after `BEGIN TRANSACTION` and before the `MERGE`.

5. **Repository and ports.** `[new file: app/services/ports.py]` `[new file: app/services/bq_repository.py]` `[new file: app/services/memory_repository.py]` `[new file: tests/unit/test_bq_repository.py]` `[new file: tests/unit/test_memory_repository.py]`
   - `ports.py` declares Protocols: `CustomerRepository` (`register`, `find_exact_matches`, `find_fuzzy_candidates`, `record_attempt`), `MxResolver`, `Advisor`, `RateLimiter`, `BotVerifier`, `Clock`, and `IdGenerator`.
   - `BigQueryCustomerRepository(client, project, dataset)` builds `ScalarQueryParameter` and `ArrayQueryParameter` lists, turns absent optionals into `''` or `-1.0` as each template expects, runs jobs through `asyncio.to_thread` with a per-job timeout, and labels jobs `app=registration-api` and `operation=<name>`. It raises `LockConflict` on the concurrent-update abort, matched on the error reason the platform check records. No method uses `insert_rows_json` or any streaming API.
   - `InMemoryCustomerRepository` implements the same port with one `asyncio.Lock` around `register`. `make dev` and the real-backend browser journey use it.
   - Tests: with `create_autospec(bigquery.Client)`, every value travels as a parameter; a given name of `'; DROP TABLE customers; --` appears in a parameter and never in the SQL text; absent optionals become `''`; the abort error raises `LockConflict`; result rows map to the four outcomes. For the memory store, 20 concurrent registrations of one email yield one `created` and 19 `duplicate`.

6. **Platform check.** This step is a gate for the advisor and assistant steps, and evidence for the transaction design. `[new file: tests/integration/conftest.py]` `[new file: tests/integration/test_bigquery_semantics.py]` `[new file: tests/integration/test_gemini_models.py]`
   - Run with `make integration` against the dev project. Each run creates the dataset `it_<run id>` with a one-day default table expiration and deletes it in teardown (`delete_contents=True`, `not_found_ok=True`), so a re-run after a crash starts clean.
   - The DDL applies, `PARTITION BY DATE(created_at)` included.
   - With the lock: 20 trials of 5 concurrent `register_customer.sql` runs for one new email. Every trial inserts exactly once, and the rest abort or report a duplicate. Record the abort's error reason and message for `LockConflict`.
   - Without the lock: the same trials with the `DELETE` removed. Record whether duplicates appear, as evidence for the README. The lock stays either way.
   - Retry timing: how soon a retry after an abort succeeds or sees the duplicate. If retries within 10 seconds fail in more than 5% of trials, the decision goes back to the user with the transactional store from Left unbuilt.
   - The script shape behaves as written: `ROLLBACK` inside `IF`, the `STRUCT` variable, and the final `SELECT`.
   - Latency: p50 and p95 of the transaction script over 30 runs.
   - Gemini: one structured call to each configured model id through Vertex AI. A failure blocks the advisor and assistant steps until the Gemini model question is answered. The deterministic steps continue meanwhile.
   - Record the findings in the PR description and capture them with `/axis-distill`.
   - When no dev project is available, this step is **BLOCKED**. The offline steps proceed, and the PR states that the transaction design is unproven against BigQuery.

7. **Email validation service.** `[new file: app/services/dns_mx.py]` `[new file: app/services/email_validation.py]` `[app/api/routes_customers.py]` `[new file: tests/unit/test_email_validation.py]`
   - `AsyncMxResolver` wraps `dns.asyncresolver` with the configured lifetime and returns `pass`, `fail`, or `unknown`.
   - `EmailValidationService.validate(email)` runs syntax, the disposable check, MX, the typo rules, and then the advisor's domain check when the rules found nothing. It returns `EmailValidationResult`. `assert_registrable(email)` raises the matching domain error for the register path.
   - Wire the validate route.
   - Tests with a fake resolver: each check's failure produces its problem code; an MX timeout gives `unknown` with `is_valid` true; a rule suggestion skips the advisor; a model suggestion whose domain fails MX is discarded; an advisor exception leaves `suggestion` null.

8. **Gemini advisor.** `[new file: app/services/advisor.py]` `[new file: tests/unit/test_advisor.py]`
   - `GeminiAdvisor(client: genai.Client, settings)` exposes `suggest_domain(domain)` and `assess_candidates(applicant, candidates)`. The lifespan builds the client with `genai.Client(vertexai=True, project=..., location=...)`, so the advisor never depends on environment-variable switching.
   - Prompts follow the section structure under Duplicate detection. Responses parse with `model_validate_json` into `TypoAdvice` and `FuzzyAdvice`, then pass the validation rules there.
   - `DisabledAdvisor` serves `ADVISOR_ENABLED=false` and reports `disabled`.
   - Tests with a fake `client.aio.models.generate_content`: valid JSON maps to advice; an unknown ref, an out-of-range confidence, or an unknown verdict gives `invalid_output`; a timeout gives `unavailable`; the captured fuzzy request contains no phone, tax ID, email local part, or customer id; the captured typo request contains the domain and nothing else from the input.

9. **Duplicate detection service.** `[new file: app/services/duplicate_detection.py]` `[app/api/routes_customers.py]` `[new file: tests/unit/test_duplicate_detection.py]`
   - `DuplicateDetectionService.check(command)` runs the exact query and the blocking query concurrently, scores candidates with `matching.py`, asks the advisor about the selected ones, and returns `DuplicateCheckResult`. It appends an audit row with operation `check_duplicate`.
   - Wire the check-duplicate route, with rate limiting and the bot check.
   - Tests: exact email and phone matches are both reported; candidates below the floor never reach the advisor; at most five reach it; refs map back to the right customer ids for the audit row and never appear in the response; an advisor failure returns exact matches with `advisory_status = unavailable`.

10. **Registration service and register route.** `[new file: app/services/registration.py]` `[new file: app/services/rate_limit.py]` `[new file: app/services/bot_check.py]` `[new file: app/services/pii.py]` `[app/api/routes_customers.py]` `[new file: tests/unit/test_registration_service.py]`
    - `RegistrationService.register(command, channel, idempotency_key)` runs the register flow under Approach and owns the retry loop on `LockConflict`.
    - `pii.py` computes the keyed hashes and the request fingerprint (SHA-256 of the canonical body).
    - `rate_limit.py` is an in-memory sliding window per client and operation. Defaults: register 5 and check-duplicate 10 per 10 minutes, validate 30 per minute, chat 20 per 10 minutes.
    - `bot_check.py` defines the `BotVerifier` port and `StubBotVerifier`, which accepts the token `local` only when local adapters are allowed. The real provider waits for the abuse providers question.
    - Wire the register route, including the `Idempotency-Key` header and the `Idempotent-Replayed` response header.
    - Tests with a fake clock: two `LockConflict`s then success returns `created` with `lock_retries = 2`; conflicts past the budget raise `RegistrationBusy`; outcome mapping for all four outcomes; non-created outcomes write exactly one audit row; the sliding window resets after its interval.

11. **ADK assistant and chat route.** `[new file: app/agents/registration_agent.py]` `[app/api/routes_agent.py]` `[new file: tests/unit/test_agent_tools.py]`
    - Build the agent, the three tools, the callbacks, the session janitor, the optional LiteLLM fallback agent, and `RegistrationAssistant.chat(request)` as specified under ADK assistant.
    - Settle the per-turn state mechanism against the pinned ADK version: `run_async(..., state_delta=...)` or `session_service.append_event`. Record which in a docstring.
    - Settle which environment variable makes ADK's Gemini model use Vertex AI in the pinned version, and set it at boot from configuration.
    - Wire the chat route. A model failure without a fallback returns 503 `assistant-unavailable`.
    - Tests call each tool directly with a fake `ToolContext` holding a `state` dict:
      - register returns `needs_confirmation` with no flag, and with a flag whose fingerprint differs from the snapshot;
      - register creates once with a matching flag, and a second call replays the same customer;
      - detect returns field names and the warning only;
      - validate passes the email through.
    - A construction test checks that the agent has exactly the three named tools, and that the declarations ADK generates for them expose only `email` and `include_likely_duplicates` as parameters.

12. **App assembly.** `[app/main.py]` `[new file: app/logging.py]` `[new file: app/api/health.py]` `[new file: tests/unit/test_app_boot.py]`
    - The lifespan builds the settings, logging, the BigQuery client (`bigquery.Client(project=..., location=...)`) or the memory store, the genai client, the advisor, the three services, the assistant and its janitor, the rate limiter, and the bot verifier, and stores them on `app.state`. On shutdown it marks the app as draining, cancels the janitor, and closes the clients.
    - Middleware: request id, the access log line, and CORS.
    - `/healthz/live` always returns 200. `/healthz/ready` reads the dataset's metadata (cached for 30 seconds) and returns 503 while draining.
    - Tests: the app boots on memory settings; boot refuses `CORS_ALLOW_ORIGINS=*` and the memory store without local adapters; readiness returns 503 during shutdown.

13. **API test suite.** **Output: unit and integration test cases.** `[new file: tests/conftest.py]` `[new file: tests/fakes.py]` `[new file: tests/test_registration.py]`
    - `fakes.py` provides a BigQuery client built on `create_autospec(bigquery.Client)` whose `query()` returns a fake job chosen by template, a scripted advisor with failure modes, a fake MX resolver, a frozen clock, and a fixed id generator. `FakeRunner` yields real `google.adk.events.Event` objects built with the pinned version's constructor, so the fake keeps the true event shape. Every test runs through `httpx` against `create_app()` with no credentials and no network.
    - `tests/test_registration.py` cases, each named after its behavior:
      1. a valid registration returns 201 with `customer_id` and sends every value as a query parameter;
      2. malformed emails return 422 `email-invalid` and write no customer (parameterized over four shapes);
      3. a disposable domain returns 422 `email-disposable`;
      4. a domain with no MX or A record returns 422 `email-domain-undeliverable`;
      5. an MX timeout still registers, with `mx_status = unknown` in the parameters;
      6. an existing email returns 409 with `matched_on = ["email"]` and no other customer's data;
      7. a matching phone and tax ID return 409 naming both;
      8. a near-duplicate (swapped name order, same postal code) returns 201 with a `possible_duplicate` warning;
      9. an advisor failure returns 201 with `advisory_status = unavailable` and no warning;
      10. `jane@gmial.com` returns a `possible_typo` warning from the rules, and the advisor records no call;
      11. a lock conflict retries and then returns 201;
      12. lock conflicts past the budget return 503 with `Retry-After`;
      13. the same `Idempotency-Key` and body return 201 with the same id and `Idempotent-Replayed: true`;
      14. the same key with a different body returns 422 `idempotency-key-reused`;
      15. the sixth register call from one client in 10 minutes returns 429 with `Retry-After`;
      16. validate returns 200 with `is_valid = false` for an invalid email;
      17. check-duplicate reports exact and likely matches and writes no customer;
      18. chat returns the mocked runner's reply;
      19. a chat turn whose model calls the register tool without a confirm action registers nobody;
      20. a chat model failure returns 503, and with the fallback configured returns 200 with `used_fallback = true`;
      21. a CORS preflight from an unlisted origin gets no allow-origin header;
      22. no captured log line contains any submitted name, email, phone, tax ID, address, or chat message.

14. **UI scaffold.** `[new file: ui/package.json]` `[new file: ui/package-lock.json]` `[new file: ui/next.config.ts]` `[new file: ui/postcss.config.mjs]` `[new file: ui/tsconfig.json]` `[new file: ui/components.json]` `[new file: ui/app/layout.tsx]` `[new file: ui/app/globals.css]` `[new file: ui/components/theme-provider.tsx]` `[new file: ui/components/theme-toggle.tsx]` `[new file: ui/lib/runtime-config.tsx]` `[new file: ui/lib/api.ts]` `[new file: ui/lib/api-schema.d.ts]`
    - Only when `ui/` does not exist, run `create-next-app` at version 15 with TypeScript, the App Router, Tailwind, ESLint, and the `@/*` alias. Pin `next` to the latest 15.x and `typescript` to the version `npm view` reports that day, both exact in `package.json`. Add an `engines` field and use `npm ci` everywhere after the first install.
    - Run `shadcn@4.23.0 init` with the neutral base and CSS variables, then `add button input label field select radio-group card alert badge sheet dialog separator textarea sonner scroll-area`. Re-running `add` with `--overwrite` is safe.
    - `globals.css`: `@import "tailwindcss";`, the shadcn tokens, the accent on `--primary` and `--ring` in both themes, `@custom-variant dark (&:is(.dark *));`, and the `@theme inline` bridge.
    - `theme-provider.tsx` wraps `next-themes` with `attribute="class"`, `defaultTheme="system"`, `enableSystem`, and `disableTransitionOnChange`. `theme-toggle.tsx` uses Lucide `Sun` and `Moon` with an accessible name.
    - `layout.tsx` sets `export const dynamic = "force-dynamic"` and `<html lang="en" suppressHydrationWarning>`, reads `API_BASE_URL`, and provides it through `runtime-config.tsx`.
    - `npm run gen:api` runs `openapi-typescript ../contracts/openapi.yaml -o lib/api-schema.d.ts`. `lib/api.ts` builds a typed client on `openapi-fetch`, version checked at scaffold, against the runtime base URL.
    - `next.config.ts` sets `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and `X-Frame-Options: DENY`, and turns on `output: "standalone"`.
    - Confirm that `@hookform/resolvers` supports zod 4. If it does not, pin zod 3 and note why.
    - Tests: `npm run lint`, `npm run typecheck`, and `npm run build` pass.

15. **Registration form.** `[new file: ui/features/registration/registration-form.tsx]` `[new file: ui/features/registration/customer-fields.tsx]` `[new file: ui/features/registration/contact-fields.tsx]` `[new file: ui/features/registration/address-fields.tsx]` `[new file: ui/features/registration/schema.ts]` `[new file: ui/features/registration/result-card.tsx]` `[new file: ui/features/registration/use-register.ts]` `[new file: ui/features/registration/use-validate-email.ts]` `[new file: ui/features/registration/map-problem.ts]` `[new file: ui/features/registration/registration-form.test.tsx]`
    - `registration-form.tsx` is the container that owns react-hook-form and the mutations. The three field-group components are presentational and receive `control` and errors.
    - `schema.ts` mirrors the server's required fields and lengths. The server stays authoritative.
    - Build the layout, alignment, and behavior under Frontend.
    - Tests (Vitest and Testing Library): a missing required field shows its error under that field, linked by `aria-describedby`; a 409 with `matched_on = ["email","phone"]` puts errors under both; a 422 pointer lands on its field; the Use button applies a suggested domain; choosing `business` reveals the company name field.

16. **Assistant panel and page.** `[new file: ui/features/assistant/assistant-panel.tsx]` `[new file: ui/features/assistant/message-list.tsx]` `[new file: ui/features/assistant/assistant-drawer.tsx]` `[new file: ui/features/assistant/confirm-registration-dialog.tsx]` `[new file: ui/features/assistant/use-chat.ts]` `[new file: ui/app/page.tsx]` `[new file: ui/features/assistant/assistant-panel.test.tsx]`
    - `page.tsx` composes the header, the form, and the panel in the `lg` grid, with the drawer below `lg`. Both placements render the same panel component.
    - Tests: each turn sends the form snapshot and last result; confirm sends the action only after the dialog's confirm; the registration status shown comes from the `registration` field; the live region exists at mount.

17. **Browser journeys.** `[new file: ui/playwright.config.ts]` `[new file: ui/tests/e2e/pages/registration-page.ts]` `[new file: ui/tests/e2e/pages/assistant-panel.ts]` `[new file: ui/tests/e2e/registration.spec.ts]`
    - Page objects are injected as fixtures, and locators use roles and labels only.
    - Route-mocked journeys cover 201 with a warning, 409, 422, 503, and the assistant confirm flow. One real-backend journey runs against `make dev` on the memory store.
    - Layout checks at 390px (one column, drawer) and 1280px (pairs in two columns, side panel) compare bounding boxes. Axe runs in light and dark themes. One journey completes the form by keyboard alone.
    - `forbidOnly: true`, with traces and screenshots kept on failure.

18. **Containers and CI.** `[new file: Dockerfile]` `[new file: ui/Dockerfile]` `[new file: docker-compose.yml]` `[new file: .github/workflows/ci.yml]`
    - The API image is a multi-stage uv build that runs as a non-root user with `uvicorn app.main:create_app --factory` on the `PORT` from the environment. The UI image runs Next.js standalone output as a non-root user.
    - `docker-compose.yml` runs the API on the memory store with `ALLOW_LOCAL_ADAPTERS=true` and the UI with `API_BASE_URL=http://localhost:8000`.
    - CI runs `uv sync --frozen`, ruff, mypy, pytest without the integration marker, the spec drift test, Spectral, then `npm ci`, lint, typecheck, Vitest, and the route-mocked Playwright suite with artifacts uploaded on failure. Deployment stays out of scope.

19. **Docs and AGENTS.md overview.** `[AGENTS.md:5-8]` `[new file: README.md]`
    - Replace the Overview paragraph with: "smart-customer-onboarding registers customers from a public signup form and a conversational assistant, and stores them in BigQuery, where the team's customer reporting lives. A customer exists as soon as registration succeeds, with no inbox confirmation. An email address, phone number, or tax ID belongs to at most one customer, and the registration transaction in BigQuery enforces that. Gemini adds typo suggestions and likely-duplicate warnings and never decides whether a registration succeeds." Writing the same text again changes nothing.
    - The README covers what the service is, `make dev` and `make test`, every setting, the IAM grants, and the platform-check findings.

20. **Code review report.** **Output: code review report.** `[new file: docs/code-review-report.md]`
    - Run `/axis-review` on the branch. It writes `.axis/reviews/<branch>.md`, which git ignores, so the committed report goes to `docs/`.
    - Sections, each finding on the Blocker, Major, Minor, Nit scale with its `path:line`:
      - **Security:** parameterization and the injection test that proves it; PII handling (hashes, prompt minimization, the log allow-list); IAM least privilege, with `roles/bigquery.dataEditor` on the dataset and `roles/bigquery.jobUser` on the project. `dataEditor` also allows deleting tables, so the report recommends a custom role with `bigquery.tables.get`, `bigquery.tables.getData`, and `bigquery.tables.updateData`.
      - **Concurrency and data integrity:** why streaming inserts are excluded, the lock idiom, the platform-check figures, and the duplicate-keys check.
      - **Agent reliability:** the confirmation gate, tool parameter design, output validation, status taken from tool results, and fallback behavior.
      - **Recommendations for Cloud Run:** a dedicated service account per service, secrets mounted as volumes, max instances and concurrency set against lock contention, session affinity while the assistant keeps sessions in memory, a request timeout above the 20-second chat budget, startup and liveness probes, Cloud Armor rate limiting at the edge, region alignment between the dataset and Vertex AI, and the pinned model id.
    - Every Blocker and Major finding is fixed, or accepted in writing with its reason, before merge.

## Acceptance criteria

- [ ] A valid registration returns 201 with a `customer_id`. The row in `customer_ops.customers` holds the canonical email, the E.164 phone, and the tax-ID hash, and no raw tax ID exists anywhere in the dataset.
- [ ] Malformed, disposable, and undeliverable emails return 422 problem+json with the matching `type`, and no customer row is written.
- [ ] Registering an existing email, phone, or tax ID returns 409 whose `matched_on` names exactly the matching fields and carries no other customer's data.
- [ ] In the platform check, every trial of five concurrent registrations for one new email inserts exactly one row, and `sql/checks/duplicate_keys.sql` returns zero rows afterward.
- [ ] A near-duplicate returns 201 with a `possible_duplicate` warning when the advisor judges it so. With the advisor failing or disabled, the same request returns 201 with `advisory_status` `unavailable` or `disabled` and no warning.
- [ ] `jane@gmial.com` gets a `possible_typo` suggestion for `gmail.com` from the rules, with no model call.
- [ ] Repeating a register request with the same `Idempotency-Key` returns 201 with the same `customer_id` and `Idempotent-Replayed: true`. A different body under the same key returns 422 `idempotency-key-reused`.
- [ ] A chat turn without `action = confirm_registration` creates no customer, even when the model calls the register tool.
- [ ] `make test` passes with no GCP credentials and no network. Ruff, `mypy --strict`, the spec drift test, and Spectral pass.
- [ ] Regenerating the spec reproduces `contracts/openapi.yaml` byte for byte.
- [ ] In the UI, labels sit above fields and errors under their fields. Pairs show in two columns at 768px and wider and in one column below. The assistant sits beside the form at 1024px and wider and opens in a drawer below. The form and the assistant confirm flow complete by keyboard alone, and axe reports no violations in either theme.
- [ ] No log line from any test run contains a submitted name, email, phone, tax ID, address, or chat message.
- [ ] The `AGENTS.md` Overview describes registration with no inbox confirmation and uniqueness enforced by the BigQuery transaction.
- [ ] The demo outputs exist at the paths in the Steps table.
- [ ] All existing tests still pass (none exist yet).

## Risks & rollback

- **Risk (Blocker):** the briefed Gemini 2.5 models are being retired. The Gemini API routes 2.5 requests to successors from 2026-12-01 and limits access to existing users, and Vertex AI listed a 2026-10-20 retirement. Successor models change function calling, thinking controls, and sampling parameters. → **Mitigation:** model ids are configuration; the platform check calls each one; the advisor and assistant set no sampling parameters; no status code depends on a model; the Gemini model question picks the id.
- **Risk (Major):** every registration takes the `customers` table lock, a losing transaction aborts at once, and Google advises waiting 60 seconds before retrying. → **Mitigation:** short jittered retries for up to 10 seconds, then 503 with `Retry-After: 60`, and the idempotency key makes the client's retry safe. The platform check measures conflict and retry behavior, and the transactional store waits in Left unbuilt.
- **Risk (Major):** an insert-only `MERGE` without the lock can insert the same email twice. → **Mitigation:** the lock statement opens every registration transaction, a unit test asserts its position, and the duplicate-keys check runs in the platform check and can run on a schedule.
- **Risk (Major):** register and check-duplicate reveal whether an email, phone, or tax ID is registered. The user accepted this for email; phone and tax ID carry the same exposure. → **Mitigation:** per-client limits per operation, the bot check on register and check-duplicate, and `client_hash` in the audit table to spot probing. The abuse providers question picks stronger providers.
- **Risk (Major):** personal data reaches model providers. Gemini on Vertex AI sees applicant and candidate names, companies, and locations. The GPT-4o fallback, when on, sees chat messages and the redacted snapshot. → **Mitigation:** the field minimization under Constraints, opaque candidate references, the fallback off by default and never used for matching, the privacy notice on the form, and the fallback data question.
- **Risk (Major):** Next.js 15 receives only critical fixes, and its security releases end on 2027-01-31. → **Mitigation:** pin the latest 15.x, avoid APIs that changed in 16, and settle the Next.js major question before production.
- **Risk (Major):** prompt injection through chat text or form fields. → **Mitigation:** the register tool takes no data from the model, only the API sets confirmation, values sit in untrusted sections, outputs are schema-validated, the UI shows status from tool results, and tool calls are capped per turn.
- **Risk (Minor):** assistant sessions and rate limits live in one instance's memory. → **Mitigation:** session affinity and an instance cap in the Cloud Run recommendations; shared storage waits in Left unbuilt.
- **Risk (Minor):** daily partitions on a small `customers` table make many tiny partitions, and BigQuery caps partitions per table. → **Mitigation:** the brief's DDL stands; the review reports partition sizes and recommends `TIMESTAMP_TRUNC(created_at, MONTH)` if they stay small.
- **Risk (Minor):** an exact phone match refuses people who share a household or office number. → **Mitigation:** the assumption is flagged for confirmation, and the 409 names the phone so the person knows why.
- **Risk (Minor):** register latency adds the MX lookup (up to 2 s), advice (up to 4 s), and the BigQuery script. → **Mitigation:** fixed budgets, a progress state on the submit button, and the p95 from the platform check.
- **Risk (Minor):** rotating the PII hash key breaks tax-ID matching on stored rows. → **Mitigation:** `hash_key_version` on every row; multi-version matching waits in Left unbuilt.
- **Risk (Minor):** some ADK details are unverified: per-turn `state_delta`, the event shape, and the Vertex AI environment variable. → **Mitigation:** the ADK step settles each against the pinned version, and the fake runner yields real ADK events.
- **Risk (Minor):** the disposable list goes stale. → **Mitigation:** the refresh script and the fetch date in the file header.
- **Rollback:**
  - Before deployment, revert the feature branch.
  - After deployment, roll each Cloud Run service back to its previous revision.
  - `ADVISOR_ENABLED=false` removes model calls from register, validate, and check-duplicate and leaves every status unchanged. `ASSISTANT_ENABLED=false` makes chat return 503, and the UI hides the panel.
  - The schema only adds objects. Customer rows created by a bad release are written by DML, so a DML `DELETE` can remove them at once.

## Out of scope

- Inbox confirmation, a staff review dashboard, a merge workflow, and sign-in.
- The policy PDFs in `files/` and any retrieval corpus.
- Endpoints that read, update, or delete a customer, including data-subject requests.
- Deploying to Cloud Run and the infrastructure listed under Dependencies. The review report gives recommendations only.
- A calibrated record-linkage model and labeled training data.
- Choosing the disposable-list source, tax-ID formats, address collection, rate-limit and bot-check providers, the Gemini model id, the Next.js major, the fallback data policy, and audit retention, which are the open questions.
