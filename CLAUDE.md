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
| Backfill | 🔄 Auto-running 4x/day (all 4 regions) |
| NA Authorization | ✅ USA, CA, MX working |
| EU Authorization | ✅ UK, DE, FR, IT, ES working |
| FE Authorization | ✅ AU working |
| UAE Authorization | ✅ Working (separate seller account, own refresh token) |

**Data Available:**
- `units_ordered`, `ordered_product_sales` - Sales metrics
- `sessions`, `page_views` - Traffic metrics
- `buy_box_percentage`, `unit_session_percentage` - Performance

**Date Logic:**
- Each marketplace uses its own timezone (USA/CA/MX = PST, UK = GMT, etc.)
- Default: Yesterday in marketplace timezone (Sales & Traffic has ~12-24hr delay)
- 14-day attribution refresh catches updates to recent data
- Re-pulls dates with 0 ASINs automatically

**EU/FE Data Validation (Feb 9, 2026):**
- **Sales UK (Feb 7):** 191 units in Supabase vs 191 in Excel — **100% match**
- **Sales DE (Feb 7):** 100 units vs 99 — **99% match** (attribution timing)
- **Sales AU (Feb 7):** 48 units vs 47 — **98% match**
- Per-ASIN spot checks: top ASINs exact match across UK, DE, AU

### Phase 1.5: Near-Real-Time Orders ✅ COMPLETE & VERIFIED

| Component | Status | Details |
|-----------|--------|---------|
| **Orders Report** | ✅ Working | `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` |
| **Daily Pull** | ✅ Running 6x/day | Every 4 hours UTC, all 4 regions |
| **S&T Protection** | ✅ Verified | Orders don't overwrite existing S&T data |
| **data_source column** | ✅ Applied | Tracks 'orders' vs 'sales_traffic' per row |

**Architecture:**
- Orders report provides same-day sales data (~30min delay) — units + revenue only
- Sales & Traffic report arrives 24-48hrs later with traffic metrics (sessions, page views, buy box %)
- Both write to same `sp_daily_asin_data` table
- `data_source` column tracks which report populated each row
- When S&T arrives, it overwrites orders data with attribution-corrected values + traffic

### Phase 2: Inventory Data ✅ COMPLETE

| Data | Source | Status | Records |
|------|--------|--------|---------|
| **FBA Inventory (NA)** | FBA Inventory API (v1/summaries) | ✅ Working | 735 records/marketplace |
| **FBA Inventory (EU/FE)** | `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` report | ✅ Working | UK:231, DE:201, FR:146, IT:140, ES:141, AU:97 |
| **AWD Inventory** | AWD API (v2024-05-09) | ✅ Working | 62 records (14,363 units) |
| **Storage Fees** | Reports API | ✅ Working | 14,227 records/month |
| **Inventory Age** | Reports API | ⚠️ BLOCKED | Amazon API returns FATAL |

**Dual Inventory Strategy:**
- **NA marketplaces**: FBA Inventory API v1 — fast, includes detailed breakdowns (reserved sub-types, damaged counts)
- **EU/FE marketplaces**: `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` report — includes Pan-European FBA (EFN) cross-border columns (`afn-fulfillable-quantity-local` + `afn-fulfillable-quantity-remote`). The API only returns physically local FC stock, which is wrong for EU marketplaces where inventory is shared across countries.
- New DB columns: `fulfillable_quantity_local`, `fulfillable_quantity_remote` for EU EFN visibility

**EU/FE Inventory Validation (Feb 9, 2026):**
- **UK:** Excel 41,626 vs Supabase 41,631 (0.01% variance) — spot checks exact
- **DE:** Excel 13,302 vs Supabase 12,982 (2.4%) — report data, acceptable timing variance
- **AU:** Excel 2,647 vs Supabase 2,464 (6.9%) — spot checks exact, timing
- **UAE:** ⚠️ NOT WORKING — needs separate refresh token (different seller account)

