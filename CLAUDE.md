# Amazon SP-API Integration - Chalkola One System

## Project Overview

**Goal:** Automate Amazon sales/traffic data collection to replace GorillaROI ($600/month) which times out across 10 marketplaces.

**Architecture:**
```
Amazon SP-API → GitHub Actions (nightly) → Supabase → Google Sheets / Web Apps
```

**Business Context:**
- **Company:** Chalkola - Art supplies (chalk markers, paint pens)
- **Seller Type:** Amazon FBA across 10 countries
- **Scale:** $100k+ monthly ad spend, 200+ ASINs, 10-15 person team
- **Founder:** Non-technical, uses GitHub Desktop for deployments

---

## Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| SP-API Developer Registration | ✅ Approved | January 2026 |
| SP-API App Created | ✅ Done | "Chalkola One System" |
| LWA Credentials | ✅ Saved | Client ID + Secret |
| North America Authorization | ✅ Working | Refresh token generated |
| Europe Authorization | ⏸️ Pending | Need to authorize in EU Seller Central |
| Far East Authorization | ⏸️ Pending | Need to authorize in FE Seller Central |
| Amazon Advertising API | ❌ Not Started | Separate from SP-API (for PPC/Search Terms) |
| Database Tables | ✅ Created | `sp_daily_asin_data`, `sp_daily_totals`, `sp_api_pulls` |
| Python Scripts | ✅ Created | `pull_daily_sales.py` + utilities |
| GitHub Actions | ✅ Created | Daily cron at 2 AM UTC |

---

## Tech Stack

- **Backend:** Python (for data pipeline scripts)
- **Scheduling:** GitHub Actions (Railway has timeout issues)
- **Database:** Supabase (PostgreSQL) - Project: `chalkola-one-system`
- **Deployment:** GitHub Desktop → Railway
- **Language SDKs:** None required - direct REST API calls

---

## Authentication

### SP-API Auth Flow (OAuth 2.0 via LWA)
1. Exchange refresh token for access token
2. Access token expires in 3600 seconds (1 hour)
3. No AWS credentials needed (removed October 2023)

### Token Refresh
```python
POST https://api.amazon.com/auth/o2/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
refresh_token={SP_REFRESH_TOKEN}
client_id={SP_LWA_CLIENT_ID}
client_secret={SP_LWA_CLIENT_SECRET}
```

### Environment Variables Required
```env
# SP-API (Login With Amazon)
SP_LWA_CLIENT_ID=amzn1.application-oa2-client.xxxxx
SP_LWA_CLIENT_SECRET=xxxxx
SP_REFRESH_TOKEN_NA=Atzr|xxxxx
SP_REFRESH_TOKEN_EU=Atzr|xxxxx  # After EU authorization
SP_REFRESH_TOKEN_FE=Atzr|xxxxx  # After FE authorization

# Supabase
SUPABASE_URL=https://yawaopfqkkvdqtsagmng.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIs...
```

---

## Database Configuration

### Supabase Project
- **Project ID:** `yawaopfqkkvdqtsagmng`
- **Project Name:** chalkola-one-system
- **Region:** ap-south-1
- **Auth:** Google OAuth (@chalkola.com domain only)

### Table Naming Convention
| Prefix | System |
|--------|--------|
| `si_` | ScaleInsight data |
| `pop_` | POP system (PPC data) |
| `kt_` | Keyword Tracker data |
| `sp_` | **SP-API data** (NEW - for sales/traffic) |

### Existing Reference Tables
- `marketplaces` (11 rows) - Marketplace codes and IDs
- `products` (208 rows) - Parent ASINs and categories
- `product_variants` (1,064 rows) - Child ASINs mapped to products

