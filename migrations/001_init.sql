CREATE TABLE stock_events (
    id          BIGSERIAL PRIMARY KEY,
    event_type  VARCHAR(16)  NOT NULL CHECK (event_type IN ('receipt', 'issue')),
    sku         VARCHAR(64)  NOT NULL,
    warehouse   VARCHAR(64)  NOT NULL,
    qty         INTEGER      NOT NULL CHECK (qty > 0),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_stock_events_wh_sku ON stock_events (warehouse, sku);

CREATE TABLE stock_agg (
    warehouse   VARCHAR(64)  NOT NULL,
    sku         VARCHAR(64)  NOT NULL,
    qty         BIGINT       NOT NULL,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (warehouse, sku)
);