### Phase 2.5: Search Query Performance (SQP/SCP) ✅ COMPLETE & VERIFIED

| Data | Report Type | Status | Granularity |
|------|-------------|--------|-------------|
| **SQP** (per-query) | `GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT` | ✅ Working | Weekly, Monthly |
| **SCP** (per-ASIN) | `GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT` | ✅ Working | Weekly, Monthly |

**SQP** = Per-ASIN, per-search-query: impressions, clicks, cart adds, purchases, shares, median prices
**SCP** = Per-ASIN aggregate: same funnel + `search_traffic_sales` (revenue) + `conversion_rate`

**Marketplaces:** NA (USA, CA) + EU (UK, DE, FR, IT, ES, UAE) + FE (AU) — all via multi-region matrix

**Key Constraints:**
- No daily granularity — Weekly (Sun-Sat) is finest
- 200-char ASIN limit per request (~18 ASINs per batch)
- ~48hr data delay after period ends
- Brand-registered ASINs only
- ~1 createReport/min rate limit (shared with all report types)
- Historical data available ~Dec 2023 onward (~113 weeks)

### Phase 3: Financial Reports ✅ COMPLETE & VERIFIED

**PRIMARY for CM2**: Settlement Reports contain **actual fees Amazon charged per order** — not estimates.

| Report Type | SP-API Report | Script | Status | Records |
|-------------|---------------|--------|--------|---------|
| **Settlement Reports** | `GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2` | `pull_settlements.py` / `backfill_settlements.py` | ✅ **Working** | 536,744 tx, 21 summaries (NA) + EU/FE landing |
| **Reimbursements** | `GET_FBA_REIMBURSEMENTS_DATA` | `pull_reimbursements.py` | ⚠️ **Partial** (API FATAL on USA/CA) | 914 (MX only) |
| **FBA Fee Estimates** | `GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA` | `pull_fba_fees.py` | ✅ **Working** (NA + EU/FE) | 1,560+ |
| **Storage Fees** | `GET_FBA_STORAGE_FEE_CHARGES_DATA` | `pull_storage_fees.py` | ✅ Working (Phase 2) | 14,227 |

### Phase 4: Product Master Data ⏸️ PENDING

### Phase 5: CM1/CM2 Calculation Engine ⏸️ PENDING

### Phase 6: Web Dashboard ⏸️ PENDING

---

## Project Structure

