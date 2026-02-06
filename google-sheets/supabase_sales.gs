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
    .addSubMenu(ui.createMenu('Daily Sheets')
      .addItem('Refresh Current Sheet', 'refreshCurrentDailySheet')
      .addItem('Refresh TESTING Sheet', 'refreshTestingSheet'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Weekly/Monthly Data')
      .addItem('Refresh SP Data USA', 'refreshSPDataUSA')
      .addItem('Refresh SP Data CA', 'refreshSPDataCA')
      .addItem('Refresh SP Data MX', 'refreshSPDataMX'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Debug')
      .addItem('Check Sheet Dates', 'debugTestingSheetDates')
      .addItem('Check Sheet ASINs', 'debugTestingSheetASINs'))
    .addSeparator()
    .addItem('Show Formula Examples', 'showFormulaExamples')
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
// DAILY SHEET REFRESH - AUTO-DETECT COLUMNS
// ============================================

/**
 * Refreshes the currently active sheet with daily data from Supabase
 * Auto-detects date columns - NO HARDCODING
 *
 * Sheet structure expected:
 * - A2: Marketplace UUID
 * - B2: Country code (for display only)
 * - Row 4: Date headers (anywhere - script auto-detects)
 * - Column C: ASINs (C5 onwards, stops at first empty)
 */
function refreshCurrentDailySheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet();

  refreshDailySheet(sheet);
}

/**
 * Refreshes the TESTING sheet specifically
 */
function refreshTestingSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('TESTING');

  if (!sheet) {
    SpreadsheetApp.getUi().alert('TESTING sheet not found!');
    return;
  }

  refreshDailySheet(sheet);
}

/**
 * Core function to refresh any daily sheet with units_ordered data
 * Auto-detects date columns by scanning row 4 for date values
 *
 * @param {Sheet} sheet - The sheet to refresh
 */
function refreshDailySheet(sheet) {
  try {
    const config = getSupabaseConfig();

    // Step 1: Get marketplace UUID from A2
    const marketplaceId = sheet.getRange('A2').getValue();
    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert('Marketplace UUID not found in A2!');
      return;
    }
    Logger.log('Marketplace ID: ' + marketplaceId);

    // Step 2: Get ASINs from column C (C5 onwards, stop at first empty)
    const asinRange = sheet.getRange('C5:C500'); // Read up to 500 rows
    const asinValues = asinRange.getValues();
    const asins = [];

    for (let i = 0; i < asinValues.length; i++) {
      const asin = String(asinValues[i][0]).trim();
      if (asin && asin.length > 0 && asin !== '' && asin !== 'undefined') {
        asins.push(asin);
      } else {
        // Stop at first empty cell
        break;
      }
    }
    Logger.log('Found ' + asins.length + ' ASINs');

    if (asins.length === 0) {
      SpreadsheetApp.getUi().alert('No ASINs found in column C!');
      return;
    }

    // Step 3: AUTO-DETECT date columns by scanning row 4
    // Start from column F (6) and scan right to find date values
    const dateColumns = autoDetectDateColumns(sheet, 4, 6, 150); // Row 4, start col F, max 150 cols
    Logger.log('Auto-detected ' + dateColumns.length + ' date columns');

    if (dateColumns.length === 0) {
      SpreadsheetApp.getUi().alert('No dates found in row 4! Make sure you have date values in the header row.');
      return;
    }

    // Get the first date column for writing data
    const firstDateCol = dateColumns[0].col;
    const dateValues = sheet.getRange(4, firstDateCol, 1, dateColumns.length).getValues()[0];

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
        // Return 0 instead of blank when no data
        const units = (lookup[asin] && lookup[asin][date] !== undefined) ? lookup[asin][date] : 0;
        rowData.push(units);
      }

      output.push(rowData);
    }

    // Step 8: Write to sheet
    // Data starts at row 5, at the first detected date column
    const outputRange = sheet.getRange(5, firstDateCol, numRows, numCols);
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

// ============================================
// AUTO-DETECT DATE COLUMNS
// ============================================

/**
 * Auto-detects date columns in a row by scanning for date values
 * Returns array of {col: column number, date: 'YYYY-MM-DD'}
 *
 * @param {Sheet} sheet - The sheet to scan
 * @param {number} row - The row number to scan (e.g., 4)
 * @param {number} startCol - Column to start scanning from (e.g., 6 for F)
 * @param {number} maxCols - Maximum columns to scan
 * @returns {Array} Array of {col, date} objects
 */
function autoDetectDateColumns(sheet, row, startCol, maxCols) {
  const range = sheet.getRange(row, startCol, 1, maxCols);
  const values = range.getValues()[0];
  const dateColumns = [];

  let foundFirstDate = false;
  let consecutiveEmpty = 0;

  for (let i = 0; i < values.length; i++) {
    const cellValue = values[i];
    const colNum = startCol + i;

    if (cellValue) {
      const dateStr = parseCellAsDate(cellValue);

      if (dateStr) {
        foundFirstDate = true;
        consecutiveEmpty = 0;
        dateColumns.push({
          col: colNum,
          date: dateStr
        });
      } else if (foundFirstDate) {
        // Non-date value after we found dates - might be end of date section
        consecutiveEmpty++;
        if (consecutiveEmpty > 5) break; // Stop after 5 non-date cells
      }
    } else if (foundFirstDate) {
      consecutiveEmpty++;
      if (consecutiveEmpty > 5) break;
    }
  }

  return dateColumns;
}

