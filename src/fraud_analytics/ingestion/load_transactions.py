from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
import logging
from pathlib import Path
import re

import duckdb

from fraud_analytics.config import ValidationConfig
from fraud_analytics.ingestion.validate_input import ValidationReport, validate_transactions


logger = logging.getLogger(__name__)

_STORAGE_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
)

_CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id VARCHAR PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    source_account VARCHAR NOT NULL,
    destination_account VARCHAR NOT NULL,
    amount DECIMAL(18, 2) NOT NULL CHECK (amount > 0),
    transaction_type VARCHAR NOT NULL,
    source_balance_before DECIMAL(18, 2) CHECK (source_balance_before >= 0),
    source_balance_after DECIMAL(18, 2) CHECK (source_balance_after >= 0),
    is_fraud BOOLEAN,
    source_timestamp VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL,
    source_row_number BIGINT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
)
"""

_INSERT_TRANSACTIONS = """
INSERT INTO transactions (
    transaction_id, timestamp, source_account, destination_account,
    amount, transaction_type, source_balance_before, source_balance_after,
    is_fraud, source_timestamp, source_file, source_row_number
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class InvalidBatchError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("Batch failed validation; no rows were loaded")
        self.report = report


def _storage_amount(value: str, row_number: int, field: str) -> Decimal | None:
    if not value:
        return None
    amount = Decimal(value)
    # DuckDB can round when casting to a fixed scale. Reject that loss here.
    with localcontext() as context:
        context.prec = 18
        try:
            stored = amount.quantize(Decimal("0.01"))
        except InvalidOperation:
            stored = None
    if stored is None or stored != amount:
        raise ValueError(
            f"Record {row_number}: {field} must fit DECIMAL(18, 2) exactly; "
            "at most 16 integer digits and 2 fractional digits are supported"
        )
    return stored


def _storage_timestamp(value: str, row_number: int) -> datetime:
    if not _STORAGE_TIMESTAMP.fullmatch(value):
        raise ValueError(
            f"Record {row_number}: storage requires YYYY-MM-DDTHH:MM:SS "
            "with optional 1-6 fractional digits and Z or a +/-HH:MM offset"
        )
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (ValueError, OverflowError) as error:
        raise ValueError(f"Record {row_number}: timestamp is outside the supported UTC range") from error


def load_transactions(
    records: list[dict[str, str]],
    config: ValidationConfig,
    database: Path,
    *,
    source_file: str,
) -> int:
    """Validate and append a small batch, rejecting the whole batch on failure.

    Transaction IDs are unique across the database. Reloading an existing ID
    fails rather than silently skipping a row or overwriting its stored values.
    """
    report = validate_transactions(records, config)
    if not report.is_valid:
        raise InvalidBatchError(report)

    rows = []
    for row_number, row in enumerate(records, start=2):
        label = row.get("is_fraud", "")
        rows.append((
            row["transaction_id"],
            _storage_timestamp(row["timestamp"], row_number),
            row["source_account"],
            row["destination_account"],
            _storage_amount(row["amount"], row_number, "amount"),
            row["transaction_type"],
            _storage_amount(row.get("source_balance_before", ""), row_number, "source_balance_before"),
            _storage_amount(row.get("source_balance_after", ""), row_number, "source_balance_after"),
            None if label == "" else label == "1",
            row["timestamp"],
            source_file,
            row_number,
        ))

    # Resolve the path so DuckDB's special ':memory:' name cannot discard a load.
    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database)) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        connection.begin()
        try:
            connection.execute(_CREATE_TRANSACTIONS)
            connection.executemany(_INSERT_TRANSACTIONS, rows)
            connection.commit()
        except duckdb.Error:
            connection.rollback()
            raise

    logger.info("Stored %d transactions in %s", len(rows), database)
    return len(rows)
