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
| Daily Pull | ✅ Running at 2 AM UTC |
| Late Attribution Refresh | ✅ Refreshes last 14 days |
| Database Tables | ✅ `sp_daily_asin_data`, `sp_api_pulls` |
| Views | ✅ Weekly, Monthly, Rolling metrics |
| NA Authorization | ✅ USA, CA, MX working |

**Data Available:**
- `units_ordered`, `ordered_product_sales` - Sales metrics
- `sessions`, `page_views` - Traffic metrics
- `buy_box_percentage`, `unit_session_percentage` - Performance

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

| Field | Description | Source |
|-------|-------------|--------|
| `fba_fees_per_unit` | Amazon fulfillment fee | Manual / FBA Fee Preview API |
| `cogs_per_unit` | Cost of goods sold | Manual entry |
| `shipping_to_fba` | Inbound shipping cost | Manual entry |

### Phase 5: CM1/CM2 Calculation Engine ⏸️ PENDING

### Phase 6: Web Dashboard ⏸️ PENDING

---

## Project Structure

```
/Sp-API/
├── scripts/
│   ├── pull_daily_sales.py        # Daily sales & traffic pull
│   ├── pull_inventory.py          # FBA inventory (uses API)
│   ├── pull_awd_inventory.py      # AWD inventory (uses AWD API)
│   ├── pull_inventory_age.py      # Inventory age buckets (--fallback option)
│   ├── pull_storage_fees.py       # Monthly storage fees
│   ├── backfill_historical.py     # 2-year backfill
│   ├── refresh_recent.py          # Late attribution refresh
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
├── .github/workflows/
│   ├── daily-pull.yml             # 2 AM UTC - Sales & Traffic
│   ├── inventory-daily.yml        # 3 AM UTC - FBA + AWD Inventory
│   ├── storage-fees-monthly.yml   # 8th of month - Storage Fees
│   └── historical-backfill.yml    # Manual - Historical data
├── requirements.txt
└── CLAUDE.md
```

---

## API Resilience System ✅ COMPLETE

All SP-API scripts use a centralized API client with automatic retry, rate limiting, and Slack alerts.

**Key Features:**
- Automatic retry with exponential backoff (1s → 2s → 4s → 8s → 16s)
- Rate limit header parsing (`x-amzn-RateLimit-*`)
- Transient error detection (429, 500, 502, 503, 504)
- Checkpoint-based resume capability for partial failures
- Slack alerts on failures → **#sp-api-alerts** channel

### Core Modules

| Module | Purpose |
|--------|---------|
| `api_client.py` | SPAPIClient - HTTP calls with retry/rate limiting |
| `pull_tracker.py` | PullTracker - per-marketplace status, resume support |
| `alerting.py` | AlertManager - Slack webhook notifications |

### Slack Alerting ✅ CONFIGURED

- **Channel**: #sp-api-alerts (ID: C0ACPAQ80KZ)
- **App**: SP-API Alerts (App ID: A0AD4S0KFU2)
- **GitHub Secret**: `SLACK_WEBHOOK_URL` ✅ Added

Alerts are sent automatically when pulls fail after retries.

### Usage

```bash
# Resume incomplete pull (default)
python pull_daily_sales.py --resume

# Start fresh
python pull_daily_sales.py --no-resume
```

---

## Database Tables

### Sales & Traffic Tables
| Table/View | Purpose |
|------------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic |
| `sp_api_pulls` | Pull tracking |
| `sp_weekly_asin_data` | **View** - Weekly aggregates |
| `sp_monthly_asin_data` | **View** - Monthly aggregates |
| `sp_rolling_asin_metrics` | **View** - Rolling 7/14/30/60 day |

