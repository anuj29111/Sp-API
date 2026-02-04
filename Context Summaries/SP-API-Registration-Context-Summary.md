# Amazon SP-API Registration - Context & Next Steps

## Document Purpose
This document provides full context for continuing SP-API integration work with Chalkola. Use this to onboard into a new conversation.

---

## Executive Summary

**Status:** ✅ SP-API Developer Registration APPROVED  
**Date:** January 2026  
**Organization:** Chalkola  
**Primary Contact:** Anuj Agarwal  
**Registration Type:** Private Developer (internal tools only)

---

## About Chalkola

### Business Overview
- **Product:** Art supplies (chalk markers, paint pens)
- **Business Model:** Amazon FBA
- **Marketplaces:** 10 countries (US, CA, UK, DE, FR, IT, ES, UAE, AU, JP)
- **Monthly Ad Spend:** $100k+
- **Team Size:** 10-15 people
- **Technical Background:** Non-technical founder, uses GitHub Desktop exclusively

### Existing Internal Systems
| System | Version | Purpose | Tech Stack |
|--------|---------|---------|------------|
| Keyword Tracker | v1.0.75+ | Track keyword rankings, DataDive/SQP/PPC data | Next.js, Supabase, Railway |
| FBA Shipment System | v5.5.28 | Manage FBA shipments, supplier files, AWD | Next.js, Supabase, Railway |
| POP System | v3.5.75 | Search Term Impression Share analytics | Next.js, Flask, Supabase |

### Data Scale
- US Search Term Reports: 200-300MB per download
- Other marketplaces: ~100MB per download
- Row counts: 100k+ rows per report
- Historical data goal: Millions of rows (12+ months retention)
- Database: Supabase Pro (can upgrade as needed)

---

## SP-API Registration Details

### Registration Path
- **URL Used:** https://developer.amazonservices.com/private-developer
- **Type Selected:** "Build applications that use SP APIs"
- **Organization Type:** Private Solution Provider

### Roles Approved (8 Roles)

| Role | Purpose for Chalkola |
|------|---------------------|
| **Product Listing** | Product catalog data, listing information, A+ content |
| **Pricing** | Future repricing automation capability |
| **Amazon Fulfillment** | FBA shipment tracking, fulfillment data, inbound shipments |
| **Selling Partner Insights** | Account performance, marketplace participation |
| **Finance and Accounting** | Settlement reports, financial statements |
| **Inventory and Order Tracking** | Inventory levels, order data, sales metrics |
| **Amazon Warehousing and Distribution** | AWD inventory and shipment tracking |
| **Brand Analytics** | Search Query Performance (SQP) data |

### Roles NOT Requested (and why)
| Role | Reason Skipped |
|------|---------------|
| Buyer Communication | Don't need to message customers via API |
| Buyer Solicitation | Don't need automated review requests |
| Direct-to-Consumer Shipping (Restricted) | Use FBA, not merchant fulfilled |
| Tax Invoicing (Restricted) | Requires PII justification |
| Tax Remittance (Restricted) | Requires PII justification |
| Professional Services (Restricted) | Not applicable |
| Amazon Business roles | B2B only, not relevant |
| Account/Payment Service Provider | European banking APIs only |

### Use Cases Submitted
```
Chalkola is an art supplies brand selling chalk markers and paint pens on Amazon 
across 10 international marketplaces (US, CA, UK, DE, FR, IT, ES, UAE, AU, JP). 
We are building internal business intelligence and automation tools for our team 
of 15 people. All data accessed through SP-API will be used exclusively for 
internal business operations.

Key use cases:
- Brand Analytics (SQP) for keyword tracking
- Inventory and order tracking for stock management
- FBA and AWD fulfillment tracking
- Financial reporting and reconciliation
- Product catalog synchronization
```

### Security Controls Confirmed
All answered "Yes":
- ✅ Network security controls (firewalls, IDS/IPS, anti-virus)
- ✅ Role-based access restrictions
- ✅ Encryption in transit (HTTPS)
- ✅ Incident response plan with 6-month reviews
- ✅ 24-hour incident reporting to security@amazon.com
- ✅ Password requirements (12-char, MFA, rotation)
- ✅ Secure credential storage (environment variables, not hardcoded)

---

## CRITICAL: Two APIs Required

### Discovery During Registration
The 200-300MB Search Term Reports that Chalkola downloads come from **Amazon Advertising API**, NOT SP-API.

| API | What It Provides | Registration Status |
|-----|------------------|-------------------|
| **SP-API** | Sales, inventory, FBA, Brand Analytics SQP, financial reports | ✅ APPROVED |
| **Amazon Advertising API** | Search Term Reports, Campaign data, PPC metrics | ❌ NOT YET REGISTERED |

### Data Source Mapping
| Data Type | Source API | File Size |
|-----------|------------|-----------|
| Search Term Reports | Advertising API | 200-300MB |
| Campaign Performance | Advertising API | Large |
| Search Query Performance (SQP) | SP-API (Brand Analytics) | Moderate |
| FBA Inventory | SP-API | Small |
| Orders/Sales | SP-API | Moderate |
| Settlement Reports | SP-API | Moderate |
| AWD Data | SP-API | Small |

---

## Next Steps Required

### STEP 1: AWS Account & IAM Setup (Required for SP-API)
Even though SP-API is approved, you still need AWS credentials to make API calls.

