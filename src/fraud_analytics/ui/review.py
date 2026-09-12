import math
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from fraud_analytics.detection.features import (
    explain_score, feature_matrix, parse_transaction, predict_scores, rule_reasons,
)
from fraud_analytics.detection.pipeline import build_analysis, load_detection_config
from fraud_analytics.detection.review import (
    QUEUE_TYPES, REVIEW_STATUSES, case_evidence, latest_run, review_queue, save_review,
)
from fraud_analytics.ingestion.paysim import TRANSACTION_TYPES


def ensure_analysis(database, info):
    run = latest_run(database)
    if run is not None:
        return run
    st.info("Build the baseline to score later transactions and create a review queue.")
    st.write(
        "The model learns from earlier simulation hours. A separate validation period sets "
        "the review threshold, then the final period is scored and evaluated."
    )
    if info["row_count"] < 1000:
        st.warning("This dataset is too small for training. Select the full PaySim database in the sidebar.")
    if st.button("Build review queue", type="primary", disabled=info["row_count"] < 1000):
        try:
            with st.status("Building the review queue", expanded=True) as status:
                config_path = Path("configs/detection.toml")
                config = load_detection_config(config_path if config_path.is_file() else None)
                build_analysis(database, config, progress=status.write)
                status.update(label="Review queue is ready", state="complete")
            st.rerun()
        except (ValueError, OSError, duckdb.Error) as error:
            st.error(f"Could not build the review queue: {error}")
    return None


def _percent(value):
    return "—" if value is None else f"{value:.2%}"


def _evidence_panel(database, run, row_number):
    evidence = case_evidence(database, run, row_number)
    record = evidence["transaction"]
    st.markdown(f"#### Transaction {row_number:,}")
    st.caption(
        f"Hour {record['simulation_step']} · {record['transaction_type']} · "
        f"Source {record['source_account']} · Destination {record['destination_account']}"
    )
    left, right = st.columns(2)
    left.metric("Amount", f"{record['amount']:,.2f}")
    right.metric("Model score", f"{record['model_score']:.6f}")
    st.write(f"Source balance before transaction: **{record['source_balance_before']:,.2f}**")
    if record["model_alert"]:
        st.write(f"Score exceeds the review threshold of **{run['threshold']:.6f}**.")
    else:
        st.write(f"Score is below or equal to the review threshold of **{run['threshold']:.6f}**.")
    reasons = rule_reasons(record, run["rules"])
    for reason in reasons:
        st.write(f"• {reason}")
    if not reasons:
        st.caption("Neither of the two rules triggered for this transaction.")
    with st.expander("Model factors"):
        st.dataframe(
            pd.DataFrame(explain_score(run["model"], record)[:4]),
            hide_index=True, width="stretch",
            column_config={"factor": "Factor", "direction": "Effect", "contribution": st.column_config.NumberColumn("Contribution", format="%.3f")},
        )
        st.caption("Contributions are in log-odds relative to the training mean. They describe the fitted model, not causal effects.")
    with st.expander("Earlier account activity"):
        history = evidence["earlier_transactions"]
        if history:
            frame = pd.DataFrame(history)
            frame["amount"] = frame["amount"].map(lambda value: f"{value:,.2f}")
            st.dataframe(frame, hide_index=True, width="stretch")
        else:
            st.info("No earlier records involving either account were found.")
        st.caption("Up to 20 records involving either account. Same-hour and future activity are excluded.")

    key = f"{run['dataset_sha256']}_{row_number}"
    with st.form(f"review_{key}"):
        status = st.selectbox(
            "Review status", REVIEW_STATUSES,
            index=REVIEW_STATUSES.index(record["review_status"]), key=f"status_{key}",
        )
        note = st.text_area("Review note", value=record["review_note"], max_chars=4000, key=f"note_{key}")
        submitted = st.form_submit_button("Save review", type="primary")
    if submitted:
        try:
            save_review(database, run, row_number, status, note)
            st.session_state["review_notice"] = "Review saved."
            st.rerun()
        except (ValueError, OSError, duckdb.Error) as error:
            st.error(f"Could not save the review: {error}")
    with st.expander("Review history"):
        if evidence["review_history"]:
            st.dataframe(pd.DataFrame(evidence["review_history"]), hide_index=True, width="stretch")
        else:
            st.caption("No review notes saved yet.")
    if st.checkbox("Show supplied label for learning", key=f"label_{key}"):
        st.write("Supplied label: **" + ("Fraud labelled" if record["is_fraud"] else "Not fraud labelled") + "**")
        st.caption("This label was not an input to this transaction's score. Review notes do not change it.")