### Inventory Tables
| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sp_fba_inventory` | Daily FBA inventory snapshot | `fulfillable_quantity`, `reserved_quantity`, `inbound_*`, detailed breakdowns |
| `sp_awd_inventory` | Daily AWD inventory | `total_onhand_quantity`, `total_inbound_quantity`, `available_quantity` |
| `sp_storage_fees` | Monthly storage fees by FNSKU+FC | `estimated_monthly_storage_fee`, `average_quantity_on_hand` |
| `sp_inventory_age` | Age bucket breakdown | ⚠️ Not populated (Amazon API FATAL) |
| `sp_inventory_pulls` | Inventory pull tracking | Status, row counts, errors |

---

## GitHub Workflows

### Daily Sales Pull (`daily-pull.yml`)
- **Schedule**: 2 AM UTC daily
- **Modes**: `daily`, `refresh`, `both` (default)

```bash
gh workflow run daily-pull.yml                         # Default: both modes
gh workflow run daily-pull.yml -f marketplace=USA      # Single marketplace
```

### FBA & AWD Inventory Pull (`inventory-daily.yml`)
- **Schedule**: 3 AM UTC daily
- **Report Types**: `all`, `inventory`, `awd`, `age`

```bash
gh workflow run inventory-daily.yml                              # All types
gh workflow run inventory-daily.yml -f report_type=inventory     # FBA only
gh workflow run inventory-daily.yml -f report_type=awd           # AWD only
gh workflow run inventory-daily.yml -f age_fallback=true         # Use fallback for age
```

### Monthly Storage Fees (`storage-fees-monthly.yml`)
- **Schedule**: 8th of month (data available ~7 days after month end)

```bash
gh workflow run storage-fees-monthly.yml -f month=2025-12 -f marketplace=USA
```

### Historical Backfill (`historical-backfill.yml`)
- **Modes**: `test` (7 days), `month`, `quarter`, `year`, `full` (730 days)

```bash
gh workflow run historical-backfill.yml -f mode=full
```

---

## Marketplaces

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
gh run list --workflow=storage-fees-monthly.yml --limit 5

# View workflow logs
gh run view <run_id> --log | tail -50

# Manual triggers
gh workflow run daily-pull.yml
gh workflow run inventory-daily.yml -f report_type=all
gh workflow run storage-fees-monthly.yml -f month=2025-12
```

```sql
-- Check sales data coverage
SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM sp_daily_asin_data;

-- Check FBA inventory
SELECT date, COUNT(*) as records, SUM(fulfillable_quantity) as fulfillable
FROM sp_fba_inventory GROUP BY date ORDER BY date DESC LIMIT 5;

-- Check AWD inventory
SELECT date, COUNT(*) as records,
       SUM(total_onhand_quantity) as onhand,
       SUM(total_inbound_quantity) as inbound
FROM sp_awd_inventory GROUP BY date ORDER BY date DESC;

-- Check storage fees
SELECT month, COUNT(*) as records,
       ROUND(SUM(estimated_monthly_storage_fee)::numeric, 2) as total_fees,
       currency_code
FROM sp_storage_fees GROUP BY month, currency_code ORDER BY month DESC;

-- Check pull status
SELECT * FROM sp_inventory_pulls ORDER BY started_at DESC LIMIT 10;
```

---

## Pending Tasks

### Next Priority: Phase 3 - Financial Reports
1. **Reimbursement Reports** - `GET_FBA_REIMBURSEMENTS_DATA`
2. **Settlement Reports** - For promotions, shipping income

### Future Phases
1. **Phase 4**: Product master table for COGS/FBA fees (manual entry initially)
2. **Phase 5**: CM1/CM2 calculation views
3. **Phase 6**: Web dashboard integration

### Known Limitations
- **Inventory Age**: Amazon's `GET_FBA_INVENTORY_AGED_DATA` returns FATAL status. This is a known widespread issue. Fallback report works but lacks age bucket data.

---

## Google Sheets Integration (Replacing GorillaROI) 🔄 IN PROGRESS

Replacing GorillaROI ($600/month) with direct Supabase data pull into Google Sheet "API - Business Amazon 2026".

### Sheet Details

| Property | Value |
|----------|-------|
| Sheet ID | `17nR0UFAOXul80mxzQeqBt2aAZ2szdYwVUWnc490NSbk` |
| Apps Script | `/Sp-API/google-sheets/supabase_sales.gs` |
| Config Location | "Script Config" tab, rows 88-92 |

### How It Works

- **A2**: Marketplace UUID (e.g., `f47ac10b-58cc-4372-a567-0e02b2c3d479`)
- **B2**: Country code (US, CA, etc.)
- **Menu**: Supabase Data > Refresh Current Sheet

### Marketplace UUIDs

| Country | UUID |
|---------|------|
| USA | `f47ac10b-58cc-4372-a567-0e02b2c3d479` |
| Canada | `a1b2c3d4-58cc-4372-a567-0e02b2c3d480` |
| UK | `b2c3d4e5-58cc-4372-a567-0e02b2c3d481` |
| Germany | `c3d4e5f6-58cc-4372-a567-0e02b2c3d482` |
| UAE | `e5f6a7b8-58cc-4372-a567-0e02b2c3d484` |
| Australia | `f6a7b8c9-58cc-4372-a567-0e02b2c3d485` |

### Status

| Step | Status |
|------|--------|
| Apps Script written | ✅ Done |
| Script Config setup | ⚠️ Needs column fix |
| Test connection | ⏸️ Pending |

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

*Last Updated: February 5, 2026*
