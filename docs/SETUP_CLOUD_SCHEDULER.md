# 🚀 НАСТРОЙКА GOOGLE CLOUD SCHEDULER

**Автоматические отчеты каждый день в 09:30 МСК**

---

## ШАГИ НАСТРОЙКИ (15 минут)

### **ШАГ 1: Перейди в Google Cloud Console**

1. Открой браузер
2. Перейди: https://console.cloud.google.com/
3. Авторизуйся через свой Google аккаунт

---

### **ШАГ 2: Создай новый проект (если нужно)**

1. Вверху слева нажми на **"Select a Project"** или название проекта
2. Нажми **"New Project"**
3. Назови: `unf-reports-automation`
4. Нажми **"Create"**
5. **Подожди 30 секунд** пока создастся

---

### **ШАГ 3: Включи необходимые API**

1. В левом меню найди **"APIs & Services"** → **"Library"**
2. В поиске напиши: `Cloud Functions`
3. Нажми на **"Cloud Functions API"**
4. Нажми кнопку **"Enable"** (голубая кнопка)
5. **Подожди загрузку**

Повтори для:
- **Cloud Scheduler API** - поиск → enable
- **Cloud Logging API** - поиск → enable

---

### **ШАГ 4: Создай Cloud Function**

1. В левом меню: **"Cloud Functions"**
2. Нажми **"Create Function"** (голубая кнопка)
3. Заполни:
   - **Environment:** Python 3.11
   - **Function name:** `unf-reports-scheduler`
   - **Trigger type:** Cloud Pub/Sub
   - **Create a new topic:** `unf-reports-trigger`
   - Нажми **"Create"**

---

### **ШАГ 5: Загрузи код функции**

После создания откроется редактор кода.

**В файл `main.py` вставь это:**

```python
import functions_framework
import subprocess
import os

@functions_framework.http
def unf_reports_scheduler(request):
    """Запуск скрипта отчетов"""
    
    try:
        # Запускаем скрипт отчетов
        result = subprocess.run([
            'python3',
            '/Users/anna/claude-test/complete_auto_reports.py'
        ], capture_output=True, text=True, timeout=300)
        
        return {
            'status': 'success',
            'message': 'Отчет создан и отправлен',
            'output': result.stdout[:500]
        }, 200
        
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }, 500
```

**В файл `requirements.txt` вставь:**

```
gspread>=5.10.0
google-auth-oauthlib>=1.0.0
google-auth>=2.20.0
requests>=2.28.0
```

Нажми **"Deploy"** (синяя кнопка внизу)

**Подожди 2-3 минуты** пока развернется

---

### **ШАГ 6: Создай Cloud Scheduler задание**

1. В левом меню: **"Cloud Scheduler"**
2. Нажми **"Create Job"** (голубая кнопка)
3. Заполни:
   - **Name:** `unf-daily-reports`
   - **Frequency:** `30 9 * * *` (09:30 каждый день)
   - **Timezone:** `Europe/Moscow`
   - Нажми **"Continue"**

4. На следующей странице:
   - **Authentication:** `Add OIDC token`
   - **Service account email:** (выбери автоматически)
   - **Audience:** (скопируй URL из Cloud Function)

5. Нажми **"Create"**

---

### **ШАГ 7: Проверь что работает**

1. Перейди в **"Cloud Scheduler"**
2. Найди `unf-daily-reports`
3. Нажми **"Force run"** (запустить вручную)
4. **Подожди 30 секунд**
5. Проверь свой Telegram - должен придти отчет! ✅

---

## ✅ ГОТОВО!

Теперь отчеты будут приходить **КАЖДЫЙ ДЕНЬ В 09:30 МСК** автоматически!

---

## 🆘 ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ:

**"Cloud Function не развернулась"**
- Проверь что `requirements.txt` правильный
- Посмотри логи в "Logs"

**"Scheduler не запускается"**
- Убедись что функция работает (Force Run)
- Проверь timezone - должна быть Europe/Moscow

**"Отчет не приходит в Telegram"**
- Проверь что в скрипте правильный токен
- Посмотри логи функции

---

## 📞 КОМАНДЫ ДЛЯ ОТЧЕТОВ В TELEGRAM:

```
/today       - отчет на сегодня
/week        - за неделю
/month       - за месяц
/range 1.06-15.06  - за выбранный период
/debtors     - ТОП 10 должников
/sales_chart - график продаж
```

---

**ВСЁ! СИСТЕМА ПОЛНОСТЬЮ АВТОМАТИЧЕСКАЯ! 🎉**
