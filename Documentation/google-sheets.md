# Google Sheets Integration

**Replaces:** GorillaROI ($600/month)

## Architecture: Flat Dump Sheets + SUMIFS Formulas

```
SUPABASE DATABASE
        │
        ├─── SP Data {country}      - Weekly/Monthly sales + traffic
        ├─── SP Rolling {country}   - Rolling 7/14/30/60 day metrics
        ├─── SP Inventory {country} - Latest FBA + AWD inventory snapshot
        └─── SP Fees {country}      - Per-unit fee estimates + settlement actuals + storage
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
| SP Data sheets | ✅ Working | All 10 marketplaces |
| SP Rolling sheets | ✅ Working | All 10 marketplaces |
| SP Inventory sheets | ✅ Working | FBA + AWD joined by SKU. EU EFN local/remote. AWD = NA only. |
| SP Fees sheets | ✅ Working | Fee estimates + settlement actuals + storage |
| SUMIFS formulas | ✅ Working | Jan/Feb 2026 pulling correctly |
| Menu organization | ✅ Done | Grouped by region (NA / EU / FE / UAE) |

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

## Pending Google Sheets Tasks

1. Copy updated `supabase_sales.gs` to Apps Script editor
2. Test all refresh functions (all 10 marketplaces)
3. Add marketplace UUIDs to Script Config sheet for: UK, DE, FR, IT, ES, AU, UAE
4. Verify fee data accuracy against GorillaROI
5. Test date conversion formula for older months
6. Create unified formula that checks SP Data first, falls back to Archive
7. Write SUMIFS formulas for dump sheets (Rolling, Inventory, Fees)
