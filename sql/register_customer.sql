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
