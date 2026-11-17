# Technical design: customer registration

**Status:** Draft • **Last updated:** 2026-11-16 • **Source plan:** `.axis/plans/customer-registration-api.md`

## Summary

The customer registration system accepts signups from a public Next.js form and a conversational assistant, and stores each customer in BigQuery. Deterministic code decides every outcome. A request returns 201 Created, 409 Conflict when the email, phone, or tax ID already belongs to a customer, or 422 when the input or email is invalid. Gemini adds typo suggestions and likely-duplicate warnings to those answers and never changes a status code.

A single FastAPI service holds the validation rules, the duplicate detection, the registration transaction, a Gemini advisor, and an ADK assistant. Uniqueness comes from one BigQuery multi-statement transaction. The transaction takes a table lock and then runs an insert-only `MERGE` keyed on email, phone, and a hash of the tax ID. A customer exists as soon as that transaction commits. The system sends no inbox confirmation.

## Goals and non-goals

**Goals**

- Return 201, 409, or 422 from deterministic checks, so the same input always produces the same status.
- Reject malformed, disposable, and undeliverable emails before any write.
- Keep email, phone, and tax ID unique across `customer_ops.customers` under concurrent registrations.
- Make register idempotent through an `Idempotency-Key` header.
- Warn about likely typos and likely duplicates without blocking the registration.
- Let the assistant explain results and register the person only after an explicit confirmation click.
- Run the full test suite offline, with no GCP credentials and no network.

**Non-goals**

- Inbox confirmation, sign-in, a staff review dashboard, and a merge workflow for duplicates.
- Endpoints that read, update, or delete a customer, including data-subject requests.
- A calibrated record-linkage model.
- Provisioning the GCP project, IAM, and Cloud Run services. This document records the target deployment, and the infrastructure lives outside this repository.
- The policy PDFs in `files/` and any retrieval corpus.

## Context and constraints

Customer reporting already lives in BigQuery, so the registration store is the BigQuery dataset `customer_ops`. BigQuery declares keys only as `NOT ENFORCED`, so the application has to enforce uniqueness itself. The design rests on the following platform behavior, checked against Google's documentation on 2026-11-16:

- A multi-statement transaction that mutates a table takes a table-level lock. Conflicting transactions are not queued. The loser fails at once with "Transaction is aborted due to concurrent update against table", and Google advises waiting at least 60 seconds before retrying.
- Opening a transaction with `DELETE FROM <table> WHERE FALSE` makes every other mutating transaction on that table conflict.
- An insert-only `MERGE` does not conflict with concurrent DML, and it matches against the table state at statement start. Two concurrent insert-only `MERGE` statements can both insert the same key.
- Rows written by streaming inserts cannot be changed by DML for 30 minutes, and DML inside a transaction against recently streamed rows is unsupported.
- Query parameters use `@name`, cannot name tables, and cannot be NULL.

The design holds these constraints:

- Only deterministic code sets 201, 409, or 422. A model failure, timeout, or invalid output removes the advisory and leaves the status unchanged.
- Customer rows are written only by DML query jobs. No code path uses streaming inserts, so the transaction lock covers every write.
- Every request value reaches BigQuery as a query parameter. Project and dataset names come from validated configuration.
- No model call receives a tax ID or a full phone number. Typo advice sends the email domain only.
- The public API never returns another customer's data.
- Names, emails, phone numbers, tax IDs, addresses, client IPs, and chat text never appear in logs, metric labels, or error bodies.
- `app/domain` imports neither FastAPI nor the BigQuery client. Each route calls one service method, and the service owns the transaction.

Several assumptions await confirmation. The dataset is `customer_ops` and the table is `customers`. An exact phone match blocks registration. Customers are individuals or businesses. Gemini runs on Vertex AI in the same project as BigQuery, in a region inside the dataset's location.

## Architecture overview

The architecture diagram lives at `.axis/diagrams/customer-registration-architecture.drawio`, with a Mermaid copy at `.axis/diagrams/customer-registration-architecture.mmd`.

The system has two deployable services and two Google Cloud backends.

| Component | Runs on | Responsibility |
| --- | --- | --- |
| UI (`ui/`) | Cloud Run, service account `registration-ui` | Next.js page with the registration form and the assistant panel. Calls the API directly from the browser. |
| API (`app/`) | Cloud Run, service account `registration-api` | FastAPI routes, validation, duplicate detection, the registration transaction, the Gemini advisor, and the ADK assistant |
| BigQuery dataset `customer_ops` | Google Cloud | The `customers` table and the `registration_audit_logs` table |
| Vertex AI | Google Cloud | Gemini models for typo advice, duplicate adjudication, and the assistant |

The browser calls the API across origins, and CORS admits only configured origins. The UI holds no data roles. Inside the API, the code is layered:

| Layer | Path | Contents |
| --- | --- | --- |
| API | `app/api/` | Routes, problem+json mapping, dependencies, health probes |
| Wire models | `app/models/schemas.py` | Pydantic v2 request and response models |
| Domain | `app/domain/` | Pure normalization, email rules, matching, typed errors |
| Services | `app/services/` | Email validation, duplicate detection, registration, advisor, repositories, rate limiting, bot check, PII hashing |
| Agent | `app/agents/registration_agent.py` | ADK `LlmAgent`, its three tools, and the runner wrapper |
| SQL | `sql/` | DDL, the registration transaction, query templates, and the duplicate-keys check |