/**
 * Parses a cell value as a date and returns YYYY-MM-DD string
 * Handles: Date objects, numbers (Excel serial), strings (d/m format)
 *
 * @param {*} cellValue - The cell value to parse
 * @returns {string|null} Date string in YYYY-MM-DD format, or null if not a date
 */
function parseCellAsDate(cellValue) {
  if (!cellValue) return null;

  // Handle Date objects from Google Sheets
  if (cellValue instanceof Date) {
    // Check if it's a valid date (not NaN)
    if (isNaN(cellValue.getTime())) return null;

    const year = cellValue.getFullYear();
    const month = String(cellValue.getMonth() + 1).padStart(2, '0');
    const day = String(cellValue.getDate()).padStart(2, '0');

    // Sanity check - year should be reasonable (1900-2100)
    if (year < 1900 || year > 2100) return null;

    return year + '-' + month + '-' + day;
  }

  // Handle number (Excel serial date)
  if (typeof cellValue === 'number') {
    // Excel serial dates are typically > 1 and < 100000
    if (cellValue < 1 || cellValue > 100000) return null;

    const jsDate = new Date((cellValue - 25569) * 86400 * 1000);
    if (isNaN(jsDate.getTime())) return null;

    const year = jsDate.getFullYear();
    const month = String(jsDate.getMonth() + 1).padStart(2, '0');
    const day = String(jsDate.getDate()).padStart(2, '0');

    if (year < 1900 || year > 2100) return null;

    return year + '-' + month + '-' + day;
  }

  // Handle string format like "4/2" (d/m format) or "2/4" (m/d format)
  if (typeof cellValue === 'string') {
    const parts = cellValue.split('/');
    if (parts.length === 2) {
      const part1 = parseInt(parts[0], 10);
      const part2 = parseInt(parts[1], 10);

      if (isNaN(part1) || isNaN(part2)) return null;

      // Assume d/m format (common in non-US locales)
      // If first number > 12, it must be day
      let day, month;
      if (part1 > 12) {
        day = part1;
        month = part2;
      } else if (part2 > 12) {
        month = part1;
        day = part2;
      } else {
        // Both could be day or month - assume d/m
        day = part1;
        month = part2;
      }

      if (day < 1 || day > 31 || month < 1 || month > 12) return null;

      // Use current year
      const year = new Date().getFullYear();
      return year + '-' + String(month).padStart(2, '0') + '-' + String(day).padStart(2, '0');
    }
  }

  return null;
}

// ============================================
// SP DATA SHEET - WEEKLY/MONTHLY
// ============================================

/**
 * Creates or gets the SP Data sheet for a marketplace
 * @param {string} country - Country code (USA, CA, MX)
 * @returns {Sheet} The SP Data sheet
 */
function getOrCreateSPDataSheet(country) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetName = 'SP Data ' + country;

  let sheet = ss.getSheetByName(sheetName);

  if (!sheet) {
    sheet = ss.insertSheet(sheetName);

    // Add headers
    const headers = [
      'data_type', 'child_asin', 'period',
      'units_ordered', 'units_ordered_b2b',
      'ordered_product_sales', 'ordered_product_sales_b2b',
      'sessions', 'page_views',
      'avg_buy_box_percentage', 'avg_conversion_rate'
    ];
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    sheet.setFrozenRows(1);

    Logger.log('Created new sheet: ' + sheetName);
  }

  return sheet;
}

/**
 * Fetches monthly data from materialized view
 */
