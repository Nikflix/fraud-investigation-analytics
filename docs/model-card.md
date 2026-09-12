# Initial PaySim detection baseline

Version 0.2.0 adds a local, reproducible scoring and review workflow. This baseline ranks synthetic transactions for analyst inspection. It does not establish real-world detection quality or calibrated fraud probabilities.

## Recorded run

The run completed on 2026-09-12 using the full [recorded PaySim snapshot](paysim.md).

| Attribute | Value |
| --- | --- |
| CSV SHA-256 | `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b` |
| Analysis ID | `2c2d991f4fcbaeaef5dcc504ac736e2e51127e8d62e7d236a83516b90370369a` |
| Algorithm / feature version | `logistic-rules-v1` / `1` |
| Python / DuckDB | 3.12.14 / 1.5.5 |
| NumPy / pandas / scikit-learn | 2.5.3 / 3.0.5 / 1.9.1 |
| Streamlit | 1.63.0 |
| Fit | Logistic regression, L2 regularization, C=1, lbfgs, max_iter=400 |
| Convergence | 14 iterations; convergence warnings cause analysis to fail |
| Model alert condition | Score strictly greater than 0.014564149417366749 |

Full-precision counts and metrics are recorded in [baseline-results.json](baseline-results.json). The raw source, fitted parameters, transaction scores, and notes stay in the local database and are excluded from Git.

## Inputs and availability

The feature function reads only transaction type, requested amount, and source balance before the transaction. It creates:

| Feature | Transformation |
| --- | --- |
| Amount | `log1p(amount)` |
| Source balance | `log1p(source_balance_before)` |
| Amount relative to balance | `log1p(min(amount / positive balance, 1000))`; zero when balance is zero |
| Source balance is zero | Binary indicator |
| Transaction type | Five one-hot columns for the allowed PaySim types |

The nine columns are standardized using training means and scales. No class weighting, oversampling, downsampling, or hyperparameter search is applied.

Labels, supplied existing-rule flags, account IDs, simulation hour, destination balances, and post-transaction balances are excluded from model inputs. Training labels are the supplied `isFraud` values; validation and test labels are used for reported evaluation.

This assumes transaction type, amount, and the recorded source balance are available before execution. The CSV cannot establish live-system balance freshness or when historical fraud labels became available. The offline experiment assumes training labels are known when the model is fitted; label-delay effects are not measured. A zero balance is a source value, not independently verified account state.

## Chronological evaluation

Boundaries use cumulative row counts targeting 70% training and a further 15% validation. Every record from the same simulation hour stays in one period. Row positions identify records; they do not establish event order within an hour.

| Period | Simulation hours | Records | Supplied fraud labels | Label prevalence |
| --- | --- | ---: | ---: | ---: |
| Training | 1–323 | 4,463,587 | 3,643 | 0.08162% |
| Validation | 324–378 | 980,416 | 564 | 0.05753% |
| Test | 379–743 | 918,617 | 4,006 | 0.43609% |

Training alone fits the model, preprocessing, and large-amount rule cutoff. The model threshold uses the validation score distribution to select at most 1% of validation rows. Labels are not needed to choose that threshold. Strict `score > threshold` comparison excludes boundary ties rather than exceeding the budget.

The same model and threshold score the test period. Tests verify that changing test labels cannot change coefficients, rule cutoffs, or the threshold. All 918,617 test scores are saved; training and validation rows are not put into the review queue.

The dataset was previously inspected in aggregate. Treat these results as an exploratory chronological baseline, not a sealed external benchmark. Future tuning after seeing these results needs a new evaluation protocol rather than repeatedly optimizing on this test period.

## Transparent rule comparison

Both rules apply only to `TRANSFER` or `CASH_OUT`:

1. Requested amount is at least the training outgoing-amount 99.5th percentile: **3,354,182.22 dataset units**.
2. Requested amount is at least **80%** of a strictly positive source balance before the transaction.

