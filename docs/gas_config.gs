/**
 * Google Apps Script Configuration
 * Для 1С → Google Sheets → Telegram интеграции
 *
 * ⚠️ ЗАПОЛНИ ЭТИ ЗНАЧЕНИЯ:
 */

// ===== СЕКРЕТЫ И ТОКЕНЫ =====
// Хранить в Script Properties (не в коде!)
// Project Settings → Script Properties

const getSecrets = () => {
  const props = PropertiesService.getScriptProperties();
  return {
    TELEGRAM_TOKEN: props.getProperty('TELEGRAM_TOKEN') || 'YOUR_BOT_TOKEN_HERE',
    AUTH_TOKEN: props.getProperty('AUTH_TOKEN') || 'secret_shared_with_1c',
    SPREADSHEET_ID: props.getProperty('SPREADSHEET_ID') || 'YOUR_SHEET_ID_HERE',
  };
};

// ===== ДОПУСТИМЫЕ ЧАТЫ (WHITELIST) =====
// Telegram chat_id куда слать отчеты
const ALLOWED_CHATS = {
  'anna': 796207056,  // Анна Кономенко
  'channel': -1001234567890, // Групповой чат (если отрицательное число)
};

// ===== РАСПИСАНИЕ =====
const SCHEDULE = {
  DAILY_TIME: '09:30',        // Время ежедневного отчета (МСК)
  WEEKLY_DAY: 1,              // День недели (0=вс, 1=пн, 2=вт...)
  WEEKLY_TIME: '09:00',
  MONTHLY_DAY: 1,             // День месяца
  MONTHLY_TIME: '09:00',
  HALFYEAR_MONTH_START: [1, 7], // Январь, июль
  HALFYEAR_TIME: '09:00',
  YEAR_TIME: '09:00',
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
// Куда писать какие показатели
// Формат: { 'показатель': { 'perfilev': 'C5', 'gubarev': 'D5', 'total': 'E5' } }
const CELL_MAP = {
  // Продажи
  'sales_total': {
    perfilev: 'C5',
    gubarev: 'D5',
    total: 'E5',
  },
  'sales_dynamics_pct': {
    perfilev: 'C6',
    gubarev: 'D6',
    total: 'E6',
  },
  'sales_avg_per_day': {
    perfilev: 'C7',
    gubarev: 'D7',
    total: 'E7',
  },
  'sales_forecast': {
    perfilev: 'C8',
    gubarev: 'D8',
    total: 'E8',
  },

  // Взаиморасчеты
  'settlements_they_owe': {
    perfilev: 'C11',
    gubarev: 'D11',
    total: 'E11',
  },
  'settlements_we_owe': {
    perfilev: 'C12',
    gubarev: 'D12',
    total: 'E12',
  },

  // Дебиторка
  'receivables_total': {
    perfilev: 'C15',
    gubarev: 'D15',
    total: 'E15',
  },
  'receivables_overdue': {
    perfilev: 'C16',
    gubarev: 'D16',
    total: 'E16',
  },

  // Период отчета
  'period_start': 'B2',
  'period_end': 'B3',
  'generated_at': 'B4',
};

// ===== КОНСТАНТЫ =====
const TIMEOUT_MINUTES = 15;        // Сколько минут ждать вторую базу
const TOP_N = 5;                   // Кол-во позиций в топах
const TIME_ZONE = 'Europe/Moscow';
const CURRENCY_FORMAT = '₽';

// ===== БАЗЫ =====
const BASES = {
  perfilev: {
    name: 'ИП Перфильев',
    id: 'perfilev',
  },
  gubarev: {
    name: 'ИП Губарев',
    id: 'gubarev',
  },
};

// ===== ФУНКЦИИ ПОМОЩНИКИ =====

/**
 * Логирование с датой-временем
 */
const log = (message) => {
  const timestamp = new Date().toLocaleString('ru-RU', { timeZone: TIME_ZONE });
  console.log(`[${timestamp}] ${message}`);
};

/**
 * Логирование ошибки
 */
const logError = (message, error) => {
  const timestamp = new Date().toLocaleString('ru-RU', { timeZone: TIME_ZONE });
  console.error(`[${timestamp}] ERROR: ${message}`);
  if (error) {
    console.error(error.stack || error.toString());
  }
};

/**
 * Форматирование денег
 */
const formatMoney = (amount) => {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(amount);
};

/**
 * Форматирование даты
 */
const formatDate = (dateStr) => {
  const date = new Date(dateStr);
  return date.toLocaleDateString('ru-RU');
};

/**
 * Генерация UUID
 */
const generateUUID = () => {
  return Utilities.getUuid();
};