function getMonthlyDataFromView(marketplaceId, config) {
  const url = config.url + '/rest/v1/sp_monthly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=month,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    '&order=month.desc,child_asin.asc';

  Logger.log('Fetching monthly data from materialized view');

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

/**
 * Fetches weekly data from materialized view
 */
function getWeeklyDataFromView(marketplaceId, config) {
  const url = config.url + '/rest/v1/sp_weekly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=week_start,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    '&order=week_start.desc,child_asin.asc';

  Logger.log('Fetching weekly data from materialized view');

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

/**
 * Refreshes SP Data sheet for USA with monthly and weekly data
 */
function refreshSPDataUSA() {
  refreshSPData('USA', 'US');
}

/**
 * Refreshes SP Data sheet for Canada with monthly and weekly data
 */
function refreshSPDataCA() {
  refreshSPData('CA', 'CA');
}

/**
 * Refreshes SP Data sheet for Mexico with monthly and weekly data
 */
function refreshSPDataMX() {
  refreshSPData('MX', 'MX');
}

/**
 * Core function to refresh SP Data sheet for any country
 * @param {string} country - Country name for sheet (USA, CA, MX)
 * @param {string} configKey - Key in config.marketplaces (US, CA, MX)
 */
/**
 * Shows formula examples for pulling data from SP Data sheets
 */
function showFormulaExamples() {
  const examples = `
FORMULA EXAMPLES FOR SP DATA SHEETS

These formulas pull data from the SP Data sheets into your display sheets.

═══════════════════════════════════════════════════════════════
SINGLE CELL FORMULAS (copy to each cell)
═══════════════════════════════════════════════════════════════

Monthly Units (USA):
=IFERROR(SUMIFS('SP Data USA'!$D:$D, 'SP Data USA'!$A:$A, "monthly", 'SP Data USA'!$B:$B, $C5, 'SP Data USA'!$C:$C, TEXT(BT$4,"yyyy-mm-dd")), 0)

Monthly Revenue (USA):
=IFERROR(SUMIFS('SP Data USA'!$F:$F, 'SP Data USA'!$A:$A, "monthly", 'SP Data USA'!$B:$B, $C5, 'SP Data USA'!$C:$C, TEXT(BT$4,"yyyy-mm-dd")), 0)

Weekly Units (USA):
=IFERROR(SUMIFS('SP Data USA'!$D:$D, 'SP Data USA'!$A:$A, "weekly", 'SP Data USA'!$B:$B, $C5, 'SP Data USA'!$C:$C, TEXT(BT$4,"yyyy-mm-dd")), 0)

═══════════════════════════════════════════════════════════════
ARRAY FORMULA (one formula fills entire grid)
═══════════════════════════════════════════════════════════════

Put this in the first data cell (e.g., BT5):

=BYROW(C5:C270, LAMBDA(asin,
  BYCOL(BT4:CZ4, LAMBDA(period,
    IFERROR(SUMIFS('SP Data USA'!$D:$D,
      'SP Data USA'!$A:$A, "monthly",
      'SP Data USA'!$B:$B, asin,
      'SP Data USA'!$C:$C, TEXT(period,"yyyy-mm-dd")), 0)
  ))
))

═══════════════════════════════════════════════════════════════
SP DATA COLUMNS REFERENCE
═══════════════════════════════════════════════════════════════

A = data_type (monthly/weekly)
B = child_asin
C = period (date)
D = units_ordered
E = units_ordered_b2b
F = ordered_product_sales
G = ordered_product_sales_b2b
H = sessions
I = page_views
J = avg_buy_box_percentage
K = avg_conversion_rate
`;

  SpreadsheetApp.getUi().alert(examples);
}

/**
 * Core function to refresh SP Data sheet for any country
 * @param {string} country - Country name for sheet (USA, CA, MX)
 * @param {string} configKey - Key in config.marketplaces (US, CA, MX)
 */
function refreshSPData(country, configKey) {
  try {
    const config = getSupabaseConfig();
    const marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert(country + ' marketplace ID not found in Script Config!');
      return;
    }

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' data from Supabase...', 'Please wait', 60);

    // Fetch monthly and weekly data
    const monthlyData = getMonthlyDataFromView(marketplaceId, config);
    const weeklyData = getWeeklyDataFromView(marketplaceId, config);

    Logger.log('Fetched ' + monthlyData.length + ' monthly rows');
    Logger.log('Fetched ' + weeklyData.length + ' weekly rows');

    // Get or create SP Data sheet
    const sheet = getOrCreateSPDataSheet(country);

    // Clear existing data (keep headers)
    const lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, 11).clear();
    }

    // Build output array
    const output = [];

    // Add monthly rows
    for (const row of monthlyData) {
      output.push([
        'monthly',
        row.child_asin,
        row.month, // Already in YYYY-MM-DD format
        row.units_ordered || 0,
        row.units_ordered_b2b || 0,
        row.ordered_product_sales || 0,
        row.ordered_product_sales_b2b || 0,
        row.sessions || 0,
        row.page_views || 0,
        row.avg_buy_box_percentage || 0,
        row.avg_conversion_rate || 0
      ]);
    }

    // Add weekly rows
    for (const row of weeklyData) {
      output.push([
        'weekly',
        row.child_asin,
        row.week_start, // Already in YYYY-MM-DD format
        row.units_ordered || 0,
        row.units_ordered_b2b || 0,
        row.ordered_product_sales || 0,
        row.ordered_product_sales_b2b || 0,
        row.sessions || 0,
        row.page_views || 0,
        row.avg_buy_box_percentage || 0,
        row.avg_conversion_rate || 0
      ]);
    }

    // Write to sheet
    if (output.length > 0) {
      sheet.getRange(2, 1, output.length, 11).setValues(output);
    }

    const summary = 'SP Data ' + country + ' refreshed!\n\n' +
      'Monthly rows: ' + monthlyData.length + '\n' +
      'Weekly rows: ' + weeklyData.length + '\n' +
      'Total rows: ' + output.length;

    Logger.log(summary);
    SpreadsheetApp.getUi().alert(summary);

  } catch (e) {
    Logger.log('Error: ' + e.message);
    Logger.log(e.stack);
    SpreadsheetApp.getUi().alert('Error: ' + e.message);
  }
}
