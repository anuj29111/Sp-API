/**
 * Supabase Sales Data Integration - DAILY DATA FOCUS
 * Pulls daily sales data from Supabase and displays in reverse chronological order.
 * Smart refresh: Today/recent data refreshes, older data stays cached.
 *
 * All configuration is read from the "Script Config" sheet - NO HARDCODING.
 */

// ============================================
// CONFIGURATION
// ============================================

/**
 * Reads Supabase configuration from the Script Config sheet
 */
function getSupabaseConfig() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const configSheet = ss.getSheetByName('Script Config');

  if (!configSheet) {
    throw new Error('Script Config sheet not found!');
  }

  const data = configSheet.getDataRange().getValues();

  const config = {
    url: null,
    anonKey: null,
    marketplaces: {}
  };

  let inSupabaseSection = false;

  for (let i = 0; i < data.length; i++) {
    const row = data[i];
    const settingName = String(row[0]).trim();
    const parameter = String(row[1]).trim();
    const value = String(row[2]).trim();

    if (settingName === 'SUPABASE SETTINGS') {
      inSupabaseSection = true;
      continue;
    }

    if (inSupabaseSection && settingName && !settingName.includes('Supabase') && !settingName.includes('Marketplace')) {
      if (config.url && config.anonKey) break;
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

  Logger.log('Config loaded. Marketplaces: ' + Object.keys(config.marketplaces).join(', '));
  return config;
}

// ============================================
// SUPABASE API
// ============================================

/**
 * Makes a GET request to Supabase REST API
 */
function fetchFromSupabase(endpoint, params, config) {
  let url = config.url + endpoint + '?';

  const queryParts = [];
  for (const key in params) {
    queryParts.push(encodeURIComponent(key) + '=' + encodeURIComponent(params[key]));
  }
  url += queryParts.join('&');

  Logger.log('Fetching: ' + url.substring(0, 100) + '...');

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
// DATA FETCHING - DAILY FOCUS
// ============================================

/**
 * Fetches daily data for a date range
 * @param {string} marketplaceId - UUID of marketplace
 * @param {string} startDate - Start date (YYYY-MM-DD)
 * @param {string} endDate - End date (YYYY-MM-DD)
 * @param {Object} config - Supabase config
 */
function getDailyDataForRange(marketplaceId, startDate, endDate, config) {
  return fetchFromSupabase('/rest/v1/sp_daily_asin_data', {
    'marketplace_id': 'eq.' + marketplaceId,
    'date': 'gte.' + startDate,
    'date': 'lte.' + endDate,
    'select': 'date,child_asin,parent_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,buy_box_percentage,unit_session_percentage',
    'order': 'date.desc,child_asin.asc'
  }, config);
}

/**
 * Fetches daily data with proper date filtering using AND logic
 */
function getDailyDataBetweenDates(marketplaceId, startDate, endDate, config) {
  // Supabase REST API needs separate params for AND conditions on same column
  // We use the 'and' filter syntax
  const url = config.url + '/rest/v1/sp_daily_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&date=gte.' + startDate +
    '&date=lte.' + endDate +
    '&select=date,child_asin,parent_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,buy_box_percentage,unit_session_percentage' +
    '&order=date.desc,child_asin.asc';

  Logger.log('Fetching daily data: ' + startDate + ' to ' + endDate);

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
    Logger.log('API Error ' + responseCode + ': ' + response.getContentText());
    throw new Error('Supabase API error: ' + responseCode);
  }

  return JSON.parse(response.getContentText());
}

// ============================================
// SIMPLE TEST - FETCH DAILY DATA
// ============================================

/**
 * TEST FUNCTION: Fetch USA daily data for Feb 1-5, 2026
 * Run this to verify the data fetch works
 */
function testFetchDailyUSA() {
  try {
    const config = getSupabaseConfig();
    const usaId = config.marketplaces['US'] || config.marketplaces['USA'];

    if (!usaId) {
      SpreadsheetApp.getUi().alert('USA marketplace ID not found in Script Config!');
      return;
    }

    Logger.log('USA Marketplace ID: ' + usaId);

    // Fetch Feb 1-5, 2026
    const data = getDailyDataBetweenDates(usaId, '2026-02-01', '2026-02-05', config);

    Logger.log('Fetched ' + data.length + ' rows');

    // Count unique dates and ASINs
    const dates = new Set();
    const asins = new Set();
    let totalUnits = 0;
    let totalRevenue = 0;

    for (const row of data) {
      dates.add(row.date);
      asins.add(row.child_asin);
      totalUnits += row.units_ordered || 0;
      totalRevenue += parseFloat(row.ordered_product_sales) || 0;
    }

    const summary = 'Data fetched successfully!\n\n' +
      'Rows: ' + data.length + '\n' +
      'Dates: ' + Array.from(dates).sort().reverse().join(', ') + '\n' +
      'Unique ASINs: ' + asins.size + '\n' +
      'Total Units: ' + totalUnits + '\n' +
      'Total Revenue: $' + totalRevenue.toFixed(2);

    Logger.log(summary);
    SpreadsheetApp.getUi().alert(summary);

    // Log first 5 rows as sample
    Logger.log('Sample data (first 5 rows):');
    for (let i = 0; i < Math.min(5, data.length); i++) {
      Logger.log(JSON.stringify(data[i]));
    }

  } catch (e) {
    Logger.log('Error: ' + e.message);
    SpreadsheetApp.getUi().alert('Error: ' + e.message);
  }
}

/**
 * TEST FUNCTION: Write daily data to a test sheet
 * Creates a simple output showing daily data in reverse date order
 */
function testWriteDailyData() {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const config = getSupabaseConfig();
    const usaId = config.marketplaces['US'] || config.marketplaces['USA'];

    if (!usaId) {
      SpreadsheetApp.getUi().alert('USA marketplace ID not found!');
      return;
    }

    // Fetch data
    const data = getDailyDataBetweenDates(usaId, '2026-02-01', '2026-02-05', config);
    Logger.log('Fetched ' + data.length + ' rows');

    // Get or create test sheet
    let testSheet = ss.getSheetByName('Daily Test Output');
    if (!testSheet) {
      testSheet = ss.insertSheet('Daily Test Output');
    } else {
      testSheet.clear();
    }

    // Get unique dates (sorted descending - most recent first)
    const dates = [...new Set(data.map(r => r.date))].sort().reverse();
    Logger.log('Dates (reverse order): ' + dates.join(', '));

    // Get unique ASINs
    const asins = [...new Set(data.map(r => r.child_asin))].sort();

    // Create data lookup: { asin: { date: { units, revenue } } }
    const lookup = {};
    for (const row of data) {
      if (!lookup[row.child_asin]) lookup[row.child_asin] = {};
      lookup[row.child_asin][row.date] = {
        units: row.units_ordered || 0,
        revenue: parseFloat(row.ordered_product_sales) || 0
      };
    }

    // Build output array
    const output = [];

    // Header row
    const header = ['ASIN'];
    for (const date of dates) {
      header.push(date + ' Units');
      header.push(date + ' Rev');
    }
    output.push(header);

    // Data rows
    for (const asin of asins) {
      const row = [asin];
      for (const date of dates) {
        const d = lookup[asin] && lookup[asin][date];
        row.push(d ? d.units : 0);
        row.push(d ? d.revenue : 0);
      }
      output.push(row);
    }

    // Write to sheet
    testSheet.getRange(1, 1, output.length, output[0].length).setValues(output);

    // Format header
    testSheet.getRange(1, 1, 1, output[0].length).setFontWeight('bold');
    testSheet.setFrozenRows(1);
    testSheet.setFrozenColumns(1);

    // Auto-resize columns
    for (let i = 1; i <= output[0].length; i++) {
      testSheet.autoResizeColumn(i);
    }

    SpreadsheetApp.getUi().alert('Done! Created "Daily Test Output" sheet with ' +
      dates.length + ' dates and ' + asins.size + ' ASINs.');

  } catch (e) {
    Logger.log('Error: ' + e.message);
    SpreadsheetApp.getUi().alert('Error: ' + e.message);
  }
}