### Marketplace UUIDs (from Supabase)
```
USA  → f47ac10b-58cc-4372-a567-0e02b2c3d479
CA   → a1b2c3d4-58cc-4372-a567-0e02b2c3d480
UK   → b2c3d4e5-58cc-4372-a567-0e02b2c3d481
DE   → c3d4e5f6-58cc-4372-a567-0e02b2c3d482
FR   → d4e5f6a7-58cc-4372-a567-0e02b2c3d483
IT   → a7b8c9d0-58cc-4372-a567-0e02b2c3d486
ES   → b8c9d0e1-58cc-4372-a567-0e02b2c3d487
UAE  → e5f6a7b8-58cc-4372-a567-0e02b2c3d484
AU   → f6a7b8c9-58cc-4372-a567-0e02b2c3d485
JP   → d0e1f2a3-58cc-4372-a567-0e02b2c3d489
MX   → c9d0e1f2-58cc-4372-a567-0e02b2c3d488
```

---

## SP-API Reference

### Regional Endpoints
| Region | Endpoint | Marketplaces |
|--------|----------|--------------|
| North America | `sellingpartnerapi-na.amazon.com` | US, CA, MX, BR |
| Europe | `sellingpartnerapi-eu.amazon.com` | UK, DE, FR, IT, ES, UAE |
| Far East | `sellingpartnerapi-fe.amazon.com` | AU, JP |

### Amazon Marketplace IDs
| Country | Marketplace ID | Region |
|---------|---------------|--------|
| USA | `ATVPDKIKX0DER` | NA |
| Canada | `A2EUQ1WTGCTBG2` | NA |
| Mexico | `A1AM78C64UM0Y8` | NA |
| Brazil | `A2Q3Y263D00KWC` | NA |
| UK | `A1F83G8C2ARO7P` | EU |
| Germany | `A1PA6795UKMFR9` | EU |
| France | `A13V1IB3VIYZZH` | EU |
| Italy | `APJ6JRA9NG5V4` | EU |
| Spain | `A1RKKUPIHCS9HS` | EU |
| UAE | `A2VIGQ35RCS4UG` | EU |
| Australia | `A39IBJ37TRP1C6` | FE |
| Japan | `A1VC38T7YXB528` | FE |

### SP-API Roles Enabled
1. Finance and Accounting
2. Selling Partner Insights
3. Inventory and Order Tracking
4. Brand Analytics
5. Amazon Fulfillment
6. Product Listing
7. Amazon Warehousing and Distribution

---

## Data Collection Approach

### Validated Method: Single-Day Reports
The Reports API `GET_SALES_AND_TRAFFIC_REPORT` works, but per-ASIN data is **aggregated** across the date range. Solution: request one report per day (same start/end date).

### Report Request
```python
POST /reports/2021-06-30/reports
{
  "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
  "marketplaceIds": ["ATVPDKIKX0DER"],
  "dataStartTime": "2026-02-01T00:00:00Z",
  "dataEndTime": "2026-02-01T00:00:00Z",  # SAME DATE = single day
  "reportOptions": {
    "dateGranularity": "DAY",
    "asinGranularity": "CHILD"
  }
}
```

### Report Flow
1. **Create Report** → Returns `reportId`
2. **Poll Status** → GET `/reports/{reportId}` until `processingStatus=DONE`
3. **Get Document URL** → GET `/documents/{reportDocumentId}`
4. **Download JSON** → Fetch from pre-signed S3 URL (gzip compressed)

### Data Available in Report
```json
{
  "salesAndTrafficByAsin": [{
    "parentAsin": "B09T6LJPGV",
    "childAsin": "B09T6LJPGV",
    "salesByAsin": {
      "unitsOrdered": 5,
      "unitsOrderedB2B": 0,
      "orderedProductSales": { "amount": 74.75, "currencyCode": "USD" },
      "orderedProductSalesB2B": { "amount": 0 },
      "totalOrderItems": 4,
      "totalOrderItemsB2B": 0
    },
    "trafficByAsin": {
      "sessions": 45,
      "sessionsB2B": 2,
      "pageViews": 68,
      "pageViewsB2B": 3,
      "browserSessions": 30,
      "mobileAppSessions": 15,
      "browserPageViews": 45,
      "mobileAppPageViews": 23,
      "buyBoxPercentage": 99.2,
      "buyBoxPercentageB2B": 100,
      "unitSessionPercentage": 11.11,
      "unitSessionPercentageB2B": 0
    }
  }]
}
```

