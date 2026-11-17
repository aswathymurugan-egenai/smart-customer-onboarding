# smart-customer-onboarding

A signup API, a Next.js form, and a conversational assistant that register customers in BigQuery. Deterministic checks decide every outcome: 201 when the customer is created, 409 when an existing customer already owns the email, phone number, or tax ID, and 422 when the input is invalid. Gemini adds typo suggestions and likely-duplicate warnings and never decides a status code.

## What the service does

| Operation | Result |
| --- | --- |
| `POST /api/v1/customers/register` | 201 with the new customer id and any warnings. 409 names which of `email`, `phone`, and `tax_id` matched. 422 puts the error under the field it concerns. 429 and 503 carry `Retry-After`. |
| `POST /api/v1/customers/validate` | 200 with a verdict for the email, an invalid one included. |
| `POST /api/v1/customers/check-duplicate` | 200 with the matched keys and a likely-duplicate warning. Writes no customer. |
| `POST /api/v1/agent/chat` | One turn with the assistant. It registers the person only when the request carries `action = confirm_registration`. |

Every error is `application/problem+json` (RFC 9457) with a stable `type` URI, and every response echoes `X-Request-Id`. The contract lives in `contracts/openapi.yaml` and is generated from the code. `make spec` regenerates it and the UI's typed client, and a test fails when the committed file drifts from the code.

A 201 has no `Location` header. The API exposes no customer read endpoint, because one would expose personal data with no sign-in. The body carries the customer id instead.

## Run it locally

