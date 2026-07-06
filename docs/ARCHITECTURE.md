# 🏗️ Архитектура бота — просто и понятно

## 🎯 3 слоя

```
TELEGRAM (пользователи)
    ↓
СЛОЙ 1: Message Router (bot.py)
    ↓ маршрутизирует
СЛОЙ 2: Handlers (обработчики)
    ↓ используют
СЛОЙ 3: Clients (интеграции)
    ↓
ВНЕШНИЕ СЕРВИСЫ (Google Sheets, OData, Telegram API)
```

---

## СЛОЙ 1: Главный файл (bot.py)

**Что делает:** Получает сообщение, определяет что делать, кому передать.

```python
# bot.py — только маршрутизация!

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Определяет что пришло и где обработать"""
    text = update.message.text
    
    if is_command(text, '/start'):
        # → RegistrationHandler
        pass
    elif is_command(text, '/sync_1c'):
        # → AdminHandler
        pass
    elif text.startswith('смена'):
        # → ShiftHandler
        pass
    elif is_command(text, '/reports'):
        # → ReportHandler
        pass
```

---

## СЛОЙ 2: Обработчики (handlers/)

**Что делают:** Каждый обработчик отвечает за одну задачу.

### Handler 1: ShiftHandler (смены сотрудников)
```python
# handlers/shift_handler.py

class ShiftHandler:
    async def handle(text: str, user_id: int):
        # 1. Распарсить текст → ShiftReport
        report = parse_report(text)  # используем существующий parser.py
        
        # 2. Сохранить в Sheets
        sheets_client.update_report(report)
        
        # 3. Проверить аномалии и отправить алерты
        if report.calls_total < 20:
            telegram_client.send_alert("Мало звонков", ...)
```

### Handler 2: ReportHandler (отчёты из 1С)
```python
# handlers/report_handler.py

class ReportHandler:
    async def handle(cmd: str, date_range):
        base_id = 'perfilev'  # или 'gubarev'
        
        # 1. Загрузить данные из OData
        odata = ODataClient(base_id)
        sales = odata.fetch_sales(date_range)
        receivables = odata.fetch_receivables()
        
        # 2. Форматировать текст
        text = format_report(sales, receivables)
        
        # 3. Отправить в Telegram
        telegram_client.send_message(text)
```

### Handler 3: AdminHandler (команды Анны)
```python
# handlers/admin_handler.py

class AdminHandler:
    async def handle_sync_1c():
        # Синхронизирует все данные из 1С в Google Sheets
        sync_42clouds_v2.sync_all_bases()  # используем существующий
    
    async def handle_archive_month():
        # Архивирует месяц
        sheets_client.archive_month()
```

---

## СЛОЙ 3: Клиенты (clients/)

**Что делают:** Разговаривают с внешними сервисами (Google Sheets, OData, Telegram).

### Client 1: ODataClient (1С OData)
```python
# clients/odata_client.py

class ODataClient:
    def __init__(base_id):  # 'perfilev' or 'gubarev'
        self.base_url = f"https://base.42clouds.com/unf/{base_id}/odata/standard.odata/"
    
    def fetch_sales(date_start, date_end):
        # GET /AccumulationRegister_Продажи_RecordType?$filter=...
        # Возвращает список продаж
    
    def fetch_receivables():
        # GET /AccumulationRegister_РасчетыСПокупателями_RecordType
        # Возвращает дебиторку по должникам
```

### Client 2: SheetsClient (Google Sheets)
```python
# clients/sheets_client.py

class SheetsClient:
    def update_report(report):
        # Добавляет строку в лист СМЕНЫ
    
    def archive_month():
        # Копирует листы с суффиксом _АРХИВ
        # Очищает рабочие листы
```

### Client 3: TelegramClient (Telegram)
```python
# clients/telegram_client.py

class TelegramClient:
    def send_message(chat_id, text):
        # POST /sendMessage с текстом
    
    def send_alert(chat_id, alert_type, details):
        # Отправляет уведомление (красивое)
```

---

## 📁 Структура файлов

