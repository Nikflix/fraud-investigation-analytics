from decimal import Decimal
from pathlib import Path

from fraud_analytics.analytics.paysim import (
    TransactionFilters, account_coverage, profile_dataset, step_summary,
    transaction_page, transaction_summary, type_summary,
)
from fraud_analytics.ingestion.paysim import load_paysim


def test_shared_filters_preserve_totals_labels_pagination_and_exact_account_search(tmp_path):
    database = tmp_path / "paysim.duckdb"
    load_paysim(Path(__file__).resolve().parents[1] / "data/sample/paysim.csv", database)
    filters = TransactionFilters(1, 3)
    summary = transaction_summary(database, filters)
    assert summary == {
        "transactions": 6, "total_amount": Decimal("10105403.53"),
        "fraud_labels": 3, "existing_rule_flags": 1, "fraud_rate": Decimal("0.5"),
    }
    assert sum(row["transactions"] for row in step_summary(database, filters)) == 6
    assert sum(row["fraud_labels"] for row in type_summary(database, filters)) == 3
    assert [row["source_row_number"] for row in transaction_page(database, filters, 1, 2)] == [2, 3]
    assert [row["source_row_number"] for row in transaction_page(database, filters, 2, 2)] == [4, 5]
    account = transaction_summary(database, TransactionFilters(1, 2, account="C099"))
    assert (account["transactions"], account["total_amount"]) == (2, Decimal("2500.00"))
    assert transaction_summary(
        database, TransactionFilters(1, 3, fraud_label=False, account="C001")
    )["transactions"] == 2
    assert transaction_summary(
        database, TransactionFilters(1, 3, transaction_types=("DEBIT",))
    )["transactions"] == 1
    for empty in (
        TransactionFilters(1, 3, transaction_types=()),
        TransactionFilters(1, 3, account="' OR TRUE --"),
    ):
        result = transaction_summary(database, empty)
        assert result["transactions"] == 0
        assert result["fraud_rate"] is None
    assert account_coverage(database) == {
        "source_accounts": 5, "repeated_source_accounts": 1,
        "max_source_transactions": 2, "rows_from_repeated_sources": 2,
    }
    profile = profile_dataset(database)
    assert profile["overview"]["zero_amount_rows"] == 1
    assert profile["overview"]["zero_amount_fraud_labels"] == 1
    assert profile["overview"]["observed_steps"] == 3
