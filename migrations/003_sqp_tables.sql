-- Migration: Create SQP/SCP (Search Query Performance / Search Catalog Performance) tables
-- Run this migration via Supabase MCP or SQL editor
--
-- Purpose: Store Amazon Brand Analytics search performance data:
-- 1. sp_sqp_data - Per-ASIN, per-search-query funnel data (impressions → clicks → cart adds → purchases)
-- 2. sp_scp_data - Per-ASIN aggregate search funnel data with revenue
-- 3. sp_sqp_pulls - Pull tracking with batch-level resume
-- 4. sp_sqp_asin_errors - Track ASINs that consistently fail (non-brand, low traffic)

-- ============================================================
-- STEP 1: Create SQP data table (per-ASIN, per-search-query)
-- ============================================================

CREATE TABLE IF NOT EXISTS sp_sqp_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Dimensions
    marketplace_id UUID NOT NULL REFERENCES marketplaces(id),
    child_asin TEXT NOT NULL,
    search_query TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('WEEK', 'MONTH', 'QUARTER')),

    -- Search query metrics
    search_query_score INTEGER,
    search_query_volume BIGINT,

    -- Impressions
    total_query_impression_count BIGINT,
    asin_impression_count BIGINT,
    asin_impression_share NUMERIC,

    -- Clicks
    total_click_count BIGINT,
    total_click_rate NUMERIC,
    asin_click_count BIGINT,
    asin_click_share NUMERIC,
    asin_click_median_price NUMERIC,
    asin_click_median_price_currency TEXT,
    total_click_median_price NUMERIC,
    total_click_median_price_currency TEXT,
    total_same_day_shipping_click_count BIGINT,
    total_one_day_shipping_click_count BIGINT,
    total_two_day_shipping_click_count BIGINT,

    -- Cart Adds
    total_cart_add_count BIGINT,
    total_cart_add_rate NUMERIC,
    asin_cart_add_count BIGINT,
    asin_cart_add_share NUMERIC,
    asin_cart_add_median_price NUMERIC,
    asin_cart_add_median_price_currency TEXT,
    total_cart_add_median_price NUMERIC,
    total_cart_add_median_price_currency TEXT,
    total_same_day_shipping_cart_add_count BIGINT,
    total_one_day_shipping_cart_add_count BIGINT,
    total_two_day_shipping_cart_add_count BIGINT,

    -- Purchases
    total_purchase_count BIGINT,
    total_purchase_rate NUMERIC,
    asin_purchase_count BIGINT,
    asin_purchase_share NUMERIC,
    asin_purchase_median_price NUMERIC,
    asin_purchase_median_price_currency TEXT,
    total_purchase_median_price NUMERIC,
    total_purchase_median_price_currency TEXT,
    total_same_day_shipping_purchase_count BIGINT,
    total_one_day_shipping_purchase_count BIGINT,
    total_two_day_shipping_purchase_count BIGINT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint for upsert
    UNIQUE(marketplace_id, child_asin, search_query, period_start, period_end, period_type)
);

-- Indexes for common query patterns
CREATE INDEX idx_sqp_marketplace_period ON sp_sqp_data(marketplace_id, period_start, period_type);
CREATE INDEX idx_sqp_asin ON sp_sqp_data(child_asin);
CREATE INDEX idx_sqp_asin_period ON sp_sqp_data(child_asin, period_start);
CREATE INDEX idx_sqp_query ON sp_sqp_data(search_query);
CREATE INDEX idx_sqp_query_volume ON sp_sqp_data(search_query_volume DESC NULLS LAST);
CREATE INDEX idx_sqp_period_type ON sp_sqp_data(period_type, period_start);

COMMENT ON TABLE sp_sqp_data IS
    'Amazon Brand Analytics Search Query Performance - per-ASIN per-search-query funnel metrics (weekly/monthly)';

-- ============================================================
-- STEP 2: Create SCP data table (per-ASIN aggregate)
-- ============================================================