```
claude-test/
├── bot.py                    ← ГЛАВНЫЙ ФАЙЛ (Message Router)
├── parser.py                 ← Существующий, не трогаем
├── sheets.py                 ← Существующий SheetsClient
├── sync_42clouds_v2.py       ← Существующий синк
│
├── handlers/                 ← НОВАЯ ПАПКА
│   ├── __init__.py
│   ├── shift_handler.py      ← обработка смен
│   ├── report_handler.py     ← обработка отчётов
│   └── admin_handler.py      ← команды Анны
│
├── clients/                  ← НОВАЯ ПАПКА
│   ├── __init__.py
│   ├── sheets_client.py      ← перемещаем из sheets.py
│   ├── odata_client.py       ← новый (логика из telegram_reports.py)
│   └── telegram_client.py    ← отправка сообщений
│
└── models.py                 ← Простые dataclasses
```

---

## 🔄 Пример: Как работает отчёт о смене

```
Сотрудник в чат: "смена 25 5 100 рест.1тел:2 250"
                    ↓
bot.py → handle_message()
    ↓ определяет: это смена
ShiftHandler.handle(text)
    ↓
    1. parser.parse_report(text) → ShiftReport объект
    2. SheetsClient.update_report(report) → вставить в Google Sheets
    3. проверить: report.calls_total < 20?
       → TelegramClient.send_alert("Мало звонков")
    ↓
TelegramClient.send_message(chat_id, "✅ Отчёт сохранён")
```

---

## 🔄 Пример: Как работает команда отчёта

```
Анна: "/reports_perfilev 25.06 25.06"
                    ↓
bot.py → handle_message()
    ↓ определяет: это отчёт
ReportHandler.handle("/reports_perfilev", ("2026-06-25", "2026-06-25"))
    ↓
    1. ODataClient('perfilev').fetch_sales(...)
    2. ODataClient('perfilev').fetch_receivables()
    3. format_report(sales, receivables) → красивый текст
    4. TelegramClient.send_message(anna_id, text)
    ↓
Анна получает отчёт в личку
```

---

## 💡 Почему так лучше?

| Было | Стало |
|------|-------|
| Всё в bot.py (1000+ строк) | Разделено на файлы по смыслу |
| OData парсер в 2 местах | ODataClient в одном месте |
| Трудно добавить новый отчёт | Просто создать новый Handler |
| Трудно найти ошибку | Понятно в каком файле искать |

---

## 📋 Как начать переделку?

### Шаг 1: Создать папки и файлы (15 мин)
```bash
mkdir -p handlers clients
touch handlers/__init__.py handlers/shift_handler.py
touch handlers/report_handler.py handlers/admin_handler.py
touch clients/__init__.py clients/odata_client.py
touch clients/telegram_client.py
```

### Шаг 2: Переместить code из bot.py в handlers
- `handle_message()` → логика в ShiftHandler.handle()
- Команды `/start` → логика в RegistrationHandler.handle()
- Команды `/sync_1c`, `/archive` → логика в AdminHandler.handle()

### Шаг 3: Создать ODataClient (новый компонент)
- Скопировать логику из `telegram_reports.py` и `Code.gs`
- Упростить (убрать дублирование)

### Шаг 4: Refactor bot.py
- Оставить только маршрутизацию (какой handler вызвать?)
- Удалить весь остальной код

---

## ❓ Вопросы?

1. **Нужна ли реальная реализация?** (начать писать код)
2. **Или сначала уточнить дизайн?**
3. **Какой приоритет?** (срочно или спокойно)

### 1️⃣ **Message Router** (точка входа)
**Файл:** `bot.py` (основной)  
**Ответственность:**
- Получает все сообщения из Telegram
- Классифицирует тип сообщения (shift report / command / query)
- Маршрутизирует к нужному обработчику
- Осуществляет аутентификацию и авторизацию

**API:**
```python
class MessageRouter:
    async def route(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Определяет тип сообщения и вызывает нужный handler.
        
        Types:
        - "shift_report" → ShiftHandler
        - "admin_command" → AdminHandler  
        - "report_query" → ReportHandler
        - "user_registration" → RegistrationHandler
        """
```

---

### 2️⃣ **ShiftHandler** (учёт смен)
**Файл:** `handlers/shift_handler.py`  
**Ответственность:**
- Парсинг отчётов о смене (текст, фото, документ)
- Валидация данных смены
- Запись в Google Sheets лист СМЕНЫ
- Проверка аномалий (низкие звонки, ранние отчёты, неправильная дата)

**API:**
```python
class ShiftHandler:
    async def handle_shift_report(report_text: str, user_id: int) -> ShiftReport:
        """
        Парсит отчёт, валидирует, сохраняет.
        Returns: ShiftReport (успешно сохранён)
        Raises: ParseError, ValidationError, SheetError
        """
```

