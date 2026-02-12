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

USA TAB (what you look at):
        └── SUMIFS / INDEX-MATCH formulas read from dump sheets above
            Uses cell references only: $C5=ASIN, G$4=date
            ZERO hardcoded values in any formula
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
| Row 4 | Date headers (actual Date values, not text) |
| Column C | ASINs (manually maintained, starting row 5) |

## The 5 Dump Sheets

### 1. SP Data US (Monthly/Weekly)
| Col | Header | Description |
|-----|--------|-------------|
| A | data_type | `"monthly"` or `"weekly"` |
| B | child_asin | ASIN |
| C | period | YYYY-MM-DD (first-of-month or week_start Sunday) |
| D | units_ordered | Total units |
| E | units_ordered_b2b | B2B units |
| F | ordered_product_sales | Revenue |
| G | ordered_product_sales_b2b | B2B revenue |
| H | sessions | Sessions |
| I | page_views | Page views |
| J | avg_buy_box_percentage | Buy box % |
| K | avg_conversion_rate | Conversion rate |

### 2. SP Daily US (Last 35 Days)
| Col | Header | Description |
|-----|--------|-------------|
| A | child_asin | ASIN |
| B | date | YYYY-MM-DD |
| C | units_ordered | Total units |
| D | units_ordered_b2b | B2B units |
| E | ordered_product_sales | Revenue |
| F | ordered_product_sales_b2b | B2B revenue |
| G | sessions | Sessions |
| H | page_views | Page views |
| I | buy_box_percentage | Buy box % |
| J | unit_session_percentage | Conversion rate |

### 3. SP Rolling US (7/14/30/60 Day)
| Col | Header | Description |
|-----|--------|-------------|
| A | child_asin | ASIN |
| B | parent_asin | Parent ASIN |
| C | currency | Currency code |
| D-H | 7d metrics | units, revenue, avg_units, sessions, conversion |
| I-M | 14d metrics | (same 5 columns) |
| N-R | 30d metrics | (same 5 columns) |
| S-W | 60d metrics | (same 5 columns) |

### 4. SP Inventory US
| Col | Header | Description |
|-----|--------|-------------|
| A | asin | ASIN |
| B | sku | SKU |
| C | product_name | Product name |
| D | fba_fulfillable | Fulfillable qty |
| E | fba_local | EU EFN local qty |
| F | fba_remote | EU EFN remote qty |
| G | fba_reserved | Reserved qty |
| H-J | fba_inbound_* | Working / shipped / receiving |
| K | fba_unsellable | Unsellable qty |
| L | fba_total | Total FBA qty |
| M | awd_onhand | AWD on-hand (NA only) |
| N | awd_inbound | AWD inbound |
| O | awd_available | AWD available |
| P | awd_total | AWD total |

### 5. SP Fees US
| Col | Header | Description |
|-----|--------|-------------|
| A | asin | ASIN |
| B | sku | SKU |
| C | product_size_tier | Size tier |
| D | your_price | Current price |
| E | est_fee_total | Estimated total fee |
| F | est_referral_per_unit | Estimated referral fee |
| G | est_fba_per_unit | Estimated FBA fee |
| H | settle_avg_fba_per_unit | Actual avg FBA fee (from settlements) |
| I | settle_avg_referral_per_unit | Actual avg referral fee |
| J | settle_fba_qty_basis | Settlement sample size |
| K | storage_fee_latest_month | Storage fee (latest month) |
| L | storage_avg_qty_on_hand | Avg qty on hand for storage |

## Formula Reference (Zero Hardcoding)

Every formula reads from cell references only:
- `$C5` = ASIN from your list
- `G$4` = date from your header row
- Sheet name = the only thing that changes per country (handled by Duplicate script)

### Monthly Units
```
=IFERROR(SUMIFS('SP Data US'!$D:$D, 'SP Data US'!$A:$A, "monthly", 'SP Data US'!$B:$B, $C5, 'SP Data US'!$C:$C, TEXT(G$4,"yyyy-mm-dd")), 0)
```
Change `$D:$D` to: `$F:$F` revenue, `$H:$H` sessions, `$K:$K` conversion

### Weekly Units
```
=IFERROR(SUMIFS('SP Data US'!$D:$D, 'SP Data US'!$A:$A, "weekly", 'SP Data US'!$B:$B, $C5, 'SP Data US'!$C:$C, TEXT(G$4,"yyyy-mm-dd")), 0)
```
Row 4 must have **Sunday** dates (Amazon weeks = Sunday-Saturday)

### Daily Units
```
=IFERROR(SUMIFS('SP Daily US'!$C:$C, 'SP Daily US'!$A:$A, $C5, 'SP Daily US'!$B:$B, TEXT(G$4,"yyyy-mm-dd")), 0)
```

### Rolling (one row per ASIN → INDEX/MATCH)
```
Units 7d:  =IFERROR(INDEX('SP Rolling US'!$D:$D, MATCH($C5, 'SP Rolling US'!$A:$A, 0)), 0)
Units 30d: =IFERROR(INDEX('SP Rolling US'!$N:$N, MATCH($C5, 'SP Rolling US'!$A:$A, 0)), 0)
```

### Inventory (multi-SKU → SUMIFS)
```
FBA Fulfillable: =IFERROR(SUMIFS('SP Inventory US'!$D:$D, 'SP Inventory US'!$A:$A, $C5), 0)
FBA Total:       =IFERROR(SUMIFS('SP Inventory US'!$L:$L, 'SP Inventory US'!$A:$A, $C5), 0)
AWD On-hand:     =IFERROR(SUMIFS('SP Inventory US'!$M:$M, 'SP Inventory US'!$A:$A, $C5), 0)
Product Name:    =IFERROR(INDEX('SP Inventory US'!$C:$C, MATCH($C5, 'SP Inventory US'!$A:$A, 0)), "")
```

### Fees (one row per ASIN → INDEX/MATCH)
```
Est Total Fee:  =IFERROR(INDEX('SP Fees US'!$E:$E, MATCH($C5, 'SP Fees US'!$A:$A, 0)), 0)
Actual FBA Fee: =ABS(IFERROR(INDEX('SP Fees US'!$H:$H, MATCH($C5, 'SP Fees US'!$A:$A, 0)), 0))
Storage Fee:    =IFERROR(INDEX('SP Fees US'!$K:$K, MATCH($C5, 'SP Fees US'!$A:$A, 0)), 0)
```

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

## Pending Tasks

1. Copy updated `supabase_sales.gs` to Apps Script editor
2. Run "Refresh One Country" for US (creates SP Daily US dump sheet)
3. Open USA tab → replace GorillaROI formulas with Supabase formulas
4. Test formulas against GorillaROI data for validation
5. Setup 5 triggers for USA
