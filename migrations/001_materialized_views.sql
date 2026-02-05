-- Migration: Convert regular views to materialized views for better performance
-- Run this migration via Supabase MCP or SQL editor
--
-- This migration:
-- 1. Drops existing regular views
-- 2. Creates materialized views with same names + _mat suffix
-- 3. Adds indexes for fast lookups
-- 4. Creates wrapper views (same original names) pointing to materialized data
--
-- After running, use: REFRESH MATERIALIZED VIEW CONCURRENTLY <view_name>;

-- ============================================================
-- STEP 1: Drop existing regular views
-- ============================================================

DROP VIEW IF EXISTS sp_weekly_asin_data CASCADE;
DROP VIEW IF EXISTS sp_monthly_asin_data CASCADE;
DROP VIEW IF EXISTS sp_rolling_asin_metrics CASCADE;


-- ============================================================
-- STEP 2: Create materialized view for WEEKLY data
-- ============================================================

CREATE MATERIALIZED VIEW sp_weekly_asin_data_mat AS
SELECT
    DATE_TRUNC('week', date::timestamp with time zone)::date AS week_start,
    EXTRACT(isoyear FROM date)::integer AS iso_year,
    EXTRACT(week FROM date)::integer AS iso_week_number,
    marketplace_id,
    child_asin,
    parent_asin,
    SUM(units_ordered) AS units_ordered,
    SUM(units_ordered_b2b) AS units_ordered_b2b,
    SUM(ordered_product_sales) AS ordered_product_sales,
    SUM(ordered_product_sales_b2b) AS ordered_product_sales_b2b,
    MAX(currency_code) AS currency_code,
    SUM(total_order_items) AS total_order_items,
    SUM(sessions) AS sessions,
    SUM(page_views) AS page_views,
    AVG(buy_box_percentage) AS avg_buy_box_percentage,
    AVG(unit_session_percentage) AS avg_conversion_rate
FROM sp_daily_asin_data
GROUP BY
    DATE_TRUNC('week', date::timestamp with time zone),
    EXTRACT(isoyear FROM date),
    EXTRACT(week FROM date),
    marketplace_id,
    child_asin,
    parent_asin;

-- Index for fast lookups by marketplace and week
CREATE UNIQUE INDEX idx_weekly_mat_unique ON sp_weekly_asin_data_mat(marketplace_id, week_start, child_asin);
CREATE INDEX idx_weekly_mat_week ON sp_weekly_asin_data_mat(week_start);
CREATE INDEX idx_weekly_mat_marketplace ON sp_weekly_asin_data_mat(marketplace_id);
CREATE INDEX idx_weekly_mat_asin ON sp_weekly_asin_data_mat(child_asin);


-- ============================================================
-- STEP 3: Create materialized view for MONTHLY data
-- ============================================================

CREATE MATERIALIZED VIEW sp_monthly_asin_data_mat AS
SELECT
    DATE_TRUNC('month', date::timestamp with time zone)::date AS month,
    marketplace_id,
    child_asin,
    parent_asin,
    SUM(units_ordered) AS units_ordered,
    SUM(units_ordered_b2b) AS units_ordered_b2b,
    SUM(ordered_product_sales) AS ordered_product_sales,
    SUM(ordered_product_sales_b2b) AS ordered_product_sales_b2b,
    MAX(currency_code) AS currency_code,
    SUM(total_order_items) AS total_order_items,
    SUM(sessions) AS sessions,
    SUM(page_views) AS page_views,
    AVG(buy_box_percentage) AS avg_buy_box_percentage,
    AVG(unit_session_percentage) AS avg_conversion_rate
FROM sp_daily_asin_data
GROUP BY
    DATE_TRUNC('month', date::timestamp with time zone),
    marketplace_id,
    child_asin,
    parent_asin;

-- Index for fast lookups
CREATE UNIQUE INDEX idx_monthly_mat_unique ON sp_monthly_asin_data_mat(marketplace_id, month, child_asin);
CREATE INDEX idx_monthly_mat_month ON sp_monthly_asin_data_mat(month);
CREATE INDEX idx_monthly_mat_marketplace ON sp_monthly_asin_data_mat(marketplace_id);
CREATE INDEX idx_monthly_mat_asin ON sp_monthly_asin_data_mat(child_asin);


-- ============================================================
-- STEP 4: Create materialized view for ROLLING metrics
-- ============================================================

