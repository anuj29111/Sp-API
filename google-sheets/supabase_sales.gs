/**
 * Supabase Sales Data Integration
 * Pulls daily sales, weekly/monthly aggregates, rolling averages,
 * inventory snapshots, and per-unit fee data from Supabase.
 *
 * All configuration is read from the "Script Config" sheet - NO HARDCODING.
 *
 * Dump Sheets:
 *   SP Data {country}      - Weekly/Monthly sales + traffic
 *   SP Rolling {country}   - Rolling 7/14/30/60 day metrics
 *   SP Inventory {country} - Latest FBA + AWD inventory snapshot
 *   SP Fees {country}      - Per-unit fee estimates + settlement actuals + storage
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
// SUPABASE API - CORE FETCH HELPERS
// ============================================

/**
 * Makes a GET request to Supabase REST API (single page, max 1000 rows)
 */
function fetchFromSupabase(endpoint, params, config) {
  let url = config.url + endpoint + '?';

  const queryParts = [];
  for (const key in params) {
    queryParts.push(encodeURIComponent(key) + '=' + encodeURIComponent(params[key]));
  }
  url += queryParts.join('&');

  Logger.log('Fetching: ' + url.substring(0, 120) + '...');

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

  if (responseCode !== 200 && responseCode !== 206) {
    Logger.log('Supabase API Error ' + responseCode + ': ' + response.getContentText());
    throw new Error('Supabase API error: ' + responseCode);
  }

  return JSON.parse(response.getContentText());
}

/**
 * Fetches ALL rows from Supabase with automatic pagination.
 * Supabase REST API returns max 1000 rows by default.
 * Uses Range header for offset-based pagination.
 *
 * @param {string} fullUrl - Complete URL with query params (no Range header yet)
 * @param {Object} config - Supabase config
 * @param {number} pageSize - Rows per page (default 1000)
 * @returns {Array} All rows combined
 */
function fetchAllFromSupabase(fullUrl, config, pageSize) {
  pageSize = pageSize || 1000;
  var allRows = [];
  var offset = 0;
  var totalCount = null;

  while (true) {
    var rangeEnd = offset + pageSize - 1;
    var options = {
      method: 'GET',
      headers: {
        'apikey': config.anonKey,
        'Authorization': 'Bearer ' + config.anonKey,
        'Content-Type': 'application/json',
        'Range': offset + '-' + rangeEnd,
        'Prefer': 'count=exact'
      },
      muteHttpExceptions: true
    };

    var response = UrlFetchApp.fetch(fullUrl, options);
    var responseCode = response.getResponseCode();

    // 200 = all rows fit in one page, 206 = partial content (more pages)
    if (responseCode !== 200 && responseCode !== 206) {
      Logger.log('Supabase API Error ' + responseCode + ': ' + response.getContentText());
      throw new Error('Supabase API error: ' + responseCode);
    }

    var pageData = JSON.parse(response.getContentText());
    allRows = allRows.concat(pageData);

    // Parse Content-Range header: "0-999/20760"
    var contentRange = response.getHeaders()['content-range'] || response.getHeaders()['Content-Range'];
    if (contentRange) {
      var match = contentRange.match(/\/(\d+)/);
      if (match) {
        totalCount = parseInt(match[1], 10);
      }
    }

    // If we got fewer rows than page size, we're done
    if (pageData.length < pageSize) {
      break;
    }

    // If we know total and have fetched all, we're done
    if (totalCount && allRows.length >= totalCount) {
      break;
    }

    offset += pageSize;
    Logger.log('Paginating: fetched ' + allRows.length + (totalCount ? '/' + totalCount : '') + ' rows...');
  }

  Logger.log('Total fetched: ' + allRows.length + ' rows' + (totalCount ? ' (server total: ' + totalCount + ')' : ''));
  return allRows;
}

// ============================================
// DATA FETCHING - DAILY
// ============================================

/**
 * Fetches daily data with proper date filtering using AND logic
 */
function getDailyDataBetweenDates(marketplaceId, startDate, endDate, config) {
  var url = config.url + '/rest/v1/sp_daily_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&date=gte.' + startDate +
    '&date=lte.' + endDate +
    '&select=date,child_asin,parent_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,buy_box_percentage,unit_session_percentage' +
    '&order=date.desc,child_asin.asc';

  Logger.log('Fetching daily data: ' + startDate + ' to ' + endDate);
  return fetchAllFromSupabase(url, config);
}

// ============================================
// DATA FETCHING - WEEKLY/MONTHLY (with pagination fix)
// ============================================

/**
 * Fetches monthly data from materialized view (WITH PAGINATION)
 */
function getMonthlyDataFromView(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_monthly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=month,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    '&order=month.desc,child_asin.asc';

  Logger.log('Fetching monthly data (paginated)');
  return fetchAllFromSupabase(url, config);
}

/**
 * Fetches weekly data from materialized view (WITH PAGINATION)
 */
function getWeeklyDataFromView(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_weekly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=week_start,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    '&order=week_start.desc,child_asin.asc';

  Logger.log('Fetching weekly data (paginated)');
  return fetchAllFromSupabase(url, config);
}

// ============================================
// DATA FETCHING - ROLLING METRICS
// ============================================

/**
 * Fetches rolling 7/14/30/60-day metrics from materialized view
 */
function getRollingMetrics(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_rolling_asin_metrics?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=child_asin,parent_asin,currency_code,units_last_7_days,revenue_last_7_days,avg_units_7_days,sessions_last_7_days,avg_conversion_7_days,units_last_14_days,revenue_last_14_days,avg_units_14_days,sessions_last_14_days,avg_conversion_14_days,units_last_30_days,revenue_last_30_days,avg_units_30_days,sessions_last_30_days,avg_conversion_30_days,units_last_60_days,revenue_last_60_days,avg_units_60_days,sessions_last_60_days,avg_conversion_60_days' +
    '&order=child_asin.asc';

  Logger.log('Fetching rolling metrics');
  return fetchAllFromSupabase(url, config);
}

