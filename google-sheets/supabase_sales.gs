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
 * SP Rolling {country}   — Rolling 7/14/30/60-day averages (one row per ASIN)
 * SP Inventory {country} — Latest FBA + AWD inventory snapshot
 * SP Fees {country}      — Fee estimates + settlement actuals + storage fees
 *
 * === 5 TRIGGERS (per country) ===
 *
 * Each dump sheet gets its own trigger because Google Apps Script
 * has a 6-minute execution limit per run. One trigger = one dump sheet.
 *
 * Currently set up: USA only (5 triggers).
 * When ready for more countries: add trigger functions + run Setup Triggers.
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

/** Rolling 7/14/30/60-day metrics */
function getRollingMetrics(marketplaceId, config) {
  var url = config.url + '/rest/v1/sp_rolling_asin_metrics?' +
    'marketplace_id=eq.' + marketplaceId +
    '&select=child_asin,parent_asin,currency_code,units_last_7_days,revenue_last_7_days,avg_units_7_days,sessions_last_7_days,avg_conversion_7_days,units_last_14_days,revenue_last_14_days,avg_units_14_days,sessions_last_14_days,avg_conversion_14_days,units_last_30_days,revenue_last_30_days,avg_units_30_days,sessions_last_30_days,avg_conversion_30_days,units_last_60_days,revenue_last_60_days,avg_units_60_days,sessions_last_60_days,avg_conversion_60_days' +
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
      'child_asin', 'parent_asin', 'currency',
      'units_7d', 'revenue_7d', 'avg_units_7d', 'sessions_7d', 'conversion_7d',
      'units_14d', 'revenue_14d', 'avg_units_14d', 'sessions_14d', 'conversion_14d',
      'units_30d', 'revenue_30d', 'avg_units_30d', 'sessions_30d', 'conversion_30d',
      'units_60d', 'revenue_60d', 'avg_units_60d', 'sessions_60d', 'conversion_60d'
    ];

    var sheet = getOrCreateDumpSheet('SP Rolling', country, headers);

    var lastRow = sheet.getLastRow();
    if (lastRow > 1) sheet.getRange(2, 1, lastRow - 1, headers.length).clear();

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
//
// To add another country later:
//   1. Add its marketplace UUID to Script Config
//   2. Copy these 5 lines, change "US" to the new country code
//   3. Run Setup Triggers from menu

function trigger_US_sales()     { refreshSPData('US', 'US'); }
function trigger_US_daily()     { refreshDailyDumpData('US', 'US'); }
function trigger_US_rolling()   { refreshRollingData('US', 'US'); }
function trigger_US_inventory() { refreshInventoryData('US', 'US'); }
function trigger_US_fees()      { refreshFeesData('US', 'US'); }


// ============================================
// AUTO-SETUP TRIGGERS
// ============================================

/**
 * Creates time-based triggers for all CONFIGURED marketplaces.
 * Only creates triggers for countries that have a marketplace ID in Script Config.
 * Currently USA only = 5 triggers.
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
    { name: 'Rolling (7/14/30/60d)',  fn: function() { refreshRollingData(country, country); } },
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
    .addItem('Setup DB Helper', 'setupDBHelper')
    .addSeparator()
    .addSubMenu(ui.createMenu('Automation')
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
// CUSTOM FUNCTION: SPDATA()
// ============================================
// Usage in cell: =SPDATA($B$2, S$3, $C5, S$4)
//   country  = "US" (from B2)
//   section  = "Monthly Sales" (from row 3)
//   asin     = "B07..." (from column C)
//   date     = date value (from row 4) — optional for non-date sections
//
// BYROW usage (one formula per section column, spills down):
//   =BYROW(INDIRECT($D$2), LAMBDA(asin, SPDATA($B$2, S$3, asin, S$4)))
//
// DB Helper sheet defines the mapping:
//   Section Name → Sheet Prefix, Value Col, ASIN Col, Date Col, Data Type, Lookup Type

/**
 * Universal lookup into dump sheets. Replaces all SUMIFS/INDEX-MATCH formulas.
 *
 * Single cell: =SPDATA("US", "Monthly Sales", "B07ABC", DATE(2025,1,1))
 * With refs:   =SPDATA($B$2, S$3, $C5, S$4)
 *
 * @param {string} country Country code (e.g., "US")
 * @param {string} section Section name from row 3 (e.g., "Monthly Sales")
 * @param {string} asin The ASIN to look up
 * @param {date} date Optional date for time-series sections
 * @return {number} The looked-up value
 * @customfunction
 */
