/**
 * Google Apps Script Web App
 * Основной файл для интеграции 1С → Google Sheets → Telegram
 *
 * Endpoints:
 * - POST /ingest — получить данные от 1С
 * - GET /pull-commands — выдать очередь команд 1С
 * - Telegram webhook — получить команды от пользователя
 */

/**
 * Главный обработчик POST запросов
 * Распределяет запросы по типам
 */
function doPost(e) {
  try {
    const request = JSON.parse(e.postData.contents);
    log(`POST request received: ${request.base_id} / ${request.report_type}`);

    // Проверка auth_token
    if (!validateAuthToken(request.auth_token)) {
      logError('Invalid auth_token');
      return buildResponse(401, { error: 'Unauthorized' });
    }

    // Маршрутизация по пути
    const path = e.parameter.path || 'ingest';

    switch (path) {
      case 'ingest':
        return handleIngest(request);
      case 'telegram':
        return handleTelegramWebhook(request);
      default:
        return buildResponse(404, { error: 'Not found' });
    }
  } catch (error) {
    logError('doPost error', error);
    return buildResponse(500, { error: 'Internal server error' });
  }
}

/**
 * Главный обработчик GET запросов
 */
function doGet(e) {
  try {
    const path = e.parameter.path || 'commands';
    const authToken = e.parameter.auth_token;

    log(`GET request: ${path}`);

    // Проверка auth_token
    if (!validateAuthToken(authToken)) {
      logError('Invalid auth_token in GET');
      return buildResponse(401, { error: 'Unauthorized' });
    }

    switch (path) {
      case 'commands':
        return handlePullCommands(e);
      case 'status':
        return handleStatusCheck(e);
      default:
        return buildResponse(404, { error: 'Not found' });
    }
  } catch (error) {
    logError('doGet error', error);
    return buildResponse(500, { error: 'Internal server error' });
  }
}

/**
 * Обработка POST /ingest — получение данных от 1С
 */
function handleIngest(request) {
  const {
    base_id,
    report_type,
    period_start,
    period_end,
    generated_at,
    request_id,
    metrics,
  } = request;

  log(`Processing ingest: ${base_id} / ${report_type} / ${period_start} - ${period_end}`);

  try {
    // 1. Записать сырые данные в RAW_*
    const rawSheetName = base_id === 'perfilev' ? SHEET_NAMES.RAW_PERFILEV : SHEET_NAMES.RAW_GUBAREV;
    appendRawData(rawSheetName, {
      timestamp: new Date(),
      base_id,
      report_type,
      period_start,
      period_end,
      metrics: JSON.stringify(metrics),
    });

    // 2. Логировать операцию
    appendLog({
      timestamp: new Date(),
      base_id,
      report_type,
      status: 'ingest_received',
      message: `Data received from ${base_id} for ${period_start}`,
    });

    // 3. Проверить если обе базы прислали данные за один период
    const shouldGenerateReport = checkBothBasesReported(period_start, period_end, report_type);

    if (shouldGenerateReport) {
      log(`Both bases reported. Generating report for ${period_start} - ${period_end}`);
      generateAndSendReport(period_start, period_end, report_type, request_id);
    }

    return buildResponse(200, { status: 'received', request_id });
  } catch (error) {
    logError('handleIngest error', error);
    appendLog({
      timestamp: new Date(),
      base_id,
      report_type,
      status: 'ingest_error',
      message: error.toString(),
    });
    return buildResponse(500, { error: error.toString() });
  }
}

/**
 * Обработка GET /pull-commands — выдача очереди команд
 */
