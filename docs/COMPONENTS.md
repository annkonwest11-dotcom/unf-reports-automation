# 🔧 Описание компонентов (текущие)

## 1. Telegram Bot (`bot.py`)

**Тип:** Message Router + Handler  
**Язык:** Python  
**Зависимости:** python-telegram-bot, google-api, requests  

### Входные данные:
- Telegram сообщения (через polling)
- Команды Telegram
- Текстовые отчёты о смене

### Выходные данные:
- Ответы в Telegram
- Запись в Google Sheets
- Запросы к OData API
- Алерты Анне

### Основные обработчики:
```
handle_message()        ← Главная точка входа
  ├─ Смена → ShiftHandler (будущее)
  ├─ Команда → AdminHandler (будущее)
  ├─ Отчёт → ReportHandler (будущее)
  └─ Регистрация → RegistrationHandler (будущее)
```

### Функции в деталях:

#### `handle_message(update, context)`
Главная функция обработки сообщений. ~250 строк.
```python
1. Получить текст сообщения
2. Проверить тип (смена / команда / регистрация)
3. Определить отправителя (user_id, chat_id)
4. Выполнить соответствующую операцию
5. Отправить ответ
```

#### `_handle_report(update, context, text)`
Обработка команды `смена ДД.ММ`
```python
1. Парсить дату из текста
2. Получить отчёт из Google Sheets за эту дату
3. Форматировать красиво
4. Отправить в Telegram
```

#### `auto_anna_shift(context)`
Автоматическая смена Анне каждый день в 11:00
```python
1. Проверить день недели (пн-пт)
2. Записать смену для "Анна Кономенко (РОП)"
3. Залогировать результат
```

#### `check_missing_reports(context)`
Проверка (каждый день в 21:00) кто не сдал отчёт
```python
1. Получить список всех сотрудников
2. Получить список сдавших отчёт за сегодня
3. Вычислить разницу
4. Отправить уведомление в группу и Анне
```

#### `auto_sync_1c(context)`
Автоматическая синхронизация (каждый день в 7:00)
```python
1. Вызвать sync_42clouds_v2.sync_all_bases()
2. Дождаться результата
3. Отправить уведомление Анне
```

---

## 2. Parser (`parser.py`)

**Тип:** Утилита для парсинга  
**Язык:** Python  
**Зависимости:** нет (только регулярные выражения)  

### Назначение:
Парсить текстовый отчёт о смене в структурированный объект.

### API:
```python
def parse_report(text: str) -> ShiftReport | None
```

### Пример:
```
Вход:  "смена 25 5 100 рест.1тел:2 250"
Выход: ShiftReport(
         employee="...",
         date="25",
         main_shifts=5,
         main_amount=100,
         side_work={'рест.1тел': 2},
         side_amount=250
       )
```

### Форматы:
Поддерживает несколько форматов входа:
- `смена 25 5 100 рест.1тел:2 250`
- Фото (OCR - не реализовано)
- Документы (парсинг - не реализовано)

---

## 3. Google Sheets Client (`sheets.py`)

**Тип:** Инфраструктурный компонент  
**Язык:** Python  
**Зависимости:** google-api-python-client, google-auth  

### API методы:

#### `update_report(report: ShiftReport) -> bool`
Добавляет или обновляет отчёт о смене в Google Sheets.

```python
# Вход:
ShiftReport(employee="Иван", date="25", main_shifts=5, ...)

# Что происходит:
1. Открыть Google Sheets
2. Найти лист СМЕНЫ
3. Найти строку для этого сотрудника и даты
4. Вставить/обновить данные
5. Пересчитать формулы
```

#### `get_report(period: str) -> Dict`
Получает отчёт за день/период.

```python
# Вход: period="25.06" или period="июнь 2026"
# Выход:
{
  'period_label': 'июнь 2026',
  'основные': [('Иван', 5, 500), ...],
  'подработки': [('Иван', 2, 0, 0, 0, 250), ...],
}
```

#### `archive_month() -> str`
Архивирует месяц (копирует листы, очищает рабочие).

```python
# Что происходит:
1. Получить текущий период из НАСТРОЙКИ.B4
2. Скопировать листы СМЕНЫ и СВОДНАЯ_ЗП с суффиксом _АРХИВ
3. Очистить листы СМЕНЫ и СВОДНАЯ_ЗП
4. Обновить период в НАСТРОЙКИ.B4 на следующий месяц
```

#### `get_employees_without_report(day: int) -> List[str]`
Получает список сотрудников, не сдавших отчёт за день.

---

## 4. OData Client (текущий: в bot.py + telegram_reports.py)

**Тип:** Интеграция с облачной 1С  
**Язык:** Python + GAS  
**Источник:** 42clouds.com OData API  

### Текущее состояние:
```
❌ Разбросан на две части:
   - telegram_reports.py (Python)
   - Code.gs (Google Apps Script)
❌ Логика дублируется
❌ Нет централизации
```