function SPDATA(country, section, asin, date) {
  if (!country || !section || !asin) return '';
  if (typeof asin === 'string') asin = asin.trim();
  if (!asin) return '';

  var mapping = _getDBHelperMapping(section);
  if (!mapping) return '#SECTION?';

  var sheetName = mapping.sheetPrefix + ' ' + country;
  var data = _getSheetData(sheetName);
  if (!data) return '#SHEET?';

  var lookupType = mapping.lookupType;

  // --- SUMIFS with date (monthly, weekly, daily) ---
  if (lookupType === 'sumifs_date') {
    if (!date) return 0;
    var dateStr = _formatDate(date);
    var asinCol = mapping.asinCol;
    var dateCol = mapping.dateCol;
    var valueCol = mapping.valueCol;
    var dataTypeFilter = mapping.dataType;

    var sum = 0;
    for (var i = 0; i < data.length; i++) {
      var row = data[i];
      if (String(row[asinCol]).trim() !== asin) continue;
      if (String(row[dateCol]).trim() !== dateStr) continue;
      if (dataTypeFilter && String(row[mapping.dataTypeCol]).trim() !== dataTypeFilter) continue;
      sum += parseFloat(row[valueCol]) || 0;
    }
    return sum;
  }

  // --- SUMIFS without date (inventory — multi-SKU) ---
  if (lookupType === 'sumifs') {
    var sum2 = 0;
    for (var j = 0; j < data.length; j++) {
      if (String(data[j][mapping.asinCol]).trim() !== asin) continue;
      sum2 += parseFloat(data[j][mapping.valueCol]) || 0;
    }
    return sum2;
  }

  // --- INDEX/MATCH (rolling, fees — one row per ASIN) ---
  if (lookupType === 'match') {
    for (var k = 0; k < data.length; k++) {
      if (String(data[k][mapping.asinCol]).trim() === asin) {
        return parseFloat(data[k][mapping.valueCol]) || 0;
      }
    }
    return 0;
  }

  // --- TEXT match (product name, size tier — returns string) ---
  if (lookupType === 'match_text') {
    for (var m = 0; m < data.length; m++) {
      if (String(data[m][mapping.asinCol]).trim() === asin) {
        return data[m][mapping.valueCol] || '';
      }
    }
    return '';
  }

  return '#TYPE?';
}


/**
 * Batch lookup: returns a column of values for all ASINs at once.
 * Much faster than BYROW + SPDATA because it reads data once and loops once.
 *
 * Usage: =SPCOL($B$2, G$3, INDIRECT($D$2), G$4)
 *   Returns a vertical array — one value per ASIN in the range.
 *   Place in row 5 of each section column. Spills down automatically.
 *
 * @param {string} country Country code (e.g., "US")
 * @param {string} section Section name (e.g., "Monthly Sales")
 * @param {range} asins Range of ASINs (e.g., C5:C270)
 * @param {date} date Optional date for time-series sections
 * @return {Array} Vertical array of values
 * @customfunction
 */
