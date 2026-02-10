# GitHub Workflows Reference

All workflows support `--region` arg and run **4 regions (NA, EU, FE, UAE) in parallel** using GitHub Actions matrix strategy (`fail-fast: false`).

---

## Daily Sales Pull (`daily-pull.yml`)
- **Schedule**: 4x/day at 2, 8, 14, 20 UTC
- **Modes**: `daily`, `refresh`, `both` (default)
- **Date Logic**: Yesterday in each marketplace's timezone
- **Re-pull**: Automatically re-pulls dates that returned 0 ASINs

```bash
gh workflow run daily-pull.yml                                    # Default: all regions, both modes
gh workflow run daily-pull.yml -f date=2026-02-05                 # Specific date
gh workflow run daily-pull.yml -f marketplace=USA                 # Single marketplace
gh workflow run daily-pull.yml -f region=EU                       # EU region only
gh workflow run daily-pull.yml -f marketplace=UK -f region=EU     # Single EU marketplace
```

## Near-Real-Time Orders (`orders-daily.yml`)
- **Schedule**: 6x/day at 0, 4, 8, 12, 16, 20 UTC
- **Data Source**: `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` (~30min delay)
- **S&T Protection**: Won't overwrite rows that already have Sales & Traffic data

```bash
gh workflow run orders-daily.yml                                    # All regions, today + yesterday
gh workflow run orders-daily.yml -f marketplace=USA                 # Single marketplace
gh workflow run orders-daily.yml -f region=EU                       # EU region only
```

## FBA & AWD Inventory Pull (`inventory-daily.yml`)
- **Schedule**: 3 AM UTC daily
- **Strategy**: NA uses FBA Inventory API v1, EU/FE uses `GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA` report

```bash
gh workflow run inventory-daily.yml                                       # All types, all regions
gh workflow run inventory-daily.yml -f report_type=inventory              # FBA only
gh workflow run inventory-daily.yml -f report_type=awd                    # AWD only (NA only)
gh workflow run inventory-daily.yml -f region=EU                          # EU region only
```

## SQP/SCP Weekly Pull (`sqp-weekly.yml`)
- **Weekly Schedule**: Every Tuesday 4 AM UTC
- **Monthly Schedule**: 4th of month 4 AM UTC
- **Timeout**: 180 minutes

```bash
gh workflow run sqp-weekly.yml                                              # Latest week, all regions
gh workflow run sqp-weekly.yml -f report_type=SQP -f region=EU              # SQP only, EU
gh workflow run sqp-weekly.yml -f period_type=MONTH                         # Monthly
```

## SQP/SCP Backfill (`sqp-backfill.yml`)
- **Schedule**: 4x/day at 1, 7, 13, 19 UTC
- **Default**: SQP only, 5 periods per run, latest-first
- **Strategy**: SQP first → then SCP. Priority: USA, CA, UK, DE, UAE, AU, FR. IT/ES deferred.
- **Timeout**: 240 minutes

```bash
gh workflow run sqp-backfill.yml                                            # Default: SQP, 5 periods
gh workflow run sqp-backfill.yml -f report_type=SCP                         # SCP backfill (after SQP done)
gh workflow run sqp-backfill.yml -f report_type=both -f max_periods=2       # Both types, slower
```

## Settlement Reports Weekly (`settlements-weekly.yml`)
- **Schedule**: Every Tuesday 7 AM UTC
- **Pattern**: LIST available reports → DOWNLOAD each → Parse TSV → Upsert

```bash
gh workflow run settlements-weekly.yml                                      # Last 30 days, all regions
gh workflow run settlements-weekly.yml -f region=EU                          # EU region only
```

## Historical Backfill (`historical-backfill.yml`)
- **Schedule**: 4x/day at 0, 6, 12, 18 UTC until complete
- **Auto-skip**: Exits early if backfill is >99% complete

```bash
gh workflow run historical-backfill.yml -f mode=full              # All regions
gh workflow run historical-backfill.yml -f region=EU              # EU only
```

## Other Workflows

| Workflow | Schedule | Notes |
|----------|----------|-------|
| `storage-fees-monthly.yml` | 5th, 10th, 15th of month | Storage fees (retry for late availability) |
| `settlement-backfill.yml` | Manual | Backfill settlements to Jan 2024 |
| `reimbursements-weekly.yml` | Mondays 6 AM UTC | Per-region pull with currency resolution |
| `financial-daily.yml` | Daily 5 AM UTC | FBA fee estimates |

---

## Quick Commands

```bash
# Check workflow status
gh run list --workflow=daily-pull.yml --limit 5
gh run list --workflow=inventory-daily.yml --limit 5
gh run list --workflow=historical-backfill.yml --limit 5
gh run list --workflow=orders-daily.yml --limit 5
gh run list --workflow=sqp-weekly.yml --limit 5
gh run list --workflow=sqp-backfill.yml --limit 5
gh run list --workflow=settlements-weekly.yml --limit 5
gh run list --workflow=financial-daily.yml --limit 5

# View workflow logs
gh run view <run_id> --log | tail -50

# Manual triggers (all support -f region=NA/EU/FE/UAE)
gh workflow run daily-pull.yml -f region=EU
gh workflow run orders-daily.yml -f marketplace=UK -f region=EU
gh workflow run inventory-daily.yml -f report_type=inventory -f region=EU
gh workflow run sqp-weekly.yml -f region=EU
gh workflow run settlements-weekly.yml -f region=EU
gh workflow run financial-daily.yml -f region=EU
```

## Diagnostic SQL

```sql
-- Check sales data coverage by marketplace
SELECT m.name as marketplace, MIN(d.date) as earliest, MAX(d.date) as latest, COUNT(DISTINCT d.date) as days
FROM sp_daily_asin_data d JOIN marketplaces m ON d.marketplace_id = m.id
GROUP BY m.name ORDER BY m.name;

-- Check FBA inventory by marketplace (today)
SELECT m.name, COUNT(*) as records, SUM(fulfillable_quantity) as fulfillable,
       SUM(fulfillable_quantity_local) as local_qty, SUM(fulfillable_quantity_remote) as remote_qty
FROM sp_fba_inventory i JOIN marketplaces m ON i.marketplace_id = m.id
WHERE i.date = CURRENT_DATE GROUP BY m.name ORDER BY m.name;

-- Check settlement data by marketplace
SELECT m.name, COUNT(DISTINCT settlement_id) as settlements,
       COUNT(*) as transactions, MIN(posted_date_time) as earliest
FROM sp_settlement_transactions t JOIN marketplaces m ON t.marketplace_id = m.id
GROUP BY m.name;

-- Check SQP/SCP pull status (recent)
SELECT report_type, period_type, period_start, marketplace_id, status,
       total_rows, completed_batches, total_batches
FROM sp_sqp_pulls ORDER BY period_start DESC LIMIT 20;
```
