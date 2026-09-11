from pathlib import Path

from fraud_analytics.config import ValidationConfig
from fraud_analytics.ingestion.sample_csv import read_sample_csv
from fraud_analytics.ingestion.validate_input import validate_transactions


def test_validation_reports_bad_records_without_changing_input(tmp_path: Path) -> None:
    input_file = tmp_path / "transactions.csv"
    input_file.write_text(
        "transaction_id,timestamp,source_account,destination_account,amount,transaction_type,"
        "source_balance_before,source_balance_after,is_fraud\n"
        "TX-001,2026-09-01T09:00:00+00:00,0001,0002,125.10,TRANSFER,500.10,375.00,\n"
        "TX-002,2026-09-01T10:00:00+00:00,0001,0002,10.00,TRANSFER,,,0\n"
        "TX-002,2026-09-01T10:01:00+00:00,0001,0002,12.00,TRANSFER,,,0\n"
        "TX-004,2026-09-01T10:03:00,,0004,-5.00,UNKNOWN,NaN,,2\n",
        encoding="utf-8",
    )
    records = read_sample_csv(input_file)
    before_validation = [row.copy() for row in records]

    report = validate_transactions(records, ValidationConfig(frozenset({"TRANSFER"})))

    assert not report.is_valid
    assert (report.total_rows, report.valid_rows, report.invalid_rows) == (4, 1, 3)
    assert {(issue.row_number, issue.field, issue.code) for issue in report.issues} == {
        (3, "transaction_id", "duplicate_id"),
        (4, "transaction_id", "duplicate_id"),
        (5, "timestamp", "invalid_timestamp"),
        (5, "source_account", "missing_value"),
        (5, "amount", "invalid_amount"),
        (5, "transaction_type", "unexpected_type"),
        (5, "source_balance_before", "invalid_balance"),
        (5, "is_fraud", "invalid_label"),
    }
    assert records == before_validation
    assert records[0]["source_account"] == "0001"
    assert records[0]["amount"] == "125.10"
    assert records[0]["is_fraud"] == ""
