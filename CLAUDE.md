# SP-API Data Pull & CM2 Profitability System

## Project Goal

Build a complete **Contribution Margin (CM1/CM2) profitability system** by pulling data from Amazon SP-API, combining with POP advertising data, and calculating per-ASIN profitability metrics.

**Replaces:** GorillaROI ($600/month) + manual Excel tracking

**Key Calculations:**
- **Organic Sales** = Total Sales - PPC Sales
- **True TACOS** = Ad Spend / Total Sales
- **CM1** = Revenue - FBA Fees - COGS (gross profit before ads)
- **CM2** = CM1 - Ad Spend - Storage (net operating profit)

---

## Architecture

```
Amazon SP-API → GitHub Actions (2 AM UTC daily) → Supabase → Web App
                                                      ↑
POP System (Advertising API) ─────────────────────────┘
```

- **GitHub Actions**: Runs Python scripts on schedule
- **Supabase**: `chalkola-one-system` database (yawaopfqkkvdqtsagmng)
- **POP System**: Already has advertising data in same Supabase

---

## Implementation Phases

### Phase 1: Sales & Traffic Data ✅ COMPLETE
**Status:** Daily pulls running, 2-year backfill in progress

| Component | Status |
|-----------|--------|
| GitHub Repo | ✅ https://github.com/anuj29111/Sp-API |
| Python Scripts | ✅ Complete |
| GitHub Actions | ✅ Daily 2 AM UTC |
| Database Tables | ✅ `sp_daily_asin_data`, `sp_api_pulls` |
| NA Authorization | ✅ USA, CA, MX working |
| Full Backfill (2 years) | 🔄 Running (workflow 21676122116) |

**Data Available:**
- `units_ordered` - Units sold
- `ordered_product_sales` - Revenue ($)
- `sessions`, `page_views` - Traffic metrics
- `buy_box_percentage`, `unit_session_percentage` - Performance

### Phase 2: Financial Reports ⏸️ PENDING
**Purpose:** Get storage fees, reimbursements, promotions for CM2 calculation

| Report Type | SP-API Report | Data |
|-------------|---------------|------|
| Storage Fees | `GET_FBA_STORAGE_FEE_CHARGES_DATA` | Monthly storage costs per ASIN |
| Reimbursements | `GET_FBA_REIMBURSEMENTS_DATA` | Amazon reimbursements |
| Promotions | Settlement Report | Promo discounts given |
| Shipping Income | Settlement Report | FBA shipping credits |
| Other Income | Settlement Report | Misc adjustments |

### Phase 3: Inventory Reports ⏸️ PENDING
**Purpose:** Track inventory levels, age, stranded inventory

| Report Type | SP-API Report | Data |
|-------------|---------------|------|
| FBA Inventory | `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` | Current FBA stock |
| Inventory Age | `GET_FBA_INVENTORY_AGED_DATA` | Age buckets (0-90, 91-180, etc.) |
| Stranded | `GET_STRANDED_INVENTORY_UI_DATA` | Unfulfillable inventory |

### Phase 4: Product Master Data ⏸️ PENDING
**Purpose:** Store static per-ASIN costs for CM1 calculation

| Field | Description | Source |
|-------|-------------|--------|
| `fba_fees_per_unit` | Amazon fulfillment fee | Manual / FBA Fee Preview API |
| `cogs_per_unit` | Cost of goods sold | Manual entry |
| `shipping_to_fba` | Inbound shipping cost | Manual entry |
| `vat_rate` | VAT percentage (if applicable) | Manual entry |

### Phase 5: CM1/CM2 Calculation Engine ⏸️ PENDING
**Purpose:** Calculate profitability metrics

```sql
-- CM1 (Contribution Margin 1) - Gross profit before ads & storage
CM1 = Revenue - (FBA_Fees × Units) - (COGS × Units) - VAT

-- CM2 (Contribution Margin 2) - Net operating profit
CM2 = CM1 - Ad_Spend_SP - Ad_Spend_SD - Storage_Fees

-- Percentages
CM1% = CM1 / Revenue
CM2% = CM2 / Revenue
```

### Phase 6: Web Dashboard ⏸️ PENDING
**Purpose:** Display metrics in Chalkola ONE web app

---

## CM2 Calc Excel Analysis

**Source:** `Business Excel/Business Amazon -2025.xlsx` → Sheet "CM2 Calc"

### Sheet Structure (270 rows × 2,457 columns)
- **Rows 4-268**: ~265 ASINs
- **Columns**: Time-series from Jun 2022 onwards