**Данные:** `ShiftReport`
```python
@dataclass
class ShiftReport:
    employee: str
    date: str
    main_shifts: int
    main_amount: int
    side_work: dict  # {category: count}
    side_amount: int
    timestamp: datetime
    source_user_id: int
```

---

### 3️⃣ **ReportHandler** (отчёты из OData)
**Файл:** `handlers/report_handler.py`  
**Ответственность:**
- Обработка команд `/reports_perfilev`, `/reports_gubarev`, `/today`, `/range`
- Координация с ODataClient для загрузки данных
- Форматирование и отправка отчётов в Telegram
- Кэширование результатов

**API:**
```python
class ReportHandler:
    async def handle_report_command(
        cmd: str,  # /reports_perfilev, /today, /range
        base_id: str,  # 'perfilev' or 'gubarev'
        date_range: Tuple[str, str],  # ('YYYY-MM-DD', 'YYYY-MM-DD')
        chat_id: int
    ) -> Dict[str, Any]:
        """Генерирует и отправляет отчёт."""
```

---

### 4️⃣ **AdminHandler** (команды Анны)
**Файл:** `handlers/admin_handler.py`  
**Ответственность:**
- Обработка `/sync_1c` (синхронизация 1С → Google Sheets)
- Обработка `/archive` (архивирование месяца)
- Проверка разрешений (только Анна)
- Логирование действий

**API:**
```python
class AdminHandler:
    async def handle_sync_1c() -> SyncResult:
        """Синхронизирует все базы из 1С."""
    
    async def handle_archive_month(period: str) -> ArchiveResult:
        """Архивирует месяц: копирует листы, очищает рабочие данные."""
```

---

### 5️⃣ **RegistrationHandler** (регистрация пользователей)
**Файл:** `handlers/registration_handler.py`  
**Ответственность:**
- Регистрация новых пользователей
- Хранение сопоставления (user_id → name)
- Валидация имён

**API:**
```python
class RegistrationHandler:
    async def start_registration(user_id: int, user_name: str):
        """Начинает процесс регистрации."""
    
    async def complete_registration(user_id: int, reported_name: str) -> bool:
        """Завершает регистрацию, сохраняет в employees.json."""
```

---

## 🔌 Инфраструктурные компоненты (Clients)

### **SheetsClient**
**Файл:** `clients/sheets_client.py`  
**Ответственность:** Все операции с Google Sheets  
**Методы:**
```python
class SheetsClient:
    def update_report(report: ShiftReport) -> bool
    def get_report(period: str) -> Dict  # для команды /смена
    def archive_month() -> str  # архивирует и возвращает период
    def get_employees_without_report(day: int) -> List[str]
    def write_shift(name: str, day: int) -> bool
```

---

### **ODataClient**
**Файл:** `clients/odata_client.py`  
**Ответственность:** Все запросы к OData 1С  
**Методы:**
```python
class ODataClient:
    def __init__(base_id: str):  # 'perfilev' or 'gubarev'
        pass
    
    def fetch_sales(date_start: str, date_end: str) -> List[Sale]
    def fetch_receivables() -> Dict[str, Receivable]  # по должнику
    def fetch_settlements() -> List[Settlement]
    def fetch_contractors() -> Dict[str, Contractor]
    
    # Кэширование
    def get_cached_sales(...) -> Optional[List[Sale]]
    def invalidate_cache()
```

**Данные:**
```python
@dataclass
class Sale:
    period: str
    contractor_key: str
    amount: float
    record_type: str  # 'Receipt' | 'Expense'

@dataclass
class Receivable:
    contractor_key: str
    contractor_name: str
    total_debt: float
    overdue_days: int
    top_contracts: List[Dict]  # что просрочено
```

---

### **TelegramClient**
**Файл:** `clients/telegram_client.py`  
**Ответственность:** Отправка сообщений в Telegram  
**Методы:**
```python
class TelegramClient:
    async def send_message(chat_id: int, text: str, **kwargs)
    async def send_report(chat_id: int, report: Report)
    async def send_alert(chat_id: int, alert_type: str, details: Dict)
    async def send_notification(user_id: int, title: str, body: str)
```

---

### **LogClient**
**Файл:** `clients/log_client.py`  
**Ответственность:** Логирование всех операций  
**Методы:**
```python
class LogClient:
    def log_event(
        event_type: str,  # 'SHIFT_REPORT' | 'SYNC_1C' | 'ERROR'
        base_id: Optional[str],
        details: Dict,
        severity: str = 'INFO'  # 'INFO' | 'WARNING' | 'ERROR'
    )
```

