# Data Validation Log

Historical record of data validation checks performed against Excel/Seller Central.

## EU/FE Sales Validation (Feb 9, 2026)

| Marketplace | Date | Supabase | Excel | Match |
|-------------|------|----------|-------|-------|
| UK | Feb 7 | 191 units | 191 units | 100% |
| DE | Feb 7 | 100 units | 99 units | 99% (attribution timing) |
| AU | Feb 7 | 48 units | 47 units | 98% |

Per-ASIN spot checks: top ASINs exact match across UK, DE, AU.

## EU/FE Inventory Validation (Feb 9, 2026)

| Marketplace | Excel | Supabase | Variance | Notes |
|-------------|-------|----------|----------|-------|
| UK | 41,626 | 41,631 | 0.01% | Spot checks exact |
| DE | 13,302 | 12,982 | 2.4% | Report data, acceptable timing variance |
| AU | 2,647 | 2,464 | 6.9% | Spot checks exact, timing |
| UAE | N/A | N/A | N/A | Not working at time of validation (needed separate refresh token) |

## Bug Fixes Log

- **Session 19 (Feb 10, 2026)**: Fixed reimbursements duplication bug. Was pulling per-marketplace causing duplicates. Now pulls ONCE per region, resolves marketplace per-row from currency-unit (USD->USA, CAD->CA, GBP->UK, EUR->DE, AUD->AU). Cleaned duplicate DB rows.
- **Feb 9, 2026**: Fixed FBA Inventory pagination — `nextToken` was read from wrong JSON path in `fba_inventory_api.py`.
- **Session 19**: Storage fees workflow updated to retry on 5th/10th/15th for late Amazon availability.
