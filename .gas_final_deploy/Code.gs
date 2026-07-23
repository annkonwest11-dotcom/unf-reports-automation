/**
 * GOOGLE APPS SCRIPT - ОСНОВНОЕ ПРИЛОЖЕНИЕ
 * 1С → Google Sheets → Telegram интеграция
 *
 * Endpoints:
 * - POST /ingest — получить данные от 1С
 * - GET /pull-commands — выдать очередь команд
 * - POST /telegram — webhook от Telegram
 */

// ===== ГЛАВНЫЕ ОБРАБОТЧИКИ =====

function doPost(e) {
  try {
    const path = e.parameter.path || 'ingest';

    // Telegram webhook может быть в body
    if (path === 'telegram') {
      return handleTelegramPost(e);
    }

    const request = JSON.parse(e.postData.contents);
    log(`POST ${path}: ${request.base_id || 'unknown'}`);

    if (!validateAuthToken(request.auth_token)) {
      return buildResponse(401, { error: 'Unauthorized' });
    }

    if (path === 'ingest') {
      return handleIngest(request);
    }

    return buildResponse(404, { error: 'Not found' });
  } catch (error) {
    logError('doPost error', error);
    return buildResponse(500, { error: error.toString() });
  }
}

function doGet(e) {
  try {
    const path = e.parameter.path || 'commands';
    const authToken = e.parameter.auth_token;
    const baseId = e.parameter.base_id;

    log(`GET ${path} for ${baseId || 'all'}`);

    if (!validateAuthToken(authToken)) {
      return buildResponse(401, { error: 'Unauthorized' });
    }

    if (path === 'commands') {
      return handlePullCommands(baseId);
    }

    if (path === 'status') {
      return handleStatusCheck();
    }

    return buildResponse(404, { error: 'Not found' });
  } catch (error) {
    logError('doGet error', error);
    return buildResponse(500, { error: error.toString() });
  }
}

// ===== ОБРАБОТЧИКИ ЗАПРОСОВ =====

/**
 * POST /ingest — получение данных от 1С
 */
function handleIngest(request) {
  const { base_id, report_type, period_start, period_end, generated_at, request_id, metrics } = request;

  log(`Ingest: ${base_id} / ${report_type} / ${period_start}-${period_end}`);

  try {
    // 1. Записать сырые данные
    const rawSheetName = base_id === 'perfilev' ? SHEET_NAMES.RAW_PERFILEV : SHEET_NAMES.RAW_GUBAREV;
    appendRawData(rawSheetName, {
      timestamp: new Date(),
      base_id,
      report_type,
      period_start,
      period_end,
      metrics: JSON.stringify(metrics),
    });

    // 2. Логировать
    appendLog({
      timestamp: new Date(),
      base_id,
      report_type,
      status: 'received',
      message: `Data from ${base_id}`,
    });

    // 3. Проверить если обе базы ответили
    if (checkBothBasesReported(period_start, period_end, report_type)) {
      log(`Both bases ready. Generating report...`);
      generateAndSendReport(period_start, period_end, report_type, request_id);
    }

    return buildResponse(200, { status: 'received', base_id, request_id });
  } catch (error) {
    logError('handleIngest error', error);
    appendLog({
      timestamp: new Date(),
      base_id,
      report_type,
      status: 'error',
      message: error.toString(),
    });
    return buildResponse(500, { error: error.toString() });
  }
}

/**
 * GET /pull-commands — выдача очереди команд
 */
function handlePullCommands(baseId) {
  try {
    const sheet = getSheet(SHEET_NAMES.QUEUE);
    const data = sheet.getDataRange().getValues();

    const commands = [];
    for (let i = 1; i < data.length; i++) {
      const row = data[i];
      if (row[5] !== 'executed' && row[0]) { // status != executed
        commands.push({
          request_id: row[0],
          report_type: row[1],
          period_start: row[2],
          period_end: row[3],
          chat_id: row[6],
        });
      }
    }

    log(`Returning ${commands.length} commands for ${baseId}`);
    return buildResponse(200, { commands });
  } catch (error) {
    logError('handlePullCommands error', error);
    return buildResponse(500, { error: error.toString() });
  }
}

/**
 * GET /status — проверка статуса
 */
