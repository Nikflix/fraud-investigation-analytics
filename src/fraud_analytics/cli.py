import argparse
import csv
from dataclasses import asdict
import json
import logging
from pathlib import Path

from fraud_analytics.config import load_config
from fraud_analytics.ingestion.sample_csv import read_sample_csv
from fraud_analytics.ingestion.validate_input import validate_transactions
from fraud_analytics.logging import configure_logging


logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate transaction data for fraud analytics.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check a CSV against the sample data contract")
    validate.add_argument("input", type=Path)
    validate.add_argument("--config", type=Path, default=Path("configs/project.toml"))
    args = parser.parse_args()

    try:
        configure_logging()
        config = load_config(args.config)
        records = read_sample_csv(args.input)
    except (OSError, ValueError, csv.Error) as error:
        logger.error("Cannot validate input: %s", error)
        return 2

    report = validate_transactions(records, config)
    print(json.dumps({
        "total_rows": report.total_rows,
        "valid_rows": report.valid_rows,
        "invalid_rows": report.invalid_rows,
        "issues": [asdict(issue) for issue in report.issues],
    }, indent=2))
    return 0 if report.is_valid else 1