The register path runs in this order:

1. Pydantic validates the request body.
2. The per-client rate limiter and the bot verifier run.
3. Normalization builds canonical email, phone, tax ID, name, and address values.
4. The email rules check the disposable list and the MX records.
5. Typo advice and likely-duplicate advice run concurrently under one 4-second budget.
6. The BigQuery transaction checks the idempotency key and runs the `MERGE`.
7. The transaction outcome maps to 201, 409, or 422, and an audit row records it.

## Component design

### API

FastAPI serves four operations under `/api/v1` plus two health probes. Each handler receives its service through `Depends` and calls one method. A central handler in `app/api/problems.py` maps each typed domain error to its problem type. It also replaces FastAPI's default validation handler, so a malformed body returns 422 `validation-error` as problem+json. Any other exception returns a generic 500.

Middleware assigns a request id, writes one access log line, and applies CORS. The CORS policy reads `allow_origins` from `CORS_ALLOW_ORIGINS` and sets `allow_credentials=False`. It allows `GET`, `POST`, and `OPTIONS`, accepts the `Content-Type`, `Idempotency-Key`, and `X-Request-Id` request headers, and exposes `X-Request-Id`, `Retry-After`, and `Idempotent-Replayed`. The service refuses to boot with an empty or wildcard origin list.

Configuration comes from `pydantic-settings` in `app/config.py`. Boot also refuses a missing GCP project when the store is BigQuery, an invalid project or dataset name, and the in-memory store or stub bot verifier without `ALLOW_LOCAL_ADAPTERS=true`.

### Validation pipeline

Normalization in `app/domain/normalize.py` is pure and idempotent.

- **Email.** email-validator checks syntax with deliverability off. The address is trimmed and lowercased, and the domain is IDNA-encoded.
- **Phone.** `phonenumbers` converts the value to E.164, with the address country as the default region.
- **Tax ID.** Spaces and dashes are removed, the value is uppercased, and it must match its type's pattern. The supported types are `us_ein` (9 digits), `gb_vat` (`GB` plus 9 or 12 digits), `in_pan` (5 letters, 4 digits, 1 letter), and `other` (4 to 30 letters and digits).
- **Name.** Normalization removes accents with NFKD, casefolds, and strips punctuation. Business names also lose legal suffixes such as `inc`, `llc`, `ltd`, and `gmbh`. The result is `normalized_name`, and its tokens sorted alphabetically form `name_key`, which matches swapped name order.
- **Address.** The optional address yields `normalized_address` for fuzzy matching.

`EmailValidationService` then applies the email rules in order:

1. **Syntax.** A failure returns `email-invalid`.
2. **Disposable list.** The domain and each parent domain are checked against `app/data/disposable_domains.txt`, loaded once into a frozenset. A hit returns `email-disposable`. `scripts/refresh_disposable_domains.py` rewrites the file from its configured source.
3. **MX lookup.** `dns.asyncresolver` looks for MX records, then A or AAAA records as the implicit MX, within 2 seconds. NXDOMAIN or no records returns `email-domain-undeliverable`. A timeout or SERVFAIL records `mx_status = unknown`, and registration continues.
4. **Typo rules.** A domain outside `free_mail_domains.txt` within Damerau-Levenshtein distance 2 of a domain inside it gets a suggestion. A known TLD slip such as `.con` or `.cmo` also gets one. These suggestions carry `source = rules`, and `gmial.com` becomes `gmail.com` with no model call.
5. **Typo model.** When the rules find nothing, the advisor sends the domain alone to Gemini. Code accepts the suggestion only when it differs from the input, is a free-mail domain or passes MX, and carries confidence of at least 0.7. The warning then carries `source = model`.

A typo suggestion is advice. An email that passes syntax, the disposable list, and MX registers with a `possible_typo` warning attached. The vendored disposable list includes some typo domains, `gmial.com` among them. An address on such a domain gets 422 `email-disposable`, with the typo suggestion attached to the problem.

### Duplicate detection

Exact matching and likely-duplicate detection are separate mechanisms.

**Exact keys.** Email, E.164 phone, and tax-ID hash are the exact-match keys. On register, the `MERGE` inside the locked transaction is the only authority. On check-duplicate, `find_exact_matches.sql` reports which keys already exist, without a lock.

**Likely duplicates.** `DuplicateDetectionService` follows a normalize, block, score, adjudicate sequence:

