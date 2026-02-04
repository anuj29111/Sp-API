# SP-API Sales & Traffic Data Pull

Automated daily sales and traffic data collection from Amazon SP-API for Chalkola.

## Purpose

Replaces GorillaROI ($600/month) which times out across 10 marketplaces. This pulls **TOTAL** sales data (Organic + PPC + External), not just PPC-attributed sales.

## Architecture

```
Amazon SP-API → GitHub Actions (nightly) → Supabase → Web App / Google Sheets
```

- **GitHub Actions**: Runs Python script daily at 2 AM UTC
- **No Railway needed**: GitHub Actions is the scheduler
- **Same Supabase**: Uses existing `chalkola-one-system` database
- **Same Web App**: Existing Next.js app displays all data

## Quick Start

### 1. Clone and Install

```bash
cd /Users/anuj/Desktop/Github/Sp-API
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

### 3. Run Manually

```bash
# Pull yesterday's data for all NA marketplaces
python scripts/pull_daily_sales.py

# Pull specific date
python scripts/pull_daily_sales.py --date 2026-02-01

# Pull specific marketplace
python scripts/pull_daily_sales.py --marketplace USA
```

## GitHub Actions Setup

Add these secrets to your GitHub repository (Settings > Secrets > Actions):

| Secret | Description |
|--------|-------------|
| `SP_LWA_CLIENT_ID` | Login With Amazon Client ID |
| `SP_LWA_CLIENT_SECRET` | Login With Amazon Client Secret |
| `SP_REFRESH_TOKEN_NA` | North America refresh token |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |

The workflow runs automatically at 2 AM UTC daily, or can be triggered manually.

## Database Tables

| Table | Purpose |
|-------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic |
| `sp_daily_totals` | Account-level daily totals |
| `sp_api_pulls` | Track pull status & debugging |

## Data Available

From SP-API (this project):
- ✅ Units ordered (total)
- ✅ Revenue (total)
- ✅ Sessions & page views
- ✅ Buy Box percentage
- ✅ Conversion rate

From POP System (existing):
- ✅ PPC-attributed sales
- ✅ Ad spend

**Now you can calculate:**
- Organic Sales = Total Sales - PPC Sales
- True TACOS = Ad Spend / Total Sales

## Marketplaces

### Currently Authorized (NA)
- 🇺🇸 USA
- 🇨🇦 Canada
- 🇲🇽 Mexico

### Pending Authorization (EU)
- 🇬🇧 UK, 🇩🇪 Germany, 🇫🇷 France, 🇮🇹 Italy, 🇪🇸 Spain, 🇦🇪 UAE

### Pending Authorization (FE)
- 🇦🇺 Australia, 🇯🇵 Japan

## Troubleshooting

Check pull status:
```sql
SELECT * FROM sp_api_pulls
ORDER BY started_at DESC
LIMIT 10;
```

Check data imports:
```sql
SELECT * FROM data_imports
WHERE import_type = 'sp_api_sales_traffic'
ORDER BY created_at DESC
LIMIT 10;
```

## License

Private - Chalkola internal use only.
