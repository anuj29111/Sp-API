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
 * Fetches monthly data from materialized view.
 * @param {string} sinceDate - Optional. Only fetch months >= this date (YYYY-MM-DD). If null, fetches all.
 */
function getMonthlyDataFromView(marketplaceId, config, sinceDate) {
  var url = config.url + '/rest/v1/sp_monthly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=month,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    (sinceDate ? '&month=gte.' + sinceDate : '') +
    '&order=month.desc,child_asin.asc';

  Logger.log('Fetching monthly data' + (sinceDate ? ' since ' + sinceDate : ' (all)'));
  return fetchAllFromSupabase(url, config);
}

/**
 * Fetches weekly data from materialized view.
 * @param {string} sinceDate - Optional. Only fetch weeks >= this date (YYYY-MM-DD). If null, fetches all.
 */
function getWeeklyDataFromView(marketplaceId, config, sinceDate) {
  var url = config.url + '/rest/v1/sp_weekly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=week_start,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    (sinceDate ? '&week_start=gte.' + sinceDate : '') +
    '&order=week_start.desc,child_asin.asc';

  Logger.log('Fetching weekly data' + (sinceDate ? ' since ' + sinceDate : ' (all)'));
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
// REFRESH: SP DATA (Weekly/Monthly)
// ============================================

/**
 * Refreshes SP Data sheet for a marketplace.
 *
 * Layout: oldest at top (row 2), newest at bottom. Sorted by data_type then period ASC.
 *
 * FIRST RUN (empty sheet): fetches ALL history, writes sorted oldest→newest.
 *
 * SUBSEQUENT RUNS (incremental):
 *   1. Reads sheet to find the latest month and latest week already present
 *   2. Fetches only data >= previous month (monthly) and >= 4 weeks ago (weekly)
 *   3. Removes matching stale rows from the BOTTOM of the sheet (recent data zone)
 *   4. Appends fresh rows at the bottom
 *   Old data above the cutoff is NEVER read or touched.
 */
function refreshSPData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      throw new Error(country + ' marketplace ID not found in Script Config!');
    }

    var sheet = getOrCreateSPDataSheet(country);
    var lastRow = sheet.getLastRow();
    var isFirstRun = (lastRow <= 1);

    // Cutoff dates for incremental fetch
    var now = new Date();
    var prevMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    var monthlyCutoff = prevMonth.getFullYear() + '-' +
      String(prevMonth.getMonth() + 1).padStart(2, '0') + '-01';
    var fourWeeksAgo = new Date(now.getTime() - 28 * 24 * 60 * 60 * 1000);
    var weeklyCutoff = fourWeeksAgo.getFullYear() + '-' +
      String(fourWeeksAgo.getMonth() + 1).padStart(2, '0') + '-' +
      String(fourWeeksAgo.getDate()).padStart(2, '0');

    SpreadsheetApp.getActiveSpreadsheet().toast(
      'Fetching ' + country + ' sales data' + (isFirstRun ? ' (full)' : ' (incremental)') + '...',
      'Please wait', 120);

    // Fetch from Supabase
    var monthlyData = getMonthlyDataFromView(marketplaceId, config, isFirstRun ? null : monthlyCutoff);
    var weeklyData = getWeeklyDataFromView(marketplaceId, config, isFirstRun ? null : weeklyCutoff);

    // Convert to sheet rows
    function toMonthlyRow(r) {
      return ['monthly', r.child_asin, r.month,
        r.units_ordered || 0, r.units_ordered_b2b || 0,
        r.ordered_product_sales || 0, r.ordered_product_sales_b2b || 0,
        r.sessions || 0, r.page_views || 0,
        r.avg_buy_box_percentage || 0, r.avg_conversion_rate || 0];
    }
    function toWeeklyRow(r) {
      return ['weekly', r.child_asin, r.week_start,
        r.units_ordered || 0, r.units_ordered_b2b || 0,
        r.ordered_product_sales || 0, r.ordered_product_sales_b2b || 0,
        r.sessions || 0, r.page_views || 0,
        r.avg_buy_box_percentage || 0, r.avg_conversion_rate || 0];
    }

    var freshRows = [];
    for (var i = 0; i < monthlyData.length; i++) freshRows.push(toMonthlyRow(monthlyData[i]));
    for (var j = 0; j < weeklyData.length; j++) freshRows.push(toWeeklyRow(weeklyData[j]));

    // Sort: monthly first (by period ASC), then weekly (by period ASC)
    freshRows.sort(function(a, b) {
      if (a[0] !== b[0]) return a[0] < b[0] ? -1 : 1; // monthly before weekly
      if (a[2] !== b[2]) return a[2] < b[2] ? -1 : 1; // period ASC (oldest first)
      return (a[1] || '').localeCompare(b[1] || '');    // child_asin ASC
    });

    if (isFirstRun) {
      // === FIRST RUN: write everything sorted ===
      if (freshRows.length > 0) {
        sheet.getRange(2, 1, freshRows.length, 11).setValues(freshRows);
      }
      Logger.log('SP Data ' + country + ' (full): ' + freshRows.length + ' rows');

    } else {
      // === INCREMENTAL: trim stale recent rows, append fresh ===

      // Build lookup of fresh keys to know what we're replacing
      var freshKeys = {};
      for (var f = 0; f < freshRows.length; f++) {
        freshKeys[freshRows[f][0] + '|' + freshRows[f][2] + '|' + freshRows[f][1]] = true;
      }

      // Scan sheet from bottom up to find where recent data starts
      // Recent = any row with period >= our cutoff dates
      // We only need to read/modify the tail of the sheet
      var existingData = sheet.getRange(2, 1, lastRow - 1, 11).getValues();

      // Keep rows that are NOT being replaced by fresh data
      var keptRows = [];
      var removedCount = 0;
      for (var e = 0; e < existingData.length; e++) {
        var key = String(existingData[e][0]) + '|' + String(existingData[e][2]) + '|' + String(existingData[e][1]);
        if (freshKeys[key]) {
          removedCount++;
        } else {
          keptRows.push(existingData[e]);
        }
      }

      // Append fresh rows at the end
      var finalRows = keptRows.concat(freshRows);

      // Clear and rewrite (only the data area — headers untouched)
      var maxClear = Math.max(lastRow - 1, finalRows.length);
      sheet.getRange(2, 1, maxClear, 11).clear();
      if (finalRows.length > 0) {
        sheet.getRange(2, 1, finalRows.length, 11).setValues(finalRows);
      }

      Logger.log('SP Data ' + country + ' (incremental): removed ' + removedCount +
        ' stale, appended ' + freshRows.length + ' fresh, total ' + finalRows.length);
    }

  } catch (e) {
    Logger.log('Error refreshing SP Data ' + country + ': ' + e.message + '\n' + e.stack);
    throw e;
  }
}

