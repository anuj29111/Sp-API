/**
 * SP-API Sales Data Google Sheets Integration
 *
 * This script pulls sales data from Supabase and populates the sheet
 * with monthly, weekly, and daily sales metrics.
 *
 * Setup: Copy this code to Extensions > Apps Script in your Google Sheet
 */

// ============================================
// CONFIGURATION
// ============================================

const CONFIG = {
  SUPABASE_URL: 'https://yawaopfqkkvdqtsagmng.supabase.co',
  SUPABASE_ANON_KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlhd2FvcGZxa2t2ZHF0c2FnbW5nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjkxNjI1MDIsImV4cCI6MjA4NDczODUwMn0.XU2q39Ps6_DSuZVsdni32iXIW48-coeZZ13ojvz2LdQ',

  MARKETPLACES: {
    'CA': 'a1b2c3d4-58cc-4372-a567-0e02b2c3d480',
    'USA': 'f47ac10b-58cc-4372-a567-0e02b2c3d479'
  },

  // Sheet names
  SHEETS: {
    'CA': 'CA Sales',
    'USA': 'USA Sales'
  }
};

// ============================================
// MENU & UI
// ============================================

/**
 * Creates custom menu when spreadsheet opens
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('SP-API Data')
    .addItem('Refresh All Data', 'refreshAllSheets')
    .addItem('Refresh CA Only', 'refreshCA')
    .addItem('Refresh USA Only', 'refreshUSA')
    .addSeparator()
    .addItem('Setup Sheets', 'setupSheets')
    .addToUi();
}

/**
 * Creates the sheet structure if it doesn't exist
 */
function setupSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  for (const [code, sheetName] of Object.entries(CONFIG.SHEETS)) {
    let sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
      Logger.log(`Created sheet: ${sheetName}`);
    }
  }

  SpreadsheetApp.getUi().alert('Sheets setup complete!');
}

// ============================================
// SUPABASE API
// ============================================

/**
 * Makes a GET request to Supabase REST API
 * @param {string} endpoint - The API endpoint (e.g., '/rest/v1/table_name')
 * @param {Object} params - Query parameters
 * @returns {Array} - JSON response data
 */
function fetchFromSupabase(endpoint, params = {}) {
  const url = new URL(CONFIG.SUPABASE_URL + endpoint);

  // Add query parameters
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.append(key, value);
  }

  const options = {
    method: 'GET',
    headers: {
      'apikey': CONFIG.SUPABASE_ANON_KEY,
      'Authorization': `Bearer ${CONFIG.SUPABASE_ANON_KEY}`,
      'Content-Type': 'application/json'
    },
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url.toString(), options);
  const responseCode = response.getResponseCode();

  if (responseCode !== 200) {
    Logger.log(`Error ${responseCode}: ${response.getContentText()}`);
    throw new Error(`Supabase API error: ${responseCode}`);
  }

  return JSON.parse(response.getContentText());
}

// ============================================
// DATA FETCHING
// ============================================

/**
 * Fetches monthly sales data for a marketplace
 * @param {string} marketplaceId - UUID of the marketplace
 * @returns {Array} - Monthly sales data
 */
function getMonthlyData(marketplaceId) {
  return fetchFromSupabase('/rest/v1/sp_monthly_asin_data', {
    'marketplace_id': `eq.${marketplaceId}`,
    'select': 'month,child_asin,units_ordered,ordered_product_sales,sessions,page_views,avg_conversion_rate',
    'order': 'month.asc'
  });
}

/**
 * Fetches weekly sales data for a marketplace
 * @param {string} marketplaceId - UUID of the marketplace
 * @returns {Array} - Weekly sales data
 */
function getWeeklyData(marketplaceId) {
  return fetchFromSupabase('/rest/v1/sp_weekly_asin_data', {
    'marketplace_id': `eq.${marketplaceId}`,
    'select': 'week_start,iso_week_number,child_asin,units_ordered,ordered_product_sales,sessions',
    'order': 'week_start.asc'
  });
}

/**
 * Fetches product info (name, category) for a marketplace
 * @param {string} marketplaceId - UUID of the marketplace
 * @returns {Object} - Map of ASIN to product info
 */
function getProductInfo(marketplaceId) {
  const data = fetchFromSupabase('/rest/v1/product_variants', {
    'select': 'child_asin,product_name,product_id,products!inner(category_name,marketplace_id)',
    'products.marketplace_id': `eq.${marketplaceId}`
  });

  // Convert to lookup map
  const productMap = {};
  for (const item of data) {
    productMap[item.child_asin] = {
      name: item.product_name || 'Unknown',
      category: item.products?.category_name || 'Uncategorized'
    };
  }

  return productMap;
}

// ============================================
// DATA TRANSFORMATION
// ============================================

/**
 * Pivots monthly data from rows to columns
 * @param {Array} data - Raw monthly data
 * @returns {Object} - { months: [...], dataByAsin: { asin: { month: value } } }
 */
function pivotMonthlyData(data) {
  const months = [...new Set(data.map(d => d.month))].sort();
  const dataByAsin = {};

  for (const row of data) {
    if (!dataByAsin[row.child_asin]) {
      dataByAsin[row.child_asin] = {};
    }
    dataByAsin[row.child_asin][row.month] = {
      units: row.units_ordered || 0,
      revenue: parseFloat(row.ordered_product_sales) || 0,
      sessions: row.sessions || 0
    };
  }

  return { months, dataByAsin };
}

/**
 * Pivots weekly data from rows to columns
 * @param {Array} data - Raw weekly data
 * @returns {Object} - { weeks: [...], dataByAsin: { asin: { week: value } } }
 */
