# SP-API Data Pull & CM2 Profitability System

## Project Goal

Build a complete **Contribution Margin (CM1/CM2) profitability system** by pulling data from Amazon SP-API, combining with POP advertising data, and calculating per-ASIN profitability metrics.

**Replaces:** GorillaROI ($600/month) + manual Excel tracking

**Key Calculations:**
- **Organic Sales** = Total Sales - PPC Sales
- **True TACOS** = Ad Spend / Total Sales
- **CM1** = Revenue - FBA Fees - COGS (gross profit before ads)
- **CM2** = CM1 - Ad Spend - Storage (net operating profit)

**CM2 Formula Breakdown:**
```
Net Revenue = Gross Sales - Returns/Refunds
CM1 = Net Revenue - Referral Fees - FBA Fees - COGS
CM2 = CM1 - Ad Spend - Storage Fees + Reimbursements
```

---

## Architecture

```
Amazon SP-API → GitHub Actions (scheduled) → Supabase → Web App
                                                 ↑
POP System (Advertising API) ────────────────────┘
```

- **GitHub Actions**: Runs Python scripts on schedule
- **Supabase**: `chalkola-one-system` database (yawaopfqkkvdqtsagmng)
- **POP System**: Already has advertising data in same Supabase

---

## Implementation Status

### Phase 1: Sales & Traffic Data ✅ COMPLETE

| Component | Status |
|-----------|--------|
| GitHub Repo | ✅ https://github.com/anuj29111/Sp-API |
| Daily Pull | ✅ Running 4x/day (2, 8, 14, 20 UTC) |
| Late Attribution Refresh | ✅ Refreshes last 14 days |
| Database Tables | ✅ `sp_daily_asin_data`, `sp_api_pulls` |
| Views | ✅ Weekly, Monthly, Rolling metrics (MATERIALIZED) |
| Backfill | 🔄 Auto-running 4x/day |
| NA Authorization | ✅ USA, CA, MX working |
| EU Authorization | ✅ UK, DE, FR, IT, ES, UAE working |
| FE Authorization | ✅ AU working |

**Data Available:**
- `units_ordered`, `ordered_product_sales` - Sales metrics
- `sessions`, `page_views` - Traffic metrics
- `buy_box_percentage`, `unit_session_percentage` - Performance

**Date Logic:**
- Each marketplace uses its own timezone (USA/CA/MX = PST, UK = GMT, etc.)
- Default: Yesterday in marketplace timezone (Sales & Traffic has ~12-24hr delay)
- 14-day attribution refresh catches updates to recent data
- Re-pulls dates with 0 ASINs automatically

### Phase 1.5: Near-Real-Time Orders ✅ COMPLETE & VERIFIED

| Component | Status | Details |
|-----------|--------|---------|
| **Orders Report** | ✅ Working | `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` |
| **Daily Pull** | ✅ Running 6x/day | Every 4 hours UTC |
| **S&T Protection** | ✅ Verified | Orders don't overwrite existing S&T data |
| **data_source column** | ✅ Applied | Tracks 'orders' vs 'sales_traffic' per row |

**Architecture:**
- Orders report provides same-day sales data (~30min delay) — units + revenue only
- Sales & Traffic report arrives 24-48hrs later with traffic metrics (sessions, page views, buy box %)
- Both write to same `sp_daily_asin_data` table
- `data_source` column tracks which report populated each row
- When S&T arrives, it overwrites orders data with attribution-corrected values + traffic

**Verified Test Results (Feb 7, 2026):**
- Feb 6 (same-day): 116 ASINs, 369 units, $7,448.35 from orders report
- Feb 5 (catch-up): 22 new ASINs added, 115 skipped (already had S&T data)
- Correctly excluded 576+ Cancelled/Pending order lines

### Phase 2: Inventory Data ✅ COMPLETE (with known limitation)

| Data | Source | Status | Records |
|------|--------|--------|---------|
| **FBA Inventory** | FBA Inventory API (v1/summaries) | ✅ Working | 735 records/marketplace (pagination fixed Feb 9, 2026) |
| **AWD Inventory** | AWD API (v2024-05-09) | ✅ Working | 62 records (14,363 units) |
| **Storage Fees** | Reports API | ✅ Working | 14,227 records/month |
| **Inventory Age** | Reports API | ⚠️ BLOCKED | Amazon API returns FATAL |

**6 Key Data Points - All Available:**
| # | Data Point | Field | Table |
|---|------------|-------|-------|
| 1 | Available/Fulfillable | `fulfillable_quantity` | `sp_fba_inventory` |
| 2 | AWD On-Hand | `total_onhand_quantity` | `sp_awd_inventory` |
| 3 | AWD In-Transit | `total_inbound_quantity` | `sp_awd_inventory` |
| 4 | Reserved | `reserved_quantity` + breakdowns | `sp_fba_inventory` |
| 5 | Inbound Working | `inbound_working_quantity` | `sp_fba_inventory` |
| 6 | Inbound Shipped | `inbound_shipped_quantity` | `sp_fba_inventory` |

**Known Issue:** `GET_FBA_INVENTORY_AGED_DATA` returns FATAL status - this is a known Amazon API issue affecting many sellers. A fallback report exists but doesn't include age bucket breakdowns.

**Data Validation (Feb 9, 2026 — GorillaROI cross-check):**
- **Sales (Feb 7):** 104/110 ASINs exact match (94.5%), 6 off by ±1 unit (attribution timing). Supabase total 557 units vs GorillaROI 514 — difference is ASINs GorillaROI doesn't track.
- **FBA Inventory:** All comparable ASINs within 1-12 unit variance (normal timing). USA: 735 records, ~96,663 fulfillable units (matches GorillaROI ~96,619).
- **AWD Inventory:** 4/4 mapped ASINs exact match on both available and inbound quantities.
- **Pagination Bug Fixed:** Code was reading `nextToken` from `result["payload"]` instead of `result["pagination"]`. Only 50 of ~735 records were stored per marketplace since system started. Fixed Feb 9, 2026.

### Phase 2.5: Search Query Performance (SQP/SCP) ✅ COMPLETE & VERIFIED

| Data | Report Type | Status | Granularity |
|------|-------------|--------|-------------|
| **SQP** (per-query) | `GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT` | ✅ Working | Weekly, Monthly |
| **SCP** (per-ASIN) | `GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT` | ✅ Working | Weekly, Monthly |

