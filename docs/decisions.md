# Implementation decisions

## Keep the first milestone small

The foundation began before dataset selection. A thin CSV adapter and working validation boundary let us review the input contract before building features or committing to source-specific assumptions. PaySim is now selected, with a separate adapter and a documented contract.

TOML is read with `tomllib`, sample amounts are checked with `Decimal`, and tests use `pytest`. DuckDB was added with local ingestion. Streamlit, pandas, and Plotly support the interface; NumPy and scikit-learn now support the baseline. Modelling dependencies remain optional for ingestion-only use.

## Use DuckDB for the local analytical store

DuckDB runs inside Python and persists data to a file. It supports SQL without a separate server, making it suitable for this project's local batch workflow. The supported dependency range is `duckdb>=1.5,<2`; this is a compatibility range, not a locked environment. `pytz` is included because DuckDB requires it to return timezone-aware Python datetimes.

One `transactions` table is sufficient for the sample. The loader validates and converts the complete batch before opening the database, then creates the table and inserts rows in one transaction. A primary key rejects transaction IDs already present in the store. The whole batch rolls back on a database error, including new rows inserted before a duplicate was encountered. A rerun fails clearly; it does not silently skip or replace records.

The provisional schema stores money as `DECIMAL(18, 2)`. Values that cannot be represented exactly are rejected before DuckDB can round them. Timestamp storage requires seconds, an explicit minute-based offset, and at most six fractional digits. Timestamps are normalized to UTC; the original timestamp string is also retained. These limits fit the sample and must be reviewed against the selected dataset.

For the original sample loader, input path, logical CSV record number, and ingestion time provide basic provenance. Its source file is not copied or hashed. PaySim uses the separate snapshot loader described below.

## Give PaySim its own snapshot contract

PaySim does not supply calendar timestamps or transaction IDs. Its zero-amount records and scientific notation also differ from the initial sample assumptions. Mapping it into the sample contract would require invented values or drop valid records, so it uses a dedicated table and validator.

The PaySim importer copies and hashes the same CSV bytes it scans. DuckDB stages the fields as text and validates exact decimal representability before bulk insertion. This preserves exponent notation without accepting silent rounding. The source-row ordinal and CSV fingerprint provide a reproducible record reference.

One database contains one PaySim snapshot. Identical content is a successful no-op; another fingerprint is rejected rather than appended or overwritten. This suits a fixed exploratory dataset and keeps incremental-ingestion semantics out of this milestone. Metadata and row-count checks do not detect arbitrary manual database edits.

The overview queries DuckDB directly with parameterized filters. It caches aggregates and bounded pages using database file metadata and keeps the full dataset out of pandas during browsing. Training materializes narrow inputs one period at a time. The app supports its own training and review writes; stop it before CLI imports or training. Multi-user state and concurrent writes will require a separate design.

## Respect the measured data limits

The [recorded PaySim profile](paysim.md) shows only 9,298 repeated source IDs among 6,353,307 distinct source IDs, with at most three source appearances each. The application therefore labels account searches as record appearances rather than inferred behavioural risk.

Step values remain simulation hours. No calendar date or within-hour ordering is fabricated. Dataset labels and supplied existing-rule flags remain separate from predictions and analyst feedback. The baseline assumes the recorded source balance before the transaction is available at scoring time; destination and outcome balances are excluded.

## Preserve ambiguous input for review

The adapter retains IDs and amounts as strings. Missing labels remain unknown. The validator reports every occurrence of a duplicate transaction ID; it does not keep the first row and silently discard the rest. It reports counts and issue locations without printing transaction values in the logs.

## Review the dataset before implementing history features

Dataset review and the next modelling milestone should address:

1. Can the data be obtained and used under documented terms?
2. Are account IDs stable, and do accounts have enough repeated activity for behavioral baselines?
3. Are both ends of each transfer available? Can merchants be distinguished from customer accounts?
4. What does the timestamp represent, and what is its actual resolution?
5. What do the labels mean, and when would they become available in a real investigation?
6. Do balance fields describe the state before or after execution? Would they be available at the intended scoring time?
7. Are there source-generated flags or other fields that directly leak the target?

Use only lookback windows supported by the data's time resolution. Define how equal timestamps are handled before computing velocity or recipient novelty. Account and graph history must be cut off at the scoring time, including when they are used to explain an evaluation example.

## Use a small chronological baseline

The first trained model is logistic regression with nine encoded features derived from three inputs. All training rows are retained, without class weighting or oversampling. Standardization and the large-amount percentile use only the training period.

The default 70%/15%/15% row split keeps whole simulation hours together. The score threshold selects at most 1% of validation rows, using strict comparison to handle tied scores conservatively. Test labels affect evaluation only. A fixed threshold can produce a different alert volume later; the app reports that observed volume.

Two separate rules flag outgoing transactions above the training 99.5th amount percentile or requesting at least 80% of a positive source balance. Their union is evaluated independently of the model. Integer-cent comparisons avoid binary floating-point errors at rule boundaries.

The [model card](model-card.md) documents the actual results, label timing assumptions, and prevalence shift. The initial analysis follows aggregate dataset inspection, so this is an exploratory baseline, not an untouched external benchmark. No hyperparameter search was performed against the test period.

## Save reproducible scores and separate reviews

Model coefficients, standardization parameters, rule settings, configuration, and metrics are JSON values in DuckDB; inference does not deserialize executable pickle files. An analysis identity includes the source fingerprint and feature/algorithm versions. Dependency versions are recorded for interpretation, but are not a lockfile or a guarantee of bitwise identical retraining.

Reviews refer to the CSV fingerprint and source row. Each save updates the current status and appends an event in one transaction. Repeating an analysis preserves those reviews. Review statuses describe workflow progress; closing a case does not establish a verified fraud label.

The queue scores the final evaluation period only, keeping training examples out of the measured review workflow. Case history includes strictly earlier hours, with at most 20 records. The new-transaction form calculates fresh results from entered values without modifying the source snapshot.

## Repository scope

The repository includes fictional sample records and executable code. Raw datasets, processed data, local environments, credentials, and model outputs are ignored by Git. The supplied architecture image is retained as a concept reference; the README describes the actual implementation status.

The CI workflow uses the documented [checkout](https://github.com/actions/checkout) and [setup-python](https://github.com/actions/setup-python) actions with read-only repository permissions and Python 3.12.
