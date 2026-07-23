/**
 * GOOGLE APPS SCRIPT - КОНФИГУРАЦИЯ
 * 1С → Google Sheets → Telegram интеграция
 *
 * ⚠️ ВАЖНО: Эти значения уже заполнены с твоими реальными параметрами
 * Но тебе всё равно нужно добавить их в Script Properties!
 */

// ===== РЕАЛЬНЫЕ ЗНАЧЕНИЯ (ПОДСТАВЬ В SCRIPT PROPERTIES) =====
// Project Settings → Script properties → Add property

const REAL_CONFIG = {
  TELEGRAM_TOKEN: '8602166476:AAEo3ySMNmF38lyH0yppcW7CKejzXK_w7cY',
  SPREADSHEET_ID: '11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tTc',
  AUTH_TOKEN: 'unf2tg_a7Kд9P2mQ8xL5fR3vT6wZ1nB4hJ0sC',
};

// Получить конфигурацию (сначала из Script Properties, потом fallback)
const getConfig = () => {
  const props = PropertiesService.getScriptProperties();
  return {
    TELEGRAM_TOKEN: props.getProperty('TELEGRAM_TOKEN') || REAL_CONFIG.TELEGRAM_TOKEN,
    SPREADSHEET_ID: props.getProperty('SPREADSHEET_ID') || REAL_CONFIG.SPREADSHEET_ID,
    AUTH_TOKEN: props.getProperty('AUTH_TOKEN') || REAL_CONFIG.AUTH_TOKEN,
  };
};

// ===== ДОПУСТИМЫЕ ЧАТЫ (WHITELIST) =====
const ALLOWED_CHATS = {
  'anna': 796207056,  // Анна Кономенко
};

// ===== РАСПИСАНИЕ =====
const SCHEDULE = {
  DAILY_TIME: '09:30',
  WEEKLY_DAY: 1,
  WEEKLY_TIME: '09:00',
  MONTHLY_DAY: 1,
  MONTHLY_TIME: '09:00',
};

// ===== ЛИСТЫ GOOGLE SHEETS =====
const SHEET_NAMES = {
  RAW_PERFILEV: 'RAW_perfilev',
  RAW_GUBAREV: 'RAW_gubarev',
  DASHBOARD: 'DASHBOARD',
  LOG: 'LOG',
  QUEUE: 'QUEUE',
};

// ===== КАРТА ЯЧЕЕК DASHBOARD =====
const CELL_MAP = {
  'sales_total': { perfilev: 'C5', gubarev: 'D5', total: 'E5' },
  'sales_dynamics_pct': { perfilev: 'C6', gubarev: 'D6', total: 'E6' },
  'sales_avg_per_day': { perfilev: 'C7', gubarev: 'D7', total: 'E7' },
  'sales_forecast': { perfilev: 'C8', gubarev: 'D8', total: 'E8' },
  'settlements_they_owe': { perfilev: 'C11', gubarev: 'D11', total: 'E11' },
  'settlements_we_owe': { perfilev: 'C12', gubarev: 'D12', total: 'E12' },
  'receivables_total': { perfilev: 'C15', gubarev: 'D15', total: 'E15' },
  'receivables_overdue': { perfilev: 'C16', gubarev: 'D16', total: 'E16' },
  'period_start': 'B2',
  'period_end': 'B3',
  'generated_at': 'B4',
};

// ===== КОНСТАНТЫ =====
const TIMEOUT_MINUTES = 15;
const TOP_N = 5;
const TIME_ZONE = 'Europe/Moscow';
const CURRENCY_FORMAT = '₽';

const BASES = {
  perfilev: { name: 'ИП Перфильев', id: 'perfilev' },
  gubarev: { name: 'ИП Губарев', id: 'gubarev' },
};

// ===== ФУНКЦИИ ПОМОЩНИКИ =====

const log = (message) => {
  const timestamp = new Date().toLocaleString('ru-RU', { timeZone: TIME_ZONE });
  console.log(`[${timestamp}] ${message}`);
};

const logError = (message, error) => {
  const timestamp = new Date().toLocaleString('ru-RU', { timeZone: TIME_ZONE });
  console.error(`[${timestamp}] ERROR: ${message}`);
  if (error) {
    console.error(error.stack || error.toString());
  }
};

const formatMoney = (amount) => {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(amount);
};

const formatDate = (dateStr) => {
  const date = new Date(dateStr);
  return date.toLocaleDateString('ru-RU');
};

const generateUUID = () => {
  return Utilities.getUuid();
};

const getSpreadsheet = () => {
  return SpreadsheetApp.openById(getConfig().SPREADSHEET_ID);
};

const getSheet = (sheetName) => {
  return getSpreadsheet().getSheetByName(sheetName);
};
