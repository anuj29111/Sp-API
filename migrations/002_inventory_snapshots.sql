-- Migration: Create monthly inventory snapshots table
-- Run this migration via Supabase MCP or SQL editor
--
-- Purpose: Capture inventory state on 1st of each month for:
-- 1. Inventory turnover calculations
-- 2. Historical inventory analysis
-- 3. Year-over-year comparisons

-- ============================================================
-- STEP 1: Create monthly snapshots table
-- ============================================================

CREATE TABLE IF NOT EXISTS sp_inventory_monthly_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Snapshot identification
    snapshot_date DATE NOT NULL,  -- Always 1st of month (e.g., 2026-02-01)
    marketplace_id UUID NOT NULL REFERENCES marketplaces(id),

    -- Product identification
    sku TEXT NOT NULL,
    asin TEXT,
    fnsku TEXT,
    product_name TEXT,

    -- Inventory quantities (captured from sp_fba_inventory)
    fulfillable_quantity INTEGER DEFAULT 0,
    reserved_quantity INTEGER DEFAULT 0,
    reserved_fc_transfers INTEGER DEFAULT 0,
    reserved_fc_processing INTEGER DEFAULT 0,
    reserved_customer_orders INTEGER DEFAULT 0,
    inbound_working_quantity INTEGER DEFAULT 0,
    inbound_shipped_quantity INTEGER DEFAULT 0,
    inbound_receiving_quantity INTEGER DEFAULT 0,
    unfulfillable_quantity INTEGER DEFAULT 0,
    researching_quantity INTEGER DEFAULT 0,

    -- Computed totals
    total_quantity INTEGER GENERATED ALWAYS AS (
        COALESCE(fulfillable_quantity, 0) +
        COALESCE(reserved_quantity, 0) +
        COALESCE(inbound_working_quantity, 0) +
        COALESCE(inbound_shipped_quantity, 0) +
        COALESCE(inbound_receiving_quantity, 0) +
        COALESCE(unfulfillable_quantity, 0) +
        COALESCE(researching_quantity, 0)
    ) STORED,

    -- Metadata
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    source_date DATE,  -- The actual date the source data was from (may be 2nd if 1st missed)

    -- Constraints
    UNIQUE(snapshot_date, marketplace_id, sku)
);

-- ============================================================
-- STEP 2: Create indexes for fast lookups
-- ============================================================

-- Primary lookup: by snapshot date
CREATE INDEX idx_inv_snapshot_date ON sp_inventory_monthly_snapshots(snapshot_date);

-- By marketplace and date (for filtering)
CREATE INDEX idx_inv_snapshot_mp_date ON sp_inventory_monthly_snapshots(marketplace_id, snapshot_date);

-- By SKU (for product-specific history)
CREATE INDEX idx_inv_snapshot_sku ON sp_inventory_monthly_snapshots(sku);

-- By ASIN (for product-specific history)
CREATE INDEX idx_inv_snapshot_asin ON sp_inventory_monthly_snapshots(asin);

-- Composite for common queries
CREATE INDEX idx_inv_snapshot_mp_sku ON sp_inventory_monthly_snapshots(marketplace_id, sku);


-- ============================================================
-- STEP 3: Create view for easy inventory turnover calculation
-- ============================================================

CREATE OR REPLACE VIEW sp_inventory_turnover AS
SELECT
    curr.marketplace_id,
    curr.sku,
    curr.asin,
    curr.product_name,
    curr.snapshot_date AS current_month,
    prev.snapshot_date AS previous_month,
    curr.total_quantity AS current_qty,
    prev.total_quantity AS previous_qty,
    curr.total_quantity - COALESCE(prev.total_quantity, 0) AS qty_change,
    CASE
        WHEN prev.total_quantity > 0 THEN
            ROUND(((curr.total_quantity - prev.total_quantity)::numeric / prev.total_quantity * 100), 2)
        ELSE NULL
    END AS pct_change
FROM sp_inventory_monthly_snapshots curr
LEFT JOIN sp_inventory_monthly_snapshots prev
    ON curr.marketplace_id = prev.marketplace_id
    AND curr.sku = prev.sku
    AND prev.snapshot_date = (curr.snapshot_date - INTERVAL '1 month')::date;


-- ============================================================
-- STEP 4: Add comments for documentation
-- ============================================================

COMMENT ON TABLE sp_inventory_monthly_snapshots IS
    'Monthly inventory snapshots captured on 1st of each month for turnover analysis';

COMMENT ON COLUMN sp_inventory_monthly_snapshots.snapshot_date IS
    'First day of the month this snapshot represents (e.g., 2026-02-01)';

COMMENT ON COLUMN sp_inventory_monthly_snapshots.source_date IS
    'Actual date the source inventory data was from (usually same as snapshot_date, may be 2nd if 1st missed)';

COMMENT ON COLUMN sp_inventory_monthly_snapshots.total_quantity IS
    'Auto-computed total of all inventory quantities (fulfillable + reserved + inbound + unfulfillable + researching)';