### Data Sections in Excel

| Section | Columns | Description | Data Source |
|---------|---------|-------------|-------------|
| ASIN Info | 0-4 | Link, Price, ASIN, Name, Category | Static |
| Monthly Sales | 5-82 | Units sold per month | **SP-API** ✅ |
| Ad Spend SP | 83-161 | Sponsored Products spend | **POP System** ✅ |
| Weekly Sales | 162-392 | Units by week | **SP-API** ✅ |
| Monthly Revenue | 393-472 | Revenue ($) per month | **SP-API** ✅ |
| Ad Spend SD | 473-551 | Sponsored Display spend | **POP System** ✅ |
| Ad Sales | 552-630 | PPC-attributed sales | **POP System** ✅ |
| Storage | 631-709 | FBA storage fees | SP-API Phase 2 |
| Promotion | 710-787 | Promo discounts | SP-API Phase 2 |
| Reimbursement | 788-866 | Amazon reimbursements | SP-API Phase 2 |
| Shipping Income | 867-946 | FBA shipping credits | SP-API Phase 2 |
| Other Income | 947-1026 | Misc income | SP-API Phase 2 |
| Event Tracking | 1027-1135 | Prime Day, BFCM metrics | Derived |
| Daily Sales | 1136-2083 | Daily unit data | **SP-API** ✅ |
| Fixed Costs | 2085-2087 | FBAFees, COGS, VAT per ASIN | Manual (Phase 4) |
| CM1 Monthly | 2089-2153 | Contribution Margin 1 | Calculated (Phase 5) |
| CM2 Monthly | 2157-2221 | Contribution Margin 2 | Calculated (Phase 5) |
| CM1%/CM2% | 2222-2456 | Margin percentages + YTD | Calculated (Phase 5) |

### Event Dates Tracked
Prime Day and Fall Prime Day dates:
- 2023: Jul 11-12, Oct 10-11
- 2024: Jul 16-17, Oct 8-9
- 2025: Jul 8-11, Oct 7-8
- 2026+: Projected dates

---

## Data Source Mapping

| Data Needed | Source | Status | Phase |
|-------------|--------|--------|-------|
| Monthly Sales (units) | SP-API Sales & Traffic | ✅ Pulling | 1 |
| Monthly Revenue ($) | SP-API Sales & Traffic | ✅ Pulling | 1 |
| Daily Sales (units) | SP-API Sales & Traffic | ✅ Pulling | 1 |
| Sessions/Page Views | SP-API Sales & Traffic | ✅ Pulling | 1 |
| Ad Spend SP | POP System | ✅ In Supabase | - |
| Ad Spend SD | POP System | ✅ In Supabase | - |
| Ad Sales (PPC) | POP System | ✅ In Supabase | - |
| Storage Fees | SP-API FBA Reports | ⏸️ Pending | 2 |
| Promotions | SP-API Settlement | ⏸️ Pending | 2 |
| Reimbursements | SP-API Reimbursements | ⏸️ Pending | 2 |
| Shipping Income | SP-API Settlement | ⏸️ Pending | 2 |
| Other Income | SP-API Settlement | ⏸️ Pending | 2 |
| FBA Fees/unit | Manual / API | ⏸️ Pending | 4 |
| COGS/unit | Manual entry | ⏸️ Pending | 4 |

---

## Current Status

### Phase 1 Progress
| Component | Status |
|-----------|--------|
| GitHub Repo | ✅ https://github.com/anuj29111/Sp-API |
| Python Scripts | ✅ Complete |
| GitHub Actions Workflow | ✅ Complete |
| Database Tables | ✅ Created (with RLS) |
| GitHub Secrets | ✅ Configured |
| NA Authorization | ✅ Working (USA, CA, MX) |
| Daily Pull (Automated) | ✅ Running at 2 AM UTC |
| Late Attribution Refresh | ✅ Refreshes last 14 days |
| Weekly View | ✅ `sp_weekly_asin_data` |
| Rolling Metrics View | ✅ `sp_rolling_asin_metrics` |
| Test Backfill (7 days) | ✅ Passed |
| Full Backfill (2 years) | 🔄 Running (workflow 21676122116) |
| EU Authorization | ⏸️ Pending |
| FE Authorization | ⏸️ Pending |

---

## GitHub Actions Workflows

### 1. Daily Pull (`daily-pull.yml`)
- **Schedule**: 2 AM UTC daily
- **Modes**: `daily`, `refresh`, `both` (default)
- **Default behavior**: Pulls new day + refreshes last 14 days for late attribution

