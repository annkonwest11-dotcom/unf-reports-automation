# 📖 Инструкция по развертыванию Google Apps Script Web App

## Шаг 1: Создать новый Google Apps Script проект

1. Перейди на [script.google.com](https://script.google.com)
2. Нажми **"+ Новый проект"**
3. Назови его: `UNF Reports Integration`

## Шаг 2: Скопировать код в проект

В Google Apps Script проекте:

1. **Создай файл `config.gs`**
   - Скопируй содержимое `gas_config.gs` из `/Users/anna/claude-test/docs/`
   - Вставь в Google Apps Script

2. **Создай файл `web_app.gs`** (или переименуй `Code.gs`)
   - Скопируй содержимое `gas_web_app.gs`
   - Вставь в Google Apps Script

3. **Создай файл `sheet_manager.gs`** (будет создан позже)
4. **Создай файл `data_aggregator.gs`** (будет создан позже)
5. **Создай файл `excel_generator.gs`** (будет создан позже)

## Шаг 3: Заполнить конфигурацию

### 3.1. Project Settings → Script Properties

Установи переменные окружения (в GAS это Script Properties):

1. Перейди **Project Settings** (⚙️ в левом меню)
2. Нажми **"Script properties"** внизу
3. Добавь три свойства:

| Property Name | Value |
|---|---|
| `TELEGRAM_TOKEN` | Твой Telegram Bot Token (скопируй из BotFather) |
| `AUTH_TOKEN` | Любой строка типа `secret_1c_integration_12345` |
| `SPREADSHEET_ID` | ID твоей Google Sheets таблицы |

**Как найти SPREADSHEET_ID:**
- Открой твою таблицу в Google Sheets
- URL выглядит так: `https://docs.google.com/spreadsheets/d/`**`1abc2def3ghi4jkl5...`**`/edit`
- Скопируй подчеркнутую часть

### 3.2. Обновить ALLOWED_CHATS в config.gs

В файле `config.gs`, строка ~20:

```javascript
const ALLOWED_CHATS = {
  'anna': 796207056,  // Замени на свой Telegram ID
  // Добавь остальные чаты
};
```

## Шаг 4: Развернуть как Web App

1. В Google Apps Script нажми **"Deploy"** (верхний правый угол)
2. Выбери **"New deployment"**
3. Тип развертывания: **"Web app"**
4. Заполни поля:
   - **Execute as:** `Your email address`
   - **Who has access:** `Anyone` (нужно для 1С)
5. Нажми **"Deploy"**
6. Скопируй **Deployment URL** вида: `https://script.google.com/macros/d/.../usercurrentUserOnly`

## Шаг 5: Создать структуру листов в Google Sheets

В своей Google Sheets таблице создай листы (если еще нет):

1. **RAW_perfilev** (для сырых данных базы А)
   - Колонки: timestamp | base_id | report_type | period_start | period_end | metrics

2. **RAW_gubarev** (для сырых данных базы Б)
   - Колонки: timestamp | base_id | report_type | period_start | period_end | metrics

3. **DASHBOARD** (заполняемый дашборд)
   - Сюда будут писаться значения по карте ячеек

4. **LOG** (журнал операций)
   - Колонки: timestamp | base_id | report_type | status | message

5. **QUEUE** (очередь команд для 1С)
   - Колонки: request_id | report_type | period_start | period_end | timestamp | status | chat_id

## Шаг 6: Протестировать Web App

### 6.1. Тест `/ingest` endpoint

Открой новую вкладку браузера и вызови:

```
https://script.google.com/macros/d/[YOUR_DEPLOYMENT_ID]/usercurrentUserOnly?path=test
```

Или используй curl из терминала:

```bash
curl -X POST "https://script.google.com/macros/d/[YOUR_DEPLOYMENT_ID]/usercurrentUserOnly?path=ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "auth_token": "secret_1c_integration_12345",
    "base_id": "perfilev",
    "report_type": "daily",
    "period_start": "2026-06-18",
    "period_end": "2026-06-18",
    "generated_at": "2026-06-18T09:30:00+03:00",
    "request_id": null,
    "metrics": {
      "settlements": { "they_owe_us": 100000, "we_owe": 50000 },
      "sales": {
        "total": 500000,
        "prev_total": 450000,
        "dynamics_abs": 50000,
        "dynamics_pct": 11.1,
        "avg_per_day": 25000,
        "forecast_turnover": 550000
      },
      "clients_activity": {
        "growing": [{"name": "Клиент А", "delta_abs": 50000, "delta_pct": 25}],
        "declining": [],
        "falling": []
      },
      "receivables": {
        "total": 100000,
        "overdue": 20000,
        "top_total": [{"name": "Должник 1", "amount": 50000}],
        "top_overdue": [{"name": "Должник 1", "amount": 20000, "days_overdue": 15}]
      }
    }
  }'
```

Если вернулся статус 200, значит endpoint работает! ✅

### 6.2. Тест `/pull-commands` endpoint

```bash
curl "https://script.google.com/macros/d/[YOUR_DEPLOYMENT_ID]/usercurrentUserOnly?path=commands&auth_token=secret_1c_integration_12345&base_id=perfilev"
```

## Шаг 7: Сохранить URL для 1С

URL для подстановки в расширение 1С:

```
https://script.google.com/macros/d/[YOUR_DEPLOYMENT_ID]/usercurrentUserOnly
```

Параметры при вызове:
- `path=ingest` — для отправки данных
- `path=commands&base_id=perfilev&auth_token=...` — для получения команд

---

## 📋 Чек-лист развертывания

- [ ] Google Apps Script проект создан
- [ ] Файлы скопированы (config.gs, web_app.gs)
- [ ] Script Properties заполнены (TELEGRAM_TOKEN, AUTH_TOKEN, SPREADSHEET_ID)
- [ ] ALLOWED_CHATS обновлены
- [ ] Web App развернута
- [ ] Deployment URL скопирован
- [ ] Листы в Google Sheets созданы (RAW_*, DASHBOARD, LOG, QUEUE)
- [ ] Тест `/ingest` прошел (200 OK)
- [ ] Тест `/pull-commands` прошел (200 OK)

---

## 🔐 Безопасность

**⚠️ ВАЖНО:**

1. **Никогда не пиши токены в коде** — используй Script Properties
2. **Deployment URL защищен доступом "Anyone"** — это нужно для 1С, но:
   - 1С обязательно отправляет правильный `auth_token`
   - GAS проверяет его перед обработкой
   - Без правильного токена запрос будет отклонен (401)

3. **Логи не должны содержать токены** — в коде используется `logError`, которая не пишет чувствительные данные

---

## 📞 Следующие шаги

1. Когда Web App будет готова — начнём писать расширение 1С
2. Расширение будет вызывать endpoints Web App в нужное время
3. Web App будет обрабатывать данные и отправлять отчеты в Telegram

---

## 🆘 Если что-то не работает

1. Проверь **Execution log** в Google Apps Script (View → Execution log)
2. Проверь что **auth_token совпадает** (в Script Properties и в запросе)
3. Проверь что **SPREADSHEET_ID правильный**
4. Проверь что **листы RAW_perfilev, RAW_gubarev существуют**

Напиши мне если есть вопросы! 👍
