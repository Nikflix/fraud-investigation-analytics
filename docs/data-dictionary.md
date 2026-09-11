# Sample transaction contract

This is the original nine-field sample interface from the foundation milestone. PaySim uses a separate [reviewed contract](paysim.md) and table because it has simulation hours and source-row positions instead of calendar timestamps and transaction IDs. Do not invent timestamps, counterparties, balances, or fraud labels to fill gaps in a source dataset.

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
| `is_fraud` | No | `0` for a known negative label, `1` for a known positive label, or blank for unknown. All labels in `data/sample/transactions.csv` are unknown. |

The adapter trims surrounding whitespace from values and retains strings. Validation parses amounts with `Decimal`, avoiding binary floating-point comparisons. It checks timestamps without changing their offsets or values. The separate ingestion command applies the storage contract below.

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

Validation does not mutate or discard records. The ingestion command rejects the whole batch when validation fails; it does not create a quarantine file. No record is scored or classified by either command.

## DuckDB storage contract

`fraud-analytics ingest` creates a `transactions` table in the selected local
database. It appends a batch only when every record is valid and fits the storage
types. An ID already present in this table rejects the entire batch, even if its
values are identical. Existing records are never overwritten by ingestion.

| Column | DuckDB type | Storage behavior |
| --- | --- | --- |
| `transaction_id` | `VARCHAR PRIMARY KEY` | Unique across all loaded batches. |
| `timestamp` | `TIMESTAMPTZ NOT NULL` | UTC instant with microsecond precision. |
| `source_account`, `destination_account` | `VARCHAR NOT NULL` | Leading zeroes remain intact. |
| `amount` | `DECIMAL(18, 2) NOT NULL` | Positive, exact decimal; no rounding. |
| `transaction_type` | `VARCHAR NOT NULL` | Validated against the supplied configuration. |
| `source_balance_before`, `source_balance_after` | `DECIMAL(18, 2)` | Nonnegative when present; blank or absent becomes `NULL`. |
| `is_fraud` | `BOOLEAN` | `0` becomes `FALSE`, `1` becomes `TRUE`, blank or absent becomes `NULL`. |
| `source_timestamp` | `VARCHAR NOT NULL` | Original timestamp string after adapter whitespace trimming. |
| `source_file` | `VARCHAR NOT NULL` | Input path supplied to the command; not a file hash. |
| `source_row_number` | `BIGINT NOT NULL` | Logical CSV record number, including the header. |
| `ingested_at` | `TIMESTAMPTZ NOT NULL` | Database transaction time for the load. |

Money must fit within 16 integer digits and two fractional digits. Additional
trailing fractional zeroes are accepted if the numeric value stays exact. A value
such as `1.001` or `10000000000000000` rejects the batch before database creation.
These are provisional storage limits; the source validator alone does not enforce
them.

Storage accepts `YYYY-MM-DDTHH:MM:SS` (a space may replace `T`), optional one to
six fractional second digits, and `Z` or a `+/-HH:MM` offset. Higher precision and
other formats accepted by Python's source validator are rejected for storage.
The UTC value must fit Python's datetime range. DuckDB displays `TIMESTAMPTZ`
values in the connection's timezone; the project examples set that timezone to
UTC explicitly. The original offset is retained in `source_timestamp`.

Database [decimal types](https://duckdb.org/docs/current/sql/data_types/numeric)
and [timestamp types](https://duckdb.org/docs/current/sql/data_types/timestamp)
determine these representation choices. Review both when adapting a real dataset.