// ============================================
// DATA FETCHING - INVENTORY
// ============================================

/**
 * Fetches FBA inventory for latest date
 */
function getFBAInventoryLatest(marketplaceId, config) {
  // First get the latest date
  var dateUrl = config.url + '/rest/v1/sp_fba_inventory?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=date' +
    '&order=date.desc' +
    '&limit=1';

  var dateResult = fetchFromSupabase('/rest/v1/sp_fba_inventory', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'date',
    'order': 'date.desc',
    'limit': '1'
  }, config);

  if (!dateResult || dateResult.length === 0) {
    Logger.log('No FBA inventory data found');
    return [];
  }

  var latestDate = dateResult[0].date;
  Logger.log('FBA inventory latest date: ' + latestDate);

  // Fetch all inventory for that date (includes EU EFN local/remote columns)
  var url = config.url + '/rest/v1/sp_fba_inventory?' +
    'marketplace_id=eq.' + marketplaceId +
    '&date=eq.' + latestDate +
    '&select=asin,sku,product_name,fulfillable_quantity,fulfillable_quantity_local,fulfillable_quantity_remote,reserved_quantity,inbound_working_quantity,inbound_shipped_quantity,inbound_receiving_quantity,unsellable_quantity,total_quantity' +
    '&order=asin.asc';

  return fetchAllFromSupabase(url, config);
}

/**
 * Fetches AWD inventory for latest date
 */
function getAWDInventoryLatest(marketplaceId, config) {
  // First get the latest date
  var dateResult = fetchFromSupabase('/rest/v1/sp_awd_inventory', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'date',
    'order': 'date.desc',
    'limit': '1'
  }, config);

  if (!dateResult || dateResult.length === 0) {
    Logger.log('No AWD inventory data found');
    return [];
  }

  var latestDate = dateResult[0].date;
  Logger.log('AWD inventory latest date: ' + latestDate);

  // Fetch all AWD inventory for that date
  var url = config.url + '/rest/v1/sp_awd_inventory?' +
    'marketplace_id=eq.' + marketplaceId +
    '&date=eq.' + latestDate +
    '&select=sku,total_onhand_quantity,total_inbound_quantity,available_quantity,reserved_quantity,total_quantity' +
    '&order=sku.asc';

  return fetchAllFromSupabase(url, config);
}

/**
 * Fetches SKU→ASIN mapping
 */
function getSKUASINMap(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_sku_asin_map?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=sku,asin';

  return fetchAllFromSupabase(url, config);
}

// ============================================
// DATA FETCHING - FEES
// ============================================

/**
 * Fetches FBA fee estimates (current per-unit fees)
 */
function getFBAFeeEstimates(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_fba_fee_estimates?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=asin,sku,product_size_tier,your_price,estimated_fee_total,estimated_referral_fee_per_unit,estimated_pick_pack_fee_per_unit,estimated_weight_handling_fee_per_unit,currency_code' +
    '&order=asin.asc';

  Logger.log('Fetching FBA fee estimates');
  return fetchAllFromSupabase(url, config);
}

/**
 * Fetches settlement-derived per-SKU average fees
 */
function getSettlementFeesBySKU(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_settlement_fees_by_sku?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=sku,avg_fba_fee_per_unit,avg_referral_fee_per_unit,fba_fee_qty_basis,referral_fee_qty_basis';

  Logger.log('Fetching settlement fees by SKU');
  return fetchAllFromSupabase(url, config);
}

/**
 * Fetches storage fees aggregated by ASIN for latest month
 */
function getStorageFeesByASIN(marketplaceId, config) {
  // First get the latest month
  var monthResult = fetchFromSupabase('/rest/v1/sp_storage_fees_by_asin', {
    'marketplace_id': 'eq.' + marketplaceId,
    'select': 'month',
    'order': 'month.desc',
    'limit': '1'
  }, config);

  if (!monthResult || monthResult.length === 0) {
    Logger.log('No storage fee data found');
    return [];
  }

  var latestMonth = monthResult[0].month;
  Logger.log('Storage fees latest month: ' + latestMonth);

  var url = config.url + '/rest/v1/sp_storage_fees_by_asin?' +
    'marketplace_id=eq.' + marketplaceId +
    '&month=eq.' + latestMonth +
    '&select=asin,total_storage_fee,total_avg_qty_on_hand,currency_code';

  return fetchAllFromSupabase(url, config);
}

// ============================================
// SHEET CREATORS
// ============================================

/**
 * Gets or creates a dump sheet with headers
 * @param {string} prefix - Sheet name prefix (e.g., 'SP Data', 'SP Rolling')
 * @param {string} country - Country code (USA, CA, MX)
 * @param {Array} headers - Array of header strings
 * @returns {Sheet}
 */
function getOrCreateDumpSheet(prefix, country, headers) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheetName = prefix + ' ' + country;

  var sheet = ss.getSheetByName(sheetName);

  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    sheet.setFrozenRows(1);
    Logger.log('Created new sheet: ' + sheetName);
  }

  return sheet;
}

// Backward-compatible wrapper for SP Data sheets
function getOrCreateSPDataSheet(country) {
  var headers = [
    'data_type', 'child_asin', 'period',
    'units_ordered', 'units_ordered_b2b',
    'ordered_product_sales', 'ordered_product_sales_b2b',
    'sessions', 'page_views',
    'avg_buy_box_percentage', 'avg_conversion_rate'
  ];
  return getOrCreateDumpSheet('SP Data', country, headers);
}

// ============================================
// REFRESH: SP DATA (Weekly/Monthly) - EXISTING + PAGINATION FIX
// ============================================

