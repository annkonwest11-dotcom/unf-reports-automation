# 📁 Описание файлов проекта

## Основные файлы (ядро проекта)

### `bot.py` (850 строк)
**Статус:** ⚠️ Нуждается в рефакторинге

**Что делает:**
- Получает обновления из Telegram (polling)
- Классифицирует сообщения (смена / команда / запрос)
- Маршрутизирует к обработчикам
- Отправляет ответы в Telegram

**Основные функции:**
```
handle_start()              ← /start (регистрация)
handle_sync_1c()            ← /sync_1c (синхронизация 1С)
handle_message()            ← Основная функция (850 строк!)
_handle_report()            ← Получить отчёт за день
_handle_archive_request()   ← Архивирование месяца
_handle_archive_confirm()   ← Подтверждение архива
_check_calls_norm()         ← Проверка звонков
_check_early_report()       ← Ранний отчёт?
_check_wrong_date()         ← Неправильная дата?
auto_anna_shift()           ← Автоматическая смена Анне (11:00)
auto_sync_1c()              ← Автосинхронизация (7:00)
check_missing_reports()     ← Кто не сдал? (21:00)
```

**Зависимости:**
- `parser.py` (парсинг смен)
- `sheets.py` (работа с Google Sheets)
- `sync_42clouds_v2.py` (синхронизация 1С)
- `telegram` (Bot API)

**Проблемы:**
- ❌ Слишком большой файл (850 строк)
- ❌ Смешивает routing, обработку, логирование
- ❌ Трудно тестировать
- ❌ Трудно добавить новый функционал

---

### `parser.py`
**Статус:** ✅ OK

**Что делает:**
Парсит текстовые отчёты о смене.

**Функция:**
```python
parse_report(text: str) -> ShiftReport | None
```

**Пример входа:**
```
смена 25 5 100 рест.1тел:2 250
```

**Пример выхода:**
```python
ShiftReport(
    employee="...",
    date="25",
    main_shifts=5,
    main_amount=100,
    side_work={'рест.1тел': 2},
    side_amount=250,
    ...
)
```

**Не трогать:** Работает хорошо.

---

### `sheets.py` (SheetsClient)
**Статус:** ✅ OK

**Что делает:**
Работает с Google Sheets через API.

**Основные методы:**
```python
class SheetsClient:
    update_report(report)           ← Добавить смену в СМЕНЫ
    get_report(period)              ← Получить отчёт за день
    archive_month()                 ← Архивирование
    get_employees_without_report()  ← Кто не сдал?
    write_shift(name, day)          ← Записать смену
```

**Зависимости:**
- `google.auth` (Google API)

**Не трогать:** Работает хорошо.

---

### `sync_42clouds_v2.py`
**Статус:** ✅ OK

**Что делает:**
Синхронизирует данные из облачной 1С (OData) в Google Sheets.

**Основная функция:**
```python
def sync_all_bases():
    # Для каждой базы:
    # 1. Загружает дебиторку (AccumulationRegister_РасчетыСПокупателями)
    # 2. Загружает взаиморасчёты (по договорам)
    # 3. Сохраняет в Google Sheets листы ИНТЕГРАЦИЯ и ВЗАИМОРАСЧЁТЫ
```

**Зависимости:**
- `requests` (HTTP)
- `sheets.py` (запись в таблицу)

**Не трогать:** Работает хорошо.

---

### `telegram_reports.py` (600 строк)
**Статус:** ❌ ДУБЛИРУЕТ Code.gs

**Что делает:**
Отправляет отчёты из OData в Telegram.

**Функции:**
```python
send_all_reports(base='both')
report_sales(base_id, base_name, date_str)
report_receivables(base_id, base_name)
report_activity(base_id, base_name, days=14)
```

**Проблема:**
```
❌ Этот файл дублирует Code.gs (Google Apps Script)
❌ Логика OData парсинга в двух местах
❌ Запускается как отдельный скрипт (не часть бота)
❌ Нужна консолидация
```

**План:** Перенести в `clients/odata_client.py`

---

## Конфигурационные файлы

### `.env`
**Статус:** ✅ OK (но не коммитится)

**Содержит:**
```
BOT_TOKEN=...
SPREADSHEET_ID=...
ANNA_CHAT_ID=...
GROUP_CHAT_ID=...
CREDENTIALS_PATH=./credentials.json
```

**Примечание:** Хранится в `.gitignore` (secrets).

---

### `.clasp.json`
**Статус:** ⚠️ Google Apps Script конфиг

**Содержит:**
```json
{
  "scriptId": "...",
  "rootDir": "."
}
```

**Примечание:** Для развертывания Google Apps Script.

