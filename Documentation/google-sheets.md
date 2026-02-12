# Google Sheets Integration

**Replaces:** GorillaROI ($600/month)
**Current scope:** USA only (expand to other countries later via Duplicate Country Tab)

## How It Works

```
SUPABASE DATABASE
        │
        │  Script pulls data every day (5 triggers for USA)
        ▼
5 DUMP SHEETS (hidden data tables, auto-refreshed):
        ├── SP Data US       — Monthly & weekly sales/traffic (27+ months)
        ├── SP Daily US      — Last 35 days of daily per-ASIN data
        ├── SP Rolling US    — Rolling 7/14/30/60-day averages
        ├── SP Inventory US  — Latest FBA + AWD stock levels
        └── SP Fees US       — Fee estimates + settlement actuals + storage

DB HELPER sheet (lookup config):
        └── Maps section names → dump sheet + column + lookup type

USA TAB (what you look at):
        └── =SPDATA($B$2, S$3, $C5, S$4) — one tiny formula for everything
            Or BYROW version that auto-fills all ASINs
```

## Google Sheet

| Property | Value |
|----------|-------|
| Name | API - Business Amazon 2026 |
| URL | https://docs.google.com/spreadsheets/d/17nR0UFAOXul80mxzQeqBt2aAZ2szdYwVUWnc490NSbk |
| Apps Script | https://script.google.com/u/2/home/projects/105bgL_S41PBK6M3CBOHkZ9A9-TXL3hIPJDu5ouk_D8nBT-p-LQKUvZvb/edit |
| Local Copy | `/Sp-API/google-sheets/supabase_sales.gs` |

## USA Tab Layout

| Cell | Purpose |
|------|---------|
| A2 | Marketplace UUID (from Script Config) |
| B2 | Country code: `US` |
| D2 | ASIN range text: `C5:C270` |
| Row 3 | Section names (must match DB Helper exactly) |
| Row 4 | Date headers (actual Date values, not text) |
| Column C | ASINs (manually maintained, starting row 5) |

## DB Helper Sheet

Auto-created via Menu → Supabase Data → Setup DB Helper.

Maps each section name to: which dump sheet, which column to read, which column has the ASIN, which column has the date, and what lookup type to use.

### Column Reference (0-indexed)

| Column | Purpose |
|--------|---------|
| A | Section name (must match row 3 in country tab exactly) |
| B | Sheet Prefix (e.g., "SP Data" → becomes "SP Data US") |
| C | Value Col (0-indexed column number to return) |
| D | ASIN Col (0-indexed column number with ASINs) |
| E | Date Col (0-indexed, blank for non-date sections) |
| F | DataType Col (0-indexed, for SP Data sheets with data_type column) |
| G | Data Type filter (e.g., "monthly", "weekly", or blank) |
| H | Lookup Type: `sumifs_date`, `sumifs`, `match`, `match_text` |

### Lookup Types

| Type | When Used | Behavior |
|------|-----------|----------|
| `sumifs_date` | Monthly, weekly, daily | Filters by ASIN + date + optional data_type, sums values |
| `sumifs` | Inventory (multi-SKU) | Filters by ASIN only, sums values |
| `match` | Rolling, fees | First ASIN match, returns number |
| `match_text` | Product name, size tier | First ASIN match, returns text |

### Available Sections

**Monthly (from SP Data sheet):**
Monthly Sales, Monthly Sales B2B, Monthly Revenue, Monthly Revenue B2B, Monthly Sessions, Monthly Page Views, Monthly Buy Box %, Monthly Conversion %

**Weekly (from SP Data sheet):**
Weekly Sales, Weekly Sales B2B, Weekly Revenue, Weekly Revenue B2B, Weekly Sessions, Weekly Page Views, Weekly Buy Box %, Weekly Conversion %

**Daily (from SP Daily sheet):**
Daily Sales, Daily Sales B2B, Daily Revenue, Daily Revenue B2B, Daily Sessions, Daily Page Views, Daily Buy Box %, Daily Conversion %

**Rolling (from SP Rolling sheet):**
Rolling 7d Units, Rolling 7d Revenue, Rolling 7d Avg Units, Rolling 7d Sessions, Rolling 7d Conversion
Rolling 14d Units, Rolling 14d Revenue, Rolling 14d Avg Units, Rolling 14d Sessions, Rolling 14d Conversion
Rolling 30d Units, Rolling 30d Revenue, Rolling 30d Avg Units, Rolling 30d Sessions, Rolling 30d Conversion
Rolling 60d Units, Rolling 60d Revenue, Rolling 60d Avg Units, Rolling 60d Sessions, Rolling 60d Conversion