function refreshSPDataUSA() { refreshSPData('USA', 'US'); }
function refreshSPDataCA() { refreshSPData('CA', 'CA'); }
function refreshSPDataMX() { refreshSPData('MX', 'MX'); }
function refreshSPDataUK() { refreshSPData('UK', 'UK'); }
function refreshSPDataDE() { refreshSPData('DE', 'DE'); }
function refreshSPDataFR() { refreshSPData('FR', 'FR'); }
function refreshSPDataIT() { refreshSPData('IT', 'IT'); }
function refreshSPDataES() { refreshSPData('ES', 'ES'); }
function refreshSPDataAU() { refreshSPData('AU', 'AU'); }
function refreshSPDataUAE() { refreshSPData('UAE', 'UAE'); }

function refreshSPData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert(country + ' marketplace ID not found in Script Config!');
      return;
    }

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' sales data (with pagination)...', 'Please wait', 120);

    // Fetch monthly and weekly data (NOW WITH PAGINATION)
    var monthlyData = getMonthlyDataFromView(marketplaceId, config);
    var weeklyData = getWeeklyDataFromView(marketplaceId, config);

    Logger.log('Fetched ' + monthlyData.length + ' monthly rows');
    Logger.log('Fetched ' + weeklyData.length + ' weekly rows');

    // Get or create SP Data sheet
    var sheet = getOrCreateSPDataSheet(country);

    // Clear existing data (keep headers)
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, 11).clear();
    }

    // Build output array
    var output = [];

    for (var i = 0; i < monthlyData.length; i++) {
      var row = monthlyData[i];
      output.push([
        'monthly', row.child_asin, row.month,
        row.units_ordered || 0, row.units_ordered_b2b || 0,
        row.ordered_product_sales || 0, row.ordered_product_sales_b2b || 0,
        row.sessions || 0, row.page_views || 0,
        row.avg_buy_box_percentage || 0, row.avg_conversion_rate || 0
      ]);
    }

    for (var j = 0; j < weeklyData.length; j++) {
      var wrow = weeklyData[j];
      output.push([
        'weekly', wrow.child_asin, wrow.week_start,
        wrow.units_ordered || 0, wrow.units_ordered_b2b || 0,
        wrow.ordered_product_sales || 0, wrow.ordered_product_sales_b2b || 0,
        wrow.sessions || 0, wrow.page_views || 0,
        wrow.avg_buy_box_percentage || 0, wrow.avg_conversion_rate || 0
      ]);
    }

    if (output.length > 0) {
      sheet.getRange(2, 1, output.length, 11).setValues(output);
    }

    var summary = 'SP Data ' + country + ' refreshed!\n\n' +
      'Monthly rows: ' + monthlyData.length + '\n' +
      'Weekly rows: ' + weeklyData.length + '\n' +
      'Total rows: ' + output.length;

    Logger.log(summary);
    SpreadsheetApp.getUi().alert(summary);

  } catch (e) {
    Logger.log('Error: ' + e.message);
    Logger.log(e.stack);
    SpreadsheetApp.getUi().alert('Error refreshing SP Data ' + country + ': ' + e.message);
  }
}

// ============================================
// REFRESH: SP ROLLING (7/14/30/60-day metrics)
// ============================================

function refreshRollingUSA() { refreshRollingData('USA', 'US'); }
function refreshRollingCA() { refreshRollingData('CA', 'CA'); }
function refreshRollingMX() { refreshRollingData('MX', 'MX'); }
function refreshRollingUK() { refreshRollingData('UK', 'UK'); }
function refreshRollingDE() { refreshRollingData('DE', 'DE'); }
function refreshRollingFR() { refreshRollingData('FR', 'FR'); }
function refreshRollingIT() { refreshRollingData('IT', 'IT'); }
function refreshRollingES() { refreshRollingData('ES', 'ES'); }
function refreshRollingAU() { refreshRollingData('AU', 'AU'); }
function refreshRollingUAE() { refreshRollingData('UAE', 'UAE'); }

function refreshRollingData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert(country + ' marketplace ID not found in Script Config!');
      return;
    }

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' rolling metrics...', 'Please wait', 30);

    var data = getRollingMetrics(marketplaceId, config);
    Logger.log('Fetched ' + data.length + ' rolling metric rows');

    // Headers
    var headers = [
      'child_asin', 'parent_asin', 'currency',
      'units_7d', 'revenue_7d', 'avg_units_7d', 'sessions_7d', 'conversion_7d',
      'units_14d', 'revenue_14d', 'avg_units_14d', 'sessions_14d', 'conversion_14d',
      'units_30d', 'revenue_30d', 'avg_units_30d', 'sessions_30d', 'conversion_30d',
      'units_60d', 'revenue_60d', 'avg_units_60d', 'sessions_60d', 'conversion_60d'
    ];

    var sheet = getOrCreateDumpSheet('SP Rolling', country, headers);

    // Clear existing data (keep headers)
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, headers.length).clear();
    }

    // Build output
    var output = [];
    for (var i = 0; i < data.length; i++) {
      var r = data[i];
      output.push([
        r.child_asin || '', r.parent_asin || '', r.currency_code || '',
        r.units_last_7_days || 0, parseFloat(r.revenue_last_7_days) || 0,
        parseFloat(r.avg_units_7_days) || 0, r.sessions_last_7_days || 0, parseFloat(r.avg_conversion_7_days) || 0,
        r.units_last_14_days || 0, parseFloat(r.revenue_last_14_days) || 0,
        parseFloat(r.avg_units_14_days) || 0, r.sessions_last_14_days || 0, parseFloat(r.avg_conversion_14_days) || 0,
        r.units_last_30_days || 0, parseFloat(r.revenue_last_30_days) || 0,
        parseFloat(r.avg_units_30_days) || 0, r.sessions_last_30_days || 0, parseFloat(r.avg_conversion_30_days) || 0,
        r.units_last_60_days || 0, parseFloat(r.revenue_last_60_days) || 0,
        parseFloat(r.avg_units_60_days) || 0, r.sessions_last_60_days || 0, parseFloat(r.avg_conversion_60_days) || 0
      ]);
    }

    if (output.length > 0) {
      sheet.getRange(2, 1, output.length, headers.length).setValues(output);
    }

    SpreadsheetApp.getUi().alert('SP Rolling ' + country + ' refreshed!\n\nRows: ' + output.length);

  } catch (e) {
    Logger.log('Error: ' + e.message + '\n' + e.stack);
    SpreadsheetApp.getUi().alert('Error refreshing SP Rolling ' + country + ': ' + e.message);
  }
}

