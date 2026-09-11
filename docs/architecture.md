# Architecture notes

The implemented workflow includes the original sample validator and loader, a bulk PaySim CSV/ZIP importer, shared read-only analytics queries, and a Streamlit transaction overview. Features, scoring, investigation cases, graph analysis, and LLM summaries remain planned.

## Implemented data overview

The PaySim importer hashes a temporary copy of the source CSV and validates all rows in DuckDB before committing a typed snapshot. Metadata records its fingerprint, source name, row count, and import time. The original sample uses the separate `transactions` table; PaySim uses `paysim_transactions` and preserves simulation steps.

The CLI profile and Streamlit application share parameterized queries in `analytics/paysim.py`. The app caches aggregates and pages by database identity and filters. It retrieves at most 100 transaction rows per page, while the SQL queries scan the selected snapshot. Hour, type, label, and exact account filters apply consistently to metrics, charts, and the table.

This is a local exploration view. It does not yet implement a review queue or store analyst decisions. Supplied fraud labels and existing-rule flags are displayed separately.

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
- The dashboard will show model output and rule-based review priority separately. A priority score must not be presented as a calibrated fraud probability.
- Analyst dispositions are feedback for later evaluation. They do not immediately retrain a model or become verified labels.
- External notifications and consequential actions require explicit authorization.

## Deployment direction

Develop the analytics workflow locally. Add PostgreSQL only when shared application state or concurrent use requires it. Add Docker when the application has a useful runnable workflow. AWS storage, hosting, credentials, and monitoring belong to the deployment phase.

An LLM call will receive a structured case-evidence object. It will not calculate features, generate fraud probabilities, choose financial actions, or execute arbitrary SQL.
