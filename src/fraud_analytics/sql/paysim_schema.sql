CREATE TABLE IF NOT EXISTS paysim_dataset (
    sha256 VARCHAR PRIMARY KEY,
    source_name VARCHAR NOT NULL,
    row_count BIGINT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS paysim_transactions (
    source_row_number BIGINT PRIMARY KEY,
    simulation_step INTEGER NOT NULL CHECK (simulation_step > 0),
    transaction_type VARCHAR NOT NULL,
    amount DECIMAL(18, 2) NOT NULL CHECK (amount >= 0),
    source_account VARCHAR NOT NULL,
    source_balance_before DECIMAL(18, 2) NOT NULL,
    source_balance_after DECIMAL(18, 2) NOT NULL,
    destination_account VARCHAR NOT NULL,
    destination_balance_before DECIMAL(18, 2) NOT NULL,
    destination_balance_after DECIMAL(18, 2) NOT NULL,
    is_fraud BOOLEAN NOT NULL,
    is_flagged_fraud BOOLEAN NOT NULL
);
