"""Read saved scores and retain analyst notes separately from dataset labels."""

import json
from pathlib import Path
from uuid import uuid4

import duckdb

from fraud_analytics.analytics.paysim import _query


REVIEW_STATUSES = ("New", "In review", "Closed")
QUEUE_TYPES = ("Model alerts", "Rule alerts", "All scored transactions")


def latest_run(database: Path | str) -> dict | None:
    tables = _query(database, "SHOW TABLES")
    if not any(row["name"] == "detection_runs" for row in tables):
        return None
    rows = _query(database, """
        SELECT r.* FROM detection_runs r
        JOIN paysim_dataset d ON d.sha256 = r.dataset_sha256
        ORDER BY r.created_at DESC, r.run_id DESC LIMIT 1
    """)
    if not rows:
        return None
    result = rows[0]
    for name in ("model", "rules", "config", "metrics"):
        result[name] = json.loads(result.pop(f"{name}_json"))
    return result


def review_queue(database, run: dict, queue_type="Model alerts", status="All", limit=100, offset=0):
    if queue_type not in QUEUE_TYPES or status not in (*REVIEW_STATUSES, "All"):
        raise ValueError("Unknown review queue filter")
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid queue page")
    condition = {
        "Model alerts": "s.model_alert",
        "Rule alerts": "(s.large_amount OR s.high_balance_share)",
        "All scored transactions": "TRUE",
    }[queue_type]
    clauses = ["s.run_id = ?", condition]
    parameters = [run["dataset_sha256"], run["run_id"]]
    if status != "All":
        clauses.append("coalesce(r.status, 'New') = ?")
        parameters.append(status)
    relation = f"""
        FROM transaction_scores s
        JOIN paysim_transactions t USING (source_row_number)
        LEFT JOIN case_reviews r
            ON r.source_row_number = s.source_row_number AND r.dataset_sha256 = ?
        WHERE {" AND ".join(clauses)}
    """
    count = _query(database, "SELECT count(*) AS n " + relation, parameters)[0]["n"]
    rows = _query(database, """
        SELECT t.source_row_number, t.simulation_step, t.transaction_type, t.amount,
               t.source_account, t.destination_account, s.model_score, s.model_alert,
               s.large_amount, s.high_balance_share, coalesce(r.status, 'New') AS review_status
    """ + relation + " ORDER BY s.model_score DESC, t.source_row_number LIMIT ? OFFSET ?",
        [*parameters, limit, offset])
    return count, rows


def case_evidence(database, run: dict, source_row_number: int) -> dict:
    rows = _query(database, """
        SELECT t.*, s.model_score, s.model_alert, s.large_amount, s.high_balance_share,
               coalesce(r.status, 'New') AS review_status, coalesce(r.note, '') AS review_note
        FROM transaction_scores s
        JOIN paysim_transactions t USING (source_row_number)
        LEFT JOIN case_reviews r
            ON r.source_row_number = s.source_row_number AND r.dataset_sha256 = ?
        WHERE s.run_id = ? AND s.source_row_number = ?
    """, [run["dataset_sha256"], run["run_id"], source_row_number])
    if not rows:
        raise ValueError("This transaction is not in the selected analysis")
    transaction = rows[0]
    accounts = [transaction["source_account"], transaction["destination_account"]]
    history = _query(database, """
        SELECT source_row_number, simulation_step, transaction_type, amount,
               source_account, destination_account
        FROM paysim_transactions
        WHERE simulation_step < ? AND (source_account IN (?, ?) OR destination_account IN (?, ?))
        ORDER BY simulation_step DESC, source_row_number DESC LIMIT 20
    """, [transaction["simulation_step"], *accounts, *accounts])
    events = _query(database, """
        SELECT created_at, status, note FROM review_events
        WHERE dataset_sha256 = ? AND source_row_number = ?
        ORDER BY created_at DESC, event_id DESC LIMIT 20
    """, [run["dataset_sha256"], source_row_number])
    return {"transaction": transaction, "earlier_transactions": history, "review_history": events}


def save_review(database, run: dict, source_row_number: int, status: str, note: str):
    if status not in REVIEW_STATUSES:
        raise ValueError("Unknown review status")
    if not isinstance(note, str) or len(note) > 4000:
        raise ValueError("Review notes must be text of at most 4,000 characters")
    # A stale page must not write notes to an unrelated/replaced dataset.
    with duckdb.connect(str(database)) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        valid = connection.execute("""
            SELECT count(*) FROM transaction_scores s
            JOIN detection_runs r USING (run_id)
            JOIN paysim_dataset d ON d.sha256 = r.dataset_sha256
            WHERE s.run_id = ? AND s.source_row_number = ? AND d.sha256 = ?
        """, [run["run_id"], source_row_number, run["dataset_sha256"]]).fetchone()[0]
        if valid != 1:
            raise ValueError("The selected transaction no longer belongs to this dataset and analysis")
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute("""
                INSERT INTO case_reviews (dataset_sha256, source_row_number, status, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (dataset_sha256, source_row_number)
                DO UPDATE SET status = excluded.status, note = excluded.note,
                              updated_at = now()
            """, [run["dataset_sha256"], source_row_number, status, note])
            connection.execute("""
                INSERT INTO review_events (event_id, dataset_sha256, source_row_number, status, note)
                VALUES (?, ?, ?, ?, ?)
            """, [str(uuid4()), run["dataset_sha256"], source_row_number, status, note])
            connection.execute("COMMIT")
        except duckdb.Error:
            connection.execute("ROLLBACK")
            raise
