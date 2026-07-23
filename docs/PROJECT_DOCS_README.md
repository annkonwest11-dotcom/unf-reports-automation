# 📚 Документация проекта

## 🎯 Проект: Система управления ботом и отчётами

**Статус:** В процессе рефакторинга  
**Дата создания:** Июнь 2026  
**Владелец:** Анна (РОП)  

---

## 📋 Содержание документации

### 📖 Начните отсюда:
1. **[OVERVIEW.md](./OVERVIEW.md)** — Что это и для кого? (5 мин чтения)
2. **[CURRENT_STATE.md](./CURRENT_STATE.md)** — Что работает и что нет? (10 мин)

### 🔧 Технические детали:
3. **[FILES.md](./FILES.md)** — Описание каждого файла в проекте
4. **[COMPONENTS.md](./COMPONENTS.md)** — Описание каждого компонента
5. **[TECH_STACK.md](./TECH_STACK.md)** — Python, Google Sheets, Telegram, OData

### 🏗️ Архитектура и план:
6. **[ARCHITECTURE.md](./ARCHITECTURE.md)** — Предложенная архитектура (как улучшить)
7. **[ISSUES.md](./ISSUES.md)** — 10 известных проблем и TODOs

### ⚙️ Конфигурация:
8. **[CONFIG.md](./CONFIG.md)** — .env, Google Sheets, OData, расписание
9. **[PAYROLL_INFO.md](./PAYROLL_INFO.md)** — 💰 Сотрудники, ставки, схема зарплаты

---

## 🚀 Быстрый старт

### Запустить бота:
```bash
python bot.py
```

### Синхронизировать 1С:
```bash
python sync_42clouds_v2.py
```

### Отправить отчёт в Telegram:
```bash
python telegram_reports.py perfilev
```

---

## 🎓 Структура проекта

```
claude-test/
├── PROJECT_DOCS/         ← Вы находитесь здесь
│   ├── README.md         ← Главный файл
│   ├── OVERVIEW.md       ← Описание проекта
│   ├── CURRENT_STATE.md  ← Что работает, что не работает
│   ├── ARCHITECTURE.md   ← Как переделать
│   ├── COMPONENTS.md     ← Описание каждого компонента
│   ├── FILES.md          ← Список файлов
│   ├── ISSUES.md         ← Проблемы
│   ├── TECH_STACK.md     ← Технологии
│   └── CONFIG.md         ← Конфигурация
│
├── bot.py                ← Основной бот (смены + команды)
├── parser.py             ← Парсинг отчётов о смене
├── sheets.py             ← Работа с Google Sheets
├── sync_42clouds_v2.py   ← Синхронизация 1С
├── telegram_reports.py   ← Отчёты из OData (ДУБЛИРУЕТ Code.gs)
│
├── handlers/             ← БУДУЩИЕ обработчики
├── clients/              ← БУДУЩИЕ клиенты
│
└── Code.gs               ← Google Apps Script (дублирует telegram_reports.py)
```

---

## 💬 Основные сущности проекта

### 1. Отчёт о смене (Shift Report)
- **Что:** Сотрудник пишет в чат смену (день, часы, сумма)
- **Куда:** Сохраняется в Google Sheets лист СМЕНЫ
- **Пример:** `смена 25 5 100 рест.1тел:2 250`

### 2. Отчёты из 1С (OData Reports)
- **Что:** Продажи, дебиторка, взаиморасчёты из облачной 1С
- **Откуда:** OData REST API (42clouds.com)
- **Куда:** Google Sheets (лист DASHBOARD) + Telegram
- **Базы:** Перфильев (152757) и Губарев (64904)

### 3. Синхронизация 1С (1C Sync)
- **Что:** Загрузить все дебиторов и взаиморасчёты из 1С
- **Куда:** Google Sheets листы ИНТЕГРАЦИЯ и ВЗАИМОРАСЧЁТЫ
- **Команда:** `/sync_1c` (только Анна)

### 4. Архивирование месяца (Archive)
- **Что:** Скопировать рабочие листы с суффиксом _АРХИВ
- **Очистить:** Листы СМЕНЫ и СВОДНАЯ_ЗП
- **Команда:** `/archive` или `архив` (только Анна)

---

## 🔗 Внешние сервисы

