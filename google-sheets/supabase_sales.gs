/**
 * Supabase Sales Data Integration — USA First
 *
 * Pulls Amazon data from Supabase into Google Sheets "dump sheets",
 * which country tabs then reference via SUMIFS / INDEX-MATCH formulas.
 *
 * ALL configuration is read from the "Script Config" sheet — NO HARDCODING.
 *
 * === HOW IT WORKS ===
 *
 * 1. Script Config sheet has: Supabase URL, Anon Key, Marketplace IDs
 * 2. Script pulls data from Supabase → writes to 5 dump sheets per country
 * 3. Country tab (e.g., USA) has SUMIFS formulas that read from dump sheets
 * 4. Formulas use cell references for ASIN ($C5) and date (G$4) — nothing hardcoded
 *
 * === 5 DUMP SHEETS (per country) ===
 *
 * SP Data {country}      — Monthly & weekly aggregates (27+ months of history)
 * SP Daily {country}     — Last 35 days of daily per-ASIN data
 * SP Rolling {country}   — Rolling 7/14/30/60/90-day averages (one row per ASIN)
 * SP Inventory {country} — Latest FBA + AWD inventory snapshot
 * SP Fees {country}      — Fee estimates + settlement actuals + storage fees
 *
 * === 5 TRIGGERS (per country) ===
 *
 * Each dump sheet gets its own trigger because Google Apps Script
 * has a 6-minute execution limit per run. One trigger = one dump sheet.
 *
 * All 10 countries have trigger functions ready (50 total).
 * To activate: add marketplace UUID to Script Config, then run Setup Triggers.
 */


// ============================================
// CONFIGURATION
// ============================================

/**
 * Reads Supabase config from the "Script Config" sheet.
 *
 * Expected layout:
 *   Column A = Setting Name
 *   Column B = Parameter
 *   Column C = Value
 *
 * Looks for:
 *   "SUPABASE SETTINGS" header row
 *   "Supabase URL" | "All" | https://xxx.supabase.co
 *   "Supabase Anon Key" | "All" | eyJhbGci...
 *   "Marketplace ID" | "US" | f47ac10b-58cc-4372-...
 */
function getSupabaseConfig() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var configSheet = ss.getSheetByName('Script Config');

  if (!configSheet) {
    throw new Error('Script Config sheet not found!');
  }

  var data = configSheet.getDataRange().getValues();

  var config = {
    url: null,
    anonKey: null,
    marketplaces: {}
  };

  var inSupabaseSection = false;

  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    var settingName = String(row[0]).trim();
    var parameter = String(row[1]).trim();
    var value = String(row[2]).trim();

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
// SUPABASE API — FETCH HELPERS
// ============================================

/**
 * Single-page fetch (max 1000 rows).
 */
function fetchFromSupabase(endpoint, params, config) {
  var url = config.url + endpoint + '?';

  var queryParts = [];
  for (var key in params) {
    queryParts.push(encodeURIComponent(key) + '=' + encodeURIComponent(params[key]));
  }
  url += queryParts.join('&');

  Logger.log('Fetching: ' + url.substring(0, 120) + '...');

  var options = {
    method: 'GET',
    headers: {
      'apikey': config.anonKey,
      'Authorization': 'Bearer ' + config.anonKey,
      'Content-Type': 'application/json'
    },
    muteHttpExceptions: true
  };

  var response = UrlFetchApp.fetch(url, options);
  var responseCode = response.getResponseCode();

  if (responseCode !== 200 && responseCode !== 206) {
    Logger.log('Supabase API Error ' + responseCode + ': ' + response.getContentText());
    throw new Error('Supabase API error: ' + responseCode);
  }

  return JSON.parse(response.getContentText());
}

/**
 * Paginated fetch — gets ALL rows automatically.
 * Supabase REST API returns max 1000 per page.
 * Uses Range header for offset-based pagination.
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

    if (pageData.length < pageSize) break;
    if (totalCount && allRows.length >= totalCount) break;

    offset += pageSize;
    Logger.log('Paginating: fetched ' + allRows.length + (totalCount ? '/' + totalCount : '') + ' rows...');
  }

  Logger.log('Total fetched: ' + allRows.length + ' rows' + (totalCount ? ' (server total: ' + totalCount + ')' : ''));
  return allRows;
}


// ============================================
// DATA FETCHERS (Supabase → raw arrays)
// ============================================

/** Monthly data from materialized view */
function getMonthlyDataFromView(marketplaceId, config, sinceDate) {
  var url = config.url + '/rest/v1/sp_monthly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=month,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    (sinceDate ? '&month=gte.' + sinceDate : '') +
    '&order=month.desc,child_asin.asc';

  Logger.log('Fetching monthly data' + (sinceDate ? ' since ' + sinceDate : ' (all)'));
  return fetchAllFromSupabase(url, config);
}

/** Weekly data from materialized view */
function getWeeklyDataFromView(marketplaceId, config, sinceDate) {
  var url = config.url + '/rest/v1/sp_weekly_asin_data?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=week_start,child_asin,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,avg_buy_box_percentage,avg_conversion_rate' +
    (sinceDate ? '&week_start=gte.' + sinceDate : '') +
    '&order=week_start.desc,child_asin.asc';

  Logger.log('Fetching weekly data' + (sinceDate ? ' since ' + sinceDate : ' (all)'));
  return fetchAllFromSupabase(url, config);
}

/** Rolling 7/14/30/60/90-day metrics */
function getRollingMetrics(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_rolling_asin_metrics?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=child_asin,parent_asin,currency_code,' +
    'units_last_7_days,revenue_last_7_days,avg_units_7_days,sessions_last_7_days,avg_conversion_7_days,' +
    'units_last_14_days,revenue_last_14_days,avg_units_14_days,sessions_last_14_days,avg_conversion_14_days,' +
    'units_last_30_days,revenue_last_30_days,avg_units_30_days,sessions_last_30_days,avg_conversion_30_days,' +
    'units_last_60_days,revenue_last_60_days,avg_units_60_days,sessions_last_60_days,avg_conversion_60_days,' +
    'browser_sessions_last_7_days,mobile_app_sessions_last_7_days,browser_page_views_last_7_days,mobile_app_page_views_last_7_days,' +
    'browser_sessions_last_14_days,mobile_app_sessions_last_14_days,browser_page_views_last_14_days,mobile_app_page_views_last_14_days,' +
    'browser_sessions_last_30_days,mobile_app_sessions_last_30_days,browser_page_views_last_30_days,mobile_app_page_views_last_30_days,' +
    'browser_sessions_last_60_days,mobile_app_sessions_last_60_days,browser_page_views_last_60_days,mobile_app_page_views_last_60_days,' +
    'units_last_90_days,revenue_last_90_days,avg_units_90_days,sessions_last_90_days,avg_conversion_90_days,' +
    'browser_sessions_last_90_days,mobile_app_sessions_last_90_days,browser_page_views_last_90_days,mobile_app_page_views_last_90_days' +
    '&order=child_asin.asc';

  return fetchAllFromSupabase(url, config);
}

/** FBA inventory (latest date) */
function getFBAInventoryLatest(marketplaceId, config) {
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

  var url = config.url + '/rest/v1/sp_fba_inventory?' +
    'marketplace_id=eq.' + marketplaceId +
    '&date=eq.' + latestDate +
    '&select=asin,sku,product_name,fulfillable_quantity,fulfillable_quantity_local,fulfillable_quantity_remote,reserved_quantity,inbound_working_quantity,inbound_shipped_quantity,inbound_receiving_quantity,unsellable_quantity,total_quantity' +
    '&order=asin.asc';

  return fetchAllFromSupabase(url, config);
}

/** AWD inventory (latest date, NA only) */
function getAWDInventoryLatest(marketplaceId, config) {
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

  var url = config.url + '/rest/v1/sp_awd_inventory?' +
    'marketplace_id=eq.' + marketplaceId +
    '&date=eq.' + latestDate +
    '&select=sku,total_onhand_quantity,total_inbound_quantity,available_quantity,reserved_quantity,total_quantity' +
    '&order=sku.asc';

  return fetchAllFromSupabase(url, config);
}

/** SKU→ASIN mapping */
function getSKUASINMap(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_sku_asin_map?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=sku,asin';

  return fetchAllFromSupabase(url, config);
}

