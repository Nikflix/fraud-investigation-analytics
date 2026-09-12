"""Run from the repository root: python -m streamlit run app/overview.py."""

from decimal import Decimal
import hashlib
import math
import os
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from fraud_analytics.analytics.paysim import (
    TransactionFilters, account_coverage, dataset_info, step_summary,
    transaction_page, transaction_summary, type_summary,
)
from fraud_analytics.ingestion.paysim import TRANSACTION_TYPES
from fraud_analytics.ui.review import render_review_queue, render_try_transaction


st.set_page_config(page_title="Fraud Risk Analytics", page_icon="🔎", layout="wide")


@st.cache_data(show_spinner=False, max_entries=4)
def load_metadata(database: str, version: tuple[int, int]):
    return dataset_info(database), account_coverage(database)


@st.cache_data(show_spinner=False, max_entries=32)
def load_overview(database: str, version: tuple[int, int], filters: TransactionFilters):
    return (
        transaction_summary(database, filters),
        step_summary(database, filters),
        type_summary(database, filters),
    )


@st.cache_data(show_spinner=False, max_entries=32)
def load_page(database: str, version: tuple[int, int], filters: TransactionFilters, page: int):
    return transaction_page(database, filters, page)


def compact_amount(value: Decimal) -> str:
    for scale, suffix in ((10**12, "T"), (10**9, "B"), (10**6, "M")):
        if value >= scale:
            return f"{value / scale:.3f}{suffix}"
    return f"{value:,.2f}"