**SQP** = Per-ASIN, per-search-query: impressions, clicks, cart adds, purchases, shares, median prices
**SCP** = Per-ASIN aggregate: same funnel + `search_traffic_sales` (revenue) + `conversion_rate`

**Verified Test Results (Feb 7, 2026):**
- CA SQP: 3,538 rows, 138 ASINs, 2,629 queries, 10/10 batches — all metrics populated
- CA SCP: 154 rows, 10/10 batches — all metrics populated
- USA SCP: 367 rows, 25/25 batches — working
- USA SQP: ✅ **6,228 rows**, 236 ASINs, 4,400 queries, 25/25 batches — fixed with per-batch upserts + 200-row chunks

**Marketplaces:** USA + CA only (MX excluded - Brand Analytics not available)

**Key Constraints:**
- No daily granularity — Weekly (Sun-Sat) is finest
- 200-char ASIN limit per request (~18 ASINs per batch)
- ~48hr data delay after period ends
- Brand-registered ASINs only
- ~1 createReport/min rate limit (shared with all report types)
- Historical data available ~Dec 2023 onward (~113 weeks)

**Backfill Estimate:** ~28 days at 2 periods/run, 2 runs/day

### Phase 3: Financial Reports ✅ COMPLETE & VERIFIED

**PRIMARY for CM2**: Settlement Reports contain **actual fees Amazon charged per order** — not estimates.

| Report Type | SP-API Report | Script | Status | Records |
|-------------|---------------|--------|--------|---------|
| **Settlement Reports** | `GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2` | `pull_settlements.py` / `backfill_settlements.py` | ✅ **Working** | 536,744 tx, 21 summaries |
| **Reimbursements** | `GET_FBA_REIMBURSEMENTS_DATA` | `pull_reimbursements.py` | ⚠️ **Partial** (API FATAL on USA/CA) | 914 (MX only) |
| **FBA Fee Estimates** | `GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA` | `pull_fba_fees.py` | ✅ **Working** (all 3 NA) | 1,560 (520/marketplace) |
| **Storage Fees** | `GET_FBA_STORAGE_FEE_CHARGES_DATA` | `pull_storage_fees.py` | ✅ Working (Phase 2) | 14,227 |

**Settlement Reports (verified Feb 7, 2026):**
- USA: 21 settlements, 393,252 transactions, $298K net (Oct 2025 → Feb 2026)
- CA: 5 settlements, 142,473 transactions, $312K CAD
- MX: 6 settlements, 1,019 transactions, $18K MXN
- Dedup integrity: CLEAN (0 duplicate hashes across all 536K rows)
- Fee types verified: Principal ($2.1M), Commission (-$328K), FBA fulfillment (-$583K), Ad spend (-$457K), Tax, Promotions, Refunds, Shipping
- **Architecture**: Single run per NA region (not per-marketplace). Each row attributed to correct marketplace via `marketplace-name` field with currency fallback.
- **API 90-day lookback limit**: `getReports` API `createdSince` parameter has maximum 90-day lookback. Historical data before that window cannot be retrieved via API.

**Reimbursements:**
- MX succeeded (914 records, Dec 2025 → Feb 2026). USA and CA return FATAL (Amazon API issue).
- Unique constraint: `(marketplace_id, reimbursement_id, sku)` — supports multi-SKU reimbursement cases
- Cron retries Monday 6 AM UTC automatically

**FBA Fee Estimates:**
- All 3 NA marketplaces working (520 SKUs each, 1,560 total). USA FATAL resolved ~Feb 8, 2026.
- Shows CURRENT fees per ASIN — for projections only, NOT historical CM2
- `dataStartTime` must be 72+ hours prior
- Runs daily 5 AM UTC

### Phase 4: Product Master Data ⏸️ PENDING

### Phase 5: CM1/CM2 Calculation Engine ⏸️ PENDING

### Phase 6: Web Dashboard ⏸️ PENDING

---

## Project Structure

```
/Sp-API/
├── scripts/
│   ├── pull_daily_sales.py        # Daily sales & traffic pull (timezone-aware)
│   ├── pull_inventory.py          # FBA inventory (uses API)
│   ├── pull_awd_inventory.py      # AWD inventory (uses AWD API)
│   ├── pull_inventory_age.py      # Inventory age buckets (--fallback option)
│   ├── pull_storage_fees.py       # Monthly storage fees
│   ├── pull_sqp.py                # Weekly SQP/SCP search performance pull
│   ├── pull_orders_daily.py       # 6x/day near-real-time orders (~30min delay)
│   ├── pull_settlements.py        # Weekly settlement report pull (LIST → DOWNLOAD)
│   ├── pull_reimbursements.py     # Weekly reimbursement report pull
│   ├── pull_fba_fees.py           # Daily FBA fee estimates pull
│   ├── backfill_historical.py     # 2-year sales backfill (with skip-existing)
│   ├── backfill_sqp.py            # SQP/SCP historical backfill
│   ├── backfill_settlements.py    # Settlement backfill to Jan 2024
│   ├── refresh_recent.py          # Late attribution refresh
│   ├── refresh_views.py           # Refresh materialized views
│   ├── capture_monthly_inventory.py  # Monthly inventory snapshots
│   └── utils/
│       ├── api_client.py          # Centralized HTTP client with retry/rate limiting
│       ├── pull_tracker.py        # Checkpoint & resume capability
│       ├── alerting.py            # Slack webhook notifications
│       ├── auth.py                # SP-API token refresh
│       ├── reports.py             # Sales & Traffic report helpers
│       ├── orders_reports.py      # Near-real-time orders report helpers
│       ├── sqp_reports.py         # SQP/SCP report helpers (Brand Analytics)
│       ├── inventory_reports.py   # Inventory report helpers
│       ├── financial_reports.py   # Settlement, Reimbursement, FBA Fee helpers
│       ├── fba_inventory_api.py   # FBA Inventory API client
│       ├── awd_api.py             # AWD API client
│       └── db.py                  # Supabase operations (all tables)
├── migrations/
│   ├── 001_materialized_views.sql # Convert views to materialized views
│   ├── 002_inventory_snapshots.sql # Monthly inventory snapshot table
│   ├── 003_sqp_tables.sql         # SQP/SCP tables + pull tracking
│   └── 004_financial_tables.sql   # Settlement, Reimbursement, FBA Fee tables (applied via MCP)
├── .github/workflows/
│   ├── daily-pull.yml             # 4x/day - Sales & Traffic + view refresh
│   ├── orders-daily.yml           # 6x/day - Near-real-time orders (~30min delay)
│   ├── inventory-daily.yml        # 3 AM UTC - FBA + AWD + monthly snapshots
│   ├── storage-fees-monthly.yml   # 5th of month - Storage Fees
│   ├── historical-backfill.yml    # 4x/day - Auto backfill until complete
│   ├── sqp-weekly.yml             # Tuesdays + 4th of month - SQP/SCP pull
│   ├── sqp-backfill.yml           # 2x/day - SQP historical backfill
│   ├── settlements-weekly.yml     # Tuesdays 7 AM UTC - Settlement reports
│   ├── settlement-backfill.yml    # Manual - Backfill settlements to Jan 2024
│   ├── reimbursements-weekly.yml  # Mondays 6 AM UTC - Reimbursement reports
│   └── financial-daily.yml        # Daily 5 AM UTC - FBA fee estimates
├── google-sheets/
│   └── supabase_sales.gs          # Apps Script for Google Sheets integration
├── requirements.txt
└── CLAUDE.md
```

