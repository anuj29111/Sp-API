/**
 * Supabase Sales Data Integration
 * Pulls sales data from Supabase and populates Daily sheets.
 * All configuration is read from the "Script Config" sheet - NO HARDCODING.
 */

// ============================================
// CONFIGURATION - Read from Script Config sheet
// ============================================

/**
 * Reads Supabase configuration from the Script Config sheet
 * @returns {Object} Configuration with url, anonKey, and marketplaces
 */
function getSupabaseConfig() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const configSheet = ss.getSheetByName('Script Config');

  if (!configSheet) {
    throw new Error('Script Config sheet not found!');
  }

  // Read all data from the sheet
  const data = configSheet.getDataRange().getValues();

  const config = {
    url: null,
    anonKey: null,
    marketplaces: {}
  };

  // Find SUPABASE SETTINGS section and extract values
  let inSupabaseSection = false;

  for (let i = 0; i < data.length; i++) {
    const row = data[i];
    const settingName = String(row[0]).trim();
    const parameter = String(row[1]).trim();
    const value = String(row[2]).trim();

    // Check if we're entering the SUPABASE SETTINGS section
    if (settingName === 'SUPABASE SETTINGS') {
      inSupabaseSection = true;
      continue;
    }

    // Check if we've left the section (hit another section header or empty row after content)
    if (inSupabaseSection && settingName && !settingName.includes('Supabase') && !settingName.includes('Marketplace')) {
      if (config.url && config.anonKey) {
        break; // We have what we need
      }
    }

    if (inSupabaseSection) {
      if (settingName === 'Supabase URL' && parameter === 'All') {
        config.url = value;
      } else if (settingName === 'Supabase Anon Key' && parameter === 'All') {
        config.anonKey = value;
      } else if (settingName === 'Marketplace ID' && parameter && value) {
        config.marketplaces[parameter] = value;
      }
    }
  }

  if (!config.url || !config.anonKey) {
    throw new Error('Supabase URL or Anon Key not found in Script Config sheet!');
  }

  Logger.log('Config loaded: URL=' + config.url.substring(0, 30) + '..., Marketplaces=' + Object.keys(config.marketplaces).join(', '));

  return config;
}

// ============================================
// SUPABASE API
// ============================================

/**
 * Makes a GET request to Supabase REST API
 * @param {string} endpoint - The API endpoint
 * @param {Object} params - Query parameters
 * @param {Object} config - Supabase config
 * @returns {Array} JSON response data
 */
function fetchFromSupabase(endpoint, params, config) {
  let url = config.url + endpoint + '?';

  const queryParts = [];
  for (const key in params) {
    queryParts.push(encodeURIComponent(key) + '=' + encodeURIComponent(params[key]));
  }
  url += queryParts.join('&');

  const options = {
    method: 'GET',
    headers: {
      'apikey': config.anonKey,
      'Authorization': 'Bearer ' + config.anonKey,
      'Content-Type': 'application/json'
    },
    muteHttpExceptions: true
  };

  const response = UrlFetchApp.fetch(url, options);
  const responseCode = response.getResponseCode();

  if (responseCode !== 200) {
    Logger.log('Supabase API Error ' + responseCode + ': ' + response.getContentText());
    throw new Error('Supabase API error: ' + responseCode);
  }

  return JSON.parse(response.getContentText());
}

// ============================================
// DATA FETCHING
// ============================================

/**
 * Fetches monthly sales data for a marketplace
 */
function getMonthlyData(marketplaceId, config) {
  return fetchFromSupabase('/rest/v1/sp_monthly_asin_data', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'month,child_asin,units_ordered,ordered_product_sales'
  }, config);
}

/**
 * Fetches weekly sales data for a marketplace
 */
function getWeeklyData(marketplaceId, config) {
  return fetchFromSupabase('/rest/v1/sp_weekly_asin_data', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'week_start,child_asin,units_ordered,ordered_product_sales'
  }, config);
}

/**
 * Fetches daily sales data for a marketplace
 */
function getDailyData(marketplaceId, config) {
  return fetchFromSupabase('/rest/v1/sp_daily_asin_data', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'date,child_asin,units_ordered,ordered_product_sales,sessions'
  }, config);
}

// ============================================
// SHEET REFRESH FUNCTIONS
// ============================================

/**
 * Refreshes the currently active sheet
 * Reads marketplace_id from cell A2
 */