// ============================================
// LEGACY FUNCTIONS (for reference)
// ============================================

function getMonthlyData(marketplaceId, config) {
  return fetchFromSupabase('/rest/v1/sp_monthly_asin_data', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'month,child_asin,units_ordered,ordered_product_sales'
  }, config);
}

function getWeeklyData(marketplaceId, config) {
  return fetchFromSupabase('/rest/v1/sp_weekly_asin_data', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'week_start,iso_year,iso_week_number,child_asin,units_ordered,ordered_product_sales'
  }, config);
}

// ============================================
// MENU
// ============================================

function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('Supabase Data')
    .addItem('Test Connection', 'testConnection')
    .addSeparator()
    .addSubMenu(ui.createMenu('TESTING Sheet')
      .addItem('Refresh TESTING Sheet', 'refreshTestingSheet')
      .addItem('Debug: Check Dates', 'debugTestingSheetDates')
      .addItem('Debug: Check ASINs', 'debugTestingSheetASINs'))
    .addSeparator()
    .addItem('Test Fetch Daily USA (Feb 1-5)', 'testFetchDailyUSA')
    .addItem('Test Write Daily Data', 'testWriteDailyData')
    .addToUi();
}

function testConnection() {
  try {
    const config = getSupabaseConfig();

    // Try a simple query
    const data = fetchFromSupabase('/rest/v1/sp_daily_asin_data', {
      'select': 'date,child_asin',
      'limit': '1'
    }, config);

    const marketplaces = Object.keys(config.marketplaces).join(', ');
    SpreadsheetApp.getUi().alert('Connection successful!\n\nConfigured marketplaces: ' + marketplaces);
  } catch (e) {
    SpreadsheetApp.getUi().alert('Connection failed: ' + e.message);
  }
}

