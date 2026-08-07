var MAIN_SS_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo';
var KPI_SS_ID  = '1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4';

// Маппинг месяца → лист КПИ-таблицы
var MONTH_TO_KPI_SHEET = {
  'Январь':  'декабрь-январь',
  'Февраль': 'январь-февраль',
  'Март':    'февраль-март',
  'Апрель':  'март-апрель',
  'Май':     'апрель-май',
  'Июнь':    'май-июнь',
  'Июль':    'июнь-июль',
  'Август':  'июль-август',
  'Сентябрь':'август-сентябрь',
  'Октябрь': 'сентябрь-октябрь',
  'Ноябрь':  'октябрь-ноябрь',
  'Декабрь': 'ноябрь-декабрь'
};

// Маппинг заголовка КПИ-таблицы → полное имя менеджера
var HEADER_TO_MANAGER = {
  'Менеджер Дарья':  'Дарья Вольнова',
  'Менеджер Алена':  'Алена Черкашина',
  'Менеджер Ксения': 'Ксения Наныкина',
  'Менеджер Лера':   'Валерия Папоян',
  'Валерия':         'Валерия Абрамова',
  'Анна':            'Анна Кононенко (РОП)',
  'Менеджер Лианна': 'Лианна Багдасарян'
};

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('KPI ОТДЕЛ ПРОДАЖ ДАШБОРД')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function getDashboardData() {
  var ss = SpreadsheetApp.openById(MAIN_SS_ID);
  var dataSheet = ss.getSheetByName('ДАШБОРД_ДАННЫЕ');
  var settingsSheet = ss.getSheetByName('НАСТРОЙКИ');
  var rows = dataSheet.getDataRange().getValues();
  var month = settingsSheet.getRange('B4').getValue();

  var rop = { name: 'Анна Кононенко (РОП)', metrics: [] };
  var poisk = [];
  var soprov = [];
  var helper = null;
  var currentPoisk = null;

  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    var name = row[0], group = row[1], metric = row[2];
    var plan = row[3] || 0, fact = row[4] || 0, pct = row[5] || 0;

    if (group === 'РОП') {
      rop.metrics.push({ metric: metric, plan: plan, fact: fact, pct: pct });
    } else if (group === 'Менеджер поиска') {
      if (metric === 'Новые продажи') {
        currentPoisk = { name: name, plan: plan, fact: fact, pct: pct, bonus: 0, rate: 0 };
        poisk.push(currentPoisk);
      } else if (metric === 'Фикс бонус' && currentPoisk) {
        currentPoisk.bonus = fact;
      } else if (metric === '% от оплат (ставка)' && currentPoisk) {
        currentPoisk.rate = fact;
      }
    } else if (group === 'Сопровождение') {
      soprov.push({ name: name, plan: plan, fact: fact, pct: pct });
    } else if (group === 'Помощник') {
      helper = { name: name, fact: fact };
    }
  }

  return JSON.stringify({ month: month, rop: rop, poisk: poisk, soprov: soprov, helper: helper });
}

// ── СИНХРОНИЗАЦИЯ НОВЫЕ_КЛИЕНТЫ ──────────────────────────────────────────────
//
// ⛔️ ОТКЛЮЧЕНО 2026-08-07. Этот синк ДУБЛИРОВАЛ sync_novye.py и перезаписывал лист
// ночью в 03:00 — из-за него в колонке H снова появлялись битые формулы, хотя в
// питоне их давно поправили. Единственный источник НОВЫЕ_КЛИЕНТЫ теперь
// sync_novye.py (джоб auto_novye_prodazhi, ежедневно 11:00 МСК) — он ещё и заводит
// клиентов в СПРАВОЧНИК и присылает расхождения, чего этот скрипт не умеет.
// Триггер снят: запустить removeSyncTrigger() ниже (или удалить его руками в
// «Триггеры» редактора Apps Script). НЕ запускать setupDailyTrigger() заново.
// Функция оставлена как резервный ручной запуск.

