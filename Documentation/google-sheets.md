# Google Sheets Integration

**Replaces:** GorillaROI ($600/month)

## Architecture: Flat Dump Sheets + SUMIFS Formulas

```
SUPABASE DATABASE
        │
        ├─── SP Data {country}      - Weekly/Monthly sales + traffic
        ├─── SP Daily {country}     - Last 35 days of daily per-ASIN data
        ├─── SP Rolling {country}   - Rolling 7/14/30/60 day metrics
        ├─── SP Inventory {country} - Latest FBA + AWD inventory snapshot
        └─── SP Fees {country}      - Per-unit fee estimates + settlement actuals + storage

COUNTRY TABS (USA, Canada, UK, etc.)
        │
        └─── SUMIFS / INDEX-MATCH formulas referencing dump sheets above
             Direct sheet references (e.g., 'SP Data US'!$D:$D)
             NOT INDIRECT — avoids volatile recalculation overhead
```

## Google Sheet

| Property | Value |
|----------|-------|
| Name | API - Business Amazon 2026 |
| URL | https://docs.google.com/spreadsheets/d/17nR0UFAOXul80mxzQeqBt2aAZ2szdYwVUWnc490NSbk |
| Apps Script Project | https://script.google.com/u/2/home/projects/105bgL_S41PBK6M3CBOHkZ9A9-TXL3hIPJDu5ouk_D8nBT-p-LQKUvZvb/edit |
| Local Script Copy | `/Sp-API/google-sheets/supabase_sales.gs` |

## Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| Supabase connection | ✅ Working | Test connection passes |
| Pagination (>1000 rows) | ✅ Fixed | Range header pagination |
| SP Data sheets | ✅ Working | All 10 marketplaces (weekly/monthly) |
| SP Daily sheets | ✅ Working | All 10 marketplaces (last 35 days from deduped view) |
| SP Rolling sheets | ✅ Working | All 10 marketplaces |
| SP Inventory sheets | ✅ Working | FBA + AWD joined by SKU. EU EFN local/remote. AWD = NA only. |
| SP Fees sheets | ✅ Working | Fee estimates + settlement actuals + storage |
| Formula templates | ✅ Done | SUMIFS/INDEX-MATCH for all dump sheet types |
| Duplicate country tab | ✅ Done | Script replaces sheet refs + updates A2/B2 |
| Menu organization | ✅ Done | Refresh, Duplicate, Automation, Debug |
| Triggers | ✅ Updated | 50 triggers (5 per country: sales, rolling, inventory, fees, daily) |

## Dump Sheet Column Reference

### SP Data {country} (Weekly/Monthly)
| Col | Header | Description |
|-----|--------|-------------|
| A | data_type | "monthly" or "weekly" |
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

### SP Daily {country} (Last 35 Days)
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

### SP Rolling {country} (7/14/30/60 Day)
| Col | Header | Description |
|-----|--------|-------------|
| A | child_asin | ASIN |
| B | parent_asin | Parent ASIN |
| C | currency | Currency code |
| D-H | 7d metrics | units, revenue, avg_units, sessions, conversion |
| I-M | 14d metrics | (same pattern) |
| N-R | 30d metrics | (same pattern) |
| S-W | 60d metrics | (same pattern) |

### SP Inventory {country}
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

### SP Fees {country}
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

## Country Tab Formula Reference

Each country tab has:
- **A2** = Marketplace UUID
- **B2** = Country code (e.g., "US")
- **Row 4** = Date headers
- **Column C** = ASINs (manually maintained, starting row 5)

### Monthly Units
```
=IFERROR(SUMIFS('SP Data US'!$D:$D, 'SP Data US'!$A:$A, "monthly", 'SP Data US'!$B:$B, $C5, 'SP Data US'!$C:$C, TEXT(G$4,"yyyy-mm-dd")), 0)
```
Row 4 must have first-of-month dates. Change `$D:$D` to `$F:$F` for revenue, `$H:$H` for sessions, `$K:$K` for conversion.

### Weekly Units
```
=IFERROR(SUMIFS('SP Data US'!$D:$D, 'SP Data US'!$A:$A, "weekly", 'SP Data US'!$B:$B, $C5, 'SP Data US'!$C:$C, TEXT(G$4,"yyyy-mm-dd")), 0)
```
Row 4 must have Sunday dates (Amazon weeks = Sunday-Saturday).

