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
| EU Authorization | ⏸️ Pending |
| FE Authorization | ⏸️ Pending |
| Historical Backfill | ⏸️ Pending (next session) |

### First Pull Results (Feb 4, 2026)
| Marketplace | ASINs | Units | Sales |
|-------------|-------|-------|-------|
| USA | 207 | 785 | $15,510.90 |
| CA | 138 | 302 | $6,924.86 |
| MX | 1 | 0 | $0.00 |

---

## Pending Items (Next Session)

### 1. Historical Backfill Strategy
- **Maximum history**: 2 years (per Amazon SP-API limits)
- **Approach**: Build backfill script that respects rate limits
- **Rate limits**: ~1 report/min per marketplace
- **Estimated time**: 730 days × 3 marketplaces = ~36 hours of processing
- **Strategy**: Run in batches, maybe 30-60 days at a time

### 2. Aggregation Views
- **Monthly totals**: Create view from `sp_daily_asin_data` (already have `sp_monthly_asin_data` view)
- **Weekly aggregates**: Add new view for weekly rollups
- **Custom date ranges**: Once backfill complete, any date range possible

### 3. EU/FE Region Expansion
- Authorize app in EU Seller Central (UK, DE, FR, IT, ES, UAE)
- Authorize app in FE Seller Central (AU, JP)
- Add `SP_REFRESH_TOKEN_EU` and `SP_REFRESH_TOKEN_FE` secrets

---

## Project Structure

```
/Sp-API/
├── scripts/
│   ├── pull_daily_sales.py     # Main daily pull script
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

## Session Log

### Feb 4, 2026 - Initial Implementation ✅
**Completed:**
1. Created GitHub repo: https://github.com/anuj29111/Sp-API
2. Built Python scripts (auth, reports, db, main pull)
3. Set up GitHub Actions workflow (2 AM UTC daily cron)
4. Created Supabase tables with RLS enabled
5. Configured all 5 GitHub Secrets
6. Ran first successful pull - 346 ASINs from 3 NA marketplaces
7. Verified data in Supabase

**Next Session Agenda:**
- Historical backfill script (up to 2 years back)
- Weekly aggregates view
- Verify monthly aggregates view
- Plan for EU/FE authorization

---

*Last Updated: February 4, 2026*
