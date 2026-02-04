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
| Database Tables | ✅ Created |
| NA Authorization | ✅ Working (USA, CA, MX) |
| EU Authorization | ⏸️ Pending |
| FE Authorization | ⏸️ Pending |
| GitHub Secrets | ⚠️ Need to add |

---

## GitHub Secrets Required

Add at: https://github.com/anuj29111/Sp-API/settings/secrets/actions

| Secret | Description |
|--------|-------------|
| `SP_LWA_CLIENT_ID` | Login With Amazon Client ID |
| `SP_LWA_CLIENT_SECRET` | Login With Amazon Client Secret |
| `SP_REFRESH_TOKEN_NA` | North America refresh token |
| `SUPABASE_URL` | `https://yawaopfqkkvdqtsagmng.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |

---

## Project Structure

```
/Sp-API/
├── scripts/
│   ├── pull_daily_sales.py     # Main script
│   └── utils/
│       ├── __init__.py
│       ├── auth.py             # SP-API token refresh
│       ├── reports.py          # Report API helpers
│       └── db.py               # Supabase operations
├── .github/workflows/
│   └── daily-pull.yml          # Cron: 2 AM UTC daily
├── requirements.txt            # requests, supabase, python-dotenv
├── .env.example                # Environment template
├── .gitignore
├── README.md
└── CLAUDE.md                   # This file
```

---

## Database Tables

All tables in Supabase project `yawaopfqkkvdqtsagmng` with `sp_` prefix:

| Table | Purpose |
|-------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic metrics |
| `sp_daily_totals` | Account-level daily totals per marketplace |
| `sp_api_pulls` | Track pull status for debugging |
| `sp_monthly_asin_data` | View - monthly aggregates |

### Key Fields in sp_daily_asin_data
- `date`, `marketplace_id`, `child_asin` (unique constraint)
- Sales: `units_ordered`, `ordered_product_sales`, `currency_code`
- Traffic: `sessions`, `page_views`, `buy_box_percentage`, `unit_session_percentage`
- B2B variants of all metrics

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

---

## Marketplaces

### Currently Authorized (NA Region)
| Country | Code | Amazon ID | Supabase UUID |
|---------|------|-----------|---------------|
| USA | USA | ATVPDKIKX0DER | f47ac10b-58cc-4372-a567-0e02b2c3d479 |
| Canada | CA | A2EUQ1WTGCTBG2 | a1b2c3d4-58cc-4372-a567-0e02b2c3d480 |
| Mexico | MX | A1AM78C64UM0Y8 | c9d0e1f2-58cc-4372-a567-0e02b2c3d488 |

### Pending Authorization (EU Region)
UK, Germany, France, Italy, Spain, UAE

### Pending Authorization (FE Region)
Australia, Japan

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

---

## Data Available

From SP-API (this project):
- Units ordered (total)
- Revenue (total)
- Sessions & page views
- Buy Box percentage
- Conversion rate (unit_session_percentage)
- B2B variants of all metrics

From POP System (existing):
- PPC-attributed sales
- Ad spend

**Now calculable:**
- Organic Sales = Total - PPC
- True TACOS = Ad Spend / Total Sales

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

---

## Rate Limits

| Operation | Limit |
|-----------|-------|
| createReport | ~1/min |
| getReport | 2/sec |
| getReportDocument | ~1/min |

For 3 NA marketplaces: ~10-15 minutes per daily run.

---

## Future Work

1. **EU/FE Authorization** - Authorize app in EU and FE Seller Central
2. **Historical Backfill** - Pull up to 2 years of data (separate script)
3. **Brand Analytics SQP** - Search Query Performance reports

---

*Last Updated: February 4, 2026*
