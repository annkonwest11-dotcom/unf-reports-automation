# 🛠️ Технологический стек

## Основные технологии

### Backend

| Технология | Версия | Назначение | Статус |
|-----------|--------|-----------|--------|
| **Python** | 3.12 | Основной язык программирования | ✅ |
| **python-telegram-bot** | 20.x | Работа с Telegram Bot API | ✅ |
| **google-api-python-client** | latest | Google Sheets API | ✅ |
| **google-auth-oauthlib** | latest | OAuth2 для Google | ✅ |
| **requests** | 2.x | HTTP запросы (OData) | ✅ |
| **python-dotenv** | latest | Управление переменными окружения | ✅ |

### Frontend

| Технология | Версия | Назначение | Статус |
|-----------|--------|-----------|--------|
| **Telegram** | Bot API | User Interface | ✅ |
| **Google Sheets** | API v4 | Хранилище + интерфейс | ✅ |

### DevOps

| Технология | Версия | Назначение | Статус |
|-----------|--------|-----------|--------|
| **Git** | latest | Версионирование кода | ✅ |
| **GitHub** | - | Repository | ✅ |
| **Google Apps Script** | latest | Дополнительная автоматизация | ⚠️ Дублирует Python |

---

## Интеграции

### Telegram Bot API
```
Endpoint: https://api.telegram.org/bot{TOKEN}/
Methods:
  - getUpdates() — получение обновлений
  - sendMessage() — отправка сообщений
  - setWebhook() — установка webhook (для GAS)
```

### Google Sheets API
```
Endpoint: https://sheets.googleapis.com/v4/
Methods:
  - spreadsheets.values.get() — чтение
  - spreadsheets.values.update() — запись
  - spreadsheets.values.append() — добавление
  - spreadsheets.batchUpdate() —批операции
```

### OData API (42clouds)
```
Endpoint: https://base.42clouds.com/unf/{base_id}/odata/standard.odata/
Auth: Basic Auth
Methods:
  - GET /Catalog_Контрагенты
  - GET /AccumulationRegister_Продажи_RecordType
  - GET /AccumulationRegister_РасчетыСПокупателями_RecordType
```

---

## Зависимости (requirements.txt)

### Основные
```
python-telegram-bot==20.x       # Telegram Bot API
google-auth-oauthlib==1.x       # Google OAuth
google-auth-httplib2==0.x       # Google HTTP
google-api-python-client==2.x   # Google API client
requests==2.x                   # HTTP requests
python-dotenv==1.x              # Environment variables
```

### Развёртывание
```
pip install -r requirements.txt
```

---

## Окружение

### Python
```bash
python --version        # Должен быть 3.10+
pip --version          # Менеджер пакетов
```

### Переменные окружения (.env)
```
BOT_TOKEN=...                   # Telegram Bot Token
SPREADSHEET_ID=...              # Google Sheet ID
ANNA_CHAT_ID=...                # Telegram Chat ID
GROUP_CHAT_ID=...               # Telegram Group ID
CREDENTIALS_PATH=./credentials.json
```

### Google Credentials
```
credentials.json                # OAuth2 credentials (из Google Cloud Console)
```

---

## Хранилище данных

### Google Sheets (основное)
```
Формат: Google Sheets таблица
Листы:
  - СМЕНЫ (основные данные)
  - СВОДНАЯ_ЗП (расчёты)
  - ИНТЕГРАЦИЯ (дебиторка из 1С)
  - ВЗАИМОРАСЧЁТЫ (из 1С)
  - DASHBOARD (сводка)
  - LOG (логирование)
  - QUEUE (очередь команд)
  - RAW_* (сырые данные)
```

### Локальные файлы
```
.env                    # Secrets
employees.json          # User mapping
last_update_id.txt      # Offset для восстановления
credentials.json        # Google API credentials
```

---

## Развёртывание

### 1. Локальное (Development)
```bash
git clone ...
cd claude-test
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
python bot.py
```

### 2. Google Apps Script (Alternative)
```
clasp login
clasp pull
clasp push
clasp deploy
```