// ============================================
// REFRESH: SP INVENTORY (FBA + AWD)
// ============================================

function refreshInventoryUSA() { refreshInventoryData('USA', 'US'); }
function refreshInventoryCA() { refreshInventoryData('CA', 'CA'); }
function refreshInventoryMX() { refreshInventoryData('MX', 'MX'); }
function refreshInventoryUK() { refreshInventoryData('UK', 'UK'); }
function refreshInventoryDE() { refreshInventoryData('DE', 'DE'); }
function refreshInventoryFR() { refreshInventoryData('FR', 'FR'); }
function refreshInventoryIT() { refreshInventoryData('IT', 'IT'); }
function refreshInventoryES() { refreshInventoryData('ES', 'ES'); }
function refreshInventoryAU() { refreshInventoryData('AU', 'AU'); }
function refreshInventoryUAE() { refreshInventoryData('UAE', 'UAE'); }

function refreshInventoryData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert(country + ' marketplace ID not found in Script Config!');
      return;
    }

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' inventory...', 'Please wait', 30);

    // Fetch FBA inventory (has ASIN)
    var fbaData = getFBAInventoryLatest(marketplaceId, config);
    Logger.log('FBA inventory: ' + fbaData.length + ' rows');

    // Fetch AWD inventory (SKU only)
    var awdData = getAWDInventoryLatest(marketplaceId, config);
    Logger.log('AWD inventory: ' + awdData.length + ' rows');

    // Build AWD lookup by SKU
    var awdBySKU = {};
    for (var a = 0; a < awdData.length; a++) {
      awdBySKU[awdData[a].sku] = awdData[a];
    }

    // Track which AWD SKUs got matched
    var matchedAWDSKUs = {};

    // Headers (includes EU EFN local/remote columns)
    var headers = [
      'asin', 'sku', 'product_name',
      'fba_fulfillable', 'fba_local', 'fba_remote', 'fba_reserved',
      'fba_inbound_working', 'fba_inbound_shipped', 'fba_inbound_receiving',
      'fba_unsellable', 'fba_total',
      'awd_onhand', 'awd_inbound', 'awd_available', 'awd_total'
    ];

    var sheet = getOrCreateDumpSheet('SP Inventory', country, headers);

    // Clear existing data
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, headers.length).clear();
    }

    // Build output: Start with FBA, join AWD by SKU
    var output = [];
    for (var f = 0; f < fbaData.length; f++) {
      var fba = fbaData[f];
      var awd = awdBySKU[fba.sku] || {};

      if (awdBySKU[fba.sku]) {
        matchedAWDSKUs[fba.sku] = true;
      }

      output.push([
        fba.asin || '', fba.sku || '', fba.product_name || '',
        fba.fulfillable_quantity || 0, fba.fulfillable_quantity_local || 0, fba.fulfillable_quantity_remote || 0,
        fba.reserved_quantity || 0,
        fba.inbound_working_quantity || 0, fba.inbound_shipped_quantity || 0,
        fba.inbound_receiving_quantity || 0,
        fba.unsellable_quantity || 0, fba.total_quantity || 0,
        awd.total_onhand_quantity || 0, awd.total_inbound_quantity || 0,
        awd.available_quantity || 0, awd.total_quantity || 0
      ]);
    }

    // Add unmatched AWD SKUs (not in FBA inventory)
    // Need SKU→ASIN mapping for these
    var unmatchedCount = 0;
    var skuAsinMap = {};

    // Check if there are unmatched AWD SKUs
    for (var awdSku in awdBySKU) {
      if (!matchedAWDSKUs[awdSku]) {
        unmatchedCount++;
      }
    }

    // If unmatched, fetch SKU→ASIN map
    if (unmatchedCount > 0) {
      Logger.log(unmatchedCount + ' AWD SKUs not in FBA inventory, fetching ASIN map...');
      var mapData = getSKUASINMap(marketplaceId, config);
      for (var m = 0; m < mapData.length; m++) {
        skuAsinMap[mapData[m].sku] = mapData[m].asin;
      }

      for (var uSku in awdBySKU) {
        if (!matchedAWDSKUs[uSku]) {
          var uAwd = awdBySKU[uSku];
          output.push([
            skuAsinMap[uSku] || '', uSku, '(AWD only)',
            0, 0, 0, 0, 0, 0, 0, 0, 0,
            uAwd.total_onhand_quantity || 0, uAwd.total_inbound_quantity || 0,
            uAwd.available_quantity || 0, uAwd.total_quantity || 0
          ]);
        }
      }
    }

    if (output.length > 0) {
      sheet.getRange(2, 1, output.length, headers.length).setValues(output);
    }

    SpreadsheetApp.getUi().alert('SP Inventory ' + country + ' refreshed!\n\n' +
      'FBA SKUs: ' + fbaData.length + '\n' +
      'AWD SKUs: ' + awdData.length + '\n' +
      'AWD matched to FBA: ' + Object.keys(matchedAWDSKUs).length + '\n' +
      'AWD-only (unmatched): ' + unmatchedCount + '\n' +
      'Total rows: ' + output.length);

  } catch (e) {
    Logger.log('Error: ' + e.message + '\n' + e.stack);
    SpreadsheetApp.getUi().alert('Error refreshing SP Inventory ' + country + ': ' + e.message);
  }
}

// ============================================
// REFRESH: SP FEES (Estimates + Settlement + Storage)
// ============================================

