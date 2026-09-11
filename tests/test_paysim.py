import csv
from decimal import Decimal
import hashlib
from importlib.resources import files
from pathlib import Path
import zipfile

import duckdb
import pytest

from fraud_analytics.ingestion.paysim import load_paysim


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample/paysim.csv"


def test_zip_import_preserves_values_and_same_csv_is_a_no_op(tmp_path):
    archive_path = tmp_path / "data.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(SAMPLE, "../../nested/paysim.csv")
    database = tmp_path / "paysim.duckdb"
    result = load_paysim(archive_path, database)
    assert (result.total_rows, result.inserted_rows, result.already_loaded) == (6, 6, False)
    assert result.csv_sha256 == hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("""
            SELECT count(*), sum(amount), count_if(is_fraud), count_if(is_flagged_fraud)
            FROM paysim_transactions
        """).fetchone() == (6, Decimal("10105403.53"), 3, 1)
        assert connection.execute("""
            SELECT source_account, amount, is_fraud
            FROM paysim_transactions WHERE source_row_number = 4
        """).fetchone() == ("C003", Decimal("0.00"), True)
        assert connection.execute("""
            SELECT amount FROM paysim_transactions WHERE source_row_number = 7
        """).fetchone()[0] == Decimal("10102842.03")
        assert connection.execute("SELECT source_name FROM paysim_dataset").fetchone()[0] == "paysim.csv"
    repeat = load_paysim(SAMPLE, database)
    assert (repeat.total_rows, repeat.inserted_rows, repeat.already_loaded) == (6, 0, True)
    assert repeat.csv_sha256 == result.csv_sha256
    assert not (tmp_path / "nested").exists()


def test_different_snapshot_cannot_overwrite_existing_database(tmp_path):
    database = tmp_path / "paysim.duckdb"
    original = load_paysim(SAMPLE, database)
    changed = tmp_path / "changed.csv"
    changed.write_text(SAMPLE.read_text().replace("10.25", "10.26"))
    with pytest.raises(ValueError, match="choose a new database path"):
        load_paysim(changed, database)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT sha256, row_count FROM paysim_dataset").fetchone() == (
            original.csv_sha256, 6
        )
        assert connection.execute("SELECT sum(amount) FROM paysim_transactions").fetchone()[0] == (
            Decimal("10105403.53")
        )


@pytest.mark.parametrize(("field", "value"), [
    ("amount", "1.001"), ("amount", "1e-50"), ("amount", "NaN"),
    ("newbalanceDest", "1e16"), ("step", "1.5"), ("nameOrig", ""),
    ("type", "UNKNOWN"), ("isFraud", "2"),
])
def test_invalid_record_rolls_back_entire_import(tmp_path, field, value):
    with SAMPLE.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        columns = reader.fieldnames
    rows[-1][field] = value
    invalid = tmp_path / "invalid.csv"
    with invalid.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    database = tmp_path / "invalid.duckdb"
    with pytest.raises(ValueError, match="PaySim validation failed"):
        load_paysim(invalid, database)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SHOW TABLES").fetchall() == []


@pytest.mark.parametrize(("value", "expected"), [
    ("1000e-5", True), ("0.0100", True), ("0.000", True),
    ("9.99999999999999999e15", True), ("-1", False),
    ("1e1001", False), ("1e2147483648", False), ("1e-2147483648", False),
])
def test_money_validation_rejects_rounding_and_overflow(value, expected):
    with duckdb.connect() as connection:
        connection.execute(files("fraud_analytics").joinpath("sql/paysim_money.sql").read_text())
        assert connection.execute("SELECT paysim_money_valid(?)", [value]).fetchone()[0] is expected


def test_wrong_schema_and_ambiguous_zip_are_rejected_before_database_creation(tmp_path):
    wrong = tmp_path / "wrong.csv"
    wrong.write_text(SAMPLE.read_text().replace("nameOrig", "source"))
    database = tmp_path / "not-created.duckdb"
    with pytest.raises(ValueError, match="header"):
        load_paysim(wrong, database)
    archive_path = tmp_path / "ambiguous.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(SAMPLE, "one.csv")
        archive.write(SAMPLE, "two.csv")
    with pytest.raises(ValueError, match="exactly one CSV"):
        load_paysim(archive_path, database)
    assert not database.exists()
