-- Must return zero rows while the uniqueness rule holds. Each row names a key and lists the
-- customer ids that share a value of it. The values themselves are never selected.
SELECT
  key_name,
  ARRAY_AGG(customer_id ORDER BY customer_id) AS customer_ids
FROM (
  SELECT 'email' AS key_name, email AS key_value, customer_id
  FROM `${project}.${dataset}.customers`
  UNION ALL
  SELECT 'phone', phone_e164, customer_id
  FROM `${project}.${dataset}.customers`
  WHERE phone_e164 IS NOT NULL
  UNION ALL
  SELECT 'tax_id', tax_id_hash, customer_id
  FROM `${project}.${dataset}.customers`
  WHERE tax_id_hash IS NOT NULL
)
GROUP BY key_name, key_value
HAVING COUNT(*) > 1
ORDER BY key_name;