---

## Database Schema (To Create)

### sp_daily_asin_data
```sql
CREATE TABLE sp_daily_asin_data (
  id BIGSERIAL PRIMARY KEY,
  date DATE NOT NULL,
  marketplace_id UUID NOT NULL REFERENCES marketplaces(id),
  amazon_marketplace_id TEXT NOT NULL,  -- ATVPDKIKX0DER etc
  parent_asin TEXT,
  child_asin TEXT NOT NULL,

  -- Sales metrics
  units_ordered INTEGER DEFAULT 0,
  units_ordered_b2b INTEGER DEFAULT 0,
  ordered_product_sales DECIMAL(12,2) DEFAULT 0,
  ordered_product_sales_b2b DECIMAL(12,2) DEFAULT 0,
  currency_code TEXT DEFAULT 'USD',
  total_order_items INTEGER DEFAULT 0,
  total_order_items_b2b INTEGER DEFAULT 0,

  -- Traffic metrics
  sessions INTEGER DEFAULT 0,
  sessions_b2b INTEGER DEFAULT 0,
  page_views INTEGER DEFAULT 0,
  page_views_b2b INTEGER DEFAULT 0,
  browser_sessions INTEGER DEFAULT 0,
  mobile_app_sessions INTEGER DEFAULT 0,
  browser_page_views INTEGER DEFAULT 0,
  mobile_app_page_views INTEGER DEFAULT 0,
  buy_box_percentage DECIMAL(5,2),
  buy_box_percentage_b2b DECIMAL(5,2),
  unit_session_percentage DECIMAL(5,2),
  unit_session_percentage_b2b DECIMAL(5,2),

  -- Metadata
  created_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(date, marketplace_id, child_asin)
);

-- Indexes for common queries
CREATE INDEX idx_sp_daily_date ON sp_daily_asin_data(date DESC);
CREATE INDEX idx_sp_daily_asin ON sp_daily_asin_data(child_asin);
CREATE INDEX idx_sp_daily_marketplace ON sp_daily_asin_data(marketplace_id);
CREATE INDEX idx_sp_daily_date_marketplace ON sp_daily_asin_data(date, marketplace_id);
```

### sp_data_pulls (Tracking table)
```sql
CREATE TABLE sp_data_pulls (
  id BIGSERIAL PRIMARY KEY,
  pull_date DATE NOT NULL,
  marketplace_id UUID NOT NULL REFERENCES marketplaces(id),
  amazon_marketplace_id TEXT NOT NULL,
  report_id TEXT,
  status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed
  asin_count INTEGER,
  error_message TEXT,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,

  UNIQUE(pull_date, marketplace_id)
);
```

---

## Rate Limits

| Operation | Rate | Notes |
|-----------|------|-------|
| createReport | ~1/min | Queue reports, don't spam |
| getReport | 2/sec | Fast polling OK |
| getReportDocument | ~1/min | Download immediately after getting URL |

### For 10 Marketplaces × 1 Day
- 10 createReport calls = ~10 minutes
- Polling = negligible
- Downloads = ~10 minutes
- **Total: ~20-30 minutes per daily run**

---

## Key Constraints & Gotchas

1. **Date range endpoints are INCLUSIVE** - Feb 1 to Feb 2 = both days
2. **Per-ASIN data aggregates across range** - No daily breakdown in multi-day reports
3. **Single-day reports give daily per-ASIN data** - This is the solution
4. **Reports are gzip compressed** - Decompress before parsing
5. **Data Kiosk requires additional authorization** - Returns 401, use Reports API instead
6. **Amazon data available ~34 hours after day ends** - Pull "2 days ago" data
7. **Maximum 2 years of historical data** - Plan backfill accordingly
8. **Each region needs separate refresh token** - NA, EU, FE authorized separately