CREATE TABLE IF NOT EXISTS sp_scp_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Dimensions
    marketplace_id UUID NOT NULL REFERENCES marketplaces(id),
    child_asin TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('WEEK', 'MONTH', 'QUARTER')),

    -- Impressions
    total_query_impression_count BIGINT,
    asin_impression_count BIGINT,
    asin_impression_share NUMERIC,

    -- Clicks
    total_click_count BIGINT,
    total_click_rate NUMERIC,
    asin_click_count BIGINT,
    asin_click_share NUMERIC,
    asin_click_median_price NUMERIC,
    asin_click_median_price_currency TEXT,
    total_click_median_price NUMERIC,
    total_click_median_price_currency TEXT,
    total_same_day_shipping_click_count BIGINT,
    total_one_day_shipping_click_count BIGINT,
    total_two_day_shipping_click_count BIGINT,

    -- Cart Adds
    total_cart_add_count BIGINT,
    total_cart_add_rate NUMERIC,
    asin_cart_add_count BIGINT,
    asin_cart_add_share NUMERIC,
    asin_cart_add_median_price NUMERIC,
    asin_cart_add_median_price_currency TEXT,
    total_cart_add_median_price NUMERIC,
    total_cart_add_median_price_currency TEXT,
    total_same_day_shipping_cart_add_count BIGINT,
    total_one_day_shipping_cart_add_count BIGINT,
    total_two_day_shipping_cart_add_count BIGINT,

    -- Purchases
    total_purchase_count BIGINT,
    total_purchase_rate NUMERIC,
    asin_purchase_count BIGINT,
    asin_purchase_share NUMERIC,
    asin_purchase_median_price NUMERIC,
    asin_purchase_median_price_currency TEXT,
    total_purchase_median_price NUMERIC,
    total_purchase_median_price_currency TEXT,
    total_same_day_shipping_purchase_count BIGINT,
    total_one_day_shipping_purchase_count BIGINT,
    total_two_day_shipping_purchase_count BIGINT,

    -- SCP-specific fields (not in SQP)
    search_traffic_sales NUMERIC,
    search_traffic_sales_currency TEXT,
    conversion_rate NUMERIC,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint for upsert
    UNIQUE(marketplace_id, child_asin, period_start, period_end, period_type)
);

-- Indexes
CREATE INDEX idx_scp_marketplace_period ON sp_scp_data(marketplace_id, period_start, period_type);
CREATE INDEX idx_scp_asin ON sp_scp_data(child_asin);
CREATE INDEX idx_scp_asin_period ON sp_scp_data(child_asin, period_start);
CREATE INDEX idx_scp_period_type ON sp_scp_data(period_type, period_start);
CREATE INDEX idx_scp_conversion ON sp_scp_data(conversion_rate DESC NULLS LAST);

COMMENT ON TABLE sp_scp_data IS
    'Amazon Brand Analytics Search Catalog Performance - per-ASIN aggregate search funnel with revenue (weekly/monthly)';

-- ============================================================
-- STEP 3: Create SQP pull tracking table
-- ============================================================

CREATE TABLE IF NOT EXISTS sp_sqp_pulls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Pull identification
    pull_date DATE NOT NULL,
    marketplace_id UUID NOT NULL REFERENCES marketplaces(id),
    report_type TEXT NOT NULL CHECK (report_type IN ('SQP', 'SCP')),
    period_type TEXT NOT NULL CHECK (period_type IN ('WEEK', 'MONTH', 'QUARTER')),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,

    -- Status tracking
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'partial', 'failed')),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Batch tracking
    total_batches INTEGER DEFAULT 0,
    completed_batches INTEGER DEFAULT 0,
    failed_batches INTEGER DEFAULT 0,
    batch_status JSONB DEFAULT '{}',

    -- Result metrics
    total_asins_requested INTEGER DEFAULT 0,
    total_asins_returned INTEGER DEFAULT 0,
    total_rows INTEGER DEFAULT 0,
    total_queries INTEGER DEFAULT 0,

    -- Error tracking
    error_message TEXT,
    error_count INTEGER DEFAULT 0,

    -- Performance
    processing_time_ms INTEGER,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint: one pull per marketplace+report_type+period
    UNIQUE(marketplace_id, report_type, period_start, period_end, period_type)
);

CREATE INDEX idx_sqp_pulls_status ON sp_sqp_pulls(status);
CREATE INDEX idx_sqp_pulls_period ON sp_sqp_pulls(period_start, period_type);
CREATE INDEX idx_sqp_pulls_marketplace ON sp_sqp_pulls(marketplace_id);

COMMENT ON TABLE sp_sqp_pulls IS
    'Tracking table for SQP/SCP data pulls with batch-level resume capability';

-- ============================================================
-- STEP 4: Create ASIN error tracking table
-- ============================================================

CREATE TABLE IF NOT EXISTS sp_sqp_asin_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    marketplace_id UUID NOT NULL REFERENCES marketplaces(id),
    child_asin TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    occurrence_count INTEGER DEFAULT 1,
    suppressed BOOLEAN DEFAULT FALSE,

    UNIQUE(marketplace_id, child_asin)
);

CREATE INDEX idx_sqp_asin_errors_suppressed ON sp_sqp_asin_errors(marketplace_id, suppressed);

COMMENT ON TABLE sp_sqp_asin_errors IS
    'Track ASINs that consistently fail SQP/SCP pulls (non-brand, low traffic). Auto-suppressed after 3 failures.';