```
/Sp-API/
├── scripts/
│   ├── pull_daily_sales.py        # Daily sales & traffic pull (timezone-aware)
│   ├── pull_inventory.py          # FBA inventory (API for NA, report for EU/FE)
│   ├── pull_awd_inventory.py      # AWD inventory (uses AWD API, NA only)
│   ├── pull_inventory_age.py      # Inventory age buckets (--fallback option)
│   ├── pull_storage_fees.py       # Monthly storage fees
│   ├── pull_sqp.py                # Weekly SQP/SCP search performance pull (multi-region)
│   ├── pull_orders_daily.py       # 6x/day near-real-time orders (~30min delay)
│   ├── pull_settlements.py        # Weekly settlement report pull (LIST → DOWNLOAD)
│   ├── pull_reimbursements.py     # Weekly reimbursement report pull
│   ├── pull_fba_fees.py           # Daily FBA fee estimates pull
│   ├── backfill_historical.py     # 2-year sales backfill (with skip-existing)
│   ├── backfill_sqp.py            # SQP/SCP historical backfill (multi-region)
│   ├── backfill_settlements.py    # Settlement backfill to Jan 2024
│   ├── refresh_recent.py          # Late attribution refresh
│   ├── refresh_views.py           # Refresh materialized views
│   ├── capture_monthly_inventory.py  # Monthly inventory snapshots
│   └── utils/
│       ├── api_client.py          # Centralized HTTP client with retry/rate limiting
│       ├── pull_tracker.py        # Checkpoint & resume capability
│       ├── alerting.py            # Slack webhook notifications
│       ├── auth.py                # SP-API token refresh (per-region token cache)
│       ├── reports.py             # Sales & Traffic report helpers
│       ├── orders_reports.py      # Near-real-time orders report helpers
│       ├── sqp_reports.py         # SQP/SCP report helpers (Brand Analytics)
│       ├── inventory_reports.py   # Inventory report helpers (incl. EU EFN report)
│       ├── financial_reports.py   # Settlement, Reimbursement, FBA Fee helpers
│       ├── fba_inventory_api.py   # FBA Inventory API client (NA)
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
│   ├── sqp-backfill.yml           # 3x/day - SQP historical backfill
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
| `sp_fba_inventory` | Daily FBA inventory snapshot | `fulfillable_quantity`, `fulfillable_quantity_local`, `fulfillable_quantity_remote`, `reserved_quantity`, `inbound_*` |
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

All workflows support `--region` arg and run **4 regions (NA, EU, FE, UAE) in parallel** using GitHub Actions matrix strategy (`fail-fast: false`).

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
- **Strategy**: NA uses FBA Inventory API v1, EU/FE uses `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` report

```bash
gh workflow run inventory-daily.yml                                       # All types, all regions
gh workflow run inventory-daily.yml -f report_type=inventory              # FBA only
gh workflow run inventory-daily.yml -f report_type=awd                    # AWD only (NA only)
gh workflow run inventory-daily.yml -f region=EU                          # EU region only
```

### Near-Real-Time Orders (`orders-daily.yml`)
- **Schedule**: 6x/day at 0, 4, 8, 12, 16, 20 UTC
- **Data Source**: `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` (~30min delay)
- **S&T Protection**: Won't overwrite rows that already have Sales & Traffic data

```bash
gh workflow run orders-daily.yml                                    # All regions, today + yesterday
gh workflow run orders-daily.yml -f marketplace=USA                 # Single marketplace
gh workflow run orders-daily.yml -f region=EU                       # EU region only
```

### SQP/SCP Weekly Pull (`sqp-weekly.yml`)
- **Weekly Schedule**: Every Tuesday 4 AM UTC
- **Monthly Schedule**: 4th of month 4 AM UTC
- **Timeout**: 180 minutes

```bash
gh workflow run sqp-weekly.yml                                              # Latest week, all regions
gh workflow run sqp-weekly.yml -f report_type=SQP -f region=EU              # SQP only, EU
gh workflow run sqp-weekly.yml -f period_type=MONTH                         # Monthly
```

### SQP/SCP Backfill (`sqp-backfill.yml`)
- **Schedule**: 3x/day at 1, 9, 17 UTC
- **Default**: 2 periods per run, latest-first
- **Timeout**: 240 minutes

```bash
gh workflow run sqp-backfill.yml                                            # Default: 2 periods
gh workflow run sqp-backfill.yml -f marketplace=CA -f report_type=SCP       # Small test
```

### Settlement Reports Weekly (`settlements-weekly.yml`)
- **Schedule**: Every Tuesday 7 AM UTC
- **Pattern**: LIST available reports → DOWNLOAD each → Parse TSV → Upsert

```bash
gh workflow run settlements-weekly.yml                                      # Last 30 days, all regions
gh workflow run settlements-weekly.yml -f region=EU                          # EU region only
```

### Historical Backfill (`historical-backfill.yml`)
- **Schedule**: 4x/day at 0, 6, 12, 18 UTC until complete
- **Auto-skip**: Exits early if backfill is >99% complete

```bash
gh workflow run historical-backfill.yml -f mode=full              # All regions
gh workflow run historical-backfill.yml -f region=EU              # EU only
```

### Other Workflows

| Workflow | Schedule | Notes |
|----------|----------|-------|
| `storage-fees-monthly.yml` | 5th of month | Storage fees |
| `settlement-backfill.yml` | Manual | Backfill settlements to Jan 2024 |
| `reimbursements-weekly.yml` | Mondays 6 AM UTC | USA/CA FATAL, MX working |
| `financial-daily.yml` | Daily 5 AM UTC | FBA fee estimates |

---

## Marketplace Timezones

| Marketplace | Timezone | Region | Auth |
|-------------|----------|--------|------|
| USA | America/Los_Angeles (PST) | NA | `SP_REFRESH_TOKEN_NA` |
| CA | America/Los_Angeles (PST) | NA | `SP_REFRESH_TOKEN_NA` |
| MX | America/Los_Angeles (PST) | NA | `SP_REFRESH_TOKEN_NA` |
| UK | Europe/London (GMT) | EU | `SP_REFRESH_TOKEN_EU` |
| DE | Europe/Berlin (CET) | EU | `SP_REFRESH_TOKEN_EU` |
| FR | Europe/Paris (CET) | EU | `SP_REFRESH_TOKEN_EU` |
| IT | Europe/Rome (CET) | EU | `SP_REFRESH_TOKEN_EU` |
| ES | Europe/Madrid (CET) | EU | `SP_REFRESH_TOKEN_EU` |
| UAE | Asia/Dubai (GST) | UAE | `SP_REFRESH_TOKEN_UAE` (separate seller account) |
| AU | Australia/Sydney (AEST) | FE | `SP_REFRESH_TOKEN_FE` |

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

**UAE Region (Separate Seller Account — uses EU API endpoint, own refresh token):**
| Country | Code | Amazon ID |
|---------|------|-----------|
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
gh run list --workflow=financial-daily.yml --limit 5

# View workflow logs
gh run view <run_id> --log | tail -50

# Manual triggers (all support -f region=NA/EU/FE/UAE)
gh workflow run daily-pull.yml -f region=EU
gh workflow run orders-daily.yml -f marketplace=UK -f region=EU
gh workflow run inventory-daily.yml -f report_type=inventory -f region=EU
gh workflow run sqp-weekly.yml -f region=EU
gh workflow run settlements-weekly.yml -f region=EU
gh workflow run financial-daily.yml -f region=EU
```