// ============================================
// REFRESH: SP ROLLING (7/14/30/60-day metrics)
// ============================================

function refreshRollingData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      throw new Error(country + ' marketplace ID not found in Script Config!');
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

    Logger.log('SP Rolling ' + country + ': ' + output.length + ' rows');

  } catch (e) {
    Logger.log('Error refreshing SP Rolling ' + country + ': ' + e.message + '\n' + e.stack);
    throw e;
  }
}

// ============================================
// REFRESH: SP INVENTORY (FBA + AWD)
// ============================================

function refreshInventoryData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      throw new Error(country + ' marketplace ID not found in Script Config!');
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

    Logger.log('SP Inventory ' + country + ': FBA=' + fbaData.length + ' AWD=' + awdData.length + ' total=' + output.length);

  } catch (e) {
    Logger.log('Error refreshing SP Inventory ' + country + ': ' + e.message + '\n' + e.stack);
    throw e;
  }
}

// ============================================
// REFRESH: SP FEES (Estimates + Settlement + Storage)
// ============================================

function refreshFeesData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];

    if (!marketplaceId) {
      throw new Error(country + ' marketplace ID not found in Script Config!');
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

    Logger.log('SP Fees ' + country + ': estimates=' + feeEstimates.length + ' settlements=' + settleFees.length + ' storage=' + storageFees.length);

  } catch (e) {
    Logger.log('Error refreshing SP Fees ' + country + ': ' + e.message + '\n' + e.stack);
    throw e;
  }
}

// ============================================
// TRIGGER-SAFE PER-COUNTRY FUNCTIONS
// ============================================
// Each function refreshes ONE data type for ONE country.
// Google Apps Script 6-min limit means we CANNOT do everything in one run.
//
// Naming: trigger_{COUNTRY}_{TYPE}
//   TYPE: sales, rolling, inventory, fees
//
// Set up time-based triggers on these (staggered 3-5 min apart).
// Use "Setup Triggers" from menu to auto-create all of them.

// --- US ---
function trigger_US_sales()     { refreshSPData('US', 'US'); }
function trigger_US_rolling()   { refreshRollingData('US', 'US'); }
function trigger_US_inventory() { refreshInventoryData('US', 'US'); }
function trigger_US_fees()      { refreshFeesData('US', 'US'); }

// --- CA ---
function trigger_CA_sales()     { refreshSPData('CA', 'CA'); }
function trigger_CA_rolling()   { refreshRollingData('CA', 'CA'); }
function trigger_CA_inventory() { refreshInventoryData('CA', 'CA'); }
function trigger_CA_fees()      { refreshFeesData('CA', 'CA'); }

