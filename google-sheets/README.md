# Google Sheets Integration for SP-API Sales Data

This Google Apps Script pulls sales data from Supabase and populates a Google Sheet with monthly and weekly sales metrics for CA and USA marketplaces.

## Quick Start

### Step 1: Create a New Google Sheet

1. Go to [Google Sheets](https://sheets.google.com)
2. Create a new blank spreadsheet
3. Name it something like "Chalkola Sales Dashboard"

### Step 2: Add the Apps Script

1. In your Google Sheet, go to **Extensions > Apps Script**
2. Delete any existing code in `Code.gs`
3. Copy the entire contents of `Code.gs` from this folder and paste it
4. Click **Save** (Ctrl+S / Cmd+S)
5. Close the Apps Script editor

### Step 3: Refresh the Page

1. Close and reopen your Google Sheet
2. You should now see a new menu item: **SP-API Data**

### Step 4: Initial Setup

1. Click **SP-API Data > Setup Sheets**
   - This creates the "CA Sales" and "USA Sales" tabs

2. Click **SP-API Data > Refresh All Data**
   - First run will ask for permissions - click "Allow"
   - Wait for the data to load (30-60 seconds)

### Step 5: Set Up Automatic Refresh (Optional)

To have the sheet refresh automatically every day:

1. Go to **Extensions > Apps Script**
2. Click the clock icon (Triggers) in the left sidebar
3. Click **+ Add Trigger**
4. Configure:
   - Function: `scheduledRefresh`
   - Event source: Time-driven
   - Type: Day timer
   - Time: 4am to 5am (after SP-API data pull at 2-3am)
5. Click **Save**

---

## Sheet Structure

### CA Sales / USA Sales Tabs

| Column | Description |
|--------|-------------|
| A - ASIN | Amazon product identifier |
| B - Name | Short product name |
| C - Category | Product category |
| D+ - Monthly Units | Units sold per month (Dec 2025, Jan 2026, etc.) |
| ... - Weekly Units | Units sold per week (Wk 51, Wk 52, etc.) |
| ... - Monthly Revenue | Revenue per month |

---

## Manual Refresh

Use the **SP-API Data** menu:
- **Refresh All Data** - Updates both CA and USA
- **Refresh CA Only** - Updates just Canada
- **Refresh USA Only** - Updates just United States

---

## Troubleshooting

### "Script function not found" error
- Make sure you saved the Code.gs file
- Refresh the Google Sheet page

### No data appears
- Check that SP-API data exists in Supabase
- Run `refreshAllSheets()` from Apps Script editor to see error logs

### Permission errors
- First run requires authorization
- Click "Advanced" > "Go to [project name]" > "Allow"

### Slow refresh
- Normal refresh takes 30-60 seconds
- Large date ranges may take longer

---

## Data Source

Data comes from these Supabase views:
- `sp_monthly_asin_data` - Monthly aggregates
- `sp_weekly_asin_data` - Weekly aggregates
- `product_variants` + `products` - Product names and categories

Marketplace IDs:
- CA: `a1b2c3d4-58cc-4372-a567-0e02b2c3d480`
- USA: `f47ac10b-58cc-4372-a567-0e02b2c3d479`

---

## Customization

### Add More Marketplaces

Edit `CONFIG.MARKETPLACES` and `CONFIG.SHEETS` in Code.gs:

```javascript
MARKETPLACES: {
  'CA': 'a1b2c3d4-58cc-4372-a567-0e02b2c3d480',
  'USA': 'f47ac10b-58cc-4372-a567-0e02b2c3d479',
  'UK': 'b2c3d4e5-58cc-4372-a567-0e02b2c3d481'  // Add new marketplace
},
SHEETS: {
  'CA': 'CA Sales',
  'USA': 'USA Sales',
  'UK': 'UK Sales'  // Add new sheet name
}
```

### Change Columns

Modify `refreshMarketplace()` function to add/remove columns:
- Sessions data is already fetched, just not displayed
- Add columns for `sessions`, `page_views`, `avg_conversion_rate`

---

## Security Notes

- Uses Supabase **anon key** (safe for client-side use)
- Data protected by Row Level Security (RLS) policies
- No sensitive credentials in the script

---

*Last Updated: February 2026*