---

## Database Tables

### Sales & Traffic Tables
| Table/View | Type | Purpose |
|------------|------|---------|
| `sp_daily_asin_data` | Table | Per-ASIN daily sales & traffic |
| `sp_api_pulls` | Table | Pull tracking |
| `sp_weekly_asin_data_mat` | **Materialized View** | Weekly aggregates (Monday-Sunday) |
| `sp_monthly_asin_data_mat` | **Materialized View** | Monthly aggregates |
| `sp_rolling_asin_metrics_mat` | **Materialized View** | Rolling 7/14/30/60 day metrics |
| `sp_weekly_asin_data` | Wrapper View | Points to materialized view (backwards compat) |
| `sp_monthly_asin_data` | Wrapper View | Points to materialized view (backwards compat) |
| `sp_rolling_asin_metrics` | Wrapper View | Points to materialized view (backwards compat) |

### Inventory Tables
| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sp_fba_inventory` | Daily FBA inventory snapshot | `fulfillable_quantity`, `reserved_quantity`, `inbound_*`, detailed breakdowns |
| `sp_awd_inventory` | Daily AWD inventory | `total_onhand_quantity`, `total_inbound_quantity`, `available_quantity` |
| `sp_storage_fees` | Monthly storage fees by FNSKU+FC | `estimated_monthly_storage_fee`, `average_quantity_on_hand` |
| `sp_inventory_age` | Age bucket breakdown | ⚠️ Not populated (Amazon API FATAL) |
| `sp_inventory_pulls` | Inventory pull tracking | Status, row counts, errors |
| `sp_inventory_monthly_snapshots` | 1st-of-month inventory archive | Historical inventory by SKU |

### Search Performance Tables (SQP/SCP)
| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sp_sqp_data` | Per-ASIN, per-search-query funnel | `search_query`, `search_query_volume`, impression/click/cart/purchase counts + shares + median prices |
| `sp_scp_data` | Per-ASIN aggregate search funnel | Same funnel + `search_traffic_sales`, `conversion_rate` |
| `sp_sqp_pulls` | SQP/SCP pull tracking with batch-level resume | `batch_status` JSONB, completed/failed batches |
| `sp_sqp_asin_errors` | ASINs that fail SQP pulls | Auto-suppressed after 3 failures |

### Financial Tables (Phase 3)
| Table | Purpose | Unique On | Key Fields |
|-------|---------|-----------|------------|
| `sp_settlement_transactions` | Per-order transaction fees (PRIMARY for CM2) | `(marketplace_id, settlement_id, row_hash)` | `transaction_type`, `amount_type`, `amount_description`, `amount`, `posted_date_time`, `sku`, `order_id` |
| `sp_settlement_summaries` | One per settlement period | `(marketplace_id, settlement_id)` | `settlement_start_date`, `settlement_end_date`, `total_amount`, `currency_code` |
| `sp_reimbursements` | Per-SKU reimbursement records | `(marketplace_id, reimbursement_id, sku)` | `reason`, `amount_total`, `sku`, `asin`, `quantity_reimbursed_*` |
| `sp_fba_fee_estimates` | Current fee estimates per ASIN | `(marketplace_id, sku)` | `estimated_fee_total`, `estimated_referral_fee_per_unit`, `estimated_pick_pack_fee_per_unit`, `product_size_tier` |
| `sp_financial_pulls` | Pull tracking for all financial reports | Auto-increment | `report_type`, `settlement_id`, `status`, `row_count` |

### Google Sheets Helper Views (created via Supabase MCP)
| View | Purpose | Source Tables |
|------|---------|---------------|
| `sp_storage_fees_by_asin` | Aggregates per-FC storage fees → per-ASIN totals | `sp_storage_fees` |
| `sp_settlement_fees_by_sku` | Per-SKU avg FBA + referral fees from settlement data | `sp_settlement_transactions` |
| `sp_sku_asin_map` | Canonical SKU→ASIN mapping from all available sources | FBA inv + fee est + storage |

---

## GitHub Workflows

### Daily Sales Pull (`daily-pull.yml`)
- **Schedule**: 4x/day at 2, 8, 14, 20 UTC
- **Modes**: `daily`, `refresh`, `both` (default)
- **Date Logic**: Yesterday in each marketplace's timezone
- **Re-pull**: Automatically re-pulls dates that returned 0 ASINs

```bash
gh workflow run daily-pull.yml                                    # Default: all regions, both modes
gh workflow run daily-pull.yml -f date=2026-02-05                 # Specific date
gh workflow run daily-pull.yml -f marketplace=USA                 # Single marketplace
gh workflow run daily-pull.yml -f region=EU                       # EU region only
gh workflow run daily-pull.yml -f marketplace=UK -f region=EU     # Single EU marketplace
```

### FBA & AWD Inventory Pull (`inventory-daily.yml`)
- **Schedule**: 3 AM UTC daily
- **Report Types**: `all`, `inventory`, `awd`, `age`

```bash
gh workflow run inventory-daily.yml                                       # All types, all regions
gh workflow run inventory-daily.yml -f report_type=inventory              # FBA only
gh workflow run inventory-daily.yml -f report_type=awd                    # AWD only (NA only)
gh workflow run inventory-daily.yml -f region=EU                          # EU region only
```

