# Code review report: customer registration API

This is the author's self-review of the branch `feat/customer-registration-api`. The independent `/axis-review` pass the plan calls for has not run, because `main` has no commits to diff against. Every Blocker and Major finding below needs a fix or a written acceptance before merge.

## Verdict

No Blocker. Five Major findings are open and need a decision. The registration transaction and the live Gemini calls are unproven because the platform check needs a GCP dev project, and the browser journeys have not run (see "Not verified").

| Severity | Count |
| --- | --- |
| Blocker | 0 |
| Major | 5 |
| Minor | 10 |
| Nit | 2 |

## Security

**What holds**

- Every request value reaches BigQuery as a query parameter. The injection test sends `'; DROP TABLE customers; --` as a given name and asserts it appears in a parameter and never in the SQL text (`tests/unit/test_bq_repository.py:22`). Project and dataset names are checked against strict patterns before substitution (`app/services/sql_templates.py`).
- Tax IDs, audit emails, client addresses, and request fingerprints are stored as HMAC-SHA256 hashes under per-kind prefixes (`app/services/pii.py`). The raw tax ID exists only in memory during a request.
- The log allow-list drops every key except fourteen operational ones (`app/logging.py:17`). A test submits distinctive names, addresses, a tax ID, and chat text through every route and asserts none reaches stdout (`tests/test_registration.py`).
- The model prompts carry the email domain only for typo advice, and opaque references with normalized names and places for duplicate advice. The tests assert no phone, tax ID, email local part, or customer id is sent (`tests/unit/test_advisor.py`).
- The advisor and assistant set no sampling parameters, and model output is schema-validated before any code acts on it.

**Findings**

| Severity | Finding | Location |
| --- | --- | --- |
| Major | **Rate limits can be bypassed by spoofing `X-Forwarded-For`.** With `TRUST_PROXY_HEADERS=true` the limiter keys on the first hop. A caller can send its own header, and the proxy appends the real address after it, so each request can claim a new client. The plan specifies the first hop. Decide how many trusted proxy hops sit in front of the service and read the address that many positions from the right. | `app/api/dependencies.py:65` |
| Major | **Registering through the assistant skips the bot check.** Chat requests carry no bot token, so the assistant channel is only rate limited under the register allowance. A script can post a chat turn with `action = confirm_registration` and a made-up snapshot. Add a token to `ChatRequest` and verify it, or accept the gap in writing. | `app/services/guard.py:45` |
| Major | **Rejected requests each write an audit row.** Every 429, 403, and 422 from the service layer triggers one BigQuery DML job, so an unauthenticated flood becomes a flood of DML jobs. Sample or drop `rate_limited` and `bot_check_failed` rows, or buffer them. | `app/services/registration.py:314` |
| Minor | Request-shape 422s (malformed JSON, unknown fields) never reach a service, so no audit row records them. | `app/api/problems.py` |
| Minor | `dataEditor` on the dataset also allows deleting tables. A custom role with `bigquery.tables.get`, `bigquery.tables.getData`, and `bigquery.tables.updateData` is enough, because the service writes only by DML. | Deployment |
| Minor | The vendored disposable list contains typo domains such as `gmial.com`, so those addresses return 422 `email-disposable` instead of registering with a typo warning. The 422 carries a suggestion. | `app/data/disposable_domains.txt` |
| Minor | A name field that normalizes to nothing is refused with a generic `validation-error` pointing at the field. | `app/services/customer_normalizer.py` |
| Nit | The stub verifier compares against a fixed token. It loads only with `ALLOW_LOCAL_ADAPTERS=true`. | `app/services/bot_check.py:16` |

## Concurrency and data integrity

**Why streaming inserts are excluded.** Rows written by streaming cannot be changed by DML for 30 minutes, and mutating DML inside a transaction against recently streamed rows is unsupported. A streamed customer row would also escape the table lock. The repository exposes no streaming call, and a test asserts `insert_rows_json` and `insert_rows` are never invoked (`tests/unit/test_bq_repository.py`).

**The lock idiom.** `register_customer.sql:12` runs `DELETE FROM customers WHERE FALSE` right after `BEGIN TRANSACTION` and before the `MERGE` at line 57. A unit test asserts that order. The `MERGE` `ON` clause is the uniqueness rule, and the later `matched_on` query only explains a refusal.

**Platform-check figures.** None. The check is written (`tests/integration/test_bigquery_semantics.py`) and has not run.