---

## 🔄 Потоки данных

### Поток 1: Отчёт о смене (сотрудник → Google Sheets)
```
┌──────────────────────────────────────────────────────────┐
│ Сотрудник пишет в групповой чат:                        │
│ "смена 25 5 100 рест.1тел:2 250"                        │
└──────┬───────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ Message Router               │
│ • Аутентификация (user_id)   │
│ • Классификация              │
│ → тип = "shift_report"       │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ ShiftHandler.parse_report()  │
│ • Парсинг текста             │
│ • Валидация данных           │
│ → ShiftReport object         │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ SheetsClient.update_report() │
│ • INSERT в лист СМЕНЫ        │
│ • Вычисление сумм            │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ Google Sheets СМЕНЫ          │
│ • Новая строка добавлена     │
│ • Формулы пересчитаны       │
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ Проверка аномалий            │
│ • Низкие звонки? → Alert     │
│ • Ранний отчёт? → Alert      │
│ • Неправильная дата? → Alert │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ TelegramClient.send_alert()  │
│ • Уведомление Анне           │
└──────────────────────────────┘
```

---

### Поток 2: Команда отчёта (Анна → OData → Telegram)
```
┌──────────────────────────────────────────────────────────┐
│ Анна в личке пишет:                                      │
│ "/reports_perfilev 25.06 25.06"                          │
└──────┬───────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ Message Router                            │
│ • Проверка: _is_from_anna()              │
│ • Классификация → "report_query"         │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ ReportHandler.handle_report_command()    │
│ • Парсинг дат                            │
│ • Выбор базы (perfilev)                  │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ ODataClient('perfilev')                  │
│ .fetch_metrics(start, end)               │
│                                          │
│ ┌─────────────────────────────────────┐  │
│ │ • fetch_sales() - продажи           │  │
│ │ • fetch_receivables() - дебиторка   │  │
│ │ • fetch_contracts() - контрагенты   │  │
│ └─────────────────────────────────────┘  │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ OData REST API (42clouds)                │
│ GET /odata/standard.odata/               │
│   Catalog_Контрагенты                    │
│   AccumulationRegister_Продажи_RecordType│
│   AccumulationRegister_РасчетыСПоку...  │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ ReportFormatter.format_odata_report()    │
│ • Структурирование данных                │
│ • Форматирование текста (HTML)           │
│ → Report object                          │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ TelegramClient.send_report()             │
│ • Разбор на части (макс 3900 симв)      │
│ • Отправка в личку Анне                 │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ Telegram (API)                           │
│ sendMessage → Анна получает отчёт       │
└──────────────────────────────────────────┘
```

---

### Поток 3: Синхронизация 1С (Анна → sync_42clouds → Google Sheets)
```
┌──────────────────────────────────────────────────────────┐
│ Анна в личке пишет: "/sync_1c"                           │
└──────┬───────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ AdminHandler.handle_sync_1c()            │
│ • Проверка разрешений (Анна)             │
│ • Сообщение пользователю: "Начинаю..."   │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ SyncCoordinator.sync_all_bases()         │
│ (это sync_42clouds_v2.sync_all_bases)    │
│                                          │
│ ┌─────────────────────────────────────┐  │
│ │ sync_base('perfilev')               │  │
│ │ sync_base('gubarev')                │  │
│ └─────────────────────────────────────┘  │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ ДЛЯ КАЖДОЙ БАЗЫ:                        │
│ 1. ODataClient.fetch_all_sales()        │
│ 2. ODataClient.fetch_all_settlements()  │
│ 3. ODataClient.fetch_contractors()      │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ OData REST API → Получение данных       │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ SheetsClient.sync_receivables()          │
│ • Очистка листа ИНТЕГРАЦИЯ               │
│ • Вставка всех дебиторов                │
│ • Вычисление сумм                       │
│                                          │
│ + SheetsClient.sync_settlements()        │
│ • Очистка листа ВЗАИМОРАСЧЁТЫ           │
│ • Вставка взаиморасчётов по контрактам  │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ Google Sheets                            │
│ • Листы обновлены с данными из 1С       │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ LogClient.log_event()                    │
│ type="SYNC_1C", severity="INFO"          │
│ → запись в лист LOG                     │
└──────┬───────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────┐
│ TelegramClient.send_message()            │
│ "✅ Синхронизация завершена успешно"    │
└──────────────────────────────────────────┘
```

