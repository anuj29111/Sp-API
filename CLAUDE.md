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
| **First Successful Pull** | ✅ Feb 4, 2026 - 346 ASINs pulled |
| **Backfill Script** | ✅ Created - `scripts/backfill_historical.py` |
| **Weekly View** | ✅ Created - `sp_weekly_asin_data` (ISO weeks) |
| **Rolling Metrics** | ✅ Created - `sp_rolling_asin_metrics` view |
| Historical Backfill Run | 🔄 Ready to run (2 years, ~36 hours) |
| EU Authorization | ⏸️ Pending |
| FE Authorization | ⏸️ Pending |

### First Pull Results (Feb 4, 2026)
| Marketplace | ASINs | Units | Sales |
|-------------|-------|-------|-------|
| USA | 207 | 785 | $15,510.90 |
| CA | 138 | 302 | $6,924.86 |
| MX | 1 | 0 | $0.00 |

---

## Pending Items

### 1. Run Historical Backfill (Ready)
- **Script**: `scripts/backfill_historical.py`
- **Duration**: ~36 hours for full 2 years
- **Command**: `python scripts/backfill_historical.py` (full 2 years)
- **Resume**: `python scripts/backfill_historical.py --resume`
- **Dry run**: `python scripts/backfill_historical.py --dry-run`

### 2. EU/FE Region Expansion
- Authorize app in EU Seller Central (UK, DE, FR, IT, ES, UAE)
- Authorize app in FE Seller Central (AU, JP)
- Add `SP_REFRESH_TOKEN_EU` and `SP_REFRESH_TOKEN_FE` secrets

### 3. Phase 2: Inventory (Future)
- Add FBA inventory report: `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA`
- Add AWD inventory report: `GET_AFN_INVENTORY_DATA`
- Add inventory age report: `GET_FBA_INVENTORY_AGED_DATA`
- Add storage costs report: `GET_FBA_STORAGE_FEE_CHARGES_DATA`

---

## Project Structure

```
/Sp-API/
├── scripts/
│   ├── pull_daily_sales.py     # Main daily pull script
│   ├── backfill_historical.py  # Historical backfill (2 years)
│   └── utils/
│       ├── __init__.py
│       ├── auth.py             # SP-API token refresh
│       ├── reports.py          # Report API helpers
│       └── db.py               # Supabase operations
├── .github/workflows/
│   └── daily-pull.yml          # Cron: 2 AM UTC daily
├── Business Excel/
│   └── Business Amazon -2025.xlsx  # GorillaROI reference
├── requirements.txt            # requests, supabase, python-dotenv
├── .env.example                # Environment template
├── .gitignore
├── README.md
└── CLAUDE.md                   # This file
```

---

## Database Tables

All tables in Supabase project `yawaopfqkkvdqtsagmng` with `sp_` prefix:

| Table/View | Purpose |
|-------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic metrics |
| `sp_daily_totals` | Account-level daily totals per marketplace |
| `sp_api_pulls` | Track pull status for debugging |
| `sp_monthly_asin_data` | **View** - Monthly aggregates by ASIN |
| `sp_weekly_asin_data` | **View** - Weekly aggregates (ISO weeks Mon-Sun) |
| `sp_rolling_asin_metrics` | **View** - Rolling 7/14/30/60 day metrics |

### Key Fields in sp_daily_asin_data
- `date`, `marketplace_id`, `child_asin` (unique constraint)
- Sales: `units_ordered`, `ordered_product_sales`, `currency_code`
- Traffic: `sessions`, `page_views`, `buy_box_percentage`, `unit_session_percentage`
- B2B variants of all metrics

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

## Running the Script

### Manual Run (Local)
```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill environment variables
cp .env.example .env

# Pull yesterday's data for all NA marketplaces
python scripts/pull_daily_sales.py

# Pull specific date
python scripts/pull_daily_sales.py --date 2026-02-01

# Pull specific marketplace
python scripts/pull_daily_sales.py --marketplace USA

# Force re-pull (overwrite existing)
python scripts/pull_daily_sales.py --force
```

