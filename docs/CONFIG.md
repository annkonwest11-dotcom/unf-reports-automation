# ⚙️ Конфигурация проекта

## Переменные окружения (.env)

### Telegram
```bash
# Bot Token (от @BotFather в Telegram)
BOT_TOKEN=8102009778:AAEsLCAZEpb7mDSO-6aRNhsUSB30g1n_meM

# Chat IDs
ANNA_CHAT_ID=796207056          # ID личного чата Анны
GROUP_CHAT_ID=-1001234567890    # ID рабочей группы
```

### Google Sheets
```bash
# Spreadsheet ID (из URL таблицы)
SPREADSHEET_ID=1KL3x5...         # https://docs.google.com/spreadsheets/d/{ID}

# Путь к credentials.json (для Google API)
CREDENTIALS_PATH=./credentials.json
```

### 1C OData (в Code.gs Properties)
```bash
ODATA_USER=api_bot                           # Логин
ODATA_PASS=slavaperfilev1414                 # Пароль
```

---

## Google Sheets конфигурация

### Листы (must-have)

| Лист | Назначение | Обязателен |
|------|-----------|-----------|
| **СМЕНЫ** | Отчёты о смене | ✅ |
| **СВОДНАЯ_ЗП** | Расчёты зарплаты | ✅ |
| **ИНТЕГРАЦИЯ** | Дебиторка из 1С | ✅ |
| **ВЗАИМОРАСЧЁТЫ** | Взаиморасчёты из 1С | ✅ |
| **DASHBOARD** | Сводный дашборд | ✅ |
| **НАСТРОЙКИ** | Текущий период и конфиги | ✅ |
| **LOG** | Логирование событий | ✅ |
| **QUEUE** | Очередь команд | ✅ |
| **RAW_perfilev** | Сырые данные Перфильева | ✅ |
| **RAW_gubarev** | Сырые данные Губарева | ✅ |

### Ячейки конфигурации

**В листе НАСТРОЙКИ:**
```
B2  = Период  (e.g., "июнь 2026")
B4  = Текущий период для архива (используется при /archive)
```

### Google Cloud конфигурация

1. **Создать Project в Google Cloud Console**
   ```
   https://console.cloud.google.com/
   ```

2. **Включить Sheets API**
   ```
   APIs & Services → Library → Google Sheets API → Enable
   ```

3. **Создать Service Account**
   ```
   APIs & Services → Credentials → Create Credentials → Service Account
   Скачать JSON key → сохранить как credentials.json
   ```

4. **Дать доступ**
   ```
   Добавить email service account в Google Sheets (Access)
   ```

---

## 1C OData конфигурация

### Базы данных

| Параметр | Значение | Назначение |
|----------|----------|-----------|
| **Base ID (Перфильев)** | 152757 | облачная 1С Перфильева |
| **Base ID (Губарев)** | 64904 | облачная 1С Губарева |
| **OData URL** | https://base.42clouds.com/unf/{id}/odata/standard.odata/ | API endpoint |
| **Auth** | Basic Auth (api_bot:password) | Аутентификация |

### Entity Names (для OData запросов)

```
Catalog_Контрагенты                           # Справочник контрагентов
AccumulationRegister_Продажи_RecordType       # Продажи
AccumulationRegister_РасчетыСПокупателями_RecordType  # Дебиторка
```

### Примеры OData запросов

```
# Получить все контрагентов
GET /Catalog_Контрагенты?$select=Ref_Key,Description

# Получить продажи за дату
GET /AccumulationRegister_Продажи_RecordType
  ?$filter=Period ge datetime'2026-06-25T00:00:00' and Period lt datetime'2026-06-26T00:00:00'

# Получить дебиторку (движения по расчётам)
GET /AccumulationRegister_РасчетыСПокупателями_RecordType
  ?$filter=Period le datetime'2026-06-25T23:59:59'
```

---

## Telegram Bot конфигурация

### Команды (в @BotFather)

```
/start - регистрация
/sync_1c - синхронизировать 1С
/today - отчёт за сегодня
/range - отчёт за период
/reports - отчёты обеих баз
/reports_perfilev - отчёты Перфильева
/reports_gubarev - отчёты Губарева
```

### Webhook (если использовать вместо polling)

```
Telegram → bot endpoint
https://yourdomain.com/telegram/webhook
```

---

## Расписание (job queue)

| Время | Функция | Описание |
|-------|---------|---------|
| **7:00 MSK** | auto_sync_1c() | Синхронизация 1С |
| **11:00 MSK** | auto_anna_shift() | Автоматическая смена Анне |
| **21:00 MSK** | check_missing_reports() | Проверка невыданных отчётов |

**Примечание:** Все времена в московском часовом поясе (MSK, UTC+3).

---

## Constants (в коде)