```sql
-- Check sales data coverage by marketplace
SELECT
    m.name as marketplace,
    MIN(d.date) as earliest,
    MAX(d.date) as latest,
    COUNT(DISTINCT d.date) as days
FROM sp_daily_asin_data d
JOIN marketplaces m ON d.marketplace_id = m.id
GROUP BY m.name ORDER BY m.name;

-- Check FBA inventory by marketplace (today)
SELECT m.name, COUNT(*) as records,
       SUM(fulfillable_quantity) as fulfillable,
       SUM(fulfillable_quantity_local) as local_qty,
       SUM(fulfillable_quantity_remote) as remote_qty
FROM sp_fba_inventory i
JOIN marketplaces m ON i.marketplace_id = m.id
WHERE i.date = CURRENT_DATE
GROUP BY m.name ORDER BY m.name;

-- Check settlement data by marketplace
SELECT m.name, COUNT(DISTINCT settlement_id) as settlements,
       COUNT(*) as transactions, MIN(posted_date_time) as earliest
FROM sp_settlement_transactions t
JOIN marketplaces m ON t.marketplace_id = m.id
GROUP BY m.name;

-- Check SQP/SCP pull status (recent)
SELECT report_type, period_type, period_start, marketplace_id, status,
       total_rows, completed_batches, total_batches
FROM sp_sqp_pulls ORDER BY period_start DESC LIMIT 20;
```

---

## Automation Summary

All systems fully automated. All workflows run for **4 regions (NA, EU, FE, UAE)** in parallel using GitHub Actions matrix strategy.