function refreshFeesUSA() { refreshFeesData('USA', 'US'); }
function refreshFeesCA() { refreshFeesData('CA', 'CA'); }
function refreshFeesMX() { refreshFeesData('MX', 'MX'); }
function refreshFeesUK() { refreshFeesData('UK', 'UK'); }
function refreshFeesDE() { refreshFeesData('DE', 'DE'); }
function refreshFeesFR() { refreshFeesData('FR', 'FR'); }
function refreshFeesIT() { refreshFeesData('IT', 'IT'); }
function refreshFeesES() { refreshFeesData('ES', 'ES'); }
function refreshFeesAU() { refreshFeesData('AU', 'AU'); }
function refreshFeesUAE() { refreshFeesData('UAE', 'UAE'); }

function refreshFeesData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert(country + ' marketplace ID not found in Script Config!');
      return;
    }

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' fee data...', 'Please wait', 30);

    // 1. Fetch fee estimates
    var feeEstimates = getFBAFeeEstimates(marketplaceId, config);
    Logger.log('Fee estimates: ' + feeEstimates.length + ' rows');

    // 2. Fetch settlement-derived fees
    var settleFees = getSettlementFeesBySKU(marketplaceId, config);
    Logger.log('Settlement fees: ' + settleFees.length + ' rows');

    // 3. Fetch storage fees (latest month)
    var storageFees = getStorageFeesByASIN(marketplaceId, config);
    Logger.log('Storage fees: ' + storageFees.length + ' rows');

    // Build lookups
    var settleBySKU = {};
    for (var s = 0; s < settleFees.length; s++) {
      settleBySKU[settleFees[s].sku] = settleFees[s];
    }

    var storageByASIN = {};
    for (var st = 0; st < storageFees.length; st++) {
      storageByASIN[storageFees[st].asin] = storageFees[st];
    }

    // Headers
    var headers = [
      'asin', 'sku', 'product_size_tier', 'your_price',
      'est_fee_total', 'est_referral_per_unit', 'est_fba_per_unit',
      'settle_avg_fba_per_unit', 'settle_avg_referral_per_unit', 'settle_fba_qty_basis',
      'storage_fee_latest_month', 'storage_avg_qty_on_hand'
    ];

    var sheet = getOrCreateDumpSheet('SP Fees', country, headers);

    // Clear existing data
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      sheet.getRange(2, 1, lastRow - 1, headers.length).clear();
    }

    // Build output
    var output = [];
    for (var i = 0; i < feeEstimates.length; i++) {
      var fee = feeEstimates[i];
      var settle = settleBySKU[fee.sku] || {};
      var storage = storageByASIN[fee.asin] || {};

      // Compute FBA fee: est_fee_total - referral = FBA portion
      var estFeeTotal = parseFloat(fee.estimated_fee_total) || 0;
      var estReferral = parseFloat(fee.estimated_referral_fee_per_unit) || 0;
      var estFbaFee = estFeeTotal > 0 ? Math.round((estFeeTotal - estReferral) * 100) / 100 : 0;

      // If pick_pack is available, use it directly (more accurate)
      var pickPack = parseFloat(fee.estimated_pick_pack_fee_per_unit) || 0;
      var weightHandling = parseFloat(fee.estimated_weight_handling_fee_per_unit) || 0;
      if (pickPack > 0 || weightHandling > 0) {
        estFbaFee = Math.round((pickPack + weightHandling) * 100) / 100;
      }

      output.push([
        fee.asin || '', fee.sku || '', fee.product_size_tier || '',
        parseFloat(fee.your_price) || 0,
        estFeeTotal, estReferral, estFbaFee,
        parseFloat(settle.avg_fba_fee_per_unit) || 0,
        parseFloat(settle.avg_referral_fee_per_unit) || 0,
        settle.fba_fee_qty_basis || 0,
        parseFloat(storage.total_storage_fee) || 0,
        parseFloat(storage.total_avg_qty_on_hand) || 0
      ]);
    }

    if (output.length > 0) {
      sheet.getRange(2, 1, output.length, headers.length).setValues(output);
    }

    SpreadsheetApp.getUi().alert('SP Fees ' + country + ' refreshed!\n\n' +
      'Fee estimates: ' + feeEstimates.length + '\n' +
      'Settlement fee SKUs: ' + settleFees.length + '\n' +
      'Storage fee ASINs: ' + storageFees.length + '\n' +
      'Total rows: ' + output.length);

  } catch (e) {
    Logger.log('Error: ' + e.message + '\n' + e.stack);
    SpreadsheetApp.getUi().alert('Error refreshing SP Fees ' + country + ': ' + e.message);
  }
}

// ============================================
// REFRESH ALL - Batch refresh for a marketplace
// ============================================

function refreshAllUSA() { refreshAll('USA', 'US'); }
function refreshAllCA() { refreshAll('CA', 'CA'); }
function refreshAllMX() { refreshAll('MX', 'MX'); }
function refreshAllUK() { refreshAll('UK', 'UK'); }
function refreshAllDE() { refreshAll('DE', 'DE'); }
function refreshAllFR() { refreshAll('FR', 'FR'); }
function refreshAllIT() { refreshAll('IT', 'IT'); }
function refreshAllES() { refreshAll('ES', 'ES'); }
function refreshAllAU() { refreshAll('AU', 'AU'); }
function refreshAllUAE() { refreshAll('UAE', 'UAE'); }

function refreshAll(country, configKey) {
  try {
    SpreadsheetApp.getActiveSpreadsheet().toast('Refreshing ALL ' + country + ' data...', 'Please wait', 300);

    refreshSPData(country, configKey);
    refreshRollingData(country, configKey);
    refreshInventoryData(country, configKey);
    refreshFeesData(country, configKey);

    SpreadsheetApp.getUi().alert('All ' + country + ' data refreshed successfully!');
  } catch (e) {
    Logger.log('Error in refreshAll: ' + e.message);
    SpreadsheetApp.getUi().alert('Error during refresh ALL ' + country + ': ' + e.message);
  }
}