The reported rule alerts are the union of these rules. They are independent of model alerts and of the CSV's `isFlaggedFraud` field. Amount/balance comparisons use integer cents. Zero-amount records remain in evaluation.

## Measured results

| Period / method | Alerts | True positives | False positives | False negatives | Precision | Recall | False-positive rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Validation / model | 9,804 | 359 | 9,445 | 205 | 3.66% | 63.65% | 0.964% |
| Validation / rules | 193,986 | 564 | 193,422 | 0 | 0.29% | 100.00% | 19.740% |
| Test / model | 11,316 | 2,631 | 8,685 | 1,375 | 23.25% | 65.68% | 0.950% |
| Test / rules | 182,750 | 3,992 | 178,758 | 14 | 2.18% | 99.65% | 19.545% |

Model average precision is **0.3012** on validation and **0.5292** on test. This uses scikit-learn's average precision calculation, not classification accuracy or trapezoidal PR-AUC.

The fixed threshold flags **1.232%** of test transactions, compared with approximately 1% on validation. Rule alerts cover **19.894%** of test transactions. Review capacity on validation is therefore not a guarantee of future workload.

Test label prevalence is about **7.6 times** validation prevalence. Precision and average precision depend on the class distribution; their increase must not be attributed solely to better discrimination. The model still produces many false alerts and misses 34.32% of the supplied test fraud labels. The rule union catches more labels but generates substantially more review work.

## Review and explanation

The interface sorts saved transactions by model score. Each case shows rule reasons and the largest additive model contributions in log-odds relative to training means. The five type-column contributions are grouped into the actual transaction type. These describe the fitted model, not causal explanations or verified suspicious behaviour.

Evidence includes up to 20 earlier records involving either account. Same-hour and future records are excluded. This history is for inspection and is not a feature of this baseline. Most source IDs occur once, so an empty history cannot establish normality or novelty.

Review status and notes persist separately from source labels, with timestamped save events. The new-transaction form uses the same feature and inference functions to score entered values. It is a local what-if calculation, not a live transaction feed or automatic decision.

## Reproduce and verify

From the repository root, with the full dataset already imported:

```bash
python -m pip install -e ".[dev,app]"
fraud-analytics analyze-paysim --database data/processed/paysim.duckdb --config configs/detection.toml
python -m streamlit run app/overview.py
```

The app's **Build review queue** button calls the same pipeline. At least 1,000 input records, three nonempty periods, and both label classes in each period are required. This minimum is a guard against tiny demos, not a claim of statistical sufficiency. Model training materializes narrow numeric inputs in memory and has greater memory needs than browsing.

The run identity combines dataset fingerprint, configuration, feature version, and algorithm version. Repeating it returns the saved run and retains reviews. Changing configuration creates a different run; the app shows the most recently created one. Changing numerical-library versions may affect retraining slightly. The recorded versions support comparison, but the dependency ranges are not an environment lock.

The automated suite checks excluded inputs, inference parity with scikit-learn, chronological boundaries, threshold ties, exact-cent rules, label independence, rerun reuse, review persistence, and Streamlit interactions using temporary fixtures.

A separate full-data Streamlit AppTest on a disposable copy verified queue totals, its final page of 16 model alerts, case history cutoffs, saved reviews and event history, unchanged source labels, new-input score changes, and reuse without losing reviews. This verifies execution and displayed values; browser layout, Windows execution, and concurrent-user behaviour were not tested.

## Limits and next work

This experiment does not measure real-world calibration, delayed labels, drift monitoring, streaming latency, multi-user review, graph detection, or LLM summary quality. It does not estimate prevented losses. Follow-up work should develop structured account evidence, test supported relationship features, and evaluate evidence-grounded summaries separately from detector performance.

Implementation references: [LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html), [average_precision_score](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html), and [avoiding data leakage](https://scikit-learn.org/stable/common_pitfalls.html).