### Daily Units
```
=IFERROR(SUMIFS('SP Daily US'!$C:$C, 'SP Daily US'!$A:$A, $C5, 'SP Daily US'!$B:$B, TEXT(G$4,"yyyy-mm-dd")), 0)
```

### Daily Average (calculated)
```
=IFERROR(G5 / DAY(EOMONTH(G$4, 0)), 0)
```

### Inventory (SUMIFS for multi-SKU ASINs)
```
FBA Fulfillable:  =IFERROR(SUMIFS('SP Inventory US'!$D:$D, 'SP Inventory US'!$A:$A, $C5), 0)
FBA Total:        =IFERROR(SUMIFS('SP Inventory US'!$L:$L, 'SP Inventory US'!$A:$A, $C5), 0)
AWD On-hand:      =IFERROR(SUMIFS('SP Inventory US'!$M:$M, 'SP Inventory US'!$A:$A, $C5), 0)
Product Name:     =IFERROR(INDEX('SP Inventory US'!$C:$C, MATCH($C5, 'SP Inventory US'!$A:$A, 0)), "")
```

### Rolling Metrics (INDEX/MATCH — one row per ASIN)
```
Units 7d:  =IFERROR(INDEX('SP Rolling US'!$D:$D, MATCH($C5, 'SP Rolling US'!$A:$A, 0)), 0)
Units 30d: =IFERROR(INDEX('SP Rolling US'!$N:$N, MATCH($C5, 'SP Rolling US'!$A:$A, 0)), 0)
```

### Fees
```
Est Total Fee:     =IFERROR(INDEX('SP Fees US'!$E:$E, MATCH($C5, 'SP Fees US'!$A:$A, 0)), 0)
Actual FBA Fee:    =ABS(IFERROR(INDEX('SP Fees US'!$H:$H, MATCH($C5, 'SP Fees US'!$A:$A, 0)), 0))
Storage Fee:       =IFERROR(INDEX('SP Fees US'!$K:$K, MATCH($C5, 'SP Fees US'!$A:$A, 0)), 0)
```

## Duplicating to Other Countries

**Menu: Supabase Data → Duplicate Country Tab...**

1. Enter source tab name (e.g., "USA")
2. Enter target country code (e.g., "CA")
3. Script duplicates the tab, replaces all `'SP Data US'` → `'SP Data CA'` (and all other dump sheet refs), updates A2 (marketplace UUID) and B2 (country code)

**Prerequisites**: Target country must have marketplace UUID in Script Config, and dump sheets should be populated (run "Refresh One Country" first).

## Supported Marketplaces (Config Keys)

| Country | Config Key | Region | Notes |
|---------|-----------|--------|-------|
| USA | US | NA | Full data (sales, rolling, inventory+AWD, fees+settlements+storage) |
| Canada | CA | NA | Full data |
| Mexico | MX | NA | Full data |
| UK | UK | EU | Sales, rolling, inventory (EFN local/remote), fees+settlements. No AWD, no storage. |
| Germany | DE | EU | Same as UK |
| France | FR | EU | Sales, rolling, inventory, fees. No settlements yet, no AWD, no storage. |
| Italy | IT | EU | Same as FR |
| Spain | ES | EU | Same as FR |
| Australia | AU | FE | Sales, rolling, inventory, fees+settlements. No AWD, no storage. |
| UAE | UAE | UAE | Sales, rolling, inventory, fees. No settlements, no AWD, no storage. |

## Trigger Schedule

50 triggers total (5 per country), staggered 3 min apart starting at 6:00 AM:

| Time | Country | Types |
|------|---------|-------|
| 6:00 | US | sales, rolling, inventory, fees, daily |
| 6:03 | CA | same |
| 6:06 | MX | same |
| 6:09 | UK | same |
| 6:12 | DE | same |
| 6:15 | FR | same |
| 6:18 | IT | same |
| 6:21 | ES | same |
| 6:24 | AU | same |
| 6:27 | UAE | same |

## Pending Tasks

1. Copy updated `supabase_sales.gs` to Apps Script editor
2. Add marketplace UUIDs to Script Config sheet for: UK, DE, FR, IT, ES, AU, UAE
3. Build USA tab formulas in the actual Google Sheet (map GorillaROI columns → new formulas)
4. Run "Refresh One Country" for US to populate SP Daily US dump sheet
5. Test all formulas against GorillaROI data for validation
6. Duplicate USA tab to CA as proof of concept
7. Re-setup triggers (menu → Automation → Setup Daily Triggers) to include the new 'daily' type