| System | Schedule | Regions | Status |
|--------|----------|---------|--------|
| **Daily Sales Pull** | 4x/day (2, 8, 14, 20 UTC) | NA, EU, FE, UAE | ✅ Running |
| **Near-Real-Time Orders** | 6x/day (0, 4, 8, 12, 16, 20 UTC) | NA, EU, FE, UAE | ✅ Running |
| **14-Day Attribution Refresh** | 4x/day (with daily pull) | NA, EU, FE, UAE | ✅ Running |
| **Materialized View Refresh** | After each daily pull (NA only) | NA | ✅ Running |
| **FBA Inventory (API for NA, Report for EU/FE/UAE)** | 3 AM UTC daily | NA, EU, FE, UAE | ✅ Running |
| **AWD Inventory** | 3 AM UTC daily | NA only | ✅ Running |
| **Historical Backfill** | 4x/day (0, 6, 12, 18 UTC) | NA, EU, FE, UAE | 🔄 Running |
| **SQP/SCP Weekly Pull** | Tuesdays 4 AM UTC | NA, EU, FE, UAE | ✅ Running |
| **SQP/SCP Backfill** | 3x/day (1, 9, 17 UTC) | NA, EU, FE, UAE | 🔄 Running |
| **Settlement Reports** | Tuesdays 7 AM UTC | NA, EU, FE, UAE | ✅ Running |
| **Reimbursements** | Mondays 6 AM UTC | NA, EU, FE, UAE | ⚠️ USA/CA FATAL |
| **FBA Fee Estimates** | Daily 5 AM UTC | NA, EU, FE, UAE | ✅ Working |

---

## Known Limitations

- **Sales & Traffic Report Delay**: ~12-24hr delay. System defaults to yesterday's date.
- **Inventory Age**: `GET_FBA_INVENTORY_AGED_DATA` returns FATAL. Known Amazon issue.
- **GitHub Timeout**: Each backfill run has 5.5-hour limit. Fixed by running 4x/day.
- **Settlement 90-Day Lookback**: `getReports` API has max 90-day lookback. Current coverage: Oct 2025 → present.
- **Settlement Uniqueness**: No row-level unique ID — system uses MD5 hash of 11 key fields.
- **FBA Fee Estimates**: Only CURRENT fees, not historical. Settlements are source of truth for historical.
- **Amazon API FATAL**: USA/CA Reimbursements and Inventory Age return FATAL. Cron retries automatically.
- **UAE Separate Account**: UAE has a different Amazon seller account with its own refresh token (`SP_REFRESH_TOKEN_UAE`). UAE is treated as a 4th region in workflow matrices, using the EU API endpoint but its own auth credentials.
- **EU Inventory (Pan-European FBA)**: FBA Inventory API v1 only returns physically local FC stock. For EU, we use `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` report instead, which includes `afn-fulfillable-quantity-local` + `afn-fulfillable-quantity-remote` columns. Chalkola uses MCI (Multi-Country Inventory) so most EU stock is local per marketplace (remote = 0).
- **~~FBA Inventory Pagination~~** *(FIXED Feb 9, 2026)*: `nextToken` was read from wrong path. Fixed in `fba_inventory_api.py`.

---

## Google Sheets Integration ✅ WORKING

**Replaces:** GorillaROI ($600/month)

### Architecture: Flat Dump Sheets + SUMIFS Formulas

```
SUPABASE DATABASE
        │
        ├─── SP Data {country}      - Weekly/Monthly sales + traffic
        ├─── SP Rolling {country}   - Rolling 7/14/30/60 day metrics
        ├─── SP Inventory {country} - Latest FBA + AWD inventory snapshot
        └─── SP Fees {country}      - Per-unit fee estimates + settlement actuals + storage
```

### Google Sheet