function SPCOL(country, section, asins, date) {
  if (!country || !section) return '';

  var mapping = _getDBHelperMapping(section);
  if (!mapping) return [['#SECTION?']];

  var sheetName = mapping.sheetPrefix + ' ' + country;
  var data = _getSheetData(sheetName);
  if (!data) return [['#SHEET?']];

  // Flatten asins to a 1D array of strings
  var asinList = [];
  if (Array.isArray(asins)) {
    for (var a = 0; a < asins.length; a++) {
      var val = Array.isArray(asins[a]) ? asins[a][0] : asins[a];
      asinList.push(String(val || '').trim());
    }
  } else {
    asinList.push(String(asins || '').trim());
  }

  var lookupType = mapping.lookupType;
  var asinCol = mapping.asinCol;
  var valueCol = mapping.valueCol;
  var dateCol = mapping.dateCol;
  var dataTypeCol = mapping.dataTypeCol;
  var dataTypeFilter = mapping.dataType;

  // --- Build index for fast lookup ---
  if (lookupType === 'sumifs_date') {
    var dateStr = date ? _formatDate(date) : '';
    if (!dateStr) {
      var zeroes = [];
      for (var z = 0; z < asinList.length; z++) zeroes.push([0]);
      return zeroes;
    }

    // Build: {asin: sum}
    var sumMap = {};
    for (var i = 0; i < data.length; i++) {
      var row = data[i];
      if (String(row[dateCol]).trim() !== dateStr) continue;
      if (dataTypeFilter && String(row[dataTypeCol]).trim() !== dataTypeFilter) continue;
      var rAsin = String(row[asinCol]).trim();
      sumMap[rAsin] = (sumMap[rAsin] || 0) + (parseFloat(row[valueCol]) || 0);
    }

    var result = [];
    for (var r = 0; r < asinList.length; r++) {
      result.push([sumMap[asinList[r]] || 0]);
    }
    return result;
  }

  if (lookupType === 'sumifs') {
    var sumMap2 = {};
    for (var j = 0; j < data.length; j++) {
      var rAsin2 = String(data[j][asinCol]).trim();
      sumMap2[rAsin2] = (sumMap2[rAsin2] || 0) + (parseFloat(data[j][valueCol]) || 0);
    }
    var result2 = [];
    for (var r2 = 0; r2 < asinList.length; r2++) {
      result2.push([sumMap2[asinList[r2]] || 0]);
    }
    return result2;
  }

  if (lookupType === 'match') {
    var matchMap = {};
    for (var k = 0; k < data.length; k++) {
      var rAsin3 = String(data[k][asinCol]).trim();
      if (!(rAsin3 in matchMap)) {
        matchMap[rAsin3] = parseFloat(data[k][valueCol]) || 0;
      }
    }
    var result3 = [];
    for (var r3 = 0; r3 < asinList.length; r3++) {
      result3.push([matchMap[asinList[r3]] || 0]);
    }
    return result3;
  }

  if (lookupType === 'match_text') {
    var textMap = {};
    for (var m = 0; m < data.length; m++) {
      var rAsin4 = String(data[m][asinCol]).trim();
      if (!(rAsin4 in textMap)) {
        textMap[rAsin4] = data[m][valueCol] || '';
      }
    }
    var result4 = [];
    for (var r4 = 0; r4 < asinList.length; r4++) {
      result4.push([textMap[asinList[r4]] || '']);
    }
    return result4;
  }

  return [['#TYPE?']];
}


/**
 * Reads the DB Helper sheet and returns config for one section.
 * Caches the full DB Helper in script-level var to avoid re-reading per cell.
 */
var _dbHelperCache = null;
function _getDBHelperMapping(section) {
  if (!_dbHelperCache) {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var helper = ss.getSheetByName('DB Helper');
    if (!helper) return null;

    var data = helper.getDataRange().getValues();
    _dbHelperCache = {};
    // Row 0 = headers: Section | Sheet Prefix | Value Col | ASIN Col | Date Col | Data Type Col | Data Type | Lookup Type
    for (var i = 1; i < data.length; i++) {
      var row = data[i];
      var name = String(row[0]).trim();
      if (!name) continue;
      _dbHelperCache[name] = {
        sheetPrefix: String(row[1]).trim(),
        valueCol:    parseInt(row[2], 10),    // 0-indexed column number
        asinCol:     parseInt(row[3], 10),
        dateCol:     parseInt(row[4], 10) || 0,
        dataTypeCol: parseInt(row[5], 10) || 0,
        dataType:    String(row[6] || '').trim(),
        lookupType:  String(row[7]).trim()    // sumifs_date, sumifs, match, match_text
      };
    }
  }
  return _dbHelperCache[section] || null;
}


