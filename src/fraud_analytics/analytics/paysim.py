"""Shared, parameterized queries for the PaySim CLI and application."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import duckdb

from fraud_analytics.ingestion.paysim import TRANSACTION_TYPES


@dataclass(frozen=True)
class TransactionFilters:
    first_step: int
    last_step: int
    transaction_types: tuple[str, ...] = TRANSACTION_TYPES
    fraud_label: bool | None = None
    account: str = ""

    def __post_init__(self):
        if self.first_step < 1 or self.last_step < self.first_step:
            raise ValueError("Invalid simulation step range")
        if not set(self.transaction_types).issubset(TRANSACTION_TYPES):
            raise ValueError("Unknown transaction type")


def _where(filters: TransactionFilters) -> tuple[str, list]:
    clauses = ["simulation_step BETWEEN ? AND ?"]
    parameters = [filters.first_step, filters.last_step]
    if filters.transaction_types:
        placeholders = ", ".join("?" for _ in filters.transaction_types)
        clauses.append(f"transaction_type IN ({placeholders})")
        parameters.extend(filters.transaction_types)
    else:
        clauses.append("FALSE")
    if filters.fraud_label is not None:
        clauses.append("is_fraud = ?")
        parameters.append(filters.fraud_label)
    if filters.account:
        clauses.append("(source_account = ? OR destination_account = ?)")
        parameters.extend([filters.account, filters.account])
    return " AND ".join(clauses), parameters


def _query(database: Path | str, sql: str, parameters=()) -> list[dict]:
    with duckdb.connect(str(database), read_only=True) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        result = connection.execute(sql, parameters)
        names = [column[0] for column in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()]


def dataset_info(database: Path | str) -> dict:
    rows = _query(database, """
        SELECT d.*, min(t.simulation_step) AS first_step, max(t.simulation_step) AS last_step
        FROM paysim_dataset d CROSS JOIN paysim_transactions t
        GROUP BY ALL
    """)
    if len(rows) != 1:
        raise ValueError("Load exactly one PaySim snapshot before opening the overview")
    return rows[0]


def transaction_summary(database: Path | str, filters: TransactionFilters) -> dict:
    where, parameters = _where(filters)
    result = _query(database, f"""
        SELECT count(*) AS transactions, coalesce(sum(amount), 0) AS total_amount,
               coalesce(count_if(is_fraud), 0) AS fraud_labels,
               coalesce(count_if(is_flagged_fraud), 0) AS existing_rule_flags
        FROM paysim_transactions WHERE {where}
    """, parameters)[0]
    result["fraud_rate"] = (
        Decimal(result["fraud_labels"]) / result["transactions"] if result["transactions"] else None
    )
    return result


def step_summary(database: Path | str, filters: TransactionFilters) -> list[dict]:
    where, parameters = _where(filters)
    return _query(database, f"""
        SELECT simulation_step, count(*) AS transactions, count_if(is_fraud) AS fraud_labels
        FROM paysim_transactions WHERE {where}
        GROUP BY simulation_step ORDER BY simulation_step
    """, parameters)


def type_summary(database: Path | str, filters: TransactionFilters) -> list[dict]:
    where, parameters = _where(filters)
    return _query(database, f"""
        SELECT transaction_type, count(*) AS transactions, count_if(is_fraud) AS fraud_labels,
               sum(amount) AS total_amount
        FROM paysim_transactions WHERE {where}
        GROUP BY transaction_type ORDER BY transaction_type
    """, parameters)


def transaction_page(
    database: Path | str, filters: TransactionFilters, page: int = 1, page_size: int = 100
) -> list[dict]:
    if page < 1 or not 1 <= page_size <= 500:
        raise ValueError("Page must be positive and page size must be between 1 and 500")
    where, parameters = _where(filters)
    return _query(database, f"""
        SELECT source_row_number, simulation_step, transaction_type, amount,
               source_account, destination_account, is_fraud, is_flagged_fraud
        FROM paysim_transactions WHERE {where}
        ORDER BY simulation_step, source_row_number LIMIT ? OFFSET ?
    """, [*parameters, page_size, (page - 1) * page_size])


def account_coverage(database: Path | str) -> dict:
    return _query(database, """
        SELECT count(*) AS source_accounts, count_if(n > 1) AS repeated_source_accounts,
               max(n) AS max_source_transactions,
               coalesce(sum(n) FILTER (WHERE n > 1), 0) AS rows_from_repeated_sources
        FROM (SELECT source_account, count(*) AS n
              FROM paysim_transactions GROUP BY source_account)
    """)[0]


def profile_dataset(database: Path | str) -> dict:
    info = dataset_info(database)
    filters = TransactionFilters(info["first_step"], info["last_step"])
    details = _query(database, """
        SELECT count(DISTINCT simulation_step) AS observed_steps,
               count(DISTINCT destination_account) AS destination_accounts,
               count_if(amount = 0) AS zero_amount_rows,
               count_if(amount = 0 AND is_fraud) AS zero_amount_fraud_labels,
               min(amount) AS min_amount, max(amount) AS max_amount,
               count_if(starts_with(destination_account, 'M')) AS merchant_destination_rows
        FROM paysim_transactions
    """)[0]
    return {
        "dataset": info,
        "overview": {**transaction_summary(database, filters), **details},
        "by_type": type_summary(database, filters),
        "source_account_coverage": account_coverage(database),
    }
