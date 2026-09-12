"""Fit an earlier period, select a threshold on validation, and score the test period."""

from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction
import hashlib
from importlib.resources import files
import json
import logging
import math
from pathlib import Path
import tomllib
import warnings

import duckdb
import numpy as np
import pandas as pd
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from fraud_analytics.detection.features import (
    FEATURE_NAMES, FEATURE_VERSION, feature_matrix, predict_scores, rule_flags,
)


logger = logging.getLogger(__name__)
ALGORITHM_VERSION = "logistic-rules-v1"


@dataclass(frozen=True)
class DetectionConfig:
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    review_fraction: float = 0.01
    min_records: int = 1000
    large_amount_quantile: float = 0.995
    balance_share: float = 0.80

    def __post_init__(self):
        if not (0 < self.train_fraction < 1 and 0 < self.validation_fraction < 1
                and self.train_fraction + self.validation_fraction < 1):
            raise ValueError("Training, validation and test fractions must all be positive")
        if not 0 < self.review_fraction < 1:
            raise ValueError("Review fraction must lie between 0 and 1")
        if not 0 < self.large_amount_quantile < 1 or not 0 < self.balance_share <= 1:
            raise ValueError("Invalid rule thresholds")
        if Fraction(Decimal(str(self.balance_share))).denominator > 10000:
            raise ValueError("Balance-share threshold must use at most four decimal places")
        if not isinstance(self.min_records, int) or self.min_records < 1000:
            raise ValueError("At least 1,000 input records are required for this baseline")


def load_detection_config(path: Path | None = None) -> DetectionConfig:
    if path is None:
        return DetectionConfig()
    with Path(path).open("rb") as stream:
        raw = tomllib.load(stream)
    if set(raw) - {"detection", "rules"}:
        raise ValueError("Unknown detection configuration section")
    try:
        return DetectionConfig(**raw.get("detection", {}), **raw.get("rules", {}))
    except TypeError as error:
        raise ValueError("Unknown or repeated detection configuration setting") from error


def chronological_boundaries(connection, config: DetectionConfig) -> tuple[int, int]:
    # Approximate row fractions, retaining all ties within the same simulation hour.
    boundaries = connection.execute("""
        WITH counts AS (
            SELECT simulation_step, count(*) AS n FROM paysim_transactions
            GROUP BY simulation_step
        ), cumulative AS (
            SELECT *, sum(n) OVER (ORDER BY simulation_step) AS seen, sum(n) OVER () AS total
            FROM counts
        )
        SELECT min(simulation_step) FILTER (WHERE seen >= total * ?),
               min(simulation_step) FILTER (WHERE seen >= total * ?),
               max(simulation_step)
        FROM cumulative
    """, [config.train_fraction, config.train_fraction + config.validation_fraction]).fetchone()
    train_end, validation_end, last_step = boundaries
    if train_end is None or not train_end < validation_end < last_step:
        raise ValueError("Need enough distinct simulation hours for three nonempty periods")
    return train_end, validation_end


def review_threshold(scores: np.ndarray, fraction: float) -> float:
    if not len(scores) or not np.isfinite(scores).all():
        raise ValueError("Validation scores must be finite and nonempty")
    if not 0 < fraction < 1:
        raise ValueError("Review fraction must lie between 0 and 1")
    budget = math.floor(len(scores) * fraction)
    if budget == 0:
        return float(scores.max())
    if budget >= len(scores):
        raise ValueError("Review budget must be smaller than the validation period")
    # Strictly greater than this boundary. Tied scores cannot exceed the chosen budget.
    return float(np.partition(scores, len(scores) - budget - 1)[len(scores) - budget - 1])


def alert_metrics(labels: np.ndarray, selected: np.ndarray) -> dict:
    labels, selected = labels.astype(bool), selected.astype(bool)
    true_positive = int((labels & selected).sum())
    false_positive = int((~labels & selected).sum())
    positives, negatives, alerts = int(labels.sum()), int((~labels).sum()), int(selected.sum())
    return {
        "alerts": alerts, "alert_fraction": alerts / len(labels),
        "true_positives": true_positive, "false_positives": false_positive,
        "false_negatives": positives - true_positive, "true_negatives": negatives - false_positive,
        "precision": true_positive / alerts if alerts else None,
        "recall": true_positive / positives if positives else None,
        "false_positive_rate": false_positive / negatives if negatives else None,
    }


def evaluate_period(records, scores, threshold, rules) -> dict:
    labels = records["is_fraud"].to_numpy(dtype=bool)
    large, high_share = rule_flags(records, rules)
    return {
        "records": len(labels), "fraud_labels": int(labels.sum()),
        "fraud_rate": float(labels.mean()),
        "model": {
            **alert_metrics(labels, scores > threshold),
            "average_precision": float(average_precision_score(labels, scores)),
        },
        "rules": alert_metrics(labels, large | high_share),
    }


def _period(connection, first_exclusive: int, last_inclusive: int):
    frame = connection.execute("""
        SELECT source_row_number, cast(amount AS DOUBLE) AS amount,
               cast(source_balance_before AS DOUBLE) AS source_balance_before,
               cast(amount * 100 AS BIGINT) AS amount_cents,
               cast(source_balance_before * 100 AS BIGINT) AS source_balance_cents,
               transaction_type, is_fraud
        FROM paysim_transactions WHERE simulation_step > ? AND simulation_step <= ?
        ORDER BY source_row_number
    """, [first_exclusive, last_inclusive]).fetchdf()
    frame["transaction_type"] = frame["transaction_type"].astype("category")
    if frame["is_fraud"].nunique() != 2:
        raise ValueError("Each chronological period must contain both supplied label classes")
    return frame


