# 🚀 GITHUB ACTIONS - ПОЛНАЯ НАСТРОЙКА

**Автоматические отчеты каждый день в 09:30 МСК**

---

## ✨ ПОЧЕМУ GITHUB ACTIONS?

- ✅ **Полностью бесплатно** - не требует карта
- ✅ **Облачный** - работает 24/7
- ✅ **Надежный** - 99.9% uptime
- ✅ **Простой** - 5 минут настройки
- ✅ **Встроенный** - не требует доп. сервисов

---

## 📋 ШАГИ НАСТРОЙКИ (5 минут)

### **ШАГ 1: Создай GitHub аккаунт (если нет)**

1. Открой: https://github.com
2. Нажми **"Sign up"**
3. Заполни данные
4. Подтверди email

---

### **ШАГ 2: Создай новый репозиторий**

1. Открой: https://github.com/new
2. Назови: `unf-reports-automation`
3. Описание: `Автоматические отчеты из 1С в Telegram`
4. Выбери: **Public** (или Private - как хочешь)
5. Нажми **"Create repository"**

---

### **ШАГ 3: Клонируй репозиторий на компьютер**

Открой терминал и выполни:

```bash
cd ~/Desktop
git clone https://github.com/ТВОЙ_ЮЗЕРНЕЙМ/unf-reports-automation.git
cd unf-reports-automation
```

---

### **ШАГ 4: Загрузи файлы проекта**

Скопируй эти файлы в репозиторий:

**Создай структуру папок:**

```
unf-reports-automation/
├── .github/
│   └── workflows/
│       └── daily_reports.yml
├── scripts/
│   └── generate_reports.py
└── README.md
```

**Файлы находятся здесь:**
- `.github/workflows/daily_reports.yml` ← есть готовый
- `scripts/generate_reports.py` ← есть готовый

Скопируй их в репозиторий!

---

### **ШАГ 5: Добавь файлы в Git**

```bash
cd ~/Desktop/unf-reports-automation

# Добавляем все файлы
git add .

# Коммитим
git commit -m "Add UNF reports automation"

# Пушим на GitHub
git push origin main
```

---

### **ШАГ 6: Добавь Secrets (переменные)**

Это самое важное! GitHub Actions нужны токены для 1С и Telegram.

1. Открой репозиторий на GitHub
2. Нажми **Settings** (в меню репозитория)
3. В левом меню: **Secrets and variables** → **Actions**
4. Нажми **"New repository secret"**

**Добавь эти секреты один за другим:**

#### Секрет 1: TELEGRAM_TOKEN

- **Name:** `TELEGRAM_TOKEN`
- **Value:** `8602166476:AAEo3ySMNmF38lyH0yppcW7CKejzXK_w7cY`
- Нажми **"Add secret"**

#### Секрет 2: TELEGRAM_CHAT_ID

- **Name:** `TELEGRAM_CHAT_ID`
- **Value:** `796207056`
- Нажми **"Add secret"**

#### Секрет 3: SHEET_ID

- **Name:** `SHEET_ID`
- **Value:** `1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo`
- Нажми **"Add secret"**

#### Секрет 4: GOOGLE_CREDENTIALS

- **Name:** `GOOGLE_CREDENTIALS`
- **Value:** Содержимое файла `credentials.json`
  
  **Как получить:**
  
  ```bash
  cat /Users/anna/claude-test/credentials.json
  ```
  
  Скопируй весь текст (весь JSON) и вставь как значение

- Нажми **"Add secret"**

---

### **ШАГ 7: Проверь что workflow активен**

1. Открой репозиторий на GitHub
2. Нажми **Actions** (в меню)
3. Нажми **"UNF Daily Reports"**
4. Нажми **"Run workflow"** (зеленая кнопка)
5. **Подожди 30 секунд**
6. Проверь Telegram - должен придти первый отчет! ✅

---

### **ШАГ 8: Проверь расписание**

Workflow будет запускаться:
- **Каждый день в 09:30 МСК**
- Или вручную через GitHub Actions UI

Проверить расписание можно в файле:
`.github/workflows/daily_reports.yml`

Строка: `cron: '30 6 * * *'` (это 09:30 МСК)

---

## ✅ ГОТОВО!

Теперь отчеты будут приходить **АВТОМАТИЧЕСКИ каждый день в 09:30 МСК**!

🎉 Всё работает облачно, бесплатно и надежно!

---

## 📊 ЧТО ПРОИСХОДИТ:

1. **GitHub Actions** проверяет расписание
2. **В 09:30 МСК** запускает workflow
3. Workflow запускает Python скрипт
4. Скрипт:
   - Подключается к облачной 1С через REST API
   - Получает данные из обеих баз
   - Форматирует красивый отчет
   - Отправляет в Telegram
   - Логирует в Google Sheets

---

## 🆘 ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ:

**"Workflow не запускается"**
- Проверь что файл `.github/workflows/daily_reports.yml` загружен
- Посмотри в GitHub Actions → Workflow runs

**"Отчет не приходит в Telegram"**
- Проверь что все Secrets добавлены правильно
- Посмотри логи в GitHub Actions → Run workflow

**"Ошибка в Python коде"**
- Посмотри Workflow logs
- Проверь что credentials.json валидный JSON

---

## 📞 КОМАНДЫ TELEGRAM:

```
/today        - отчет на сегодня
/week         - за неделю
/month        - за месяц
/debtors      - ТОП 10 должников
/sales_chart  - график продаж
```

---

**🚀 СИСТЕМА ПОЛНОСТЬЮ ГОТОВА!**
