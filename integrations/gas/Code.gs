/**
 * ============================================================================
 *  Отчёты УНФ → Telegram + Google Sheets   (внешний слой, Google Apps Script)
 * ============================================================================
 *
 *  Что делает этот скрипт:
 *   1) Читает данные из OData обеих облачных баз 1С:УНФ (Перфильев, Губарев).
 *   2) Считает показатели (продажи, дебиторка, взаиморасчёты, активность клиентов).
 *   3) Заполняет КОНКРЕТНЫЕ ЯЧЕЙКИ листа DASHBOARD и отправляет
 *      ТЕКСТОВУЮ сводку в Telegram (sendMessage).
 *   4) По таймтриггерам (09:30 ежедневно + периодические) генерирует отчёты.
 *   5) Обрабатывает команды бота (/today, /range) через Telegram webhook.
 *
 *  --------------------------------------------------------------------------
 *  НАСТРОЙКА ПЕРЕД ЗАПУСКОМ (делается один раз):
 *  --------------------------------------------------------------------------
 *  A. Создайте Google-таблицу. Из её адреса возьмите SHEET_ID.
 *  B. В редакторе Apps Script: «Настройки проекта» → «Свойства скрипта»
 *     Добавьте:
 *        TELEGRAM_TOKEN   = токен бота
 *        SHEET_ID         = ID таблицы
 *        AUTH_TOKEN       = общий секрет (для совместимости)
 *        ALLOWED_CHATS    = разрешённые chat_id
 *        ODATA_USER       = логин для 1С OData (api_bot)
 *        ODATA_PASS       = пароль для 1С OData
 *  C. Разверните как Web App: доступ = «Все».
 *  D. Выполните initSheets() один раз.
 * ============================================================================
 */

// ─────────────────────────────────────────────────────────────────────────
//  КОНФИГУРАЦИЯ
// ─────────────────────────────────────────────────────────────────────────

const PROPS = PropertiesService.getScriptProperties();

const CONFIG = {
  TELEGRAM_TOKEN: PROPS.getProperty('TELEGRAM_TOKEN') || '',
  SHEET_ID:       PROPS.getProperty('SHEET_ID') || '',
  AUTH_TOKEN:     PROPS.getProperty('AUTH_TOKEN') || '',
  ALLOWED_CHATS: (PROPS.getProperty('ALLOWED_CHATS') || '')
                   .split(',').map(s => s.trim()).filter(Boolean),
  ODATA_USER:     PROPS.getProperty('ODATA_USER') || '',
  ODATA_PASS:     PROPS.getProperty('ODATA_PASS') || '',
  TIMEZONE: 'Europe/Moscow',
  ODATA_BASES: {
    perfilev: 'https://base.42clouds.com/unf/152757/odata/standard.odata/',
    gubarev:  'https://base.42clouds.com/unf/64904/odata/standard.odata/',
  },
  BASE_TITLE: { perfilev: 'Перфильев', gubarev: 'Губарев' },
  OVERDUE_DAYS: 30,
  ACTIVITY_GROWTH_PCT: 20,
  ACTIVITY_DECLINE_PCT: 50,
};

const SHEETS = {
  RAW:       { perfilev: 'RAW_perfilev', gubarev: 'RAW_gubarev' },
  DASHBOARD: 'DASHBOARD',
  LOG:       'LOG',
  QUEUE:     'QUEUE',
};

const CELL_MAP = {
  period_label:        'B2',
  sales_total:         { perfilev: 'C5',  gubarev: 'D5',  total: 'E5'  },
  sales_dyn_pct:       { perfilev: 'C6',  gubarev: 'D6',  total: 'E6'  },
  sales_avg_per_day:   { perfilev: 'C7',  gubarev: 'D7',  total: 'E7'  },
  sales_forecast:      { perfilev: 'C8',  gubarev: 'D8',  total: 'E8'  },
  settle_they_owe_us:  { perfilev: 'C11', gubarev: 'D11', total: 'E11' },
  settle_we_owe:       { perfilev: 'C12', gubarev: 'D12', total: 'E12' },
  recv_total:          { perfilev: 'C15', gubarev: 'D15', total: 'E15' },
  recv_overdue:        { perfilev: 'C16', gubarev: 'D16', total: 'E16' },
};

// ─────────────────────────────────────────────────────────────────────────
//  OData КЛИЕНТ
// ─────────────────────────────────────────────────────────────────────────

function buildBasicAuth() {
  const creds = CONFIG.ODATA_USER + ':' + CONFIG.ODATA_PASS;
  return 'Basic ' + Utilities.base64Encode(creds);
}

function fetchWithRetry(url, headers = {}, retries = 3) {
  headers.Authorization = buildBasicAuth();
  headers.Accept = 'application/json';

  for (let i = 0; i < retries; i++) {
    try {
      const resp = UrlFetchApp.fetch(url, {
        method: 'get',
        headers: headers,
        muteHttpExceptions: true,
      });

      const code = resp.getResponseCode();
      if (code === 200) {
        return JSON.parse(resp.getContentText());
      }
      if (code === 401) {
        throw new Error('OData 401 Unauthorized — проверь ODATA_USER/ODATA_PASS');
      }
      if (code === 404) {
        throw new Error('OData 404 Not Found — ' + url);
      }
      if (i < retries - 1) {
        Utilities.sleep(2000);
        continue;
      }
      throw new Error('OData HTTP ' + code);
    } catch (err) {
      if (i === retries - 1) throw err;
      Utilities.sleep(2000);
    }
  }
}