**Inventory (from SP Inventory sheet):**
FBA Fulfillable, FBA Local, FBA Remote, FBA Reserved, FBA Inbound Work, FBA Inbound Ship, FBA Inbound Recv, FBA Unsellable, FBA Total, AWD On-hand, AWD Inbound, AWD Available, AWD Total, Product Name

**Fees (from SP Fees sheet):**
Size Tier, Price, Est Fee Total, Est Referral Fee, Est FBA Fee, Settle Avg FBA Fee, Settle Avg Referral, Settle FBA Qty Basis, Storage Fee, Storage Avg Qty

## Formulas — Two Custom Functions

### Option A: SPCOL() — Batch Column (RECOMMENDED)

One formula per section column. Returns an entire column of values for all ASINs at once. Much faster than per-cell because it reads the dump sheet once and builds an index.

```
=SPCOL($B$2, G$3, INDIRECT($D$2), G$4)
```
- `$B$2` = country code ("US")
- `G$3` = section name from row 3 ("Monthly Sales")
- `INDIRECT($D$2)` = ASIN range (D2 contains "C5:C270")
- `G$4` = date from row 4 (optional for non-date sections)

Put this in **row 5** of each section column. It spills down to fill all ASIN rows automatically.

For non-date sections (inventory, rolling, fees):
```
=SPCOL($B$2, G$3, INDIRECT($D$2))
```

### Option B: SPDATA() — Single Cell

For one-off cells or debugging. Slower if used in many cells.

```
=SPDATA($B$2, S$3, $C5, S$4)
```

### Examples

Monthly Sales column (all ASINs, one date):
```
=SPCOL($B$2, G$3, INDIRECT($D$2), G$4)
```

FBA Total column (no date):
```
=SPCOL($B$2, "FBA Total", INDIRECT($D$2))
```

Product Name column (returns text):
```
=SPCOL($B$2, "Product Name", INDIRECT($D$2))
```

Single cell for debugging:
```
=SPDATA($B$2, G$3, $C5, G$4)
```

### Performance Notes

- **SPCOL()** reads the dump sheet ONCE and builds a hash map → O(n) for all ASINs
- **SPDATA()** reads once per batch but is called per cell → slower with many cells
- Both cache dump sheet data in memory during a recalculation cycle
- DB Helper is read once and cached
- Custom functions have a 30-second timeout per batch
- SPCOL with ~270 ASINs x ~50 columns = ~50 SPCOL calls → very fast

### IMPORTANT: Custom Function Limitations

- Custom functions are **read-only** — they cannot modify other cells
- They run in a sandboxed context — `SpreadsheetApp.getUi()` is not available
- They are recalculated when inputs change (ASIN, date, or section name)
- They cache data per execution batch (many cells share cache)
- SPCOL returns an array that "spills" down — don't put anything in the cells below it

## The 5 Dump Sheets

### 1. SP Data US (Monthly/Weekly)
| Col | Index | Header | Description |
|-----|-------|--------|-------------|
| A | 0 | data_type | `"monthly"` or `"weekly"` |
| B | 1 | child_asin | ASIN |
| C | 2 | period | YYYY-MM-DD (first-of-month or week_start Sunday) |
| D | 3 | units_ordered | Total units |
| E | 4 | units_ordered_b2b | B2B units |
| F | 5 | ordered_product_sales | Revenue |
| G | 6 | ordered_product_sales_b2b | B2B revenue |
| H | 7 | sessions | Sessions |
| I | 8 | page_views | Page views |
| J | 9 | avg_buy_box_percentage | Buy box % |
| K | 10 | avg_conversion_rate | Conversion rate |

### 2. SP Daily US (Last 35 Days)
| Col | Index | Header | Description |
|-----|-------|--------|-------------|
| A | 0 | child_asin | ASIN |
| B | 1 | date | YYYY-MM-DD |
| C | 2 | units_ordered | Total units |
| D | 3 | units_ordered_b2b | B2B units |
| E | 4 | ordered_product_sales | Revenue |
| F | 5 | ordered_product_sales_b2b | B2B revenue |
| G | 6 | sessions | Sessions |
| H | 7 | page_views | Page views |
| I | 8 | buy_box_percentage | Buy box % |
| J | 9 | unit_session_percentage | Conversion rate |

### 3. SP Rolling US (7/14/30/60 Day)
| Col | Index | Header | Description |
|-----|-------|--------|-------------|
| A | 0 | child_asin | ASIN |
| B | 1 | parent_asin | Parent ASIN |
| C | 2 | currency | Currency code |
| D-H | 3-7 | 7d metrics | units, revenue, avg_units, sessions, conversion |
| I-M | 8-12 | 14d metrics | (same 5 columns) |
| N-R | 13-17 | 30d metrics | (same 5 columns) |
| S-W | 18-22 | 60d metrics | (same 5 columns) |

