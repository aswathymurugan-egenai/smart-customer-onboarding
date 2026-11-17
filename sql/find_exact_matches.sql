-- Reports which unique keys already belong to a customer, by name only. It decides nothing:
-- register_customer.sql enforces uniqueness inside its transaction. Optional values arrive as
-- '' because query parameters cannot be NULL.
SELECT field
FROM (
  SELECT 'email' AS field
  FROM `${project}.${dataset}.customers`
  WHERE email = @email
  UNION ALL
  SELECT 'phone'
  FROM `${project}.${dataset}.customers`
  WHERE @phone_e164 != '' AND phone_e164 = @phone_e164
  UNION ALL
  SELECT 'tax_id'
  FROM `${project}.${dataset}.customers`
  WHERE @tax_id_hash != '' AND tax_id_hash = @tax_id_hash
)
GROUP BY field
ORDER BY field;
