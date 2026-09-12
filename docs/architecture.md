# Architecture notes

The implemented workflow includes the original sample validator and loader, a bulk PaySim CSV/ZIP importer, shared analytics queries, a chronological model and rule pipeline, and a Streamlit queue with persistent reviews. Graph analysis and LLM summaries remain planned.

## Implemented data overview

The PaySim importer hashes a temporary copy of the source CSV and validates all rows in DuckDB before committing a typed snapshot. Metadata records its fingerprint, source name, row count, and import time. The original sample uses the separate `transactions` table; PaySim uses `paysim_transactions` and preserves simulation steps.

The CLI profile and Streamlit application share parameterized queries in `analytics/paysim.py`. The app caches aggregates and pages by database identity and filters. It retrieves at most 100 transaction rows per page, while the SQL queries scan the selected snapshot. Hour, type, label, and exact account filters apply consistently to metrics, charts, and the table.

The overview remains an exploration view. Supplied fraud labels and existing-rule flags are displayed separately from model results in the review workspace.

## Implemented scoring and review

`detection/pipeline.py` selects three consecutive periods using cumulative row counts and whole simulation hours. Training alone fits the scaler, logistic regression coefficients, and large-amount rule cutoff. Validation scores determine the model alert threshold. The final period provides evaluation and the saved transaction queue.

The explicit input contract in `detection/features.py` uses transaction type, amount, and source balance before the transaction. It excludes labels, source flags, IDs, time, and outcome balances. JSON parameters support the same inference calculation for saved test transactions and the new-transaction form. The [model card](model-card.md) records assumptions and measured results.

| DuckDB table | Responsibility |
| --- | --- |
| `paysim_transactions` | Immutable imported transaction values and source-row references. |
| `paysim_dataset` | Source fingerprint and ingestion metadata. |
| `detection_runs` | Versioned configuration, model parameters, thresholds, and evaluation. |
| `transaction_scores` | Model score and independent rule flags for each test-period row and run. |
| `case_reviews` | Latest local status and note for a dataset row. |
| `review_events` | Append-only application history of saved statuses and notes. |

Analysis writes model metadata and all scores in one transaction. The run identity combines the source fingerprint, configuration, feature version, and algorithm version; repeating it reuses existing results. Review persistence is keyed to the source snapshot and row, independent of a model run.

The interface retrieves at most 100 queue rows per page. A selected case includes up to 20 earlier records involving either account, using strictly earlier hours. It also presents exact rule reasons, additive model factors, and saved review history. The application does not infer within-hour event order or automatically turn notes into training labels.

This is a single-user local application. Connections are short-lived; CLI imports and training should not run while another process holds the database. Training needs more memory than paginated browsing because each modelling period is materialized as a narrow feature matrix.

## Intended components

| Component | Responsibility |
| --- | --- |
| Batch ingestion | Read a documented source, validate it, retain provenance, and prevent accidental duplicate ingestion. |
| Analytical store | Persist transactions and reproducible SQL transformations, initially in DuckDB. |
| Feature and detection pipeline | Calculate historical features, run rules and models, and retain the reasons for each flag. |
| Investigation engine | Gather account history, counterparties, temporal patterns, and graph evidence. |
| Evidence package | Store typed findings and their provenance before any LLM call. |
| Summary component | Turn the evidence into a concise, qualified investigation summary. |
| Streamlit application | Present the queue, case evidence, network context, and analyst feedback. |
| Evaluation | Measure detection quality, review workload, and summary grounding on held-out examples. |

## Reference diagram

[View the original concept diagram](architecture-reference.png).

That diagram predates the current project name and contains illustrative outputs. Its example probabilities and business-impact claims are not measured results of this repository.

The implementation follows these decisions:

- Batch processing comes first. Streaming is a possible later extension.
- Detection is deterministic Python/SQL and model execution; it is not an LLM agent.
- Investigation functions collect facts before the summary component runs.
- Initial orchestration uses ordinary Python functions. Additional agent frameworks need a concrete reason.
- The dashboard shows model output and rule alerts separately. Score calibration has not been validated.
- Analyst dispositions are feedback for later evaluation. They do not immediately retrain a model or become verified labels.
- External notifications and consequential actions require explicit authorization.

## Deployment direction

Develop the analytics workflow locally. Add PostgreSQL only when shared application state or concurrent use requires it. Add Docker when the application has a useful runnable workflow. AWS storage, hosting, credentials, and monitoring belong to the deployment phase.

An LLM call will receive a structured case-evidence object. It will not calculate features, generate fraud probabilities, choose financial actions, or execute arbitrary SQL.
