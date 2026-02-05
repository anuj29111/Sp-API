/**
 * MINIMAL TEST - Supabase Connection for Google Sheets
 *
 * Purpose: Prove Supabase API connection works before adding complexity
 *
 * Usage:
 * 1. Create a sheet called "Test Supabase" with:
 *    - A2: Marketplace UUID (e.g., f47ac10b-58cc-4372-a567-0e02b2c3d479)
 *    - B2: Country code (e.g., US)
 *    - Row 4: Headers (A4: "ASIN", B4: "2025-12", C4: "2026-01", D4: "2026-02")
 *    - Row 5+: ASINs in column A
 * 2. Run "Supabase > Test Connection" to verify API access
 * 3. Run "Supabase > Refresh Data" to populate cells
 *
 * Note: This is a TEST script with hardcoded config.
 * For production, use supabase_sales.gs which reads config from Script Config sheet.
 */

// ============================================
// CONFIGURATION - Hardcoded for testing only
// In production, these come from Script Config sheet
// ============================================
const SUPABASE_URL = 'https://yawaopfqkkvdqtsagmng.supabase.co';
const SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inlhd2FvcGZxa2t2ZHF0c2FnbW5nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjkxNjI1MDIsImV4cCI6MjA4NDczODUwMn0.XU2q39Ps6_DSuZVsdni32iXIW48-coeZZ13ojvz2LdQ';

// ============================================
// MENU
// ============================================

/**
 * Creates custom menu when spreadsheet opens
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Supabase')
    .addItem('Test Connection', 'testConnection')
    .addItem('Refresh Data', 'refreshData')
    .addSeparator()
    .addItem('Show Sample ASINs', 'showSampleAsins')
    .addToUi();
}

// ============================================
// TEST CONNECTION
// ============================================

/**
 * Tests connectivity to Supabase REST API
 */
function testConnection() {
  try {
    const url = SUPABASE_URL + '/rest/v1/sp_monthly_asin_data?select=month,child_asin&limit=1';

    const response = UrlFetchApp.fetch(url, {
      method: 'GET',
      headers: {
        'apikey': SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY,
        'Content-Type': 'application/json'
      },
      muteHttpExceptions: true
    });

    const code = response.getResponseCode();
    const body = response.getContentText();

    if (code === 200) {
      const data = JSON.parse(body);
      SpreadsheetApp.getUi().alert(
        'SUCCESS! Connection works.\n\n' +
        'Response code: ' + code + '\n' +
        'Sample data: ' + JSON.stringify(data)
      );
    } else {
      SpreadsheetApp.getUi().alert(
        'API returned error.\n\n' +
        'Response code: ' + code + '\n' +
        'Body: ' + body
      );
    }
  } catch (e) {
    SpreadsheetApp.getUi().alert('FAILED: ' + e.message);
    Logger.log('Error: ' + e.message);
  }
}

// ============================================
// REFRESH DATA
// ============================================

/**
 * Fetches monthly sales data from Supabase and populates the sheet
 * Reads marketplace UUID from A2
 * Matches ASINs in column A with headers in row 4
 */