/**
 * Placeholder for future sheet refresh functionality
 */
function refreshCurrentSheet() {
  SpreadsheetApp.getUi().alert('Full sheet refresh coming soon!\n\nFor now, use "Test Write Daily Data" to test the data fetch.');
}

// ============================================
// TESTING SHEET - SIMPLE REFRESH
// ============================================

/**
 * Refreshes the TESTING sheet with units_ordered data from Supabase
 *
 * Sheet structure:
 * - A2: Marketplace UUID
 * - B2: Country code (for display only)
 * - Row 4: Date headers starting at column BT (column 72), in d/m format (e.g., 4/2 = Feb 4)
 * - Column C: ASINs (C5:C270)
 * - Data starts at BT5
 */
function refreshTestingSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('TESTING');

  if (!sheet) {
    SpreadsheetApp.getUi().alert('TESTING sheet not found!');
    return;
  }

  try {
    const config = getSupabaseConfig();

    // Step 1: Get marketplace UUID from A2
    const marketplaceId = sheet.getRange('A2').getValue();
    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert('Marketplace UUID not found in A2!');
      return;
    }
    Logger.log('Marketplace ID: ' + marketplaceId);

    // Step 2: Get ASINs from column C (C5:C270)
    const asinRange = sheet.getRange('C5:C270');
    const asinValues = asinRange.getValues();
    const asins = [];
    const asinRowMap = {}; // Map ASIN to row index (0-based from C5)

    for (let i = 0; i < asinValues.length; i++) {
      const asin = String(asinValues[i][0]).trim();
      if (asin && asin.length > 0 && asin !== '' && asin !== 'undefined') {
        asins.push(asin);
        asinRowMap[asin] = i;
      }
    }
    Logger.log('Found ' + asins.length + ' ASINs');

    if (asins.length === 0) {
      SpreadsheetApp.getUi().alert('No ASINs found in column C!');
      return;
    }

    // Step 3: Get dates from row 4, starting at column BT (column 72)
    // Read a range of date columns (let's check BT4:CZ4 which is columns 72 to 104)
    const DATE_START_COL = 72; // Column BT
    const dateHeaderRange = sheet.getRange(4, DATE_START_COL, 1, 40); // Read 40 columns of dates
    const dateValues = dateHeaderRange.getValues()[0];

    const dateColumns = []; // Array of {col: column number, date: 'YYYY-MM-DD'}

    for (let i = 0; i < dateValues.length; i++) {
      const cellValue = dateValues[i];
      if (cellValue) {
        let dateStr = null;

        // Handle Date objects from Google Sheets
        if (cellValue instanceof Date) {
          const year = cellValue.getFullYear();
          const month = String(cellValue.getMonth() + 1).padStart(2, '0');
          const day = String(cellValue.getDate()).padStart(2, '0');
          dateStr = year + '-' + month + '-' + day;
        }
        // Handle string format like "4/2" (d/m format)
        else if (typeof cellValue === 'string') {
          const parts = cellValue.split('/');
          if (parts.length === 2) {
            const day = parts[0].padStart(2, '0');
            const month = parts[1].padStart(2, '0');
            // Assume 2026 for now
            dateStr = '2026-' + month + '-' + day;
          }
        }
        // Handle number (Excel serial date)
        else if (typeof cellValue === 'number') {
          const jsDate = new Date((cellValue - 25569) * 86400 * 1000);
          const year = jsDate.getFullYear();
          const month = String(jsDate.getMonth() + 1).padStart(2, '0');
          const day = String(jsDate.getDate()).padStart(2, '0');
          dateStr = year + '-' + month + '-' + day;
        }

        if (dateStr) {
          dateColumns.push({
            col: DATE_START_COL + i,
            date: dateStr
          });
          Logger.log('Column ' + (DATE_START_COL + i) + ' = ' + dateStr);
        }
      }
    }

    Logger.log('Found ' + dateColumns.length + ' date columns');

    if (dateColumns.length === 0) {
      SpreadsheetApp.getUi().alert('No dates found in row 4 starting at column BT!');
      return;
    }

    // Step 4: Determine date range for API call
    const allDates = dateColumns.map(d => d.date).sort();
    const minDate = allDates[0];
    const maxDate = allDates[allDates.length - 1];
    Logger.log('Date range: ' + minDate + ' to ' + maxDate);

    // Step 5: Fetch ALL data from Supabase in ONE call
    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching data from Supabase...', 'Please wait', 30);

    const data = getDailyDataBetweenDates(marketplaceId, minDate, maxDate, config);
    Logger.log('Fetched ' + data.length + ' rows from Supabase');

    // Step 6: Build lookup: { asin: { date: units_ordered } }
    const lookup = {};
    for (const row of data) {
      const asin = row.child_asin;
      const date = row.date;
      const units = row.units_ordered || 0;

      if (!lookup[asin]) lookup[asin] = {};
      lookup[asin][date] = units;
    }

    // Step 7: Build output array matching sheet structure
    const numRows = asins.length;
    const numCols = dateColumns.length;
    const output = [];

    for (let r = 0; r < numRows; r++) {
      const asin = asins[r];
      const rowData = [];

      for (let c = 0; c < numCols; c++) {
        const date = dateColumns[c].date;
        const units = (lookup[asin] && lookup[asin][date]) ? lookup[asin][date] : '';
        rowData.push(units);
      }

      output.push(rowData);
    }

    // Step 8: Write to sheet
    // Data starts at row 5, column BT (72)
    const outputRange = sheet.getRange(5, DATE_START_COL, numRows, numCols);
    outputRange.setValues(output);

    // Count non-empty cells
    let filledCells = 0;
    for (const row of output) {
      for (const cell of row) {
        if (cell !== '' && cell !== 0) filledCells++;
      }
    }

    const summary = 'TESTING sheet refreshed!\n\n' +
      'ASINs: ' + asins.length + '\n' +
      'Date columns: ' + dateColumns.length + '\n' +
      'Date range: ' + minDate + ' to ' + maxDate + '\n' +
      'Supabase rows: ' + data.length + '\n' +
      'Cells with data: ' + filledCells;

    Logger.log(summary);
    SpreadsheetApp.getUi().alert(summary);

  } catch (e) {
    Logger.log('Error: ' + e.message);
    Logger.log(e.stack);
    SpreadsheetApp.getUi().alert('Error: ' + e.message);
  }
}

