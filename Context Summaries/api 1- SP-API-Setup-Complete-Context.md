# SP-API Setup Complete - Context for Next Session

## Document Purpose
Use this document to continue SP-API automation work with Chalkola. Contains full context from setup session on February 3, 2026.

---

## Executive Summary

| Item | Status |
|------|--------|
| SP-API Developer Registration | ✅ Approved (January 2026) |
| SP-API App Created | ✅ "Chalkola One System" |
| LWA Credentials | ✅ Obtained and saved |
| North America Authorization | ✅ Refresh token generated |
| API Access Tested | ✅ Sales data successfully pulled |
| Europe/Far East Regions | ⏸️ Not yet set up (intentionally deferred) |
| Amazon Advertising API | ❌ Not yet registered (separate from SP-API) |
| Automation Pipeline | 📋 Ready to discuss and build |

---

## About Chalkola (Business Context)

### Company Overview
- **Product:** Art supplies (chalk markers, paint pens)
- **Business Model:** Amazon FBA
- **Marketplaces:** 10 countries (US, CA, UK, DE, FR, IT, ES, UAE, AU, JP)
- **Monthly Ad Spend:** $100k+
- **Team Size:** 10-15 people
- **Technical Background:** Non-technical founder, uses GitHub Desktop exclusively

### Existing Internal Systems
| System | Purpose | Tech Stack |
|--------|---------|------------|
| Keyword Tracker | Track keyword rankings, DataDive/SQP/PPC data | Next.js, Supabase, Railway |
| FBA Shipment System | Manage FBA shipments, supplier files, AWD | Next.js, Supabase, Railway |
| POP System | Search Term Impression Share analytics | Next.js, Flask, Supabase |

### Data Scale
- US Search Term Reports: 200-300MB per download
- Other marketplaces: ~100MB per download
- Historical data goal: Millions of rows (12+ months retention)
- Database: Supabase Pro

---

## SP-API App Details

### App Information
- **App Name:** Chalkola One System
- **App ID:** `amzn1.sp.solution.ef31cf5b-35c8-4fd5-baf4-5ee85ffedbde`
- **App Type:** Production
- **Registration Type:** Private Developer (internal tools only)
- **Status:** Draft (normal for private apps)

### Roles Enabled (7 Roles)
| Role | Purpose |
|------|---------|
| Finance and Accounting | Settlement reports, financial statements |
| Selling Partner Insights | Account performance |
| Inventory and Order Tracking | Inventory levels, order data |
| Brand Analytics | Search Query Performance (SQP) data |
| Amazon Fulfillment | FBA shipment tracking |
| Product Listing | Product catalog data, A+ content |
| Amazon Warehousing and Distribution | AWD inventory and shipment tracking |

### Role NOT Requested
- **Pricing** - Can be added later if repricing automation needed

---

## Credentials Status

### What Anuj Has Saved
| Credential | Status | Where It Came From |
|------------|--------|-------------------|
| LWA Client ID | ✅ Saved | Seller Central → Develop Apps → View LWA credentials |
| LWA Client Secret | ✅ Saved | Seller Central → Develop Apps → View LWA credentials |
| NA Refresh Token | ✅ Saved | Self-authorization via "Authorize app" button |

### Important Notes
- **No AWS credentials needed** - SP-API dropped AWS IAM requirement in October 2023
- Refresh tokens don't expire
- Access tokens expire in 1 hour (3600 seconds)
- Access tokens obtained by exchanging refresh token via POST to `https://api.amazon.com/auth/o2/token`

---

## Regions & Authorization Status

### Authorized
| Region | Marketplaces | Refresh Token |
|--------|--------------|---------------|
| **North America** | US, CA, MX, BR | ✅ Generated |

### Not Yet Authorized (Deferred)
| Region | Marketplaces | How to Authorize |
|--------|--------------|------------------|
| **Europe** | UK, DE, FR, IT, ES, UAE | Log into EU Seller Central → Developer Central → Authorize app |
| **Far East** | AU, JP | Log into FE Seller Central → Developer Central → Authorize app |

**Decision:** Set up other regions after automation is working for NA. Same process, just need to generate refresh tokens in each region.

---

## Marketplace IDs (For API Calls)

