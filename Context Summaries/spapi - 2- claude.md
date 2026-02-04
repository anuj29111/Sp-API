# Chalkola Hub - SP-API Sales Data Automation
## Claude Context Document

---

## Project Overview

**Purpose:** Automate Amazon sales data collection to replace GorillaROI ($600/month) which constantly times out across 10 marketplaces.

**Architecture:**
```
Amazon SP-API → GitHub Actions (nightly) → Supabase (Chalkola Hub) → Google Sheets / Web Apps
```

**Tech Stack:** Next.js 14, Flask/Python, Supabase, Railway, GitHub Actions

---

## Business Context

**Company:** Chalkola - Art supplies (chalk markers, paint pens)  
**Amazon Presence:** FBA seller across 10 countries (US, CA, UK, DE, FR, IT, ES, UAE, AU, JP)  
**Scale:** $100k+ monthly ad spend, 10-15 person team  
**Founder:** Non-technical, uses GitHub Desktop

**Current Problem:** GorillaROI Google Sheets plugin hits "ErrorExceeded maximum execution time" when pulling live data for 10 marketplaces × 200+ ASINs × multiple metrics.

**Solution:** Background service pulls data nightly → stores in Supabase → Google Sheets queries fast local data.

---

## SP-API Credentials

### North America (Working)
- **Endpoint:** `sellingpartnerapi-na.amazon.com`
- **Auth:** LWA OAuth2 (Client ID + Client Secret + Refresh Token)
- **Token URL:** `https://api.amazon.com/auth/o2/token`
- **Access Token Expiry:** 3600 seconds (refresh hourly)

### Marketplace IDs
| Country | Marketplace ID |
|---------|---------------|
| US | ATVPDKIKX0DER |
| CA | A2EUQ1WTGCTBG2 |
| MX | A1AM78C64UM0Y8 |
| BR | A2Q3Y263D00KWC |
| UK | A1F83G8C2ARO7P |
| DE | A1PA6795UKMFR9 |
| FR | A13V1IB3VIYBER |
| IT | APJ6JRA9NG5V4 |
| ES | A1RKKUPIHCS9HS |
| AU | A39IBJ37TRP1C6 |
| JP | A1VC38T7YXB528 |
| UAE | A2VIGQ35RCS4UG |

### Regional Endpoints
- North America: `sellingpartnerapi-na.amazon.com`
- Europe: `sellingpartnerapi-eu.amazon.com`
- Far East: `sellingpartnerapi-fe.amazon.com`

---

## Supabase Configuration

**Project ID:** yawaopfqkkvdqtsagmng  
**Region:** ap-south-1  
**Auth:** Google OAuth (@chalkola.com domain only)

### Existing Tables (Relevant)

| Table | Rows | Purpose |
|-------|------|---------|
| `products` | 208 | Product master (ASIN, name, category) |
| `product_variants` | 1,064 | Product name mapping |
| `marketplaces` | 11 | Marketplace reference data |

### Naming Convention
- `si_` = ScaleInsight data
- `pop_` = POP system data
- `kt_` = Keyword Tracker data
- `sp_` = SP-API data (NEW - for sales/traffic)

---

## Data Requirements

### Daily Per-ASIN Sales Data Needed
- Units ordered (B2C and B2B)
- Revenue / ordered product sales
- Sessions / page views
- Conversion rate (unit session percentage)
- Buy box percentage

### Granularity
- **Storage:** Daily per-ASIN per-marketplace
- **Aggregation:** Weekly/monthly computed from daily data
- **History:** Up to 2 years (maximum Amazon provides)

---

## API Approaches

### Option 1: Reports API (GET_SALES_AND_TRAFFIC_REPORT)
- **Limitation:** Per-ASIN data is aggregated across date range, not daily
- **Workaround:** Request one report per day
- **Calls needed:** 365 × 10 marketplaces = 3,650/year

### Option 2: Data Kiosk API (Recommended)
- **Query:** `salesAndTrafficTrends` in `analytics_salesAndTraffic_2024_04_24`
- **Advantage:** Daily per-ASIN data in single GraphQL query
- **Format:** JSONL response

---

## Reports API Flow (Tested)

```python
# Step 1: Create report request
POST /reports/2021-06-30/reports
{
  "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
  "marketplaceIds": ["ATVPDKIKX0DER"],
  "dataStartTime": "2026-01-27T00:00:00Z",
  "dataEndTime": "2026-01-28T00:00:00Z",  # Single day for daily ASIN data
  "reportOptions": {
    "dateGranularity": "DAY",
    "asinGranularity": "CHILD"
  }
}
# Returns: reportId

# Step 2: Poll for completion
GET /reports/2021-06-30/reports/{reportId}
# Poll until processingStatus = "DONE"
# Returns: reportDocumentId

# Step 3: Get download URL
GET /reports/2021-06-30/documents/{reportDocumentId}
# Returns: Pre-signed S3 URL (expires in 5 minutes)

# Step 4: Download JSON
GET {pre-signed URL}
# Returns: JSON with salesAndTrafficByDate + salesAndTrafficByAsin
```

---

## Proposed Table Schema

```sql
-- Daily sales and traffic data per ASIN
CREATE TABLE sp_daily_sales_traffic (
  id BIGSERIAL PRIMARY KEY,
  date DATE NOT NULL,
  marketplace_id TEXT NOT NULL,
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
  buy_box_percentage DECIMAL(5,2),
  buy_box_percentage_b2b DECIMAL(5,2),
  unit_session_percentage DECIMAL(5,2),
  unit_session_percentage_b2b DECIMAL(5,2),
  
  -- Metadata
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE(date, marketplace_id, child_asin)
);

-- Index for common queries
CREATE INDEX idx_sp_daily_date ON sp_daily_sales_traffic(date);
CREATE INDEX idx_sp_daily_asin ON sp_daily_sales_traffic(child_asin);
CREATE INDEX idx_sp_daily_marketplace ON sp_daily_sales_traffic(marketplace_id);
```