/**
 * Debug function to check what's in the date header row
 */
function debugTestingSheetDates() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('TESTING');

  if (!sheet) {
    SpreadsheetApp.getUi().alert('TESTING sheet not found!');
    return;
  }

  // Check row 4, columns BT onwards (column 72)
  const range = sheet.getRange(4, 72, 1, 10); // BT4:CC4
  const values = range.getValues()[0];

  let debug = 'Date header debug (Row 4, starting BT):\n\n';

  for (let i = 0; i < values.length; i++) {
    const val = values[i];
    const colLetter = columnToLetter(72 + i);
    debug += colLetter + '4: ';

    if (val instanceof Date) {
      debug += 'Date object: ' + val.toISOString().split('T')[0];
    } else if (typeof val === 'number') {
      debug += 'Number: ' + val;
    } else if (typeof val === 'string') {
      debug += 'String: "' + val + '"';
    } else {
      debug += 'Empty/null';
    }
    debug += '\n';
  }

  Logger.log(debug);
  SpreadsheetApp.getUi().alert(debug);
}

/**
 * Debug function to check ASINs in column C
 */
function debugTestingSheetASINs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('TESTING');

  if (!sheet) {
    SpreadsheetApp.getUi().alert('TESTING sheet not found!');
    return;
  }

  const range = sheet.getRange('C5:C15'); // First 10 ASINs
  const values = range.getValues();

  let debug = 'ASIN debug (Column C, rows 5-14):\n\n';

  for (let i = 0; i < values.length; i++) {
    const val = values[i][0];
    debug += 'C' + (5 + i) + ': ';

    if (val && String(val).trim().length > 0) {
      debug += '"' + String(val).trim() + '"';
    } else {
      debug += '(empty)';
    }
    debug += '\n';
  }

  // Also check A2 for marketplace UUID
  const marketplaceId = sheet.getRange('A2').getValue();
  debug += '\nA2 (Marketplace UUID): "' + marketplaceId + '"';

  Logger.log(debug);
  SpreadsheetApp.getUi().alert(debug);
}

/**
 * Convert column number to letter(s)
 */
function columnToLetter(column) {
  let temp, letter = '';
  while (column > 0) {
    temp = (column - 1) % 26;
    letter = String.fromCharCode(temp + 65) + letter;
    column = (column - temp - 1) / 26;
  }
  return letter;
}