1. **Blocking.** `find_fuzzy_candidates.sql` returns up to 50 rows that share `normalized_name` or `name_key`, or share postal code and country, or, for businesses, share a business email domain. Free-mail domains are excluded from that last test.
2. **Pre-score.** rapidfuzz builds a comparison vector per candidate. The vector holds name similarity (`token_sort_ratio`), address similarity (`token_set_ratio`), same postal code, same business domain, and email local-part similarity.
3. **Selection.** A candidate goes to the model when name similarity is at least 0.80. It also qualifies at 0.60 or above together with a shared postal code, a shared business domain, or address similarity of at least 0.85. The top five by name similarity go forward. Every threshold is configuration and is an uncalibrated default.
4. **Adjudication.** Gemini receives the applicant and up to five candidates under the opaque references `c1` to `c5`. Each candidate carries customer type, normalized name, company name, city, postal code, country, and business email domain. The model never sees a phone, tax ID, email local part, or customer id. It returns a verdict of `likely_same`, `possibly_same`, or `different` per reference, with a confidence and reason codes.
5. **Output validation.** Every reference must be one that was sent, every verdict and reason must belong to its enum, and confidence must fall between 0 and 1. Any failure marks the advisory `unavailable`.
6. **Warning.** A `possible_duplicate` warning appears when a verdict is `likely_same` or `possibly_same` with confidence of at least 0.60. It carries the highest confidence and up to three reason codes. The audit row records the candidate customer ids, and the response never does.

### Gemini advisor

`GeminiAdvisor` in `app/services/advisor.py` makes single structured calls through `google-genai` on Vertex AI. It exposes `suggest_domain(domain)` and `assess_candidates(applicant, candidates)`. Each prompt has role, context, task, format, and constraint sections. Applicant and candidate values sit in a delimited section marked as untrusted input. Responses use the Pydantic model as the response schema and parse with `model_validate_json`. Calls set no sampling parameters, because the successor models removed some of them. Each call has its own timeout inside the 4-second advisory budget.

`DisabledAdvisor` serves `ADVISOR_ENABLED=false` and reports `advisory_status = disabled`. The advisor runs as a single call because each task is one prompt with one structured output, which needs no agent loop.

### ADK assistant and tools

The assistant is one ADK `LlmAgent` named `registration_assistant`. Its model comes from `GEMINI_ASSISTANT_MODEL`, and `output_schema=AssistantTurn` constrains its final response to a message and suggested actions. The instruction gives the agent its role as the signup assistant for this form. The context section holds a redacted form snapshot and the last result, marked untrusted, with the tax ID and phone reduced to type and last four characters. The agent explains validation problems, conflicts, and warnings, helps fix fields, and offers registration. It may say a registration happened only when the register tool returned `created` in the same turn.

The agent has three function tools. Each takes its schema from type hints and its docstring.

| Tool | Parameters the model sees | Behavior |
| --- | --- | --- |
| `validate_email_tool` | `email: str` | Calls `EmailValidationService.validate` and returns the result |
| `detect_duplicate_customer_tool` | `include_likely_duplicates: bool` | Reads the form snapshot from session state, calls `DuplicateDetectionService.check`, and returns matched field names and the warning |
| `register_customer_bq_tool` | none | Reads the snapshot and the confirmed fingerprint from session state, then calls `RegistrationService.register` with channel `assistant` |

The register tool takes no customer fields from the model, so a hallucinated or injected call cannot register invented data. Code enforces these guardrails:

- The API sets `registration_confirmed` and `confirmed_fingerprint` in session state only for a request with `action = confirm_registration`. It clears both after the turn.
- The register tool returns `needs_confirmation` unless confirmation is set for this turn and the snapshot's fingerprint equals the confirmed one.
- The tool derives its idempotency key from the session and the fingerprint, so a repeated confirmation replays the same customer.
- `before_model_callback` refuses a turn past 30 per session or a prompt above the configured size.
- `before_tool_callback` caps tool calls at four per turn and checks the confirmation flag again before the register tool runs.
- `AssistantReply.registration` is copied from the tool's stored outcome, so the UI shows registration status from code and never from model prose.

A `Runner` with `InMemorySessionService` runs each turn under a 20-second budget. A janitor task deletes sessions idle for 30 minutes and caps the store at 1,000 sessions.

An optional fallback runs the same turn on GPT-4o through ADK's `LiteLlm` wrapper when the Gemini call fails with a transient error or times out. ADK has no fallback chain, so the wrapper in `registration_agent.py` owns the switch. The fallback is off by default and needs `LLM_FALLBACK_MODEL` and an OpenAI key. It never performs duplicate adjudication. `AssistantReply.used_fallback` and the log line record which model answered.

### BigQuery data layer

`app/services/ports.py` declares the `CustomerRepository` protocol with `register`, `find_exact_matches`, `find_fuzzy_candidates`, and `record_attempt`. Two implementations exist:

- **`BigQueryCustomerRepository`** loads SQL templates from `sql/`, substitutes the validated project and dataset names, and sends every value as a `ScalarQueryParameter` or `ArrayQueryParameter`. Absent optional values travel as `''` or `-1.0`, because parameters cannot be NULL. Jobs run through `asyncio.to_thread` with a per-job timeout and carry the labels `app=registration-api` and `operation=<name>`. The repository raises `LockConflict` on the concurrent-update abort.
- **`InMemoryCustomerRepository`** serializes `register` behind one `asyncio.Lock`. It serves local development and the real-backend browser journey, and it loads only with `ALLOW_LOCAL_ADAPTERS=true`.

`RegistrationService.register` owns the transaction call and the retry loop described under Reliability and concurrency.

### UI

The UI is a Next.js 15 App Router application with React 19, strict TypeScript, Tailwind CSS v4, shadcn/ui, and Lucide icons. Forms use react-hook-form with `zodResolver` and the shadcn `Field` components. TanStack Query runs the mutations. The typed API client in `ui/lib/api.ts` uses `openapi-fetch` with types generated from the OpenAPI file by `openapi-typescript`.

