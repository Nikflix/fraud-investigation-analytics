CREATE TABLE IF NOT EXISTS detection_runs (
    run_id VARCHAR PRIMARY KEY,
    dataset_sha256 VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    train_end INTEGER NOT NULL,
    validation_end INTEGER NOT NULL,
    threshold DOUBLE NOT NULL,
    model_json JSON NOT NULL,
    rules_json JSON NOT NULL,
    config_json JSON NOT NULL,
    metrics_json JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS transaction_scores (
    run_id VARCHAR NOT NULL,
    source_row_number BIGINT NOT NULL,
    model_score DOUBLE NOT NULL,
    model_alert BOOLEAN NOT NULL,
    large_amount BOOLEAN NOT NULL,
    high_balance_share BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, source_row_number)
);

CREATE TABLE IF NOT EXISTS case_reviews (
    dataset_sha256 VARCHAR NOT NULL,
    source_row_number BIGINT NOT NULL,
    status VARCHAR NOT NULL CHECK (status IN ('New', 'In review', 'Closed')),
    note VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (dataset_sha256, source_row_number)
);

CREATE TABLE IF NOT EXISTS review_events (
    event_id VARCHAR PRIMARY KEY,
    dataset_sha256 VARCHAR NOT NULL,
    source_row_number BIGINT NOT NULL,
    status VARCHAR NOT NULL,
    note VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
