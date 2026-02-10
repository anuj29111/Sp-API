# Database Schema Reference

Supabase project: `chalkola-one-system` (yawaopfqkkvdqtsagmng)

## Sales & Traffic Tables

| Table/View | Type | Purpose |
|------------|------|---------|
| `sp_daily_asin_data` | Table | Per-ASIN daily sales & traffic. Key fields: `units_ordered`, `ordered_product_sales`, `sessions`, `page_views`, `buy_box_percentage`, `unit_session_percentage`, `data_source` ('orders' or 'sales_traffic') |
| `sp_api_pulls` | Table | Pull tracking |
| `sp_weekly_asin_data_mat` | Materialized View | Weekly aggregates (Monday-Sunday) |
| `sp_monthly_asin_data_mat` | Materialized View | Monthly aggregates |
| `sp_rolling_asin_metrics_mat` | Materialized View | Rolling 7/14/30/60 day metrics |
| `sp_weekly_asin_data` | Wrapper View | Points to materialized view (backwards compat) |
| `sp_monthly_asin_data` | Wrapper View | Points to materialized view (backwards compat) |
| `sp_rolling_asin_metrics` | Wrapper View | Points to materialized view (backwards compat) |

## Inventory Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sp_fba_inventory` | Daily FBA inventory snapshot | `fulfillable_quantity`, `fulfillable_quantity_local`, `fulfillable_quantity_remote`, `reserved_quantity`, `inbound_*` |
| `sp_awd_inventory` | Daily AWD inventory | `total_onhand_quantity`, `total_inbound_quantity`, `available_quantity` |
| `sp_storage_fees` | Monthly storage fees by FNSKU+FC | `estimated_monthly_storage_fee`, `average_quantity_on_hand` |
| `sp_inventory_age` | Age bucket breakdown | Not populated (Amazon API FATAL) |
| `sp_inventory_pulls` | Inventory pull tracking | Status, row counts, errors |
| `sp_inventory_monthly_snapshots` | 1st-of-month inventory archive | Historical inventory by SKU |

## Search Performance Tables (SQP/SCP)

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sp_sqp_data` | Per-ASIN, per-search-query funnel | `search_query`, `search_query_volume`, impression/click/cart/purchase counts + shares + median prices |
| `sp_scp_data` | Per-ASIN aggregate search funnel | Same funnel + `search_traffic_sales`, `conversion_rate` |
| `sp_sqp_pulls` | SQP/SCP pull tracking with batch-level resume | `batch_status` JSONB, completed/failed batches |
| `sp_sqp_asin_errors` | ASINs that fail SQP pulls | Auto-suppressed after 3 failures |

## Search Terms Tables (TST — Competitive Intelligence)

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sp_search_terms_data` | Top 3 clicked ASINs per search term (marketplace-wide) | `search_term`, `search_frequency_rank`, `clicked_asin`, `click_share_rank`, `click_share`, `conversion_share`, `department_name` |
| `sp_search_terms_pulls` | Pull tracking per marketplace per period | `sqp_keywords_count`, `matched_terms_count`, `total_rows`, `processing_time_ms` |

## Financial Tables

| Table | Purpose | Unique On | Key Fields |
|-------|---------|-----------|------------|
| `sp_settlement_transactions` | Per-order transaction fees (PRIMARY for CM2) | `(marketplace_id, settlement_id, row_hash)` | `transaction_type`, `amount_type`, `amount_description`, `amount`, `posted_date_time`, `sku`, `order_id` |
| `sp_settlement_summaries` | One per settlement period | `(marketplace_id, settlement_id)` | `settlement_start_date`, `settlement_end_date`, `total_amount`, `currency_code` |
| `sp_reimbursements` | Per-SKU reimbursement records | `(marketplace_id, reimbursement_id, sku)` | `reason`, `amount_total`, `sku`, `asin`, `quantity_reimbursed_*` |
| `sp_fba_fee_estimates` | Current fee estimates per ASIN | `(marketplace_id, sku)` | `estimated_fee_total`, `estimated_referral_fee_per_unit`, `estimated_pick_pack_fee_per_unit`, `product_size_tier` |
| `sp_financial_pulls` | Pull tracking for all financial reports | Auto-increment | `report_type`, `settlement_id`, `status`, `row_count` |

## Google Sheets Helper Views

| View | Purpose | Source Tables |
|------|---------|---------------|
| `sp_storage_fees_by_asin` | Aggregates per-FC storage fees to per-ASIN totals | `sp_storage_fees` |
| `sp_settlement_fees_by_sku` | Per-SKU avg FBA + referral fees from settlement data | `sp_settlement_transactions` |
| `sp_sku_asin_map` | Canonical SKU to ASIN mapping from all available sources | FBA inv + fee est + storage |

## Phase Details

### Phase 1: Sales & Traffic - COMPLETE
- Orders report provides same-day sales data (~30min delay) — units + revenue only
- Sales & Traffic report arrives 24-48hrs later with traffic metrics (sessions, page views, buy box %)
- Both write to `sp_daily_asin_data`; `data_source` tracks which report populated each row
- When S&T arrives, it overwrites orders data with attribution-corrected values + traffic

### Phase 1.5: Near-Real-Time Orders - COMPLETE
- `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` report, 6x/day
- Won't overwrite rows that already have Sales & Traffic data

### Phase 2: Inventory - COMPLETE
- NA: FBA Inventory API v1 (fast, detailed breakdowns)
- EU/FE: `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` report (includes Pan-European EFN local/remote columns)
- AWD: AWD API v2024-05-09 (NA only, 62 records)
- Inventory Age: BLOCKED (Amazon API returns FATAL)

### Phase 2.5: SQP/SCP - COMPLETE
- SQP = per-ASIN, per-search-query funnel metrics (weekly/monthly)
- SCP = per-ASIN aggregate search funnel + revenue + conversion rate
- Constraints: No daily granularity, ~18 ASINs/batch, ~48hr delay, brand-registered only

### Phase 2.6: Search Terms (TST) - COMPLETE
- Brand Analytics Search Terms Report: top 3 clicked ASINs per search term across entire marketplace
- Bulk report (~12M rows / ~2.3 GB) — stream-parsed with `ijson`, filtered against SQP keywords
- Only ~25% of SQP terms match (small-volume terms absent from TST)
- Weekly auto-pull: Tuesday 6 AM UTC (after SQP ensures fresh keywords)
- Unique on: `(marketplace_id, search_term, period_start, period_type, clicked_asin)`

### Phase 3: Financial Reports - COMPLETE
- Settlement Reports: PRIMARY for CM2 (actual fees per order)
- Reimbursements: Per-region pull, currency-based marketplace resolution
- FBA Fee Estimates: Current fees only (settlements = historical source of truth)
- Storage Fees: Monthly, retry on 5th/10th/15th for late availability