/** FBA fee estimates */
function getFBAFeeEstimates(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_fba_fee_estimates?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=asin,sku,product_size_tier,your_price,estimated_fee_total,estimated_referral_fee_per_unit,estimated_pick_pack_fee_per_unit,estimated_weight_handling_fee_per_unit,currency_code' +
    '&order=asin.asc';

  return fetchAllFromSupabase(url, config);
}

/** Settlement-derived per-SKU average fees */
function getSettlementFeesBySKU(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_settlement_fees_by_sku?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=sku,avg_fba_fee_per_unit,avg_referral_fee_per_unit,fba_fee_qty_basis,referral_fee_qty_basis';

  return fetchAllFromSupabase(url, config);
}

/** Storage fees by ASIN (latest month) */
function getStorageFeesByASIN(marketplaceId, config) {
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
// SHEET HELPER
// ============================================

/**
 * Gets or creates a dump sheet with headers.
 * Example: getOrCreateDumpSheet('SP Data', 'US', [...headers])
 * Creates sheet named "SP Data US" if it doesn't exist.
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


// ============================================
// REFRESH FUNCTION 1: SP DATA (Weekly/Monthly)
// ============================================
// Dump sheet: "SP Data {country}"
// Columns: data_type | child_asin | period | units | units_b2b | revenue | revenue_b2b | sessions | page_views | buy_box% | conversion%
// First run: fetches ALL history. Subsequent: incremental (last month + last 4 weeks).

function refreshSPData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];
    if (!marketplaceId) throw new Error(country + ' marketplace ID not found in Script Config!');

    var headers = [
      'data_type', 'child_asin', 'period',
      'units_ordered', 'units_ordered_b2b',
      'ordered_product_sales', 'ordered_product_sales_b2b',
      'sessions', 'page_views',
      'avg_buy_box_percentage', 'avg_conversion_rate'
    ];
    var sheet = getOrCreateDumpSheet('SP Data', country, headers);
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

    var monthlyData = getMonthlyDataFromView(marketplaceId, config, isFirstRun ? null : monthlyCutoff);
    var weeklyData = getWeeklyDataFromView(marketplaceId, config, isFirstRun ? null : weeklyCutoff);

    function toRow(type, r, periodField) {
      return [type, r.child_asin, r[periodField],
        r.units_ordered || 0, r.units_ordered_b2b || 0,
        r.ordered_product_sales || 0, r.ordered_product_sales_b2b || 0,
        r.sessions || 0, r.page_views || 0,
        r.avg_buy_box_percentage || 0, r.avg_conversion_rate || 0];
    }

    var freshRows = [];
    for (var i = 0; i < monthlyData.length; i++) freshRows.push(toRow('monthly', monthlyData[i], 'month'));
    for (var j = 0; j < weeklyData.length; j++) freshRows.push(toRow('weekly', weeklyData[j], 'week_start'));

    // Sort: monthly first then weekly, oldest→newest within each
    freshRows.sort(function(a, b) {
      if (a[0] !== b[0]) return a[0] < b[0] ? -1 : 1;
      if (a[2] !== b[2]) return a[2] < b[2] ? -1 : 1;
      return (a[1] || '').localeCompare(b[1] || '');
    });

    if (isFirstRun) {
      if (freshRows.length > 0) {
        sheet.getRange(2, 1, freshRows.length, 11).setValues(freshRows);
      }
      Logger.log('SP Data ' + country + ' (full): ' + freshRows.length + ' rows');
    } else {
      // Incremental: remove stale rows that match fresh data, then append
      var freshKeys = {};
      for (var f = 0; f < freshRows.length; f++) {
        freshKeys[freshRows[f][0] + '|' + freshRows[f][2] + '|' + freshRows[f][1]] = true;
      }

      var existingData = sheet.getRange(2, 1, lastRow - 1, 11).getValues();
      var keptRows = [];
      for (var e = 0; e < existingData.length; e++) {
        var key = String(existingData[e][0]) + '|' + String(existingData[e][2]) + '|' + String(existingData[e][1]);
        if (!freshKeys[key]) keptRows.push(existingData[e]);
      }

      var finalRows = keptRows.concat(freshRows);
      var maxClear = Math.max(lastRow - 1, finalRows.length);
      sheet.getRange(2, 1, maxClear, 11).clear();
      if (finalRows.length > 0) {
        sheet.getRange(2, 1, finalRows.length, 11).setValues(finalRows);
      }
      Logger.log('SP Data ' + country + ' (incremental): total ' + finalRows.length);
    }
  } catch (e) {
    Logger.log('Error refreshing SP Data ' + country + ': ' + e.message + '\n' + e.stack);
    throw e;
  }
}


// ============================================
// REFRESH FUNCTION 2: SP DAILY (Last 35 days)
// ============================================
// Dump sheet: "SP Daily {country}"
// Columns: child_asin | date | units | units_b2b | revenue | revenue_b2b | sessions | page_views | buy_box% | conversion%
// Full clear + rewrite each run (data is small: ~100 ASINs x 35 days = ~3500 rows).
// Uses the DEDUPED view (prefers Sales&Traffic over Orders, avoids double-counting).

function refreshDailyDumpData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];
    if (!marketplaceId) throw new Error(country + ' marketplace ID not found in Script Config!');

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' daily data (35 days)...', 'Please wait', 60);

    var now = new Date();
    var daysBack = new Date(now.getTime() - 35 * 24 * 60 * 60 * 1000);
    var startDate = daysBack.getFullYear() + '-' +
      String(daysBack.getMonth() + 1).padStart(2, '0') + '-' +
      String(daysBack.getDate()).padStart(2, '0');

    var url = config.url + '/rest/v1/sp_daily_asin_data_deduped?' +
      'marketplace_id=eq.' + marketplaceId +
      '&date=gte.' + startDate +
      '&select=child_asin,date,units_ordered,units_ordered_b2b,ordered_product_sales,ordered_product_sales_b2b,sessions,page_views,buy_box_percentage,unit_session_percentage' +
      '&order=child_asin.asc,date.asc';

    var data = fetchAllFromSupabase(url, config);

    var headers = ['child_asin', 'date', 'units_ordered', 'units_ordered_b2b',
      'ordered_product_sales', 'ordered_product_sales_b2b',
      'sessions', 'page_views', 'buy_box_percentage', 'unit_session_percentage'];

    var sheet = getOrCreateDumpSheet('SP Daily', country, headers);

    var lastRow = sheet.getLastRow();
    if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, headers.length).clear();

    var output = [];
    for (var i = 0; i < data.length; i++) {
      var r = data[i];
      output.push([
        r.child_asin || '', r.date || '',
        r.units_ordered || 0, r.units_ordered_b2b || 0,
        parseFloat(r.ordered_product_sales) || 0, parseFloat(r.ordered_product_sales_b2b) || 0,
        r.sessions || 0, r.page_views || 0,
        parseFloat(r.buy_box_percentage) || 0, parseFloat(r.unit_session_percentage) || 0
      ]);
    }

    if (output.length > 0) {
      sheet.getRange(2, 1, output.length, headers.length).setValues(output);
    }
    Logger.log('SP Daily ' + country + ': ' + output.length + ' rows');
  } catch (e) {
    Logger.log('Error refreshing SP Daily ' + country + ': ' + e.message + '\n' + e.stack);
    throw e;
  }
}


// ============================================
// REFRESH FUNCTION 3: SP ROLLING (7/14/30/60-day)
// ============================================
// Dump sheet: "SP Rolling {country}"
// One row per ASIN. Full clear + rewrite each run.

function refreshRollingData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];
    if (!marketplaceId) throw new Error(country + ' marketplace ID not found in Script Config!');

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' rolling metrics...', 'Please wait', 30);
    var data = getRollingMetrics(marketplaceId, config);

    var headers = [
      // A-W: Original columns (DO NOT REORDER — existing formulas depend on these positions)
      'child_asin', 'parent_asin', 'currency',
      'units_7d', 'revenue_7d', 'avg_units_7d', 'sessions_7d', 'conversion_7d',
      'units_14d', 'revenue_14d', 'avg_units_14d', 'sessions_14d', 'conversion_14d',
      'units_30d', 'revenue_30d', 'avg_units_30d', 'sessions_30d', 'conversion_30d',
      'units_60d', 'revenue_60d', 'avg_units_60d', 'sessions_60d', 'conversion_60d',
      // X onward: New session breakdown columns (appended, never reorder above)
      'browser_sessions_7d', 'mobile_app_sessions_7d', 'browser_page_views_7d', 'mobile_app_page_views_7d',
      'browser_sessions_14d', 'mobile_app_sessions_14d', 'browser_page_views_14d', 'mobile_app_page_views_14d',
      'browser_sessions_30d', 'mobile_app_sessions_30d', 'browser_page_views_30d', 'mobile_app_page_views_30d',
      'browser_sessions_60d', 'mobile_app_sessions_60d', 'browser_page_views_60d', 'mobile_app_page_views_60d',
      // 90-day window
      'units_90d', 'revenue_90d', 'avg_units_90d', 'sessions_90d', 'conversion_90d',
      'browser_sessions_90d', 'mobile_app_sessions_90d', 'browser_page_views_90d', 'mobile_app_page_views_90d'
    ];

    var sheet = getOrCreateDumpSheet('SP Rolling', country, headers);

    var lastRow = sheet.getLastRow();
    if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, headers.length).clear();

    var output = [];
    for (var i = 0; i < data.length; i++) {
      var r = data[i];
      output.push([
        // A-W: Original columns (same order as before)
        r.child_asin || '', r.parent_asin || '', r.currency_code || '',
        r.units_last_7_days || 0, parseFloat(r.revenue_last_7_days) || 0,
        parseFloat(r.avg_units_7_days) || 0, r.sessions_last_7_days || 0, parseFloat(r.avg_conversion_7_days) || 0,
        r.units_last_14_days || 0, parseFloat(r.revenue_last_14_days) || 0,
        parseFloat(r.avg_units_14_days) || 0, r.sessions_last_14_days || 0, parseFloat(r.avg_conversion_14_days) || 0,
        r.units_last_30_days || 0, parseFloat(r.revenue_last_30_days) || 0,
        parseFloat(r.avg_units_30_days) || 0, r.sessions_last_30_days || 0, parseFloat(r.avg_conversion_30_days) || 0,
        r.units_last_60_days || 0, parseFloat(r.revenue_last_60_days) || 0,
        parseFloat(r.avg_units_60_days) || 0, r.sessions_last_60_days || 0, parseFloat(r.avg_conversion_60_days) || 0,
        // X onward: New session breakdown columns
        r.browser_sessions_last_7_days || 0, r.mobile_app_sessions_last_7_days || 0,
        r.browser_page_views_last_7_days || 0, r.mobile_app_page_views_last_7_days || 0,
        r.browser_sessions_last_14_days || 0, r.mobile_app_sessions_last_14_days || 0,
        r.browser_page_views_last_14_days || 0, r.mobile_app_page_views_last_14_days || 0,
        r.browser_sessions_last_30_days || 0, r.mobile_app_sessions_last_30_days || 0,
        r.browser_page_views_last_30_days || 0, r.mobile_app_page_views_last_30_days || 0,
        r.browser_sessions_last_60_days || 0, r.mobile_app_sessions_last_60_days || 0,
        r.browser_page_views_last_60_days || 0, r.mobile_app_page_views_last_60_days || 0,
        // 90-day window
        r.units_last_90_days || 0, parseFloat(r.revenue_last_90_days) || 0,
        parseFloat(r.avg_units_90_days) || 0, r.sessions_last_90_days || 0, parseFloat(r.avg_conversion_90_days) || 0,
        r.browser_sessions_last_90_days || 0, r.mobile_app_sessions_last_90_days || 0,
        r.browser_page_views_last_90_days || 0, r.mobile_app_page_views_last_90_days || 0
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
// REFRESH FUNCTION 4: SP INVENTORY (FBA + AWD)
// ============================================
// Dump sheet: "SP Inventory {country}"
// Joins FBA inventory with AWD inventory by SKU.
// Multi-SKU ASINs = multiple rows (use SUMIFS in formulas, not INDEX/MATCH).

function refreshInventoryData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];
    if (!marketplaceId) throw new Error(country + ' marketplace ID not found in Script Config!');

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' inventory...', 'Please wait', 30);

    var fbaData = getFBAInventoryLatest(marketplaceId, config);
    var awdData = getAWDInventoryLatest(marketplaceId, config);

    // Build AWD lookup by SKU
    var awdBySKU = {};
    for (var a = 0; a < awdData.length; a++) {
      awdBySKU[awdData[a].sku] = awdData[a];
    }
    var matchedAWDSKUs = {};

    var headers = [
      'asin', 'sku', 'product_name',
      'fba_fulfillable', 'fba_local', 'fba_remote', 'fba_reserved',
      'fba_inbound_working', 'fba_inbound_shipped', 'fba_inbound_receiving',
      'fba_unsellable', 'fba_total',
      'awd_onhand', 'awd_inbound', 'awd_available', 'awd_total'
    ];

    var sheet = getOrCreateDumpSheet('SP Inventory', country, headers);

    var lastRow = sheet.getLastRow();
    if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, headers.length).clear();

    var output = [];
    for (var f = 0; f < fbaData.length; f++) {
      var fba = fbaData[f];
      var awd = awdBySKU[fba.sku] || {};
      if (awdBySKU[fba.sku]) matchedAWDSKUs[fba.sku] = true;

      output.push([
        fba.asin || '', fba.sku || '', fba.product_name || '',
        fba.fulfillable_quantity || 0, fba.fulfillable_quantity_local || 0, fba.fulfillable_quantity_remote || 0,
        fba.reserved_quantity || 0,
        fba.inbound_working_quantity || 0, fba.inbound_shipped_quantity || 0, fba.inbound_receiving_quantity || 0,
        fba.unsellable_quantity || 0, fba.total_quantity || 0,
        awd.total_onhand_quantity || 0, awd.total_inbound_quantity || 0,
        awd.available_quantity || 0, awd.total_quantity || 0
      ]);
    }

    // Add unmatched AWD SKUs (AWD-only, not in FBA)
    var unmatchedCount = 0;
    for (var awdSku in awdBySKU) {
      if (!matchedAWDSKUs[awdSku]) unmatchedCount++;
    }

    if (unmatchedCount > 0) {
      var mapData = getSKUASINMap(marketplaceId, config);
      var skuAsinMap = {};
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
    Logger.log('SP Inventory ' + country + ': FBA=' + fbaData.length + ' AWD=' + awdData.length);
  } catch (e) {
    Logger.log('Error refreshing SP Inventory ' + country + ': ' + e.message + '\n' + e.stack);
    throw e;
  }
}


// ============================================
// REFRESH FUNCTION 5: SP FEES (Estimates + Settlement + Storage)
// ============================================
// Dump sheet: "SP Fees {country}"
// Joins fee estimates + settlement-derived actuals + storage fees.

function refreshFeesData(country, configKey) {
  try {
    var config = getSupabaseConfig();
    var marketplaceId = config.marketplaces[configKey];
    if (!marketplaceId) throw new Error(country + ' marketplace ID not found in Script Config!');

    SpreadsheetApp.getActiveSpreadsheet().toast('Fetching ' + country + ' fee data...', 'Please wait', 30);

    var feeEstimates = getFBAFeeEstimates(marketplaceId, config);
    var settleFees = getSettlementFeesBySKU(marketplaceId, config);
    var storageFees = getStorageFeesByASIN(marketplaceId, config);

    var settleBySKU = {};
    for (var s = 0; s < settleFees.length; s++) {
      settleBySKU[settleFees[s].sku] = settleFees[s];
    }
    var storageByASIN = {};
    for (var st = 0; st < storageFees.length; st++) {
      storageByASIN[storageFees[st].asin] = storageFees[st];
    }

    var headers = [
      'asin', 'sku', 'product_size_tier', 'your_price',
      'est_fee_total', 'est_referral_per_unit', 'est_fba_per_unit',
      'settle_avg_fba_per_unit', 'settle_avg_referral_per_unit', 'settle_fba_qty_basis',
      'storage_fee_latest_month', 'storage_avg_qty_on_hand'
    ];

    var sheet = getOrCreateDumpSheet('SP Fees', country, headers);

    var lastRow = sheet.getLastRow();
    if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, headers.length).clear();

    var output = [];
    for (var i = 0; i < feeEstimates.length; i++) {
      var fee = feeEstimates[i];
      var settle = settleBySKU[fee.sku] || {};
      var storage = storageByASIN[fee.asin] || {};

      var estFeeTotal = parseFloat(fee.estimated_fee_total) || 0;
      var estReferral = parseFloat(fee.estimated_referral_fee_per_unit) || 0;
      var estFbaFee = estFeeTotal > 0 ? Math.round((estFeeTotal - estReferral) * 100) / 100 : 0;

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
// TRIGGER FUNCTIONS — USA ONLY (for now)
// ============================================
// 5 triggers, one per dump sheet.
// Each runs independently within the 6-min limit.
// All 10 countries supported: US, CA, MX, UK, DE, FR, IT, ES, AU, UAE
// To activate: add marketplace UUID to Script Config, then run Setup Triggers.

// North America
function trigger_US_sales()     { refreshSPData('US', 'US'); }
function trigger_US_daily()     { refreshDailyDumpData('US', 'US'); }
function trigger_US_rolling()   { refreshRollingData('US', 'US'); }
function trigger_US_inventory() { refreshInventoryData('US', 'US'); }
function trigger_US_fees()      { refreshFeesData('US', 'US'); }

function trigger_CA_sales()     { refreshSPData('CA', 'CA'); }
function trigger_CA_daily()     { refreshDailyDumpData('CA', 'CA'); }
function trigger_CA_rolling()   { refreshRollingData('CA', 'CA'); }
function trigger_CA_inventory() { refreshInventoryData('CA', 'CA'); }
function trigger_CA_fees()      { refreshFeesData('CA', 'CA'); }

function trigger_MX_sales()     { refreshSPData('MX', 'MX'); }
function trigger_MX_daily()     { refreshDailyDumpData('MX', 'MX'); }
function trigger_MX_rolling()   { refreshRollingData('MX', 'MX'); }
function trigger_MX_inventory() { refreshInventoryData('MX', 'MX'); }
function trigger_MX_fees()      { refreshFeesData('MX', 'MX'); }

// Europe
function trigger_UK_sales()     { refreshSPData('UK', 'UK'); }
function trigger_UK_daily()     { refreshDailyDumpData('UK', 'UK'); }
function trigger_UK_rolling()   { refreshRollingData('UK', 'UK'); }
function trigger_UK_inventory() { refreshInventoryData('UK', 'UK'); }
function trigger_UK_fees()      { refreshFeesData('UK', 'UK'); }

function trigger_DE_sales()     { refreshSPData('DE', 'DE'); }
function trigger_DE_daily()     { refreshDailyDumpData('DE', 'DE'); }
function trigger_DE_rolling()   { refreshRollingData('DE', 'DE'); }
function trigger_DE_inventory() { refreshInventoryData('DE', 'DE'); }
function trigger_DE_fees()      { refreshFeesData('DE', 'DE'); }

function trigger_FR_sales()     { refreshSPData('FR', 'FR'); }
function trigger_FR_daily()     { refreshDailyDumpData('FR', 'FR'); }
function trigger_FR_rolling()   { refreshRollingData('FR', 'FR'); }
function trigger_FR_inventory() { refreshInventoryData('FR', 'FR'); }
function trigger_FR_fees()      { refreshFeesData('FR', 'FR'); }

function trigger_IT_sales()     { refreshSPData('IT', 'IT'); }
function trigger_IT_daily()     { refreshDailyDumpData('IT', 'IT'); }
function trigger_IT_rolling()   { refreshRollingData('IT', 'IT'); }
function trigger_IT_inventory() { refreshInventoryData('IT', 'IT'); }
function trigger_IT_fees()      { refreshFeesData('IT', 'IT'); }

function trigger_ES_sales()     { refreshSPData('ES', 'ES'); }
function trigger_ES_daily()     { refreshDailyDumpData('ES', 'ES'); }
function trigger_ES_rolling()   { refreshRollingData('ES', 'ES'); }
function trigger_ES_inventory() { refreshInventoryData('ES', 'ES'); }
function trigger_ES_fees()      { refreshFeesData('ES', 'ES'); }

// Asia-Pacific & Middle East
function trigger_AU_sales()     { refreshSPData('AU', 'AU'); }
function trigger_AU_daily()     { refreshDailyDumpData('AU', 'AU'); }
function trigger_AU_rolling()   { refreshRollingData('AU', 'AU'); }
function trigger_AU_inventory() { refreshInventoryData('AU', 'AU'); }
function trigger_AU_fees()      { refreshFeesData('AU', 'AU'); }

function trigger_UAE_sales()     { refreshSPData('UAE', 'UAE'); }
function trigger_UAE_daily()     { refreshDailyDumpData('UAE', 'UAE'); }
function trigger_UAE_rolling()   { refreshRollingData('UAE', 'UAE'); }
function trigger_UAE_inventory() { refreshInventoryData('UAE', 'UAE'); }
function trigger_UAE_fees()      { refreshFeesData('UAE', 'UAE'); }


// ============================================
// AUTO-SETUP TRIGGERS
// ============================================

/**
 * Creates time-based triggers for all CONFIGURED marketplaces.
 * Only creates triggers for countries that have a marketplace ID in Script Config.
 * All 10 countries supported (US, CA, MX, UK, DE, FR, IT, ES, AU, UAE) = up to 50 triggers.
 *
 * Deletes existing trigger_ functions first to avoid duplicates.
 */
function setupTriggers() {
  var ui = SpreadsheetApp.getUi();
  var config = getSupabaseConfig();
  var countries = Object.keys(config.marketplaces);

  if (countries.length === 0) {
    ui.alert('No marketplaces configured in Script Config!');
    return;
  }

  var types = ['sales', 'daily', 'rolling', 'inventory', 'fees'];

  // Check which trigger functions actually exist
  var availableFunctions = [];
  for (var i = 0; i < countries.length; i++) {
    var testFunc = 'trigger_' + countries[i] + '_sales';
    // We can only create triggers for functions that exist in the script
    availableFunctions.push(countries[i]);
  }

  var totalTriggers = availableFunctions.length * types.length;

  var confirm = ui.alert(
    'Setup Triggers',
    'This will create triggers for: ' + availableFunctions.join(', ') + '\n\n' +
    types.length + ' triggers per country\n' +
    'Total: ' + totalTriggers + ' triggers\n' +
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

  var startHour = 6;
  var startMinute = 0;
  var created = 0;

  for (var ci = 0; ci < availableFunctions.length; ci++) {
    var country = availableFunctions[ci];
    var minuteOffset = startMinute + (ci * 3);
    var hour = startHour + Math.floor(minuteOffset / 60);
    var minute = minuteOffset % 60;

    for (var j = 0; j < types.length; j++) {
      var funcName = 'trigger_' + country + '_' + types[j];
      try {
        ScriptApp.newTrigger(funcName)
          .timeBased()
          .atHour(hour)
          .nearMinute(minute)
          .everyDays(1)
          .create();
        created++;
      } catch (e) {
        Logger.log('Failed to create trigger ' + funcName + ': ' + e.message);
      }
    }
  }

  ui.alert('Triggers created!\n\n' +
    'Deleted: ' + deleted + ' old triggers\n' +
    'Created: ' + created + ' new triggers\n\n' +
    'Schedule (daily):\n' +
    availableFunctions.map(function(c, idx) {
      var mo = startMinute + (idx * 3);
      var h = startHour + Math.floor(mo / 60);
      var m = mo % 60;
      return c + ' -> ~' + h + ':' + String(m).padStart(2, '0');
    }).join('\n'));
}

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


// ============================================
// MANUAL REFRESH — ONE COUNTRY
// ============================================

/**
 * Runs all 5 dump sheet refreshes for a single country.
 * Use from menu to test or manually update.
 */
function refreshOneCountry() {
  var ui = SpreadsheetApp.getUi();
  var response = ui.prompt(
    'Refresh One Country',
    'Enter country code (e.g., US, CA, UK, DE):',
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
    { name: 'Sales (weekly/monthly)', fn: function() { refreshSPData(country, country); } },
    { name: 'Daily (last 35 days)',   fn: function() { refreshDailyDumpData(country, country); } },
    { name: 'Rolling (7/14/30/60/90d)', fn: function() { refreshRollingData(country, country); } },
    { name: 'Inventory (FBA+AWD)',    fn: function() { refreshInventoryData(country, country); } },
    { name: 'Fees (est+settle+stor)', fn: function() { refreshFeesData(country, country); } }
  ];

  for (var i = 0; i < steps.length; i++) {
    ss.toast('(' + (i + 1) + '/5) ' + country + ' ' + steps[i].name + '...', 'Refreshing', 120);
    try {
      steps[i].fn();
    } catch (e) {
      errors.push(steps[i].name + ': ' + e.message);
    }
  }

  if (errors.length > 0) {
    ui.alert(country + ' refresh done with errors:\n\n' + errors.join('\n'));
  } else {
    ui.alert(country + ' — all 5 dump sheets refreshed!');
  }
}


// ============================================
// DUPLICATE COUNTRY TAB
// ============================================

/**
 * Duplicates a country tab (e.g., USA) to a new country.
 * Copies the sheet, then:
 *   - Replaces all dump sheet references in formulas
 *     ('SP Data US' → 'SP Data CA', etc.)
 *   - Updates A2 (marketplace UUID) and B2 (country code)
 *
 * This is how you expand from USA to other countries
 * without manually editing hundreds of formulas.
 */
function duplicateCountryTab() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // Source tab
  var sourceResponse = ui.prompt(
    'Duplicate Country Tab',
    'Enter the SOURCE tab name to copy from (e.g., "USA"):',
    ui.ButtonSet.OK_CANCEL);
  if (sourceResponse.getSelectedButton() !== ui.Button.OK) return;

  var sourceTabName = sourceResponse.getResponseText().trim();
  var sourceSheet = ss.getSheetByName(sourceTabName);
  if (!sourceSheet) {
    ui.alert('Tab "' + sourceTabName + '" not found!');
    return;
  }

  var sourceCountry = String(sourceSheet.getRange('B2').getValue()).trim();
  if (!sourceCountry) {
    ui.alert('No country code found in B2 of "' + sourceTabName + '"!');
    return;
  }

  // Target country
  var targetResponse = ui.prompt(
    'Target Country',
    'Enter the TARGET country code (e.g., CA, UK, DE):\n\n' +
    'Source: ' + sourceTabName + ' (code: ' + sourceCountry + ')',
    ui.ButtonSet.OK_CANCEL);
  if (targetResponse.getSelectedButton() !== ui.Button.OK) return;

  var targetCountry = targetResponse.getResponseText().trim().toUpperCase();
  if (targetCountry === sourceCountry) {
    ui.alert('Target country is the same as source!');
    return;
  }

  var config = getSupabaseConfig();
  var targetMarketplaceId = config.marketplaces[targetCountry];
  if (!targetMarketplaceId) {
    ui.alert('Country "' + targetCountry + '" not found in Script Config!\n\n' +
      'Available: ' + Object.keys(config.marketplaces).join(', ') + '\n\n' +
      'Add the marketplace UUID to Script Config first.');
    return;
  }

  // Country display names
  var countryNames = {
    'US': 'USA', 'CA': 'Canada', 'MX': 'Mexico',
    'UK': 'UK', 'DE': 'Germany', 'FR': 'France',
    'IT': 'Italy', 'ES': 'Spain',
    'AU': 'Australia', 'UAE': 'UAE'
  };
  var targetTabName = countryNames[targetCountry] || targetCountry;

  if (ss.getSheetByName(targetTabName)) {
    var overwrite = ui.alert(
      'Tab "' + targetTabName + '" already exists!',
      'Delete it and create a fresh copy?',
      ui.ButtonSet.YES_NO);
    if (overwrite !== ui.Button.YES) return;
    ss.deleteSheet(ss.getSheetByName(targetTabName));
  }

  // Check dump sheets exist
  var dumpPrefixes = ['SP Data', 'SP Daily', 'SP Rolling', 'SP Inventory', 'SP Fees'];
  var missingDumps = [];
  for (var d = 0; d < dumpPrefixes.length; d++) {
    if (!ss.getSheetByName(dumpPrefixes[d] + ' ' + targetCountry)) {
      missingDumps.push(dumpPrefixes[d] + ' ' + targetCountry);
    }
  }

  if (missingDumps.length > 0) {
    var proceed = ui.alert(
      'Missing dump sheets:\n\n' + missingDumps.join('\n') + '\n\n' +
      'Run "Refresh One Country" for ' + targetCountry + ' first.\n\n' +
      'Continue anyway? (formulas will show errors)',
      ui.ButtonSet.YES_NO);
    if (proceed !== ui.Button.YES) return;
  }

  ss.toast('Duplicating ' + sourceTabName + ' -> ' + targetTabName + '...', 'Please wait', 60);

  // Copy sheet
  var newSheet = sourceSheet.copyTo(ss);
  newSheet.setName(targetTabName);

  // Update config cells
  newSheet.getRange('A2').setValue(targetMarketplaceId);
  newSheet.getRange('B2').setValue(targetCountry);

  // Replace all dump sheet references in formulas
  var dataRange = newSheet.getDataRange();
  var formulas = dataRange.getFormulas();
  var replacementCount = 0;

  for (var row = 0; row < formulas.length; row++) {
    for (var col = 0; col < formulas[row].length; col++) {
      var formula = formulas[row][col];
      if (!formula) continue;

      var newFormula = formula;
      for (var p = 0; p < dumpPrefixes.length; p++) {
        var oldRef = dumpPrefixes[p] + ' ' + sourceCountry;
        var newRef = dumpPrefixes[p] + ' ' + targetCountry;
        newFormula = newFormula.split("'" + oldRef + "'").join("'" + newRef + "'");
        newFormula = newFormula.split(oldRef).join(newRef);
      }

      if (newFormula !== formula) {
        newSheet.getRange(row + 1, col + 1).setFormula(newFormula);
        replacementCount++;
      }
    }
  }

  ui.alert('Done!\n\n' +
    'Created: ' + targetTabName + '\n' +
    'Country: ' + targetCountry + '\n' +
    'Formulas updated: ' + replacementCount + '\n\n' +
    (missingDumps.length > 0 ?
      'NOTE: Run "Refresh One Country" for ' + targetCountry + ' to create missing dump sheets.' :
      'All dump sheets found.'));
}


// ============================================
// MENU
// ============================================

function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('Supabase Data')
    .addItem('Refresh One Country...', 'refreshOneCountry')
    .addItem('Duplicate Country Tab...', 'duplicateCountryTab')
    .addSeparator()
    .addSubMenu(ui.createMenu('Setup')
      .addItem('Setup DB Helper', 'setupDBHelper')
      .addItem('Setup Triggers', 'setupTriggers')
      .addItem('Remove All Triggers', 'removeAllTriggers'))
    .addSeparator()
    .addSubMenu(ui.createMenu('Debug')
      .addItem('Test Connection', 'testConnection')
      .addItem('Show Formula Examples', 'showFormulaExamples'))
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

function _safeAlert(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (e) {
    Logger.log(message);
  }
}


// ============================================
// DB HELPER SHEET — AUTO-CREATE
// ============================================

/**
 * Creates (or rebuilds) the DB Helper sheet with all section mappings.
 * Run from menu: Supabase Data > Setup DB Helper
 *
 * Column numbers are 0-INDEXED (A=0, B=1, C=2, etc.)
 *
 * Each row maps a section name from the country tab (row 3) to:
 *   - Which dump sheet to read from
 *   - Which column has the value to return
 *   - Which column has the ASIN
 *   - Which column has the date (if applicable)
 *   - Which column has data_type (if applicable)
 *   - What data_type to filter on (if applicable)
 *   - What lookup type to use (sumifs_date / sumifs / match / match_text)
 */
function setupDBHelper() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('DB Helper');

  if (sheet) {
    sheet.clear();
  } else {
    sheet = ss.insertSheet('DB Helper');
  }

  // DB Helper layout — stores range strings for direct use with INDIRECT in formulas.
  //   A = Section (goes in row 3 of country tab)
  //   B = Sheet Prefix (e.g., "SP Data" → becomes "SP Data US" via $B$2)
  //   C = Value Range (e.g., "$D:$D")
  //   D = ASIN Range (e.g., "$B:$B")
  //   E = Date Range (e.g., "$C:$C", blank for non-date sections)
  //   F = DataType Range (e.g., "$A:$A", blank for sheets without data_type)
  //   G = Data Type (e.g., "monthly", "weekly", blank)
  //   H = Lookup Type (sumifs_date / sumifs / match / match_text)
  var headers = ['Section', 'Sheet Prefix', 'Value Range', 'ASIN Range', 'Date Range', 'DataType Range', 'Data Type', 'Lookup Type'];

  // Dump sheet column mappings:
  // SP Data:      A=data_type B=child_asin C=period D=units E=units_b2b F=revenue G=revenue_b2b H=sessions I=page_views J=buy_box% K=conversion%
  // SP Daily:     A=child_asin B=date C=units D=units_b2b E=revenue F=revenue_b2b G=sessions H=page_views I=buy_box% J=conversion%
  // SP Rolling:   A=child_asin B=parent C=currency D-H=7d I-M=14d N-R=30d S-W=60d (original)
  //               X-AA=browser/mobile 7d, AB-AE=14d, AF-AI=30d, AJ-AM=60d (session breakdown, appended)
  //               AN-AR=90d core, AS-AV=90d session breakdown (appended)
  // SP Inventory: A=asin B=sku C=product_name D=fba_fulfillable E=fba_local F=fba_remote G=reserved H-J=inbound K=unsellable L=fba_total M-P=awd
  // SP Fees:      A=asin B=sku C=size_tier D=price E=est_total F=est_referral G=est_fba H-J=settlement K=storage_fee L=storage_qty
  var rows = [
    // === SP Data (monthly) — LOCKED LAYOUT, DO NOT REORDER ===
    ['Monthly Sales',        'SP Data', '$D:$D', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],
    ['Monthly Sales B2B',    'SP Data', '$E:$E', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],
    ['Monthly Revenue',      'SP Data', '$F:$F', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],
    ['Monthly Revenue B2B',  'SP Data', '$G:$G', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],
    ['Monthly Sessions',     'SP Data', '$H:$H', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],
    ['Monthly Page Views',   'SP Data', '$I:$I', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],
    ['Monthly Buy Box %',    'SP Data', '$J:$J', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],
    ['Monthly Conversion %', 'SP Data', '$K:$K', '$B:$B', '$C:$C', '$A:$A', 'monthly', 'sumifs_date'],

    // === SP Data (weekly) — LOCKED LAYOUT, DO NOT REORDER ===
    ['Weekly Sales',        'SP Data', '$D:$D', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],
    ['Weekly Sales B2B',    'SP Data', '$E:$E', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],
    ['Weekly Revenue',      'SP Data', '$F:$F', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],
    ['Weekly Revenue B2B',  'SP Data', '$G:$G', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],
    ['Weekly Sessions',     'SP Data', '$H:$H', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],
    ['Weekly Page Views',   'SP Data', '$I:$I', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],
    ['Weekly Buy Box %',    'SP Data', '$J:$J', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],
    ['Weekly Conversion %', 'SP Data', '$K:$K', '$B:$B', '$C:$C', '$A:$A', 'weekly', 'sumifs_date'],

    // === SP Daily — LOCKED LAYOUT, DO NOT REORDER ===
    ['Daily Sales',        'SP Daily', '$C:$C', '$A:$A', '$B:$B', '', '', 'sumifs_date'],
    ['Daily Sales B2B',    'SP Daily', '$D:$D', '$A:$A', '$B:$B', '', '', 'sumifs_date'],
    ['Daily Revenue',      'SP Daily', '$E:$E', '$A:$A', '$B:$B', '', '', 'sumifs_date'],
    ['Daily Revenue B2B',  'SP Daily', '$F:$F', '$A:$A', '$B:$B', '', '', 'sumifs_date'],
    ['Daily Sessions',     'SP Daily', '$G:$G', '$A:$A', '$B:$B', '', '', 'sumifs_date'],
    ['Daily Page Views',   'SP Daily', '$H:$H', '$A:$A', '$B:$B', '', '', 'sumifs_date'],
    ['Daily Buy Box %',    'SP Daily', '$I:$I', '$A:$A', '$B:$B', '', '', 'sumifs_date'],
    ['Daily Conversion %', 'SP Daily', '$J:$J', '$A:$A', '$B:$B', '', '', 'sumifs_date'],

    // === SP Rolling (original 7/14/30/60d) — LOCKED LAYOUT, DO NOT REORDER ===
    ['Rolling 7d Units',       'SP Rolling', '$D:$D', '$A:$A', '', '', '', 'match'],
    ['Rolling 7d Revenue',     'SP Rolling', '$E:$E', '$A:$A', '', '', '', 'match'],
    ['Rolling 7d Avg Units',   'SP Rolling', '$F:$F', '$A:$A', '', '', '', 'match'],
    ['Rolling 7d Sessions',    'SP Rolling', '$G:$G', '$A:$A', '', '', '', 'match'],
    ['Rolling 7d Conversion',  'SP Rolling', '$H:$H', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Units',      'SP Rolling', '$I:$I', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Revenue',    'SP Rolling', '$J:$J', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Avg Units',  'SP Rolling', '$K:$K', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Sessions',   'SP Rolling', '$L:$L', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Conversion', 'SP Rolling', '$M:$M', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Units',      'SP Rolling', '$N:$N', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Revenue',    'SP Rolling', '$O:$O', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Avg Units',  'SP Rolling', '$P:$P', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Sessions',   'SP Rolling', '$Q:$Q', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Conversion', 'SP Rolling', '$R:$R', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Units',      'SP Rolling', '$S:$S', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Revenue',    'SP Rolling', '$T:$T', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Avg Units',  'SP Rolling', '$U:$U', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Sessions',   'SP Rolling', '$V:$V', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Conversion', 'SP Rolling', '$W:$W', '$A:$A', '', '', '', 'match'],

    // === SP Inventory (no date — SUMIFS for multi-SKU ASINs) ===
    ['FBA Fulfillable',  'SP Inventory', '$D:$D', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Local',        'SP Inventory', '$E:$E', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Remote',       'SP Inventory', '$F:$F', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Reserved',     'SP Inventory', '$G:$G', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Inbound Work', 'SP Inventory', '$H:$H', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Inbound Ship', 'SP Inventory', '$I:$I', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Inbound Recv', 'SP Inventory', '$J:$J', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Unsellable',   'SP Inventory', '$K:$K', '$A:$A', '', '', '', 'sumifs'],
    ['FBA Total',        'SP Inventory', '$L:$L', '$A:$A', '', '', '', 'sumifs'],
    ['AWD On-hand',      'SP Inventory', '$M:$M', '$A:$A', '', '', '', 'sumifs'],
    ['AWD Inbound',      'SP Inventory', '$N:$N', '$A:$A', '', '', '', 'sumifs'],
    ['AWD Available',    'SP Inventory', '$O:$O', '$A:$A', '', '', '', 'sumifs'],
    ['AWD Total',        'SP Inventory', '$P:$P', '$A:$A', '', '', '', 'sumifs'],
    ['Product Name',     'SP Inventory', '$C:$C', '$A:$A', '', '', '', 'match_text'],

    // === SP Fees (no date — one row per ASIN, INDEX/MATCH) ===
    ['Size Tier',            'SP Fees', '$C:$C', '$A:$A', '', '', '', 'match_text'],
    ['Price',                'SP Fees', '$D:$D', '$A:$A', '', '', '', 'match'],
    ['Est Fee Total',        'SP Fees', '$E:$E', '$A:$A', '', '', '', 'match'],
    ['Est Referral Fee',     'SP Fees', '$F:$F', '$A:$A', '', '', '', 'match'],
    ['Est FBA Fee',          'SP Fees', '$G:$G', '$A:$A', '', '', '', 'match'],
    ['Settle Avg FBA Fee',   'SP Fees', '$H:$H', '$A:$A', '', '', '', 'match'],
    ['Settle Avg Referral',  'SP Fees', '$I:$I', '$A:$A', '', '', '', 'match'],
    ['Settle FBA Qty Basis', 'SP Fees', '$J:$J', '$A:$A', '', '', '', 'match'],
    ['Storage Fee',          'SP Fees', '$K:$K', '$A:$A', '', '', '', 'match'],
    ['Storage Avg Qty',      'SP Fees', '$L:$L', '$A:$A', '', '', '', 'match'],

    // === Aliases ===
    ['Storage',              'SP Fees', '$K:$K', '$A:$A', '', '', '', 'match'],

    // =============================================================================
    // NEW SECTIONS (appended — never reorder above, add new sections below only)
    // =============================================================================

    // === SP Rolling — Session Breakdown (appended after col W) ===
    // 7d session breakdown: X-AA
    ['Rolling 7d Browser Sessions',  'SP Rolling', '$X:$X', '$A:$A', '', '', '', 'match'],
    ['Rolling 7d Mobile Sessions',   'SP Rolling', '$Y:$Y', '$A:$A', '', '', '', 'match'],
    ['Rolling 7d Browser PV',        'SP Rolling', '$Z:$Z', '$A:$A', '', '', '', 'match'],
    ['Rolling 7d Mobile PV',         'SP Rolling', '$AA:$AA', '$A:$A', '', '', '', 'match'],
    // 14d session breakdown: AB-AE
    ['Rolling 14d Browser Sessions', 'SP Rolling', '$AB:$AB', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Mobile Sessions',  'SP Rolling', '$AC:$AC', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Browser PV',       'SP Rolling', '$AD:$AD', '$A:$A', '', '', '', 'match'],
    ['Rolling 14d Mobile PV',        'SP Rolling', '$AE:$AE', '$A:$A', '', '', '', 'match'],
    // 30d session breakdown: AF-AI
    ['Rolling 30d Browser Sessions', 'SP Rolling', '$AF:$AF', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Mobile Sessions',  'SP Rolling', '$AG:$AG', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Browser PV',       'SP Rolling', '$AH:$AH', '$A:$A', '', '', '', 'match'],
    ['Rolling 30d Mobile PV',        'SP Rolling', '$AI:$AI', '$A:$A', '', '', '', 'match'],
    // 60d session breakdown: AJ-AM
    ['Rolling 60d Browser Sessions', 'SP Rolling', '$AJ:$AJ', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Mobile Sessions',  'SP Rolling', '$AK:$AK', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Browser PV',       'SP Rolling', '$AL:$AL', '$A:$A', '', '', '', 'match'],
    ['Rolling 60d Mobile PV',        'SP Rolling', '$AM:$AM', '$A:$A', '', '', '', 'match'],
    // 90d full window: AN-AV
    ['Rolling 90d Units',            'SP Rolling', '$AN:$AN', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Revenue',          'SP Rolling', '$AO:$AO', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Avg Units',        'SP Rolling', '$AP:$AP', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Sessions',         'SP Rolling', '$AQ:$AQ', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Conversion',       'SP Rolling', '$AR:$AR', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Browser Sessions', 'SP Rolling', '$AS:$AS', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Mobile Sessions',  'SP Rolling', '$AT:$AT', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Browser PV',       'SP Rolling', '$AU:$AU', '$A:$A', '', '', '', 'match'],
    ['Rolling 90d Mobile PV',        'SP Rolling', '$AV:$AV', '$A:$A', '', '', '', 'match'],
  ];

  // Write headers + data
  var allData = [headers].concat(rows);
  sheet.getRange(1, 1, allData.length, headers.length).setValues(allData);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  sheet.setFrozenRows(1);

  // Auto-fit columns A-H
  for (var c = 1; c <= headers.length; c++) {
    sheet.autoResizeColumn(c);
  }

  // ============================================
  // REFERENCE SECTION (columns J onward)
  // ============================================
  var refCol = 10; // Column J
  var refData = [
    // --- FORMULA TEMPLATES ---
    ['FORMULA TEMPLATES', '', ''],
    ['', '', ''],
    ['Type', 'When to Use', 'Formula (change G to your column)'],
    ['A: Monthly/Weekly', 'Row 3 = Monthly Sales, Weekly Revenue, etc.', '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(SUMIFS(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$F,6,0)),VLOOKUP(G$3,\'DB Helper\'!$A:$G,7,0),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),asin,INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$E,5,0)),TEXT(G$4,"yyyy-mm-dd")),0)))))'],
    ['B: Daily', 'Row 3 = Daily Sales, Daily Revenue, etc.', '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(SUMIFS(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),asin,INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$E,5,0)),TEXT(G$4,"yyyy-mm-dd")),0)))))'],
    ['C: Inventory', 'Row 3 = FBA Fulfillable, FBA Total, etc.', '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(SUMIFS(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),asin),0)))))'],
    ['D: Rolling/Fees', 'Row 3 = Rolling 7d Units, Price, etc.', '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(INDEX(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),MATCH(asin,INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),0)),0)))))'],
    ['', '', ''],

    // --- COUNTRY TAB SETUP ---
    ['COUNTRY TAB SETUP', '', ''],
    ['', '', ''],
    ['Cell', 'Purpose', 'Example'],
    ['B2', 'Country code', 'US'],
    ['D2', 'ASIN range (text)', 'C5:C270'],
    ['Row 3', 'Section name (must match col A exactly)', 'Monthly Sales'],
    ['Row 4', 'Date (real Date value, for date sections)', '2026-01-01'],
    ['Row 5+', 'Paste formula in row 5, BYROW fills down', ''],
    ['', '', ''],

    // --- DUMP SHEET COLUMNS ---
    ['DUMP SHEET COLUMNS', '', ''],
    ['', '', ''],
    ['SP Data (monthly/weekly)', 'Col', 'Header'],
    ['', 'A', 'data_type (monthly/weekly)'],
    ['', 'B', 'child_asin'],
    ['', 'C', 'period (yyyy-mm-dd)'],
    ['', 'D', 'units_ordered'],
    ['', 'E', 'units_ordered_b2b'],
    ['', 'F', 'ordered_product_sales'],
    ['', 'G', 'ordered_product_sales_b2b'],
    ['', 'H', 'sessions'],
    ['', 'I', 'page_views'],
    ['', 'J', 'avg_buy_box_percentage'],
    ['', 'K', 'avg_conversion_rate'],
    ['', '', ''],
    ['SP Daily (last 35 days)', 'Col', 'Header'],
    ['', 'A', 'child_asin'],
    ['', 'B', 'date (yyyy-mm-dd)'],
    ['', 'C', 'units_ordered'],
    ['', 'D', 'units_ordered_b2b'],
    ['', 'E', 'ordered_product_sales'],
    ['', 'F', 'ordered_product_sales_b2b'],
    ['', 'G', 'sessions'],
    ['', 'H', 'page_views'],
    ['', 'I', 'buy_box_percentage'],
    ['', 'J', 'unit_session_percentage'],
    ['', '', ''],
    ['SP Rolling (one row/ASIN)', 'Col', 'Header'],
    ['', 'A', 'child_asin'],
    ['', 'B', 'parent_asin'],
    ['', 'C', 'currency'],
    ['', 'D-H', '7d: units, revenue, avg_units, sessions, conversion'],
    ['', 'I-M', '14d: units, revenue, avg_units, sessions, conversion'],
    ['', 'N-R', '30d: units, revenue, avg_units, sessions, conversion'],
    ['', 'S-W', '60d: units, revenue, avg_units, sessions, conversion'],
    ['', '---', '--- APPENDED COLUMNS (after W) ---'],
    ['', 'X-AA', '7d: browser_sess, mobile_sess, browser_pv, mobile_pv'],
    ['', 'AB-AE', '14d: browser_sess, mobile_sess, browser_pv, mobile_pv'],
    ['', 'AF-AI', '30d: browser_sess, mobile_sess, browser_pv, mobile_pv'],
    ['', 'AJ-AM', '60d: browser_sess, mobile_sess, browser_pv, mobile_pv'],
    ['', 'AN-AR', '90d: units, revenue, avg_units, sessions, conversion'],
    ['', 'AS-AV', '90d: browser_sess, mobile_sess, browser_pv, mobile_pv'],
    ['', '', ''],
    ['SP Inventory (latest snapshot)', 'Col', 'Header'],
    ['', 'A', 'asin'],
    ['', 'B', 'sku'],
    ['', 'C', 'product_name'],
    ['', 'D', 'fba_fulfillable'],
    ['', 'E', 'fba_local (EU EFN)'],
    ['', 'F', 'fba_remote (EU EFN)'],
    ['', 'G', 'fba_reserved'],
    ['', 'H', 'fba_inbound_working'],
    ['', 'I', 'fba_inbound_shipped'],
    ['', 'J', 'fba_inbound_receiving'],
    ['', 'K', 'fba_unsellable'],
    ['', 'L', 'fba_total'],
    ['', 'M', 'awd_onhand (NA only)'],
    ['', 'N', 'awd_inbound'],
    ['', 'O', 'awd_available'],
    ['', 'P', 'awd_total'],
    ['', '', ''],
    ['SP Fees (latest estimates)', 'Col', 'Header'],
    ['', 'A', 'asin'],
    ['', 'B', 'sku'],
    ['', 'C', 'product_size_tier'],
    ['', 'D', 'your_price'],
    ['', 'E', 'est_fee_total'],
    ['', 'F', 'est_referral_per_unit'],
    ['', 'G', 'est_fba_per_unit'],
    ['', 'H', 'settle_avg_fba_per_unit'],
    ['', 'I', 'settle_avg_referral_per_unit'],
    ['', 'J', 'settle_fba_qty_basis'],
    ['', 'K', 'storage_fee_latest_month'],
    ['', 'L', 'storage_avg_qty_on_hand'],
    ['', '', ''],

    // --- ACCOUNT-LEVEL ROLLING CONVERSION ---
    ['ACCOUNT-LEVEL CONVERSION', '', ''],
    ['', '', ''],
    ['Period', 'Units Col', 'Formula'],
    ['7d', 'D / G', '=IFERROR(SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$D:$D"))/SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$G:$G"))*100,0)'],
    ['14d', 'I / L', '=IFERROR(SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$I:$I"))/SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$L:$L"))*100,0)'],
    ['30d', 'N / Q', '=IFERROR(SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$N:$N"))/SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$Q:$Q"))*100,0)'],
    ['60d', 'S / V', '=IFERROR(SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$S:$S"))/SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$V:$V"))*100,0)'],
    ['90d', 'AN / AQ', '=IFERROR(SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$AN:$AN"))/SUMPRODUCT(INDIRECT("\'SP Rolling "&$B$2&"\'!$AQ:$AQ"))*100,0)'],
    ['', '', ''],

    // --- DATE FORMULAS ---
    ['DATE FORMULAS', '', ''],
    ['', '', ''],
    ['Purpose', '', 'Formula'],
    ['Current month 1st', '', '=DATE(YEAR(TODAY()),MONTH(TODAY()),1)'],
    ['Previous year same month', '', '=DATE(YEAR(TODAY())-1,MONTH(TODAY()),1)'],
    ['Monday anchor (this month)', '', '=DATE(YEAR(TODAY()),MONTH(TODAY()),1)-WEEKDAY(DATE(YEAR(TODAY()),MONTH(TODAY()),1),2)+1'],
    ['Monday anchor (last year)', '', '=DATE(YEAR(TODAY())-1,MONTH(TODAY()),1)-WEEKDAY(DATE(YEAR(TODAY())-1,MONTH(TODAY()),1),2)+1'],
    ['Monday 4wk before anchor', '', '=anchor_cell-28'],
    ['Next week from any Monday', '', '=previous_cell+7'],
    ['', '', ''],

    // --- WEEKLY DATE NOTE ---
    ['IMPORTANT NOTES', '', ''],
    ['', '', ''],
    ['Note', '', 'Detail'],
    ['Weekly dates', '', 'Weeks start MONDAY (not Sunday). Match week_start dates from SP Data dump sheet.'],
    ['Monthly dates', '', 'Use 1st of month (e.g., 2026-01-01). TEXT(date,"yyyy-mm-dd") must match period in dump sheet.'],
    ['Conversion %', '', 'Already in % form (e.g., 16.67 = 16.67%). Do NOT use % cell format (would show 1667%).'],
    ['Buy Box %', '', 'Already in % form (e.g., 100 = 100%).'],
    ['Multi-SKU ASINs', '', 'Use SUMIFS (Formula C) for inventory — sums across all SKUs for the ASIN.'],
    ['Session breakdown', '', 'browser_sessions + mobile_app_sessions = sessions (total). In SP Rolling only (rolling 7/14/30/60/90d).'],
    ['Adding new sections', '', 'ALWAYS append new DB Helper rows BELOW existing ones. NEVER insert between or reorder — breaks formulas.'],
    ['Adding new dump cols', '', 'ALWAYS append new columns AFTER existing ones. NEVER insert between — shifts column letters.'],
  ];

  // Write reference section
  sheet.getRange(1, refCol, refData.length, 3).setValues(refData);

  // Bold the section headers
  for (var r = 0; r < refData.length; r++) {
    if (refData[r][0] && refData[r][1] === '' && refData[r][2] === '' && refData[r][0] === refData[r][0].toUpperCase()) {
      sheet.getRange(r + 1, refCol, 1, 3).setFontWeight('bold').setBackground('#d9ead3');
    }
    // Bold sub-headers (Type/Cell/Col rows)
    if (refData[r][0] === 'Type' || refData[r][0] === 'Cell' || refData[r][0] === 'Period' || refData[r][0] === 'Purpose' || refData[r][0] === 'Note') {
      sheet.getRange(r + 1, refCol, 1, 3).setFontWeight('bold');
    }
    // Also bold dump sheet name rows
    if (refData[r][0] && refData[r][0].indexOf('SP ') === 0) {
      sheet.getRange(r + 1, refCol, 1, 3).setFontWeight('bold').setFontStyle('italic');
    }
  }

  // Auto-fit reference columns
  for (var rc = refCol; rc <= refCol + 2; rc++) {
    sheet.autoResizeColumn(rc);
  }

  _safeAlert('DB Helper created with ' + rows.length + ' section mappings.\n\n' +
    'Reference guide added in columns J-L.\n' +
    'Includes: formula templates, dump sheet columns, date formulas, and notes.');
}


// ============================================
// FORMULA EXAMPLES
// ============================================

function showFormulaExamples() {
  var examples =
    'FORMULA REFERENCE — DB Helper Driven (No Hardcoding)\n' +
    '=====================================================\n\n' +

    'Row 3 = section name from DB Helper. $B$2 = country code. $D$2 = ASIN range.\n' +
    'LET(s,...) builds the sheet ref once: \'SP Data US\'!\n' +
    'Change G to whatever column you are placing the formula in.\n\n' +

    '=== A: MONTHLY/WEEKLY (data_type + date) ===\n' +
    'Row 3 = Monthly Sales, Weekly Revenue, etc.\n' +
    '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(SUMIFS(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$F,6,0)),VLOOKUP(G$3,\'DB Helper\'!$A:$G,7,0),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),asin,INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$E,5,0)),TEXT(G$4,"yyyy-mm-dd")),0)))))\n\n' +

    '=== B: DAILY (date, no data_type) ===\n' +
    'Row 3 = Daily Sales, Daily Revenue, etc.\n' +
    '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(SUMIFS(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),asin,INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$E,5,0)),TEXT(G$4,"yyyy-mm-dd")),0)))))\n\n' +

    '=== C: INVENTORY (SUMIFS by ASIN only) ===\n' +
    'Row 3 = FBA Fulfillable, FBA Total, AWD Total, etc.\n' +
    '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(SUMIFS(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),asin),0)))))\n\n' +

    '=== D: ROLLING/FEES (INDEX-MATCH) ===\n' +
    'Row 3 = Rolling 7d Units, Price, Product Name, etc.\n' +
    '=BYROW(INDIRECT($D$2),LAMBDA(asin,IF(asin="","",LET(s,"\'"&VLOOKUP(G$3,\'DB Helper\'!$A:$B,2,0)&" "&$B$2&"\'!",IFERROR(INDEX(INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$C,3,0)),MATCH(asin,INDIRECT(s&VLOOKUP(G$3,\'DB Helper\'!$A:$D,4,0)),0)),0)))))';

  SpreadsheetApp.getUi().alert(examples);
}
