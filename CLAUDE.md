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
| Backfill | 🔄 Oct 4, 2025 → Feb 3, 2026 (~123 days, 17%) - Auto-running 4x/day |
| NA Authorization | ✅ USA, CA, MX working |

**Data Available:**
- `units_ordered`, `ordered_product_sales` - Sales metrics
- `sessions`, `page_views` - Traffic metrics
- `buy_box_percentage`, `unit_session_percentage` - Performance

**Date Logic:**
- Each marketplace uses its own timezone (USA/CA/MX = PST, UK = GMT, etc.)
- Default: Yesterday in marketplace timezone (Sales & Traffic has ~12-24hr delay)
- 14-day attribution refresh catches updates to recent data
- Re-pulls dates with 0 ASINs automatically

### Phase 2: Inventory Data ✅ COMPLETE (with known limitation)

| Data | Source | Status | Records |
|------|--------|--------|---------|
| **FBA Inventory** | FBA Inventory API (v1/summaries) | ✅ Working | 269 records daily |
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

### Phase 3: Financial Reports ⏸️ PENDING

| Report Type | SP-API Report | Status |
|-------------|---------------|--------|
| Storage Fees | `GET_FBA_STORAGE_FEE_CHARGES_DATA` | ✅ Working (Phase 2) |
| Reimbursements | `GET_FBA_REIMBURSEMENTS_DATA` | ⏸️ Not started |
| Settlement Reports | Various | ⏸️ Not started |

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
│   ├── backfill_historical.py     # 2-year backfill (with skip-existing)
│   ├── refresh_recent.py          # Late attribution refresh
│   ├── refresh_views.py           # Refresh materialized views
│   ├── capture_monthly_inventory.py  # Monthly inventory snapshots
│   └── utils/
│       ├── api_client.py          # Centralized HTTP client with retry/rate limiting
│       ├── pull_tracker.py        # Checkpoint & resume capability
│       ├── alerting.py            # Slack webhook notifications
│       ├── auth.py                # SP-API token refresh
│       ├── reports.py             # Sales & Traffic report helpers
│       ├── inventory_reports.py   # Inventory report helpers
│       ├── fba_inventory_api.py   # FBA Inventory API client
│       ├── awd_api.py             # AWD API client
│       └── db.py                  # Supabase operations + checkpoint functions
├── migrations/
│   ├── 001_materialized_views.sql # Convert views to materialized views
│   └── 002_inventory_snapshots.sql # Monthly inventory snapshot table
├── .github/workflows/
│   ├── daily-pull.yml             # 4x/day - Sales & Traffic + view refresh
│   ├── inventory-daily.yml        # 3 AM UTC - FBA + AWD + monthly snapshots
│   ├── storage-fees-monthly.yml   # 8th of month - Storage Fees
│   └── historical-backfill.yml    # 4x/day - Auto backfill until complete
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

---

## GitHub Workflows

### Daily Sales Pull (`daily-pull.yml`)
- **Schedule**: 4x/day at 2, 8, 14, 20 UTC
- **Modes**: `daily`, `refresh`, `both` (default)
- **Date Logic**: Yesterday in each marketplace's timezone
- **Re-pull**: Automatically re-pulls dates that returned 0 ASINs

```bash
gh workflow run daily-pull.yml                         # Default: both modes
gh workflow run daily-pull.yml -f date=2026-02-05      # Specific date
gh workflow run daily-pull.yml -f marketplace=USA      # Single marketplace
```

### FBA & AWD Inventory Pull (`inventory-daily.yml`)
- **Schedule**: 3 AM UTC daily
- **Report Types**: `all`, `inventory`, `awd`, `age`

```bash
gh workflow run inventory-daily.yml                              # All types
gh workflow run inventory-daily.yml -f report_type=inventory     # FBA only
gh workflow run inventory-daily.yml -f report_type=awd           # AWD only
```

### Monthly Storage Fees (`storage-fees-monthly.yml`)
- **Schedule**: 8th of month (data available ~7 days after month end)

```bash
gh workflow run storage-fees-monthly.yml -f month=2025-12 -f marketplace=USA
```

### Historical Backfill (`historical-backfill.yml`)
- **Schedule**: 4x/day at 0, 6, 12, 18 UTC until complete
- **Modes**: `test` (7 days), `month`, `quarter`, `year`, `full` (730 days)
- **Auto-skip**: Exits early if backfill is >99% complete
- **Resume**: Automatically skips existing data and continues from where it left off

```bash
gh workflow run historical-backfill.yml -f mode=full   # Manual trigger
# Usually no need - it runs automatically until backfill is complete
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

### Currently Authorized (NA Region)
| Country | Code | Amazon ID |
|---------|------|-----------|
| USA | USA | ATVPDKIKX0DER |
| Canada | CA | A2EUQ1WTGCTBG2 |
| Mexico | MX | A1AM78C64UM0Y8 |

### Pending Authorization
- **EU Region**: UK, Germany, France, Italy, Spain, UAE
- **FE Region**: Australia, Japan

---

## Quick Commands

```bash
# Check workflow status
gh run list --workflow=daily-pull.yml --limit 5
gh run list --workflow=inventory-daily.yml --limit 5
gh run list --workflow=historical-backfill.yml --limit 5