| Severity | Finding | Location |
| --- | --- | --- |
| Major | **The transaction design is unproven against BigQuery.** Whether the lock closes the race, the abort's error reason, the script shape (`ROLLBACK` inside `IF`, the `STRUCT` variable, the final `SELECT`), and `PARTITION BY DATE(created_at)` are all untested. If retries within 10 seconds fail in more than 5% of trials, the plan returns the decision to the user. | `sql/register_customer.sql` |
| Minor | `LockConflict` is detected by the message text `aborted due to concurrent update`. Harden it with the error reason the platform check records. | `app/services/bq_repository.py:35` |
| Minor | A client-side job timeout after the server committed makes the retry see the caller's own row and answer 409. An `Idempotency-Key` turns that into a replay. The UI always sends one. A client without one gets the 409. | `app/services/registration.py:232` |
| Minor | Only `email` is clustered, so phone and tax-ID lookups in the `MERGE` and the exact-match query scan the table. That is fine at signup volume and worth a review when the table grows. | `sql/001_customer_ops_schema.sql` |
| Minor | A replayed registration returns no warnings, because the original advisory result is not stored. | `app/services/registration.py:273` |

## Agent reliability

- **Confirmation gate.** Three independent checks stand between a model and a registration. The API sets `registration_confirmed` and the confirmed fingerprint only for `action = confirm_registration`. `before_tool` refuses the register tool when the flag is off (`app/agents/registration_agent.py:323`). The tool checks the flag and the fingerprint again before calling the service (`app/agents/registration_agent.py:282`). Tests cover each layer and a real ADK `Runner` run with a scripted model (`tests/unit/test_agent_runner.py`).
- **Tool parameter design.** The model can set `email` on one tool and `include_likely_duplicates` on another. The register tool exposes no parameters and reads the form snapshot from session state, so a hallucinated or injected call cannot register invented data. A test inspects the declarations ADK generates.
- **Output validation.** The final answer is parsed into `AssistantTurn`, and a parse failure raises `AssistantUnavailable`. The model's `suggested_actions` are de-duplicated and drop `confirm_registration` after a registration.
- **Status from tool results.** `AssistantReply.registration` is copied from `state["registration_outcome"]`. The UI shows status only from that field, and a test confirms a reply that claims success in prose shows the tool's `needs_confirmation`.
- **Fallback.** The fallback model runs the same turn only after a transient failure or a timeout, and it reuses the idempotency key derived from the session and fingerprint, so a half-finished register call replays instead of registering twice.

| Severity | Finding | Location |
| --- | --- | --- |
| Major | **The model sees the visitor's name, email, and address in clear text.** The privacy notice discloses Gemini and OpenAI. Gemini on Vertex AI receives the redacted form, and the OpenAI fallback receives the same when switched on. Decide the fallback data policy (open question 7) before enabling it. | `app/agents/registration_agent.py` |
| Minor | An invalid or empty model answer is not retried on the fallback, because only timeouts, connection errors, and 429 or 5xx responses count as transient. | `app/agents/registration_agent.py:386` |
| Minor | Sessions and rate-limit windows live in one instance's memory. Cloud Run needs session affinity and an instance cap until shared storage exists. | `app/agents/registration_agent.py:420` |
| Nit | The tool-call cap counts calls the callback refuses, so a refused call still uses one of the four. | `app/agents/registration_agent.py:323` |

## Recommendations for Cloud Run

- Give the API and the UI each a dedicated service account with only the grants in the README.
- Mount `pii-hash-key` and any other secret as a volume at `SECRETS_DIR`, and never as an environment variable.
- Cap max instances and set concurrency against lock contention, because every registration takes one table lock.
- Enable session affinity while the assistant keeps sessions in memory.
- Set the request timeout above the 20-second chat budget.
- Configure startup and liveness probes on `/healthz/live`, and readiness on `/healthz/ready`.
- Put Cloud Armor rate limiting at the edge. The in-process limiter counts per instance.
- Keep the dataset and the Vertex AI region aligned, and pin the model id after the Gemini model question is answered.
- Set `TRUST_PROXY_HEADERS=true` only together with the fix for the `X-Forwarded-For` finding above.
- Recommend `TIMESTAMP_TRUNC(created_at, MONTH)` partitioning if the daily partitions of `customers` stay small.

## Not verified

- **The platform check.** It needs a GCP dev project. The offline suite uses a BigQuery double that mirrors the transaction's rules, so it shows the service handles each outcome and not that BigQuery returns them.
- **The browser journeys.** Chromium cannot start in the build environment because `libnspr4.so` is missing, and installing it needs root. The Playwright suite type-checks, lints, and lists its 11 tests. The layout and axe assertions have not run. Vitest covers the form and the assistant panel, and a unit test verifies contrast for every token pair in both themes.
- **The images and CI.** The Dockerfiles, `docker-compose.yml`, and the GitHub Actions workflow were not run. The production UI build and the standalone server were run, and the API was started under uvicorn and exercised over HTTP.
- **Live Gemini.** The advisor and assistant ran against fakes and a scripted ADK model only.