function fetchAllODataRecords(baseId, entityName, options = {}) {
  const results = [];
  let url = CONFIG.ODATA_BASES[baseId] + entityName;
  let queryParts = [];
  if (options.select) queryParts.push('$select=' + options.select);
  if (options.filter) queryParts.push('$filter=' + options.filter);
  if (queryParts.length) url += '?' + queryParts.join('&');

  let attempts = 0;
  const maxAttempts = 50;  // Уменьшено с 1000 до 50 для timeout защиты
  let pageCount = 0;
  const maxRecords = 50000;  // Лимит записей

  while (url && attempts < maxAttempts && results.length < maxRecords) {
    attempts++;
    pageCount++;
    try {
      const data = fetchWithRetry(url);
      if (!data || !data.value) break;
      results.push(...data.value);
      url = data['@odata.nextLink'];

      if (results.length >= maxRecords) {
        Logger.log(`Reached max records limit: ${results.length}`);
        break;
      }
    } catch (e) {
      Logger.log(`Error fetching page ${pageCount}: ${e}`);
      break;
    }
  }

  Logger.log(`Total pages: ${pageCount}, total records: ${results.length}`);
  return results;
}

function getContractorNames(baseId) {
  const catalog = fetchAllODataRecords(baseId, 'Catalog_Контрагенты', {
    select: 'Ref_Key,Description',
  });

  const map = {};
  catalog.forEach(c => {
    map[c.Ref_Key] = c.Description || 'Unknown';
  });
  return map;
}

// ─────────────────────────────────────────────────────────────────────────
//  СЛУЖЕБНАЯ ФУНКЦИЯ: тест одной базы с детальной диагностикой
// ─────────────────────────────────────────────────────────────────────────