function refreshCurrentSheet() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const sheetName = sheet.getName();

  // Skip if not a Daily sheet
  if (!sheetName.includes('Daily')) {
    SpreadsheetApp.getUi().alert('This sheet does not appear to be a Daily sheet. Please select a Daily sheet (e.g., USA Daily, CA Daily).');
    return;
  }

  // Read marketplace_id from A2
  const marketplaceId = sheet.getRange('A2').getValue();
  const countryCode = sheet.getRange('B2').getValue();

  if (!marketplaceId || marketplaceId.length < 30) {
    SpreadsheetApp.getUi().alert('No valid marketplace ID found in cell A2. Please add the Supabase marketplace UUID to A2.');
    return;
  }

  Logger.log('Refreshing ' + sheetName + ' with marketplace ID: ' + marketplaceId);

  try {
    const config = getSupabaseConfig();

    // Fetch data
    const monthlyData = getMonthlyData(marketplaceId, config);
    const weeklyData = getWeeklyData(marketplaceId, config);

    Logger.log('Fetched ' + monthlyData.length + ' monthly rows, ' + weeklyData.length + ' weekly rows');

    // Create lookup maps
    const monthlyMap = createDataMap(monthlyData, 'month');
    const weeklyMap = createDataMap(weeklyData, 'week_start');

    // Get headers from row 4
    const headerRow = sheet.getRange(4, 1, 1, sheet.getLastColumn()).getValues()[0];

    // Find ASIN column (usually C)
    let asinCol = -1;
    for (let i = 0; i < headerRow.length; i++) {
      if (headerRow[i] && String(headerRow[i]).toLowerCase().includes('asin')) {
        asinCol = i;
        break;
      }
    }

    if (asinCol === -1) {
      SpreadsheetApp.getUi().alert('Could not find ASIN column in row 4');
      return;
    }

    // Get all ASINs from the sheet (starting row 5)
    const lastRow = sheet.getLastRow();
    const asins = sheet.getRange(5, asinCol + 1, lastRow - 4, 1).getValues();

    // Map column headers to dates
    const columnDateMap = mapColumnsToDates(headerRow);

    // Update data for each ASIN
    let updatedCount = 0;
    for (let row = 0; row < asins.length; row++) {
      const asin = asins[row][0];
      if (!asin) continue;

      const sheetRow = row + 5; // Data starts at row 5

      // Update monthly columns
      for (const [col, dateInfo] of Object.entries(columnDateMap)) {
        const colNum = parseInt(col);
        let value = null;

        if (dateInfo.type === 'month') {
          const asinData = monthlyMap[asin];
          if (asinData && asinData[dateInfo.key]) {
            value = dateInfo.field === 'revenue'
              ? asinData[dateInfo.key].revenue
              : asinData[dateInfo.key].units;
          }
        } else if (dateInfo.type === 'week') {
          const asinData = weeklyMap[asin];
          if (asinData && asinData[dateInfo.key]) {
            value = dateInfo.field === 'revenue'
              ? asinData[dateInfo.key].revenue
              : asinData[dateInfo.key].units;
          }
        }

        if (value !== null) {
          sheet.getRange(sheetRow, colNum + 1).setValue(value);
          updatedCount++;
        }
      }
    }

    Logger.log('Updated ' + updatedCount + ' cells');
    SpreadsheetApp.getUi().alert('Refresh complete! Updated ' + updatedCount + ' cells for ' + asins.length + ' ASINs.');

  } catch (e) {
    Logger.log('Error: ' + e.message);
    SpreadsheetApp.getUi().alert('Error refreshing data: ' + e.message);
  }
}

/**
 * Creates a nested map: { asin: { dateKey: { units, revenue } } }
 */
function createDataMap(data, dateField) {
  const map = {};

  for (const row of data) {
    const asin = row.child_asin;
    const dateKey = row[dateField];

    if (!map[asin]) {
      map[asin] = {};
    }

    map[asin][dateKey] = {
      units: row.units_ordered || 0,
      revenue: parseFloat(row.ordered_product_sales) || 0
    };
  }

  return map;
}

/**
 * Maps column indices to date information
 * Parses headers like "Dec 2025 Units", "Jan 2026 Rev", "Wk 51 Units"
 */
function mapColumnsToDates(headers) {
  const map = {};

  const monthNames = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
    'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
    'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12'
  };

  for (let i = 0; i < headers.length; i++) {
    const header = String(headers[i]).toLowerCase().trim();

    // Match monthly: "Dec 2025 Units" or "Dec 2025 Rev"
    const monthMatch = header.match(/^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+(\d{4})\s+(units|rev)/i);
    if (monthMatch) {
      const month = monthNames[monthMatch[1].toLowerCase()];
      const year = monthMatch[2];
      const field = monthMatch[3].toLowerCase() === 'rev' ? 'revenue' : 'units';

      map[i] = {
        type: 'month',
        key: year + '-' + month + '-01', // Format: 2025-12-01
        field: field
      };
      continue;
    }

    // Match weekly: "Wk 51 Units" or "Wk 1 Units"
    const weekMatch = header.match(/^wk\s+(\d+)\s+(units|rev)/i);
    if (weekMatch) {
      const weekNum = parseInt(weekMatch[1]);
      const field = weekMatch[2].toLowerCase() === 'rev' ? 'revenue' : 'units';

      // Convert week number to approximate date (this is simplified)
      // In production, you'd want to match against actual week_start dates from your data
      map[i] = {
        type: 'week',
        key: 'week_' + weekNum, // Will need to match with actual week_start
        field: field
      };
    }
  }

  return map;
}

/**
 * Refreshes all Daily sheets
 */
function refreshAllDailySheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheets = ss.getSheets();

  let refreshedCount = 0;

  for (const sheet of sheets) {
    const name = sheet.getName();
    if (name.includes('Daily')) {
      ss.setActiveSheet(sheet);
      try {
        refreshCurrentSheet();
        refreshedCount++;
      } catch (e) {
        Logger.log('Error refreshing ' + name + ': ' + e.message);
      }
    }
  }

  SpreadsheetApp.getUi().alert('Refreshed ' + refreshedCount + ' Daily sheets!');
}

// ============================================
// MENU
// ============================================

/**
 * Creates custom menu when spreadsheet opens
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Supabase Data')
    .addItem('Refresh Current Sheet', 'refreshCurrentSheet')
    .addItem('Refresh All Daily Sheets', 'refreshAllDailySheets')
    .addSeparator()
    .addItem('Test Connection', 'testConnection')
    .addToUi();
}

/**
 * Tests the Supabase connection
 */
function testConnection() {
  try {
    const config = getSupabaseConfig();

    // Try a simple query
    const data = fetchFromSupabase('/rest/v1/sp_monthly_asin_data', {
      'select': 'month,child_asin',
      'limit': '1'
    }, config);

    SpreadsheetApp.getUi().alert('Connection successful! Found ' + data.length + ' test record(s).');
  } catch (e) {
    SpreadsheetApp.getUi().alert('Connection failed: ' + e.message);
  }
}