---

## Scheduling

**Platform:** GitHub Actions (Railway has timeout issues)

**Schedule:**
- Daily pull at 2 AM UTC
- Amazon data available ~34 hours after day ends
- So pulling "2 days ago" data ensures availability

**Workflow:**
1. Authenticate with LWA
2. For each marketplace:
   - Request report for target date
   - Poll until complete
   - Download and parse JSON
   - Upsert to Supabase
3. Log completion/errors

---

## Key Constraints

1. **One marketplace per report request** - Must loop through 10 marketplaces
2. **Report processing time:** 30 seconds to several minutes
3. **Download URL expires in 5 minutes** - Download immediately after getting URL
4. **Rate limits:** ~1 request/second for reports API
5. **Data delay:** Amazon data ready ~34 hours after day ends
6. **History limit:** Maximum 2 years of historical data

---

## Environment Variables Needed

```env
# SP-API Credentials
SP_API_LWA_CLIENT_ID=
SP_API_LWA_CLIENT_SECRET=
SP_API_REFRESH_TOKEN_NA=
SP_API_REFRESH_TOKEN_EU=
SP_API_REFRESH_TOKEN_FE=

# Supabase
SUPABASE_URL=https://yawaopfqkkvdqtsagmng.supabase.co
SUPABASE_SERVICE_KEY=
```

---

## Files in This Project

| File | Purpose |
|------|---------|
| `sp-api-sales-data-session-summary.md` | Detailed session notes |
| `claude.md` | This context file |
| (Future) `scripts/pull_sales_traffic.py` | Data pull script |
| (Future) `.github/workflows/nightly-pull.yml` | GitHub Actions workflow |

---

## Next Steps (For New Chat)

### IMMEDIATE: Test Data Kiosk API in Postman

**Why:** GET_SALES_AND_TRAFFIC_REPORT has a limitation—per-ASIN data is aggregated across the date range, NOT daily. Data Kiosk's `salesAndTrafficTrends` query supposedly provides daily per-ASIN data in one call.

**Postman Steps to Test:**

1. **Get Access Token** (same as before)
```
POST https://api.amazon.com/auth/o2/token
Body (x-www-form-urlencoded):
  grant_type: refresh_token
  refresh_token: {{your_refresh_token}}
  client_id: {{lwa_client_id}}
  client_secret: {{lwa_client_secret}}
```

2. **Create Data Kiosk Query**
```
POST https://sellingpartnerapi-na.amazon.com/datakiosk/2023-11-15/queries
Headers:
  x-amz-access-token: {{access_token}}
  Content-Type: application/json

Body:
{
  "query": "query MyQuery { analytics_salesAndTraffic_2024_04_24 { salesAndTrafficTrends( startDate: \"2026-01-27\" endDate: \"2026-02-02\" aggregateBy: DAY marketplaceIds: [\"ATVPDKIKX0DER\"] ) { startDate endDate marketplaceId trends { date traffic { sessions pageViews buyBoxPercentage unitSessionPercentage } sales { unitsOrdered orderedProductSales { amount currencyCode } } asin } } } }"
}
```

3. **Poll Query Status**
```
GET https://sellingpartnerapi-na.amazon.com/datakiosk/2023-11-15/queries/{queryId}
```

4. **Get Document (when status = DONE)**
```
GET https://sellingpartnerapi-na.amazon.com/datakiosk/2023-11-15/documents/{documentId}
```

5. **Download JSONL from pre-signed URL**

---

### If Data Kiosk Works → Build Pipeline

1. **Create Supabase table** `sp_daily_sales_traffic` (schema in this doc)
2. **Build Python script** for daily pull (GitHub Actions)
3. **Backfill 2 years** of historical data
4. **Connect Google Sheets** to Supabase

### If Data Kiosk Doesn't Work → Use Reports API Workaround

- Request **one report per day** (not date ranges)
- 365 API calls × 10 marketplaces = 3,650 calls/year
- Same table schema, just more API calls

---

## Session Transcript Location

Full conversation transcript: `/mnt/transcripts/2026-02-03-13-58-16-sp-api-sales-report-structure-analysis.txt`

Previous transcript: `/mnt/transcripts/2026-02-03-12-35-32-sp-api-sales-data-architecture.txt`

---

## Key Findings from This Session

1. **GET_SALES_AND_TRAFFIC_REPORT works** but has limitation
2. **Per-ASIN data is aggregated** across date range (not daily breakdown)
3. **dateGranularity: DAY** only affects account-level totals
4. **Data Kiosk API** has `salesAndTrafficTrends` that may solve this
5. **GitHub Actions** recommended for scheduling (Railway has timeout issues)
6. **2 years of history** available from Amazon

---

## Files Created This Session

| File | Location |
|------|----------|
| Session Summary | `/mnt/user-data/outputs/sp-api-sales-data-session-summary.md` |
| Claude Context | `/mnt/user-data/outputs/claude.md` |
| Downloaded Report | `268ce8e4-8186-4c63-a331-e3c85eb2c3ce_amzn1_tortuga_4.na` (in uploads) |

---

## Questions to Answer in Next Session

1. Does Data Kiosk `salesAndTrafficTrends` return daily per-ASIN data?
2. What's the exact JSONL structure from Data Kiosk?
3. Rate limits for Data Kiosk vs Reports API?
4. Can Data Kiosk query multiple marketplaces in one call?