function testODataOneBase() {
  const baseId = 'perfilev';
  const testDate = '2026-06-23'; // Проверяем 23 июня
  const nextDate = '2026-06-24';

  Logger.log('═══════════════════════════════════════════════════════════════');
  Logger.log('🔍 ДИАГНОСТИКА OData для ' + CONFIG.BASE_TITLE[baseId]);
  Logger.log('═══════════════════════════════════════════════════════════════');
  Logger.log('Дата проверки: ' + testDate);
  Logger.log('');

  logRow('TEST', baseId, 'start', 'Reading sales for ' + testDate);

  try {
    Logger.log('\n📋 ЗАГРУЗКА СПРАВОЧНИКА КОНТРАГЕНТОВ...');
    const contractorNames = getContractorNames(baseId);
    Logger.log('✅ Загружено контрагентов: ' + Object.keys(contractorNames).length);

    Logger.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    Logger.log('📊 ОТЧЁТ №1: ПРОДАЖИ ЗА ' + testDate);
    Logger.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    Logger.log('Эталон из 1С: 23 239,00 ₽');
    Logger.log('');

    const sales = fetchAllODataRecords(baseId, 'AccumulationRegister_Продажи_RecordType', {
      filter: `Period ge datetime'${testDate}T00:00:00' and Period lt datetime'${nextDate}T00:00:00'`,
    });

    Logger.log('Всего записей в OData: ' + sales.length);

    // Debug: breakdown by Recorder_Type and Active
    Logger.log('\n📋 РАЗБОР СТРУКТУРЫ:');
    const byRecorderType = {};
    const byActive = {};
    const byRecordType = {};
    sales.forEach(r => {
      const recorderType = r.Recorder_Type || 'unknown';
      const active = r.Active !== false ? 'true' : 'false';
      const recordType = r.RecordType || 'unknown';
      byRecorderType[recorderType] = (byRecorderType[recorderType] || 0) + 1;
      byActive[active] = (byActive[active] || 0) + 1;
      byRecordType[recordType] = (byRecordType[recordType] || 0) + 1;
    });

    Logger.log('По Recorder_Type (тип документа):');
    Object.entries(byRecorderType).forEach(([type, count]) => {
      Logger.log(`  ${type}: ${count}`);
    });
    Logger.log('По Active:');
    Object.entries(byActive).forEach(([active, count]) => {
      Logger.log(`  ${active}: ${count}`);
    });
    Logger.log('По RecordType:');
    Object.entries(byRecordType).forEach(([type, count]) => {
      Logger.log(`  ${type}: ${count}`);
    });

    let totalSales = 0;
    let receiptCount = 0;
    const salesByContractor = {};
    sales.forEach(r => {
      const recordType = r.RecordType || 'Receipt';
      if (recordType !== 'Receipt') return;
      receiptCount++;
      const sum = r.Сумма || 0;
      totalSales += sum;
      const key = r.Контрагент_Key || 'unknown';
      salesByContractor[key] = (salesByContractor[key] || 0) + sum;
    });

    Logger.log('\n✅ ИТОГО (RecordType=Receipt):');
    Logger.log('   Записей: ' + receiptCount);
    Logger.log('   Сумма: ' + fmtMoney(totalSales));
    Logger.log('⚖️  Эталон из 1С: 23 239,00 ₽');
    Logger.log('📊 Разница: ' + fmtMoney(totalSales - 23239));
    Logger.log('\n🏆 ТОП-5 ПОКУПАТЕЛЕЙ:');
    const topSales = Object.entries(salesByContractor)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    const expectedTop = [
      { name: 'ФРЕСА', amount: 7050 },
      { name: 'Санфрутбери', amount: 4223 },
      { name: 'А 81', amount: 3048 }
    ];

    topSales.forEach(([key, sum], idx) => {
      const name = contractorNames[key] || 'Unknown (' + key + ')';
      const expected = expectedTop[idx];
      const match = expected ? (Math.abs(sum - expected.amount) < 1 ? '✅' : '❌') : '';
      Logger.log(`  ${idx + 1}. ${name}: ${fmtMoney(sum)} ${match}`);
    });

    Logger.log('\n=== SETTLEMENTS (BALANCE BY CONTRACT = SUM(positive by договор)) ===');
    const settlements = fetchAllODataRecords(baseId, 'AccumulationRegister_РасчетыСПокупателями_RecordType', {
      filter: `Period le datetime'${tomorrow}T00:00:00'`,
    });

    Logger.log('💼 Total settlements records (movements): ' + settlements.length);

    // Структура: { контрагент: { договор: { receipt, expense } } }
    const settlementsByContractorAndDeal = {};
    settlements.forEach(r => {
      const ctgKey = r.Контрагент_Key || 'unknown';
      const dealKey = r.Договор_Key || 'nodeal';
      const sum = r.Сумма || 0;
      const recordType = r.RecordType || 'Receipt';

      if (!settlementsByContractorAndDeal[ctgKey]) settlementsByContractorAndDeal[ctgKey] = {};
      if (!settlementsByContractorAndDeal[ctgKey][dealKey]) {
        settlementsByContractorAndDeal[ctgKey][dealKey] = { receipt: 0, expense: 0 };
      }

      if (recordType === 'Receipt') {
        settlementsByContractorAndDeal[ctgKey][dealKey].receipt += sum;
      } else if (recordType === 'Expense') {
        settlementsByContractorAndDeal[ctgKey][dealKey].expense += sum;
      }
    });

    // Для каждого контрагента: сумма только ПОЛОЖИТЕЛЬНЫХ остатков по договорам (долги)
    const debtByContractor = {};
    Object.entries(settlementsByContractorAndDeal).forEach(([ctgKey, deals]) => {
      let contractorDebt = 0;
      Object.entries(deals).forEach(([dealKey, { receipt, expense }]) => {
        const dealBalance = receipt - expense;
        if (dealBalance > 0) {
          contractorDebt += dealBalance; // Только долги, авансы не вычитаем
        }
      });
      if (contractorDebt > 0) {
        debtByContractor[ctgKey] = contractorDebt;
      }
    });

    const totalDebt = Object.values(debtByContractor).reduce((sum, val) => sum + val, 0);
    Logger.log('\n💳 TOTAL DEBT (sum of positive contract balances): ' + fmtMoney(totalDebt));
    Logger.log('⚖️ Expected from 1С: ≈ 1 457 629 ₽');

    Logger.log('\nTop 5 contractors by debt (with names):');
    Object.entries(debtByContractor)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .forEach(([key, sum]) => {
        const name = contractorNames[key] || 'Unknown (' + key + ')';
        Logger.log('  ' + name + ': ' + fmtMoney(sum));
      });


    // DEBUG: А 81 и Кросс док Слава — почему нулевой нетто?
    Logger.log('\n=== DEBUG: RECEIPT vs EXPENSE FOR А 81 & КРОСС ДОК СЛАВА ===');
    ['А 81 (перевод)', 'Кросс док Слава (наличка)'].forEach(pattern => {
      const key = Object.entries(contractorNames).find(([k, v]) => v.includes(pattern))?.[0];
      if (!key) {
        Logger.log(`❌ ${pattern} not found`);
        return;
      }

      Logger.log(`\n📊 ${pattern}:`);
      const contractorSettlements = settlements.filter(r => r.Контрагент_Key === key);
      Logger.log(`Total records: ${contractorSettlements.length}`);

      let receipt = 0, expense = 0;
      const recordTypes = new Set();
      contractorSettlements.forEach(r => {
        const rt = r.RecordType || 'Unknown';
        recordTypes.add(rt);
        const sum = r.Сумма || 0;
        if (rt === 'Receipt') receipt += sum;
        else if (rt === 'Expense') expense += sum;
      });

      Logger.log(`Receipt types found: ${JSON.stringify(Array.from(recordTypes))}`);
      Logger.log(`Receipt: ${fmtMoney(receipt)}`);
      Logger.log(`Expense: ${fmtMoney(expense)}`);
      Logger.log(`Balance: ${fmtMoney(receipt - expense)}`);
      Logger.log(`Expected from 1С: ${pattern.includes('А 81') ? '305 498' : '158 350'}`);
    });

    logRow('TEST', baseId, 'success', 'Sales: ' + fmtMoney(totalSales) + ', Settlements: ' + settlements.length);
  } catch (err) {
    logRow('TEST', baseId, 'error', err.toString());
    Logger.log('ERROR: ' + err.toString());
    throw err;
  }
}