// ============================================
// MENU
// ============================================

function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('Supabase Data')
    .addItem('Test Connection', 'testConnection')
    .addSeparator()
    .addSubMenu(ui.createMenu('Daily Sheets')
      .addItem('Refresh Current Sheet', 'refreshCurrentDailySheet')
      .addItem('Refresh TESTING Sheet', 'refreshTestingSheet'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Sales (Weekly/Monthly)')
      .addItem('--- NA ---', 'noOp')
      .addItem('Refresh SP Data USA', 'refreshSPDataUSA')
      .addItem('Refresh SP Data CA', 'refreshSPDataCA')
      .addItem('Refresh SP Data MX', 'refreshSPDataMX')
      .addItem('--- EU ---', 'noOp')
      .addItem('Refresh SP Data UK', 'refreshSPDataUK')
      .addItem('Refresh SP Data DE', 'refreshSPDataDE')
      .addItem('Refresh SP Data FR', 'refreshSPDataFR')
      .addItem('Refresh SP Data IT', 'refreshSPDataIT')
      .addItem('Refresh SP Data ES', 'refreshSPDataES')
      .addItem('--- FE ---', 'noOp')
      .addItem('Refresh SP Data AU', 'refreshSPDataAU')
      .addItem('--- UAE ---', 'noOp')
      .addItem('Refresh SP Data UAE', 'refreshSPDataUAE'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Rolling Averages')
      .addItem('--- NA ---', 'noOp')
      .addItem('Refresh SP Rolling USA', 'refreshRollingUSA')
      .addItem('Refresh SP Rolling CA', 'refreshRollingCA')
      .addItem('Refresh SP Rolling MX', 'refreshRollingMX')
      .addItem('--- EU ---', 'noOp')
      .addItem('Refresh SP Rolling UK', 'refreshRollingUK')
      .addItem('Refresh SP Rolling DE', 'refreshRollingDE')
      .addItem('Refresh SP Rolling FR', 'refreshRollingFR')
      .addItem('Refresh SP Rolling IT', 'refreshRollingIT')
      .addItem('Refresh SP Rolling ES', 'refreshRollingES')
      .addItem('--- FE ---', 'noOp')
      .addItem('Refresh SP Rolling AU', 'refreshRollingAU')
      .addItem('--- UAE ---', 'noOp')
      .addItem('Refresh SP Rolling UAE', 'refreshRollingUAE'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Inventory')
      .addItem('--- NA ---', 'noOp')
      .addItem('Refresh SP Inventory USA', 'refreshInventoryUSA')
      .addItem('Refresh SP Inventory CA', 'refreshInventoryCA')
      .addItem('Refresh SP Inventory MX', 'refreshInventoryMX')
      .addItem('--- EU ---', 'noOp')
      .addItem('Refresh SP Inventory UK', 'refreshInventoryUK')
      .addItem('Refresh SP Inventory DE', 'refreshInventoryDE')
      .addItem('Refresh SP Inventory FR', 'refreshInventoryFR')
      .addItem('Refresh SP Inventory IT', 'refreshInventoryIT')
      .addItem('Refresh SP Inventory ES', 'refreshInventoryES')
      .addItem('--- FE ---', 'noOp')
      .addItem('Refresh SP Inventory AU', 'refreshInventoryAU')
      .addItem('--- UAE ---', 'noOp')
      .addItem('Refresh SP Inventory UAE', 'refreshInventoryUAE'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Fees & Costs')
      .addItem('--- NA ---', 'noOp')
      .addItem('Refresh SP Fees USA', 'refreshFeesUSA')
      .addItem('Refresh SP Fees CA', 'refreshFeesCA')
      .addItem('Refresh SP Fees MX', 'refreshFeesMX')
      .addItem('--- EU ---', 'noOp')
      .addItem('Refresh SP Fees UK', 'refreshFeesUK')
      .addItem('Refresh SP Fees DE', 'refreshFeesDE')
      .addItem('Refresh SP Fees FR', 'refreshFeesFR')
      .addItem('Refresh SP Fees IT', 'refreshFeesIT')
      .addItem('Refresh SP Fees ES', 'refreshFeesES')
      .addItem('--- FE ---', 'noOp')
      .addItem('Refresh SP Fees AU', 'refreshFeesAU')
      .addItem('--- UAE ---', 'noOp')
      .addItem('Refresh SP Fees UAE', 'refreshFeesUAE'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Refresh ALL')
      .addItem('--- NA ---', 'noOp')
      .addItem('Refresh ALL USA', 'refreshAllUSA')
      .addItem('Refresh ALL CA', 'refreshAllCA')
      .addItem('Refresh ALL MX', 'refreshAllMX')
      .addItem('--- EU ---', 'noOp')
      .addItem('Refresh ALL UK', 'refreshAllUK')
      .addItem('Refresh ALL DE', 'refreshAllDE')
      .addItem('Refresh ALL FR', 'refreshAllFR')
      .addItem('Refresh ALL IT', 'refreshAllIT')
      .addItem('Refresh ALL ES', 'refreshAllES')
      .addItem('--- FE ---', 'noOp')
      .addItem('Refresh ALL AU', 'refreshAllAU')
      .addItem('--- UAE ---', 'noOp')
      .addItem('Refresh ALL UAE', 'refreshAllUAE'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Debug')
      .addItem('Check Sheet Dates', 'debugTestingSheetDates')
      .addItem('Check Sheet ASINs', 'debugTestingSheetASINs'))
    .addSeparator()
    .addItem('Show Formula Examples', 'showFormulaExamples')
    .addToUi();
}

/** No-op function used as menu separator labels */
function noOp() {}

function testConnection() {
  try {
    var config = getSupabaseConfig();

    var data = fetchFromSupabase('/rest/v1/sp_daily_asin_data', {
      'select': 'date,child_asin',
      'limit': '1'
    }, config);

    var marketplaces = Object.keys(config.marketplaces).join(', ');
    SpreadsheetApp.getUi().alert('Connection successful!\n\nConfigured marketplaces: ' + marketplaces);
  } catch (e) {
    SpreadsheetApp.getUi().alert('Connection failed: ' + e.message);
  }
}

// ============================================
// DAILY SHEET REFRESH - AUTO-DETECT COLUMNS
// ============================================

function refreshCurrentDailySheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getActiveSheet();
  refreshDailySheet(sheet);
}

function refreshTestingSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('TESTING');

  if (!sheet) {
    SpreadsheetApp.getUi().alert('TESTING sheet not found!');
    return;
  }

  refreshDailySheet(sheet);
}

function refreshDailySheet(sheet) {
  try {
    var config = getSupabaseConfig();

    var marketplaceId = sheet.getRange('A2').getValue();
    if (!marketplaceId) {
      SpreadsheetApp.getUi().alert('Marketplace UUID not found in A2!');
      return;
    }

    var asinRange = sheet.getRange('C5:C500');
    var asinValues = asinRange.getValues();
    var asins = [];

    for (var i = 0; i < asinValues.length; i++) {
      var asin = String(asinValues[i][0]).trim();
      if (asin && asin.length > 0 && asin !== '' && asin !== 'undefined') {
        asins.push(asin);
      } else {
        break;
      }
    }

    if (asins.length === 0) {
      SpreadsheetApp.getUi().alert('No ASINs found in column C!');
      return;
    }

    var dateColumns = autoDetectDateColumns(sheet, 4, 6, 150);
    if (dateColumns.length === 0) {
      SpreadsheetApp.getUi().alert('No dates found in row 4!');
      return;
    }

    var firstDateCol = dateColumns[0].col;
    var allDates = dateColumns.map(function(d) { return d.date; }).sort();
    var minDate = allDates[0];
    var maxDate = allDates[allDates.length - 1];

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching data from Supabase...', 'Please wait', 30);

    var data = getDailyDataBetweenDates(marketplaceId, minDate, maxDate, config);

    var lookup = {};
    for (var d = 0; d < data.length; d++) {
      var row = data[d];
      if (!lookup[row.child_asin]) lookup[row.child_asin] = {};
      lookup[row.child_asin][row.date] = row.units_ordered || 0;
    }

    var numRows = asins.length;
    var numCols = dateColumns.length;
    var output = [];

    for (var r = 0; r < numRows; r++) {
      var asinKey = asins[r];
      var rowData = [];
      for (var c = 0; c < numCols; c++) {
        var dateKey = dateColumns[c].date;
        var units = (lookup[asinKey] && lookup[asinKey][dateKey] !== undefined) ? lookup[asinKey][dateKey] : 0;
        rowData.push(units);
      }
      output.push(rowData);
    }

    sheet.getRange(5, firstDateCol, numRows, numCols).setValues(output);

    var filledCells = 0;
    for (var ri = 0; ri < output.length; ri++) {
      for (var ci = 0; ci < output[ri].length; ci++) {
        if (output[ri][ci] !== '' && output[ri][ci] !== 0) filledCells++;
      }
    }

    SpreadsheetApp.getUi().alert('Sheet refreshed!\n\nASINs: ' + asins.length +
      '\nDate columns: ' + dateColumns.length +
      '\nDate range: ' + minDate + ' to ' + maxDate +
      '\nSupabase rows: ' + data.length +
      '\nCells with data: ' + filledCells);

  } catch (e) {
    Logger.log('Error: ' + e.message + '\n' + e.stack);
    SpreadsheetApp.getUi().alert('Error: ' + e.message);
  }
}

// ============================================
// AUTO-DETECT DATE COLUMNS
// ============================================

function autoDetectDateColumns(sheet, row, startCol, maxCols) {
  var range = sheet.getRange(row, startCol, 1, maxCols);
  var values = range.getValues()[0];
  var dateColumns = [];

  var foundFirstDate = false;
  var consecutiveEmpty = 0;

  for (var i = 0; i < values.length; i++) {
    var cellValue = values[i];
    var colNum = startCol + i;

    if (cellValue) {
      var dateStr = parseCellAsDate(cellValue);

      if (dateStr) {
        foundFirstDate = true;
        consecutiveEmpty = 0;
        dateColumns.push({ col: colNum, date: dateStr });
      } else if (foundFirstDate) {
        consecutiveEmpty++;
        if (consecutiveEmpty > 5) break;
      }
    } else if (foundFirstDate) {
      consecutiveEmpty++;
      if (consecutiveEmpty > 5) break;
    }
  }

  return dateColumns;
}

function parseCellAsDate(cellValue) {
  if (!cellValue) return null;

  if (cellValue instanceof Date) {
    if (isNaN(cellValue.getTime())) return null;
    var year = cellValue.getFullYear();
    var month = String(cellValue.getMonth() + 1).padStart(2, '0');
    var day = String(cellValue.getDate()).padStart(2, '0');
    if (year < 1900 || year > 2100) return null;
    return year + '-' + month + '-' + day;
  }

  if (typeof cellValue === 'number') {
    if (cellValue < 1 || cellValue > 100000) return null;
    var jsDate = new Date((cellValue - 25569) * 86400 * 1000);
    if (isNaN(jsDate.getTime())) return null;
    var y = jsDate.getFullYear();
    var m = String(jsDate.getMonth() + 1).padStart(2, '0');
    var d = String(jsDate.getDate()).padStart(2, '0');
    if (y < 1900 || y > 2100) return null;
    return y + '-' + m + '-' + d;
  }

  if (typeof cellValue === 'string') {
    var parts = cellValue.split('/');
    if (parts.length === 2) {
      var part1 = parseInt(parts[0], 10);
      var part2 = parseInt(parts[1], 10);
      if (isNaN(part1) || isNaN(part2)) return null;
      var dy, mo;
      if (part1 > 12) { dy = part1; mo = part2; }
      else if (part2 > 12) { mo = part1; dy = part2; }
      else { dy = part1; mo = part2; }
      if (dy < 1 || dy > 31 || mo < 1 || mo > 12) return null;
      var yr = new Date().getFullYear();
      return yr + '-' + String(mo).padStart(2, '0') + '-' + String(dy).padStart(2, '0');
    }
  }

  return null;
}

function columnToLetter(column) {
  var temp, letter = '';
  while (column > 0) {
    temp = (column - 1) % 26;
    letter = String.fromCharCode(temp + 65) + letter;
    column = (column - temp - 1) / 26;
  }
  return letter;
}

// ============================================
// DEBUG FUNCTIONS
// ============================================

function debugTestingSheetDates() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('TESTING');
  if (!sheet) { SpreadsheetApp.getUi().alert('TESTING sheet not found!'); return; }

  var range = sheet.getRange(4, 72, 1, 10);
  var values = range.getValues()[0];
  var debug = 'Date header debug (Row 4, starting BT):\n\n';

  for (var i = 0; i < values.length; i++) {
    var val = values[i];
    var colLetter = columnToLetter(72 + i);
    debug += colLetter + '4: ';
    if (val instanceof Date) { debug += 'Date: ' + val.toISOString().split('T')[0]; }
    else if (typeof val === 'number') { debug += 'Number: ' + val; }
    else if (typeof val === 'string') { debug += 'String: "' + val + '"'; }
    else { debug += 'Empty'; }
    debug += '\n';
  }
  SpreadsheetApp.getUi().alert(debug);
}

function debugTestingSheetASINs() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('TESTING');
  if (!sheet) { SpreadsheetApp.getUi().alert('TESTING sheet not found!'); return; }

  var range = sheet.getRange('C5:C15');
  var values = range.getValues();
  var debug = 'ASIN debug (Column C, rows 5-14):\n\n';

  for (var i = 0; i < values.length; i++) {
    var val = values[i][0];
    debug += 'C' + (5 + i) + ': ';
    if (val && String(val).trim().length > 0) { debug += '"' + String(val).trim() + '"'; }
    else { debug += '(empty)'; }
    debug += '\n';
  }

  var marketplaceId = sheet.getRange('A2').getValue();
  debug += '\nA2 (Marketplace UUID): "' + marketplaceId + '"';
  SpreadsheetApp.getUi().alert(debug);
}

// ============================================
// FORMULA EXAMPLES
// ============================================

function showFormulaExamples() {
  var examples =
    'FORMULA EXAMPLES FOR SUPABASE DATA SHEETS\n' +
    '═══════════════════════════════════════\n\n' +
    'SP DATA COLUMNS (Sales Weekly/Monthly):\n' +
    'A=data_type B=child_asin C=period D=units E=units_b2b\n' +
    'F=revenue G=revenue_b2b H=sessions I=page_views\n' +
    'J=avg_buy_box% K=avg_conversion%\n\n' +

    'Monthly Units:\n' +
    '=IFERROR(SUMIFS(\'SP Data USA\'!$D:$D, \'SP Data USA\'!$A:$A, "monthly", \'SP Data USA\'!$B:$B, $C5, \'SP Data USA\'!$C:$C, TEXT(BT$4,"yyyy-mm-dd")), 0)\n\n' +

    'SP ROLLING COLUMNS (7/14/30/60 day):\n' +
    'A=child_asin D=units_7d E=revenue_7d F=avg_units_7d\n' +
    'G=sessions_7d H=conversion_7d (same pattern for 14/30/60)\n\n' +

    'Rolling 30-day Units:\n' +
    '=IFERROR(INDEX(\'SP Rolling USA\'!$N:$N, MATCH($C5, \'SP Rolling USA\'!$A:$A, 0)), 0)\n\n' +

    'SP INVENTORY COLUMNS:\n' +
    'A=asin B=sku C=product_name D=fba_fulfillable E=fba_local F=fba_remote\n' +
    'G=fba_reserved H-J=fba_inbound(working/shipped/receiving)\n' +
    'K=fba_unsellable L=fba_total M=awd_onhand N=awd_inbound O=awd_available P=awd_total\n' +
    '(fba_local/fba_remote are EU Pan-European FBA columns; AWD is NA only)\n\n' +

    'FBA Fulfillable:\n' +
    '=IFERROR(INDEX(\'SP Inventory USA\'!$D:$D, MATCH($C5, \'SP Inventory USA\'!$A:$A, 0)), 0)\n\n' +

    'SP FEES COLUMNS:\n' +
    'A=asin B=sku C=size_tier D=price E=est_fee_total\n' +
    'F=est_referral G=est_fba_fee H=settle_avg_fba I=settle_avg_referral\n' +
    'J=settle_qty_basis K=storage_fee L=storage_avg_qty\n\n' +

    'Per-Unit FBA Fee (estimated):\n' +
    '=IFERROR(INDEX(\'SP Fees USA\'!$G:$G, MATCH($C5, \'SP Fees USA\'!$A:$A, 0)), 0)\n\n' +

    'Per-Unit FBA Fee (actual from settlements):\n' +
    '=ABS(IFERROR(INDEX(\'SP Fees USA\'!$H:$H, MATCH($C5, \'SP Fees USA\'!$A:$A, 0)), 0))';

  SpreadsheetApp.getUi().alert(examples);
}

// ============================================
// LEGACY FUNCTIONS (kept for reference)
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

function refreshCurrentSheet() {
  SpreadsheetApp.getUi().alert('Use "Refresh Current Sheet" under Daily Sheets menu.');
}

function getDailyDataForRange(marketplaceId, startDate, endDate, config) {
  return getDailyDataBetweenDates(marketplaceId, startDate, endDate, config);
}
