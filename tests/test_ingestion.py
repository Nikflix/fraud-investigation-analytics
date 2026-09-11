from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys

import duckdb
import pytest

from fraud_analytics.cli import main
from fraud_analytics.config import ValidationConfig
from fraud_analytics.ingestion.load_transactions import InvalidBatchError, load_transactions


CONFIG = ValidationConfig(frozenset({"TRANSFER"}))


def transaction(**changes: str) -> dict[str, str]:
    return {
        "transaction_id": "TX-001",
        "timestamp": "2026-09-01T14:30:00.123456+05:30",
        "source_account": "0001",
        "destination_account": "0002",
        "amount": "125.10",
        "transaction_type": "TRANSFER",
        "source_balance_before": "500.10",
        "source_balance_after": "375.00",
        "is_fraud": "",
        **changes,
    }


def test_load_preserves_values_and_provenance(tmp_path: Path) -> None:
    database = tmp_path / "processed" / "fraud.duckdb"
    unknown = transaction()
    negative = transaction(transaction_id="TX-002", is_fraud="0", source_balance_before="0")
    positive = transaction(transaction_id="TX-003", is_fraud="1")
    del positive["source_balance_after"]
    records = [unknown, negative, positive]
    original = [row.copy() for row in records]

    assert load_transactions(records, CONFIG, database, source_file="sample's.csv") == 3
    assert records == original

    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        rows = connection.execute("""
            SELECT transaction_id, timestamp, source_account, destination_account,
                   amount, source_balance_before, source_balance_after, is_fraud,
                   source_timestamp, source_file, source_row_number, ingested_at
            FROM transactions ORDER BY transaction_id
        """).fetchall()

    assert len(rows) == 3
    assert rows[0][1:8] == (
        datetime(2026, 9, 1, 9, 0, 0, 123456, tzinfo=UTC),
        "0001", "0002", Decimal("125.10"), Decimal("500.10"), Decimal("375.00"), None,
    )
    assert rows[0][8:11] == (unknown["timestamp"], "sample's.csv", 2)
    assert rows[0][11].tzinfo is not None
    assert rows[1][5] == Decimal("0.00")
    assert [row[7] for row in rows] == [None, False, True]
    assert rows[2][6] is None
    assert [row[10] for row in rows] == [2, 3, 4]


@pytest.mark.parametrize("existing_amount", ["125.10", "50.00"])
def test_duplicate_rolls_back_new_rows_without_overwriting_history(
    tmp_path: Path, existing_amount: str
) -> None:
    database = tmp_path / "fraud.duckdb"
    load_transactions([transaction()], CONFIG, database, source_file="first.csv")

    # Insert a new row before the conflict to verify rollback of partial work.
    batch = [transaction(transaction_id="TX-NEW"), transaction(amount=existing_amount)]
    with pytest.raises(duckdb.ConstraintException):
        load_transactions(batch, CONFIG, database, source_file="second.csv")

    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT transaction_id, amount, source_file FROM transactions"
        ).fetchall() == [("TX-001", Decimal("125.10"), "first.csv")]

    assert load_transactions(
        [transaction(transaction_id="TX-002")], CONFIG, database, source_file="third.csv"
    ) == 1
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM transactions").fetchone() == (2,)


@pytest.mark.parametrize("records", [
    [],
    [transaction(), transaction()],
    [transaction(), transaction(transaction_id="TX-BAD", amount="-1")],
])
def test_invalid_batch_does_not_create_database(tmp_path: Path, records: list[dict[str, str]]) -> None:
    database = tmp_path / "fraud.duckdb"
    with pytest.raises(InvalidBatchError) as error:
        load_transactions(records, CONFIG, database, source_file="invalid.csv")
    assert not error.value.report.is_valid
    assert not database.exists()


@pytest.mark.parametrize("changes", [
    {"amount": "125.101"},
    {"amount": "10000000000000000"},
    {"source_balance_before": "500.101"},
    {"source_balance_after": "375.001"},
    {"timestamp": "2026-09-01T09:00:00.1234567Z"},
    {"timestamp": "0001-01-01T00:00:00+01:00"},
])
def test_unrepresentable_values_reject_batch_before_storage(
    tmp_path: Path, changes: dict[str, str]
) -> None:
    database = tmp_path / "fraud.duckdb"
    records = [transaction(), transaction(transaction_id="TX-BAD", **changes)]
    with pytest.raises(ValueError, match="Record 3:"):
        load_transactions(records, CONFIG, database, source_file="precision.csv")
    assert not database.exists()


def test_decimal_boundary_and_trailing_zeroes_remain_exact(tmp_path: Path) -> None:
    database = tmp_path / "fraud.duckdb"
    records = [
        transaction(amount="9999999999999999.99"),
        transaction(transaction_id="TX-002", amount="0.0100"),
    ]
    load_transactions(records, CONFIG, database, source_file="boundaries.csv")
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT amount FROM transactions ORDER BY transaction_id"
        ).fetchall() == [(Decimal("9999999999999999.99"),), (Decimal("0.01"),)]


def test_cli_load_and_repeat_have_clear_exit_codes(tmp_path: Path, monkeypatch, capsys) -> None:
    database = tmp_path / "fraud.duckdb"
    monkeypatch.setattr(sys, "argv", [
        "fraud-analytics", "ingest", "data/sample/transactions.csv", "--database", str(database),
    ])

    assert main() == 0
    assert json.loads(capsys.readouterr().out) == {"database": str(database), "inserted_rows": 6}
    assert main() == 1
    assert capsys.readouterr().out == ""

    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM transactions").fetchone() == (6,)