### Monthly Storage Fees (`storage-fees-monthly.yml`)
- **Schedule**: 5th of month (data available ~7 days after month end)

```bash
gh workflow run storage-fees-monthly.yml -f month=2025-12 -f marketplace=USA
gh workflow run storage-fees-monthly.yml -f region=EU                          # EU region only
```

### Historical Backfill (`historical-backfill.yml`)
- **Schedule**: 4x/day at 0, 6, 12, 18 UTC until complete
- **Modes**: `test` (7 days), `month`, `quarter`, `year`, `full` (730 days)
- **Auto-skip**: Exits early if backfill is >99% complete
- **Resume**: Automatically skips existing data and continues from where it left off

```bash
gh workflow run historical-backfill.yml -f mode=full              # All regions, manual trigger
gh workflow run historical-backfill.yml -f region=EU              # EU only
gh workflow run historical-backfill.yml -f region=FE -f mode=year # FE, last year only
```

### Near-Real-Time Orders (`orders-daily.yml`)
- **Schedule**: 6x/day at 0, 4, 8, 12, 16, 20 UTC
- **Data Source**: `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` (~30min delay)
- **Default**: Pulls today + yesterday per marketplace timezone
- **S&T Protection**: Won't overwrite rows that already have Sales & Traffic data
- **Timeout**: 60 minutes

```bash
gh workflow run orders-daily.yml                                    # All regions, today + yesterday
gh workflow run orders-daily.yml -f marketplace=USA                 # Single marketplace
gh workflow run orders-daily.yml -f date=2026-02-07                 # Specific date
gh workflow run orders-daily.yml -f region=EU                       # EU region only
gh workflow run orders-daily.yml -f today_only=true                 # Skip yesterday catch-up
gh workflow run orders-daily.yml -f marketplace=USA -f dry_run=true # Test without DB writes
```

### SQP/SCP Weekly Pull (`sqp-weekly.yml`)
- **Weekly Schedule**: Every Tuesday 4 AM UTC (Sun-Sat week ended Saturday, +48hr delay)
- **Monthly Schedule**: 4th of month 4 AM UTC (previous month, +48hr delay)
- **Auto-detects**: Period type from schedule date (Tuesday=WEEK, 4th=MONTH)
- **Timeout**: 150 minutes

```bash
gh workflow run sqp-weekly.yml                                              # Latest week, both reports
gh workflow run sqp-weekly.yml -f report_type=SQP                           # SQP only
gh workflow run sqp-weekly.yml -f period_type=MONTH                         # Monthly
gh workflow run sqp-weekly.yml -f marketplace=USA                           # Single marketplace
gh workflow run sqp-weekly.yml -f period_start=2026-01-26 -f period_end=2026-02-01  # Specific period
```

### SQP/SCP Backfill (`sqp-backfill.yml`)
- **Schedule**: 3x/day at 1, 9, 17 UTC (8hrs apart, avoiding other workflows)
- **Default**: 2 periods per run (~3 hours), latest-first
- **Timeout**: 240 minutes
- **Auto-exits**: When >99% of periods are complete

```bash
gh workflow run sqp-backfill.yml                                            # Default: 2 periods
gh workflow run sqp-backfill.yml -f max_periods=3                           # More periods per run
gh workflow run sqp-backfill.yml -f marketplace=CA -f report_type=SCP       # Small test
gh workflow run sqp-backfill.yml -f start_date=2024-01-01                   # From specific date
```

### Settlement Reports Weekly (`settlements-weekly.yml`)
- **Schedule**: Every Tuesday 7 AM UTC
- **Pattern**: LIST available reports → DOWNLOAD each → Parse TSV → Upsert
- **Auto-skip**: Already-processed settlement IDs are skipped

```bash
gh workflow run settlements-weekly.yml                                      # Last 30 days, all regions
gh workflow run settlements-weekly.yml -f since=2026-01-01                   # Since specific date
gh workflow run settlements-weekly.yml -f region=EU                          # EU region only
gh workflow run settlements-weekly.yml -f marketplace=USA -f dry_run=true    # Test
```

### Settlement Backfill (`settlement-backfill.yml`)
- **Trigger**: Manual only
- **Default**: Since Jan 2024 (matching GorillaROI history)
- **Timeout**: 120 minutes
- **Auto-skip**: Already-processed settlements skipped (idempotent)

```bash
gh workflow run settlement-backfill.yml                                     # Default: since 2024-01-01, all regions
gh workflow run settlement-backfill.yml -f since=2025-01-01                 # Custom start
gh workflow run settlement-backfill.yml -f region=EU                        # EU region only
gh workflow run settlement-backfill.yml -f marketplace=USA                  # Single marketplace
gh workflow run settlement-backfill.yml -f dry_run=true                     # Test first
```

### Reimbursements Weekly (`reimbursements-weekly.yml`)
- **Schedule**: Every Monday 6 AM UTC
- **Default window**: Last 60 days (overlapping ensures nothing missed)
- **Pattern**: CREATE → POLL → DOWNLOAD (standard report)

```bash
gh workflow run reimbursements-weekly.yml                                   # Last 60 days, all regions
gh workflow run reimbursements-weekly.yml -f start_date=2024-01-01          # Backfill
gh workflow run reimbursements-weekly.yml -f region=EU                      # EU region only
gh workflow run reimbursements-weekly.yml -f marketplace=USA                # Single marketplace
```

### FBA Fee Estimates Daily (`financial-daily.yml`)
- **Schedule**: Daily 5 AM UTC
- **Note**: Shows CURRENT fees only (for projections, not historical CM2)
- **Limitation**: Can only be requested once/day per seller

```bash
gh workflow run financial-daily.yml                                         # All regions
gh workflow run financial-daily.yml -f marketplace=USA                      # Single marketplace
gh workflow run financial-daily.yml -f region=EU                            # EU region only
gh workflow run financial-daily.yml -f dry_run=true                         # Test
```

---

## Marketplace Timezones

| Marketplace | Timezone | Region |
|-------------|----------|--------|
| USA | America/Los_Angeles (PST) | NA |
| CA | America/Los_Angeles (PST) | NA |
| MX | America/Los_Angeles (PST) | NA |
| UK | Europe/London (GMT) | EU |
| DE | Europe/Berlin (CET) | EU |
| FR | Europe/Paris (CET) | EU |
| IT | Europe/Rome (CET) | EU |
| ES | Europe/Madrid (CET) | EU |
| UAE | Asia/Dubai (GST) | EU |
| AU | Australia/Sydney (AEST) | FE |
| JP | Asia/Tokyo (JST) | FE |