You need Python 3.14 (or 3.11 and later), [uv](https://docs.astral.sh/uv/), and Node 24.

```
make dev     # API on :8000 with the in-memory store, and the UI on :3000
make test    # the offline suite: no credentials, no network
make lint    # ruff, ruff format --check, and mypy --strict
make ui-test # eslint, tsc, and Vitest
make e2e     # Playwright journeys; E2E_REAL_BACKEND=1 adds the real-backend journey
```

`make dev` uses the in-memory store and the local adapters, so it needs no GCP project. Gemini runs on Vertex AI, so the advisor and the assistant stay off unless you export `GCP_PROJECT`, authenticate with application default credentials, and run `ADVISOR_ENABLED=true ASSISTANT_ENABLED=true make dev`. The UI hides the assistant panel while `ASSISTANT_ENABLED` is `false`.

`uv` pins Python 3.14 in `.python-version` so `uuid.uuid7()` comes from the standard library. The code falls back to a small UUIDv7 implementation on 3.11 to 3.13.

## How a registration stays unique

BigQuery key constraints exist only as `NOT ENFORCED`, and two concurrent insert-only `MERGE` statements each read the table as it was when they started. Both can insert the same email. `sql/register_customer.sql` therefore opens its transaction with `DELETE FROM customers WHERE FALSE`. That statement takes the table lock, so a concurrent registration aborts at once with "Transaction is aborted due to concurrent update". The service retries with full-jitter backoff for up to 10 seconds, and then answers 503 with `Retry-After: 60`. An `Idempotency-Key` makes the client's retry safe.

Customer rows are written only by DML query jobs, never by streaming inserts, because streamed rows cannot be changed by DML for 30 minutes and would escape the lock. `sql/checks/duplicate_keys.sql` must return zero rows while the rule holds.

The transaction design is unproven against real BigQuery. The platform check below is blocked until a dev project is available.

## Configuration

The API reads its settings from the environment, a `.env` file, and a mounted secrets directory (`SECRETS_DIR`, default `/run/secrets`, one file per secret named like the setting in lower case). It refuses to boot on a missing or malformed value. Secrets are `SecretStr` values and never appear in logs or in the settings `repr`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `GCP_PROJECT` | none | GCP project for BigQuery and Vertex AI. Required for the BigQuery store and while either model switch is on. |
| `BQ_DATASET` | `customer_ops` | BigQuery dataset that holds the customer tables. |
| `BQ_LOCATION` | `US` | Dataset location. |
| `GENAI_LOCATION` | `us-central1` | Vertex AI region. It must sit inside the dataset's location. |
| `CUSTOMER_STORE` | `bigquery` | `bigquery`, or `memory` for local work. |
| `BQ_JOB_TIMEOUT_SECONDS` | `30.0` | Timeout for each BigQuery job. |
| `ALLOW_LOCAL_ADAPTERS` | `false` | Permits the memory store, the stub bot verifier, and reserved email domains. Deployed configuration never sets it. |
| `BOT_CHECK_PROVIDER` | `stub` | The bot verifier. Only the local `stub` exists. |
| `EMAIL_ALLOW_RESERVED_DOMAINS` | `false` | Accepts names such as `example.test`, for fictional data. |
| `CORS_ALLOW_ORIGINS` | none | Comma-separated exact origins. A wildcard or an empty list refuses to boot. |
| `TRUST_PROXY_HEADERS` | `false` | Read the first `X-Forwarded-For` hop as the client address. Set it behind Cloud Run. |
| `GEMINI_ADVISOR_MODEL` | `gemini-2.5-flash` | Model id for typo and likely-duplicate advice. |
| `GEMINI_ASSISTANT_MODEL` | `gemini-2.5-flash` | Model id for the assistant. |
| `ADVISOR_ENABLED` | `true` | Kill switch for model advice. Off removes model calls and leaves every status unchanged. |
| `ASSISTANT_ENABLED` | `true` | Kill switch for the assistant. Off makes chat return 503. |
| `LLM_FALLBACK_MODEL` | none | Fallback model for assistant turns, such as `openai/gpt-4o`. Needs `OPENAI_API_KEY` and `uv sync --extra fallback`. Off when empty. |
| `MX_TIMEOUT_SECONDS` | `2.0` | Lifetime of each MX lookup. |
| `ADVISORY_BUDGET_SECONDS` | `4.0` | Total budget for typo and duplicate advice on one request. |
| `CHAT_BUDGET_SECONDS` | `20.0` | Budget for one assistant turn. |
| `LOCK_RETRY_BUDGET_SECONDS` | `10.0` | Total time a registration waits on table-lock conflicts. |
| `LOCK_RETRY_BASE_SECONDS` | `0.5` | First full-jitter backoff ceiling. It doubles on each retry. |
| `LOCK_RETRY_MAX_ATTEMPTS` | `3` | Retries after a lock conflict before answering 503. |
| `LOCK_RETRY_AFTER_SECONDS` | `60` | `Retry-After` on a 503 registration-busy. |
| `READINESS_CACHE_SECONDS` | `30.0` | How long a successful readiness check is cached. |
| `FUZZY_BLOCKING_LIMIT` | `50` | Rows the blocking query returns. |
| `FUZZY_NAME_FLOOR` | `0.8` | Name similarity that sends a candidate to the model on its own. Uncalibrated. |
| `FUZZY_NAME_WITH_SIGNAL_FLOOR` | `0.6` | Name similarity that qualifies with a second signal. Uncalibrated. |
| `FUZZY_ADDRESS_FLOOR` | `0.85` | Address similarity that counts as that second signal. Uncalibrated. |
| `FUZZY_MAX_CANDIDATES_FOR_MODEL` | `5` | Most candidates the model sees, 1 to 5. |
| `DUPLICATE_WARNING_MIN_CONFIDENCE` | `0.6` | Lowest model confidence that produces a likely-duplicate warning. |
| `TYPO_MIN_CONFIDENCE` | `0.7` | Lowest model confidence that produces a typo suggestion. |
| `RATE_REGISTER_LIMIT` | `5` | Register calls per client per window. |
| `RATE_REGISTER_WINDOW_SECONDS` | `600` | Register window. |
| `RATE_CHECK_DUPLICATE_LIMIT` | `10` | Check-duplicate calls per client per window. |
| `RATE_CHECK_DUPLICATE_WINDOW_SECONDS` | `600` | Check-duplicate window. |
| `RATE_VALIDATE_LIMIT` | `30` | Validate calls per client per window. |
| `RATE_VALIDATE_WINDOW_SECONDS` | `60` | Validate window. |
| `RATE_CHAT_LIMIT` | `20` | Chat calls per client per window. |
| `RATE_CHAT_WINDOW_SECONDS` | `600` | Chat window. |
| `CHAT_MAX_TURNS_PER_SESSION` | `30` | Turns one conversation may take. |
| `CHAT_MAX_PROMPT_CHARS` | `12000` | Prompt size the assistant refuses to exceed. |
| `CHAT_MAX_TOOL_CALLS_PER_TURN` | `4` | Tool calls the assistant may make in one turn. |
| `SESSION_IDLE_SECONDS` | `1800.0` | Idle time after which a session is deleted. |
| `SESSION_MAX_COUNT` | `1000` | Most sessions held in memory. |
| `SESSION_JANITOR_INTERVAL_SECONDS` | `60.0` | How often idle sessions are swept. |
| `PII_HASH_KEY` | none | Secret. HMAC key for tax-ID, email, client, and request hashes. At least 16 characters. |
| `HASH_KEY_VERSION` | `v1` | Version recorded with each hashed tax ID. |
| `BOT_CHECK_SECRET` | none | Secret. Reserved for the bot-check provider. |
| `OPENAI_API_KEY` | none | Secret. Needed only when `LLM_FALLBACK_MODEL` is set. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |

The memory store, the stub verifier, and reserved email domains load only with `ALLOW_LOCAL_ADAPTERS=true`. No real bot-check provider exists yet, so a deployed configuration cannot boot until one is chosen. This is deliberate, and it fails closed.

The UI reads three public values from its server environment on every request, so one build serves every environment: `API_BASE_URL` (required), `ASSISTANT_ENABLED` (default `true`), and `BOT_CHECK_STUB_TOKEN` (empty unless the local stub verifier is in use). The UI calls the API directly from the browser, so `API_BASE_URL` must be reachable from the visitor.

## IAM grants

| Identity | Grants |
| --- | --- |
| Service account `registration-api` | `roles/bigquery.dataEditor` on the `customer_ops` dataset only, `roles/bigquery.jobUser` on the project, `roles/aiplatform.user` on the project, and `roles/secretmanager.secretAccessor` on its own secrets. The default compute account is never attached. |
| Service account `registration-ui` | No data roles. |
| Platform-check identity | The API's grants plus create and delete on scratch datasets in the dev project. |

`dataEditor` also allows deleting tables. A custom role with `bigquery.tables.get`, `bigquery.tables.getData`, and `bigquery.tables.updateData` is the tighter grant, and `docs/code-review-report.md` recommends it.

## Platform check

`tests/integration/` holds the platform check. It needs a GCP dev project, so it has not run, and `make integration` skips it without `GCP_PROJECT`. When it runs it creates the dataset `it_<run id>` with a one-day table expiration and deletes it afterward. It records the following into `it-findings.json` when `IT_FINDINGS_PATH` is set:

- whether the DDL applies, `PARTITION BY DATE(created_at)` included;
- that 20 trials of 5 concurrent registrations for one email each insert exactly once with the lock, and what happens without it;
- the abort's error reason and message, which `LockConflict` detection currently matches by message text;
- how soon a retry after an abort succeeds or sees the duplicate, and the p50 and p95 latency of the script over 30 runs;
- one structured call to each configured Gemini model id through Vertex AI.

Findings: none recorded yet.

## Decisions and environment notes

- **Gemini model ids.** Both default to `gemini-2.5-flash` as briefed. Google has deprecated the 2.5 line, so the ids are configuration and the platform check calls each one.
- **ADK.** The pinned `google-adk` 2.14.1 supports `Runner.run_async(..., state_delta=...)`, and the assistant uses it for per-turn state. ADK and `google-genai` choose Vertex AI from `GOOGLE_GENAI_USE_ENTERPRISE` together with `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`, which the app sets at boot from configuration. On Vertex AI, ADK lets a Gemini model combine an output schema with tools.
- **Disposable list.** `app/data/disposable_domains.txt` is a copy of the public disposable-email-domains list (CC0 1.0), refreshed by `python scripts/refresh_disposable_domains.py`. The list includes typo domains of common providers, such as `gmial.com`, so those addresses get 422 `email-disposable` with a "Did you mean" suggestion attached.
- **TypeScript.** The UI pins TypeScript 5.9.3. TypeScript 7.0.2 has no JavaScript compiler API, which `openapi-typescript` and Next.js type checking need.
- **Zod.** `@hookform/resolvers` 7 accepts zod 3.25 and later and zod 4, so the UI uses zod 4.
- **Next.js 15.** Next.js 15 is in maintenance support with security releases through 2027-01-31. Settle the Next.js major before production.

## Layout

```
app/          FastAPI app: api/ (routes, problem handlers), domain/ (pure rules), services/, agents/
sql/          DDL, the registration transaction, query templates, the duplicate-key check
scripts/      apply_schema, export_openapi, refresh_disposable_domains
contracts/    openapi.yaml, generated and committed
tests/        offline suite; integration/ is the platform check
ui/           Next.js 15 app: features/registration, features/assistant, shadcn/ui components
```
