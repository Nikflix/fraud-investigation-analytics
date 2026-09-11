"""Bulk import of one PaySim CSV snapshot, directly or from a ZIP."""

from contextlib import contextmanager
import csv
from dataclasses import dataclass
import hashlib
from importlib.resources import files
from pathlib import Path
import tempfile
import zipfile

import duckdb


PAYSIM_COLUMNS = (
    "step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud",
)
MONEY_COLUMNS = (
    "amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest",
)
TRANSACTION_TYPES = ("CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER")


@dataclass(frozen=True)
class PaySimLoadResult:
    database: str
    csv_sha256: str
    total_rows: int
    inserted_rows: int
    already_loaded: bool


@contextmanager
def _csv_snapshot(source: Path):
    # Hash and scan the same immutable copy. ZIP member paths are never extracted.
    with tempfile.TemporaryDirectory(prefix="paysim-") as directory:
        snapshot = Path(directory) / "source.csv"
        digest = hashlib.sha256()

        def copy_csv(stream):
            with snapshot.open("wb") as target:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    target.write(chunk)

        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                members = [
                    item for item in archive.infolist()
                    if not item.is_dir() and item.filename.lower().endswith(".csv")
                ]
                if len(members) != 1:
                    raise ValueError("The ZIP must contain exactly one CSV file")
                source_name = Path(members[0].filename).name
                with archive.open(members[0]) as stream:
                    copy_csv(stream)
        elif source.suffix.lower() == ".csv":
            source_name = source.name
            with source.open("rb") as stream:
                copy_csv(stream)
        else:
            raise ValueError("PaySim input must be a .csv or .zip file")

        with snapshot.open(encoding="utf-8-sig", newline="") as stream:
            if tuple(next(csv.reader(stream), ())) != PAYSIM_COLUMNS:
                raise ValueError("CSV header does not match the documented PaySim columns")
        yield snapshot, digest.hexdigest(), source_name


def _check_stage(connection) -> int:
    missing = " OR ".join(f'"{name}" IS NULL OR "{name}" = \'\'' for name in PAYSIM_COLUMNS)
    checks = {
        "missing_fields": f"({missing})",
        "step": "NOT regexp_full_match(step, '[0-9]+') "
                "OR try_cast(step AS INTEGER) IS NULL OR try_cast(step AS INTEGER) < 1",
        "type": "type NOT IN ('CASH_IN', 'CASH_OUT', 'DEBIT', 'PAYMENT', 'TRANSFER')",
        "nameOrig": "NOT regexp_full_match(nameOrig, 'C[0-9]+')",
        "nameDest": "NOT regexp_full_match(nameDest, '[CM][0-9]+')",
        "isFraud": "isFraud NOT IN ('0', '1')",
        "isFlaggedFraud": "isFlaggedFraud NOT IN ('0', '1')",
        **{name: f'NOT paysim_money_valid("{name}")' for name in MONEY_COLUMNS},
    }
    counts = ", ".join(f"count_if({expression})" for expression in checks.values())
    row_count, *invalid_counts = connection.execute(
        f"SELECT count(*), {counts} FROM paysim_stage"
    ).fetchone()
    if not row_count:
        raise ValueError("PaySim input contains no data records")
    failures = [
        f"{name}={count}" for name, count in zip(checks, invalid_counts) if count
    ]
    if failures:
        raise ValueError("PaySim validation failed: " + ", ".join(failures))
    return row_count


def load_paysim(source: Path, database: Path) -> PaySimLoadResult:
    source, database = Path(source).resolve(), Path(database).resolve()
    if source == database:
        raise ValueError("The input and database paths must differ")

    with _csv_snapshot(source) as (snapshot, digest, source_name):
        database.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(database), config={"memory_limit": "1GB", "threads": 4}) as connection:
            connection.execute("SET TimeZone = 'UTC'")
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute(
                    files("fraud_analytics").joinpath("sql/paysim_schema.sql").read_text()
                )
                existing = connection.execute(
                    "SELECT sha256, row_count FROM paysim_dataset"
                ).fetchall()
                stored_rows = connection.execute(
                    "SELECT count(*) FROM paysim_transactions"
                ).fetchone()[0]
                if existing:
                    if existing == [(digest, stored_rows)]:
                        connection.execute("ROLLBACK")
                        return PaySimLoadResult(str(database), digest, stored_rows, 0, True)
                    raise ValueError(
                        "This database contains another snapshot or inconsistent metadata; "
                        "choose a new database path"
                    )
                if stored_rows:
                    raise ValueError("Transactions have no source metadata; choose a new database path")

                connection.execute("""
                    CREATE TEMP TABLE paysim_stage AS
                    SELECT row_number() OVER () + 1 AS source_row_number, *
                    FROM read_csv(?, header=true, all_varchar=true, parallel=false,
                                  delim=',', null_padding=false, strict_mode=true)
                """, [str(snapshot)])
                connection.execute(
                    files("fraud_analytics").joinpath("sql/paysim_money.sql").read_text()
                )
                row_count = _check_stage(connection)
                connection.execute("""
                    INSERT INTO paysim_transactions
                    SELECT source_row_number, cast(step AS INTEGER), type,
                           cast(amount AS DECIMAL(18, 2)), nameOrig,
                           cast(oldbalanceOrg AS DECIMAL(18, 2)),
                           cast(newbalanceOrig AS DECIMAL(18, 2)), nameDest,
                           cast(oldbalanceDest AS DECIMAL(18, 2)),
                           cast(newbalanceDest AS DECIMAL(18, 2)),
                           isFraud = '1', isFlaggedFraud = '1'
                    FROM paysim_stage
                """)
                connection.execute(
                    "INSERT INTO paysim_dataset (sha256, source_name, row_count) VALUES (?, ?, ?)",
                    [digest, source_name, row_count],
                )
                connection.execute("COMMIT")
            except (ValueError, duckdb.Error):
                connection.execute("ROLLBACK")
                raise
    return PaySimLoadResult(str(database), digest, row_count, row_count, False)