CREATE MATERIALIZED VIEW sp_rolling_asin_metrics_mat AS
WITH date_ranges AS (
    SELECT
        CURRENT_DATE - INTERVAL '2 days' AS reference_date,
        CURRENT_DATE - INTERVAL '2 days' - INTERVAL '6 days' AS last_7_start,
        CURRENT_DATE - INTERVAL '2 days' - INTERVAL '13 days' AS last_14_start,
        CURRENT_DATE - INTERVAL '2 days' - INTERVAL '29 days' AS last_30_start,
        CURRENT_DATE - INTERVAL '2 days' - INTERVAL '59 days' AS last_60_start
)
SELECT
    d.marketplace_id,
    d.child_asin,
    d.parent_asin,
    MAX(d.currency_code) AS currency_code,
    -- 7-day metrics
    SUM(CASE WHEN d.date > dr.last_7_start THEN d.units_ordered ELSE 0 END) AS units_last_7_days,
    SUM(CASE WHEN d.date > dr.last_7_start THEN d.ordered_product_sales ELSE 0 END) AS revenue_last_7_days,
    AVG(CASE WHEN d.date > dr.last_7_start THEN d.units_ordered ELSE NULL END) AS avg_units_7_days,
    SUM(CASE WHEN d.date > dr.last_7_start THEN d.sessions ELSE 0 END) AS sessions_last_7_days,
    AVG(CASE WHEN d.date > dr.last_7_start THEN d.unit_session_percentage ELSE NULL END) AS avg_conversion_7_days,
    -- 14-day metrics
    SUM(CASE WHEN d.date > dr.last_14_start THEN d.units_ordered ELSE 0 END) AS units_last_14_days,
    SUM(CASE WHEN d.date > dr.last_14_start THEN d.ordered_product_sales ELSE 0 END) AS revenue_last_14_days,
    AVG(CASE WHEN d.date > dr.last_14_start THEN d.units_ordered ELSE NULL END) AS avg_units_14_days,
    SUM(CASE WHEN d.date > dr.last_14_start THEN d.sessions ELSE 0 END) AS sessions_last_14_days,
    AVG(CASE WHEN d.date > dr.last_14_start THEN d.unit_session_percentage ELSE NULL END) AS avg_conversion_14_days,
    -- 30-day metrics
    SUM(CASE WHEN d.date > dr.last_30_start THEN d.units_ordered ELSE 0 END) AS units_last_30_days,
    SUM(CASE WHEN d.date > dr.last_30_start THEN d.ordered_product_sales ELSE 0 END) AS revenue_last_30_days,
    AVG(CASE WHEN d.date > dr.last_30_start THEN d.units_ordered ELSE NULL END) AS avg_units_30_days,
    SUM(CASE WHEN d.date > dr.last_30_start THEN d.sessions ELSE 0 END) AS sessions_last_30_days,
    AVG(CASE WHEN d.date > dr.last_30_start THEN d.unit_session_percentage ELSE NULL END) AS avg_conversion_30_days,
    -- 60-day metrics
    SUM(CASE WHEN d.date > dr.last_60_start THEN d.units_ordered ELSE 0 END) AS units_last_60_days,
    SUM(CASE WHEN d.date > dr.last_60_start THEN d.ordered_product_sales ELSE 0 END) AS revenue_last_60_days,
    AVG(CASE WHEN d.date > dr.last_60_start THEN d.units_ordered ELSE NULL END) AS avg_units_60_days,
    SUM(CASE WHEN d.date > dr.last_60_start THEN d.sessions ELSE 0 END) AS sessions_last_60_days,
    AVG(CASE WHEN d.date > dr.last_60_start THEN d.unit_session_percentage ELSE NULL END) AS avg_conversion_60_days
FROM sp_daily_asin_data d
CROSS JOIN date_ranges dr
WHERE d.date > dr.last_60_start
GROUP BY d.marketplace_id, d.child_asin, d.parent_asin;

-- Index for fast lookups
CREATE UNIQUE INDEX idx_rolling_mat_unique ON sp_rolling_asin_metrics_mat(marketplace_id, child_asin);
CREATE INDEX idx_rolling_mat_marketplace ON sp_rolling_asin_metrics_mat(marketplace_id);
CREATE INDEX idx_rolling_mat_asin ON sp_rolling_asin_metrics_mat(child_asin);


-- ============================================================
-- STEP 5: Create wrapper views (same names as original)
-- These provide backwards compatibility for existing queries
-- ============================================================

CREATE VIEW sp_weekly_asin_data AS
SELECT * FROM sp_weekly_asin_data_mat;

CREATE VIEW sp_monthly_asin_data AS
SELECT * FROM sp_monthly_asin_data_mat;

CREATE VIEW sp_rolling_asin_metrics AS
SELECT * FROM sp_rolling_asin_metrics_mat;


-- ============================================================
-- STEP 6: Initial refresh (run automatically after creation)
-- ============================================================
-- The materialized views are populated on creation, so no initial refresh needed.
-- For subsequent refreshes, use:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY sp_weekly_asin_data_mat;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY sp_monthly_asin_data_mat;
--   REFRESH MATERIALIZED VIEW CONCURRENTLY sp_rolling_asin_metrics_mat;

-- Note: CONCURRENTLY requires a unique index (which we created above)
-- and allows the view to be read during refresh.
