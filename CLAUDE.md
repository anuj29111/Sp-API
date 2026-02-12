# SP-API Data Pull & CM2 Profitability System

## Project Goal

Build a **CM1/CM2 profitability system** pulling Amazon SP-API data into Supabase, combined with POP advertising data, for per-ASIN profitability.

**Replaces:** GorillaROI ($600/month) + manual Excel tracking

```
CM1 = Net Revenue - Referral Fees - FBA Fees - COGS
CM2 = CM1 - Ad Spend - Storage Fees + Reimbursements
```

## Architecture

```
Amazon SP-API → GitHub Actions (scheduled) → Supabase → Web App / Google Sheets
                                                 ↑
POP System (Advertising API) ────────────────────┘
```

- **Supabase**: `chalkola-one-system` (yawaopfqkkvdqtsagmng)
- **GitHub Actions**: Python scripts on per-region cron schedules (6 orders workflows + 1 S&T daily)
- **POP System**: Advertising data already in same Supabase

## Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Sales & Traffic | ✅ Complete | 1x/day pull (6AM UTC), 14-day attribution refresh |
| 1.5 Near-Real-Time Orders | ✅ Complete | Per-region schedules (9-16x/day), ~30min delay, S&T overwrites when available |
| 2. Inventory | ✅ Complete | FBA (API for NA, report for EU/FE), AWD (NA only), Storage Fees |
| 2.5 SQP/SCP | ✅ Complete | Weekly/monthly search performance, backfill running |
| 2.6 Search Terms (TST) | ✅ Complete | Top 3 competitor ASINs per keyword, weekly auto-pull |
| 3. Financial Reports | ✅ Complete | Settlements, reimbursements, FBA fee estimates |
| 4. Product Master / COGS | ⏸️ Pending | Need SKU→ASIN→COGS mapping |
| 5. CM1/CM2 Engine | ⏸️ Pending | Combine settlements + COGS + ad spend |
| 6. Web Dashboard | ⏸️ Pending | |

## Marketplace Reference

| Code | Amazon ID | Timezone | Region | Token | UUID |
|------|-----------|----------|--------|-------|------|
| USA | ATVPDKIKX0DER | America/Los_Angeles | NA | `SP_REFRESH_TOKEN_NA` | `f47ac10b-58cc-4372-a567-0e02b2c3d479` |
| CA | A2EUQ1WTGCTBG2 | America/Los_Angeles | NA | `SP_REFRESH_TOKEN_NA` | `a1b2c3d4-58cc-4372-a567-0e02b2c3d480` |
| MX | A1AM78C64UM0Y8 | America/Los_Angeles | NA | `SP_REFRESH_TOKEN_NA` | `c9d0e1f2-58cc-4372-a567-0e02b2c3d488` |
| UK | A1F83G8C2ARO7P | Europe/London | EU | `SP_REFRESH_TOKEN_EU` | `b2c3d4e5-58cc-4372-a567-0e02b2c3d481` |
| DE | A1PA6795UKMFR9 | Europe/Berlin | EU | `SP_REFRESH_TOKEN_EU` | `c3d4e5f6-58cc-4372-a567-0e02b2c3d482` |
| FR | A13V1IB3VIYZZH | Europe/Paris | EU | `SP_REFRESH_TOKEN_EU` | `d4e5f6a7-58cc-4372-a567-0e02b2c3d483` |
| IT | APJ6JRA9NG5V4 | Europe/Rome | EU | `SP_REFRESH_TOKEN_EU` | `a7b8c9d0-58cc-4372-a567-0e02b2c3d486` |
| ES | A1RKKUPIHCS9HS | Europe/Madrid | EU | `SP_REFRESH_TOKEN_EU` | `b8c9d0e1-58cc-4372-a567-0e02b2c3d487` |
| UAE | A2VIGQ35RCS4UG | Asia/Dubai | UAE | `SP_REFRESH_TOKEN_UAE` | `e5f6a7b8-58cc-4372-a567-0e02b2c3d484` |
| AU | A39IBJ37TRP1C6 | Australia/Sydney | FE | `SP_REFRESH_TOKEN_FE` | `f6a7b8c9-58cc-4372-a567-0e02b2c3d485` |

**Not authorized**: Japan (JP) — Chalkola doesn't operate there.

**UAE note**: Separate seller account, own refresh token, uses EU API endpoint.

## Key Database Tables