function syncNewClientsFromKPI() {
  var mainSS = SpreadsheetApp.openById(MAIN_SS_ID);
  var kpiSS  = SpreadsheetApp.openById(KPI_SS_ID);

  // Текущий месяц из НАСТРОЙКИ!B4 ("Май 2026" → "Май")
  var currentPeriod = mainSS.getSheetByName('НАСТРОЙКИ').getRange('B4').getValue();
  var month = currentPeriod.toString().split(' ')[0];
  var kpiSheetName = MONTH_TO_KPI_SHEET[month];
  if (!kpiSheetName) throw new Error('Нет маппинга для месяца: ' + month);

  var kpiSheet = kpiSS.getSheetByName(kpiSheetName);
  if (!kpiSheet) throw new Error('Лист не найден в КПИ-таблице: ' + kpiSheetName);

  var data = kpiSheet.getDataRange().getValues();
  var headers = data[0];

  // Определяем колонки менеджеров (начиная с индекса 5)
  var managerCols = [];
  for (var i = 5; i < headers.length; i++) {
    var h = headers[i].toString().trim();
    if (HEADER_TO_MANAGER[h]) {
      managerCols.push({ col: i, name: HEADER_TO_MANAGER[h] });
    }
  }

  // Собираем строки для НОВЫЕ_КЛИЕНТЫ
  var newRows = [];
  var today = new Date();

  for (var r = 1; r < data.length; r++) {
    var row = data[r];
    var restaurant = row[0].toString().trim();
    if (!restaurant) continue;

    for (var m = 0; m < managerCols.length; m++) {
      var colIdx = managerCols[m].col;
      var managerName = managerCols[m].name;
      var cellVal = (row[colIdx] || '').toString().trim();

      if (!cellVal || cellVal === '-') continue;

      // Парсим число (формат "72 000,00")
      var amount = parseFloat(cellVal.replace(/\s/g, '').replace(',', '.'));
      if (isNaN(amount) || amount <= 0) continue;

      // ru-локаль таблицы: разделитель аргументов «;» (с запятыми ячейка даёт #ERROR!).
      // IFERROR на КАЖДЫЙ VLOOKUP — клиент, который есть только в одной базе,
      // всё равно отдаёт свой оборот. Совпадает с формулой из sync_novye.py.
      var hRow = newRows.length + 4;
      var vlookupH = '=IFERROR(VLOOKUP(B' + hRow +
        ';ДАННЫЕ_Губарев!$A$4:$L$503;12;0);0)' +
        '+IFERROR(VLOOKUP(B' + hRow +
        ';ДАННЫЕ_Перфильев!$A$4:$L$503;12;0);0)';

      newRows.push([
        today,                    // A: дата синка
        restaurant,               // B: ресторан
        managerName,              // C: менеджер поиска
        'из КПИ ' + kpiSheetName,// D: примечание
        kpiSheetName,             // E: период
        amount,                   // F: сумма
        amount,                   // G: сумма для SUMIF
        vlookupH                  // H: оборот (формула)
      ]);
    }
  }

  // Обновляем НОВЫЕ_КЛИЕНТЫ
  var ncSheet = mainSS.getSheetByName('НОВЫЕ_КЛИЕНТЫ');
  var clearRange = ncSheet.getRange(4, 1, 200, 8);
  clearRange.clearContent();

  if (newRows.length > 0) {
    // Пишем данные без формул отдельно, потом формулы H
    var dataOnly = newRows.map(function(r) { return r.slice(0, 7).concat(['']); });
    ncSheet.getRange(4, 1, newRows.length, 8).setValues(dataOnly);

    // Формулы в столбце H
    var hFormulas = newRows.map(function(r) { return [r[7]]; });
    ncSheet.getRange(4, 8, newRows.length, 1).setFormulas(hFormulas);
  }

  // Обновляем ДАШБОРД_ДАННЫЕ (C102 в СВОДНАЯ_ЗП обновится автоматически через формулу)
  Logger.log('Синхронизировано: ' + newRows.length + ' строк из «' + kpiSheetName + '»');
  return 'OK: ' + newRows.length + ' строк';
}

// Запустить один раз для установки ежедневного триггера
// ⛔️ Снять ночной триггер синка (2026-08-07: синк переехал в sync_novye.py).
// Запустить ОДИН РАЗ из редактора Apps Script: выбрать removeSyncTrigger → «Выполнить».
function removeSyncTrigger() {
  var n = 0;
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'syncNewClientsFromKPI') {
      ScriptApp.deleteTrigger(t);
      n++;
    }
  });
  Logger.log('Удалено триггеров syncNewClientsFromKPI: ' + n);
  return 'Удалено триггеров: ' + n;
}

// ⚠️ УСТАРЕЛО — НЕ ЗАПУСКАТЬ: вернёт ночной дубль синка (см. комментарий выше).
function setupDailyTrigger() {
  // Удаляем старые триггеры этой функции
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'syncNewClientsFromKPI') {
      ScriptApp.deleteTrigger(t);
    }
  });
  // Создаём новый — каждую ночь в 03:00
  ScriptApp.newTrigger('syncNewClientsFromKPI')
    .timeBased()
    .everyDays(1)
    .atHour(3)
    .create();
  Logger.log('Триггер установлен: синк каждую ночь в 03:00');
}