# View workflow logs
gh run view <run_id> --log | tail -50

# Manual triggers
gh workflow run daily-pull.yml
gh workflow run daily-pull.yml -f date=2026-02-05
gh workflow run inventory-daily.yml -f report_type=all
```

```sql
-- Check sales data coverage
SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM sp_daily_asin_data;

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
```

---

## Automation Summary

All systems are fully automated with no manual intervention required:

| System | Schedule | Status |
|--------|----------|--------|
| **Daily Sales Pull** | 4x/day (2, 8, 14, 20 UTC) | ✅ Running |
| **14-Day Attribution Refresh** | 4x/day (with daily pull) | ✅ Running |
| **Materialized View Refresh** | After each daily pull | ✅ Running |
| **FBA/AWD Inventory** | 3 AM UTC daily | ✅ Running |
| **Monthly Inventory Snapshot** | 1st-2nd of month | ✅ Configured |
| **Storage Fees** | 8th of month | ✅ Configured |
| **Historical Backfill** | 4x/day (0, 6, 12, 18 UTC) | 🔄 Running (~17%) |

**Backfill Progress (as of Feb 6, 2026):**
- USA: Oct 4, 2025 → Feb 4, 2026 (~17%)
- Canada: Oct 4, 2025 → Feb 4, 2026 (~17%)
- Mexico: Oct 5, 2025 → Feb 4, 2026 (~17%)

Estimated completion: ~4-5 more days at 4 runs/day

---

## Known Limitations

- **Sales & Traffic Report Delay**: Amazon's Sales & Traffic report has ~12-24hr delay. Pulling "today" returns 0 ASINs. System defaults to yesterday's date.
- **Inventory Age**: Amazon's `GET_FBA_INVENTORY_AGED_DATA` returns FATAL status. This is a known widespread issue. Fallback report works but lacks age bucket data.
- **GitHub Timeout**: Each backfill run has 5.5-hour limit (GitHub's max is 6 hours). Fixed by running 4x/day.

---

## Pending Tasks

### Next Priority: Phase 3 - Financial Reports
1. **Reimbursement Reports** - `GET_FBA_REIMBURSEMENTS_DATA`
2. **Settlement Reports** - For promotions, shipping income

### Future Phases
1. **Phase 4**: Product master table for COGS/FBA fees (manual entry initially)
2. **Phase 5**: CM1/CM2 calculation views
3. **Phase 6**: Web dashboard integration

---

## GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `SP_LWA_CLIENT_ID` | Amazon SP-API credentials |
| `SP_LWA_CLIENT_SECRET` | Amazon SP-API credentials |
| `SP_REFRESH_TOKEN_NA` | North America refresh token |
| `SUPABASE_URL` | Database URL |
| `SUPABASE_SERVICE_KEY` | Database access |
| `SLACK_WEBHOOK_URL` | Slack alerts for failures |

---

## Google Sheets Integration 🔧 IN PROGRESS

**Replaces:** GorillaROI ($600/month)

### Google Sheet

| Property | Value |
|----------|-------|
| Name | API - Business Amazon 2026 |
| URL | https://docs.google.com/spreadsheets/d/17nR0UFAOXul80mxzQeqBt2aAZ2szdYwVUWnc490NSbk |
| Apps Script Project | https://script.google.com/u/2/home/projects/105bgL_S41PBK6M3CBOHkZ9A9-TXL3hIPJDu5ouk_D8nBT-p-LQKUvZvb/edit |
| Local Script Copy | `/Sp-API/google-sheets/supabase_sales.gs` |
| Config | "Script Config" tab, rows 88-93 |

### Marketplace UUIDs

| Country | UUID |
|---------|------|
| USA | `f47ac10b-58cc-4372-a567-0e02b2c3d479` |
| Canada | `a1b2c3d4-58cc-4372-a567-0e02b2c3d480` |
| Mexico | `c9d0e1f2-58cc-4372-a567-0e02b2c3d488` |
| UK | `b2c3d4e5-58cc-4372-a567-0e02b2c3d481` |
| Germany | `c3d4e5f6-58cc-4372-a567-0e02b2c3d482` |
| UAE | `e5f6a7b8-58cc-4372-a567-0e02b2c3d484` |
| Australia | `f6a7b8c9-58cc-4372-a567-0e02b2c3d485` |

### Current Status

| Step | Status | Notes |
|------|--------|-------|
| Apps Script deployed | ✅ Complete | Functions: `refreshCurrentSheet`, `testConnection`, etc. |
| Supabase connection test | ✅ **Working** | Connection successful |
| USA Daily data refresh | ⚠️ **Issue** | Date/ASIN matching needs fixing |

---

*Last Updated: February 6, 2026 (Session 4)*