def render_review_queue(database, info):
    st.subheader("Review queue")
    run = ensure_analysis(database, info)
    if run is None:
        return
    if notice := st.session_state.pop("review_notice", None):
        st.success(notice)
    test = run["metrics"]["test"]
    st.caption(
        f"Scored test period · Simulation hours {run['validation_end'] + 1}–{run['metrics']['last_step']} · "
        "Model scores rank synthetic transactions; probability calibration has not been validated."
    )
    columns = st.columns(3)
    columns[0].metric("Scored transactions", f"{test['records']:,}")
    columns[1].metric("Model alerts", f"{test['model']['alerts']:,}")
    columns[2].metric("Rule alerts", f"{test['rules']['alerts']:,}")
    with st.expander("Measured performance"):
        performance = []
        for method in ("model", "rules"):
            result = test[method]
            performance.append({
                "Method": "Logistic regression" if method == "model" else "Either rule",
                "Alerts": result["alerts"], "Precision": _percent(result["precision"]),
                "Recall": _percent(result["recall"]), "False-positive rate": _percent(result["false_positive_rate"]),
            })
        st.dataframe(pd.DataFrame(performance), hide_index=True, width="stretch")
        st.write(f"Model average precision: **{test['model']['average_precision']:.4f}**.")
        st.caption(
            f"Threshold selected for at most {run['config']['review_fraction']:.1%} of validation records. "
            f"Observed test alert rate: {test['model']['alert_fraction']:.2%}. "
            "A fixed threshold does not guarantee the same workload in a later period."
        )
        st.caption("These are results on synthetic data. AP summarizes the precision–recall curve; it is not accuracy.")
    filters = st.columns(2)
    queue_type = filters[0].selectbox("Queue", QUEUE_TYPES)
    status = filters[1].selectbox("Status filter", ("All", *REVIEW_STATUSES))
    signature = (str(database), run["run_id"], queue_type, status)
    if st.session_state.get("queue_filter_signature") != signature:
        st.session_state["queue_page"] = 1
        st.session_state["queue_filter_signature"] = signature
    page = st.session_state.get("queue_page", 1)
    count, rows = review_queue(database, run, queue_type, status, offset=(page - 1) * 100)
    if not count:
        st.info("No transactions match this queue and review status.")
        return
    max_page = math.ceil(count / 100)
    if page > max_page:
        page = 1
        st.session_state["queue_page"] = page
        count, rows = review_queue(database, run, queue_type, status)
    st.number_input("Queue page", 1, max_page, step=1, key="queue_page")
    table, detail = st.columns([1.2, 1])
    with table:
        st.caption(f"{count:,} matching transactions · Highest model score first")
        frame = pd.DataFrame(rows)
        frame["amount"] = frame["amount"].map(lambda value: f"{value:,.2f}")
        st.dataframe(
            frame[["source_row_number", "simulation_step", "transaction_type", "amount", "model_score", "review_status"]],
            hide_index=True, width="stretch", height=400,
            column_config={
                "source_row_number": "Row", "simulation_step": "Hour",
                "transaction_type": "Type", "amount": "Amount", "review_status": "Status",
                "model_score": st.column_config.NumberColumn("Model score", format="%.4f"),
            },
        )
    with detail:
        options = [row["source_row_number"] for row in rows]
        selected = st.selectbox("Inspect transaction", options, format_func=lambda row: f"Source row {row:,}")
        _evidence_panel(database, run, selected)


def render_try_transaction(database, info):
    st.subheader("Try a transaction")
    run = ensure_analysis(database, info)
    if run is None:
        return
    st.write("Enter transaction details to get a new model score and rule checks.")
    st.caption("This is a what-if check using the saved baseline. It does not send money or add a record to the original dataset.")
    with st.form("score_transaction"):
        kind = st.selectbox("Transaction type", TRANSACTION_TYPES, index=4)
        amount = st.text_input("Amount", value="900.00")
        balance = st.text_input("Source balance before transaction", value="1000.00")
        submitted = st.form_submit_button("Score transaction", type="primary")
    if submitted:
        try:
            record = parse_transaction(kind, amount, balance)
            score = float(predict_scores(
                run["model"], feature_matrix({key: [value] for key, value in record.items()})
            )[0])
            st.session_state["whatif_result"] = {"run_id": run["run_id"], "record": record, "score": score}
        except ValueError as error:
            st.session_state.pop("whatif_result", None)
            st.error(str(error))
    result = st.session_state.get("whatif_result")
    if not result or result["run_id"] != run["run_id"]:
        return
    record, score = result["record"], result["score"]
    st.caption(
        f"Scored input: {record['transaction_type']} · Amount {record['amount']:,.2f} · "
        f"Source balance {record['source_balance_before']:,.2f}"
    )
    st.metric("Model score", f"{score:.6f}")
    st.write(
        ("**Above the review threshold.**" if score > run["threshold"] else "**Below or equal to the review threshold.**")
        + f" Threshold: {run['threshold']:.6f}."
    )
    st.caption("A low score does not establish that a transaction is legitimate. Calibration on real transactions has not been assessed.")
    reasons = rule_reasons(record, run["rules"])
    for reason in reasons:
        st.write(f"• {reason}")
    if not reasons:
        st.write("Neither of the two rules triggered.")
    st.dataframe(pd.DataFrame(explain_score(run["model"], record)[:4]), hide_index=True, width="stretch")
    st.caption("Factors explain the fitted model in log-odds relative to the training mean. No dataset label is used for this new score.")
