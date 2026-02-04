# Amazon SP-API Use Case Matrix for Chalkola Private Seller Development

Direct API access can fully replace Gorilla ROI functions and unlock powerful automation capabilities across Chalkola's 7 marketplaces. The **Amazon Advertising API operates separately from SP-API** with different credentials, while core business data flows through SP-API's Reports, Orders, and Inventory endpoints. For a $100k+ monthly ad spend FBA business, priority implementation should focus on advertising data pipelines first, followed by inventory automation and Brand Analytics integration.

---

## Critical architecture finding: Two separate APIs required

Your internal tools will need to integrate with **two distinct Amazon APIs** that have separate registration and authentication:

| API System | Purpose | Authentication | Registration Portal |
|------------|---------|----------------|---------------------|
| **SP-API** | Orders, inventory, reports, catalog, fulfillment | OAuth 2.0 + LWA only | developer-docs.amazon.com/sp-api |
| **Amazon Advertising API** | Campaign management, ad reporting, bid optimization | OAuth 2.0 + LWA | advertising.amazon.com/about-api |

**Both APIs are free to use** (no per-call charges). SP-API requires a Professional Seller account; Advertising API requires an active advertising account.

---

## 1. Data pull use cases (Gorilla ROI replacement)

### Sales data endpoints

| Gorilla Function | SP-API Replacement | Endpoint | Role Required | Rate Limit | Data Freshness | Complexity |
|------------------|-------------------|----------|---------------|------------|----------------|------------|
| GORILLA_SALESCOUNT | Sales API `getOrderMetrics` | `GET /sales/v1/orderMetrics` | Direct to Consumer | 0.5/sec, burst 15 | Hourly updates | **Easy** |
| GORILLA_SALESTOTAL | Sales API + GET_SALES_AND_TRAFFIC_REPORT | Reports API | Brand Analytics | Report queue | 72 hours after period close | **Easy** |
| Sales by date range | Orders API `getOrders` | `GET /orders/v0/orders` | Direct to Consumer | 0.0167/sec, burst 20 | Real-time | **Easy** |

**Key parameters for Sales API:** Supports `interval` (ISO 8601 date range), `granularity` (DAY/WEEK/MONTH), date ranges up to **2 years historical**.

### Inventory data endpoints

| Gorilla Function | SP-API Replacement | Endpoint | Role Required | Rate Limit | Data Freshness | Complexity |
|------------------|-------------------|----------|---------------|------------|----------------|------------|
| GORILLA_INVENTORY | FBA Inventory API `getInventorySummaries` | `GET /fba/inventory/v1/summaries` | Inventory and Order Management | 2/sec, burst 2 | Real-time | **Easy** |
| GORILLA_INVENTORYHEALTH | GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA | Reports API | Inventory and Order Tracking | Report queue | Generated max every 4 hours | **Easy** |
| Stranded inventory | GET_STRANDED_INVENTORY_UI_DATA | Reports API | Inventory and Order Tracking | Report queue | Daily | **Easy** |
| Reserved inventory | GET_RESERVED_INVENTORY_DATA | Reports API | Inventory and Order Tracking | Report queue | Daily | **Easy** |

**FBA Inventory API returns:** fulfillableQuantity, inboundWorkingQuantity, inboundShippedQuantity, inboundReceivingQuantity, reservedQuantity, unfulfillableQuantity, researchingQuantity.

### Business reports (sessions and conversions)

| Gorilla Function | SP-API Replacement | Report Type | Role Required | Date Range | Data Freshness | Complexity |
|------------------|-------------------|-------------|---------------|------------|----------------|------------|
| GORILLA_BIZCONVERSION | GET_SALES_AND_TRAFFIC_REPORT | Reports API | Brand Analytics | Up to 2 years | 72 hours after period | **Easy** |
| GORILLA_BIZSESSIONS | GET_SALES_AND_TRAFFIC_REPORT | Reports API | Brand Analytics | Up to 2 years | 72 hours after period | **Easy** |

**Available metrics in Sales and Traffic Report:**
- **Sales:** orderedProductSales, unitsOrdered, totalOrderItems (with B2B breakdowns)
- **Traffic:** pageViews, sessions, buyBoxPercentage, unitSessionPercentage (conversion rate)

### Pricing and fees endpoints