### 3. Docker (Future)
```dockerfile
FROM python:3.12
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

---

## Версионирование

### Python пакеты
```
python-telegram-bot >= 20.0, < 21.0
google-api-python-client >= 2.80
```

### API версии
```
Telegram Bot API: latest (автоматически)
Google Sheets API: v4 (фиксированная)
OData: standard.odata (от 42clouds)
```

---

## Мониторинг и Логирование

### Текущее
```
- Логи в консоль (logging module)
- Логи в файлы (bot.log, bot_session.log)
- Логи в Google Sheets (LOG лист)
```

### Будущее (рекомендуется)
```
- Централизованное логирование (LogClient)
- Структурированные логи (JSON)
- Интеграция с сервисом логирования (e.g., Sentry, Datadog)
```

---

## Производительность

### Текущие метрики
```
- Парсинг смены:        < 100ms
- Запись в Sheets:      ~500ms
- Загрузка OData:        ~2-5s
- Полная синхронизация: ~30s
```

### Лимиты
```
- Telegram API: ~30 запросов в секунду
- Google Sheets API: ~100 запросов в минуту
- OData: ~1000 записей за запрос (пагинация)
```

---

## Безопасность

### Аутентификация
```
- Telegram: BOT_TOKEN (в переменных окружения)
- Google: OAuth2 (credentials.json)
- OData: Basic Auth (api_bot:password)
```

### Авторизация
```
- Только Анна (ANNA_CHAT_ID) может делать критичные операции
- Проверка user_id перед любой операцией
- Проверка chat_id (только определённые чаты)
```

### Секреты
```
.env              → в .gitignore
credentials.json  → в .gitignore
employees.json    → в .gitignore (может быть опция)
```

---

## Альтернативные технологии (для будущего)

### Вместо polling → webhook
```
Текущее: bot.run_polling()
Будущее: FastAPI + webhook
```

### Вместо Google Sheets → Database
```
Текущее: Google Sheets как БД
Будущее: PostgreSQL / MongoDB
```

### Вместо GAS → Python
```
Текущее: Code.gs (1000 строк)
Будущее: Миграция на Python
```

### Вместо sync_42clouds_v2 → Scheduler
```
Текущее: Job Queue в bot.py
Будущее: Celery + Redis, или APScheduler
```

---

## Чек-лист для нового разработчика

```
[ ] Установить Python 3.12+
[ ] Клонировать репо
[ ] Создать virtual environment
[ ] pip install -r requirements.txt
[ ] Получить .env (от Анны)
[ ] Получить credentials.json (от Анны)
[ ] python bot.py
[ ] Проверить логи
[ ] Отправить тестовую смену в чат
[ ] Проверить что появилась в Google Sheets
[ ] Готово!
```

---

## Полезные команды

### Запуск
```bash
python bot.py                          # Запустить бота
python telegram_reports.py perfilev   # Отправить отчёты
python sync_42clouds_v2.py            # Синхронизировать 1С
```

### Отладка
```bash
python -m pdb bot.py                  # Debugger
python -c "import bot; bot.main()"   # Тестирование
```

### Google Apps Script
```bash
clasp login                            # Авторизация
clasp pull                             # Загрузить с Google
clasp push                             # Загрузить в Google
clasp deploy                           # Развернуть
```

### Управление виртуальным окружением
```bash
python -m venv venv                   # Создать
source venv/bin/activate              # Активировать (Linux/Mac)
venv\Scripts\activate                 # Активировать (Windows)
pip freeze > requirements.txt          # Сохранить зависимости
pip install -r requirements.txt        # Установить зависимости
```

---

## Ссылки

- **Telegram Bot API:** https://core.telegram.org/bots/api
- **Google Sheets API:** https://developers.google.com/sheets/api
- **python-telegram-bot:** https://python-telegram-bot.readthedocs.io/
- **Google Auth:** https://developers.google.com/identity/protocols/oauth2
- **42clouds OData:** https://base.42clouds.com/ (документация внутри)