### 4. SP Inventory US
| Col | Index | Header | Description |
|-----|-------|--------|-------------|
| A | 0 | asin | ASIN |
| B | 1 | sku | SKU |
| C | 2 | product_name | Product name |
| D | 3 | fba_fulfillable | Fulfillable qty |
| E | 4 | fba_local | EU EFN local qty |
| F | 5 | fba_remote | EU EFN remote qty |
| G | 6 | fba_reserved | Reserved qty |
| H | 7 | fba_inbound_working | Working |
| I | 8 | fba_inbound_shipped | Shipped |
| J | 9 | fba_inbound_receiving | Receiving |
| K | 10 | fba_unsellable | Unsellable qty |
| L | 11 | fba_total | Total FBA qty |
| M | 12 | awd_onhand | AWD on-hand (NA only) |
| N | 13 | awd_inbound | AWD inbound |
| O | 14 | awd_available | AWD available |
| P | 15 | awd_total | AWD total |

### 5. SP Fees US
| Col | Index | Header | Description |
|-----|-------|--------|-------------|
| A | 0 | asin | ASIN |
| B | 1 | sku | SKU |
| C | 2 | product_size_tier | Size tier |
| D | 3 | your_price | Current price |
| E | 4 | est_fee_total | Estimated total fee |
| F | 5 | est_referral_per_unit | Estimated referral fee |
| G | 6 | est_fba_per_unit | Estimated FBA fee |
| H | 7 | settle_avg_fba_per_unit | Actual avg FBA fee (from settlements) |
| I | 8 | settle_avg_referral_per_unit | Actual avg referral fee |
| J | 9 | settle_fba_qty_basis | Settlement sample size |
| K | 10 | storage_fee_latest_month | Storage fee (latest month) |
| L | 11 | storage_avg_qty_on_hand | Avg qty on hand for storage |

## 5 USA Triggers

| Trigger Function | Dump Sheet | What It Does |
|-----------------|------------|--------------|
| `trigger_US_sales` | SP Data US | Pulls monthly + weekly aggregates |
| `trigger_US_daily` | SP Daily US | Pulls last 35 days from deduped view |
| `trigger_US_rolling` | SP Rolling US | Pulls rolling 7/14/30/60d averages |
| `trigger_US_inventory` | SP Inventory US | Pulls latest FBA + AWD snapshot |
| `trigger_US_fees` | SP Fees US | Pulls fee estimates + settlements + storage |

All run once daily at ~6:00 AM. Set up via Menu → Supabase Data → Automation → Setup Triggers.

## Adding More Countries Later

1. Add marketplace UUID to Script Config sheet
2. Add trigger functions to the script (copy the 5 US lines, change "US" to new code)
3. Run Menu → Refresh One Country → enter the country code (creates dump sheets)
4. Run Menu → Duplicate Country Tab (copies USA tab, replaces all sheet refs)
5. Run Menu → Setup Triggers (creates triggers for all configured countries)

## Setup Steps (First Time)

1. Copy updated `supabase_sales.gs` to Apps Script editor
2. Run Menu → Supabase Data → **Setup DB Helper** (creates the DB Helper sheet)
3. Run Menu → Refresh One Country → enter "US" (populates all 5 dump sheets)
4. In USA tab:
   - Set B2 = `US`
   - Set D2 = `C5:C270` (or whatever your ASIN range is)
   - Row 3 = section names (must match DB Helper exactly)
   - Row 4 = date values (real Date objects, cell-formatted for display)
5. In row 5 of each section column, enter:
   ```
   =SPCOL($B$2, G$3, INDIRECT($D$2), G$4)
   ```
   (Omit the last parameter for non-date sections like inventory/fees/rolling)
6. Test values against GorillaROI data
7. Run Menu → Setup Triggers (creates 5 daily triggers for US)

## Pending Tasks

1. ~~Copy updated supabase_sales.gs to Apps Script editor~~ → includes SPDATA() + DB Helper
2. Run "Setup DB Helper" from menu (creates config sheet)
3. Run "Refresh One Country" for US (populates dump sheets)
4. Replace GorillaROI formulas with BYROW + SPDATA() formulas
5. Test formulas against GorillaROI data for validation
6. Setup 5 triggers for USA
7. Add sections for POP ad spend data (future — when POP dump sheet added)
8. Expand to other countries via Duplicate Country Tab