| Gorilla Function | SP-API Replacement | Endpoint | Role Required | Rate Limit | Data Freshness | Complexity |
|------------------|-------------------|----------|---------------|------------|----------------|------------|
| GORILLA_MYPRICE | Product Pricing API `getPricing` | `GET /products/pricing/v0/price` | Pricing | 0.5/sec, burst 1 | Real-time | **Easy** |
| GORILLA_FEESESTIMATE | Product Fees API `getMyFeesEstimates` | `POST /products/fees/v0/feesEstimate` | Pricing | 1/sec, burst 2 | Real-time | **Easy** |
| Competitive pricing | `getCompetitivePricing` | Product Pricing API | Pricing | 0.5/sec, burst 1 | Real-time | **Easy** |

**Batch capabilities:** Both pricing and fees APIs support batch operations for up to **20 items per request**, critical for rate limit optimization.

### Product catalog endpoints

| Gorilla Function | SP-API Replacement | Endpoint | Role Required | Rate Limit | Data Freshness | Complexity |
|------------------|-------------------|----------|---------------|------------|----------------|------------|
| GORILLA_PRODUCT | Catalog Items API `getCatalogItem` | `GET /catalog/2022-04-01/items/{asin}` | Product Listing | 2/sec, burst 2 | Real-time | **Easy** |
| GORILLA_CATEGORY | Catalog Items API with `classifications` | Same endpoint | Product Listing | 2/sec, burst 2 | Real-time | **Easy** |
| BSR data | Catalog Items API with `salesRanks` | Same endpoint | Product Listing | 2/sec, burst 2 | Updated periodically | **Easy** |

---

## 2. Advertising data (separate API required)

**Critical:** Advertising data requires the **Amazon Advertising API**, not SP-API. This replaces all GORILLA_AD* functions.

| Gorilla Function | Amazon Ads API Replacement | Report Type | Rate Limit | Data Freshness | Complexity |
|------------------|---------------------------|-------------|------------|----------------|------------|
| GORILLA_ADPERFORMPROD | Sponsored Products Advertised Product Report | V3 Reporting API | 10/sec general | 24-48 hours | **Medium** |
| GORILLA_SPSTATS | amzn_ads_sp_campaigns | V3 Reporting API | 10/sec general | 24-48 hours | **Medium** |
| GORILLA_SBSTATS | amzn_ads_sb_campaigns | V3 Reporting API | 10/sec general | 24-48 hours | **Medium** |
| GORILLA_SPSPENDPROD | SP Advertised Product Report | V3 Reporting API | 10/sec general | 24-48 hours | **Medium** |
| GORILLA_SDSPENDPROD | amzn_ads_sd_advertised_products | V3 Reporting API | 10/sec general | 24-48 hours | **Medium** |

**Available metrics:** impressions, clicks, CTR, spend, CPC, sales7d/14d, ACOS, ROAS, purchases, conversionRate.

**Historical data limits:**
- Sponsored Products: **95 days** lookback
- Sponsored Brands/Display: **60-65 days** lookback
- Store your own historical data for longer analysis

---

## 3. Automation use cases

### FBA shipment automation (for your FBA Shipment System)

| Use Case | API/Endpoint | Can Automate? | Role Required | Complexity | Priority |
|----------|--------------|---------------|---------------|------------|----------|
| Create FBA inbound shipment | Fulfillment Inbound API v2024-03-20 | ✅ **Yes** | Amazon Fulfillment | **High** | **P1** |
| Generate shipping labels | `getLabels` (v0) | ✅ **Yes** | Amazon Fulfillment | Medium | P1 |
| Set box content information | `setPackingInformation` | ✅ **Yes** | Amazon Fulfillment | Medium | P1 |
| Create AWD inbound order | AWD API `createInbound` | ✅ **Yes** | Amazon Warehousing and Distribution | **Medium** | **P1** |
| AWD → FBA transfers | Automated by Amazon | ⚠️ Limited control | - | - | - |
| Track shipment status | `getShipment`, `listShipmentItems` | ✅ **Yes** | Amazon Fulfillment | Easy | P2 |

**FBA Inbound workflow (10 sequential API calls):**
1. `createInboundPlan` → 2. `generatePackingOptions` → 3. `confirmPackingOption` → 4. `setPackingInformation` → 5. `generatePlacementOptions` → 6. `confirmPlacementOption` → 7. `generateTransportationOptions` → 8. `confirmTransportationOptions` → 9. `generateDeliveryWindowOptions` → 10. `confirmDeliveryWindowOptions`

### Advertising campaign automation (for POP System)