---

## 🔀 API контракты между компонентами

### **Message Router → Handler**
```python
# Input
class TelegramMessage:
    update_id: int
    user_id: int
    chat_id: int
    chat_type: str  # 'private' | 'group' | 'supergroup'
    text: str
    timestamp: datetime

# Output (Result)
class HandlerResult:
    success: bool
    message: str  # ответ пользователю
    log_event: Optional[LogEvent]
    alerts: List[Alert]  # уведомления
```

### **Handler → SheetsClient**
```python
# Shift Handler → Sheets
class ShiftOperation:
    operation: str  # 'insert' | 'update' | 'archive'
    sheet_name: str  # 'СМЕНЫ'
    row_data: List[Any]
    formula_range: Optional[str]  # для пересчёта

# Report Query → Sheets
class ReportQuery:
    period: str  # "июнь 2026" or "25.06"
    date_from: str  # "2026-06-25"
    date_to: str  # "2026-06-25"
    include_amounts: bool
```

### **Handler → ODataClient**
```python
# Request
class ODataQuery:
    base_id: str  # 'perfilev' | 'gubarev'
    entity: str  # 'Catalog_Контрагенты'
    filter: Optional[str]  # OData $filter
    select: Optional[str]  # OData $select
    
# Response
class ODataResult:
    success: bool
    data: List[Dict]
    record_count: int
    fetch_time_ms: int
```

### **Client → External API**
```python
# ODataClient → OData REST API
GET https://base.42clouds.com/unf/{base_id}/odata/standard.odata/{Entity}
Authorization: Basic {base64(login:password)}
?$filter=Period ge datetime'{date_start}T00:00:00'
?$select=Ref_Key,Description,Period,Сумма

# Response: { "value": [...], "@odata.nextLink": "..." }

# TelegramClient → Telegram API
POST https://api.telegram.org/bot{TOKEN}/sendMessage
{ "chat_id": ..., "text": ..., "parse_mode": "HTML" }
```

---

## 📊 Структура данных (единый словарь)

### **Отчёт о смене** (Report Document)
```python
@dataclass
class ShiftReport:
    employee: str                # "Иван Петров"
    date: str                    # "25" или "25.06"
    main_shifts: int             # основные смены
    main_amount: int             # сумма за основные
    side_work: Dict[str, int]    # {"рест.1тел": 2, "фирмы+1тел": 1}
    side_amount: int             # сумма за подработки
    calls_total: Optional[str]   # "45" (только для менеджеров)
    manager_type: Optional[str]  # "поиск" | "вторая"
    source_user_id: int          # ID отправившего
    timestamp: datetime          # когда получено
    parsed_at: datetime          # когда спарсено
```

### **Метрики из OData** (Business Metrics)
```python
@dataclass
class Metrics:
    sales_total: float           # ₽ продано
    sales_prev: float            # ₽ в прошлом периоде
    sales_dynamics_pct: int      # % изменения
    sales_avg_per_day: float     # ₽/день
    sales_forecast: float        # прогноз оборота
    
    receivables_total: float     # ₽ всего дебиторки
    receivables_overdue: float   # ₽ просрочено (>30дн)
    receivables_by_ctg: Dict     # по должникам
    
    settlements_they_owe: float  # ₽ нам должны
    settlements_we_owe: float    # ₽ мы должны
    
    contractors_count: int       # сколько контрагентов
    contractors_active: int      # активных за период
```

---

## 🛡️ Обработка ошибок

```
┌─────────────────────────────────────────────────────────┐
│ Ошибка на любом уровне                                  │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ Exception → Handler (try-except)                         │
│ Определяет тип ошибки:                                  │
│ • ParseError → Ответ пользователю (невалидный формат)   │
│ • AuthError → Отказ в доступе                          │
│ • SheetError → Сообщение об ошибке Sheets              │
│ • ODataError → Ошибка подключения к 1С                 │
│ • TelegramError → Не удалось отправить                 │
│ • UnknownError → Сообщение Анне (для отладки)          │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ LogClient.log_event(                                     │
│     event_type='ERROR',                                 │
│     severity='ERROR' | 'WARNING',                        │
│     error_code=...,                                      │
│     traceback=...                                        │
│ )                                                        │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ Лист LOG в Google Sheets:                              │
│ Запись для анализа и отладки                           │
└──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ ЕСЛИ severity='ERROR':                                  │
│ • Отправить уведомление Анне                            │
│ • Заинкрементировать счётчик ошибок                     │
└──────────────────────────────────────────────────────────┘
```

