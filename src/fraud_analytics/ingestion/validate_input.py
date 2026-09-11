from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging

from fraud_analytics.config import ValidationConfig
from fraud_analytics.ingestion.sample_csv import REQUIRED_FIELDS


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationIssue:
    row_number: int
    field: str
    code: str


@dataclass(frozen=True)
class ValidationReport:
    total_rows: int
    issues: tuple[ValidationIssue, ...]

    @property
    def invalid_rows(self) -> int:
        return len({issue.row_number for issue in self.issues if issue.row_number > 0})

    @property
    def valid_rows(self) -> int:
        return self.total_rows - self.invalid_rows

    @property
    def is_valid(self) -> bool:
        return not self.issues


def _valid_money(value: str, *, allow_zero: bool) -> bool:
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return False
    return amount.is_finite() and (amount >= 0 if allow_zero else amount > 0)


def _valid_timestamp(value: str) -> bool:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return False
    return timestamp.tzinfo is not None and timestamp.utcoffset() is not None


def validate_transactions(
    records: list[dict[str, str]], config: ValidationConfig
) -> ValidationReport:
    """Report problems without dropping, correcting, or scoring input records.

    Record numbers include the header, so the first data record is 2. A row
    number of 0 denotes a file-level issue. Labels remain optional and unknown
    labels are never converted to a negative fraud label.
    """
    issues: list[ValidationIssue] = []
    id_rows: dict[str, list[int]] = {}

    if not records:
        issues.append(ValidationIssue(0, "file", "empty_input"))

    for row_number, row in enumerate(records, start=2):
        for field in REQUIRED_FIELDS:
            if not row.get(field, ""):
                issues.append(ValidationIssue(row_number, field, "missing_value"))

        transaction_id = row.get("transaction_id", "")
        if transaction_id:
            id_rows.setdefault(transaction_id, []).append(row_number)

        timestamp = row.get("timestamp", "")
        if timestamp and not _valid_timestamp(timestamp):
            issues.append(ValidationIssue(row_number, "timestamp", "invalid_timestamp"))

        amount = row.get("amount", "")
        if amount and not _valid_money(amount, allow_zero=False):
            issues.append(ValidationIssue(row_number, "amount", "invalid_amount"))

        transaction_type = row.get("transaction_type", "")
        if transaction_type and transaction_type not in config.allowed_transaction_types:
            issues.append(ValidationIssue(row_number, "transaction_type", "unexpected_type"))

        for field in ("source_balance_before", "source_balance_after"):
            balance = row.get(field, "")
            if balance and not _valid_money(balance, allow_zero=True):
                issues.append(ValidationIssue(row_number, field, "invalid_balance"))

        if row.get("is_fraud", "") not in ("", "0", "1"):
            issues.append(ValidationIssue(row_number, "is_fraud", "invalid_label"))

    # Reject every occurrence: retaining the first duplicate would silently
    # choose between potentially conflicting descriptions of one transaction.
    for row_numbers in id_rows.values():
        if len(row_numbers) > 1:
            issues.extend(
                ValidationIssue(row_number, "transaction_id", "duplicate_id")
                for row_number in row_numbers
            )

    report = ValidationReport(
        len(records), tuple(sorted(issues, key=lambda issue: (issue.row_number, issue.field)))
    )
    logger.info(
        "Validated %d records: %d valid, %d invalid",
        report.total_rows,
        report.valid_rows,
        report.invalid_rows,
    )
    return report
