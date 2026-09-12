import csv
from decimal import Decimal

import pytest

from fraud_analytics.ingestion.paysim import PAYSIM_COLUMNS, load_paysim


@pytest.fixture
def make_detection_database(tmp_path):
    """A generated test fixture, with both classes in each chronological period."""
    def create(name="baseline", flip_test_labels=False):
        source = tmp_path / f"{name}.csv"
        with source.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(PAYSIM_COLUMNS)
            for step in range(1, 101):
                for slot in range(12):
                    kind = ("PAYMENT", "TRANSFER", "CASH_OUT", "DEBIT", "CASH_IN")[slot % 5]
                    balance = Decimal(1000 + (step * 19 + slot * 71) % 1300)
                    fraud = slot in (1, 7) and step % 4 != 0
                    amount = (balance * Decimal(".96")).quantize(Decimal(".01")) if fraud else Decimal(3 + (step * 37 + slot * 103) % 997)
                    label = not fraud if flip_test_labels and step > 85 else fraud
                    writer.writerow([
                        step, kind, amount, f"C{step * 100 + slot}", balance,
                        max(0, balance - amount), f"C{900000 + slot}", 1000, 1000 + amount,
                        int(label), int(fraud),
                    ])
        database = tmp_path / f"{name}.duckdb"
        load_paysim(source, database)
        return database
    return create