function handleStatusCheck() {
  try {
    const perfilevLast = getLastReport(SHEET_NAMES.RAW_PERFILEV);
    const gubarevLast = getLastReport(SHEET_NAMES.RAW_GUBAREV);

    return buildResponse(200, {
      status: 'ok',
      timestamp: new Date().toISOString(),
      last_reports: {
        perfilev: perfilevLast,
        gubarev: gubarevLast,
      },
    });
  } catch (error) {
    logError('handleStatusCheck error', error);
    return buildResponse(500, { error: error.toString() });
  }
}

/**
 * POST /telegram — Telegram webhook
 */
function handleTelegramPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    const message = body.message;

    if (!message || !message.chat || !message.text) {
      return buildResponse(200, { ok: true });
    }

    const chatId = message.chat.id;
    const text = message.text.trim();

    log(`Telegram message from ${chatId}: ${text}`);

    if (!isAllowedChat(chatId)) {
      sendTelegramMessage(chatId, '❌ Ты не авторизован');
      return buildResponse(200, { ok: true });
    }

    processCommand(chatId, text);
    return buildResponse(200, { ok: true });
  } catch (error) {
    logError('handleTelegramPost error', error);
    return buildResponse(500, { error: error.toString() });
  }
}

// ===== ОБРАБОТКА КОМАНД TELEGRAM =====

function processCommand(chatId, text) {
  const parts = text.split(/\s+/);
  const command = parts[0].toLowerCase();

  if (command === '/start') {
    sendTelegramMessage(chatId, '👋 Привет! Я помогу с отчетами.\n\n/help — список команд');
    return;
  }

  if (command === '/help') {
    const help = `
📊 Доступные команды:

/today — отчет за сегодня
/week — отчет за неделю
/month — отчет за месяц
/range ДД.ММ.ГГГГ ДД.ММ.ГГГГ — отчет за период
/status — статус синхронизации

Отчеты формируются автоматически в 09:30 по МСК.
    `.trim();
    sendTelegramMessage(chatId, help);
    return;
  }

  if (command === '/today') {
    const today = formatDateISO(new Date());
    queueCommand('daily', today, today, chatId);
    sendTelegramMessage(chatId, '✅ Команда поставлена в очередь. Отчет будет готов в течение минуты...');
    return;
  }

  if (command === '/week') {
    const weekStart = getWeekStartISO();
    const weekEnd = formatDateISO(new Date());
    queueCommand('weekly', weekStart, weekEnd, chatId);
    sendTelegramMessage(chatId, '✅ Команда поставлена в очередь.');
    return;
  }

  if (command === '/month') {
    const monthStart = getMonthStartISO();
    const monthEnd = formatDateISO(new Date());
    queueCommand('monthly', monthStart, monthEnd, chatId);
    sendTelegramMessage(chatId, '✅ Команда поставлена в очередь.');
    return;
  }

  if (command === '/range' && parts.length === 3) {
    const start = parts[1];
    const end = parts[2];
    queueCommand('ondemand', start, end, chatId);
    sendTelegramMessage(chatId, `✅ Отчет за ${start} - ${end} поставлен в очередь.`);
    return;
  }

  if (command === '/status') {
    const status = getSystemStatus();
    sendTelegramMessage(chatId, status);
    return;
  }

  sendTelegramMessage(chatId, '❌ Неизвестная команда. /help для справки');
}

// ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

function validateAuthToken(token) {
  return token === getConfig().AUTH_TOKEN;
}

function isAllowedChat(chatId) {
  const values = Object.values(ALLOWED_CHATS);
  return values.includes(parseInt(chatId));
}

