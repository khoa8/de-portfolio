-- Phase 07 source contract. This file is safe to apply repeatedly.
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT NOT NULL,
    customer_name VARCHAR(200) NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    status VARCHAR(40) NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT chk_phase07_orders_amount CHECK (amount >= 0)
) ENGINE=InnoDB;
