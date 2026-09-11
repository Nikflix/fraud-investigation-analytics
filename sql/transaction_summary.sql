-- Unknown labels stay separate from known negative and positive labels.
SELECT
    transaction_type,
    COUNT(*) AS transaction_count,
    SUM(amount) AS total_amount,
    COUNT(*) FILTER (WHERE is_fraud IS NULL) AS unknown_labels,
    COUNT(*) FILTER (WHERE is_fraud = FALSE) AS negative_labels,
    COUNT(*) FILTER (WHERE is_fraud = TRUE) AS positive_labels
FROM transactions
GROUP BY transaction_type
ORDER BY transaction_type;