| Property | Value |
|----------|-------|
| Name | API - Business Amazon 2026 |
| URL | https://docs.google.com/spreadsheets/d/17nR0UFAOXul80mxzQeqBt2aAZ2szdYwVUWnc490NSbk |
| Apps Script Project | https://script.google.com/u/2/home/projects/105bgL_S41PBK6M3CBOHkZ9A9-TXL3hIPJDu5ouk_D8nBT-p-LQKUvZvb/edit |
| Local Script Copy | `/Sp-API/google-sheets/supabase_sales.gs` |

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
| Italy | IT | `b8c9d0e1-58cc-4372-a567-0e02b2c3d487` |
| Spain | ES | `d0e1f2a3-58cc-4372-a567-0e02b2c3d489` |

### Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| Supabase connection | ✅ Working | Test connection passes |
| Pagination (>1000 rows) | ✅ Fixed | Range header pagination |
| SP Data USA sheet | ✅ Working | ~27,700 rows (with pagination) |
| SP Rolling sheets | ✅ Ready | USA: ~569 rows |
| SP Inventory sheets | ✅ Ready | FBA + AWD joined by SKU |
| SP Fees sheets | ✅ Ready | Fee estimates + settlement actuals + storage |
| SUMIFS formulas | ✅ Working | Jan/Feb 2026 pulling correctly |

---

## Pending Tasks

### ~~Immediate: UAE Separate Token Setup~~ ✅ DONE (Session 17)
- UAE added as 4th region in all workflows and scripts
- `SP_REFRESH_TOKEN_UAE` GitHub secret added
- All 30 files updated (auth, utils, scripts, workflows)
- Pending: validate inventory + sales data against Excel

### Google Sheets — Copy & Test
1. Copy updated `supabase_sales.gs` to Apps Script editor
2. Test all refresh functions (USA, CA, MX)
3. Add EU/FE marketplace menu entries
4. Verify fee data accuracy against GorillaROI

### Google Sheets — Formula Refinement
1. Test date conversion formula for older months
2. Create unified formula that checks SP Data first, falls back to Archive
3. Write SUMIFS formulas for dump sheets (Rolling, Inventory, Fees)

### Monitoring: Automated Systems
- **Historical Backfill (EU/FE)** — Just started running for EU/FE. Will fill 2 years of data.
- **SQP/SCP Backfill** — Running 3x/day. NA estimated ~19 days from Feb 8. EU/FE just started.
- **Reimbursements** — USA/CA return FATAL (Amazon API issue). MX working.
- **Settlement 90-day lookback** — API max 90-day window. Options: manual Seller Central download or accept rolling window.

### Future: Phase 4 — Product Master Data & COGS
1. Product master table for COGS (manual entry initially via Google Sheets)
2. Map SKU → ASIN → COGS for CM1 calculation

### Future: Phase 5 — CM1/CM2 Calculation Engine
1. CM1/CM2 calculation views (combine settlements + COGS + ad spend from POP)

### Future: Phase 6 — Web Dashboard

---

## GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `SP_LWA_CLIENT_ID` | Amazon SP-API credentials (shared across all regions) |
| `SP_LWA_CLIENT_SECRET` | Amazon SP-API credentials (shared across all regions) |
| `SP_REFRESH_TOKEN_NA` | North America refresh token (USA, CA, MX) |
| `SP_REFRESH_TOKEN_EU` | Europe refresh token (UK, DE, FR, IT, ES) |
| `SP_REFRESH_TOKEN_FE` | Far East refresh token (AU) |
| `SP_REFRESH_TOKEN_UAE` | UAE refresh token (separate seller account) |
| `SUPABASE_URL` | Database URL |
| `SUPABASE_SERVICE_KEY` | Database access |
| `SLACK_WEBHOOK_URL` | Slack alerts for failures |

---

*Last Updated: February 9, 2026 (Session 17 — UAE added as 4th region with separate refresh token. SP_REFRESH_TOKEN_UAE secret added. All 30 files updated: auth.py, 6 utils modules, 12 pull/backfill scripts, 11 workflow YAMLs. UAE uses EU API endpoint but own token. All workflows now run 4 regions (NA, EU, FE, UAE) in parallel. UAE inventory uses report-based approach same as EU.)*
