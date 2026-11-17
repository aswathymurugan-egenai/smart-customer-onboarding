-- Appends one audit row for an attempt that did not create a customer. The created row is
-- written inside register_customer.sql. Optional values arrive as '' (or -1.0) because query
-- parameters cannot be NULL.
INSERT INTO `${project}.${dataset}.registration_audit_logs`
  (event_id, request_id, idempotency_key, request_fingerprint, channel, operation, outcome,
   http_status, customer_id, email_hash, client_hash, matched_on, problem_codes, mx_status,
   advisory_status, typo_suggested_domain, fuzzy_candidate_ids, fuzzy_max_confidence,
   advisory_model, lock_retries, latency_ms, created_at)
VALUES
  (@event_id, @request_id, NULLIF(@idempotency_key, ''), NULLIF(@request_fingerprint, ''),
   @channel, @operation, @outcome, @http_status, NULLIF(@customer_id, ''),
   NULLIF(@email_hash, ''), @client_hash, @matched_on, @problem_codes, NULLIF(@mx_status, ''),
   NULLIF(@advisory_status, ''), NULLIF(@typo_suggested_domain, ''), @fuzzy_candidate_ids,
   NULLIF(@fuzzy_max_confidence, -1.0), NULLIF(@advisory_model, ''), @lock_retries,
   @latency_ms, CURRENT_TIMESTAMP());