### bot.py
```python
CALLS_NORM = 20                    # Минимум звонков для менеджера
MSK = timezone(timedelta(hours=3)) # Moscow timezone
ANNA_USER_ID = int(ANNA_CHAT_ID)  # ID Анны
```

### Code.gs
```python
ODATA_BASES = {
  'perfilev': 'https://base.42clouds.com/unf/152757/odata/standard.odata/',
  'gubarev': 'https://base.42clouds.com/unf/64904/odata/standard.odata/',
}

BASE_TITLE = {
  'perfilev': 'Перфильев',
  'gubarev': 'Губарев'
}

OVERDUE_DAYS = 30  # Дни просрочки
```

---

## Локальные файлы конфигурации

### .gitignore
```
.env                    # Secrets
credentials.json        # Google credentials
employees.json          # User mapping
*.log                   # Логи
__pycache__/            # Python cache
venv/                   # Virtual environment
.DS_Store               # macOS
```

### .env.example (для документации)
```bash
BOT_TOKEN=your_token_here
SPREADSHEET_ID=your_id_here
ANNA_CHAT_ID=your_id_here
GROUP_CHAT_ID=your_id_here
CREDENTIALS_PATH=./credentials.json
```

---

## Инициализация проекта (First Time Setup)

### 1. Клонировать репо
```bash
git clone <repo>
cd claude-test
```

### 2. Создать virtual environment
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate     # Windows
```

### 3. Установить зависимости
```bash
pip install -r requirements.txt
```

### 4. Получить credentials
```bash
# От Анны получить:
# 1. .env файл (с токенами)
# 2. credentials.json (для Google API)
```

### 5. Инициализировать Google Sheets
```bash
python -c "from sheets import SheetsClient; SheetsClient(...).initSheets()"
```

### 6. Запустить бота
```bash
python bot.py
```

### 7. Проверить что всё работает
```
Отправить сообщение в групповой чат:
"смена 25 5 100"

Проверить что появилось в Google Sheets листе СМЕНЫ
```

---

## Проверка конфигурации

### Скрипт для проверки

```python
# test_config.py
import os
from dotenv import load_dotenv

load_dotenv()

print("✅ Конфигурация:")
print(f"BOT_TOKEN: {os.getenv('BOT_TOKEN')[:20]}...")
print(f"SPREADSHEET_ID: {os.getenv('SPREADSHEET_ID')}")
print(f"ANNA_CHAT_ID: {os.getenv('ANNA_CHAT_ID')}")
print(f"GROUP_CHAT_ID: {os.getenv('GROUP_CHAT_ID')}")
print(f"CREDENTIALS_PATH: {os.getenv('CREDENTIALS_PATH')}")

# Проверить что файлы существуют
import os
assert os.path.exists(os.getenv('CREDENTIALS_PATH')), "credentials.json не найден"
print("✅ Все файлы на месте")
```

---

## Обновление конфигурации

### Если изменить .env
```bash
# Перезагрузить бота
python bot.py
```

### Если изменить Google Sheets конфигурацию
```bash
# Обновить листы и запустить initSheets()
from sheets import SheetsClient
sheets = SheetsClient(...)
sheets.initSheets()
```

### Если изменить OData credentials (в Code.gs)
```javascript
// В Google Apps Script:
// Project Settings → Script Properties
// Обновить ODATA_USER и ODATA_PASS
```

---

## Беседа с Terraform/IaC (Future)

В будущем конфигурацию можно вынести в:
```hcl
# Terraform
variable "bot_token" {
  description = "Telegram Bot Token"
  type        = string
  sensitive   = true
}

variable "spreadsheet_id" {
  description = "Google Sheets ID"
  type        = string
}
```

---

## Резервная копия конфигурации

### Что нужно сохранить
```
.env                    ← Обязательно
credentials.json        ← Обязательно
employees.json          ← Важно (user mapping)
```

### Как сделать бэкап
```bash
# Сохранить в безопасном месте:
cp .env ~/backups/.env.backup
cp credentials.json ~/backups/credentials.json.backup
cp employees.json ~/backups/employees.json.backup
```

### Восстановление
```bash
cp ~/backups/.env.backup .env
cp ~/backups/credentials.json.backup credentials.json
```

---

## Troubleshooting

### Проблема: "Invalid BOT_TOKEN"
```
Решение: Проверить .env файл
         BOT_TOKEN должен начинаться на цифру и иметь двоеточие
```

### Проблема: "Access denied to Google Sheets"
```
Решение: Проверить что service account добавлен в документе
         Google Sheets → Share → добавить email service account
```

### Проблема: "OData 401 Unauthorized"
```
Решение: Проверить ODATA_USER и ODATA_PASS в Code.gs Properties
```

### Проблема: "Telegram API rate limit"
```
Решение: Уменьшить частоту запросов
         Добавить delay между запросами
```