/**
 * Caches sheet data in memory per execution (custom functions run many times).
 * Without this, each cell call would re-read the sheet.
 */
var _sheetDataCache = {};
function _getSheetData(sheetName) {
  if (!(sheetName in _sheetDataCache)) {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      _sheetDataCache[sheetName] = null;
      return null;
    }
    var lastRow = sheet.getLastRow();
    if (lastRow <= 1) {
      _sheetDataCache[sheetName] = [];
      return [];
    }
    _sheetDataCache[sheetName] = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
  }
  return _sheetDataCache[sheetName];
}


/**
 * Formats a date value to YYYY-MM-DD string for matching dump sheet data.
 */
function _formatDate(date) {
  if (date instanceof Date) {
    var y = date.getFullYear();
    var m = String(date.getMonth() + 1).padStart(2, '0');
    var d = String(date.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + d;
  }
  // Already a string
  return String(date).trim().substring(0, 10);
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

  var headers = ['Section', 'Sheet Prefix', 'Value Col', 'ASIN Col', 'Date Col', 'DataType Col', 'Data Type', 'Lookup Type'];

  // All section mappings
  // Col numbers are 0-indexed: SP Data US → A=0(data_type) B=1(asin) C=2(period) D=3(units) E=4(units_b2b) F=5(revenue) ...
  var rows = [
    // === SP Data (monthly) ===
    ['Monthly Sales',        'SP Data', 3, 1, 2, 0, 'monthly', 'sumifs_date'],
    ['Monthly Sales B2B',    'SP Data', 4, 1, 2, 0, 'monthly', 'sumifs_date'],
    ['Monthly Revenue',      'SP Data', 5, 1, 2, 0, 'monthly', 'sumifs_date'],
    ['Monthly Revenue B2B',  'SP Data', 6, 1, 2, 0, 'monthly', 'sumifs_date'],
    ['Monthly Sessions',     'SP Data', 7, 1, 2, 0, 'monthly', 'sumifs_date'],
    ['Monthly Page Views',   'SP Data', 8, 1, 2, 0, 'monthly', 'sumifs_date'],
    ['Monthly Buy Box %',    'SP Data', 9, 1, 2, 0, 'monthly', 'sumifs_date'],
    ['Monthly Conversion %', 'SP Data', 10, 1, 2, 0, 'monthly', 'sumifs_date'],

    // === SP Data (weekly) ===
    ['Weekly Sales',        'SP Data', 3, 1, 2, 0, 'weekly', 'sumifs_date'],
    ['Weekly Sales B2B',    'SP Data', 4, 1, 2, 0, 'weekly', 'sumifs_date'],
    ['Weekly Revenue',      'SP Data', 5, 1, 2, 0, 'weekly', 'sumifs_date'],
    ['Weekly Revenue B2B',  'SP Data', 6, 1, 2, 0, 'weekly', 'sumifs_date'],
    ['Weekly Sessions',     'SP Data', 7, 1, 2, 0, 'weekly', 'sumifs_date'],
    ['Weekly Page Views',   'SP Data', 8, 1, 2, 0, 'weekly', 'sumifs_date'],
    ['Weekly Buy Box %',    'SP Data', 9, 1, 2, 0, 'weekly', 'sumifs_date'],
    ['Weekly Conversion %', 'SP Data', 10, 1, 2, 0, 'weekly', 'sumifs_date'],

    // === SP Daily ===
    ['Daily Sales',        'SP Daily', 2, 0, 1, '', '', 'sumifs_date'],
    ['Daily Sales B2B',    'SP Daily', 3, 0, 1, '', '', 'sumifs_date'],
    ['Daily Revenue',      'SP Daily', 4, 0, 1, '', '', 'sumifs_date'],
    ['Daily Revenue B2B',  'SP Daily', 5, 0, 1, '', '', 'sumifs_date'],
    ['Daily Sessions',     'SP Daily', 6, 0, 1, '', '', 'sumifs_date'],
    ['Daily Page Views',   'SP Daily', 7, 0, 1, '', '', 'sumifs_date'],
    ['Daily Buy Box %',    'SP Daily', 8, 0, 1, '', '', 'sumifs_date'],
    ['Daily Conversion %', 'SP Daily', 9, 0, 1, '', '', 'sumifs_date'],

    // === SP Rolling (no date — one row per ASIN) ===
    ['Rolling 7d Units',       'SP Rolling', 3, 0, '', '', '', 'match'],
    ['Rolling 7d Revenue',     'SP Rolling', 4, 0, '', '', '', 'match'],
    ['Rolling 7d Avg Units',   'SP Rolling', 5, 0, '', '', '', 'match'],
    ['Rolling 7d Sessions',    'SP Rolling', 6, 0, '', '', '', 'match'],
    ['Rolling 7d Conversion',  'SP Rolling', 7, 0, '', '', '', 'match'],
    ['Rolling 14d Units',      'SP Rolling', 8, 0, '', '', '', 'match'],
    ['Rolling 14d Revenue',    'SP Rolling', 9, 0, '', '', '', 'match'],
    ['Rolling 14d Avg Units',  'SP Rolling', 10, 0, '', '', '', 'match'],
    ['Rolling 14d Sessions',   'SP Rolling', 11, 0, '', '', '', 'match'],
    ['Rolling 14d Conversion', 'SP Rolling', 12, 0, '', '', '', 'match'],
    ['Rolling 30d Units',      'SP Rolling', 13, 0, '', '', '', 'match'],
    ['Rolling 30d Revenue',    'SP Rolling', 14, 0, '', '', '', 'match'],
    ['Rolling 30d Avg Units',  'SP Rolling', 15, 0, '', '', '', 'match'],
    ['Rolling 30d Sessions',   'SP Rolling', 16, 0, '', '', '', 'match'],
    ['Rolling 30d Conversion', 'SP Rolling', 17, 0, '', '', '', 'match'],
    ['Rolling 60d Units',      'SP Rolling', 18, 0, '', '', '', 'match'],
    ['Rolling 60d Revenue',    'SP Rolling', 19, 0, '', '', '', 'match'],
    ['Rolling 60d Avg Units',  'SP Rolling', 20, 0, '', '', '', 'match'],
    ['Rolling 60d Sessions',   'SP Rolling', 21, 0, '', '', '', 'match'],
    ['Rolling 60d Conversion', 'SP Rolling', 22, 0, '', '', '', 'match'],

    // === SP Inventory (no date — SUMIFS for multi-SKU) ===
    ['FBA Fulfillable',  'SP Inventory', 3, 0, '', '', '', 'sumifs'],
    ['FBA Local',        'SP Inventory', 4, 0, '', '', '', 'sumifs'],
    ['FBA Remote',       'SP Inventory', 5, 0, '', '', '', 'sumifs'],
    ['FBA Reserved',     'SP Inventory', 6, 0, '', '', '', 'sumifs'],
    ['FBA Inbound Work', 'SP Inventory', 7, 0, '', '', '', 'sumifs'],
    ['FBA Inbound Ship', 'SP Inventory', 8, 0, '', '', '', 'sumifs'],
    ['FBA Inbound Recv', 'SP Inventory', 9, 0, '', '', '', 'sumifs'],
    ['FBA Unsellable',   'SP Inventory', 10, 0, '', '', '', 'sumifs'],
    ['FBA Total',        'SP Inventory', 11, 0, '', '', '', 'sumifs'],
    ['AWD On-hand',      'SP Inventory', 12, 0, '', '', '', 'sumifs'],
    ['AWD Inbound',      'SP Inventory', 13, 0, '', '', '', 'sumifs'],
    ['AWD Available',    'SP Inventory', 14, 0, '', '', '', 'sumifs'],
    ['AWD Total',        'SP Inventory', 15, 0, '', '', '', 'sumifs'],
    ['Product Name',     'SP Inventory', 2, 0, '', '', '', 'match_text'],

    // === SP Fees (no date — one row per ASIN) ===
    ['Size Tier',            'SP Fees', 2, 0, '', '', '', 'match_text'],
    ['Price',                'SP Fees', 3, 0, '', '', '', 'match'],
    ['Est Fee Total',        'SP Fees', 4, 0, '', '', '', 'match'],
    ['Est Referral Fee',     'SP Fees', 5, 0, '', '', '', 'match'],
    ['Est FBA Fee',          'SP Fees', 6, 0, '', '', '', 'match'],
    ['Settle Avg FBA Fee',   'SP Fees', 7, 0, '', '', '', 'match'],
    ['Settle Avg Referral',  'SP Fees', 8, 0, '', '', '', 'match'],
    ['Settle FBA Qty Basis', 'SP Fees', 9, 0, '', '', '', 'match'],
    ['Storage Fee',          'SP Fees', 10, 0, '', '', '', 'match'],
    ['Storage Avg Qty',      'SP Fees', 11, 0, '', '', '', 'match'],

    // === Aliases (match user's existing row 3 names) ===
    ['Storage',              'SP Fees', 10, 0, '', '', '', 'match'],
  ];

  // Write headers + data
  var allData = [headers].concat(rows);
  sheet.getRange(1, 1, allData.length, headers.length).setValues(allData);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold');
  sheet.setFrozenRows(1);

  // Auto-fit columns
  for (var c = 1; c <= headers.length; c++) {
    sheet.autoResizeColumn(c);
  }

  _safeAlert('DB Helper created with ' + rows.length + ' section mappings.\n\n' +
    'Now use =SPDATA($B$2, S$3, $C5, S$4) in country tab cells.\n\n' +
    'BYROW (spills down all ASINs):\n' +
    '=BYROW(INDIRECT($D$2), LAMBDA(a, SPDATA($B$2, S$3, a, S$4)))');
}


// ============================================
// FORMULA EXAMPLES
// ============================================

function showFormulaExamples() {
  var examples =
    'FORMULA REFERENCE — SPDATA() CUSTOM FUNCTION\n' +
    '==============================================\n\n' +

    'SETUP:\n' +
    '  1. Run: Menu > Supabase Data > Setup DB Helper\n' +
    '  2. Country tab: B2=country code, D2=ASIN range (e.g., C5:C270)\n' +
    '  3. Row 3 = section names, Row 4 = dates\n\n' +

    '=== SPCOL — BATCH COLUMN (RECOMMENDED) ===\n' +
    '=SPCOL($B$2, G$3, INDIRECT($D$2), G$4)\n\n' +

    '  $B$2 = country (US)\n' +
    '  G$3  = section name (Monthly Sales)\n' +
    '  INDIRECT($D$2) = ASIN range\n' +
    '  G$4  = date (omit for inventory/fees/rolling)\n\n' +

    '  Put in row 5 of each section column.\n' +
    '  Spills down for all ASINs. No dragging.\n' +
    '  One formula per column = fast.\n\n' +

    '=== SPDATA — SINGLE CELL ===\n' +
    '=SPDATA($B$2, S$3, $C5, S$4)\n\n' +

    '  Use for one-off cells or debugging.\n\n' +

    '=== SECTION NAMES (Row 3) ===\n' +
    'Monthly: Monthly Sales, Monthly Revenue, Monthly Sessions...\n' +
    'Weekly:  Weekly Sales, Weekly Revenue, Weekly Sessions...\n' +
    'Daily:   Daily Sales, Daily Revenue, Daily Sessions...\n' +
    'Rolling: Rolling 7d Units, Rolling 30d Revenue...\n' +
    'Stock:   FBA Fulfillable, FBA Total, AWD On-hand...\n' +
    'Fees:    Est Fee Total, Storage Fee, Settle Avg FBA Fee...\n' +
    'Text:    Product Name, Size Tier\n\n' +

    'Full list: see DB Helper sheet.\n\n' +

    '=== TO ADD A COUNTRY ===\n' +
    '1. Menu > Refresh One Country (creates dump sheets)\n' +
    '2. Menu > Duplicate Country Tab (copies formulas)\n' +
    '   All formulas auto-adjust — only B2 changes.';

  SpreadsheetApp.getUi().alert(examples);
}