- **Runtime configuration.** `ui/app/layout.tsx` renders dynamically and reads `API_BASE_URL` at request time, so one build serves every environment.
- **Theme.** A neutral palette with one blue accent on `--primary` and `--ring`. Light and dark themes override the same CSS tokens through `next-themes` with `attribute="class"`. Text contrast meets 4.5:1 and focus rings and borders meet 3:1 in both themes.
- **Layout.** From the `lg` breakpoint up, the form sits on the left and a sticky 24rem assistant panel on the right. Below `lg`, the form is full width and a floating button opens the same panel in a bottom drawer.
- **Form.** Labels sit above fields, help text and errors sit under their control, and errors link through `aria-describedby`. Field groups cover customer, contact, and address. Paired fields use two columns from `md` up and stack below it.
- **Behavior.** The form calls validate when the email field loses focus and offers a "Did you mean" suggestion with a Use button. Submit sends one `Idempotency-Key` per form session. A 201 shows a success card with warnings. A 409 marks each matched field. A 422 maps `errors[].pointer` onto fields. A 429 shows the wait time, and a 503 offers a retry.
- **Assistant panel.** Messages render in a polite live region. Each turn sends the form snapshot and the last result. Confirm registration opens a dialog that names the consequence before it sends `action = confirm_registration`. The session id lives in `sessionStorage`.
- **Privacy notice.** A notice under the form states what is stored and that Gemini on Google Cloud checks for typos and possible duplicates. It also states that OpenAI is used only when the fallback is on.
- **Headers.** `next.config.ts` sets `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, and `X-Frame-Options: DENY`.

## API contract summary

The authoritative contract is `contracts/openapi.yaml`, an OpenAPI 3.1 file generated from the FastAPI app by `scripts/export_openapi.py` and committed. A contract test fails when the regenerated spec differs from the committed file, and Spectral lints it against `.spectral.yaml`.

| Operation | Statuses | Behavior |
| --- | --- | --- |
| `POST /api/v1/customers/register` | 201, 403, 409, 422, 429, 500, 503 | Body `CustomerInput` and an optional `Idempotency-Key` UUID header. 201 returns `RegistrationCreated` with `customer_id`, warnings, and `advisory_status`. 409 `customer-duplicate` carries `matched_on`. 503 `registration-busy` carries `Retry-After`. |
| `POST /api/v1/customers/validate` | 200, 422, 429, 500 | Body `{email}`. 200 carries the verdict for valid and invalid emails alike. 422 means only a malformed body. |
| `POST /api/v1/customers/check-duplicate` | 200, 403, 422, 429, 500 | Body `CustomerInput`. Writes no customer. 200 returns `exact_matches` and `possible_duplicate`, including when a match is found. |
| `POST /api/v1/agent/chat` | 200, 422, 429, 500, 503 | Body `ChatRequest`. 200 returns `AssistantReply`. 503 `assistant-unavailable` when the model fails and no fallback answers. |

The four status codes at the center of the contract mean the following on register:

| Status | Problem type | Meaning |
| --- | --- | --- |
| 201 | none | The customer was created, or an idempotent replay returned the original `customer_id` with `Idempotent-Replayed: true` |
| 409 | `customer-duplicate` | The email, phone, or tax ID already belongs to a customer. `matched_on` lists the matching fields from `email`, `phone`, and `tax_id`. |
| 422 | `email-invalid`, `email-disposable`, `email-domain-undeliverable`, `phone-invalid`, `tax-id-invalid`, `validation-error`, `idempotency-key-reused` | The input failed a deterministic rule, or the idempotency key was reused with a different body |
| 503 | `registration-busy` | The table lock stayed contended past the retry budget. `Retry-After: 60` is set. |

Every error body is RFC 9457 `application/problem+json`:

```json
{
  "type": "urn:smart-customer-onboarding:problem:customer-duplicate",
  "title": "Customer already registered",
  "status": 409,
  "detail": "The email address already belongs to a registered customer.",
  "instance": "/api/v1/customers/register",
  "request_id": "0193a6f2-6c1e-7b52-9d0a-2f4e8c1b7a90",
  "errors": [
    { "pointer": "/email", "code": "duplicate", "message": "Already registered to another customer." }
  ],
  "matched_on": ["email"]
}
```

`matched_on` and `suggestion` appear only where they apply. Every response echoes `X-Request-Id`. Every request model sets `extra="forbid"`.

Register returns 201 without a `Location` header. The API has no customer read endpoint, because one would expose personal data with no sign-in. The body carries `customer_id`, and the operation description records this choice. The liveness probe `/healthz/live` and the readiness probe `/healthz/ready` are excluded from the published spec.

## Data model

`sql/001_customer_ops_schema.sql` creates the dataset and both tables. `scripts/apply_schema.py` substitutes the project, dataset, and location from validated configuration. Every statement uses `IF NOT EXISTS`, so reapplying the schema changes nothing. The dataset and the customer table carry the label `data-classification=pii`.

### `customers`

One row per registered customer.

| Column group | Columns | Notes |
| --- | --- | --- |
| Identity | `customer_id`, `customer_type` | UUIDv7 generated by the API. `customer_id` is the `NOT ENFORCED` primary key. |
| Name | `given_name`, `family_name`, `company_name`, `normalized_name`, `name_key` | `normalized_name` holds the company name for businesses and the full name otherwise |
| Email | `email`, `email_as_entered`, `email_local_part`, `email_domain`, `mx_status` | `email` is canonical and unique. `mx_status` is `pass` or `unknown`. |
| Phone | `phone_e164` | E.164. Unique when present. |
| Tax ID | `tax_id_type`, `tax_id_hash`, `tax_id_last4`, `hash_key_version` | The raw tax ID is never stored. `tax_id_hash` is unique when present. |
| Address | `address` (STRUCT), `normalized_address` | Null when no address was given |
| Lineage | `source_channel`, `created_at`, `updated_at` | `source_channel` is `form`, `assistant`, or `api` |

The table is partitioned by `DATE(created_at)` and clustered by `email` and `normalized_name`. Clustering on `email` keeps the uniqueness and exact-match lookups cheap, since those lookups span every partition. The table does not set `require_partition_filter` for the same reason.

### `registration_audit_logs`

An append-only record of every register and check-duplicate call. It holds no raw email, phone, tax ID, or IP address. The table carries the label `data-classification=pii-pseudonymous`.

Columns record the request (`event_id`, `request_id`, `idempotency_key`, `request_fingerprint`, `channel`, `operation`), the result (`outcome`, `http_status`, `customer_id`, `matched_on`, `problem_codes`), the pseudonymous links (`email_hash`, `client_hash`), the advice (`mx_status`, `advisory_status`, `typo_suggested_domain`, `fuzzy_candidate_ids`, `fuzzy_max_confidence`, `advisory_model`), and performance (`lock_retries`, `latency_ms`, `created_at`). `outcome` is one of `created`, `replay`, `duplicate`, `invalid_email`, `invalid_input`, `rate_limited`, `bot_check_failed`, `busy`, `checked`, or `error`.

The table is partitioned by `DATE(created_at)` and clustered by `outcome` and `email_hash`. Partition expiration is unset until the retention period is decided.

### Registration transaction

`sql/register_customer.sql` is one multi-statement script:

1. `BEGIN TRANSACTION`.
2. `DELETE FROM customers WHERE FALSE` takes the table lock for the whole transaction. Any concurrent registration transaction now aborts.
3. A lookup in the audit table finds a `created` row with the same idempotency key from the last 24 hours. A match with the same request fingerprint sets the outcome to `replay`. A match with a different fingerprint sets `fingerprint_mismatch`. Either way the transaction rolls back.
4. Otherwise an insert-only `MERGE` inserts the customer when no row matches on email, on phone when present, or on tax-ID hash when present. The `MERGE` `ON` clause is the uniqueness rule.
5. When one row was inserted, the script writes the `created` audit row and commits.
6. When nothing was inserted, a follow-up query computes `matched_on` to explain the refusal, and the transaction rolls back. This query never decides the outcome.
7. A final `SELECT` returns the outcome, the customer id, and `matched_on`.

The service maps `created` to 201, `replay` to 201 with `Idempotent-Replayed: true`, `fingerprint_mismatch` to 422 `idempotency-key-reused`, and `duplicate` to 409. Every outcome other than `created` writes its audit row through a separate parameterized `INSERT` after the transaction.

The lock is needed because an insert-only `MERGE` alone lets two concurrent registrations of one email both insert. `sql/checks/duplicate_keys.sql` groups customers by each unique key and returns any key that two customers share. It returns zero rows while uniqueness holds and prints customer ids only, never key values.

### Hashing

Tax IDs, audit emails, and client IPs are hashed with HMAC-SHA256 under one key, `pii-hash-key`, with a domain prefix per kind (`tax_id:`, `email:`, `client:`). The prefix keeps a hash of one kind from matching a hash of another. Each customer row records `hash_key_version`. The customer row keeps the tax ID's last four characters for display. The request fingerprint for idempotency is an HMAC-SHA256 of the canonical request body under the same key. An unkeyed hash of so small an input space could be reversed by brute force from the audit table.

## Decision logic

Rules decide, and the model advises.

| Decision | Made by | Model involvement |
| --- | --- | --- |
| Body shape, phone, and tax-ID validity (422) | Pydantic and `app/domain/normalize.py` | None |
| Email syntax, disposable, undeliverable (422) | `EmailValidationService` | None |
| Exact duplicate (409) | The `MERGE` inside the locked transaction | None |
| Idempotent replay and key reuse | The transaction's audit lookup | None |
| Typo suggestion | Rules first, then Gemini for the domain only | Advisory warning on 201 or in validate |
| Likely duplicate | Blocking and rapidfuzz, then Gemini | Advisory warning on 201 or in check-duplicate |
| Assistant registration | The register tool, gated by the confirmation flag the API sets | The model may call the tool, and code decides whether it runs |

Every model failure degrades to no advisory:

| Failure | Result |
| --- | --- |
| Timeout past the 4-second budget | That half's warnings are dropped. `advisory_status = unavailable`. |
| API error or quota error | Same as timeout |
| Output that fails schema or reference validation | Same as timeout |
| Typo suggestion whose domain fails MX | The suggestion is discarded |
| `ADVISOR_ENABLED=false` | No model call. `advisory_status = disabled`. |
| Assistant model failure with no fallback | Chat returns 503 `assistant-unavailable`. The form and register route are unaffected. |
| `ASSISTANT_ENABLED=false` | Chat returns 503, and the UI hides the panel |

In each case the register status is the one the deterministic checks produce.

## Security and privacy

**Personal data.** The system stores names, email, phone, address, and a tax-ID hash with its last four characters. Logs carry none of these. structlog writes JSON through an allow-list processor that admits only `event`, `level`, `timestamp`, `request_id`, `route`, `status`, `outcome`, `duration_ms`, `problem_type`, `advisory_status`, `lock_retries`, `model`, `used_fallback`, and `error_type`. Uvicorn's access log is off. The ADK and google-genai loggers run at WARNING, and GenAI telemetry content capture is off. The audit table holds hashes in place of email and client IP.

**Data sent to models.** Gemini on Vertex AI receives the email domain for typo advice. For duplicate adjudication it receives applicant and candidate names, company names, city, postal code, country, and business email domain under opaque references. It never receives a phone, tax ID, email local part, or customer id. The assistant sees a redacted form snapshot. When the GPT-4o fallback is on, OpenAI receives chat messages and the redacted snapshot. The fallback ships switched off.

**Enumeration tradeoff.** The API tells a caller whether an email, phone, or tax ID is already registered, through 409 on register and `exact_matches` on check-duplicate. This lets the form show the exact problem at once. The product owner accepted this exposure for email. Phone and tax ID carry the same exposure because both are exact-match keys. Three controls slow probing without stopping it:

- Per-client sliding-window rate limits per operation. Register allows 5 and check-duplicate 10 per 10 minutes. Validate allows 30 per minute, and chat 20 per 10 minutes.
- A bot check on register and check-duplicate, through the `BotVerifier` port.
- `client_hash` in the audit table, which shows probing patterns without storing IP addresses.

The rate limiter reads the first `X-Forwarded-For` hop only when `TRUST_PROXY_HEADERS=true`, which Cloud Run sets. Otherwise it reads the socket peer. The shipped limiter is per instance. The shipped bot verifier is a stub that accepts the token `local` and loads only with `ALLOW_LOCAL_ADAPTERS=true`. Production needs a real provider for both.

**SQL injection.** SQL templates load from files. The project name must match `^[a-z][a-z0-9-]{4,28}[a-z0-9]$` and the dataset name `^[A-Za-z0-9_]{1,1024}$` before substitution. Every value travels as a query parameter, and a unit test proves that a hostile name appears only in a parameter.

**Prompt injection.** Form values and chat text sit in delimited sections marked untrusted. Outputs are schema-validated. The register tool takes no data from the model, only the API sets confirmation, the UI shows status from tool results, and tool calls are capped per turn.

**IAM.**

| Identity | Roles |
| --- | --- |
| `registration-api` | `roles/bigquery.dataEditor` on the `customer_ops` dataset only, `roles/bigquery.jobUser` on the project, `roles/aiplatform.user` on the project, `roles/secretmanager.secretAccessor` on its own secrets |
| `registration-ui` | No data roles |

Neither service runs as the default compute service account. `roles/bigquery.dataEditor` also allows deleting tables. A custom role with `bigquery.tables.get`, `bigquery.tables.getData`, and `bigquery.tables.updateData` would narrow it.

**Secrets.** `pii-hash-key`, the bot-check secret, and the OpenAI key (only with the fallback on) live in Secret Manager. Cloud Run mounts them as files, and `pydantic-settings` reads them as `SecretStr` from the secrets directory.

## Reliability and concurrency

**Uniqueness under concurrency.** The lock statement makes one registration transaction run at a time on `customers`. A concurrent transaction aborts at once with the concurrent-update error, and the repository raises `LockConflict`. A unit test asserts that the lock `DELETE` follows `BEGIN TRANSACTION` and precedes the `MERGE`.

**Retries.** `RegistrationService` retries a `LockConflict` up to three times with full-jitter backoff starting at 500 ms, within 10 seconds in total. After that it returns 503 `registration-busy` with `Retry-After: 60`, following Google's 60-second retry guidance. The idempotency key makes the client's retry safe. A retried request that already committed returns the original `customer_id`.

**Budgets.**

| Call | Budget | On expiry |
| --- | --- | --- |
| MX lookup | 2 s | `mx_status = unknown`, registration continues |
| Advisory (typo and duplicate together) | 4 s | No advisory |
| Lock retries | 10 s | 503 `registration-busy` |
| Chat turn | 20 s | 503 `assistant-unavailable`, or the fallback answers when configured |

The BigQuery client is synchronous, so jobs run in worker threads through `asyncio.to_thread`.

**Health.** `/healthz/live` always returns 200. `/healthz/ready` reads the dataset metadata, caches the result for 30 seconds, and returns 503 while the app drains on shutdown.

**Kill switches.** `ADVISOR_ENABLED=false` removes every model call from register, validate, and check-duplicate and leaves every status unchanged. `ASSISTANT_ENABLED=false` turns off chat.

**Single-instance state.** Assistant sessions and rate-limit windows live in one instance's memory. A conversation that lands on another instance starts a new session, and limits apply per instance.

## Observability

- **Request tracing.** Middleware assigns or accepts `X-Request-Id`, echoes it on every response, and includes it in every log line and problem body.
- **Logs.** One JSON access line per request carries method, route template, status, and duration. Service logs carry `outcome`, `problem_type`, `advisory_status`, `lock_retries`, `model`, and `used_fallback` through the allow-list.
- **Audit table.** `registration_audit_logs` is the record for reporting and investigation. It shows outcome counts, lock retries, latency, advisory availability, which model advised, likely-duplicate candidates, and probing by `client_hash`.
- **BigQuery job labels.** Every job carries `app=registration-api` and `operation=<name>`, so job history and cost attribute to the operation.
- **Data integrity check.** `sql/checks/duplicate_keys.sql` returns zero rows while uniqueness holds and can run on a schedule.

Signals to watch in production: the share of registrations with `lock_retries > 0`, the 503 `registration-busy` rate, the share of `advisory_status = unavailable`, register p95 latency, and unresolved likely-duplicate warnings.

## Testing strategy

The default suite runs with no GCP credentials and no network. `make test` runs it, and CI runs it on every push.

| Layer | Location | Covers |
| --- | --- | --- |
| Domain unit tests | `tests/unit/test_normalize.py`, `test_email_rules.py`, `test_matching.py` | Canonical forms, name keys, E.164, tax-ID patterns, disposable parent domains, typo rules. Hypothesis checks that normalization is idempotent and `name_key` ignores token order. |
| SQL template tests | `tests/unit/test_sql_templates.py` | Identifier validation, no format placeholders, parameter names matching the builder, and the position of the lock statement |
| Repository tests | `tests/unit/test_bq_repository.py`, `test_memory_repository.py` | Every value as a parameter, the injection case, `LockConflict` mapping, outcome mapping, and 20 concurrent in-memory registrations yielding one customer |
| Service tests | `tests/unit/test_email_validation.py`, `test_advisor.py`, `test_duplicate_detection.py`, `test_registration_service.py` | Each check's problem code, advisor validation and failure modes, the data minimization in captured prompts, retry and busy behavior, rate-limit windows |
| Agent tool tests | `tests/unit/test_agent_tools.py` | The confirmation gate, replay on repeated confirm, tool outputs free of other customers' data, and exactly three tools with the expected parameters |
| API suite | `tests/test_registration.py` | Every status through `httpx` against `create_app()`, idempotency, rate limits, the confirm-only registration in chat, fallback, CORS, and a check that no log line contains submitted personal data |
| Contract | `tests/test_contract.py` | Spec drift, `ProblemDetails` on every error, descriptions on every property, and the documented statuses |
| UI unit tests | `ui/` with Vitest and Testing Library | Field errors and their ARIA links, 409 and 422 mapping, the suggestion Use button, the confirm dialog, status taken from the `registration` field |
| Browser journeys | `ui/tests/e2e/` with Playwright | Route-mocked 201, 409, 422, 503, and the confirm flow, one journey against the in-memory backend, layout at 390px and 1280px, axe in both themes, keyboard-only completion |
| Platform check | `tests/integration/`, run by `make integration` | Against a dev project: the DDL, 20 trials of 5 concurrent registrations with and without the lock, retry timing, the script shape, transaction latency, and one structured call to each configured Gemini model |

Test fakes in `tests/fakes.py` include an autospec BigQuery client, a scripted advisor with failure modes, a fake MX resolver, a frozen clock, a fixed id generator, and a fake ADK runner that yields real ADK `Event` objects.

## Deployment

Both services run on Cloud Run.

- **API image.** A multi-stage uv build runs `uvicorn app.main:create_app --factory` on `PORT` as a non-root user, under the `registration-api` service account.
- **UI image.** Next.js standalone output runs as a non-root user, under the `registration-ui` service account, with `API_BASE_URL` set per environment.
- **Configuration.** Secrets mount from Secret Manager as volumes. `TRUST_PROXY_HEADERS=true`, `CORS_ALLOW_ORIGINS` lists the UI origin, and `ALLOW_LOCAL_ADAPTERS` stays unset.
- **Instances.** Max instances and per-instance concurrency are set against lock contention. Session affinity keeps a conversation on one instance while sessions live in memory.
- **Timeouts and probes.** The request timeout exceeds the 20-second chat budget. Startup and liveness probes use the health endpoints.
- **Edge.** Cloud Armor rate limiting at the load balancer backs up the per-instance limiter.
- **Region.** The Vertex AI region sits inside the dataset's location, and the model id is pinned in configuration.

Local development runs `docker-compose.yml` or `make dev`, with the API on the in-memory store and `ALLOW_LOCAL_ADAPTERS=true`.

Rollback uses Cloud Run revisions. The schema only adds objects. Customer rows written by a bad release came from DML, so a DML `DELETE` can remove them at once.

## Alternatives considered

| Criterion | A: rules decide, model advises (chosen) | B: the ADK agent decides | C: chat first, form as fallback |
| --- | --- | --- | --- |
| Who sets 201, 409, or 422 | Deterministic checks and the BigQuery transaction | The model, through tool calls | The model, through conversation |
| Model failure or timeout | Registration proceeds with no advisory | Registration fails or stalls | Onboarding stops |
| Same input twice | Same status | Can differ between runs | Can differ between runs |
| Offline testing | Unit and API tests with fakes | Model mocks for every outcome | Scripted conversations |
| Contract | Fixed operations with fixed outcomes | Fixed operations with model-chosen outcomes | No predictable contract |

Approach B was rejected because model mistakes would reach customers and outcomes would differ between runs. Approach C was rejected because it has no predictable contract and is the hardest to test offline.

Narrower alternatives inside approach A:

- **A bare `MERGE` for uniqueness.** Two concurrent insert-only `MERGE` statements can both insert one email. The lock statement closes that gap.
- **ADK `BigQueryToolset`.** Its `execute_sql` tool runs SQL the model writes, and its support for query parameters is unconfirmed. Custom tools call the same service methods as the REST routes.
- **Every model call through ADK.** Typo advice and duplicate adjudication are one prompt and one structured output each, so they call `google-genai` directly. ADK runs only the conversational assistant.
- **A Next.js proxy in front of the API.** It would remove CORS, but it would hide the client IP that rate limiting needs and add a network hop.
- **A transactional store such as Firestore, Spanner, or Cloud SQL owning uniqueness.** It becomes worth building if lock conflicts exceed 1% of registrations or register p95 passes 8 seconds.

## Risks and open questions

### Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Gemini 2.5 Flash and Pro are deprecated. The Gemini API limits them to existing users and routes requests to successors from 2026-12-01. Vertex AI listed their retirement for 2026-10-20, and whether the endpoints still answer is unverified. Successor models change function calling, thinking controls, and sampling parameters. | Blocker | Model ids are configuration. The platform check calls each one. Calls set no sampling parameters. No status code depends on a model. |
| Next.js 15 is in maintenance support and receives security releases only through 2027-01-31 | Major | Pin the latest 15.x, avoid APIs that changed in 16, and settle the major version before production |
| The `MERGE` concurrency design is unproven against live BigQuery until the platform check runs. The 60-second retry guidance may make 10-second retries fail under contention. | Major | The lock statement opens every transaction, and a unit test checks its position. The platform check measures inserts, aborts, and retry success. More than 5% retry failures reopens the transactional-store decision. |
| `PARTITION BY DATE(created_at)` on a TIMESTAMP column is unverified | Minor | The platform check applies the DDL |
| Every registration takes the table lock | Major | Jittered retries, 503 with `Retry-After`, idempotent client retries |
| Register and check-duplicate reveal whether an email, phone, or tax ID is registered | Major | Rate limits, the bot check, and `client_hash` in the audit table. A production limiter and bot provider are still to be chosen. |
| Personal data reaches model providers | Major | Field minimization, opaque references, fallback off by default and excluded from matching, privacy notice |
| Prompt injection through chat or form fields | Major | Untrusted data sections, schema-validated output, a register tool that takes no model data, the API-set confirmation flag, the tool-call cap |
| Sessions and rate limits live in one instance's memory | Minor | Session affinity and an instance cap. Shared storage becomes necessary when the API runs several instances. |
| Daily partitions on a small table create many tiny partitions | Minor | Review partition sizes and switch to monthly partitions if they stay small |
| An exact phone match refuses people who share a household or office number | Minor | The 409 names the phone. The rule awaits confirmation. |
| Register latency adds MX (up to 2 s), advice (up to 4 s), and the transaction | Minor | Fixed budgets and a progress state on the submit button |
| Rotating the PII hash key breaks tax-ID matching on stored rows | Minor | `hash_key_version` on every row. Matching across key versions is unbuilt. |
| Some ADK details are unverified: per-turn `state_delta`, the event shape, and the Vertex AI environment variable | Minor | Settled against the pinned ADK version. The fake runner yields real ADK events. |
| The disposable list goes stale | Minor | The refresh script and the fetch date in the file header |
| LiteLLM 1.82.7 and 1.82.8 contained unauthorized code | Minor | The optional `fallback` extra pins `litellm>=1.84,<1.106.3` |

### Open questions

1. **Disposable list source.** Which source feeds the disposable-domain list? The current build vendors a public list and refreshes it by script.
2. **Tax-ID formats.** Which government and tax-ID formats are validated, and does reporting need the raw value? The current build validates four types and stores a keyed hash plus the last four characters.
3. **Address collection.** Is a postal address collected? The current build collects an optional address for likely-duplicate matching.
4. **Abuse providers.** Which providers serve rate limiting and the bot check? The current build ships a per-instance limiter and a stub verifier limited to local configuration.
5. **Gemini model.** Which model ids to pin, given the 2.5 deprecation? Can the dev project still call 2.5, and if not, which successor?
6. **Next.js major.** Next.js 15 or 16? Version 16 is recommended if the brief allows it.
7. **Fallback data.** May a registrant's chat messages and form values go to OpenAI when the GPT-4o fallback is on? The fallback ships switched off.
8. **Audit retention.** How long are audit rows kept? The audit table needs a partition expiration.
9. **Shared phone numbers.** Should an exact phone match block registration?
