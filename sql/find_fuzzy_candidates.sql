-- Blocking query for likely-duplicate matching: returns up to @max_rows customers that share
-- a normalized name, a name key, a postal code in the same country, or a business email
-- domain with the applicant. Scoring happens in the service. Optional values arrive as ''
-- because query parameters cannot be NULL.
SELECT
  customer_id,
  customer_type,
  company_name,
  normalized_name,
  name_key,
  normalized_address,
  address.city AS city,
  REGEXP_REPLACE(UPPER(address.postal_code), r'[^A-Z0-9]', '') AS postal_code_key,
  address.country_code AS country_code,
  email_domain,
  email_local_part
FROM `${project}.${dataset}.customers`
WHERE normalized_name = @normalized_name
   OR name_key = @name_key
   OR (@postal_code_key != ''
       AND REGEXP_REPLACE(UPPER(address.postal_code), r'[^A-Z0-9]', '') = @postal_code_key
       AND address.country_code = @country_code)
   OR (@business_domain != '' AND customer_type = 'business' AND email_domain = @business_domain)
ORDER BY created_at DESC
LIMIT @max_rows;