### GitHub Actions (Automatic)
- Runs daily at 2 AM UTC
- Pulls data from 2 days ago (Amazon data delay)
- Can trigger manually from Actions tab

### Manual GitHub Actions Trigger
```bash
gh workflow run daily-pull.yml
gh run list --limit 3
gh run watch <run_id>
```

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

## SP-API Reference

### Regional Endpoints
| Region | Endpoint |
|--------|----------|
| North America | `sellingpartnerapi-na.amazon.com` |
| Europe | `sellingpartnerapi-eu.amazon.com` |
| Far East | `sellingpartnerapi-fe.amazon.com` |

### Report Type
`GET_SALES_AND_TRAFFIC_REPORT` with options:
- `dateGranularity`: DAY
- `asinGranularity`: CHILD

### Key Constraint
Per-ASIN data aggregates across date range. **Solution**: Request single-day reports (same start/end date).

### Rate Limits
| Operation | Limit |
|-----------|-------|
| createReport | ~1/min |
| getReport | 2/sec |
| getReportDocument | ~1/min |

---

## Debugging

### Check Pull Status
```sql
SELECT * FROM sp_api_pulls
ORDER BY started_at DESC
LIMIT 10;
```

### Check Data
```sql
SELECT date, marketplace_id, COUNT(*) as asin_count,
       SUM(units_ordered) as total_units
FROM sp_daily_asin_data
GROUP BY date, marketplace_id
ORDER BY date DESC;
```

### Check Totals
```sql
SELECT * FROM sp_daily_totals
ORDER BY date DESC
LIMIT 20;
```

### Check with Marketplace Names
```sql
SELECT
  date,
  m.code as marketplace,
  COUNT(*) as asin_count,
  SUM(units_ordered) as total_units,
  SUM(ordered_product_sales) as total_sales
FROM sp_daily_asin_data d
JOIN marketplaces m ON d.marketplace_id = m.id
GROUP BY date, m.code
ORDER BY date DESC, m.code;
```

---

## Data Available

**From SP-API (this project):**
- Units ordered (total)
- Revenue (total)
- Sessions & page views
- Buy Box percentage
- Conversion rate (unit_session_percentage)
- B2B variants of all metrics

**From POP System (existing):**
- PPC-attributed sales
- Ad spend

**Now calculable:**
- Organic Sales = Total - PPC
- True TACOS = Ad Spend / Total Sales

---

## Running Historical Backfill

### Commands
```bash
# Full 2-year backfill (recommended: run in tmux/screen)
python scripts/backfill_historical.py

# Dry run - see what would be pulled
python scripts/backfill_historical.py --dry-run

# Custom date range
python scripts/backfill_historical.py --start-date 2024-01-01 --end-date 2024-12-31

# Single marketplace
python scripts/backfill_historical.py --marketplace USA

# Resume from last successful date
python scripts/backfill_historical.py --resume

# Force re-pull existing dates
python scripts/backfill_historical.py --force
```

### Features
- **Rate limiting**: Waits 65 seconds between requests (Amazon limit ~1/min)
- **Batch pauses**: Extra 2-minute pause every 30 requests
- **Resume capability**: Saves state to `.backfill_state.json`
- **Skip existing**: Automatically skips dates with existing data

### Estimated Time
- Full 2 years × 3 marketplaces = ~36 hours
- Run overnight or in background with `nohup` or `tmux`

---

## Session Log

### Feb 4, 2026 (Session 2) - Backfill & Aggregation ✅
**Completed:**
1. Analyzed GorillaROI Business Excel structure (400+ columns)
2. Mapped Excel columns to SP-API data sources
3. Created historical backfill script (`scripts/backfill_historical.py`)
4. Created weekly aggregation view (`sp_weekly_asin_data`) - ISO weeks
5. Created rolling metrics view (`sp_rolling_asin_metrics`)
6. Created helper functions for custom period queries

**Ready to Run:**
- Historical backfill (2 years, ~36 hours)

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

*Last Updated: February 4, 2026*
