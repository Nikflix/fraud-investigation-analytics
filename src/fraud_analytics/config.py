from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ValidationConfig:
    allowed_transaction_types: frozenset[str]


def load_config(path: Path) -> ValidationConfig:
    with path.open("rb") as handle:
        settings = tomllib.load(handle)

    validation = settings.get("validation", {})
    if not isinstance(validation, dict):
        raise ValueError("validation must be a TOML table")
    transaction_types = validation.get("allowed_transaction_types")
    if (
        not isinstance(transaction_types, list)
        or not transaction_types
        or any(not isinstance(value, str) or not value.strip() for value in transaction_types)
    ):
        raise ValueError("validation.allowed_transaction_types must be a nonempty list of strings")

    return ValidationConfig(frozenset(value.strip() for value in transaction_types))
