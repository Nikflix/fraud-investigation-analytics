# PaySim contract and recorded profile

PaySim is a synthetic mobile-money transaction dataset. The project uses the CSV available from [the PaySim dataset page](https://www.kaggle.com/datasets/ealaxi/paysim1). The [simulator repository](https://github.com/EdgarLopezPhD/PaySim) and [2017 paper](https://www.msc-les.org/proceedings/emss/2017/EMSS2017_296.pdf) provide source context. A simulator's current implementation is not assumed to describe every detail of an older generated CSV.

The uploaded archive was inspected on 2026-09-11. The following profile records that inspection; it is not a model evaluation. Raw data is not included in this repository. Reproduce the aggregates for a loaded snapshot with:

```bash
fraud-analytics profile-paysim --database data/processed/paysim.duckdb
```

## Source identity

| Attribute | Recorded value |
| --- | --- |
| CSV name | `PS_20174392719_1491204439457_log.csv` |
| Uncompressed CSV bytes | 493,534,783 |
| CSV SHA-256 | `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b` |
| Columns | 11 |
| Data records | 6,362,620 |

The fingerprint is for the uncompressed CSV, not the ZIP. Repacking identical CSV bytes produces the same identity. Changing line endings or row order produces a different identity.

## Full-dataset verification

On 2026-09-11, the reattached archive was imported and checked using code from
[commit 2597697](https://github.com/Nikflix/fraud-investigation-analytics/commit/2597697063e72feee9bb8b19b89005a4062e4c48),
with Python 3.12.14, DuckDB 1.5.5, and Streamlit 1.63.0. Its CSV fingerprint
matches the source identity above.

| Check | Observed result |
| --- | --- |
| Complete ZIP import | 6,362,620 records inserted. |
| Profile reconciliation | All recorded totals, type subtotals, amount totals, step coverage, and account-coverage measures matched. |
| Identical archive imported again | Zero records inserted; 6,362,620 records retained. |
| Initial dashboard overview | 6,362,620 transactions, 8,213 fraud labels, 16 existing-rule flags, and 100 rows on the first page. |
| Final dashboard page | Page 63,627 contains the final 20 records. |
| Fraud-label filter | 8,213 records; changing the filter resets pagination to page 1. |
| Fraud-label and TRANSFER filters | 4,097 records. |
| Simulation hour 1 | 2,708 records. |
| Exact account filter | Returned rows and count agree with an independent SQL query across both account roles. |
| No transaction types selected | Zero records and a clear empty-state message. |

Dashboard checks used Streamlit's AppTest against the full DuckDB file. They
verify application execution, widget interactions, displayed values, and table
contents. Browser layout, Windows execution, and concurrent-user behaviour were
not tested in this run.

The full dataset is an additional local integration check; GitHub Actions
continues to use the small fictional fixtures. The archive and generated
database are excluded from the repository.

## Input and field mapping

The importer accepts UTF-8 CSV, with an optional byte-order mark, or a ZIP containing exactly one CSV. The header names and order must match:

```text
step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,newbalanceDest,isFraud,isFlaggedFraud
```

| Input | DuckDB column | Type and interpretation |
| --- | --- | --- |
| `step` | `simulation_step` | Positive `INTEGER`; simulation hour, not a calendar timestamp. |
| `type` | `transaction_type` | `VARCHAR`; CASH_IN, CASH_OUT, DEBIT, PAYMENT, or TRANSFER. |
| `amount` | `amount` | Exact nonnegative `DECIMAL(18, 2)`; unspecified dataset units. |
| `nameOrig` | `source_account` | `VARCHAR` matching `C[0-9]+`; retained as a source identifier. |
| `oldbalanceOrg` | `source_balance_before` | Exact nonnegative `DECIMAL(18, 2)`. |
| `newbalanceOrig` | `source_balance_after` | Exact nonnegative `DECIMAL(18, 2)`. |
| `nameDest` | `destination_account` | `VARCHAR` matching `[CM][0-9]+`; customer or merchant identifier. |
| `oldbalanceDest` | `destination_balance_before` | Exact nonnegative `DECIMAL(18, 2)`. |
| `newbalanceDest` | `destination_balance_after` | Exact nonnegative `DECIMAL(18, 2)`. |
| `isFraud` | `is_fraud` | `0`/`1` converted to `BOOLEAN`; supplied synthetic fraud label. |
| `isFlaggedFraud` | `is_flagged_fraud` | `0`/`1` converted to `BOOLEAN`; supplied existing-rule flag, kept separate from the label. |

All eleven values are required. The original spelling `oldbalanceOrg` is intentional. Unlike the original sample adapter, PaySim values are not trimmed or mapped into the nine-column sample contract.

The `paysim_transactions` table also stores `source_row_number` as a `BIGINT PRIMARY KEY`. It is the logical CSV record position, with the header counted as row 1. It is not a source transaction ID or a guarantee of event order within a simulation hour.

The separate `paysim_dataset` table holds the CSV SHA-256, source basename, record count, and import time. No calendar timestamp is invented.

## Recorded profile

| Measure | Value |
| --- | ---: |
| Simulation step range | 1–743 |
| Distinct observed steps | 743 |
| Supplied fraud labels | 8,213 |
| Fraud-label prevalence | 0.129082% |
| Supplied existing-rule flags | 16 |
| Total recorded amount | 1,144,392,944,759.77 |
| Minimum amount | 0.00 |
| Maximum amount | 92,445,516.64 |
| Zero-amount records | 16 |
| Zero-amount records with a fraud label | 16 |
| Distinct source IDs | 6,353,307 |
| Source IDs appearing more than once | 9,298 |
| Maximum source-ID record count | 3 |
| Records involving a repeated source ID in the source role | 18,611 |
| Distinct destination IDs | 2,722,362 |
| Merchant-destination records | 2,151,495 |

Amounts are transaction volume in unspecified dataset units. They are not fraud losses or net money flow.

| Type | Transactions | Fraud labels | Existing-rule flags | Recorded amount |
| --- | ---: | ---: | ---: | ---: |
| CASH_IN | 1,399,284 | 0 | 0 | 236,367,391,912.46 |
| CASH_OUT | 2,237,500 | 4,116 | 0 | 394,412,995,224.49 |
| DEBIT | 41,432 | 0 | 0 | 227,199,221.28 |
| PAYMENT | 2,151,495 | 0 | 0 | 28,093,371,138.37 |
| TRANSFER | 532,909 | 4,097 | 16 | 485,291,987,263.17 |

The initial inspection found no missing values in the eleven fields or exactly duplicated raw records. The importer does not deduplicate by account pair, step, type, and amount; repeated records retain separate source-row identities.

## Validation and load behaviour

The loader snapshots and hashes the uncompressed CSV, then bulk-reads it into a temporary DuckDB table with every source field initially treated as text. It uses four DuckDB threads and a 1 GB memory limit; staging can spill to disk. It does not materialize millions of Python record dictionaries.

Validation checks missing values, steps, categories, account formats, binary labels, and exact decimal representability. Scientific notation occurs in the full source: for example, `1.010284203E7` is exactly `10102842.03`. Rejecting all exponent notation would discard valid records. Values with nonzero sub-cent digits, overflow, negative amounts or balances, and non-finite values are rejected rather than rounded.

Zero-amount records are preserved, including their supplied labels. Applying the sample contract's strictly positive amount rule would incorrectly remove all sixteen such records from this snapshot.

Validation, typed insertion, and metadata creation are one transaction. An invalid batch adds no rows. The same CSV fingerprint and stored record count yield a successful no-op on rerun. A different snapshot or inconsistent metadata is refused; choose a new database path to retain a separate copy.

The fingerprint identifies the imported source bytes. It does not detect arbitrary manual edits to values inside an already loaded database. Leave imported transaction values unchanged and retain the original CSV for reconstruction. The scoring and review workflows write separate tables in the same database.

## Analysis limits

- **Time resolution:** one step represents a simulation hour. Do not invent real dates, minute-level windows, or a true ordering among records in the same hour. Future history features must explicitly handle ties.
- **Sparse source history:** approximately 99.85% of source IDs appear once; the maximum is three records. A source-ID search is useful for inspection but cannot establish a rich sender behaviour baseline. Destination repetition needs separate analysis.
- **Account roles:** source and destination preserve the supplied columns. Their meaning varies across transaction types; do not relabel every appearance as money sent or received, or infer verified account ownership.
- **Labels:** `isFraud` is supplied synthetic ground truth. `isFlaggedFraud` is an existing flag from the source, not a prediction made by this project. Neither is analyst review feedback.
- **Leakage:** the current baseline excludes labels, supplied flags, IDs, simulation hour, destination balances, and post-transaction balances from its inputs. It assumes the recorded source balance before execution is available. See the [model card](model-card.md) for label timing and evaluation assumptions.
- **Balances:** merchant-related zero balance values must not be treated as verified observed account state. Balance reconciliation needs transaction-type-specific source assumptions.
- **Generalization:** this simulation does not establish performance on real banking data. Label prevalence and rule behaviour in it must not be presented as real-world fraud rates.

## Test fixture

`data/sample/paysim.csv` contains six hand-written fictional records. It exercises all five transaction types, a repeated source ID, scientific notation, zero amounts, and separate fraud-label and existing-flag values. Its three fraud labels out of six records are deliberately chosen test coverage, not representative sampling.

The app identifies this fixture and disables training. Select the full database for the scoring and review workflow. Recorded model results are documented separately in the [model card](model-card.md).