### Основные операции:

#### `fetch_sales(date_start, date_end)`
Загружает продажи за период.

```python
# GET /AccumulationRegister_Продажи_RecordType
# ?$filter=Period ge datetime'2026-06-25T00:00:00' and ...
# Возвращает: [
#   {
#     'Period': '2026-06-25T10:30:00',
#     'Контрагент_Key': '...',
#     'Сумма': 5000,
#     'RecordType': 'Receipt'
#   },
#   ...
# ]
```

#### `fetch_receivables()`
Загружает дебиторку (должников).

```python
# GET /AccumulationRegister_РасчетыСПокупателями_RecordType
# Возвращает структурированный список с расчётом:
# - receipt - сумма, которую должны нам
# - expense - сумма авансов
# - balance = receipt - expense (положительная = долг)
```

#### `fetch_contractors()`
Загружает справочник контрагентов.

```python
# GET /Catalog_Контрагенты
# ?$select=Ref_Key,Description
# Возвращает: {
#   'ref_key_123': 'ООО Компания',
#   'ref_key_456': 'ИП Петров',
#   ...
# }
```

### Проблемы:
```
⚠️  Нет timeout защиты (может зависнуть)
⚠️  Нет retry логики
⚠️  Нет кэширования
⚠️  Нет обработки ошибок 404/401
⚠️  OData запросы могут быть долгими (>10s)
```

---

## 5. Sync 1C (`sync_42clouds_v2.py`)

**Тип:** Синхронизация данных  
**Язык:** Python  
**Зависимости:** requests, sheets.py  

### Назначение:
Загружает полные данные из 1С в Google Sheets (дебиторка, взаиморасчёты).

### Основная функция:
```python
def sync_all_bases():
    # Для Перфильева:
    # 1. Загрузить все дебиторы
    # 2. Сохранить в ИНТЕГРАЦИЯ
    # 
    # Для Губарева:
    # 1. Загрузить все дебиторы
    # 2. Сохранить в ИНТЕГРАЦИЯ (добавить)
    #
    # Для обеих:
    # 1. Загрузить все взаиморасчёты
    # 2. Сохранить в ВЗАИМОРАСЧЁТЫ
```

### Время выполнения:
```
~30 секунд (зависит от количества данных в 1С)
```

---

## 6. Google Apps Script (`Code.gs`)

**Тип:** Webhook + OData Client  
**Язык:** Google Apps Script (JavaScript)  
**Развёрнуто:** Google Apps Script platform  

### Назначение:
Альтернативный способ обработки команд и отправки отчётов.

### Основные функции:
```
doPost(e)               ← Получить webhook от Telegram
doGet(e)                ← GET requests
handleTelegramUpdate()  ← Обработать команду
sendODataReport()       ← Загрузить и отправить отчёт
```

### Проблема:
```
❌ Дублирует Python логику
❌ Поддерживать две системы одновременно
❌ Потенциальные конфликты
```

---

## 7. Telegram Reports (`telegram_reports.py`)

**Тип:** Standalone скрипт для отправки отчётов  
**Язык:** Python  
**Зависимости:** requests  

### Назначение:
Отправляет отчёты из OData в Telegram по-требованию.

### Основные функции:
```python
send_all_reports()      ← Отправить отчёты
report_sales()          ← Продажи за день
report_receivables()    ← Дебиторка
report_activity()       ← Активность клиентов
```

### Как запускается:
```bash
python telegram_reports.py perfilev  # Отчёты Перфильева
python telegram_reports.py gubarev   # Отчёты Губарева
python telegram_reports.py both      # Обеих
```

### Проблема:
```
❌ Запускается вручную (не интегрирован в бот)
❌ Дублирует OData логику из Code.gs
❌ Нужна консолидация
```

---

## 📊 Зависимости между компонентами

```
bot.py
  ├─ uses: parser.py
  ├─ uses: sheets.py
  ├─ uses: sync_42clouds_v2.py
  └─ uses: python-telegram-bot (Telegram API)

telegram_reports.py
  ├─ uses: requests (OData API)
  └─ uses: Telegram API (direct)

Code.gs (Google Apps Script)
  ├─ uses: UrlFetchApp (OData API)
  └─ uses: Telegram API (webhook)

sync_42clouds_v2.py
  ├─ uses: requests (OData API)
  └─ uses: sheets.py (сохранение)

sheets.py
  └─ uses: google-api-python-client
```

---

## 🎯 Улучшения (рефакторинг)

| Компонент | Текущее | Будущее |
|-----------|---------|---------|
| bot.py | Монолит (850 строк) | Message Router (50 строк) |
| handlers/ | не существует | shift, report, admin handlers |
| clients/ | не существует | sheets, odata, telegram clients |
| OData | в 2 местах (Py + GAS) | 1 место (ODataClient) |
| Code.gs | 1000 строк | Удалить или оставить для логирования |
| telegram_reports.py | 600 строк | Удалить (перейти в ODataClient) |

