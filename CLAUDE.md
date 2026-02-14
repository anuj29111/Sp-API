# SP-API Data Pull & CM2 Profitability System

## Project Goal

Build a **CM1/CM2 profitability system** pulling Amazon SP-API data into Supabase, combined with POP advertising data, for per-ASIN profitability. Replaces GorillaROI ($600/month).

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

## Phase Status

| Phase | Status |
|-------|--------|
| 1. Sales & Traffic | ✅ Complete |
| 1.5 Near-Real-Time Orders | ✅ Complete |
| 2. Inventory (FBA/AWD/Storage) | ✅ Complete |
| 2.5 SQP/SCP | ✅ Complete |
| 2.6 Search Terms (TST) | ✅ Complete |
| 3. Financial Reports | ✅ Complete |
| 4. Product Master / COGS | ⏸️ Pending |
| 5. CM1/CM2 Engine | ⏸️ Pending |
| 6. Web Dashboard | ⏸️ Pending |

## Key Database Tables

| Table | Purpose |
|-------|---------|
| `sp_daily_asin_data` | Per-ASIN daily sales & traffic + orders. **Always use `sp_daily_asin_data_deduped` view** (deduplicates S&T vs orders, S&T wins) |
| `sp_fba_inventory` | Daily FBA inventory (EU has `fulfillable_quantity_local`/`_remote` for EFN) |
| `sp_awd_inventory` | Daily AWD inventory (NA only) |
| `sp_storage_fees` | Monthly storage fees by FNSKU+FC |
| `sp_sqp_data` / `sp_scp_data` | Search query/catalog performance (weekly/monthly) |
| `sp_search_terms_data` | Top 3 clicked ASINs per search term |
| `sp_settlement_transactions` | Per-order fees — PRIMARY source for CM2 |
| `sp_reimbursements` | Per-SKU reimbursement records |
| `sp_fba_fee_estimates` | Current fee estimates per ASIN (not historical) |

Materialized views: `sp_weekly_asin_data_mat`, `sp_monthly_asin_data_mat`, `sp_rolling_asin_metrics_mat`
Pull tracking: `sp_api_pulls`, `sp_inventory_pulls`, `sp_sqp_pulls`, `sp_financial_pulls`, `sp_search_terms_pulls`

## Critical Rules (Bug Prevention)

- **ALWAYS query `sp_daily_asin_data_deduped` view**, not raw `sp_daily_asin_data` — prevents double-counting orders vs S&T
- **Amazon weeks are Sunday–Saturday**, NOT Monday–Sunday. Misaligned dates cause FATAL report status.
- **Settlement uniqueness**: No row-level unique ID — uses MD5 hash of 11 key fields
- **ijson returns Decimal**: Must convert to `float`/`int` before Supabase upsert
- **EU orders report returns ALL EU marketplaces**: Filter by `sales-channel` column in `aggregate_orders_by_asin()`
- **Reimbursements**: EUR cannot distinguish DE/FR/IT/ES — defaults to DE
- **Schema changes break Chalkola ONE** — check `Chalkola ONE/CLAUDE.md` for downstream dependencies before modifying tables

## Active Tasks

### Backfills In Progress
- **Historical Sales (EU/FE)**: Auto-running 4x/day until 2-year coverage complete
- **SQP/SCP**: Running 4x/day until 2-year backfill complete

### Pending Work
- **Google Sheets**: Deploy updated script to Google Sheets, run Setup DB Helper + Refresh Rolling
- **Google Sheets**: Add rolling session breakdown columns to USA Daily tab (Rolling 14d/30d/60d/90d Browser/Mobile Sessions)
- **Google Sheets**: Use Duplicate Country Tab menu to create other country tabs (trigger functions ready for all 10 countries)
- Monthly TST pull (`--period-type MONTH`)
- Phase 4: Product master + COGS
- Phase 5: CM1/CM2 calculation views
- Phase 6: Web dashboard

## Google Sheets Lessons Learned (CRITICAL — read before touching formulas)

- **Custom functions (SPCOL/SPDATA) DO NOT WORK** — 30-sec execution limit, dump sheets too large. NEVER build custom functions.
- **Native BYROW+SUMIFS with INDIRECT are instant** — no execution limit. Always use native formulas.
- **DB Helper drives everything** — row 3 section name → VLOOKUP DB Helper → INDIRECT builds dump sheet ref → SUMIFS/INDEX-MATCH. 4 formula types: A (monthly/weekly), B (daily), C (inventory), D (rolling/fees).
- **Weekly dates are MONDAY** — not Sunday. Use `WEEKDAY(date,2)` for Monday anchor formulas.
- **Conversion/Buy Box already in %** — 16.67 means 16.67%. Do NOT use % cell format.
- **DB Helper has built-in reference guide** — columns J-L auto-generated with all formulas, dump sheet columns, date helpers, and notes.
- **NEVER insert columns between existing dump sheet columns** — always APPEND after last column. Inserting shifts column letters and breaks all formulas.
- **NEVER reorder DB Helper rows** — always APPEND new sections below existing ones. Existing formulas reference these by section name, but column letters in the mappings are positional.

## Reference Docs (read on-demand, NOT every session)

- `Documentation/reference-data.md` — Marketplace IDs/UUIDs, GitHub secrets, downstream consumers, full known limitations
- `Documentation/workflows.md` — Workflow details, schedules, run examples, diagnostic SQL
- `Documentation/google-sheets.md` — Google Sheets integration, config keys, pending tasks
- `Documentation/database-schema.md` — Full table schemas, column details
- `Documentation/validation-log.md` — Historical data validation records, bug fix log
