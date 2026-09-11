# Sample transaction contract

This is a provisional interface for the foundation milestone. A dataset-specific adapter will map the selected source into a reviewed contract. Do not invent timestamps, counterparties, balances, or fraud labels to fill gaps in a source dataset.

The CSV uses UTF-8, with a header and one transaction per record. A UTF-8 byte-order mark is accepted. Required headers must match exactly; optional headers may be omitted. Duplicate headers, unexpected headers, and records whose width differs from the header cause a file-level failure.

| Field | Required | Meaning and current checks |
| --- | --- | --- |
| `transaction_id` | Yes | Nonempty string, unique within the batch. Every occurrence of a duplicated ID is reported. |
| `timestamp` | Yes | ISO-8601 datetime with an explicit timezone offset or `Z`. Naive timestamps are rejected. |
| `source_account` | Yes | Nonempty string. Leading zeroes are preserved. |
| `destination_account` | Yes | Nonempty string. May represent an account or fictional merchant in the sample. |
| `amount` | Yes | Finite decimal value strictly greater than zero. |
| `transaction_type` | Yes | Case-sensitive value listed in the configuration. |
| `source_balance_before` | No | Finite nonnegative decimal value when supplied. Blank means unknown. |
| `source_balance_after` | No | Finite nonnegative decimal value when supplied. Blank means unknown. |
| `is_fraud` | No | `0` for a known negative label, `1` for a known positive label, or blank for unknown. All bundled sample labels are unknown. |

The adapter trims surrounding whitespace from values and retains strings. Validation parses amounts with `Decimal`, avoiding binary floating-point comparisons. It checks timestamps without changing their offsets or values. UTC normalization and typed storage belong to the next ingestion milestone.

The sample represents one unspecified currency. It is not safe to combine amounts across currencies without adding a currency field and a documented conversion policy. Current checks do not enforce a decimal scale or an upper amount limit.

Nonnegative balances and positive amounts are sample assumptions. Datasets containing overdrafts, reversals, zero-value events, fees, or other balance conventions will require explicit changes. A balance equation is not enforced because the sample interface does not describe all of those accounting events.

## Validation output

The report includes `total_rows`, `valid_rows`, `invalid_rows`, and `issues`. Each issue has a `row_number`, `field`, and `code`. A record with several issues counts once in `invalid_rows`.

Record numbering includes the header, so the first data record is `2`. Record numbers are logical CSV records, not physical line numbers when a quoted value contains a newline. `0` denotes an issue applying to the whole input, such as `empty_input`.

| Code | Meaning |
| --- | --- |
| `empty_input` | The CSV has a header but no data records. |
| `missing_value` | A required field is missing or blank. |
| `duplicate_id` | An ID occurs more than once in the batch. |
| `invalid_timestamp` | Timestamp cannot be parsed as a timezone-aware datetime. |
| `invalid_amount` | Amount is not a finite, positive decimal value. |
| `unexpected_type` | Transaction category is absent from the configuration. |
| `invalid_balance` | A supplied balance is not a finite, nonnegative decimal value. |
| `invalid_label` | A supplied label is not `0` or `1`. |

Validation does not mutate or discard records. A caller must decide how to quarantine invalid input before persisting it. No record is scored or classified by this command.
