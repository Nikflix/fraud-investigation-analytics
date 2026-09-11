# Architecture notes

The implemented workflow reads the sample CSV, validates every record, converts supported values to explicit types, and appends the complete batch to a local DuckDB table. The command records basic provenance and rejects duplicate transaction IDs across loads. Features, scoring, investigations, and the dashboard remain planned.

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