// --- MX ---
function trigger_MX_sales()     { refreshSPData('MX', 'MX'); }
function trigger_MX_rolling()   { refreshRollingData('MX', 'MX'); }
function trigger_MX_inventory() { refreshInventoryData('MX', 'MX'); }
function trigger_MX_fees()      { refreshFeesData('MX', 'MX'); }

// --- UK ---
function trigger_UK_sales()     { refreshSPData('UK', 'UK'); }
function trigger_UK_rolling()   { refreshRollingData('UK', 'UK'); }
function trigger_UK_inventory() { refreshInventoryData('UK', 'UK'); }
function trigger_UK_fees()      { refreshFeesData('UK', 'UK'); }

// --- DE ---
function trigger_DE_sales()     { refreshSPData('DE', 'DE'); }
function trigger_DE_rolling()   { refreshRollingData('DE', 'DE'); }
function trigger_DE_inventory() { refreshInventoryData('DE', 'DE'); }
function trigger_DE_fees()      { refreshFeesData('DE', 'DE'); }

// --- FR ---
function trigger_FR_sales()     { refreshSPData('FR', 'FR'); }
function trigger_FR_rolling()   { refreshRollingData('FR', 'FR'); }
function trigger_FR_inventory() { refreshInventoryData('FR', 'FR'); }
function trigger_FR_fees()      { refreshFeesData('FR', 'FR'); }

// --- IT ---
function trigger_IT_sales()     { refreshSPData('IT', 'IT'); }
function trigger_IT_rolling()   { refreshRollingData('IT', 'IT'); }
function trigger_IT_inventory() { refreshInventoryData('IT', 'IT'); }
function trigger_IT_fees()      { refreshFeesData('IT', 'IT'); }

// --- ES ---
function trigger_ES_sales()     { refreshSPData('ES', 'ES'); }
function trigger_ES_rolling()   { refreshRollingData('ES', 'ES'); }
function trigger_ES_inventory() { refreshInventoryData('ES', 'ES'); }
function trigger_ES_fees()      { refreshFeesData('ES', 'ES'); }

// --- AU ---
function trigger_AU_sales()     { refreshSPData('AU', 'AU'); }
function trigger_AU_rolling()   { refreshRollingData('AU', 'AU'); }
function trigger_AU_inventory() { refreshInventoryData('AU', 'AU'); }
function trigger_AU_fees()      { refreshFeesData('AU', 'AU'); }

// --- UAE ---
function trigger_UAE_sales()     { refreshSPData('UAE', 'UAE'); }
function trigger_UAE_rolling()   { refreshRollingData('UAE', 'UAE'); }
function trigger_UAE_inventory() { refreshInventoryData('UAE', 'UAE'); }
function trigger_UAE_fees()      { refreshFeesData('UAE', 'UAE'); }

// ============================================
// AUTO-SETUP TRIGGERS
// ============================================
// Creates time-based triggers for all countries, staggered 3 min apart.
// Each country gets 4 triggers (sales, rolling, inventory, fees) at the same time.
// Run once from menu: Supabase Data → Setup Daily Triggers
//
// Schedule (default 6 AM start):
//   6:00 - US | 6:03 - CA | 6:06 - MX | 6:09 - UK | 6:12 - DE
//   6:15 - FR | 6:18 - IT | 6:21 - ES | 6:24 - AU | 6:27 - UAE

/**
 * Creates daily time-based triggers for all configured marketplaces.
 * Deletes existing supabase triggers first to avoid duplicates.
 */