def style_chart(figure):
    figure.update_layout(
        template="plotly_white", height=280, margin=dict(l=12, r=12, t=12, b=12),
        font=dict(family="Arial", size=14, color="#16243D"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    figure.update_yaxes(gridcolor="#E5EAF3", rangemode="tozero")
    return figure


def choose_database():
    configured = Path(os.environ.get("FRAUD_DATABASE_PATH", "data/processed/paysim.duckdb")).resolve()
    options = [configured]
    labels = {configured: configured.stem}
    candidates = sorted(set(Path("data/processed").resolve().glob("*.duckdb")) | {configured})
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            with duckdb.connect(str(candidate), read_only=True) as connection:
                row = connection.execute("SELECT row_count FROM paysim_dataset").fetchone()
            if row:
                labels[candidate] = f"{candidate.stem} · {row[0]:,} records"
                if candidate not in options:
                    options.append(candidate)
        except (OSError, duckdb.Error):
            continue
    selected = st.sidebar.selectbox("Dataset", options, format_func=lambda path: labels.get(path, path.stem))
    if st.session_state.get("active_dataset") != str(selected):
        st.session_state["active_dataset"] = str(selected)
        for key in ("transaction_page", "queue_page", "queue_filter_signature", "whatif_result", "review_notice"):
            st.session_state.pop(key, None)
    return selected


def main():
    st.title("Fraud Risk Analytics")
    st.caption("PaySim · Local scoring and transaction review")
    database = choose_database()
    if not database.is_file():
        st.info("Load a PaySim CSV or ZIP to open the transaction overview.")
        st.code('fraud-analytics ingest-paysim "path/to/archive.zip"', language="bash")
        st.markdown(
            "[Open the setup guide](https://github.com/Nikflix/"
            "fraud-investigation-analytics/blob/main/docs/local-setup.md)"
        )
        return

    try:
        stat = database.stat()
        version = (stat.st_mtime_ns, stat.st_size)
        info, coverage = load_metadata(str(database), version)
    except (OSError, ValueError, duckdb.Error):
        st.error("Cannot read the PaySim database. Check the path and finish any running import.")
        return

    fixture = Path(__file__).resolve().parents[1] / "data/sample/paysim.csv"
    if fixture.is_file() and info["sha256"] == hashlib.sha256(fixture.read_bytes()).hexdigest():
        st.warning("Demo dataset: six hand-written records. Select the full PaySim database in the sidebar to build a review queue.")
    st.sidebar.caption(f"Simulation hours {info['first_step']}–{info['last_step']}")
    workspace = st.sidebar.radio("Workspace", ("Review queue", "Try a transaction", "Data overview"))
    try:
        if workspace == "Review queue":
            render_review_queue(database, info)
        elif workspace == "Try a transaction":
            render_try_transaction(database, info)
        else:
            render_overview(database, version, info, coverage)
    except (ValueError, OSError, duckdb.Error) as error:
        st.error(f"Could not open this view: {error}")


def render_overview(database, version, info, coverage):
    st.caption("Data overview · Supplied dataset labels")
    with st.sidebar:
        st.header("Explore transactions")
        st.caption(
            f"{info['row_count']:,} records · Simulation hours "
            f"{info['first_step']}–{info['last_step']}"
        )
        with st.form("transaction_filters"):
            if info["first_step"] < info["last_step"]:
                first_step, last_step = st.slider(
                    "Simulation hour", info["first_step"], info["last_step"],
                    (info["first_step"], info["last_step"]),
                )
            else:
                first_step = last_step = info["first_step"]
                st.caption(f"Simulation hour {first_step}")
            selected_types = st.multiselect(
                "Transaction types", TRANSACTION_TYPES, default=TRANSACTION_TYPES
            )
            selected_label = st.selectbox(
                "Dataset label", ("All labels", "Fraud labelled", "Not fraud labelled")
            )
            account = st.text_input("Exact account ID", placeholder="e.g. C001").strip()
            submitted = st.form_submit_button("Apply filters", type="primary", width="stretch")
        st.caption("One step represents one simulation hour. Calendar dates are not supplied.")

    fraud_label = {
        "All labels": None, "Fraud labelled": True, "Not fraud labelled": False
    }[selected_label]
    filters = TransactionFilters(first_step, last_step, tuple(selected_types), fraud_label, account)
    try:
        summary, hourly, by_type = load_overview(str(database), version, filters)
    except (OSError, ValueError, duckdb.Error):
        st.error("Could not query the database. Finish the import and try again.")
        return

    st.subheader("Transaction overview")
    if account:
        st.caption(f"Records containing {account} as the source or destination account")
    metrics = st.columns(4)
    metrics[0].metric("Transactions", f"{summary['transactions']:,}")
    metrics[1].metric(
        "Recorded amount", compact_amount(summary["total_amount"]),
        help=f"{summary['total_amount']:,.2f} dataset units. This is transaction volume, not losses.",
    )
    metrics[2].metric("Fraud labels", f"{summary['fraud_labels']:,}", help="Supplied isFraud labels.")
    metrics[3].metric(
        "Existing-rule flags", f"{summary['existing_rule_flags']:,}",
        help="Supplied isFlaggedFraud values. These are separate from the fraud labels.",
    )
    rate = summary["fraud_rate"]
    st.caption(
        (f"{rate:.3%} of selected records carry a fraud label. " if rate is not None else "")
        + "Amounts use unspecified dataset units. Model scores are shown separately in the review queue."
    )
    if not summary["transactions"]:
        st.info("No transactions match these filters. Select a transaction type or widen the search.")
        return

    volume, labels = st.columns([2, 1])
    with volume:
        st.markdown("#### Transactions by simulation hour")
        figure = go.Figure(go.Bar(
            x=[row["simulation_step"] for row in hourly],
            y=[row["transactions"] for row in hourly], marker_color="#285ADC",
            hovertemplate="Hour %{x}<br>%{y:,} transactions<extra></extra>",
        ))
        figure.update_xaxes(title="Simulation hour", range=[first_step - 0.5, last_step + 0.5])
        st.plotly_chart(style_chart(figure), width="stretch")
    with labels:
        st.markdown("#### Fraud labels by type")
        figure = go.Figure(go.Bar(
            x=[row["transaction_type"] for row in by_type],
            y=[row["fraud_labels"] for row in by_type], marker_color="#D65B22",
            hovertemplate="%{x}<br>%{y:,} fraud labels<extra></extra>",
        ))
        st.plotly_chart(style_chart(figure), width="stretch")

    st.subheader("Transactions")
    page_count = math.ceil(summary["transactions"] / 100)
    if submitted or st.session_state.get("transaction_page", 1) > page_count:
        st.session_state["transaction_page"] = 1
    page = st.number_input("Page", 1, page_count, step=1, key="transaction_page")
    try:
        rows = load_page(str(database), version, filters, int(page))
    except (OSError, ValueError, duckdb.Error):
        st.error("Could not load this page. Try applying the filters again.")
        return
    st.caption(
        f"Rows {(page - 1) * 100 + 1:,}–{min(page * 100, summary['transactions']):,} "
        f"of {summary['transactions']:,} · Ordered by simulation hour, then source row"
    )
    frame = pd.DataFrame(rows)
    frame["amount"] = frame["amount"].map(lambda value: f"{value:,.2f}")
    frame["is_fraud"] = frame["is_fraud"].map({True: "Fraud labelled", False: "Not fraud labelled"})
    st.dataframe(
        frame, hide_index=True, width="stretch", height=380,
        column_config={
            "source_row_number": "Source row", "simulation_step": "Hour",
            "transaction_type": "Type", "amount": "Amount",
            "source_account": "Source account", "destination_account": "Destination account",
            "is_fraud": "Dataset label",
            "is_flagged_fraud": st.column_config.CheckboxColumn("Existing-rule flag"),
        },
    )

    with st.expander("Dataset notes"):
        singleton_share = 1 - coverage["repeated_source_accounts"] / coverage["source_accounts"]
        st.write(
            f"{singleton_share:.2%} of source account IDs appear once in this snapshot. "
            f"The maximum source account history is {coverage['max_source_transactions']} records. "
            "These records show account appearances; they do not establish account ownership "
            "or a reliable behavioural baseline."
        )
        st.write(
            "Zero-amount transactions are retained. Scoring uses the documented pre-transaction inputs. "
            "Source and destination preserve the dataset "
            "roles and do not imply the direction of funds for every transaction type."
        )
        st.write(
            "Source row is the CSV record position, including the header, not a bank transaction ID. "
            "Rows within an hour have no finer event timestamps. "
            "The repository's six-row sample is hand-written test data."
        )


main()