// ─────────────────────────────────────────────────────────────────────────
//  WEB APP ENTRY
// ─────────────────────────────────────────────────────────────────────────

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);

    Logger.log('[doPost] Received update: ' + (body.update_id || 'no update_id'));

    if (body.action === 'setup-webhook' && body.auth_token === CONFIG.AUTH_TOKEN) {
      const result = setWebhook();
      return jsonOut({ ok: true, webhook_setup: result });
    }

    if (body.update_id !== undefined) {
      handleTelegramUpdate(body);
      // ВАЖНО: Всегда возвращаем 200 OK для Telegram
      return ContentService.createTextOutput(JSON.stringify({ ok: true }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    if (body.auth_token !== CONFIG.AUTH_TOKEN) {
      return jsonOut({ ok: false, error: 'unauthorized' });
    }

    switch (body.action) {
      case 'ingest':        return jsonOut(handleIngest(body));
      case 'pull-commands': return jsonOut(handlePull(body));
      default:              return jsonOut({ ok: false, error: 'unknown action' });
    }
  } catch (err) {
    Logger.log('[doPost] ERROR: ' + err);
    logRow('ERROR', '', '', 'doPost: ' + err);
    // Всё равно возвращаем OK для Telegram
    return ContentService.createTextOutput(JSON.stringify({ ok: true }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  if (e && e.parameter && e.parameter.setup === 'webhook') {
    const result = setWebhook();
    return jsonOut({ ok: true, webhook_setup: result });
  }
  return jsonOut({ ok: true, service: 'UNF reports layer', time: now() });
}

function jsonOut(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// ─────────────────────────────────────────────────────────────────────────
//  INGEST (совместимость с 1С)
// ─────────────────────────────────────────────────────────────────────────

function handleIngest(body) {
  const baseId = body.base_id;
  const key = periodKey(body.report_type, body.period_start, body.period_end, body.request_id);

  saveRaw(baseId, body);
  PROPS.setProperty('PEND::' + key + '::' + baseId, JSON.stringify(body));

  logRow('INGEST', baseId, body.report_type, 'period ' + body.period_start + '..' + body.period_end);

  const a = PROPS.getProperty('PEND::' + key + '::perfilev');
  const b = PROPS.getProperty('PEND::' + key + '::gubarev');

  if (a && b) {
    finalizeReport(key, JSON.parse(a), JSON.parse(b), null);
  } else {
    if (!PROPS.getProperty('PEND_TS::' + key)) {
      PROPS.setProperty('PEND_TS::' + key, String(Date.now()));
    }
  }
  return { ok: true };
}

function finalizeReport(key, payloadA, payloadB, partialBase) {
  const present = [payloadA, payloadB].filter(Boolean);
  const sample = present[0];

  const combined = combineMetrics(payloadA, payloadB);
  const periodLabel = humanPeriod(sample.report_type, sample.period_start, sample.period_end);

  fillDashboard(periodLabel, payloadA, payloadB, combined);

  const text = buildText(periodLabel, payloadA, payloadB, combined, partialBase);
  const chatId = sample.request_id ? sample.chat_id : null;
  sendReport(text, chatId);

  ['perfilev', 'gubarev'].forEach(b => PROPS.deleteProperty('PEND::' + key + '::' + b));
  PROPS.deleteProperty('PEND_TS::' + key);

  logRow('REPORT', partialBase ? 'partial' : 'full', sample.report_type, periodLabel);
}

function combineMetrics(a, b) {
  const ma = a ? a.metrics : null;
  const mb = b ? b.metrics : null;
  const g = (m, path, d) => {
    try { return path.split('.').reduce((o, k) => o[k], m); } catch (e) { return d; }
  };
  const sum = (path) => (g(ma, path, 0) || 0) + (g(mb, path, 0) || 0);

  const salesTotal = sum('sales.total');
  const salesPrev  = sum('sales.prev_total');
  return {
    settlements: { they_owe_us: sum('settlements.they_owe_us'), we_owe: sum('settlements.we_owe') },
    sales: {
      total: salesTotal,
      prev_total: salesPrev,
      dynamics_pct: salesPrev ? Math.round((salesTotal - salesPrev) / salesPrev * 100) : 0,
      avg_per_day: sum('sales.avg_per_day'),
      forecast_turnover: sum('sales.forecast_turnover'),
    },
    receivables: { total: sum('receivables.total'), overdue: sum('receivables.overdue') },
  };
}

// ─────────────────────────────────────────────────────────────────────────
//  TELEGRAM
// ─────────────────────────────────────────────────────────────────────────

function sendReport(text, chatId) {
  const targets = chatId ? [String(chatId)] : CONFIG.ALLOWED_CHATS;
  targets.forEach(id => sendMessage(id, text));
}

function sendMessage(chatId, text) {
  const chunks = splitText(text, 3900);
  chunks.forEach(part => {
    const url = `https://api.telegram.org/bot${CONFIG.TELEGRAM_TOKEN}/sendMessage`;
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      muteHttpExceptions: true,
      payload: JSON.stringify({
        chat_id: chatId,
        text: part,
        parse_mode: 'HTML',
        disable_web_page_preview: true,
      }),
    });
    if (resp.getResponseCode() !== 200) {
      logRow('ERROR', 'telegram', '', resp.getContentText());
    }
  });
}

function handleTelegramUpdate(update) {
  if (!update || !update.update_id) {
    Logger.log('[handleTelegramUpdate] Empty update received');
    return;
  }
  var _uid = String(update.update_id || '');
  var _c = CacheService.getScriptCache();
  if (_uid && _c.get('u'+_uid)) return;
  if (_uid) _c.put('u'+_uid, '1', 600);
  const msg = update.message || update.edited_message;
  if (!msg || !msg.text) return;

  const chatId = String(msg.chat.id);
  if (CONFIG.ALLOWED_CHATS.length && CONFIG.ALLOWED_CHATS.indexOf(chatId) === -1) {
    sendMessage(chatId, '⛔ Доступ ограничен.');
    return;
  }

  const text = msg.text.trim();
  const [cmd, ...args] = text.split(/\s+/);

  switch (cmd) {
    case '/start':
    case '/help':
      sendMessage(chatId, helpText());
      break;

    case '/today':
      enqueueCommand({ chat_id: chatId, report_type: 'ondemand',
        period_start: today(), period_end: today() });
      sendMessage(chatId, '⏳ Готовлю отчёт.');
      break;

    case '/range': {
      const from = parseDate(args[0]), to = parseDate(args[1]);
      if (!from || !to) { sendMessage(chatId, 'Формат: /range 01.05.2026 31.05.2026'); break; }
      enqueueCommand({ chat_id: chatId, report_type: 'ondemand',
        period_start: from, period_end: to });
      sendMessage(chatId, `⏳ Готовлю отчёт за период.`);
      break;
    }

    case '/reports_perfilev':
    case '/reports_gubarev':
    case '/reports': {
      let dateStart, dateEnd;

      if (args.length === 0) {
        dateStart = dateEnd = yesterday();
      } else if (args[0] === 'today') {
        dateStart = dateEnd = today();
      } else if (args.length >= 2) {
        dateStart = parseDate(args[0]);
        dateEnd = parseDate(args[1]);
        if (!dateStart || !dateEnd) {
          sendMessage(chatId, 'Формат: /reports_перфильев ДД.ММ.ГГГГ ДД.ММ.ГГГГ');
          break;
        }
      } else {
        sendMessage(chatId, 'Использование: /reports_перфильев [today | ДД.ММ.ГГГГ ДД.ММ.ГГГГ]');
        break;
      }

      if (cmd === '/reports_perfilev') {
        sendMessage(chatId, `🔄 <b>Генерирую отчёты ИП Перфильев (${dateStart}${dateStart !== dateEnd ? ' - ' + dateEnd : ''})...</b>`);
        sendODataReport(chatId, 'perfilev', dateStart, dateEnd);
      } else if (cmd === '/reports_gubarev') {
        sendMessage(chatId, `🔄 <b>Генерирую отчёты ИП Губарев (${dateStart}${dateStart !== dateEnd ? ' - ' + dateEnd : ''})...</b>`);
        sendODataReport(chatId, 'gubarev', dateStart, dateEnd);
      } else if (cmd === '/reports') {
        sendMessage(chatId, `🔄 <b>Генерирую отчёты обеих баз (${dateStart}${dateStart !== dateEnd ? ' - ' + dateEnd : ''})...</b>`);
        sendODataReport(chatId, 'perfilev', dateStart, dateEnd);
        sendODataReport(chatId, 'gubarev', dateStart, dateEnd);
      }
      break;
    }

    default:
      sendMessage(chatId, 'Неизвестная команда. ' + helpText());
  }
}

function helpText() {
  return [
    '🤖 <b>Команды</b>',
    '/today — отчёт за сегодня',
    '/range ДД.ММ.ГГГГ ДД.ММ.ГГГГ — за период',
    '<b>Отчёты:</b>',
    '/reports_perfilev — вчера (Перфильев)',
    '/reports_perfilev today — сегодня (Перфильев)',
    '/reports_perfilev ДД.ММ ДД.ММ — диапазон (Перфильев)',
    '/reports_gubarev — вчера (Губарев)',
    '/reports_gubarev today — сегодня (Губарев)',
    '/reports — обе базы (вчера)',
    '/help — справка',
  ].join('\n');
}

// ─────────────────────────────────────────────────────────────────────────
//  ОТЧЁТЫ ПО OData
// ─────────────────────────────────────────────────────────────────────────

function sendODataReport(chatId, baseId, dateStart, dateEnd) {
  if (!dateEnd) dateEnd = dateStart;
  const startTime = Date.now();
  const timeout = 25000;  // 25 секунд timeout

  try {
    Logger.log(`[sendODataReport] Starting for ${baseId} from ${dateStart} to ${dateEnd}`);
    const baseName = CONFIG.BASE_TITLE[baseId];
    if (!baseName) {
      sendMessage(chatId, '❌ Неизвестная база: ' + baseId);
      return;
    }
    const nextDateAfterEnd = shiftDays(dateEnd, 1);

    // Функция для проверки timeout
    const checkTimeout = () => {
      if (Date.now() - startTime > timeout) {
        throw new Error('Timeout: request took too long');
      }
    };

    Logger.log(`[sendODataReport] Fetching sales for ${baseId}`);
    // 1. ПРОДАЖИ
    const sales = fetchAllODataRecords(baseId, 'AccumulationRegister_Продажи_RecordType', {
      filter: `Period ge datetime'${dateStart}T00:00:00' and Period lt datetime'${nextDateAfterEnd}T00:00:00'`,
    });
    let totalSales = 0;
    if (sales && sales.length > 0) {
      sales.forEach(s => {
        if (s.RecordType === 'Receipt') totalSales += (s.Сумма || 0);
      });
    }
    Logger.log(`[sendODataReport] Sales: ${sales ? sales.length : 0} records, total ${totalSales}`);

    Logger.log(`[sendODataReport] Fetching settlements for ${baseId}`);
    // 2. ДЕБИТОРКА (на конец периода)
    let settlements = [];
    try {
      settlements = fetchAllODataRecords(baseId, 'AccumulationRegister_РасчетыСПокупателями_RecordType', {
        filter: `Period le datetime'${nextDateAfterEnd}T00:00:00'`,
      }) || [];
    } catch (e) {
      Logger.log(`[sendODataReport] Error fetching settlements: ${e}`);
      settlements = [];
    }
    Logger.log(`[sendODataReport] Settlements: ${settlements ? settlements.length : 0} records`);

    const contractorNames = getContractorNames(baseId);
    Logger.log(`[sendODataReport] Contractors: ${Object.keys(contractorNames).length}`);

    const debtByCtg = {};
    if (settlements && settlements.length > 0) {
      settlements.forEach(s => {
        const ctgKey = s.Контрагент_Key || 'unknown';
        if (!debtByCtg[ctgKey]) debtByCtg[ctgKey] = { receipt: 0, expense: 0 };
        if (s.RecordType === 'Receipt') {
          debtByCtg[ctgKey].receipt += (s.Сумма || 0);
        } else if (s.RecordType === 'Expense') {
          debtByCtg[ctgKey].expense += (s.Сумма || 0);
        }
      });
    }

    let totalDebt = 0;
    const topDebtors = [];
    Object.entries(debtByCtg).forEach(([ctgKey, bal]) => {
      const balance = bal.receipt - bal.expense;
      if (balance > 0) {
        totalDebt += balance;
        topDebtors.push({
          name: contractorNames[ctgKey] || 'Unknown',
          amount: balance
        });
      }
    });
    topDebtors.sort((a, b) => b.amount - a.amount);
    Logger.log(`[sendODataReport] Total debt: ${totalDebt}`);

    // 3. АКТИВНОСТЬ (за период)
    const customerActivity = {};
    if (sales && sales.length > 0) {
      sales.forEach(s => {
        const period = s.Period || '';
        const pDate = period.substr(0, 10);
        if (pDate >= dateStart && pDate <= dateEnd) {
          const ctgKey = s.Контрагент_Key || 'unknown';
          if (!customerActivity[ctgKey]) customerActivity[ctgKey] = 0;
          customerActivity[ctgKey]++;
        }
      });
    }

    const activeCount = Object.keys(customerActivity).length;
    Logger.log(`[sendODataReport] Active customers: ${activeCount}`);

    // Отправляем отчёт
    const periodLabel = dateStart === dateEnd ? dateStart : `${dateStart} – ${dateEnd}`;
    let msg = `📊 <b>${baseName} — ОТЧЁТЫ за ${periodLabel}</b>\n\n`;
    msg += `💰 <b>ПРОДАЖИ</b>\n`;
    msg += `Выручка: <b>${fmtMoney(totalSales)}</b>\n\n`;

    msg += `💳 <b>ДЕБИТОРКА</b>\n`;
    msg += `Всего: <b>${fmtMoney(totalDebt)}</b>\n`;
    const ctgCount = Object.keys(debtByCtg).length || 0;
    msg += `Контрагентов: ${ctgCount}\n`;
    msg += `\nТоп-5 должников:\n`;
    topDebtors.slice(0, 5).forEach((d, i) => {
      msg += `${i+1}. ${escapeHtml(d.name)}: ${fmtMoney(d.amount)}\n`;
    });

    msg += `\n📈 <b>АКТИВНОСТЬ (за 14дн)</b>\n`;
    msg += `Активных клиентов: <b>${activeCount}</b>\n`;

    Logger.log(`[sendODataReport] Sending message to ${chatId}`);
    sendMessage(chatId, msg);
  } catch (err) {
    Logger.log(`[sendODataReport] ERROR: ${err}`);
    sendMessage(chatId, '❌ Ошибка: ' + String(err).substr(0, 100));
    logRow('ERROR', baseId, 'sendODataReport', String(err));
  }
}

// ─────────────────────────────────────────────────────────────────────────
//  ОЧЕРЕДЬ КОМАНД
// ─────────────────────────────────────────────────────────────────────────

function enqueueCommand(cmd) {
  const sh = book().getSheetByName(SHEETS.QUEUE);
  const requestId = Utilities.getUuid();
  sh.appendRow([requestId, now(), cmd.chat_id, cmd.report_type,
    cmd.period_start, cmd.period_end, 'pending:perfilev,gubarev']);
  return requestId;
}

function handlePull(body) {
  const baseId = body.base_id;
  const sh = book().getSheetByName(SHEETS.QUEUE);
  const data = sh.getDataRange().getValues();
  const out = [];

  for (let r = 1; r < data.length; r++) {
    const status = String(data[r][6] || '');
    if (status.indexOf('pending') === -1) continue;
    if (status.indexOf(baseId) === -1) continue;
    out.push({
      request_id: data[r][0],
      chat_id: data[r][2],
      report_type: data[r][3],
      period_start: data[r][4],
      period_end: data[r][5],
    });
    const left = status.replace('pending:', '').split(',')
      .map(s => s.trim()).filter(s => s && s !== baseId);
    data[r][6] = left.length ? 'pending:' + left.join(',') : 'sent';
    sh.getRange(r + 1, 7).setValue(data[r][6]);
  }
  return { ok: true, commands: out };
}

// ─────────────────────────────────────────────────────────────────────────
//  ТАЙМТРИГГЕРЫ
// ─────────────────────────────────────────────────────────────────────────

function triggerWeekly()   { enqueuePeriodic('weekly',   shiftDays(today(), -7),   yesterday()); }
function triggerMonthly()  { enqueuePeriodic('monthly',  firstDayPrevMonth(),      lastDayPrevMonth()); }
function triggerHalfyear() { enqueuePeriodic('halfyear', shiftDays(today(), -182), yesterday()); }
function triggerYearly()   { enqueuePeriodic('yearly',   shiftDays(today(), -365), yesterday()); }

function enqueuePeriodic(type, from, to) {
  const sh = book().getSheetByName(SHEETS.QUEUE);
  sh.appendRow([Utilities.getUuid(), now(), '', type, from, to, 'pending:perfilev,gubarev']);
  logRow('SCHEDULE', '', type, from + '..' + to);
}

function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('triggerWeekly').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(9).create();
  ScriptApp.newTrigger('triggerMonthly').timeBased().onMonthDay(1).atHour(9).create();
  ScriptApp.newTrigger('maybeHalfYearOrYear').timeBased().atHour(9).everyDays(1).create();
  ScriptApp.newTrigger('checkPendingTimeouts').timeBased().everyMinutes(5).create();
}

function maybeHalfYearOrYear() {
  const d = new Date();
  const day = d.getDate(), month = d.getMonth() + 1;
  if (day === 1 && (month === 1 || month === 7)) triggerHalfyear();
  if (day === 1 && month === 1) triggerYearly();
}

function checkPendingTimeouts() {
  const all = PROPS.getProperties();
  const limitMs = 15 * 60 * 1000;
  Object.keys(all).filter(k => k.indexOf('PEND_TS::') === 0).forEach(tsKey => {
    const key = tsKey.replace('PEND_TS::', '');
    if (Date.now() - Number(all[tsKey]) < limitMs) return;
    const a = all['PEND::' + key + '::perfilev'];
    const b = all['PEND::' + key + '::gubarev'];
    if (a && b) return;
    const present = a ? JSON.parse(a) : (b ? JSON.parse(b) : null);
    if (!present) { PROPS.deleteProperty(tsKey); return; }
    const missing = a ? 'gubarev' : 'perfilev';
    finalizeReport(key, a ? present : null, b ? present : null, missing);
  });
}

// ─────────────────────────────────────────────────────────────────────────
//  SHEETS & DASHBOARD
// ─────────────────────────────────────────────────────────────────────────

function fillDashboard(periodLabel, a, b, combined) {
  const sh = book().getSheetByName(SHEETS.DASHBOARD);
  sh.getRange(CELL_MAP.period_label).setValue(periodLabel);

  const put = (mapKey, baseId, value) => {
    const addr = CELL_MAP[mapKey] && CELL_MAP[mapKey][baseId];
    if (addr) sh.getRange(addr).setValue(value == null ? '' : value);
  };

  [['perfilev', a], ['gubarev', b]].forEach(([id, p]) => {
    const x = p ? p.metrics : null;
    put('sales_total',        id, get(x, 'sales.total'));
    put('sales_dyn_pct',      id, get(x, 'sales.dynamics_pct'));
    put('sales_avg_per_day',  id, get(x, 'sales.avg_per_day'));
    put('sales_forecast',     id, get(x, 'sales.forecast_turnover'));
    put('settle_they_owe_us', id, get(x, 'settlements.they_owe_us'));
    put('settle_we_owe',      id, get(x, 'settlements.we_owe'));
    put('recv_total',         id, get(x, 'receivables.total'));
    put('recv_overdue',       id, get(x, 'receivables.overdue'));
  });

  put('sales_total',        'total', combined.sales.total);
  put('sales_dyn_pct',      'total', combined.sales.dynamics_pct);
  put('sales_avg_per_day',  'total', combined.sales.avg_per_day);
  put('sales_forecast',     'total', combined.sales.forecast_turnover);
  put('settle_they_owe_us', 'total', combined.settlements.they_owe_us);
  put('settle_we_owe',      'total', combined.settlements.we_owe);
  put('recv_total',         'total', combined.receivables.total);
  put('recv_overdue',       'total', combined.receivables.overdue);
}

function buildText(periodLabel, a, b, c, partialBase) {
  const L = [];
  const money = (v) => fmtMoney(v);
  const pct = (v) => (v > 0 ? '📈 +' : (v < 0 ? '📉 ' : '')) + (v || 0) + '%';

  L.push(`📊 <b>Отчёт за ${escapeHtml(periodLabel)}</b>`);
  if (partialBase) {
    L.push(`⚠️ Данные базы «${CONFIG.BASE_TITLE[partialBase]}» не получены — отчёт частичный.`);
  }
  L.push('');

  L.push('🏢 <b>ИТОГО (Перфильев + Губарев)</b>');
  L.push(`💰 Продажи: <b>${money(c.sales.total)}</b> (${pct(c.sales.dynamics_pct)} к пред. периоду)`);
  L.push(`   средн./день: ${money(c.sales.avg_per_day)} · прогноз оборота: ${money(c.sales.forecast_turnover)}`);
  L.push(`🤝 Взаиморасчёты: нам должны ${money(c.settlements.they_owe_us)} · мы должны ${money(c.settlements.we_owe)}`);
  L.push(`📕 Дебиторка: ${money(c.receivables.total)}, просрочено ${money(c.receivables.overdue)}`);
  L.push('— — —');

  [['🟦 Перфильев', a], ['🟩 Губарев', b]].forEach(([title, p]) => {
    L.push(`<b>${title}</b>`);
    if (!p) { L.push('   нет данных'); return; }
    const x = p.metrics;
    L.push(`💰 Продажи: ${money(get(x, 'sales.total'))} (${pct(get(x, 'sales.dynamics_pct'))})`);
    L.push(`📕 Дебиторка: ${money(get(x, 'receivables.total'))}, просрочено ${money(get(x, 'receivables.overdue'))}`);
    const topOver = get(x, 'receivables.top_overdue') || [];
    if (topOver.length) {
      const s = topOver.slice(0, 5)
        .map(d => `${escapeHtml(d.name)} ${money(d.amount)} (${d.days_overdue} дн)`)
        .join(', ');
      L.push(`   Топ-просрочка: ${s}`);
    }
    const grow = (get(x, 'clients_activity.growing')  || []).slice(0, 5);
    const drop = (get(x, 'clients_activity.declining') || []).slice(0, 5);
    if (grow.length) L.push(`   📈 Рост: ${grow.map(o => escapeHtml(o.name) + ' (' + pctRaw(o.delta_pct) + ')').join(', ')}`);
    if (drop.length) L.push(`   📉 Проседание: ${drop.map(o => escapeHtml(o.name) + ' (' + pctRaw(o.delta_pct) + ')').join(', ')}`);
  });

  L.push('');
  L.push(`🔗 <a href="${sheetUrl()}">Полный дашборд в Google Sheets</a>`);
  return L.join('\n');
}

function book() { return SpreadsheetApp.openById(CONFIG.SHEET_ID); }
function sheetUrl() { return book().getUrl(); }

function saveRaw(baseId, body) {
  const sh = book().getSheetByName(SHEETS.RAW[baseId]);
  sh.appendRow([now(), body.report_type, body.period_start, body.period_end,
    JSON.stringify(body.metrics)]);
}

function logRow(kind, base, type, msg) {
  try {
    book().getSheetByName(SHEETS.LOG).appendRow([now(), kind, base, type, msg]);
  } catch (e) {}
}

function initSheets() {
  const ss = book();
  const ensure = (name) => ss.getSheetByName(name) || ss.insertSheet(name);

  ensure(SHEETS.RAW.perfilev).getRange(1, 1, 1, 5)
    .setValues([['Время', 'Тип', 'Начало', 'Конец', 'Метрики(JSON)']]);
  ensure(SHEETS.RAW.gubarev).getRange(1, 1, 1, 5)
    .setValues([['Время', 'Тип', 'Начало', 'Конец', 'Метрики(JSON)']]);
  ensure(SHEETS.LOG).getRange(1, 1, 1, 5)
    .setValues([['Время', 'Событие', 'База', 'Тип', 'Сообщение']]);
  ensure(SHEETS.QUEUE).getRange(1, 1, 1, 7)
    .setValues([['request_id', 'Время', 'chat_id', 'Тип', 'Начало', 'Конец', 'Статус']]);

  const d = ensure(SHEETS.DASHBOARD);
  d.getRange('B1').setValue('ОТЧЁТ УНФ');
  d.getRange('B2').setValue('период');
  d.getRange('C4:E4').setValues([['Перфильев', 'Губарев', 'Итого']]);
  const labels = [
    ['B5', 'Продажи за период'], ['B6', 'Динамика, %'], ['B7', 'Средние/день'],
    ['B8', 'Прогноз оборота'], ['B11', 'Нам должны'], ['B12', 'Мы должны'],
    ['B15', 'Дебиторка общая'], ['B16', 'Дебиторка просрочено'],
  ];
  labels.forEach(([addr, text]) => d.getRange(addr).setValue(text));
  logRow('INIT', '', '', 'Sheets initialized');
}

function setWebhook() {
  const WEBAPP_URL = 'https://script.google.com/macros/s/AKfycbyeGLtHdoMs1v1yaG1OUNYnsTpIr3dqb--C_9cNmTA7T6FB1qFKHCzbkvJZk-wsrPYScQ/exec';
  const url = `https://api.telegram.org/bot${CONFIG.TELEGRAM_TOKEN}/setWebhook?url=${encodeURIComponent(WEBAPP_URL)}&drop_pending_updates=true`;
  const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  return resp.getContentText();
}

// ─────────────────────────────────────────────────────────────────────────
//  UTILS
// ─────────────────────────────────────────────────────────────────────────

function get(obj, path, d) {
  try { return path.split('.').reduce((o, k) => o[k], obj); } catch (e) { return d; }
}
function periodKey(type, from, to, requestId) {
  return requestId ? ('req:' + requestId) : (type + ':' + from + ':' + to);
}
function humanPeriod(type, from, to) {
  const names = { daily: 'текущий день', weekly: 'неделю', monthly: 'месяц',
    halfyear: 'полугодие', yearly: 'год', ondemand: 'период' };
  if (from === to) return `${from} (${names[type] || ''})`.trim();
  return `${from} – ${to}`;
}
function fmtMoney(v) {
  v = Number(v) || 0;
  return v.toLocaleString('ru-RU') + ' ₽';
}
function pctRaw(v) { return (v > 0 ? '+' : '') + (v || 0) + '%'; }
function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function splitText(text, max) {
  if (text.length <= max) return [text];
  const parts = [], lines = text.split('\n');
  let buf = '';
  lines.forEach(line => {
    if ((buf + '\n' + line).length > max) { parts.push(buf); buf = line; }
    else { buf = buf ? buf + '\n' + line : line; }
  });
  if (buf) parts.push(buf);
  return parts;
}
function now() { return Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd HH:mm:ss'); }
function today() { return Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd'); }
function yesterday() { return shiftDays(today(), -1); }
function shiftDays(isoDate, days) {
  const d = new Date(isoDate + 'T00:00:00');
  d.setDate(d.getDate() + days);
  return Utilities.formatDate(d, CONFIG.TIMEZONE, 'yyyy-MM-dd');
}
function firstDayPrevMonth() {
  const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1);
  return Utilities.formatDate(d, CONFIG.TIMEZONE, 'yyyy-MM-dd');
}
function lastDayPrevMonth() {
  const d = new Date(); d.setDate(0);
  return Utilities.formatDate(d, CONFIG.TIMEZONE, 'yyyy-MM-dd');
}
function parseDate(s) {
  if (!s) return null;
  let m = s.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (m) return `${m[3]}-${m[2]}-${m[1]}`;
  m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return s;
  return null;
}