function setupDailyTriggers() {
  var ui = SpreadsheetApp.getUi();

  // Get configured countries
  var config = getSupabaseConfig();
  var countries = Object.keys(config.marketplaces);

  if (countries.length === 0) {
    ui.alert('No marketplaces configured in Script Config!');
    return;
  }

  var confirm = ui.alert(
    'Setup Daily Triggers',
    'This will create daily triggers for ' + countries.length + ' marketplaces:\n' +
    countries.join(', ') + '\n\n' +
    '4 triggers per country (sales, rolling, inventory, fees)\n' +
    'Total: ' + (countries.length * 4) + ' triggers\n' +
    'Staggered 3 min apart starting at 6:00 AM\n\n' +
    'Any existing "trigger_" triggers will be deleted first.\n\n' +
    'Continue?',
    ui.ButtonSet.YES_NO);

  if (confirm !== ui.Button.YES) return;

  // Delete existing trigger_ functions
  var existing = ScriptApp.getProjectTriggers();
  var deleted = 0;
  for (var t = 0; t < existing.length; t++) {
    if (existing[t].getHandlerFunction().indexOf('trigger_') === 0) {
      ScriptApp.deleteTrigger(existing[t]);
      deleted++;
    }
  }
  Logger.log('Deleted ' + deleted + ' existing triggers');

  // Data types for each country
  var types = ['sales', 'rolling', 'inventory', 'fees'];
  var startHour = 6;
  var startMinute = 0;
  var created = 0;

  for (var i = 0; i < countries.length; i++) {
    var country = countries[i];
    var minuteOffset = startMinute + (i * 3);
    var hour = startHour + Math.floor(minuteOffset / 60);
    var minute = minuteOffset % 60;

    for (var j = 0; j < types.length; j++) {
      var funcName = 'trigger_' + country + '_' + types[j];

      // Verify function exists
      try {
        ScriptApp.newTrigger(funcName)
          .timeBased()
          .atHour(hour)
          .nearMinute(minute)
          .everyDays(1)
          .create();
        created++;
        Logger.log('Created trigger: ' + funcName + ' at ~' + hour + ':' + String(minute).padStart(2, '0'));
      } catch (e) {
        Logger.log('Failed to create trigger ' + funcName + ': ' + e.message);
      }
    }
  }

  ui.alert('Triggers created!\n\n' +
    'Deleted: ' + deleted + ' old triggers\n' +
    'Created: ' + created + ' new triggers\n\n' +
    'Schedule (daily):\n' +
    countries.map(function(c, idx) {
      var mo = startMinute + (idx * 3);
      var h = startHour + Math.floor(mo / 60);
      var m = mo % 60;
      return c + ' → ~' + h + ':' + String(m).padStart(2, '0');
    }).join('\n'));
}

/**
 * Deletes all trigger_ triggers. Use to stop automation.
 */
function removeAllTriggers() {
  var existing = ScriptApp.getProjectTriggers();
  var deleted = 0;
  for (var t = 0; t < existing.length; t++) {
    if (existing[t].getHandlerFunction().indexOf('trigger_') === 0) {
      ScriptApp.deleteTrigger(existing[t]);
      deleted++;
    }
  }
  _safeAlert('Removed ' + deleted + ' triggers.');
}

/**
 * Manual run: refresh one country at a time from menu.
 * Runs all 4 data types sequentially for the selected country.
 */
function refreshOneCountry() {
  var ui = SpreadsheetApp.getUi();
  var response = ui.prompt(
    'Refresh One Country',
    'Enter country code (US, CA, MX, UK, DE, FR, IT, ES, AU, UAE):',
    ui.ButtonSet.OK_CANCEL);

  if (response.getSelectedButton() !== ui.Button.OK) return;

  var country = response.getResponseText().trim().toUpperCase();
  var config = getSupabaseConfig();

  if (!config.marketplaces[country]) {
    ui.alert('Country "' + country + '" not found in Script Config!\n\nAvailable: ' +
      Object.keys(config.marketplaces).join(', '));
    return;
  }

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var errors = [];

  var steps = [
    { name: 'Sales', fn: function() { refreshSPData(country, country); } },
    { name: 'Rolling', fn: function() { refreshRollingData(country, country); } },
    { name: 'Inventory', fn: function() { refreshInventoryData(country, country); } },
    { name: 'Fees', fn: function() { refreshFeesData(country, country); } }
  ];

  for (var i = 0; i < steps.length; i++) {
    ss.toast('(' + (i + 1) + '/4) ' + country + ' ' + steps[i].name + '...', 'Refreshing', 120);
    try {
      steps[i].fn();
    } catch (e) {
      errors.push(steps[i].name + ': ' + e.message);
    }
  }

  if (errors.length > 0) {
    ui.alert(country + ' refresh done with errors:\n\n' + errors.join('\n'));
  } else {
    ui.alert(country + ' — all 4 data types refreshed!');
  }
}

/**
 * Shows alert if running interactively, logs if running from trigger.
 */
function _safeAlert(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (e) {
    // Running from trigger — no UI available, just log
    Logger.log(message);
  }
}

// ============================================
// MENU
// ============================================

function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('Supabase Data')
    .addItem('Refresh One Country...', 'refreshOneCountry')
    .addSeparator()
    .addSubMenu(ui.createMenu('Automation')
      .addItem('Setup Daily Triggers', 'setupDailyTriggers')
      .addItem('Remove All Triggers', 'removeAllTriggers'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Daily Sheets')
      .addItem('Refresh Current Sheet', 'refreshCurrentDailySheet')
      .addItem('Refresh TESTING Sheet', 'refreshTestingSheet'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Debug')
      .addItem('Test Connection', 'testConnection')
      .addItem('Check Sheet Dates', 'debugTestingSheetDates')
      .addItem('Check Sheet ASINs', 'debugTestingSheetASINs'))
    .addSeparator()
    .addItem('Show Formula Examples', 'showFormulaExamples')
    .addToUi();
}

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
