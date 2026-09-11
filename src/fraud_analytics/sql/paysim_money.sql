-- Accept exact cents, including scientific notation, without silently rounding.
CREATE TEMP MACRO paysim_mantissa(value) AS split_part(lower(value), 'e', 1);
CREATE TEMP MACRO paysim_exponent(value) AS (
    CASE WHEN contains(lower(value), 'e')
         THEN try_cast(split_part(lower(value), 'e', 2) AS INTEGER)
         ELSE 0 END
);
CREATE TEMP MACRO paysim_money_valid(value) AS (
    coalesce(
        regexp_full_match(value, '[+]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?')
        AND try_cast(value AS DECIMAL(18, 2)) IS NOT NULL
        AND paysim_exponent(value) BETWEEN -1000 AND 1000
        AND (
            NOT regexp_matches(paysim_mantissa(value), '[1-9]')
            OR length(split_part(paysim_mantissa(value), '.', 2))
               - (length(replace(paysim_mantissa(value), '.', ''))
                  - length(rtrim(replace(paysim_mantissa(value), '.', ''), '0')))
               - paysim_exponent(value)::BIGINT <= 2
        ), FALSE
    )
);