function buildResponse(statusCode, data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function sendTelegramMessage(chatId, message) {
  const url = `https://api.telegram.org/bot${getConfig().TELEGRAM_TOKEN}/sendMessage`;
  const payload = {
    chat_id: chatId,
    text: message,
    parse_mode: 'HTML',
  };

  try {
    UrlFetchApp.fetch(url, {
      method: 'post',
      payload: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
      muteHttpExceptions: true,
    });
    log(`Message sent to ${chatId}`);
  } catch (error) {
    logError(`Failed to send message to ${chatId}`, error);
  }
}

function sendTelegramFile(chatId, fileBlob, caption) {
  const url = `https://api.telegram.org/bot${getConfig().TELEGRAM_TOKEN}/sendDocument`;

  try {
    const formData = {
      chat_id: chatId,
      document: fileBlob,
      caption: caption,
      parse_mode: 'HTML',
    };

    UrlFetchApp.fetch(url, {
      method: 'post',
      payload: formData,
      muteHttpExceptions: true,
    });
    log(`File sent to ${chatId}`);
  } catch (error) {
    logError(`Failed to send file to ${chatId}`, error);
  }
}

function queueCommand(reportType, periodStart, periodEnd, chatId) {
  const sheet = getSheet(SHEET_NAMES.QUEUE);
  const requestId = generateUUID();

  sheet.appendRow([
    requestId,
    reportType,
    periodStart,
    periodEnd,
    new Date(),
    'pending',
    chatId,
  ]);

  log(`Queued: ${reportType} for ${periodStart}-${periodEnd}`);
}

function appendLog(logEntry) {
  const sheet = getSheet(SHEET_NAMES.LOG);
  sheet.appendRow([
    logEntry.timestamp,
    logEntry.base_id || '',
    logEntry.report_type || '',
    logEntry.status,
    logEntry.message,
  ]);
}

function appendRawData(sheetName, data) {
  const sheet = getSheet(sheetName);
  sheet.appendRow([
    data.timestamp,
    data.base_id,
    data.report_type,
    data.period_start,
    data.period_end,
    data.metrics,
  ]);
}

function checkBothBasesReported(periodStart, periodEnd, reportType) {
  try {
    const perfilevSheet = getSheet(SHEET_NAMES.RAW_PERFILEV);
    const gubarevSheet = getSheet(SHEET_NAMES.RAW_GUBAREV);

    const perfilevData = perfilevSheet.getDataRange().getValues();
    const gubarevData = gubarevSheet.getDataRange().getValues();

    let perfilevFound = false;
    let gubarevFound = false;

    for (let i = 1; i < perfilevData.length; i++) {
      const row = perfilevData[i];
      if (row[3] === periodStart && row[4] === periodEnd && row[2] === reportType) {
        perfilevFound = true;
        break;
      }
    }

    for (let i = 1; i < gubarevData.length; i++) {
      const row = gubarevData[i];
      if (row[3] === periodStart && row[4] === periodEnd && row[2] === reportType) {
        gubarevFound = true;
        break;
      }
    }

    return perfilevFound && gubarevFound;
  } catch (error) {
    logError('checkBothBasesReported error', error);
    return false;
  }
}

function getLastReport(sheetName) {
  try {
    const sheet = getSheet(sheetName);
    const data = sheet.getDataRange().getValues();

    if (data.length > 1) {
      const lastRow = data[data.length - 1];
      return {
        timestamp: lastRow[0],
        base_id: lastRow[1],
        report_type: lastRow[2],
        period_start: lastRow[3],
        period_end: lastRow[4],
      };
    }
    return null;
  } catch (error) {
    logError('getLastReport error', error);
    return null;
  }
}

function getSystemStatus() {
  const perfilevLast = getLastReport(SHEET_NAMES.RAW_PERFILEV);
  const gubarevLast = getLastReport(SHEET_NAMES.RAW_GUBAREV);

  let status = '📊 Статус системы:\n\n';
  status += '✅ Сервер работает\n\n';

  if (perfilevLast) {
    status += `<b>Перфильев:</b>\n`;
    status += `  Последний отчет: ${perfilevLast.period_start}\n`;
    status += `  Тип: ${perfilevLast.report_type}\n\n`;
  } else {
    status += `<b>Перфильев:</b> нет данных\n\n`;
  }

  if (gubarevLast) {
    status += `<b>Губарев:</b>\n`;
    status += `  Последний отчет: ${gubarevLast.period_start}\n`;
    status += `  Тип: ${gubarevLast.report_type}\n`;
  } else {
    status += `<b>Губарев:</b> нет данных\n`;
  }

  return status;
}

// ===== ДАТА-ВРЕМЯ =====

function formatDateISO(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getWeekStartISO() {
  const today = new Date();
  const day = today.getDay();
  const diff = today.getDate() - day + (day === 0 ? -6 : 1);
  const weekStart = new Date(today.setDate(diff));
  return formatDateISO(weekStart);
}

function getMonthStartISO() {
  const today = new Date();
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
  return formatDateISO(monthStart);
}

// ===== ГЕНЕРАЦИЯ ОТЧЕТА =====

function generateAndSendReport(periodStart, periodEnd, reportType, requestId) {
  try {
    log(`Generating report: ${periodStart} - ${periodEnd} (${reportType})`);

    // Получить данные обеих баз
    const perfilevData = getLatestMetrics(SHEET_NAMES.RAW_PERFILEV, periodStart, periodEnd);
    const gubarevData = getLatestMetrics(SHEET_NAMES.RAW_GUBAREV, periodStart, periodEnd);

    if (!perfilevData || !gubarevData) {
      log('Not enough data for report generation');
      return;
    }

    // Записать в DASHBOARD
    writeToDashboard(perfilevData, gubarevData);

    // Отправить в Telegram
    const message = formatReportMessage(perfilevData, gubarevData, periodStart, periodEnd);

    // TODO: Найти chat_id для отправки (из request_id или из QUEUE)
    const chatId = ALLOWED_CHATS.anna; // По умолчанию Анне
    sendTelegramMessage(chatId, message);

    // Логировать
    appendLog({
      timestamp: new Date(),
      base_id: 'all',
      report_type: reportType,
      status: 'sent',
      message: `Report sent for ${periodStart}-${periodEnd}`,
    });

    log(`Report generated and sent for ${periodStart}-${periodEnd}`);
  } catch (error) {
    logError('generateAndSendReport error', error);
  }
}

function getLatestMetrics(sheetName, periodStart, periodEnd) {
  try {
    const sheet = getSheet(sheetName);
    const data = sheet.getDataRange().getValues();

    for (let i = data.length - 1; i > 0; i--) {
      const row = data[i];
      if (row[3] === periodStart && row[4] === periodEnd) {
        return JSON.parse(row[5]);
      }
    }
    return null;
  } catch (error) {
    logError('getLatestMetrics error', error);
    return null;
  }
}

function writeToDashboard(perfilevMetrics, gubarevMetrics) {
  try {
    const sheet = getSheet(SHEET_NAMES.DASHBOARD);

    // Продажи
    sheet.getRange(CELL_MAP.sales_total.perfilev).setValue(perfilevMetrics.sales.total);
    sheet.getRange(CELL_MAP.sales_total.gubarev).setValue(gubarevMetrics.sales.total);
    sheet.getRange(CELL_MAP.sales_total.total).setValue(perfilevMetrics.sales.total + gubarevMetrics.sales.total);

    // Взаиморасчеты
    sheet.getRange(CELL_MAP.settlements_they_owe.perfilev).setValue(perfilevMetrics.settlements.they_owe_us);
    sheet.getRange(CELL_MAP.settlements_they_owe.gubarev).setValue(gubarevMetrics.settlements.they_owe_us);
    sheet.getRange(CELL_MAP.settlements_they_owe.total).setValue(
      perfilevMetrics.settlements.they_owe_us + gubarevMetrics.settlements.they_owe_us
    );

    // Дебиторка
    sheet.getRange(CELL_MAP.receivables_total.perfilev).setValue(perfilevMetrics.receivables.total);
    sheet.getRange(CELL_MAP.receivables_total.gubarev).setValue(gubarevMetrics.receivables.total);
    sheet.getRange(CELL_MAP.receivables_total.total).setValue(
      perfilevMetrics.receivables.total + gubarevMetrics.receivables.total
    );

    log('Dashboard updated');
  } catch (error) {
    logError('writeToDashboard error', error);
  }
}

function formatReportMessage(perfilevMetrics, gubarevMetrics, periodStart, periodEnd) {
  const totalSales = perfilevMetrics.sales.total + gubarevMetrics.sales.total;
  const totalReceivables = perfilevMetrics.receivables.total + gubarevMetrics.receivables.total;

  return `
📊 <b>Отчет за ${periodStart} - ${periodEnd}</b>

<b>Продажи:</b>
  Перфильев: ${formatMoney(perfilevMetrics.sales.total)}
  Губарев: ${formatMoney(gubarevMetrics.sales.total)}
  <b>Итого: ${formatMoney(totalSales)}</b>

<b>Дебиторка:</b>
  Перфильев: ${formatMoney(perfilevMetrics.receivables.total)}
  Губарев: ${formatMoney(gubarevMetrics.receivables.total)}
  <b>Итого: ${formatMoney(totalReceivables)}</b>

<b>Взаиморасчеты (нам должны):</b>
  Перфильев: ${formatMoney(perfilevMetrics.settlements.they_owe_us)}
  Губарев: ${formatMoney(gubarevMetrics.settlements.they_owe_us)}
  <b>Итого: ${formatMoney(perfilevMetrics.settlements.they_owe_us + gubarevMetrics.settlements.they_owe_us)}</b>

  ⏰ Отчет сформирован: ${new Date().toLocaleString('ru-RU', { timeZone: TIME_ZONE })}
  `.trim();
}