**Tasks:**
1. Create AWS Account (if not already done)
2. Create IAM User (`sp-api-user`)
3. Attach policy: `AmazonAPIGatewayInvokeFullAccess`
4. Generate Access Keys (save securely!)
5. Create IAM Role (`sp-api-role`) with trust policy
6. Save the Role ARN

**Credentials to Save:**
- AWS Account ID (12 digits)
- IAM User Access Key ID
- IAM User Secret Access Key (cannot retrieve again!)
- IAM Role ARN

### STEP 2: Register SP-API Application
In Seller Central → Apps & Services → Develop Apps:
1. Create new app client
2. Enter IAM Role ARN
3. Select approved roles
4. Get LWA (Login with Amazon) credentials:
   - Client ID
   - Client Secret

### STEP 3: Self-Authorization (Private Developer)
Since Chalkola is a Private Developer:
1. Go to app in Developer Central
2. Click "Authorize" for your own seller account
3. Generate Refresh Token
4. Save the Refresh Token (used for all API calls)

### STEP 4: Register for Amazon Advertising API
**URL:** https://advertising.amazon.com/API

This is SEPARATE from SP-API and required for:
- Search Term Reports (your 200-300MB files)
- Campaign performance data
- Sponsored Products/Brands/Display data
- All PPC metrics

### STEP 5: Build Integration
Once all credentials are obtained:
1. Build backend service (Flask on Railway recommended)
2. Implement OAuth token refresh flow
3. Create scheduled jobs for data pulls
4. Process and load data to Supabase
5. Connect to existing Keyword Tracker / POP systems

---

## Architecture Vision

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                                 │
├─────────────────────────────────────────────────────────────────┤
│  Amazon SP-API          │  Amazon Advertising API               │
│  - Brand Analytics SQP  │  - Search Term Reports (300MB)        │
│  - FBA Inventory        │  - Campaign Performance               │
│  - Orders/Sales         │  - Sponsored Products Data            │
│  - AWD Data             │  - PPC Metrics                        │
│  - Settlement Reports   │                                       │
└───────────┬─────────────┴──────────────┬────────────────────────┘
            │                            │
            ▼                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  DATA PIPELINE (Railway)                         │
│  - Scheduled jobs (pg_cron)                                     │
│  - Large file processing (chunked)                              │
│  - Data transformation                                          │
│  - Error handling & retries                                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  SUPABASE (PostgreSQL)                          │
│  - Millions of rows capacity                                    │
│  - Partitioned tables by marketplace + month                    │
│  - Proper indexing                                              │
│  - 12+ months data retention                                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│   Keyword     │  │     POP       │  │     FBA       │
│   Tracker     │  │    System     │  │   Shipment    │
└───────────────┘  └───────────────┘  └───────────────┘
```

---

## Technical Considerations

### File Size Handling
- Browser uploads limited to ~100MB practical
- Supabase request limit: 6MB default
- Railway timeout: 30 seconds
- **Solution:** Chunked uploads → Supabase Storage → Background processing

### Database Scaling
| Consideration | Approach |
|---------------|----------|
| Row volume | Millions supported on Supabase Pro |
| Query speed | Composite indexes from day 1 |
| Partitioning | By marketplace + time period |
| Retention | Raw data 12 months, aggregates indefinitely |

### Existing Patterns to Follow
- Use `python-calamine` for fast Excel reading
- Use `xlsxwriter` for Excel generation
- Use `ThreadPoolExecutor` for parallel API calls
- Use composite period keys (e.g., `2025-01-01_MONTH`)
- Pagination: increment by `len(result.data)`, not page size

---

## Credentials Checklist

### SP-API Credentials (To Obtain)
- [ ] AWS Account ID
- [ ] IAM User Access Key ID
- [ ] IAM User Secret Access Key
- [ ] IAM Role ARN
- [ ] LWA Client ID
- [ ] LWA Client Secret
- [ ] Refresh Token (per marketplace/seller account)

### Advertising API Credentials (To Obtain)
- [ ] Advertising API Client ID
- [ ] Advertising API Client Secret
- [ ] Advertising API Refresh Token
- [ ] Profile IDs (one per marketplace)

---

## Questions for Next Session

1. **AWS Account:** Do you already have an AWS account, or do we need to create one?

2. **Priority API:** Which data do you want to automate first?
   - Search Term Reports (Advertising API) — your 300MB files
   - Brand Analytics SQP (SP-API) — keyword rankings
   - FBA/AWD Inventory (SP-API) — stock levels

3. **Manual Upload Interim:** While waiting for Advertising API approval, do you want to build a chunked upload system for your Search Term Reports so you can start using them immediately?

4. **Marketplace Priority:** Start with US only, or build for all 10 marketplaces from the beginning?

---

## Reference Links

- SP-API Documentation: https://developer-docs.amazon.com/sp-api/docs
- SP-API Role Mappings: https://developer-docs.amazon.com/sp-api/docs/role-mappings
- Amazon Advertising API: https://advertising.amazon.com/API
- Advertising API Docs: https://advertising.amazon.com/API/docs
- DataDive (current tool): https://datadive.tools

---

## Document History

| Date | Update |
|------|--------|
| Jan 2026 | Initial SP-API registration completed and approved |
| Jan 2026 | Context document created for continuation |

---

*End of Context Document*
