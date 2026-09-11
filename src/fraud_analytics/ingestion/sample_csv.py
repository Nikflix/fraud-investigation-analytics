import csv
import logging
from pathlib import Path


logger = logging.getLogger(__name__)

REQUIRED_FIELDS = (
    "transaction_id",
    "timestamp",
    "source_account",
    "destination_account",
    "amount",
    "transaction_type",
)
OPTIONAL_FIELDS = ("source_balance_before", "source_balance_after", "is_fraud")


def read_sample_csv(path: Path) -> list[dict[str, str]]:
    """Read the sample contract without guessing types or filling missing values.

    A future dataset adapter can return the same string-valued records after
    explicitly mapping its source fields. This reader holds the sample in memory.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        columns = reader.fieldnames
        if not columns:
            raise ValueError("CSV input must have a header")
        if len(columns) != len(set(columns)):
            raise ValueError("CSV header contains duplicate column names")

        missing = set(REQUIRED_FIELDS) - set(columns)
        unexpected = set(columns) - set(REQUIRED_FIELDS + OPTIONAL_FIELDS)
        if missing or unexpected:
            raise ValueError(
                f"CSV schema mismatch: missing={sorted(missing)}, unexpected={sorted(unexpected)}"
            )

        records = []
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV record {row_number} has a different width from the header")
            records.append({field: value.strip() for field, value in row.items()})

    logger.info("Loaded %d transaction records", len(records))
    return records