| Table | Purpose |
|-------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic (+ orders data via `data_source` column). **Use `sp_daily_asin_data_deduped` view for queries** — it deduplicates S&T vs orders (S&T takes priority) |
| `sp_fba_inventory` | Daily FBA inventory (includes `fulfillable_quantity_local`/`_remote` for EU EFN) |
| `sp_awd_inventory` | Daily AWD inventory (NA only) |
| `sp_storage_fees` | Monthly storage fees by FNSKU+FC |
| `sp_sqp_data` / `sp_scp_data` | Search query/catalog performance (weekly/monthly) |
| `sp_search_terms_data` | Top 3 clicked ASINs per search term (competitive intelligence) |
| `sp_settlement_transactions` | Per-order fees — PRIMARY source for CM2 |
| `sp_settlement_summaries` | One row per settlement period |
| `sp_reimbursements` | Per-SKU reimbursement records |
| `sp_fba_fee_estimates` | Current fee estimates per ASIN (not historical) |

Pull tracking tables: `sp_api_pulls`, `sp_inventory_pulls`, `sp_sqp_pulls`, `sp_financial_pulls`, `sp_search_terms_pulls`

Deduplication view: `sp_daily_asin_data_deduped` — returns one row per (child_asin, date, marketplace_id), preferring `sales_traffic` over `orders`. **All downstream queries should use this view, not the raw table.**

Materialized views: `sp_weekly_asin_data_mat`, `sp_monthly_asin_data_mat`, `sp_rolling_asin_metrics_mat` (with wrapper views for backwards compat)

Full schema details: `Documentation/database-schema.md`

## Known Limitations & Gotchas

- **Sales & Traffic delay**: ~12-24hr. System defaults to yesterday in marketplace timezone.
- **Inventory Age**: `GET_FBA_INVENTORY_AGED_DATA` returns FATAL. Known Amazon issue.
- **Settlement 90-day lookback**: `getReports` API max 90-day window. Coverage: Oct 2025 onward.
- **Settlement uniqueness**: No row-level unique ID — uses MD5 hash of 11 key fields.
- **FBA Fee Estimates**: Current fees only. Settlements = source of truth for historical.
- **Reimbursements region behavior**: Amazon returns ALL reimbursements per region. Script pulls ONCE per region, resolves marketplace from currency (USD→USA, CAD→CA, GBP→UK, EUR→DE, AUD→AU). EUR cannot distinguish DE/FR/IT/ES — defaults to DE.
- **EU Inventory**: FBA Inventory API v1 only returns local FC stock. EU uses report with EFN local/remote columns instead.
- **SQP constraints**: No daily granularity (weekly finest), ~18 ASINs/batch, ~48hr delay, brand-registered only.
- **Search Terms Report**: Bulk ~12M rows / ~2.3 GB. Stream-parsed with ijson (~165s). Only ~25% of SQP keywords match (small-volume terms absent). Runs Tue 6 AM UTC after SQP.
- **ijson returns Decimal**: All JSON numbers become Python `Decimal` objects. Must convert to `float`/`int` before Supabase upsert or serialization fails.
- **SP-API week boundaries**: Amazon weeks are Sunday–Saturday, NOT Monday–Sunday. Misaligned dates cause FATAL report status.
- **GitHub Actions timeout**: 5.5hr limit per run. Backfills run 4x/day to work around this.
- **EU orders report returns ALL EU marketplaces** (BUG FIXED Feb 2026): `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` returns orders from the entire EU unified account regardless of which `marketplaceId` is passed. Fixed by filtering rows by `sales-channel` column (e.g., `Amazon.co.uk`, `Amazon.de`) in `aggregate_orders_by_asin()`. NA/FE/UAE are single-account so unaffected.
- **Orders + S&T double-counting** (BUG FIXED Feb 2026): `sp_daily_asin_data` stores both `data_source='orders'` and `data_source='sales_traffic'` rows for the same ASIN+date. Queries must use `sp_daily_asin_data_deduped` view (prefers S&T over orders) to avoid summing both.
- **Orders workflows are per-region**: 6 separate workflow files (`orders-na.yml`, `orders-mx.yml`, `orders-eu-core.yml`, `orders-eu-other.yml`, `orders-au.yml`, `orders-uae.yml`). Use `--marketplaces USA,CA` flag (comma-separated) to target specific marketplaces within a region. All cron times are Dubai GST converted to UTC.
- **S&T daily-pull.yml runs once/day at 6AM UTC (10AM Dubai)**: Don't increase frequency — the 14-day refresh is heavy. Orders workflows handle near-real-time.
- **Google Apps Script 6-min limit**: Each trigger function must complete within 6 min. Uses per-country per-data-type triggers (5 per country) staggered 3 min apart.
- **Google Sheets date headers must be real Date values**: Row 4 dates must use `=Inputs!$T21` (actual date) with cell format `mmmyy` for display. NEVER use `=TEXT(date,"mmmyy")` — produces a string, and `TEXT(string,"yyyy-mm-dd")` fails silently. SUMIFS match against dump sheet's `"2025-01-01"` format requires real Date input.
- **Google Sheets SUMIFS + ARRAYFORMULA don't work together**: Use `BYROW(range, LAMBDA(...))` instead. One formula per column, spills down all ASIN rows.
- **Google Sheets `_safeAlert()` pattern**: Trigger context has no UI — `SpreadsheetApp.getUi()` throws. Always wrap alerts in try/catch with `Logger.log` fallback.
- **IT/ES UUID was historically wrong**: Old docs had IT=`b8c9d0e1-...` (that's Spain) and ES=`d0e1f2a3-...` (that's Japan). Fixed Feb 2026. If any config still uses old values, correct them.

## GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `SP_LWA_CLIENT_ID` / `SP_LWA_CLIENT_SECRET` | SP-API credentials (all regions) |
| `SP_REFRESH_TOKEN_NA` | North America (USA, CA, MX) |
| `SP_REFRESH_TOKEN_EU` | Europe (UK, DE, FR, IT, ES) |
| `SP_REFRESH_TOKEN_FE` | Far East (AU) |
| `SP_REFRESH_TOKEN_UAE` | UAE (separate seller account) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Database |
| `SLACK_WEBHOOK_URL` | Failure alerts |

## Active Tasks

### Backfills In Progress
- **Historical Sales (EU/FE)**: Auto-running 4x/day until 2-year coverage complete
- **SQP/SCP**: Running 4x/day until 2-year backfill complete

### Pending Work
- **Google Sheets — DB Helper + universal formula**: DB Helper sheet + `SPCOL()` / `SPDATA()` custom functions BUILT (in `supabase_sales.gs`). Need to: (1) copy script to Apps Script editor, (2) run "Setup DB Helper" from menu, (3) replace GorillaROI formulas with `=SPCOL($B$2, G$3, INDIRECT($D$2), G$4)` in each section column. See `Documentation/google-sheets.md`. POP ad spend sections not yet mapped (need POP dump sheet first).
- **Google Sheets — expand to other countries**: After USA formulas work, use `duplicateCountryTab()` to add CA, UK, DE, etc. Only change B2 country code.
- **Monthly TST pull**: Add `--period-type MONTH` to Search Terms automation once monthly SQP backfill has enough data to match against
- **Phase 4**: Product master table + COGS entry (via Google Sheets)
- **Phase 5**: CM1/CM2 calculation views (settlements + COGS + POP ad spend)
- **Phase 6**: Web dashboard

## Downstream Consumer: Chalkola ONE

Chalkola ONE (`/Users/anuj/Desktop/Github/Chalkola ONE/`) is the frontend/backend that reads SP-API data.

**How it reads data:**
- Backend (Flask on Railway) queries `sp_daily_asin_data_deduped` (not raw table) for all daily sales/traffic data — prevents double-counting orders vs S&T
- Frontend reads `sp_sqp_data`, `sp_scp_data`, `sp_fba_inventory` directly via Supabase RLS
- Backend reads PPC tables + S&T for Business Overview, Negation, AI queries
- Supabase RPC: `exec_sql` = void (INSERT/UPDATE/DELETE), `execute_readonly_query` = jsonb (SELECT). Parameter: `query_text`

**Critical data rules Chalkola ONE depends on:**
- `products.parent_asin` is a product NAME, not an ASIN — join through `product_variants`
- Child ASIN PPC: must come from `pop_sp_advertised_product_data`, NOT search term tables
- PPC tables: monthly/weekly = `pop_sp_search_term_data`, daily = `pop_sp_search_term_data_daily`
- BR date column = `date` on `sp_daily_totals`; PPC daily tables use `report_date`
- `si_daily_ranks` (2.3M+ rows) — always filter by marketplace + date range
- Pre-computed views (`sp_weekly_asin_data_mat`, `sp_monthly_asin_data_mat`) should be used instead of raw GROUP BY on daily tables

**If you change table schemas, column names, or data formats**, these will break Chalkola ONE. Check the Chalkola ONE CLAUDE.md for downstream dependencies.

### ScaleInsights (`/Users/anuj/Desktop/Github/Scale Insights/`)

Separate data pipeline — pulls keyword ranking data (organic + sponsored) into `si_keywords` + `si_daily_ranks`. Runs daily via GitHub Actions. Covers 6 countries: US, CA, UK, DE, FR, AU (NOT MX, IT, ES, UAE). No dependency on SP-API tables.

---

## Reference Docs (read on-demand, not loaded every session)

- `Documentation/workflows.md` — Full workflow details, schedules, run examples, diagnostic SQL
- `Documentation/google-sheets.md` — Google Sheets integration, config keys, pending tasks
- `Documentation/database-schema.md` — Full table schemas, column details, phase architecture
- `Documentation/validation-log.md` — Historical data validation records, bug fix log
