# Initial implementation decisions

## Keep the first milestone small

The dataset has not been selected. A thin CSV adapter and working validation boundary let us review the input contract before building features or committing to source-specific assumptions. There are no empty application, model, cloud, or agent modules.

The runtime currently uses the standard library. TOML is read with `tomllib`, amounts are checked with `Decimal`, and the first test uses `pytest`. Dataframe libraries, databases, and ML packages will be introduced with the components that use them.

## Preserve ambiguous input for review

The adapter retains IDs and amounts as strings. Missing labels remain unknown. The validator reports every occurrence of a duplicate transaction ID; it does not keep the first row and silently discard the rest. It reports counts and issue locations without printing transaction values in the logs.

## Review the dataset before implementing history features

The next milestone should answer:

1. Can the data be obtained and used under documented terms?
2. Are account IDs stable, and do accounts have enough repeated activity for behavioral baselines?
3. Are both ends of each transfer available? Can merchants be distinguished from customer accounts?
4. What does the timestamp represent, and what is its actual resolution?
5. What do the labels mean, and when would they become available in a real investigation?
6. Do balance fields describe the state before or after execution? Would they be available at the intended scoring time?
7. Are there source-generated flags or other fields that directly leak the target?

Use only lookback windows supported by the data's time resolution. Define how equal timestamps are handled before computing velocity or recipient novelty. Account and graph history must be cut off at the scoring time, including when they are used to explain an evaluation example.

The first trained model should be a logistic regression baseline with chronological train, validation, and test periods. Fit preprocessing on the training partition. Select thresholds on validation data against an explicit review capacity. Keep the test period for final evaluation.

## Repository scope

The repository includes fictional sample records and executable code. Raw datasets, processed data, local environments, credentials, and model outputs are ignored by Git. The supplied architecture image is retained as a concept reference; the README describes the actual implementation status.

The CI workflow uses the documented [checkout](https://github.com/actions/checkout) and [setup-python](https://github.com/actions/setup-python) actions with read-only repository permissions and Python 3.12.
