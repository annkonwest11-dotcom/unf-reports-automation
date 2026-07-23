# 📋 План реализации интеграции 1С → Telegram → Google Sheets

## Этапы (в порядке выполнения)

### ✅ Фаза 1: Инфраструктура Google Sheets (ГОТОВО)
- [x] Листы для сырых данных (RAW_perfilev, RAW_gubarev)
- [x] Лист DASHBOARD с ячейками для значений
- [x] Листы для логирования (LOG, QUEUE)

### ⏳ Фаза 2: Google Apps Script Web App (СЕЙЧАС)
**Дата старта:** Сейчас
**Требуемые файлы:**
1. `gas_web_app.gs` — основное приложение (endpoints, обработчики)
2. `gas_config.gs` — конфигурация (карта ячеек, константы)
3. `gas_sheet_manager.gs` — работа с Google Sheets
4. `gas_excel_generator.gs` — генерация Excel
5. `gas_data_aggregator.gs` — объединение данных А+Б

**Что делает:**
- `POST /ingest` — принимает JSON от 1С, записывает в RAW_*
- `GET /pull-commands` — отдает очередь команд 1С
- Telegram webhook — принимает команды /today, /range
- Генерирует Excel и отправляет в Telegram
- Логирует все операции в LOG

### ⏳ Фаза 3: Расширение 1С (ПОСЛЕ GAS)
**Требуемые файлы:**
1. Модуль общего назначения — процедуры расчета показателей
2. Регламентное задание — ежедневная выгрузка (09:30)
3. Регламентное задание — опрос очереди (каждую минуту)
4. Обработчик webhook (если нужен)

### ⏳ Фаза 4: Тестирование и доработки
- Первый прогон синхронизации
- Проверка данных в RAW_*
- Проверка Excel
- Проверка Telegram доставки

---

## 🎯 Начинаем с Фазы 2: GAS Web App

### Что создам:

**Файлы для Google Apps Script (код на JavaScript):**

1. **gas_web_app.gs** (основной файл)
   - `doPost(e)` — handle POST /ingest
   - `doGet(e)` — handle GET /pull-commands
   - Telegram webhook
   - Обработка команд (/today, /range, /help)

2. **gas_config.gs** — конфигурация
   - TELEGRAM_TOKEN, AUTH_TOKEN
   - Карта ячеек DASHBOARD
   - ID Google Sheet
   - Whitelist чатов

3. **gas_sheet_manager.gs** — API для работы с листами
   - Запись сырых данных в RAW_perfilev, RAW_gubarev
   - Чтение и запись ячеек DASHBOARD
   - Работа с LOG и QUEUE

4. **gas_data_aggregator.gs** — логика объединения
   - Получить данные от обеих баз за один период
   - Объединить (суммировать)
   - Проверить что обе базы ответили

5. **gas_excel_generator.gs** — экспорт Excel
   - Экспортировать Google Sheets как .xlsx
   - Оформление (цвета, формат валюты)
   - Отправить в Telegram

### Структура Google Sheets:

```
Листы:
├── RAW_perfilev       (сырые данные из базы А)
│   ├── base_id = "perfilev"
│   ├── report_type, period, metrics (JSON)
│   └── timestamp
├── RAW_gubarev        (сырые данные из базы Б)
│   ├── base_id = "gubarev"
│   ├── report_type, period, metrics (JSON)
│   └── timestamp
├── DASHBOARD          (заполняемый дашборд)
│   ├── Перфильев (колонка C)
│   ├── Губарев (колонка D)
│   └── Итого (колонка E)
├── LOG               (журнал операций)
│   ├── timestamp
│   ├── base_id
│   ├── report_type
│   ├── status (success/error)
│   └── message
└── QUEUE             (очередь команд для 1С)
    ├── request_id (UUID)
    ├── report_type (daily/ondemand)
    ├── period_start
    ├── period_end
    ├── status (pending/executed)
    └── chat_id (для ответа)
```

### Контракт 1С ↔ GAS:

**POST /ingest (из 1С в GAS):**
```json
{
  "auth_token": "secret_token_here",
  "base_id": "perfilev|gubarev",
  "report_type": "daily|weekly|monthly|halfyear|yearly|ondemand",
  "period_start": "2026-06-18",
  "period_end": "2026-06-18",
  "generated_at": "2026-06-18T09:30:00+03:00",
  "request_id": "uuid-or-null",
  "metrics": {
    "settlements": { "they_owe_us": 0, "we_owe": 0 },
    "sales": {
      "total": 0,
      "prev_total": 0,
      "dynamics_abs": 0,
      "dynamics_pct": 0,
      "avg_per_day": 0,
      "forecast_turnover": 0
    },
    "clients_activity": {
      "growing": [{"name": "", "delta_abs": 0, "delta_pct": 0}],
      "declining": [{"name": "", "delta_abs": 0, "delta_pct": 0}],
      "falling": [{"name": "", "delta_abs": 0, "delta_pct": 0}]
    },
    "receivables": {
      "total": 0,
      "overdue": 0,
      "top_total": [{"name": "", "amount": 0}],
      "top_overdue": [{"name": "", "amount": 0, "days_overdue": 0}]
    }
  }
}
```

**GET /pull-commands (1С опрашивает очередь):**
```
Request: ?auth_token=secret&base_id=perfilev

Response:
{
  "commands": [
    {
      "request_id": "uuid",
      "report_type": "ondemand",
      "period_start": "2026-05-01",
      "period_end": "2026-05-31",
      "chat_id": 123456789
    }
  ]
}
```

---

## 🚀 Готов начинать?

Напиши:
1. **Google Sheet ID** (скопируй из URL: `https://docs.google.com/spreadsheets/d/[ЭТО_ID]/edit`)
2. **Telegram Bot Token** (у тебя уже есть)
3. **Какой auth_token** использовать (придумаем вместе)
4. **List of chat_id** где слать отчеты (whitelist)

Или скажи "старт" — я начну создавать с placeholder значениями, потом ты подставишь реальные.