| Use Case | API Endpoint | Can Automate? | Rate Limit | Complexity | Priority |
|----------|--------------|---------------|------------|------------|----------|
| Adjust keyword bids | Keywords API + Bid Recommendations API | ✅ **Yes** | 10/sec | Medium | **P1** |
| Pause/enable campaigns | Campaigns API (SP, SB, SD) | ✅ **Yes** | 10/sec | Easy | P1 |
| Change budgets | Budget Rules API, Campaign endpoints | ✅ **Yes** | 10/sec | Easy | P1 |
| Create new campaigns | Campaigns API | ✅ **Yes** | 10/sec | Medium | P2 |
| Add/remove keywords | Keywords API | ✅ **Yes** | 10/sec | Easy | P1 |
| Negative keyword management | Negative Keywords API | ✅ **Yes** | 10/sec | Easy | P2 |

### Pricing and deals automation

| Use Case | API/Endpoint | Can Automate? | Role Required | Complexity | Priority |
|----------|--------------|---------------|---------------|------------|----------|
| Automated repricing | Listings Items API | ✅ **Yes** | Product Listing | Medium | P2 |
| Competitive price monitoring | `ANY_OFFER_CHANGED` notification | ✅ **Yes** | Pricing | Medium | P2 |
| Deals/coupons submission | ⚠️ Limited API support | Partially | - | High | P3 |

---

## 4. Operations use cases

### Order management and returns

| Use Case | API/Endpoint | Role Required | Rate Limit | Data Freshness | Complexity |
|----------|--------------|---------------|------------|----------------|------------|
| Order retrieval (with PII) | Orders API `getOrders` | Direct-to-Consumer Shipping (Restricted) | 0.0167/sec | Real-time | Easy |
| Order tracking only | Orders API | Inventory and Order Tracking | 0.0167/sec | Real-time | Easy |
| Returns data | GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA | Amazon Fulfillment | Report queue | Daily | Easy |
| Reimbursement tracking | GET_FBA_REIMBURSEMENTS_DATA | Amazon Fulfillment | Report queue | Daily | Easy |
| Create removal orders | POST_FLAT_FILE_FBA_CREATE_REMOVAL (Feeds API) | Amazon Fulfillment | 0.0083/sec | Processed async | Medium |

### Inventory operations

| Use Case | API/Endpoint | Role Required | Data Freshness | Complexity | Priority |
|----------|--------------|---------------|----------------|------------|----------|
| Restock recommendations | GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT | Inventory and Order Tracking | Near real-time | Easy | **P1** |
| Inventory planning | GET_FBA_INVENTORY_PLANNING_DATA | Inventory and Order Tracking | Daily | Easy | P2 |
| LTSF fee avoidance | GET_FBA_RECOMMENDED_REMOVAL_DATA | Amazon Fulfillment | Daily | Easy | P2 |
| Inventory ledger reconciliation | GET_LEDGER_DETAIL_VIEW_DATA | Inventory and Order Tracking | Daily | Medium | P2 |

---

## 5. Business intelligence use cases (for Keyword Tracker)

### Brand Analytics reports

| Report | API Report Type | Role Required | Periods | Data Freshness | Priority |
|--------|-----------------|---------------|---------|----------------|----------|
| Search Query Performance (SQP) | GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT | Brand Analytics | Week/Month/Quarter | 48-72 hours | **P1** |
| Search Catalog Performance | GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT | Brand Analytics | Week/Month/Quarter | 48-72 hours | P1 |
| Market Basket Analysis | GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT | Brand Analytics | Day/Week/Month/Quarter | 48-72 hours | P2 |
| Repeat Purchase | GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT | Brand Analytics | Week/Month/Quarter | 48-72 hours | P2 |
| Search Terms | GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT | Brand Analytics + Brand Representative | Day/Week/Month/Quarter | 48-72 hours | **P1** |

**SQP Report provides:** searchQuery, impressionCount/Share, clickCount/Share, cartAddCount/Share, purchaseCount/Share — perfect for merging with DataDive and PPC metrics in your Keyword Tracker.

### Competitor monitoring capabilities

| Data Type | Source | What's Available | Limitations |
|-----------|--------|------------------|-------------|
| Market share | SQP Report | Your asinImpressionShare, asinClickShare, asinPurchaseShare vs. total market | Your ASINs only |
| Top clicked ASINs | Search Terms Report | Top 3 clicked ASINs per search term (may include competitors) | Aggregated only |
| Competitive pricing | Product Pricing API `getCompetitiveSummary` | Buy Box prices, lowest offers, price thresholds | No sales volume |
| Price change alerts | `ANY_OFFER_CHANGED` notification | Real-time competitive price changes | Requires SQS setup |

**Note:** Demographics Report is available in Seller Central UI but **NOT via API**.

---

## 6. Integration requirements for Chalkola

### Multi-marketplace regional mapping

