"""Inputs available for a hypothetical pre-execution scoring decision."""

from decimal import Decimal, InvalidOperation, ROUND_CEILING
from fractions import Fraction

import numpy as np

from fraud_analytics.ingestion.paysim import TRANSACTION_TYPES


FEATURE_VERSION = 1
FEATURE_NAMES = (
    "log_amount", "log_source_balance", "log_balance_share", "source_balance_zero",
    *(f"type_{name.lower()}" for name in TRANSACTION_TYPES),
)
FEATURE_LABELS = (
    "Transaction amount", "Source balance before transaction",
    "Amount relative to source balance", "Source balance is zero",
    *(f"Type: {name}" for name in TRANSACTION_TYPES),
)
OUTGOING_TYPES = ("TRANSFER", "CASH_OUT")


def feature_matrix(records) -> np.ndarray:
    # Explicit allowlist: labels, IDs, steps and post-transaction balances never enter X.
    amount = np.asarray(records["amount"], dtype=np.float64)
    balance = np.asarray(records["source_balance_before"], dtype=np.float64)
    kinds = np.asarray(records["transaction_type"])
    if (not np.isfinite(amount).all() or not np.isfinite(balance).all()
            or (amount < 0).any() or (balance < 0).any()):
        raise ValueError("Amounts and source balances must be finite and nonnegative")
    if not np.isin(kinds, TRANSACTION_TYPES).all():
        raise ValueError("Unknown transaction type")
    share = np.divide(amount, balance, out=np.zeros_like(amount), where=balance > 0)
    return np.column_stack((
        np.log1p(amount), np.log1p(balance), np.log1p(np.minimum(share, 1000)),
        (balance == 0).astype(float),
        *((kinds == name).astype(float) for name in TRANSACTION_TYPES),
    ))


def rule_flags(records, rules: dict) -> tuple[np.ndarray, np.ndarray]:
    if "amount_cents" in records and "source_balance_cents" in records:
        amount = np.asarray(records["amount_cents"], dtype=np.int64)
        balance = np.asarray(records["source_balance_cents"], dtype=np.int64)
    else:
        amount = np.array([int(Decimal(str(value)) * 100) for value in records["amount"]], dtype=np.int64)
        balance = np.array([int(Decimal(str(value)) * 100) for value in records["source_balance_before"]], dtype=np.int64)
    outgoing = np.isin(np.asarray(records["transaction_type"]), OUTGOING_TYPES)
    large_cutoff = int((Decimal(str(rules["large_amount_threshold"])) * 100).to_integral_value(rounding=ROUND_CEILING))
    share = Fraction(Decimal(str(rules["balance_share"])))
    if not 0 < share <= 1 or share.denominator > 10000:
        raise ValueError("Balance-share threshold must use at most four decimal places")
    # Exact cents, including values like 0.08 / 0.10. Splitting quotient and remainder
    # avoids overflowing int64 when a valid large balance is multiplied by the ratio.
    whole, remainder = np.divmod(balance, share.denominator)
    share_cutoff = (
        whole * share.numerator
        + (remainder * share.numerator + share.denominator - 1) // share.denominator
    )
    large = outgoing & (amount >= large_cutoff)
    high_share = outgoing & (balance > 0) & (amount >= share_cutoff)
    return large, high_share


def rule_reasons(record: dict, rules: dict) -> list[str]:
    large, high_share = rule_flags({key: [value] for key, value in record.items()}, rules)
    reasons = []
    if large[0]:
        reasons.append(
            f"Outgoing amount is at least {rules['large_amount_threshold']:,.2f} dataset units, "
            f"the {rules['large_amount_quantile']:.1%} training cutoff."
        )
    if high_share[0]:
        share = Decimal(str(record["amount"])) / Decimal(str(record["source_balance_before"]))
        reasons.append(
            f"Requested amount is {share:.1%} of the source balance before the transaction "
            f"(rule threshold: {rules['balance_share']:.0%})."
        )
    return reasons


def parse_transaction(kind: str, amount: str, balance: str) -> dict:
    values = []
    for name, text in (("Amount", amount), ("Source balance", balance)):
        try:
            value = Decimal(text.strip())
            if (not value.is_finite() or value < 0 or value > Decimal("9999999999999999.99")
                    or value != value.quantize(Decimal("0.01"))):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError(f"{name} must be nonnegative and fit exactly into two decimal places") from None
        values.append(value)
    if kind not in TRANSACTION_TYPES:
        raise ValueError("Unknown transaction type")
    return {"transaction_type": kind, "amount": values[0], "source_balance_before": values[1]}


def predict_scores(model: dict, features: np.ndarray) -> np.ndarray:
    if model.get("feature_version") != FEATURE_VERSION or model.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("The saved model uses another feature contract; build a new analysis")
    mean, scale, weights = (np.asarray(model[key], dtype=float) for key in ("mean", "scale", "weights"))
    if any(array.shape != (len(FEATURE_NAMES),) for array in (mean, scale, weights)):
        raise ValueError("Saved model dimensions do not match the feature contract")
    if not all(np.isfinite(array).all() for array in (mean, scale, weights)) or (scale <= 0).any():
        raise ValueError("Saved model contains invalid parameters")
    logits = (features - mean) / scale @ weights + model["intercept"]
    # Stable sigmoid, without executable model files or pickle deserialization.
    return np.exp(-np.logaddexp(0, -logits))


def explain_score(model: dict, record: dict) -> list[dict]:
    features = feature_matrix({key: [value] for key, value in record.items()})[0]
    contributions = (features - np.asarray(model["mean"])) / np.asarray(model["scale"]) * model["weights"]
    # Group the one-hot columns so an absent type is not presented as the transaction's type.
    factors = list(zip(FEATURE_LABELS[:4], contributions[:4]))
    factors.append((f"Transaction type: {record['transaction_type']}", float(contributions[4:].sum())))
    result = [
        {"factor": label, "contribution": float(value), "direction": "Raises score" if value > 0 else "Lowers score"}
        for label, value in factors if abs(value) > 1e-8
    ]
    return sorted(result, key=lambda row: abs(row["contribution"]), reverse=True)