```bash
# Manual trigger examples
gh workflow run daily-pull.yml                         # Default: both modes
gh workflow run daily-pull.yml -f mode=daily           # Just new day
gh workflow run daily-pull.yml -f mode=refresh         # Just refresh last 14 days
gh workflow run daily-pull.yml -f date=2026-01-30 -f marketplace=USA
```

### 2. Historical Backfill (`historical-backfill.yml`)
- **Modes**: `test` (7 days), `month` (30), `quarter` (90), `year` (365), `full` (730)
- **Order**: Latest dates first (reverse chronological)
- **Timeout**: 6 hours per job

```bash
# Test first (7 days)
gh workflow run historical-backfill.yml -f mode=test

# Full 2-year backfill (~40 hours)
gh workflow run historical-backfill.yml -f mode=full

# Custom date range
gh workflow run historical-backfill.yml -f start_date=2024-01-01 -f end_date=2024-12-31
```

---

## Project Structure

```
/Sp-API/
├── scripts/
│   ├── pull_daily_sales.py     # Main daily pull script
│   ├── backfill_historical.py  # Historical backfill (2 years, latest first)
│   ├── refresh_recent.py       # Late attribution refresh (last N days)
│   └── utils/
│       ├── __init__.py
│       ├── auth.py             # SP-API token refresh
│       ├── reports.py          # Report API helpers
│       └── db.py               # Supabase operations (upsert support)
├── .github/workflows/
│   ├── daily-pull.yml          # Cron: 2 AM UTC daily + refresh
│   └── historical-backfill.yml # Manual: historical data backfill
├── Business Excel/
│   └── Business Amazon -2025.xlsx  # GorillaROI reference (Daily + CM2 Calc sheets)
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── CLAUDE.md                   # This file
```

---

## Database Tables & Views

All in Supabase project `yawaopfqkkvdqtsagmng` with `sp_` prefix:

| Table/View | Purpose |
|------------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic metrics |
| `sp_daily_totals` | Account-level daily totals per marketplace |
| `sp_api_pulls` | Track pull status (supports upsert for re-pulls) |
| `sp_monthly_asin_data` | **View** - Monthly aggregates by ASIN |
| `sp_weekly_asin_data` | **View** - Weekly aggregates (ISO weeks Mon-Sun) |
| `sp_rolling_asin_metrics` | **View** - Rolling 7/14/30/60 day metrics |

### Key Fields in sp_daily_asin_data
- `date`, `marketplace_id`, `child_asin` (unique constraint)
- Sales: `units_ordered`, `ordered_product_sales`, `currency_code`
- Traffic: `sessions`, `page_views`, `buy_box_percentage`, `unit_session_percentage`
- B2B variants of all metrics
- Note: `unit_session_percentage` can exceed 100% (multiple units per session)

### Database Functions
- `get_asin_rolling_metrics(asin, marketplace_id, days, end_date)` - Get rolling metrics for any period
- `get_marketplace_daily_totals(marketplace_id, start_date, end_date)` - Get daily totals for a marketplace

---

## GitHub Secrets (Configured)

| Secret | Status |
|--------|--------|
| `SP_LWA_CLIENT_ID` | ✅ |
| `SP_LWA_CLIENT_SECRET` | ✅ |
| `SP_REFRESH_TOKEN_NA` | ✅ |
| `SUPABASE_URL` | ✅ |
| `SUPABASE_SERVICE_KEY` | ✅ |

---

## Marketplaces

### Currently Authorized (NA Region)
| Country | Code | Amazon ID | Supabase UUID |
|---------|------|-----------|---------------|
| USA | USA | ATVPDKIKX0DER | f47ac10b-58cc-4372-a567-0e02b2c3d479 |
| Canada | CA | A2EUQ1WTGCTBG2 | a1b2c3d4-58cc-4372-a567-0e02b2c3d480 |
| Mexico | MX | A1AM78C64UM0Y8 | c9d0e1f2-58cc-4372-a567-0e02b2c3d488 |

### Pending Authorization
- **EU Region**: UK, Germany, France, Italy, Spain, UAE
- **FE Region**: Australia, Japan

---

## Rate Limits & Timing

| Operation | Limit | Notes |
|-----------|-------|-------|
| createReport | ~1/min | 65 second wait between requests |
| getReport | 2/sec | Used for polling |
| getReportDocument | ~1/min | Download rate limited |
| Batch pause | 2 min | Every 30 requests |
| Amazon data delay | 2 days | Data available ~34 hours after day ends |
| Late attribution | 14 days | Amazon may update data for up to 14 days |