function refreshData() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const sheetName = sheet.getName();

  // Read marketplace ID from A2
  const marketplaceId = String(sheet.getRange('A2').getValue()).trim();
  const countryCode = String(sheet.getRange('B2').getValue()).trim();

  // Validate marketplace ID
  if (!marketplaceId || marketplaceId.length < 30) {
    SpreadsheetApp.getUi().alert(
      'Invalid marketplace UUID in cell A2.\n\n' +
      'Please enter a valid Supabase marketplace UUID.\n\n' +
      'Example for USA: f47ac10b-58cc-4372-a567-0e02b2c3d479'
    );
    return;
  }

  Logger.log('Refreshing sheet: ' + sheetName);
  Logger.log('Marketplace ID: ' + marketplaceId);
  Logger.log('Country: ' + countryCode);

  try {
    // Fetch monthly data from Supabase
    const data = fetchMonthlyData(marketplaceId);
    Logger.log('Fetched ' + data.length + ' rows from Supabase');

    if (data.length === 0) {
      SpreadsheetApp.getUi().alert(
        'No data found for this marketplace.\n\n' +
        'Marketplace ID: ' + marketplaceId + '\n' +
        'Please verify the UUID is correct.'
      );
      return;
    }

    // Build lookup map: { asin: { monthKey: units } }
    const lookup = buildLookupMap(data);
    Logger.log('Built lookup for ' + Object.keys(lookup).length + ' unique ASINs');

    // Get headers from row 4 (starting from column B)
    const lastCol = sheet.getLastColumn();
    if (lastCol < 2) {
      SpreadsheetApp.getUi().alert('No date headers found in row 4. Add headers like "2025-12", "2026-01" starting at B4.');
      return;
    }

    const headers = sheet.getRange(4, 2, 1, lastCol - 1).getValues()[0];
    Logger.log('Headers: ' + JSON.stringify(headers));

    // Get ASINs from column A starting row 5
    const lastRow = sheet.getLastRow();
    if (lastRow < 5) {
      SpreadsheetApp.getUi().alert('No ASINs found. Add ASINs starting at row 5 in column A.');
      return;
    }

    const asinRange = sheet.getRange(5, 1, lastRow - 4, 1);
    const asins = asinRange.getValues();
    Logger.log('Found ' + asins.length + ' ASINs to process');

    // Fill in data
    let updatedCells = 0;
    let matchedAsins = 0;

    for (let i = 0; i < asins.length; i++) {
      const asin = String(asins[i][0]).trim();
      if (!asin) continue;

      if (!lookup[asin]) {
        Logger.log('No data for ASIN: ' + asin);
        continue;
      }

      matchedAsins++;

      for (let j = 0; j < headers.length; j++) {
        const monthKey = String(headers[j]).trim();
        if (!monthKey) continue;

        if (lookup[asin][monthKey] !== undefined) {
          const cellRow = 5 + i;
          const cellCol = 2 + j;
          sheet.getRange(cellRow, cellCol).setValue(lookup[asin][monthKey]);
          updatedCells++;
        }
      }
    }

    SpreadsheetApp.getUi().alert(
      'Refresh Complete!\n\n' +
      'Data rows fetched: ' + data.length + '\n' +
      'ASINs matched: ' + matchedAsins + ' of ' + asins.length + '\n' +
      'Cells updated: ' + updatedCells
    );

  } catch (e) {
    SpreadsheetApp.getUi().alert('Error refreshing data: ' + e.message);
    Logger.log('Error: ' + e.message + '\n' + e.stack);
  }
}

/**
 * Fetches monthly sales data from Supabase
 * @param {string} marketplaceId - The Supabase marketplace UUID
 * @returns {Array} Array of {month, child_asin, units_ordered} objects
 */
function fetchMonthlyData(marketplaceId) {
  const url = SUPABASE_URL + '/rest/v1/sp_monthly_asin_data' +
    '?marketplace_id=eq.' + encodeURIComponent(marketplaceId) +
    '&select=month,child_asin,units_ordered,ordered_product_sales';

  Logger.log('Fetching: ' + url);

  const response = UrlFetchApp.fetch(url, {
    method: 'GET',
    headers: {
      'apikey': SUPABASE_KEY,
      'Authorization': 'Bearer ' + SUPABASE_KEY,
      'Content-Type': 'application/json'
    },
    muteHttpExceptions: true
  });

  const code = response.getResponseCode();
  if (code !== 200) {
    throw new Error('Supabase API error: ' + code + ' - ' + response.getContentText());
  }

  return JSON.parse(response.getContentText());
}

/**
 * Builds a lookup map from the data
 * @param {Array} data - Array of data rows from Supabase
 * @returns {Object} Nested map: { asin: { monthKey: units } }
 */
function buildLookupMap(data) {
  const lookup = {};

  for (const row of data) {
    const asin = row.child_asin;
    if (!asin) continue;

    if (!lookup[asin]) {
      lookup[asin] = {};
    }

    // Convert "2026-02-01" to "2026-02" for simpler header matching
    const monthKey = row.month.substring(0, 7);
    lookup[asin][monthKey] = row.units_ordered || 0;
  }

  return lookup;
}

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * Shows sample ASINs that have data in Supabase
 * Useful for setting up test sheets
 */
function showSampleAsins() {
  const sampleAsins = [
    'B086BNG4DY',
    'B07PQDFJW8',
    'B07DKXHBDX',
    'B0846W6TN8',
    'B089NN5R7Y',
    'B0F66S1GTS',
    'B08DHLLQNC',
    'B0DF2SB2H7',
    'B071F5ZCQV',
    'B0F6KWG6LV'
  ];

  SpreadsheetApp.getUi().alert(
    'Sample ASINs (USA top sellers with 3 months data):\n\n' +
    sampleAsins.join('\n') +
    '\n\nCopy these to column A starting at row 5.'
  );
}