| Chalkola Marketplace | Region | SP-API Endpoint | AWS Region |
|---------------------|--------|-----------------|------------|
| **USA** | North America | sellingpartnerapi-na.amazon.com | us-east-1 |
| **Canada** | North America | sellingpartnerapi-na.amazon.com | us-east-1 |
| **UK** | Europe | sellingpartnerapi-eu.amazon.com | eu-west-1 |
| **Germany** | Europe | sellingpartnerapi-eu.amazon.com | eu-west-1 |
| **France** | Europe | sellingpartnerapi-eu.amazon.com | eu-west-1 |
| **UAE** | Europe | sellingpartnerapi-eu.amazon.com | eu-west-1 |
| **Australia** | Far East | sellingpartnerapi-fe.amazon.com | us-west-2 |

**Authorization requirement:** Generate **separate refresh tokens per region** (NA, EU, FE). One LWA client ID/secret works across all regions.

### Required roles for Chalkola's use cases

| System Being Built | Required Roles | Restricted? |
|--------------------|----------------|-------------|
| **POP System** | Brand Analytics, Pricing | No |
| **Keyword Tracker** | Brand Analytics, Product Listing | No |
| **FBA Shipment System** | Amazon Fulfillment, Amazon Warehousing and Distribution | No |
| **Full Gorilla ROI replacement** | Direct-to-Consumer Shipping (for order PII), Inventory and Order Tracking, Pricing, Product Listing, Finance and Accounting | Partial (PII role restricted) |

### Rate limit planning for 160k+ row data processing

For high-volume operations, implement these strategies:

- **Use batch endpoints:** Product Pricing (20 items), Product Fees (20 items), Catalog Items (supports multiple identifiers)
- **Use Reports API for bulk data:** Much higher throughput than real-time APIs
- **Implement exponential backoff:** With jitter for 429 responses
- **Subscribe to notifications:** ORDER_CHANGE, ANY_OFFER_CHANGED, REPORT_PROCESSING_FINISHED instead of polling
- **Spread requests over time:** Avoid burst patterns that hit rate limits

### Data retention considerations

| Data Type | API Retention | Recommendation |
|-----------|---------------|----------------|
| Orders | 2 years | Build data warehouse for longer history |
| Ad reports | 60-95 days | Store daily for trend analysis |
| Reports (generated) | 90 days | Download and archive immediately |
| Customer PII | 30 days post-shipment | Comply with DPP requirements |

---

## Priority implementation roadmap for Chalkola

### Phase 1: Advertising data pipeline (Week 1-2)
Replace GORILLA_AD* functions first given $100k+ monthly ad spend. Register for Amazon Advertising API, implement V3 reporting for SP/SB/SD campaigns, build daily data pull automation.

**Complexity:** Medium | **Impact:** High (POP System core data)

### Phase 2: Core business data (Week 2-3)
Replace GORILLA_SALES*, GORILLA_INVENTORY*, GORILLA_BIZ* functions. Implement Sales API, FBA Inventory API, GET_SALES_AND_TRAFFIC_REPORT.

**Complexity:** Easy | **Impact:** High (eliminates Gorilla ROI dependency)

### Phase 3: Brand Analytics integration (Week 3-4)
Implement SQP and Search Terms reports for Keyword Tracker. Merge with DataDive rankings and PPC metrics.

**Complexity:** Easy | **Impact:** High (Keyword Tracker enhancement)

### Phase 4: FBA shipment automation (Week 4-6)
Implement Fulfillment Inbound API v2024-03-20 and AWD API for 2-step workflow automation.

**Complexity:** High (10-step workflow) | **Impact:** High (FBA Shipment System core)

### Phase 5: Campaign automation (Week 6-8)
Implement bid adjustment, pause/enable, budget automation via Advertising API for POP System advanced features.

**Complexity:** Medium | **Impact:** Medium (optimization automation)

---

## Registration checklist for private seller developer

1. **Verify Professional Seller account** in all 7 marketplaces
2. **Complete Developer Profile** in Seller Central → Apps and Services → Develop Apps
3. **Select "Private Developer"** for internal tools only
4. **Request all required roles:** Direct-to-Consumer Shipping, Inventory and Order Tracking, Pricing, Product Listing, Brand Analytics, Amazon Fulfillment, Amazon Warehousing and Distribution
5. **Generate refresh tokens** for each region (NA, EU, FE)
6. **Register separately** for Amazon Advertising API at advertising.amazon.com/about-api
7. **Approval timeline:** Approximately 1 week for non-restricted roles

**Authentication simplified (since October 2023):** SP-API now requires only LWA OAuth tokens — no AWS IAM or Signature V4 signing needed.