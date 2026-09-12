from dataclasses import asdict
from pathlib import Path

import duckdb
import pytest

pytest.importorskip("sklearn")
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from fraud_analytics.detection.features import (
    FEATURE_NAMES, FEATURE_VERSION, explain_score, feature_matrix, parse_transaction, predict_scores, rule_flags,
)
from fraud_analytics.detection.pipeline import (
    DetectionConfig, build_analysis, load_detection_config, review_threshold,
)
from fraud_analytics.detection.review import case_evidence, latest_run, review_queue, save_review
from fraud_analytics.ingestion.paysim import load_paysim


def test_model_inputs_exclude_labels_ids_time_and_outcome_balances():
    rows = pd.DataFrame({
        "amount": [0, 900, 100], "source_balance_before": [0, 1000, 0],
        "transaction_type": ["CASH_OUT", "TRANSFER", "PAYMENT"],
        "is_fraud": [True, False, True], "is_flagged_fraud": [False, True, False],
        "source_balance_after": [0, 100, 0], "source_account": ["C1", "C2", "C3"],
        "simulation_step": [1, 2, 3],
    })
    original = feature_matrix(rows)
    assert np.isfinite(original).all()
    for name in ("is_fraud", "is_flagged_fraud", "source_balance_after", "source_account", "simulation_step"):
        rows[name] = "changed"
    np.testing.assert_array_equal(original, feature_matrix(rows))


def test_json_model_matches_fitted_sklearn_predictions():
    records = pd.DataFrame({
        "amount": [1, 2, 900, 950, 3, 850],
        "source_balance_before": [1000] * 6,
        "transaction_type": ["TRANSFER"] * 6,
    })
    matrix = feature_matrix(records)
    scaler = StandardScaler().fit(matrix)
    estimator = LogisticRegression().fit(scaler.transform(matrix), [0, 0, 1, 1, 0, 1])
    artifact = {
        "feature_version": FEATURE_VERSION, "feature_names": list(FEATURE_NAMES),
        "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
        "weights": estimator.coef_[0].tolist(), "intercept": float(estimator.intercept_[0]),
    }
    np.testing.assert_allclose(
        predict_scores(artifact, matrix), estimator.predict_proba(scaler.transform(matrix))[:, 1],
        rtol=1e-12, atol=1e-12,
    )
    explanation = explain_score(artifact, records.iloc[0].to_dict())
    logit = sum(row["contribution"] for row in explanation) + artifact["intercept"]
    assert float(1 / (1 + np.exp(-logit))) == pytest.approx(predict_scores(artifact, matrix)[0])
    assert all("type_" not in row["factor"] for row in explanation)


def test_rules_use_pre_transaction_values_and_threshold_ties_respect_budget():
    records = pd.DataFrame({
        "transaction_type": ["TRANSFER", "CASH_IN", "CASH_OUT", "TRANSFER"],
        "amount": [800, 9000, 0, 9000], "source_balance_before": [1000, 1000, 0, 0],
    })
    large, share = rule_flags(records, {"large_amount_threshold": 5000, "balance_share": .8})
    assert large.tolist() == [False, False, False, True]
    assert share.tolist() == [True, False, False, False]
    _, cents_boundary = rule_flags({
        "transaction_type": ["TRANSFER", "TRANSFER"],
        "amount": ["0.08", "0.07"], "source_balance_before": ["0.10", "0.10"],
    }, {"large_amount_threshold": 5000, "balance_share": .8})
    assert cents_boundary.tolist() == [True, False]
    for scores in (np.array([.1, .2, .3, .9, .9]), np.array([.5] * 5)):
        threshold = review_threshold(scores, .2)
        assert int((scores > threshold).sum()) <= 1
    scores = np.array([.1, .2, .9])
    assert not (scores > review_threshold(scores, .01)).any()
    with pytest.raises(ValueError):
        parse_transaction("TRANSFER", "1.001", "100")
    with pytest.raises(ValueError):
        parse_transaction("TRANSFER", "NaN", "100")


def test_test_labels_cannot_change_model_threshold_or_training(make_detection_database):
    first = make_detection_database()
    second = make_detection_database("changed_labels", flip_test_labels=True)
    result = build_analysis(first)
    build_analysis(second)
    original, changed = latest_run(first), latest_run(second)
    assert (original["train_end"], original["validation_end"]) == (70, 85)
    assert original["model"] == changed["model"]
    assert original["threshold"] == changed["threshold"]
    assert original["rules"] == changed["rules"]
    assert original["metrics"]["test"]["fraud_labels"] != changed["metrics"]["test"]["fraud_labels"]
    assert build_analysis(first)["reused"] is True
    assert result["metrics"]["training"]["records"] == 840
    with duckdb.connect(str(first), read_only=True) as connection:
        assert connection.execute("""
            SELECT count(*), min(t.simulation_step) FROM transaction_scores s
            JOIN paysim_transactions t USING (source_row_number)
        """).fetchone() == (180, 86)


def test_reviews_persist_separately_and_case_history_excludes_same_hour(make_detection_database):
    database = make_detection_database()
    build_analysis(database)
    run = latest_run(database)
    count, rows = review_queue(database, run, "All scored transactions")
    assert count == 180 and len(rows) == 100
    row_number = rows[0]["source_row_number"]
    before = case_evidence(database, run, row_number)
    assert before["earlier_transactions"]
    assert all(
        row["simulation_step"] < before["transaction"]["simulation_step"]
        for row in before["earlier_transactions"]
    )
    save_review(database, run, row_number, "In review", "Checking the source balance.")
    save_review(database, run, row_number, "Closed", "Example review; retain the original label.")
    after = case_evidence(database, run, row_number)
    assert after["transaction"]["review_status"] == "Closed"
    assert after["transaction"]["is_fraud"] == before["transaction"]["is_fraud"]
    assert len(after["review_history"]) == 2
    assert review_queue(database, run, "All scored transactions", "Closed")[0] == 1
    with pytest.raises(ValueError):
        save_review(database, run, 1, "Closed", "Unknown source row")


def test_demo_cannot_train_a_misleading_model(tmp_path):
    database = tmp_path / "demo.duckdb"
    load_paysim(Path(__file__).resolve().parents[1] / "data/sample/paysim.csv", database)
    with pytest.raises(ValueError, match="1,000"):
        build_analysis(database)
    assert latest_run(database) is None
    assert asdict(load_detection_config(Path("configs/detection.toml"))) == asdict(DetectionConfig())