### North America (Verified Working)
| Marketplace | ID | Status |
|-------------|-----|--------|
| Amazon.com (US) | `ATVPDKIKX0DER` | ✅ Active |
| Amazon.ca (Canada) | `A2EUQ1WTGCTBG2` | ✅ Active |
| Amazon.com.mx (Mexico) | `A1AM78C64UM0Y8` | ✅ Active |
| Amazon.com.br (Brazil) | `A2Q3Y263D00KWC` | ✅ Active |

### Europe (For Later)
| Marketplace | ID |
|-------------|-----|
| Amazon.co.uk | `A1F83G8C2ARO7P` |
| Amazon.de | `A1PA6795UKMFR9` |
| Amazon.fr | `A13V1IB3VIYBER` |
| Amazon.it | `APJ6JRA9NG5V4` |
| Amazon.es | `A1RKKUPIHCS9HS` |
| Amazon.ae | `A2VIGQ35RCS4UG` |

### Far East (For Later)
| Marketplace | ID |
|-------------|-----|
| Amazon.com.au | `A39IBJ37TRP1C6` |
| Amazon.co.jp | `A1VC38T7YXB528` |

---

## API Testing Completed

### Test 1: Token Exchange ✅
```
POST https://api.amazon.com/auth/o2/token
Body (x-www-form-urlencoded):
  grant_type=refresh_token
  refresh_token=<NA_REFRESH_TOKEN>
  client_id=<LWA_CLIENT_ID>
  client_secret=<LWA_CLIENT_SECRET>

Response: 200 OK with access_token
```

### Test 2: Marketplace Participations ✅
```
GET https://sellingpartnerapi-na.amazon.com/sellers/v1/marketplaceParticipations
Headers:
  x-amz-access-token: <ACCESS_TOKEN>

Response: 200 OK - returned all 4 NA marketplaces
```

### Test 3: Sales Order Metrics ✅
```
GET https://sellingpartnerapi-na.amazon.com/sales/v1/orderMetrics?marketplaceIds=ATVPDKIKX0DER&interval=2026-01-27T00:00:00-08:00--2026-02-03T23:59:59-08:00&granularity=DAY
Headers:
  x-amz-access-token: <ACCESS_TOKEN>

Response: 200 OK - returned daily sales data
```

### Sample Sales Data Retrieved (US, Jan 27 - Feb 3, 2026)
| Date | Units | Orders | Revenue |
|------|-------|--------|---------|
| Jan 27 | 814 | 603 | $15,318 |
| Jan 28 | 662 | 594 | $12,829 |
| Jan 29 | 734 | 666 | $14,799 |
| Jan 30 | 759 | 653 | $14,690 |
| Jan 31 | 585 | 548 | $11,657 |
| Feb 1 | 681 | 635 | $13,264 |
| Feb 2 | 794 | 712 | $15,645 |

---

## CRITICAL: Two APIs Required

### The Discovery
The 200-300MB Search Term Reports that Chalkola downloads come from **Amazon Advertising API**, NOT SP-API.

| Data Type | Source API | SP-API Status |
|-----------|------------|---------------|
| Brand Analytics SQP | SP-API ✅ | Ready to use |
| Sales/Orders | SP-API ✅ | Ready to use |
| FBA Inventory | SP-API ✅ | Ready to use |
| AWD Data | SP-API ✅ | Ready to use |
| **Search Term Reports (300MB)** | Advertising API ❌ | **NOT SP-API** |
| **Campaign Performance** | Advertising API ❌ | **NOT SP-API** |
| **PPC Metrics** | Advertising API ❌ | **NOT SP-API** |

### Advertising API Registration (Still Needed)
- **URL:** https://advertising.amazon.com/API
- **Status:** Not yet registered
- **Required for:** Search Term Reports, Campaign data, all PPC metrics
- **Note:** Separate OAuth credentials from SP-API

---

## Pending Decisions for Next Session

### 1. What Data to Automate First?
Options discussed:
- **Brand Analytics SQP** - Keyword performance for Keyword Tracker (SP-API)
- **Daily Sales Data** - Revenue tracking (SP-API)
- **FBA Inventory** - Stock levels (SP-API)
- **Search Term Reports** - Requires Advertising API (not SP-API)

**Key Question:** What manual task is causing the most pain right now?

### 2. Database Structure
Options:
- New Supabase tables (separate from existing apps)
- Into existing Keyword Tracker database
- New dedicated database

