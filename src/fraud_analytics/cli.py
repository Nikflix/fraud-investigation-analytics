import argparse
import csv
from dataclasses import asdict
import json
import logging
from pathlib import Path

import duckdb

from fraud_analytics.config import load_config
from fraud_analytics.ingestion.load_transactions import InvalidBatchError, load_transactions
from fraud_analytics.ingestion.sample_csv import read_sample_csv
from fraud_analytics.ingestion.validate_input import ValidationReport, validate_transactions
from fraud_analytics.logging import configure_logging


logger = logging.getLogger(__name__)


def _print_validation_report(report: ValidationReport) -> None:
    print(json.dumps({
        "total_rows": report.total_rows,
        "valid_rows": report.valid_rows,
        "invalid_rows": report.invalid_rows,
        "issues": [asdict(issue) for issue in report.issues],
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and load transaction data for fraud analytics.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check a CSV against the sample data contract")
    validate.add_argument("input", type=Path)
    validate.add_argument("--config", type=Path, default=Path("configs/project.toml"))
    ingest = commands.add_parser("ingest", help="Validate a CSV and append it to a local DuckDB file")
    ingest.add_argument("input", type=Path)
    ingest.add_argument("--config", type=Path, default=Path("configs/project.toml"))
    ingest.add_argument("--database", type=Path, default=Path("data/processed/fraud.duckdb"))
    args = parser.parse_args()

    try:
        configure_logging()
        config = load_config(args.config)
        records = read_sample_csv(args.input)
    except (OSError, ValueError, csv.Error) as error:
        logger.error("Cannot read input or configuration: %s", error)
        return 2

    if args.command == "validate":
        report = validate_transactions(records, config)
        _print_validation_report(report)
        return 0 if report.is_valid else 1

    if args.database.resolve() in (args.input.resolve(), args.config.resolve()):
        logger.error("The database path must differ from the input and configuration paths")
        return 2

    try:
        inserted_rows = load_transactions(
            records, config, args.database, source_file=args.input.as_posix()
        )
    except InvalidBatchError as error:
        _print_validation_report(error.report)
        logger.error("Batch failed validation; no rows were loaded")
        return 1
    except ValueError as error:
        logger.error("Batch cannot be stored: %s; no rows were loaded", error)
        return 1
    except duckdb.ConstraintException:
        logger.error(
            "Batch rejected by database constraints; a transaction ID may already be loaded. "
            "No rows were added. Use a new database path for a separate copy of the sample."
        )
        return 1
    except (OSError, duckdb.Error) as error:
        logger.error(
            "Database operation failed (%s). Check the file path, file lock, and table schema.",
            type(error).__name__,
        )
        return 2

    print(json.dumps({
        "database": str(args.database),
        "inserted_rows": inserted_rows,
    }, indent=2))
    return 0