---

### `credentials.json`
**Статус:** ⚠️ Google API credentials

**Содержит:** OAuth2 credentials для доступа к Google Sheets.

**Примечание:** Не коммитится (в `.gitignore`).

---

## Данные и логи

### `employees.json`
**Статус:** ✅ OK

**Содержит:** Регистрацию пользователей
```json
{
  "12345": "Иван Петров",
  "67890": "Мария Сидорова"
}
```

**Кто создаёт:** Bot при регистрации (`/start`).

---

### `last_update_id.txt`
**Статус:** ✅ OK

**Содержит:** Последний ID обновления Telegram (для восстановления).

**Пример:**
```
987654321
```

**Зачем:** При рестарте бота загружает пропущенные обновления.

---

### `bot.log` / `bot_session.log` / `bot_startup.log`
**Статус:** ⚠️ Логи, но разбросаны

**Проблема:**
```
❌ Логи в разных файлах
❌ Нет централизованного логирования
❌ Трудно отследить ошибку
```

**План:** Переместить в `clients/log_client.py`

---

## Google Apps Script

### `Code.gs` (1000 строк)
**Статус:** ❌ ДУБЛИРУЕТ telegram_reports.py

**Что делает:**
- Получает webhook'и от Telegram
- Обрабатывает команды (/today, /range, /reports)
- Загружает OData из 1С
- Заполняет Google Sheets DASHBOARD
- Отправляет отчёты в Telegram

**Основные функции:**
```python
doPost(e)                      ← Webhook от Telegram
doGet(e)                       ← GET requests
handleTelegramUpdate(update)   ← Обработка команд
sendODataReport()              ← Загрузка и отправка отчёта
fetchAllODataRecords()         ← OData запрос
testODataOneBase()             ← Диагностика OData
```

**Проблема:**
```
❌ Дублирует telegram_reports.py (Python)
❌ Усложняет поддержку (нужно менять в двух местах)
❌ OData логика в Python И в GAS одновременно
❌ Потенциальные конфликты
```

**План:** Перенести логику в Python, убрать GAS.

---

## Документация

### `PROJECT_DOCS/` (текущая папка)
**Статус:** ✅ Создана сейчас

**Содержит:**
```
README.md           ← Главный файл
OVERVIEW.md         ← Описание проекта
CURRENT_STATE.md    ← Текущее состояние
ARCHITECTURE.md     ← Архитектура решения
COMPONENTS.md       ← Описание компонентов
FILES.md            ← Этот файл
ISSUES.md           ← Известные проблемы
TECH_STACK.md       ← Технологии
CONFIG.md           ← Конфигурация
```

---

### `ARCHITECTURE.md` (в корне проекта)
**Статус:** ✅ Предлагаемая архитектура

**Содержит:** Как переделать систему (рефакторинг).

---

## Вспомогательные файлы

### `requirements.txt`
**Статус:** ⚠️ Может быть не полный

**Должен содержать:**
```
python-telegram-bot==20.x
google-auth-oauthlib
google-auth-httplib2
google-api-python-client
requests
python-dotenv
```

---

### `.gitignore`
**Статус:** ✅ OK

**Игнорирует:**
```
.env
credentials.json
employees.json
*.log
__pycache__/
venv/
```

---

## Будущие файлы (в рефакторинге)

### `handlers/` (НОВАЯ ПАПКА)
```
shift_handler.py      ← Обработка смен
report_handler.py     ← Обработка отчётов
admin_handler.py      ← Команды Анны
registration_handler.py ← Регистрация
```

---

### `clients/` (НОВАЯ ПАПКА)
```
sheets_client.py      ← Перемещение из sheets.py
odata_client.py       ← OData парсер (из telegram_reports.py + Code.gs)
telegram_client.py    ← Отправка сообщений
log_client.py         ← Логирование
```

---

### `models.py` (НОВЫЙ ФАЙЛ)
```python
@dataclass
class ShiftReport:
    employee: str
    date: str
    # ... и так далее
```

---

## 📊 Статистика

| Файл | Строк | Статус | Комментарий |
|------|-------|--------|------------|
| bot.py | 850 | ❌ Рефакторинг | Слишком большой |
| Code.gs | 1000 | ❌ Дублирует | Убрать |
| telegram_reports.py | 600 | ❌ Дублирует | Убрать |
| parser.py | ~150 | ✅ OK | Не менять |
| sheets.py | ~200 | ✅ OK | Не менять |
| sync_42clouds_v2.py | ~200 | ✅ OK | Не менять |
| **ВСЕГО** | **~3000** | | |

**План:** Переделав на handlers + clients, уменьшим размер и улучшим читаемость.