### 3. Automation Frequency
Options:
- Once daily (overnight)
- Every few hours
- Depends on data type

### 4. Advertising API Priority
**Question:** Should we register for Advertising API before building SP-API automation, since the biggest files (Search Term Reports) require it?

---

## Automation Approach Agreed

### Method
- Claude builds complete, ready-to-deploy project
- Anuj deploys via GitHub Desktop to Railway (familiar workflow)
- Runs automatically on schedule
- Managed via environment variables in Railway

### Technical Requirements
The automation service needs to:
1. Refresh access tokens automatically (hourly expiration)
2. Run on a schedule (cron jobs)
3. Store data in Supabase
4. Handle errors and retries
5. Support multiple marketplaces (NA first, EU/FE later)

### Anuj's Technical Comfort Level
- Uses GitHub Desktop (not command line Git)
- Deploys to Railway
- Can manage environment variables
- Not comfortable writing/debugging code
- Needs ready-to-deploy solutions

---

## SP-API Endpoints Reference

### Regional Endpoints
| Region | Endpoint |
|--------|----------|
| North America | `sellingpartnerapi-na.amazon.com` |
| Europe | `sellingpartnerapi-eu.amazon.com` |
| Far East | `sellingpartnerapi-fe.amazon.com` |

### Key APIs for Chalkola's Use Cases
| API | Endpoint | Use Case |
|-----|----------|----------|
| Sales | `/sales/v1/orderMetrics` | Daily sales data |
| FBA Inventory | `/fba/inventory/v1/summaries` | Stock levels |
| Reports | `/reports/2021-06-30/reports` | Brand Analytics SQP, financial reports |
| Orders | `/orders/v0/orders` | Order details |
| Catalog | `/catalog/2022-04-01/items/{asin}` | Product data |

### Brand Analytics SQP (3-Step Process)
1. **Create Report:** POST `/reports/2021-06-30/reports` with reportType `GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT`
2. **Poll Status:** GET `/reports/2021-06-30/reports/{reportId}` until status is `DONE`
3. **Download:** GET the document from `reportDocumentId`

---

## Technical Patterns From Existing Systems

From context doc - patterns already used in Chalkola's systems:
- Use `python-calamine` for fast Excel reading
- Use `xlsxwriter` for Excel generation
- Use `ThreadPoolExecutor` for parallel API calls
- Use composite period keys (e.g., `2025-01-01_MONTH`)
- Pagination: increment by `len(result.data)`, not page size
- Supabase batch inserts for large data
- Chunked uploads for large files

---

## Reference Links

### SP-API
- SP-API Documentation: https://developer-docs.amazon.com/sp-api/docs
- Connecting to SP-API: https://developer-docs.amazon.com/sp-api/docs/connecting-to-the-selling-partner-api
- Reports API: https://developer-docs.amazon.com/sp-api/docs/reports-api-v2021-06-30-reference
- Sales API: https://developer-docs.amazon.com/sp-api/docs/sales-api-v1-reference

### Amazon Advertising API (For Later)
- Portal: https://advertising.amazon.com/API
- Documentation: https://advertising.amazon.com/API/docs

### Chalkola Tools
- DataDive (current SQP source): https://datadive.tools

---

## Postman Collection Info

Anuj has Postman set up with working requests:
1. **Token Request** - POST to LWA for access token
2. **Marketplace Participations** - GET to verify access
3. **Sales Order Metrics** - GET for sales data

These can be used as reference for building automation.

---

## Session Log

| Date | What Happened |
|------|---------------|
| Jan 2026 | SP-API developer registration approved (8 roles) |
| Feb 3, 2026 | Created SP-API app "Chalkola One System" |
| Feb 3, 2026 | Generated LWA credentials |
| Feb 3, 2026 | Authorized app for North America region |
| Feb 3, 2026 | Successfully tested Sales API via Postman |
| Feb 3, 2026 | Confirmed SP-API authentication working |

---

## Next Steps for Next Session

1. **Decide:** What data to automate first (SQP vs Sales vs Search Terms)
2. **Decide:** Database structure (new tables vs existing)
3. **Decide:** Whether to register Advertising API first
4. **Build:** Automation service based on decisions
5. **Later:** Authorize EU and FE regions

---

*End of Context Document - February 3, 2026*
