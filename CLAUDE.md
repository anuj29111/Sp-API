# SP-API Sales & Traffic Data Pull

## What This Does

Pulls **TOTAL** daily sales/traffic data from Amazon SP-API (Organic + PPC + External), replacing GorillaROI ($600/month).

**Key Insight:** POP system only has PPC-attributed sales. SP-API gives TOTAL sales. Now we can calculate:
- **Organic Sales** = Total Sales - PPC Sales
- **True TACOS** = Ad Spend / Total Sales

---

## Architecture

```
Amazon SP-API → GitHub Actions (2 AM UTC daily) → Supabase → Web App
```

- **GitHub Actions**: Runs Python script on schedule
- **Supabase**: Same `chalkola-one-system` database (yawaopfqkkvdqtsagmng)
- **No Railway**: GitHub Actions handles scheduling

---

## Current Status

| Component | Status |
|-----------|--------|
| GitHub Repo | ✅ https://github.com/anuj29111/Sp-API |
| Python Scripts | ✅ Complete |
| GitHub Actions Workflow | ✅ Complete |
| Database Tables | ✅ Created (with RLS) |
| GitHub Secrets | ✅ Configured |
| NA Authorization | ✅ Working (USA, CA, MX) |
| Daily Pull (Automated) | ✅ Running at 2 AM UTC |
| **Daily Pull + Late Attribution Refresh** | ✅ `daily-pull.yml` (pulls new day + refreshes last 14 days) |
| **Backfill Script** | ✅ `scripts/backfill_historical.py` |
| **Backfill Workflow** | ✅ `historical-backfill.yml` (test/month/quarter/year/full modes) |
| **Refresh Script** | ✅ `scripts/refresh_recent.py` (late attribution refresh) |
| **Weekly View** | ✅ `sp_weekly_asin_data` (ISO weeks Mon-Sun) |
| **Rolling Metrics View** | ✅ `sp_rolling_asin_metrics` (7/14/30/60 days) |
| **Test Backfill (7 days)** | 🔄 Running (workflow ID: 21674815193) |
| Historical Backfill (Full) | ⏳ After test passes, run `mode=full` |
| EU Authorization | ⏸️ Pending |
| FE Authorization | ⏸️ Pending |

### Data in Database (as of Feb 4, 2026)
| Date | Marketplace | ASINs | Units | Sales |
|------|-------------|-------|-------|-------|
| 2026-02-02 | USA | 207 | 785 | $15,510.90 |
| 2026-02-02 | CA | 138 | 302 | $6,924.86 CAD |
| 2026-02-02 | MX | 1 | 0 | $0.00 MXN |
| 2026-01-30 | USA | 204 | 759 | $14,689.57 |

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

# Full 2-year backfill (~36+ hours)
gh workflow run historical-backfill.yml -f mode=full

# Custom date range
gh workflow run historical-backfill.yml -f start_date=2024-01-01 -f end_date=2024-12-31

# Single marketplace
gh workflow run historical-backfill.yml -f mode=full -f marketplace=USA
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
│   └── Business Amazon -2025.xlsx  # GorillaROI reference
├── requirements.txt            # requests, supabase, python-dotenv
├── .env.example                # Environment template
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

### Backfill Timing Estimates
| Mode | Days | Requests | Time |
|------|------|----------|------|
| test | 7 | 21 | ~25 min |
| month | 30 | 90 | ~2 hours |
| quarter | 90 | 270 | ~5 hours |
| year | 365 | 1,095 | ~20 hours |
| full | 730 | 2,190 | ~40 hours |

---

## Debugging

### Check Pull Status
```sql
SELECT * FROM sp_api_pulls
ORDER BY started_at DESC
LIMIT 10;
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
- **Migration**: `fix_numeric_precision_for_percentage_columns`

### 2. Duplicate Pull Records (Fixed)
- **Issue**: Re-pulling same date/marketplace caused unique constraint violation
- **Fix**: Changed `create_pull_record()` to use upsert instead of insert
- **File**: `scripts/utils/db.py`

### 3. Views Depend on Column Types (Fixed)
- **Issue**: Can't alter column types when views depend on them
- **Fix**: Drop views → alter columns → recreate views (in single migration)

---

## Session Log

### Feb 4, 2026 (Session 3) - Backfill Workflow & Fixes ✅
**Completed:**
1. Fixed numeric column precision for percentage fields (can exceed 100%)
2. Fixed pull record to use upsert for re-pulls
3. Created `scripts/refresh_recent.py` for late attribution refresh
4. Updated `daily-pull.yml` to support modes (daily/refresh/both)
5. Created `historical-backfill.yml` workflow with multiple modes
6. Modified backfill to process dates in reverse order (latest first)
7. Started test backfill (7 days) - running as workflow 21674815193

**Next Steps:**
1. Verify test backfill completes successfully
2. Run full 2-year backfill: `gh workflow run historical-backfill.yml -f mode=full`

### Feb 4, 2026 (Session 2) - Backfill & Aggregation ✅
**Completed:**
1. Analyzed GorillaROI Business Excel structure (400+ columns)
2. Mapped Excel columns to SP-API data sources (~70% replicable)
3. Created historical backfill script (`scripts/backfill_historical.py`)
4. Created weekly aggregation view (`sp_weekly_asin_data`) - ISO weeks
5. Created rolling metrics view (`sp_rolling_asin_metrics`)
6. Created helper functions for custom period queries

### Feb 4, 2026 (Session 1) - Initial Implementation ✅
**Completed:**
1. Created GitHub repo: https://github.com/anuj29111/Sp-API
2. Built Python scripts (auth, reports, db, main pull)
3. Set up GitHub Actions workflow (2 AM UTC daily cron)
4. Created Supabase tables with RLS enabled
5. Configured all 5 GitHub Secrets
6. Ran first successful pull - 346 ASINs from 3 NA marketplaces
7. Verified data in Supabase

---

## Next Session Checklist

1. **Check test backfill result**: `gh run view 21674815193`
2. **If passed, run full backfill**: `gh workflow run historical-backfill.yml -f mode=full`
3. **Verify data in Supabase**: Check date range coverage
4. **Phase 2 (Future)**: Inventory reports (FBA, AWD, Inventory Age, Storage Costs)

---

*Last Updated: February 4, 2026*
