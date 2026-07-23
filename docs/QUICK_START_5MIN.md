# ⚡ БЫСТРЫЙ СТАРТ - 5 минут

Этот файл поможет развернуть Google Apps Script за 5 минут.

---

## Шаг 1: Создать Google Apps Script проект (1 минута)

1. Перейди на [script.google.com](https://script.google.com)
2. Нажми **"+ New project"**
3. Назови: `UNF Reports`

---

## Шаг 2: Скопировать код (2 минуты)

В проекте Google Apps Script:

### 2.1. Удали весь код в `Code.gs`

Селектируй всё (Ctrl+A) → Delete

### 2.2. Скопируй из файла `GAS_COMPLETE_CONFIG.gs`

Открой файл `/Users/anna/claude-test/docs/GAS_COMPLETE_CONFIG.gs`
Скопируй **ВСЕ содержимое**
Вставь в Google Apps Script

Сохрани (Ctrl+S)

### 2.3. Создай файл `Code.gs`

В Google Apps Script нажми **+ (плюс)** рядом с файлами
Выбери **Script**
Назови `Code.gs`

Открой файл `/Users/anna/claude-test/docs/GAS_COMPLETE_MAIN.gs`
Скопируй **ВСЕ содержимое**
Вставь в новый файл `Code.gs`

Сохрани

---

## Шаг 3: Развернуть приложение (1.5 минуты)

1. Нажми кнопку **Deploy** (верхний правый угол)
2. Выбери **New deployment**
3. Тип развертывания: **Web app**
4. Заполни:
   - **Execute as:** твой email
   - **Who has access:** `Anyone`
5. Нажми **Deploy**
6. **Скопируй Deployment URL** (он вид: `https://script.google.com/macros/d/ABC123.../usercurrentUserOnly`)

---

## Шаг 4: Подготовить Google Sheets (30 секунд)

Открой свою таблицу: https://docs.google.com/spreadsheets/d/11XIw2dHpEF6EOxX9QlNFGbPwCjMJAZzYwbJpJtl_tTc/

Создай эти листы (если их ещё нет):
- `RAW_perfilev`
- `RAW_gubarev`
- `DASHBOARD`
- `LOG`
- `QUEUE`

На каждом листе добавь заголовки в строку 1:

**RAW_perfilev и RAW_gubarev:**
```
timestamp | base_id | report_type | period_start | period_end | metrics
```

**DASHBOARD:**
```
Показатель | Перфильев | Губарев | Итого
```

**LOG:**
```
timestamp | base_id | report_type | status | message
```

**QUEUE:**
```
request_id | report_type | period_start | period_end | timestamp | status | chat_id
```

---

## Шаг 5: Готово! ✅

Теперь ты можешь:

### Тестировать POST /ingest:

```bash
curl -X POST "https://script.google.com/macros/d/YOUR_DEPLOYMENT_ID/usercurrentUserOnly?path=ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "auth_token": "unf2tg_a7Kд9P2mQ8xL5fR3vT6wZ1nB4hJ0sC",
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
        "top_total": [{"name": "Должник", "amount": 50000}],
        "top_overdue": [{"name": "Должник", "amount": 20000, "days_overdue": 15}]
      }
    }
  }'
```

Если вернулось `{"status":"received"...}` — всё работает! ✅

### Тестировать GET /commands:

```bash
curl "https://script.google.com/macros/d/YOUR_DEPLOYMENT_ID/usercurrentUserOnly?path=commands&auth_token=unf2tg_a7Kд9P2mQ8xL5fR3vT6wZ1nB4hJ0sC&base_id=perfilev"
```

### Проверить статус:

```bash
curl "https://script.google.com/macros/d/YOUR_DEPLOYMENT_ID/usercurrentUserOnly?path=status&auth_token=unf2tg_a7Kд9P2mQ8xL5fR3vT6wZ1nB4hJ0sC"
```

---

## 🤖 Следующий шаг: Расширение 1С

Когда Deployment URL готов, я создам расширение 1С которое:
1. Будет отправлять данные на этот URL
2. Опрашивать очередь команд
3. Все станет работать автоматически

**Напиши мне Deployment URL и готов к загрузке расширения в 1С!** 🚀

---

## 🆘 Если не работает

1. Проверь что **ScriptApp одобрил доступ** (может быть окно с просьбой разрешить)
2. Проверь **View → Execution log** чтобы увидеть ошибки
3. Проверь что **листы созданы** и имеют правильные имена
4. Проверь что **auth_token совпадает** (`unf2tg_a7Kд9P2mQ8xL5fR3vT6wZ1nB4hJ0sC`)

Если всё ещё не работает — напиши ошибку из Execution log!