---

## Implementation Phases

### Phase 1: Daily Sales/Traffic Automation (Current Priority)
- [ ] Create Supabase tables (`sp_daily_asin_data`, `sp_data_pulls`)
- [ ] Build Python script for single-marketplace pull
- [ ] Add GitHub Actions workflow for daily cron
- [ ] Test with US marketplace only
- [ ] Expand to all NA marketplaces

### Phase 2: Multi-Region Expansion
- [ ] Authorize EU region (UK, DE, FR, IT, ES, UAE)
- [ ] Authorize FE region (AU, JP)
- [ ] Update script for multi-region support

### Phase 3: Historical Backfill
- [ ] Script to backfill 2 years of data
- [ ] Rate limit handling for bulk pulls
- [ ] 730 days × 10 marketplaces = 7,300 reports

### Phase 4: Brand Analytics SQP (Future)
- [ ] Implement SQP report pulling
- [ ] Merge with existing Keyword Tracker data

---

## Two APIs Required (Important!)

**SP-API** provides:
- Sales/Orders data ✅
- FBA Inventory ✅
- Brand Analytics SQP ✅
- AWD Data ✅

**Amazon Advertising API** (SEPARATE) provides:
- Search Term Reports (your 200-300MB files)
- Campaign performance
- PPC metrics
- Sponsored Products/Brands/Display data

The Advertising API requires **separate registration** at https://advertising.amazon.com/API

---

## Development Patterns

### Supabase Best Practices (from Global CLAUDE.md)
- Always wrap `auth.uid()` in SELECT for RLS performance
- Index columns used in RLS policies
- Use Transaction Mode (port 6543) for serverless
- Batch inserts for large data loads

### Python Patterns Used in Chalkola Systems
- `python-calamine` for fast Excel reading
- `xlsxwriter` for Excel generation
- `ThreadPoolExecutor` for parallel API calls
- Pagination: increment by `len(result.data)`, not page size

### Error Handling
- Implement exponential backoff for 429 (rate limit) responses
- Log all API calls to `sp_data_pulls` table
- Alert on failures (Slack webhook or email)

---

## Project Structure (Recommended)

```
/sp-api/
├── scripts/
│   ├── pull_daily_sales.py      # Main daily pull script
│   ├── backfill_historical.py   # Historical data backfill
│   └── utils/
│       ├── auth.py              # Token refresh
│       ├── reports.py           # Report API helpers
│       └── supabase.py          # Database operations
├── .github/
│   └── workflows/
│       └── daily-pull.yml       # GitHub Actions cron
├── requirements.txt              # requests, supabase-py
├── .env.example                  # Template for credentials
├── CLAUDE.md                     # This file
└── README.md                     # Setup instructions
```

---

## Quick Reference

### Test API Access (Postman/curl)
```bash
# 1. Get access token
curl -X POST https://api.amazon.com/auth/o2/token \
  -d "grant_type=refresh_token&refresh_token=${SP_REFRESH_TOKEN}&client_id=${SP_LWA_CLIENT_ID}&client_secret=${SP_LWA_CLIENT_SECRET}"

# 2. Test with marketplace participations
curl https://sellingpartnerapi-na.amazon.com/sellers/v1/marketplaceParticipations \
  -H "x-amz-access-token: ${ACCESS_TOKEN}"
```

### Useful Links
- SP-API Documentation: https://developer-docs.amazon.com/sp-api/docs
- Reports API Reference: https://developer-docs.amazon.com/sp-api/docs/reports-api-v2021-06-30-reference
- Amazon Advertising API: https://advertising.amazon.com/API (separate registration)

---

## Debugging Protocol

**ALWAYS check data layer FIRST before touching code:**
1. Check if data exists in `sp_daily_asin_data`
2. Check `sp_data_pulls` for pull status/errors
3. Check API response structure
4. Then look at code logic

Use Supabase MCP `execute_sql` to run diagnostic queries directly.

---

*Last Updated: February 4, 2026*