function handlePullCommands(e) {
  const baseId = e.parameter.base_id;

  log(`Pull commands for base: ${baseId}`);

  try {
    const sheet = SpreadsheetApp.openById(getSecrets().SPREADSHEET_ID).getSheetByName(SHEET_NAMES.QUEUE);
    const data = sheet.getDataRange().getValues();

    // Собрать невыполненные команды для этой базы
    const commands = [];
    for (let i = 1; i < data.length; i++) {
      const row = data[i];
      const status = row[5]; // статус в 6й колонке

      if (status !== 'executed') {
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
 * Обработка Telegram webhook
 * GET запрос с параметром ?action=telegram&chat_id=...&command=/today
 */
function handleTelegramWebhook(e) {
  const chatId = e.parameter.chat_id;
  const command = e.parameter.command || '';
  const param1 = e.parameter.param1;
  const param2 = e.parameter.param2;

  log(`Telegram command from ${chatId}: ${command} ${param1} ${param2}`);

  // Проверка whitelist
  if (!isAllowedChat(chatId)) {
    logError(`Chat ${chatId} not in whitelist`);
    return buildResponse(403, { error: 'Not allowed' });
  }

  try {
    switch (command) {
      case '/today':
        queueCommand('daily', 'today', 'today', chatId);
        return buildResponse(200, { status: 'queued' });

      case '/range':
        if (!param1 || !param2) {
          return buildResponse(400, { error: 'Missing date parameters' });
        }
        queueCommand('ondemand', param1, param2, chatId);
        return buildResponse(200, { status: 'queued' });

      case '/week':
        const weekStart = getWeekStart();
        const weekEnd = getWeekEnd();
        queueCommand('weekly', weekStart, weekEnd, chatId);
        return buildResponse(200, { status: 'queued' });

      case '/month':
        const monthStart = getMonthStart();
        const monthEnd = getMonthEnd();
        queueCommand('monthly', monthStart, monthEnd, chatId);
        return buildResponse(200, { status: 'queued' });

      case '/help':
        sendTelegramMessage(
          chatId,
          'Доступные команды:\n' +
          '/today — отчет за сегодня\n' +
          '/week — отчет за неделю\n' +
          '/month — отчет за месяц\n' +
          '/range ДД.ММ.ГГГГ ДД.ММ.ГГГГ — отчет за диапазон\n' +
          '/help — эта справка'
        );
        return buildResponse(200, { status: 'sent' });

      default:
        return buildResponse(400, { error: 'Unknown command' });
    }
  } catch (error) {
    logError('handleTelegramWebhook error', error);
    return buildResponse(500, { error: error.toString() });
  }
}

/**
 * Обработка проверки статуса
 */
function handleStatusCheck(e) {
  const baseId = e.parameter.base_id;

  try {
    // Получить последнюю запись для каждой базы
    const perfilevLast = getLastReport('RAW_perfilev');
    const gubarevLast = getLastReport('RAW_gubarev');

    return buildResponse(200, {
      status: 'ok',
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

// ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

/**
 * Валидация auth_token
 */
function validateAuthToken(token) {
  const secrets = getSecrets();
  return token === secrets.AUTH_TOKEN;
}

/**
 * Проверка разрешенного чата
 */
function isAllowedChat(chatId) {
  const values = Object.values(ALLOWED_CHATS);
  return values.includes(parseInt(chatId));
}

/**
 * Построить JSON ответ
 */
function buildResponse(statusCode, data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * Отправить сообщение в Telegram
 */
function sendTelegramMessage(chatId, message) {
  const secrets = getSecrets();
  const url = `https://api.telegram.org/bot${secrets.TELEGRAM_TOKEN}/sendMessage`;

  const payload = {
    chat_id: chatId,
    text: message,
    parse_mode: 'HTML',
  };

  try {
    UrlFetchApp.fetch(url, {
      method: 'post',
      payload: JSON.stringify(payload),
      headers: {
        'Content-Type': 'application/json',
      },
      muteHttpExceptions: true,
    });
    log(`Message sent to ${chatId}`);
  } catch (error) {
    logError(`Failed to send message to ${chatId}`, error);
  }
}

/**
 * Добавить команду в очередь
 */
function queueCommand(reportType, periodStart, periodEnd, chatId) {
  const sheet = SpreadsheetApp.openById(getSecrets().SPREADSHEET_ID).getSheetByName(SHEET_NAMES.QUEUE);
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

  log(`Command queued: ${requestId} for chat ${chatId}`);
}

/**
 * Добавить запись в логи
 */
function appendLog(logEntry) {
  const sheet = SpreadsheetApp.openById(getSecrets().SPREADSHEET_ID).getSheetByName(SHEET_NAMES.LOG);
  sheet.appendRow([
    logEntry.timestamp,
    logEntry.base_id,
    logEntry.report_type,
    logEntry.status,
    logEntry.message,
  ]);
}

/**
 * Добавить сырые данные
 */
function appendRawData(sheetName, data) {
  const sheet = SpreadsheetApp.openById(getSecrets().SPREADSHEET_ID).getSheetByName(sheetName);
  sheet.appendRow([
    data.timestamp,
    data.base_id,
    data.report_type,
    data.period_start,
    data.period_end,
    data.metrics,
  ]);
}

/**
 * Проверить если обе базы прислали данные
 */
function checkBothBasesReported(periodStart, periodEnd, reportType) {
  const sheet = SpreadsheetApp.openById(getSecrets().SPREADSHEET_ID);

  try {
    const perfilevSheet = sheet.getSheetByName(SHEET_NAMES.RAW_PERFILEV);
    const gubarevSheet = sheet.getSheetByName(SHEET_NAMES.RAW_GUBAREV);

    const perfilevData = perfilevSheet.getDataRange().getValues();
    const gubarevData = gubarevSheet.getDataRange().getValues();

    // Проверить если есть запись с нужным периодом в обоих листах
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

/**
 * Получить последний отчет для базы
 */
function getLastReport(sheetName) {
  const sheet = SpreadsheetApp.openById(getSecrets().SPREADSHEET_ID).getSheetByName(sheetName);
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
}

// ===== ФУНКЦИИ ДЛЯ ДАТА =====

function getWeekStart() {
  const today = new Date();
  const day = today.getDay();
  const diff = today.getDate() - day + (day === 0 ? -6 : 1);
  const weekStart = new Date(today.setDate(diff));
  return formatDate(weekStart.toISOString().split('T')[0]);
}

function getWeekEnd() {
  const today = new Date();
  return formatDate(today.toISOString().split('T')[0]);
}

function getMonthStart() {
  const today = new Date();
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
  return formatDate(monthStart.toISOString().split('T')[0]);
}

function getMonthEnd() {
  const today = new Date();
  return formatDate(today.toISOString().split('T')[0]);
}

// ===== ЗАГЛУШКА ДЛЯ ГЕНЕРАЦИИ ОТЧЕТА =====
// TODO: Реализовать полную генерацию отчета (в отдельном файле)
function generateAndSendReport(periodStart, periodEnd, reportType, requestId) {
  log(`TODO: Generate report for ${periodStart} - ${periodEnd}`);
  // Это будет реализовано в gas_data_aggregator.gs и gas_excel_generator.gs
}
