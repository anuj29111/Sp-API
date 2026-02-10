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
- **GitHub Actions**: Python scripts on cron schedules, 4 regions in parallel
- **POP System**: Advertising data already in same Supabase

## Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Sales & Traffic | ✅ Complete | 4x/day pull, 14-day attribution refresh |
| 1.5 Near-Real-Time Orders | ✅ Complete | 6x/day, ~30min delay, S&T overwrites when available |
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
| IT | APJ6JRA9NG5V4 | Europe/Rome | EU | `SP_REFRESH_TOKEN_EU` | `b8c9d0e1-58cc-4372-a567-0e02b2c3d487` |
| ES | A1RKKUPIHCS9HS | Europe/Madrid | EU | `SP_REFRESH_TOKEN_EU` | `d0e1f2a3-58cc-4372-a567-0e02b2c3d489` |
| UAE | A2VIGQ35RCS4UG | Asia/Dubai | UAE | `SP_REFRESH_TOKEN_UAE` | `e5f6a7b8-58cc-4372-a567-0e02b2c3d484` |
| AU | A39IBJ37TRP1C6 | Australia/Sydney | FE | `SP_REFRESH_TOKEN_FE` | `f6a7b8c9-58cc-4372-a567-0e02b2c3d485` |

**Not authorized**: Japan (JP) — Chalkola doesn't operate there.

**UAE note**: Separate seller account, own refresh token, uses EU API endpoint.

## Key Database Tables

| Table | Purpose |
|-------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic (+ orders data via `data_source` column) |
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
- **GitHub Actions timeout**: 5.5hr limit per run. Backfills run 4x/day to work around this.

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
- **SQP/SCP**: Running 4x/day. NA ~19 days from Feb 8. EU/FE just started.

### Pending Work
- **Phase 4**: Product master table + COGS entry (via Google Sheets)
- **Phase 5**: CM1/CM2 calculation views (settlements + COGS + POP ad spend)
- **Phase 6**: Web dashboard
- **Google Sheets**: Verify fee data against GorillaROI, formula refinement

## Reference Docs (read on-demand, not loaded every session)

- `Documentation/workflows.md` — Full workflow details, schedules, run examples, diagnostic SQL
- `Documentation/google-sheets.md` — Google Sheets integration, config keys, pending tasks
- `Documentation/database-schema.md` — Full table schemas, column details, phase architecture
- `Documentation/validation-log.md` — Historical data validation records, bug fix log