function pivotWeeklyData(data) {
  const weeks = [...new Set(data.map(d => d.week_start))].sort();
  const dataByAsin = {};

  for (const row of data) {
    if (!dataByAsin[row.child_asin]) {
      dataByAsin[row.child_asin] = {};
    }
    dataByAsin[row.child_asin][row.week_start] = {
      units: row.units_ordered || 0,
      revenue: parseFloat(row.ordered_product_sales) || 0,
      sessions: row.sessions || 0
    };
  }

  return { weeks, dataByAsin };
}

// ============================================
// SHEET WRITING
// ============================================

/**
 * Formats a date string to readable format
 * @param {string} dateStr - ISO date string
 * @param {string} type - 'month' or 'week'
 * @returns {string} - Formatted date
 */
function formatDate(dateStr, type) {
  const date = new Date(dateStr);
  if (type === 'month') {
    return Utilities.formatDate(date, 'UTC', 'MMM yyyy');
  } else {
    return `Wk ${Utilities.formatDate(date, 'UTC', 'w')}`;
  }
}

/**
 * Refreshes data for a specific marketplace
 * @param {string} marketplaceCode - 'CA' or 'USA'
 */
function refreshMarketplace(marketplaceCode) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetName = CONFIG.SHEETS[marketplaceCode];
  let sheet = ss.getSheetByName(sheetName);

  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
  }

  const marketplaceId = CONFIG.MARKETPLACES[marketplaceCode];

  Logger.log(`Refreshing ${marketplaceCode}...`);

  // Fetch all data
  const monthlyData = getMonthlyData(marketplaceId);
  const weeklyData = getWeeklyData(marketplaceId);
  const productInfo = getProductInfo(marketplaceId);

  Logger.log(`Fetched ${monthlyData.length} monthly rows, ${weeklyData.length} weekly rows`);

  // Pivot data
  const { months, dataByAsin: monthlyByAsin } = pivotMonthlyData(monthlyData);
  const { weeks, dataByAsin: weeklyByAsin } = pivotWeeklyData(weeklyData);

  // Get all unique ASINs
  const allAsins = [...new Set([...Object.keys(monthlyByAsin), ...Object.keys(weeklyByAsin)])].sort();

  Logger.log(`Found ${allAsins.length} unique ASINs, ${months.length} months, ${weeks.length} weeks`);

  // Build header row
  const headers = ['ASIN', 'Name', 'Category'];

  // Add monthly headers (Units)
  for (const month of months) {
    headers.push(formatDate(month, 'month') + ' Units');
  }

  // Add weekly headers (Units)
  for (const week of weeks) {
    headers.push(formatDate(week, 'week') + ' Units');
  }

  // Add monthly revenue columns
  for (const month of months) {
    headers.push(formatDate(month, 'month') + ' Rev');
  }

  // Build data rows
  const rows = [headers];

  for (const asin of allAsins) {
    const product = productInfo[asin] || { name: 'Unknown', category: 'Unknown' };
    const row = [asin, product.name, product.category];

    // Monthly units
    for (const month of months) {
      const monthData = monthlyByAsin[asin]?.[month];
      row.push(monthData ? monthData.units : 0);
    }

    // Weekly units
    for (const week of weeks) {
      const weekData = weeklyByAsin[asin]?.[week];
      row.push(weekData ? weekData.units : 0);
    }

    // Monthly revenue
    for (const month of months) {
      const monthData = monthlyByAsin[asin]?.[month];
      row.push(monthData ? monthData.revenue : 0);
    }

    rows.push(row);
  }

  // Clear and write to sheet
  sheet.clear();
  sheet.getRange(1, 1, rows.length, rows[0].length).setValues(rows);

  // Format header row
  const headerRange = sheet.getRange(1, 1, 1, headers.length);
  headerRange.setFontWeight('bold');
  headerRange.setBackground('#4285f4');
  headerRange.setFontColor('white');

  // Freeze header row and first 3 columns
  sheet.setFrozenRows(1);
  sheet.setFrozenColumns(3);

  // Auto-resize columns
  for (let i = 1; i <= Math.min(headers.length, 26); i++) {
    sheet.autoResizeColumn(i);
  }

  Logger.log(`${marketplaceCode} refresh complete: ${allAsins.length} products, ${headers.length} columns`);
}

// ============================================
// PUBLIC FUNCTIONS
// ============================================

/**
 * Refreshes all marketplace sheets
 */
function refreshAllSheets() {
  const startTime = new Date();

  for (const code of Object.keys(CONFIG.MARKETPLACES)) {
    try {
      refreshMarketplace(code);
    } catch (e) {
      Logger.log(`Error refreshing ${code}: ${e.message}`);
    }
  }

  const duration = (new Date() - startTime) / 1000;
  SpreadsheetApp.getUi().alert(`Refresh complete in ${duration.toFixed(1)} seconds!`);
}

/**
 * Refreshes CA sheet only
 */
function refreshCA() {
  refreshMarketplace('CA');
  SpreadsheetApp.getUi().alert('CA data refreshed!');
}

/**
 * Refreshes USA sheet only
 */
function refreshUSA() {
  refreshMarketplace('USA');
  SpreadsheetApp.getUi().alert('USA data refreshed!');
}

// ============================================
// SCHEDULED TRIGGER
// ============================================

/**
 * Function to be called by time-based trigger
 * Runs silently without UI alerts
 */
function scheduledRefresh() {
  for (const code of Object.keys(CONFIG.MARKETPLACES)) {
    try {
      refreshMarketplace(code);
      Logger.log(`Scheduled refresh for ${code} complete`);
    } catch (e) {
      Logger.log(`Scheduled refresh error for ${code}: ${e.message}`);
    }
  }
}