### Authorized Regions & Marketplaces

**NA Region:**
| Country | Code | Amazon ID |
|---------|------|-----------|
| USA | USA | ATVPDKIKX0DER |
| Canada | CA | A2EUQ1WTGCTBG2 |
| Mexico | MX | A1AM78C64UM0Y8 |

**EU Region:**
| Country | Code | Amazon ID |
|---------|------|-----------|
| UK | UK | A1F83G8C2ARO7P |
| Germany | DE | A1PA6795UKMFR9 |
| France | FR | A13V1IB3VIYZZH |
| Italy | IT | APJ6JRA9NG5V4 |
| Spain | ES | A1RKKUPIHCS9HS |
| UAE | UAE | A2VIGQ35RCS4UG |

**FE Region:**
| Country | Code | Amazon ID |
|---------|------|-----------|
| Australia | AU | A39IBJ37TRP1C6 |

**Not authorized** (Chalkola doesn't operate): Japan (JP)

---

## Quick Commands

```bash
# Check workflow status
gh run list --workflow=daily-pull.yml --limit 5
gh run list --workflow=inventory-daily.yml --limit 5
gh run list --workflow=historical-backfill.yml --limit 5
gh run list --workflow=orders-daily.yml --limit 5
gh run list --workflow=sqp-weekly.yml --limit 5
gh run list --workflow=sqp-backfill.yml --limit 5
gh run list --workflow=settlements-weekly.yml --limit 5
gh run list --workflow=settlement-backfill.yml --limit 5
gh run list --workflow=reimbursements-weekly.yml --limit 5
gh run list --workflow=financial-daily.yml --limit 5

# View workflow logs
gh run view <run_id> --log | tail -50

# Manual triggers (all support -f region=NA/EU/FE)
gh workflow run daily-pull.yml
gh workflow run daily-pull.yml -f date=2026-02-05 -f region=EU
gh workflow run orders-daily.yml -f marketplace=UK -f region=EU
gh workflow run orders-daily.yml -f marketplace=USA -f dry_run=true
gh workflow run inventory-daily.yml -f report_type=all
gh workflow run sqp-weekly.yml
gh workflow run sqp-backfill.yml -f marketplace=CA -f report_type=SCP
gh workflow run settlements-weekly.yml -f region=EU
gh workflow run settlement-backfill.yml -f region=FE -f dry_run=true
gh workflow run reimbursements-weekly.yml -f start_date=2024-01-01
gh workflow run financial-daily.yml -f region=EU
```

```sql
-- Check sales data coverage
SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM sp_daily_asin_data;

-- Check orders vs S&T data by date
SELECT date, data_source, COUNT(*) as asins,
       SUM(units_ordered) as units, ROUND(SUM(ordered_product_sales)::numeric, 2) as sales
FROM sp_daily_asin_data
WHERE date >= CURRENT_DATE - 3
GROUP BY date, data_source
ORDER BY date DESC, data_source;

-- Check recent data by marketplace
SELECT
    m.name as marketplace,
    MAX(d.date) as latest_date,
    COUNT(DISTINCT d.date) as total_days
FROM sp_daily_asin_data d
JOIN marketplaces m ON d.marketplace_id = m.id
GROUP BY m.name;

-- Check backfill progress
SELECT
    m.name as marketplace,
    MIN(d.date) as earliest,
    MAX(d.date) as latest,
    COUNT(DISTINCT d.date) as days,
    ROUND(COUNT(DISTINCT d.date)::numeric / 730 * 100, 1) as pct
FROM sp_daily_asin_data d
JOIN marketplaces m ON d.marketplace_id = m.id
GROUP BY m.name;

-- Check FBA inventory
SELECT date, COUNT(*) as records, SUM(fulfillable_quantity) as fulfillable
FROM sp_fba_inventory GROUP BY date ORDER BY date DESC LIMIT 5;

-- Check pull status (find 0 ASIN pulls that need re-pull)
SELECT pull_date, asin_count, status, started_at
FROM sp_api_pulls
WHERE pull_date >= CURRENT_DATE - 7
ORDER BY started_at DESC LIMIT 20;

-- Check monthly inventory snapshots
SELECT snapshot_date, marketplace_id, COUNT(*) as skus,
       SUM(total_quantity) as total_units
FROM sp_inventory_monthly_snapshots
GROUP BY snapshot_date, marketplace_id
ORDER BY snapshot_date DESC;

-- Check SQP/SCP pull status
SELECT report_type, period_type, period_start, period_end, status,
       total_asins_requested, total_rows, completed_batches, total_batches
FROM sp_sqp_pulls ORDER BY period_start DESC LIMIT 20;

-- Check SQP data coverage
SELECT period_type, MIN(period_start), MAX(period_start), COUNT(DISTINCT period_start) as periods,
       COUNT(DISTINCT child_asin) as asins, COUNT(*) as rows
FROM sp_sqp_data GROUP BY period_type;

-- Check SCP data coverage
SELECT period_type, MIN(period_start), MAX(period_start), COUNT(DISTINCT period_start) as periods,
       COUNT(DISTINCT child_asin) as asins, COUNT(*) as rows
FROM sp_scp_data GROUP BY period_type;

-- Check suppressed ASINs
SELECT marketplace_id, child_asin, error_type, occurrence_count
FROM sp_sqp_asin_errors WHERE suppressed = true;

-- Check settlement data
SELECT
    m.name as marketplace,
    COUNT(DISTINCT settlement_id) as settlements,
    COUNT(*) as transactions,
    MIN(posted_date_time) as earliest,
    MAX(posted_date_time) as latest
FROM sp_settlement_transactions t
JOIN marketplaces m ON t.marketplace_id = m.id
GROUP BY m.name;

-- Check settlement summaries
SELECT settlement_id, settlement_start_date, settlement_end_date,
       total_amount, currency_code
FROM sp_settlement_summaries
ORDER BY settlement_end_date DESC LIMIT 10;

-- Check financial pull tracking
SELECT report_type, status, COUNT(*) as pulls,
       SUM(row_count) as total_rows
FROM sp_financial_pulls
GROUP BY report_type, status;

-- Check reimbursements
SELECT
    m.name as marketplace,
    COUNT(*) as records,
    SUM(amount_total) as total_reimbursed,
    MIN(approval_date) as earliest,
    MAX(approval_date) as latest
FROM sp_reimbursements r
JOIN marketplaces m ON r.marketplace_id = m.id
GROUP BY m.name;

-- Check FBA fee estimates
SELECT
    m.name as marketplace,
    COUNT(*) as skus,
    AVG(estimated_fee_total) as avg_total_fee,
    MAX(pull_date) as last_updated
FROM sp_fba_fee_estimates f
JOIN marketplaces m ON f.marketplace_id = m.id
GROUP BY m.name;
```

---

## Automation Summary

All systems are fully automated with no manual intervention required. All workflows run for **3 regions (NA, EU, FE)** in parallel using GitHub Actions matrix strategy (`fail-fast: false`).

| System | Schedule | Regions | Status |
|--------|----------|---------|--------|
| **Daily Sales Pull** | 4x/day (2, 8, 14, 20 UTC) | NA, EU, FE | ✅ Running |
| **Near-Real-Time Orders** | 6x/day (0, 4, 8, 12, 16, 20 UTC) | NA, EU, FE | ✅ Running |
| **14-Day Attribution Refresh** | 4x/day (with daily pull) | NA, EU, FE | ✅ Running |
| **Materialized View Refresh** | After each daily pull (NA only) | NA | ✅ Running |
| **FBA/AWD Inventory** | 3 AM UTC daily | NA, EU, FE (AWD: NA only) | ✅ Running |
| **Monthly Inventory Snapshot** | 1st-2nd of month | NA | ✅ Configured |
| **Storage Fees** | 5th of month | NA, EU, FE | ✅ Configured |
| **Historical Backfill** | 4x/day (0, 6, 12, 18 UTC) | NA, EU, FE | 🔄 Running |
| **SQP/SCP Weekly Pull** | Tuesdays 4 AM UTC | NA only | ✅ Verified & Running |
| **SQP/SCP Backfill** | 3x/day (1, 9, 17 UTC) | NA only | ✅ Running |
| **Settlement Reports** | Tuesdays 7 AM UTC | NA, EU, FE | ✅ Running |
| **Settlement Backfill** | Manual trigger | NA, EU, FE | ✅ Available |
| **Reimbursements** | Mondays 6 AM UTC | NA, EU, FE | ⚠️ USA/CA FATAL (MX working) |
| **FBA Fee Estimates** | Daily 5 AM UTC | NA, EU, FE | ✅ Working |

---

## Known Limitations

- **Sales & Traffic Report Delay**: Amazon's Sales & Traffic report has ~12-24hr delay. Pulling "today" returns 0 ASINs. System defaults to yesterday's date.
- **Inventory Age**: Amazon's `GET_FBA_INVENTORY_AGED_DATA` returns FATAL status. This is a known widespread issue. Fallback report works but lacks age bucket data.
- **GitHub Timeout**: Each backfill run has 5.5-hour limit (GitHub's max is 6 hours). Fixed by running 4x/day.
- **Settlement Report Uniqueness**: Amazon provides no row-level unique ID — system uses MD5 hash of 11 key fields for deduplication.
- **Settlement 90-Day API Lookback**: Amazon's `getReports` API `createdSince` parameter has a maximum 90-day lookback. Dates older than 90 days return HTTP 400. Historical settlement data before that window cannot be retrieved via API. Current coverage: Oct 2025 → present.
- **Settlement Architecture**: Amazon's LIST API returns ALL NA-region settlements regardless of marketplace filter. Scripts run once per region (not per marketplace) and attribute each row to the correct marketplace via `marketplace-name` field with currency fallback.
- **FBA Fee Estimates**: Only show CURRENT fees, not historical. Settlement reports are the source of truth for historical fee data.
- **Reimbursement Multi-SKU**: One reimbursement case can cover multiple SKUs. Unique constraint is `(marketplace_id, reimbursement_id, sku)`.
- **Amazon API FATAL**: USA/CA Reimbursements and Inventory Age return FATAL status. This is a known widespread Amazon API issue. Cron retries automatically. FBA Fee Estimates now working for all 3 NA marketplaces (resolved ~Feb 8, 2026).
- **SQP Large Upserts**: USA SQP generates ~6,000+ rows per weekly pull. Fixed: upserts now use 200-row chunks and write per-batch (not accumulated). Verified working Feb 7, 2026.
- **Cross-Workflow Rate Limits**: Each GitHub Actions workflow has its own `RateLimitHandler` (per-process, no shared state). This is fine — total usage is ~150-200 createReport calls/day out of 1,440 available (1/min). Retry/backoff handles any 429 collisions.
- **~~FBA Inventory Pagination~~** *(FIXED Feb 9, 2026)*: Code read `nextToken` from `result["payload"]` instead of `result["pagination"]`, causing only 50 of ~735 records to be stored per marketplace per day. All historical FBA inventory data (4 days) had only 50 records each. Fixed in `fba_inventory_api.py`. Verified: 735 records across 15 pages now stored correctly.

---

## Google Sheets Integration ✅ WORKING

**Replaces:** GorillaROI ($600/month)

### Architecture: Flat Dump Sheets + SUMIFS Formulas

```
SUPABASE DATABASE
        │
        ├─── DAILY DATA (Direct to sheet)
        │    Script auto-detects dates, writes directly
        │
        ├─── SP Data {country}      - Weekly/Monthly sales + traffic
        ├─── SP Rolling {country}   - Rolling 7/14/30/60 day metrics
        ├─── SP Inventory {country} - Latest FBA + AWD inventory snapshot
        └─── SP Fees {country}      - Per-unit fee estimates + settlement actuals + storage
```

**Why this design:**
- All data dumped to flat sheets → user writes SUMIFS/INDEX formulas to pull what they need
- No GorillaROI-style per-cell API calls = no timeouts
- Pagination support: handles >1000 rows (USA weekly has 20,760+ rows)
- Daily data: Rolling 30-day window, direct write is simpler

### Google Sheet

| Property | Value |
|----------|-------|
| Name | API - Business Amazon 2026 |
| URL | https://docs.google.com/spreadsheets/d/17nR0UFAOXul80mxzQeqBt2aAZ2szdYwVUWnc490NSbk |
| Apps Script Project | https://script.google.com/u/2/home/projects/105bgL_S41PBK6M3CBOHkZ9A9-TXL3hIPJDu5ouk_D8nBT-p-LQKUvZvb/edit |
| Local Script Copy | `/Sp-API/google-sheets/supabase_sales.gs` |
| Config | "Script Config" tab, rows 88-93 |

### Marketplace UUIDs

| Country | Code | UUID |
|---------|------|------|
| USA | USA | `f47ac10b-58cc-4372-a567-0e02b2c3d479` |
| Canada | CA | `a1b2c3d4-58cc-4372-a567-0e02b2c3d480` |
| Mexico | MX | `c9d0e1f2-58cc-4372-a567-0e02b2c3d488` |
| UK | UK | `b2c3d4e5-58cc-4372-a567-0e02b2c3d481` |
| Germany | DE | `c3d4e5f6-58cc-4372-a567-0e02b2c3d482` |
| France | FR | `d4e5f6a7-58cc-4372-a567-0e02b2c3d483` |
| UAE | UAE | `e5f6a7b8-58cc-4372-a567-0e02b2c3d484` |
| Australia | AU | `f6a7b8c9-58cc-4372-a567-0e02b2c3d485` |
| Japan | JP | `a7b8c9d0-58cc-4372-a567-0e02b2c3d486` |
| Italy | IT | `b8c9d0e1-58cc-4372-a567-0e02b2c3d487` |
| Spain | ES | `d0e1f2a3-58cc-4372-a567-0e02b2c3d489` |

### Apps Script Menu

```
Supabase Data:
├── Test Connection
├── Daily Sheets
│   ├── Refresh Current Sheet (auto-detects dates)
│   └── Refresh TESTING Sheet
├── Sales (Weekly/Monthly)
│   ├── Refresh SP Data USA
│   ├── Refresh SP Data CA
│   └── Refresh SP Data MX
├── Rolling Averages
│   ├── Refresh SP Rolling USA
│   ├── Refresh SP Rolling CA
│   └── Refresh SP Rolling MX
├── Inventory
│   ├── Refresh SP Inventory USA
│   ├── Refresh SP Inventory CA
│   └── Refresh SP Inventory MX
├── Fees & Costs
│   ├── Refresh SP Fees USA
│   ├── Refresh SP Fees CA
│   └── Refresh SP Fees MX
├── Refresh ALL
│   ├── Refresh ALL USA
│   ├── Refresh ALL CA
│   └── Refresh ALL MX
├── Debug
│   ├── Check Sheet Dates
│   └── Check Sheet ASINs
└── Show Formula Examples
```

### Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| Supabase connection | ✅ Working | Test connection passes |
| Daily sheet refresh | ✅ Working | Auto-detects date columns, returns 0 (not blank) |
| Pagination (>1000 rows) | ✅ Fixed | Range header pagination, Content-Range parsing |
| SP Data USA sheet | ✅ Working | ~6,959 monthly + ~20,760 weekly rows (with pagination) |
| SP Data CA/MX | ✅ Ready | Menu functions ready |
| SP Rolling sheets | ✅ Ready | USA: ~569 rows, CA: ~299, MX: ~157 |
| SP Inventory sheets | ✅ Ready | FBA + AWD joined by SKU, ~735 rows/country (pagination fixed) |
| SP Fees sheets | ✅ Ready | Fee estimates + settlement actuals + storage |
| SUMIFS formulas | ✅ Working | Jan/Feb 2026 pulling correctly |

### Formula for Monthly Data (SP Data sheet)

**Single cell formula** (converts "Dec25" text to "2025-12-01"):
```
=IFERROR(SUMIFS('SP Data USA'!$D:$D,
  'SP Data USA'!$A:$A, "monthly",
  'SP Data USA'!$B:$B, $C5,
  'SP Data USA'!$C:$C,
  TEXT(DATE(IF(VALUE(RIGHT(BB$4,2))<50,2000,1900)+VALUE(RIGHT(BB$4,2)),
       MATCH(LEFT(BB$4,3),{"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"},0), 1),
       "yyyy-mm-dd")), 0)
```

**SP Data columns reference:**
| Col | Field |
|-----|-------|
| A | data_type (monthly/weekly) |
| B | child_asin |
| C | period (YYYY-MM-DD) |
| D | units_ordered |
| E | units_ordered_b2b |
| F | ordered_product_sales |
| G | ordered_product_sales_b2b |
| H | sessions |
| I | page_views |
| J | avg_buy_box_percentage |
| K | avg_conversion_rate |

**SP Rolling columns reference:**
| Col | Field | Source |
|-----|-------|--------|
| A | child_asin | sp_rolling_asin_metrics_mat |
| B | parent_asin | sp_rolling_asin_metrics_mat |
| C | currency | currency_code |
| D-H | units_7d, revenue_7d, avg_units_7d, sessions_7d, conversion_7d | 7-day window |
| I-M | units_14d, revenue_14d, avg_units_14d, sessions_14d, conversion_14d | 14-day window |
| N-R | units_30d, revenue_30d, avg_units_30d, sessions_30d, conversion_30d | 30-day window |
| S-W | units_60d, revenue_60d, avg_units_60d, sessions_60d, conversion_60d | 60-day window |

**SP Inventory columns reference:**
| Col | Field | Source |
|-----|-------|--------|
| A | asin | sp_fba_inventory |
| B | sku | sp_fba_inventory |
| C | product_name | sp_fba_inventory |
| D | fba_fulfillable | fulfillable_quantity |
| E | fba_reserved | reserved_quantity |
| F | fba_inbound_working | inbound_working_quantity |
| G | fba_inbound_shipped | inbound_shipped_quantity |
| H | fba_inbound_receiving | inbound_receiving_quantity |
| I | fba_unsellable | unsellable_quantity |
| J | fba_total | total_quantity |
| K | awd_onhand | total_onhand_quantity (joined via SKU) |
| L | awd_inbound | total_inbound_quantity |
| M | awd_available | available_quantity |
| N | awd_total | total_quantity |

**SP Fees columns reference:**
| Col | Field | Source | Purpose |
|-----|-------|--------|---------|
| A | asin | sp_fba_fee_estimates | |
| B | sku | sp_fba_fee_estimates | |
| C | product_size_tier | sp_fba_fee_estimates | |
| D | your_price | sp_fba_fee_estimates | Current listing price |
| E | est_fee_total | estimated_fee_total | Total per-unit fee (referral + FBA) |
| F | est_referral_per_unit | estimated_referral_fee_per_unit | Referral fee component |
| G | est_fba_per_unit | est_fee_total - referral (computed) | **FBA fee for CM1** |
| H | settle_avg_fba_per_unit | sp_settlement_fees_by_sku | Actual avg FBA fee (negative) |
| I | settle_avg_referral_per_unit | sp_settlement_fees_by_sku | Actual avg referral (negative) |
| J | settle_fba_qty_basis | sp_settlement_fees_by_sku | Units the avg is based on |
| K | storage_fee_latest_month | sp_storage_fees_by_asin | Monthly storage cost |
| L | storage_avg_qty_on_hand | sp_storage_fees_by_asin | Avg units stored |

### Database Views for Google Sheets

3 views created (via Supabase MCP, not migration file) to support the dump sheets:

| View | Purpose | Row Count | Source |
|------|---------|-----------|--------|
| `sp_storage_fees_by_asin` | Aggregates per-FC storage → per-ASIN | ~202 | `sp_storage_fees` |
| `sp_settlement_fees_by_sku` | Per-SKU avg FBA + referral fees from settlements | ~373 | `sp_settlement_transactions` |
| `sp_sku_asin_map` | Canonical SKU→ASIN mapping from all sources | ~1,669 | FBA inv + fee est + storage |

**RLS Policies Added (anon read):**
- `sp_fba_inventory` — anon SELECT
- `sp_awd_inventory` — anon SELECT
- `sp_storage_fees` — anon SELECT
- `sp_settlement_transactions` — RLS disabled (no policy needed)
- `sp_fba_fee_estimates` — RLS disabled (no policy needed)

### Key Technical Details

**Pagination Fix:** Supabase REST API returns max 1000 rows by default. `fetchAllFromSupabase()` uses `Range: 0-999` header + `Prefer: count=exact`, reads `Content-Range` response header for total count, loops with offset increments. Fixes USA weekly (20,760 rows) and monthly (6,959 rows) that were previously silently truncated to 1,000.

**FBA Fee Computation:** `est_fba_per_unit = est_fee_total - est_referral_per_unit`. If `pick_pack_fee` + `weight_handling_fee` are available (CA/MX), uses those instead (more accurate).

**AWD Inventory Join:** AWD table has SKU only (no ASIN). Script joins AWD to FBA by SKU first. Unmatched AWD SKUs get ASIN via `sp_sku_asin_map` view. AWD is USA-only (~62 SKUs).

**Settlement Fees:** Negative values (Amazon charges). GorillaROI shows ~$6.10 for 40 Chalk 6mm; settlement avg shows $6.04; fee estimate shows $5.82. Both sources included so user can choose.

### Pending: Formula Integration

1. **Date format mismatch** - Header shows "Dec25" (text), SP Data has "2025-12-01". Formula needs to convert. Working formula provided above.
2. **Archive fallback** - For historical data not in SP Data, formula should fall back to Archive sheets (existing INDEX/INDIRECT logic)
3. **Array formulas** - Single formula to fill entire data grid (BYROW/BYCOL with LAMBDA)

---

## Pending Tasks

### Immediate: Google Sheets — Copy Script & Test Dumps
1. Copy updated `supabase_sales.gs` from `/Sp-API/google-sheets/supabase_sales.gs` to Apps Script editor
2. Run `refreshSPDataUSA()` — verify row count >1000 (should be ~27,700 with pagination fix)
3. Run `refreshRollingUSA()` — verify ~569 rows with 7/14/30/60 day data
4. Run `refreshInventoryUSA()` — verify ~735 rows with FBA + AWD columns (pagination fixed)
5. Run `refreshFeesUSA()` — verify fee estimates + settlement + storage populated
6. Run CA and MX refreshes
7. Verify fee data accuracy against GorillaROI (e.g., 40 Chalk 6mm ≈ $6.10/unit)

### Next: Google Sheets Formula Refinement
1. Test the date conversion formula for older months (Dec25, Nov25, etc.)
2. Create unified formula that checks SP Data first, falls back to Archive
3. Consider adding hidden row with "yyyy-mm-dd" dates for simpler formulas
4. Write SUMIFS formulas for new dump sheets (Rolling, Inventory, Fees)

### Monitoring: Automated Systems
- **SQP/SCP Backfill** — Running 3x/day (1, 9, 17 UTC). Estimated completion ~19 days from Feb 8, 2026. CA HTTP 403 on older weeks (Brand Analytics auth issue, not code bug).
- **Reimbursements** — USA/CA return FATAL (Amazon API issue). MX working (914 rows). Cron retries every Monday 6 AM UTC. Consider Amazon support ticket if persists.
- **Settlement 90-day lookback** — API only allows 90-day lookback. Current coverage: Oct 2025 → present. Jan 2024 → Oct 2025 NOT available via API. Options: manual Seller Central download, GorillaROI export, or accept rolling window.

### Future: Phase 4 — Product Master Data & COGS
1. Product master table for COGS (manual entry initially via Google Sheets)
2. Map SKU → ASIN → COGS for CM1 calculation

### Future: Phase 5 — CM1/CM2 Calculation Engine
1. CM1/CM2 calculation views (combine settlements + COGS + ad spend from POP)
2. Organic Sales = Total Sales - PPC Sales
3. True TACOS = Ad Spend / Total Sales

### Future: Phase 6 — Web Dashboard

---

## GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `SP_LWA_CLIENT_ID` | Amazon SP-API credentials (shared across all regions) |
| `SP_LWA_CLIENT_SECRET` | Amazon SP-API credentials (shared across all regions) |
| `SP_REFRESH_TOKEN_NA` | North America refresh token (USA, CA, MX) |
| `SP_REFRESH_TOKEN_EU` | Europe refresh token (UK, DE, FR, IT, ES, UAE) |
| `SP_REFRESH_TOKEN_FE` | Far East refresh token (AU) |
| `SUPABASE_URL` | Database URL |
| `SUPABASE_SERVICE_KEY` | Database access |
| `SLACK_WEBHOOK_URL` | Slack alerts for failures |

---

*Last Updated: February 9, 2026 (Session 15 — Multi-region expansion: EU (UK, DE, FR, IT, ES, UAE) and FE (AU) now fully supported. auth.py uses per-region token cache. All 11 scripts accept --region arg. All 9 workflows use region matrix strategy (NA/EU/FE in parallel). IT, ES, MX marketplaces activated in Supabase. JP excluded — Chalkola doesn't operate there. SQP/SCP remain NA-only pending Brand Analytics availability confirmation.)*