def build_analysis(database: Path | str, config: DetectionConfig | None = None, progress=None) -> dict:
    config = config or DetectionConfig()
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError("Import the full PaySim dataset before building the review queue")

    def report(message):
        logger.info(message)
        if progress is not None:
            progress(message)

    with duckdb.connect(str(database), config={"memory_limit": "1GB", "threads": 4}) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        source = connection.execute("SELECT sha256, row_count FROM paysim_dataset").fetchall()
        if len(source) != 1 or source[0][1] < config.min_records:
            raise ValueError("Load at least 1,000 PaySim records. The six-row demo is only for exploration.")
        dataset_sha, row_count = source[0]
        if connection.execute("SELECT count(*) FROM paysim_transactions").fetchone()[0] != row_count:
            raise ValueError("Stored records do not match the imported snapshot metadata")
        signature = json.dumps({
            "dataset_sha256": dataset_sha, "config": asdict(config),
            "algorithm": ALGORITHM_VERSION, "feature_version": FEATURE_VERSION,
        }, sort_keys=True)
        run_id = hashlib.sha256(signature.encode()).hexdigest()
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        if "detection_runs" in tables:
            existing = connection.execute(
                "SELECT metrics_json FROM detection_runs WHERE run_id = ?", [run_id]
            ).fetchone()
            if existing:
                metrics = json.loads(existing[0])
                stored = connection.execute(
                    "SELECT count(*) FROM transaction_scores WHERE run_id = ?", [run_id]
                ).fetchone()[0]
                if stored != metrics["test"]["records"]:
                    raise ValueError("Stored scores do not match this analysis; use a fresh database")
                return {"run_id": run_id, "reused": True, "metrics": metrics}

        train_end, validation_end = chronological_boundaries(connection, config)
        last_step = connection.execute("SELECT max(simulation_step) FROM paysim_transactions").fetchone()[0]
        report("Fitting the baseline on the earlier training period")
        training = _period(connection, 0, train_end)
        training_summary = {"records": len(training), "fraud_labels": int(training["is_fraud"].sum())}
        values, labels = feature_matrix(training), training["is_fraud"].to_numpy(dtype=bool)
        del training
        scaler = StandardScaler(copy=False)
        scaled = scaler.fit_transform(values)
        estimator = LogisticRegression(C=1.0, max_iter=400, solver="lbfgs")
        with warnings.catch_warnings(), threadpool_limits(limits=4):
            warnings.simplefilter("error", ConvergenceWarning)
            try:
                estimator.fit(scaled, labels)
            except ConvergenceWarning as error:
                raise ValueError("The baseline did not converge; inspect the data before using its scores") from error
        model = {
            "algorithm": ALGORITHM_VERSION, "feature_version": FEATURE_VERSION,
            "feature_names": list(FEATURE_NAMES), "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(), "weights": estimator.coef_[0].tolist(),
            "intercept": float(estimator.intercept_[0]), "iterations": int(estimator.n_iter_[0]),
            "sklearn_version": sklearn.__version__,
        }
        del values, scaled, labels, estimator, scaler
        large_threshold = connection.execute("""
            SELECT quantile_cont(amount, ?) FROM paysim_transactions
            WHERE simulation_step <= ? AND transaction_type IN ('TRANSFER', 'CASH_OUT')
        """, [config.large_amount_quantile, train_end]).fetchone()[0]
        if large_threshold is None or large_threshold <= 0:
            raise ValueError("Training data needs positive outgoing amounts for the rule baseline")
        rules = {
            "large_amount_threshold": float(large_threshold),
            "large_amount_quantile": config.large_amount_quantile,
            "balance_share": config.balance_share,
        }
        report("Selecting a review threshold from validation scores")
        validation = _period(connection, train_end, validation_end)
        validation_scores = predict_scores(model, feature_matrix(validation))
        threshold = review_threshold(validation_scores, config.review_fraction)
        validation_metrics = evaluate_period(validation, validation_scores, threshold, rules)
        del validation, validation_scores
        report("Scoring the later test period and measuring results")
        test = _period(connection, validation_end, last_step)
        scores = predict_scores(model, feature_matrix(test))
        metrics = {
            "train_end": train_end, "validation_end": validation_end, "last_step": last_step,
            "training": training_summary, "validation": validation_metrics,
            "test": evaluate_period(test, scores, threshold, rules),
        }
        large, high_share = rule_flags(test, rules)
        score_frame = pd.DataFrame({
            "source_row_number": test["source_row_number"], "model_score": scores,
            "model_alert": scores > threshold, "large_amount": large, "high_balance_share": high_share,
        })
        connection.register("new_scores", score_frame)
        report("Saving the model, evaluation and review queue")
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(files("fraud_analytics").joinpath("sql/detection_schema.sql").read_text())
            connection.execute("""
                INSERT INTO detection_runs
                    (run_id, dataset_sha256, train_end, validation_end, threshold,
                     model_json, rules_json, config_json, metrics_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                run_id, dataset_sha, train_end, validation_end, threshold,
                json.dumps(model), json.dumps(rules), json.dumps(asdict(config)), json.dumps(metrics),
            ])
            connection.execute("INSERT INTO transaction_scores SELECT ?, * FROM new_scores", [run_id])
            connection.execute("COMMIT")
        except duckdb.Error:
            connection.execute("ROLLBACK")
            raise
    return {"run_id": run_id, "reused": False, "metrics": metrics}