---

## Debugging

### Check Pull Status
```sql
SELECT * FROM sp_api_pulls
ORDER BY started_at DESC
LIMIT 10;
```

### Check Data Coverage
```sql
SELECT
  MIN(date) as earliest,
  MAX(date) as latest,
  COUNT(DISTINCT date) as days_covered
FROM sp_daily_asin_data;
```

### Check Data by Date
```sql
SELECT
  date,
  m.code as marketplace,
  COUNT(*) as asin_count,
  SUM(units_ordered) as total_units,
  ROUND(SUM(ordered_product_sales)::numeric, 2) as total_sales
FROM sp_daily_asin_data d
JOIN marketplaces m ON d.marketplace_id = m.id
GROUP BY date, m.code
ORDER BY date DESC, m.code;
```

### Check Workflow Status
```bash
gh run list --workflow=historical-backfill.yml --limit 5
gh run view <run_id> --log | tail -50
```

---

## Known Issues & Fixes Applied

### 1. Numeric Column Overflow (Fixed)
- **Issue**: `unit_session_percentage` can exceed 100% (e.g., 3 units in 1 session = 300%)
- **Fix**: Changed NUMERIC(5,2) to NUMERIC(7,2) for percentage columns

### 2. Duplicate Pull Records (Fixed)
- **Issue**: Re-pulling same date/marketplace caused unique constraint violation
- **Fix**: Changed `create_pull_record()` to use upsert instead of insert

### 3. Views Depend on Column Types (Fixed)
- **Issue**: Can't alter column types when views depend on them
- **Fix**: Drop views → alter columns → recreate views (in single migration)

---

## Session Log

### Feb 4, 2026 (Session 4) - CM2 Calc Analysis ✅
**Completed:**
1. Analyzed CM2 Calc sheet structure (270 rows × 2,457 columns)
2. Identified all 16+ data sections in the Excel
3. Mapped each data requirement to its source (SP-API, POP, Manual)
4. Documented CM1/CM2 calculation formulas
5. Created implementation phase roadmap (Phases 1-6)
6. Updated CLAUDE.md with complete project scope

**Key Findings:**
- Phase 1 (Sales & Traffic) provides foundation ✅
- Phase 2 (Financial Reports) needed for storage, reimbursements
- Phase 4 (Product Master) needed for COGS/FBA fees per ASIN
- POP system already has advertising data we need

### Feb 4, 2026 (Session 3) - Backfill Workflow & Fixes ✅
**Completed:**
1. Fixed numeric column precision for percentage fields
2. Fixed pull record to use upsert for re-pulls
3. Created `scripts/refresh_recent.py` for late attribution refresh
4. Updated `daily-pull.yml` to support modes (daily/refresh/both)
5. Created `historical-backfill.yml` workflow with multiple modes
6. Modified backfill to process dates in reverse order (latest first)
7. ✅ Test backfill (7 days) completed successfully
8. 🔄 Started full 2-year backfill (workflow 21676122116)

### Feb 4, 2026 (Session 2) - Backfill & Aggregation ✅
**Completed:**
1. Analyzed GorillaROI Business Excel structure (400+ columns)
2. Mapped Excel columns to SP-API data sources (~70% replicable)
3. Created historical backfill script
4. Created weekly aggregation view (ISO weeks)
5. Created rolling metrics view

### Feb 4, 2026 (Session 1) - Initial Implementation ✅
**Completed:**
1. Created GitHub repo
2. Built Python scripts (auth, reports, db, main pull)
3. Set up GitHub Actions workflow
4. Created Supabase tables with RLS
5. Configured GitHub Secrets
6. Ran first successful pull - 346 ASINs

---

## Next Steps

### Immediate
1. **Monitor full backfill**: `gh run view 21676122116`
2. **Verify data coverage** after backfill completes

### Phase 2 Implementation
1. Add Storage Fee report pulling
2. Add Reimbursement report pulling
3. Add Settlement report parsing (promotions, shipping income)

### Phase 4 Implementation
1. Create `sp_product_master` table for static ASIN costs
2. Build UI for entering COGS/FBA fees per ASIN
3. Consider FBA Fee Preview API for automated fee lookup

### Phase 5 Implementation
1. Create CM1/CM2 calculation views
2. Join with POP advertising data
3. Build aggregation views (monthly, quarterly, YTD)

---

*Last Updated: February 4, 2026*