---

## 📁 Предлагаемая структура файлов

```
claude-test/
├── bot.py                          # MAIN entry point (Message Router)
├── parser.py                       # Parsing utilities (keep as is)
├── sheets.py                       # Keep SheetsClient (refactor later)
├── sync_42clouds_v2.py             # Keep as SyncCoordinator
│
├── handlers/
│   ├── __init__.py
│   ├── base_handler.py            # базовый класс для всех
│   ├── shift_handler.py           # ShiftHandler
│   ├── report_handler.py          # ReportHandler
│   ├── admin_handler.py           # AdminHandler
│   └── registration_handler.py    # RegistrationHandler
│
├── clients/
│   ├── __init__.py
│   ├── sheets_client.py           # SheetsClient (рефакторить)
│   ├── odata_client.py            # ODataClient (новый)
│   ├── telegram_client.py         # TelegramClient (новый)
│   └── log_client.py              # LogClient (новый)
│
├── models/
│   ├── __init__.py
│   ├── shift_report.py            # ShiftReport dataclass
│   ├── metrics.py                 # Metrics dataclass
│   ├── exceptions.py              # Custom exceptions
│   └── constants.py               # Constants & configs
│
├── utils/
│   ├── __init__.py
│   ├── formatters.py              # Форматирование для Telegram
│   ├── validators.py              # Валидация данных
│   └── cache.py                   # Кэширование
│
├── config.py                       # Единый конфиг (вместо .env)
├── logger.py                       # Централизованное логирование
├── requirements.txt                # Зависимости
│
└── docs/
    └── ARCHITECTURE.md            # Этот файл
```

---

## ✅ Преимущества новой архитектуры

| Проблема | Было | Станет |
|----------|------|--------|
| **Дублирование OData** | OData парсер в `telegram_reports.py` и `Code.gs` | Единый `ODataClient` |
| **Смешанная ответственность** | Всё в `bot.py` (1000+ строк) | Разделение на handlers + clients |
| **Нет тестов** | Трудно писать тесты для монолита | Каждый handler легко тестировать |
| **Отладка** | Трудно найти баг (откуда ошибка?) | Четкие boundaries, логирование |
| **Масштабирование** | Сложно добавить новый report type | Просто добавить новый handler |
| **Конфигурация** | Разбросана по .env и PROPS | Единый `config.py` |
| **OData тайм-ауты** | Нет контроля | Timeout, retry, кэширование |
| **Эмодзи+HTML** | Дублирование форматирования | Единый `formatters.py` |

---

## 🚀 План миграции (пошагово)

### Этап 1: Создать инфраструктуру (без изменений в логике)
- [ ] Создать папки `handlers/`, `clients/`, `models/`, `utils/`
- [ ] Рефакторить `SheetsClient` из `sheets.py` в `clients/sheets_client.py`
- [ ] Создать `ODataClient` (скопировать логику из `telegram_reports.py` и `Code.gs`)
- [ ] Создать `TelegramClient` (логика отправки)
- [ ] Создать `LogClient` (логирование)

### Этап 2: Создать обработчики
- [ ] `handlers/shift_handler.py` (логика из `handle_message()`)
- [ ] `handlers/report_handler.py` (логика из `handle_message()` + `telegram_reports.py`)
- [ ] `handlers/admin_handler.py` (логика `/sync_1c`, `/archive`)
- [ ] `handlers/registration_handler.py` (логика `/start`)

### Этап 3: Переписать bot.py
- [ ] Создать `MessageRouter` как основной класс
- [ ] Заменить `handle_message()` на `router.route()`
- [ ] Удалить дублирование

### Этап 4: Миграция GAS → Python (опционально)
- [ ] Перенести `Code.gs` логику в Python
- [ ] Заменить GAS webhook на Python endpoint
- [ ] Удалить `telegram_reports.py`

---

## 📞 Вопросы для уточнения

1. **Оставить ли GAS для некритичной логики** (логирование в QUEUE)?
   - ✅ Да (самостоятельная система)
   - ❌ Нет (мигрировать всё в Python)

2. **Нужна ли история всех операций (LOG лист)?**
   - ✅ Да (важна для отладки и аудита)
   - ❌ Нет (логирование только в консоль)

3. **Какой приоритет рефакторингу?**
   - 🔥 Срочно 
  