| Сервис | Что | Как |
|--------|-----|-----|
| **Google Sheets** | Хранилище данных | API с credentials.json |
| **Telegram** | Отправка отчётов и уведомлений | Bot API (BOT_TOKEN) |
| **1С OData** | Облачная база (42clouds) | Basic Auth |
| **GitHub** | Версионирование кода | Git |

---

## 📞 Контакты

- **Telegram:** Личка Анны
- **Таблица:** https://docs.google.com/spreadsheets/d/...
- **1С:** https://base.42clouds.com/unf/{base_id}

---

## 📝 История

- **2026-06-18:** Добавлена защита от повторной обработки Telegram апдейтов
- **2026-06-17:** Обновить получение реальных данных из 1С API
- **2026-06-xx:** Создание UNF Reports Automation (готовая система)

---

---

## 📊 Индекс файлов

```
PROJECT_DOCS/
├── README.md              ← ВЫ ЗДЕСЬ (главный файл)
│
├── 📖 ОСНОВНОЕ (начните отсюда)
│   ├── OVERVIEW.md        ← Что это и зачем?
│   └── CURRENT_STATE.md   ← Состояние: что работает / что нет
│
├── 🔍 АНАЛИЗ КОДА
│   ├── FILES.md           ← Каждый файл: зачем, что делает, проблемы
│   ├── COMPONENTS.md      ← Каждый компонент в деталях
│   └── TECH_STACK.md      ← Python, Google Sheets, Telegram, OData
│
├── 🏗️ АРХИТЕКТУРА
│   ├── ARCHITECTURE.md    ← Как переделать (рефакторинг)
│   └── ISSUES.md          ← 10 проблем и план исправлений
│
└── ⚙️ КОНФИГУРАЦИЯ
    └── CONFIG.md          ← .env, Google Sheets, OData, расписание
```

---

## 🎯 Навигация по задачам

### Я новый разработчик — что мне читать?
1. [OVERVIEW.md](./OVERVIEW.md) (что это?)
2. [CURRENT_STATE.md](./CURRENT_STATE.md) (что работает?)
3. [FILES.md](./FILES.md) (структура проекта)
4. [CONFIG.md](./CONFIG.md) (как запустить)

### Я want to fix a bug — что мне нужно?
1. [ISSUES.md](./ISSUES.md) (что ломается?)
2. [FILES.md](./FILES.md) (где это находится?)
3. [COMPONENTS.md](./COMPONENTS.md) (как это работает?)

### Я want to add a feature — с чего начать?
1. [ARCHITECTURE.md](./ARCHITECTURE.md) (как должно быть)
2. [COMPONENTS.md](./COMPONENTS.md) (какие компоненты трогать)
3. [FILES.md](./FILES.md) (где это находится)

### Я want to deploy — что мне нужно?
1. [CONFIG.md](./CONFIG.md) (переменные окружения)
2. [TECH_STACK.md](./TECH_STACK.md) (зависимости)
3. [CURRENT_STATE.md](./CURRENT_STATE.md) (что работает)

---

## 📈 Статистика проекта

| Метрика | Значение |
|---------|----------|
| **Основной файл** | bot.py (850 строк) |
| **Главный компонент** | Telegram Bot + Google Sheets Integration |
| **Язык** | Python 3.12 |
| **외部 сервисы** | Telegram, Google Sheets, OData (1С) |
| **Проблемы** | 10 (3 critical, 4 important, 3 low) |
| **Рефакторинг** | ~40% готов (архитектура определена) |
| **Документация** | 9 файлов (этот пакет) |

---

## ✅ Checklist: что прочитать перед работой

- [ ] [OVERVIEW.md](./OVERVIEW.md) — понимаю что это за проект
- [ ] [CURRENT_STATE.md](./CURRENT_STATE.md) — знаю что работает и что нет
- [ ] [FILES.md](./FILES.md) — ориентируюсь в файлах
- [ ] [CONFIG.md](./CONFIG.md) — могу запустить локально
- [ ] [COMPONENTS.md](./COMPONENTS.md) — понимаю архитектуру
- [ ] [ISSUES.md](./ISSUES.md) — знаю о проблемах
- [ ] [ARCHITECTURE.md](./ARCHITECTURE.md) — знаю как улучшить

---

**Последнее обновление:** 2026-06-25  
**Общее количество документов:** 9 файлов, ~70KB текста
