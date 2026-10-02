#!/usr/bin/env python3
"""Борд РОПа: KPI отдела продаж + новые продажи по менеджерам + воронка дегустаций.

Собирает данные из трёх источников и рендерит статическую страницу
`templates/rop_board.html` (данные подставляются в `const DATA = {...}`):

  1С (OData, все живые базы) — оборот месяца (регистр Продажи) и оборот
      клиентов в разрезе менеджера поиска (регистр РасчетыСПокупателями).
  Касса GREENCH            — поступления (оплаты) месяца.
  Google Sheets            — новые продажи по менеджерам (таблица «ОТЧЕТЫ ПО
      ПРОДАЖАМ», лист текущего периода, ведётся вручную — решение Анны
      28.09.2026) и планы из листа НАСТРОЙКИ зарплатной таблицы.
  Битрикс24                — воронка «Дегустации» (CATEGORY_ID=0): отправленные
      дегустации, сделки в работе, стадии и комментарии менеджеров.

Статус сделки = стадия воронки, уточнённая разбором последнего комментария
через LLM (OpenRouter; решение Анны 28.09.2026). Ответ модели кешируется по
хешу комментария в rop_board_cache.json — повторные прогоны почти бесплатны.
Без ключа/при ошибке модели статус остаётся по стадии, борд не падает.

Запуск:
    python rop_board.py --out /data/board/index.html      # собрать страницу
    python rop_board.py --json out/board.json --no-llm    # только данные, без LLM
    python rop_board.py --print                           # сводка в консоль
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import gspread
import requests
from google.oauth2.service_account import Credentials

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sync_odata as so  # noqa: E402  (оборот 1С, матчинг имён контрагентов)

logger = logging.getLogger("rop_board")

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "templates", "rop_board.html")
CACHE_PATH = os.path.join(HERE, "rop_board_cache.json")
CREDENTIALS_PATH = os.path.join(HERE, "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Таблица «ОТЧЕТЫ ПО ПРОДАЖАМ» — новые продажи, помесячные листы (ручной ввод)
SALES_SPREADSHEET = "1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4"
CATEGORY_TASTINGS = 0          # воронка «Дегустации»
PLAN_SEARCH_DEFAULT = 210000   # план новых продаж менеджера поиска (НАСТРОЙКИ!C8)
STALE_DAYS = 7                 # сделка без движения столько дней — флаг РОПу
SALES_SHEET_WINDOW = 6         # сколько последних листов «ОТЧЕТОВ» считаем текущими

MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
             "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]

# Стадии воронки «Дегустации» → базовый статус борда.
# push — дожать до заказа, meet — встреча, call — связь/обратная связь,
# fill — заполнить карточку в CRM, obj — возражение, out — провал/перевод,
# won — закрепили сотрудничество.
STAGE_STATUS = {
    "NEW": "call",             # Новая дегустация
    "UC_ZX1F5K": "fill",       # РАЗОБРАТЬ!!!
    "UC_4B3C08": "call",       # Обратная связь получена
    "PREPARATION": "push",     # Прайс и создание договора
    "UC_0LGKWV": "push",       # Первые заказы/контроль
    "WON": "won",              # Закрепили сотрудничество/работаем
    "LOSE": "out",             # Другое
    "UC_V53410": "out",        # Перестали работать
    "1": "obj",                # Цена
    "2": "obj",                # Ассортимент
    "3": "obj",                # Качество
    "4": "out",                # Передумали вводить
    "5": "out",                # Не вышли на ЛПР
    "6": "out",                # Связаться позже
}
CLOSED_STAGES = {"WON", "LOSE", "UC_V53410", "1", "2", "3", "4", "5", "6"}
STAGE_NAMES_FALLBACK = {
    "NEW": "Новая дегустация", "UC_ZX1F5K": "РАЗОБРАТЬ!!!",
    "UC_4B3C08": "Обратная связь получена", "PREPARATION": "Прайс и создание договора",
    "UC_0LGKWV": "Первые заказы/контроль", "WON": "Закрепили сотрудничество/работаем",
    "LOSE": "Другое", "UC_V53410": "Перестали работать", "1": "Цена",
    "2": "Ассортимент", "3": "Качество", "4": "Передумали вводить",
    "5": "Не вышли на ЛПР", "6": "Связаться позже",
}
STATUS_TITLES = {
    "push": "Дожать до заказа",
    "meet": "Встреча",
    "call": "Связь / ОС",
    "fill": "Заполнить CRM",
    "obj": "Возражение",
    "out": "Провал / перевод",
    "won": "Работаем",
    "none": "Без статуса",
}


# ─── общее ────────────────────────────────────────────────────────────────────

def load_env():
    """Читает .env рядом со скриптом (как остальные модули проекта)."""
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def num(s):
    """Число из ячейки Google Sheets: «30 250,00» → 30250.0, «-»/«» → 0."""
    if isinstance(s, (int, float)):
        return float(s)
    s = (s or "").replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    s = s.replace("₽", "")
    if s in ("", "-", "—", "–"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def first_name(full):
    """«Дарья Вольнова» → «Дарья» (в KPI-таблице колонки названы по имени)."""
    return (full or "").strip().split()[0] if (full or "").strip() else ""


def month_bounds(today):
    start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = calendar.monthrange(today.year, today.month)[1]
    return start, days


def open_sheets():
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


# ─── Битрикс24 ────────────────────────────────────────────────────────────────

def bitrix(method, params=None):
    webhook = os.environ.get("BITRIX_WEBHOOK", "").rstrip("/")
    if not webhook:
        raise RuntimeError("BITRIX_WEBHOOK не задан в .env")
    r = requests.post(f"{webhook}/{method}.json", json=params or {}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Битрикс {method}: {data.get('error_description') or data['error']}")
    return data


def bitrix_list(method, params):
    """Постраничный обход списочного метода."""
    out, start = [], 0
    while True:
        data = bitrix(method, dict(params, start=start))
        out += data.get("result", [])
        if "next" not in data:
            return out
        start = data["next"]


def fetch_deals():
    """Все сделки воронки «Дегустации» с полями, нужными борду."""
    return bitrix_list("crm.deal.list", {
        "filter": {"CATEGORY_ID": CATEGORY_TASTINGS},
        "select": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "DATE_CREATE",
                   "DATE_MODIFY", "COMMENTS", "OPPORTUNITY"],
        "order": {"DATE_MODIFY": "DESC"},
    })


def fetch_stage_names():
    """{STATUS_ID: название} стадий сделок — чтобы борд не врал, если их переименуют."""
    try:
        res = bitrix("crm.status.list",
                     {"filter": {"ENTITY_ID": "DEAL_STAGE"}}).get("result") or []
        return {x["STATUS_ID"]: x["NAME"] for x in res}
    except Exception as exc:
        logger.warning("Названия стадий не прочитаны: %s", exc)
        return {}


def fetch_users(ids):
    """{user_id: «Имя Фамилия»} одним запросом на пользователя (их единицы)."""
    names = {}
    for uid in ids:
        try:
            res = bitrix("user.get", {"ID": uid}).get("result") or []
        except Exception:
            logger.warning("Битрикс: не удалось прочитать пользователя %s", uid)
            res = []
        full = ""
        if res:
            u = res[0]
            full = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
        names[str(uid)] = full or "без менеджера"
    return names


_BB = re.compile(r"\[/?[^\]]{1,40}\]")
_SPACES = re.compile(r"[ \t\xa0]+")


def clean_bb(text):
    """Комментарий Битрикса (BB-код) → строки обычного текста."""
    t = _BB.sub("\n", text or "")
    t = t.replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    lines = [_SPACES.sub(" ", ln).strip() for ln in t.split("\n")]
    return [ln for ln in lines if ln]


def last_note(comments, limit=600, keep=3):
    """Хвост комментария: последние записи, которые менеджер дописал внизу.

    Одной строки мало — менеджеры пишут историю абзацами («28.09 не дозвон»,
    «26.09 шеф просил прайс»), и по последней строке модель ошибочно решала,
    что информации нет. Берём последние `keep` строк, самая свежая — в конце.
    """
    lines = clean_bb(comments)
    if not lines:
        return ""
    return " · ".join(lines[-keep:])[-limit:]


_DATE_IN_TEXT = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b")


def note_date(text, today):
    """Дата из текста комментария («28.09-созвонилась…») — чем свежее, тем лучше."""
    best = None
    for m in _DATE_IN_TEXT.finditer(text or ""):
        day, month = int(m.group(1)), int(m.group(2))
        year_raw = m.group(3)
        if not (1 <= day <= 31 and 1 <= month <= 12):
            continue
        year = today.year
        if year_raw:
            year = int(year_raw) + (2000 if len(year_raw) == 2 else 0)
        try:
            d = datetime(year, month, day)
        except ValueError:
            continue
        if d > today + timedelta(days=1):
            continue
        if best is None or d > best:
            best = d
    return best


# Тестовые карточки, которыми пользуются при настройке CRM, в борд не берём
TEST_TITLE = re.compile(r"\b(?:тест(?:ов\w*)?|test)\b", re.I)


def norm_title(title):
    """Нормализованное имя карточки — для поиска дублей в воронке."""
    t = (title or "").lower()
    t = re.sub(r"[^a-zа-яё0-9 ]+", " ", t)
    t = re.sub(r"\b(ооо|ип|кафе|ресторан|бар|бистро|the|group)\b", " ", t)
    return " ".join(sorted(set(t.split())))


# ─── LLM: уточнение статуса по комментарию ────────────────────────────────────

SYSTEM_PROMPT = (
    "Ты помощник руководителя отдела продаж компании GREENCH (поставки зелени и "
    "микрозелени ресторанам). На вход — карточки сделок из воронки «Дегустации» "
    "Битрикс24: стадия и последняя запись комментария менеджера. Для каждой "
    "карточки верни статус и одну короткую фразу — что РОПу требовать от менеджера.\n"
    "Статусы: push (клиент готов, дожать до заказа), meet (нужна встреча или "
    "повторная дегустация), call (нужен звонок, ждём обратную связь), "
    "fill (в карточке нет информации, менеджеру заполнить CRM), "
    "obj (возражение: цена, ассортимент, качество, минималка), "
    "out (провал, отказ, перевод на другого менеджера), won (уже работаем).\n"
    "Фраза action: до 90 символов, по-русски, без кавычек, повелительно или "
    "назывным оборотом («дожать заказ на следующую неделю», «взять ОС у шефа»). "
    "Опирайся только на текст комментария, ничего не придумывай. Статус fill и "
    "фразу «нет информации в карточке» ставь ТОЛЬКО когда комментарий пустой; "
    "если текст есть — вытащи из него следующий шаг, даже когда он скупой "
    "(«не дозвон» → «дозвониться до ЛПР»).\n"
    'Ответ — только JSON: {"1234": {"status": "push", "action": "…"}, …}'
)


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        logger.warning("Не смог записать кеш %s", CACHE_PATH)


def llm_classify(items, model=None):
    """items: [{id, stage, note}] → {id: {status, action}}. Ошибка не критична."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key or not items:
        if not key:
            logger.warning("OPENROUTER_API_KEY нет — статусы только по стадиям")
        return {}
    model = model or os.environ.get("BOARD_LLM_MODEL", "anthropic/claude-haiku-4.5")
    base = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
    out = {}
    for i in range(0, len(items), 20):
        chunk = items[i:i + 20]
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(chunk, ensure_ascii=False)},
            ],
        }
        try:
            r = requests.post(f"{base}/chat/completions", timeout=120,
                              headers={"Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json"},
                              json=payload)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", text, re.S)
            parsed = json.loads(m.group(0) if m else text)
            for k, v in parsed.items():
                status = str(v.get("status", "")).strip()
                action = str(v.get("action", "")).strip()
                if status in STATUS_TITLES:
                    out[str(k)] = {"status": status, "action": action[:120]}
        except Exception as exc:
            logger.warning("LLM-разбор партии %d не удался: %s", i // 20 + 1, exc)
    logger.info("LLM разобрал %d карточек из %d", len(out), len(items))
    return out


# ─── Google Sheets: новые продажи и планы ─────────────────────────────────────

def pick_sales_sheet(spreadsheet, today):
    """Лист «ОТЧЕТОВ ПО ПРОДАЖАМ» за текущий период.

    Листы Анна называет «август-сентябрь», «июль-август» и добавляет в конец
    книги. ★ГРАБЛИ (пойманы 02.10.2026): названия месяцев повторяются каждый год —
    в книге есть прошлогодние «конец сентября-октярь» и «Октябрь (конец)-Ноябрь»,
    и поиск «любой лист с текущим месяцем» выдал прошлогодний, а борд показал его
    цифры как октябрь 2026. Поэтому ищем только среди последних листов книги; если
    среди них листа текущего месяца нет — его ещё не создали, и это видно в борде.
    """
    month = MONTHS_RU[today.month - 1]
    sheets = [ws for ws in spreadsheet.worksheets() if "копия" not in ws.title.lower()]
    if not sheets:
        raise RuntimeError("В таблице «ОТЧЕТЫ ПО ПРОДАЖАМ» нет листов")
    recent = sheets[-SALES_SHEET_WINDOW:]
    named = [ws for ws in recent if month in ws.title.lower()]
    if named:
        return named[-1], True
    return sheets[-1], False


def manager_sales(spreadsheet, today):
    """{имя: сумма новых продаж} с листа текущего периода + служебная информация.

    Строка = клиент (непустая колонка A), суммы — в колонке «своего» менеджера
    (заголовки в строке 1 начиная с F). Нижние итоговые блоки листа колонку A
    не заполняют, поэтому в сумму не попадают.
    """
    ws, exact = pick_sales_sheet(spreadsheet, today)
    values = ws.get_all_values()
    if not values:
        return {}, {"sheet": ws.title, "exact": exact, "rows": 0, "url": ""}
    header = values[0]
    cols = {i: header[i].strip() for i in range(5, min(len(header), 14))
            if header[i].strip() and header[i].strip().upper() != "ИТОГ"}
    totals = {name: 0.0 for name in cols.values()}
    clients = defaultdict(list)
    rows = 0
    for row in values[1:]:
        if not (row[0] or "").strip():
            continue
        rows += 1
        for idx, name in cols.items():
            if idx < len(row):
                v = num(row[idx])
                if v:
                    totals[name] += v
                    clients[name].append({"name": (row[0] or "").strip()[:60],
                                          "sum": round(v)})
    if not exact:
        # лист текущего месяца не создан: суммы прошлого периода выдавать нельзя
        logger.warning("Листа за текущий месяц нет, ближайший — «%s»", ws.title)
        totals = {name: None for name in cols.values()}
        clients = defaultdict(list)
    meta = {
        "sheet": ws.title,
        "exact": exact,
        "rows": rows if exact else 0,
        "url": f"https://docs.google.com/spreadsheets/d/{SALES_SPREADSHEET}/edit#gid={ws.id}",
    }
    return ({k: (round(v) if v is not None else None) for k, v in totals.items()},
            meta, clients)


def read_plans(spreadsheet):
    """Планы из листа НАСТРОЙКИ: отдел (оборот/оплаты/новые) и по менеджерам.

    Персональные планы новых продаж лежат отдельными строками («София Хакимова
    (стажёр) · Оборот новых клиентов (план) · 105000» — правило Анны 01.09.2026),
    общий план менеджера поиска — строка «Менеджеры поиска (каждый)».
    """
    values = spreadsheet.worksheet("НАСТРОЙКИ").get_all_values()
    plans = {"oborot": 0.0, "postup": 0.0, "new": 0.0,
             "search_default": PLAN_SEARCH_DEFAULT, "personal": {}, "support": {},
             "period": ""}
    for row in values:
        who = (row[0] or "").strip() if len(row) > 0 else ""
        what = (row[1] or "").strip().lower() if len(row) > 1 else ""
        val = num(row[2]) if len(row) > 2 else 0.0
        if who == "Месяц и год расчёта" and len(row) > 1:
            plans["period"] = (row[1] or "").strip()
            continue
        if not who or not what:
            continue
        low = who.lower()
        if "роп" in low:
            # ★ «новые» проверяем первым: строка плана новых клиентов называется
            # «Новые клиенты — оплаты (план)» и иначе попала бы в план оплат.
            if "новые" in what:
                plans["new"] = val
            elif "оборот" in what:
                plans["oborot"] = val
            elif "оплаты" in what:
                plans["postup"] = val
        elif "менеджеры поиска" in low and "новых клиентов" in what:
            plans["search_default"] = val or PLAN_SEARCH_DEFAULT
        elif "новых клиентов" in what and val:
            plans["personal"][first_name(who)] = val
        elif "оплаты ресторанов" in what and val:
            # план менеджера сопровождения (НАСТРОЙКИ!C9 у Алёны) — ключ полным именем,
            # как он написан в колонке G листов ДАННЫЕ_*
            plans["support"][who.split("(")[0].strip()] = val
    return plans


def support_payments(spreadsheet, names):
    """{имя: (оплаты до вычета беби, скорр. оплаты)} по ресторанам сопровождения.

    Повторяет формулы СВОДНОЙ (блок сопровождения): суммируем листы ДАННЫЕ_* по
    колонкам D (уменьшение долга = оплаты) и J (скорр. оплаты, из которых вычтены
    беби-листы) там, где G — этот менеджер, а H = «Ресторан». % плана в ЗП считается
    от оплат ДО вычета беби — так же, как в файле взаиморасчётов менеджера.
    """
    D, J, G, H = 3, 9, 6, 7          # колонки листа ДАННЫЕ_* (данные с 4-й строки)
    result = {n: [0.0, 0.0] for n in names}
    for cfg in so.SHEET_BASES.values():
        sheet_name = cfg.get("sheet_name")
        if not sheet_name:
            continue
        try:
            rows = spreadsheet.worksheet(sheet_name).get_all_values()
        except Exception as exc:
            logger.warning("Лист %s недоступен: %s", sheet_name, exc)
            continue
        for row in rows[so.DATA_START_ROW - 1:]:
            if len(row) <= J:
                continue
            who = (row[G] or "").strip()
            if who not in result or (row[H] or "").strip() != "Ресторан":
                continue
            result[who][0] += num(row[D])
            result[who][1] += num(row[J])
    return {n: (round(v[0]), round(v[1])) for n, v in result.items()}


# ─── 1С: оборот отдела и оборот клиентов по менеджеру поиска ──────────────────

def oborot_total(today):
    """Оборот месяца по всем живым базам (регистр Продажи, как отчёт 1С)."""
    bases = so.live_bases()
    per_base, total = {}, 0.0
    for key, cfg in bases.items():
        try:
            v = so.fetch_oborot(cfg["id"], today)
        except Exception as exc:
            logger.warning("Оборот базы %s недоступен: %s", key, exc)
            per_base[key] = None
            continue
        per_base[key] = round(v)
        total += v
    return round(total), per_base, [k for k, v in per_base.items() if v is None]


def oborot_by_search_manager(spreadsheet, today):
    """{имя менеджера поиска: оборот его клиентов за месяц} из 1С + СПРАВОЧНИК.

    Оборот клиента = приход по регистру РасчетыСПокупателями (увеличение долга,
    зачёты аванса вычтены в sync_odata.aggregate_balances). Конкурентов и
    закупки исключаем — правило учёта из СПРАВОЧНИКА (колонка «Тип»).
    """
    ref = spreadsheet.worksheet("СПРАВОЧНИК").get_all_values()
    owner, skip = {}, set()
    for row in ref[3:]:
        name = (row[0] or "").strip()
        if not name:
            continue
        kind = (row[3] or "").strip().lower() if len(row) > 3 else ""
        if kind in ("конкурент", "закупки"):
            skip.add(name)
            continue
        search = (row[1] or "").strip() if len(row) > 1 else ""
        if search and search.lower() != "прямой клиент":
            owner[name] = first_name(search)
    index = so.build_token_index(list(owner) + list(skip))
    result = defaultdict(float)
    unmatched = 0.0
    for key, cfg in so.live_bases().items():
        try:
            balances = so.fetch_base_balances(cfg["id"], today)
        except Exception as exc:
            logger.warning("Взаиморасчёты базы %s недоступны: %s", key, exc)
            continue
        for name, vals in balances.items():
            turnover = vals[1]
            if turnover <= 0:
                continue
            canon = name if name in owner or name in skip else so.soft_lookup(name, index)
            if canon in skip:
                continue
            who = owner.get(canon)
            if who:
                result[who] += turnover
            else:
                unmatched += turnover
    logger.info("Оборот по менеджерам поиска: %s (без привязки %.0f)",
                {k: round(v) for k, v in result.items()}, unmatched)
    return {k: round(v) for k, v in result.items()}, round(unmatched)


# ─── сборка данных борда ──────────────────────────────────────────────────────

def build(today=None, use_llm=True):
    load_env()
    today = today or datetime.now()
    start, days_in_month = month_bounds(today)
    pace = min(today.day / days_in_month, 1.0)

    gc = open_sheets()
    salary = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    sales_book = gc.open_by_key(SALES_SPREADSHEET)

    plans = read_plans(salary)
    sales, sales_meta, sales_clients = manager_sales(sales_book, today)

    oborot, oborot_bases, bases_down = oborot_total(today)
    try:
        from sync_kassa import fetch_postupleniya
        postup = round(fetch_postupleniya(today))
        postup_error = None
    except Exception as exc:                                  # касса не должна ронять борд
        logger.warning("Поступления из кассы недоступны: %s", exc)
        postup, postup_error = None, str(exc)[:200]

    support = []
    try:
        # листы ДАННЫЕ_* живут по расчётному периоду из НАСТРОЕК (B4): пока месяц не
        # закрыт, в них лежит он, а не календарный — иначе борд выдал бы сентябрьские
        # оплаты за октябрьские (поймано 02.10.2026)
        data_period = plans["period"]
        facts = support_payments(salary, list(plans["support"]))
        for who, plan in plans["support"].items():
            raw, adj = facts.get(who, (0, 0))
            support.append({"name": first_name(who), "full": who, "plan": round(plan),
                            "fact": raw, "fact_adj": adj, "period": data_period,
                            "stale": (data_period or "").lower()
                                     != f"{MONTHS_RU[today.month - 1]} {today.year}",
                            "pct": round(raw / plan, 4) if plan else None})
    except Exception as exc:
        logger.warning("Оплаты сопровождения не посчитаны: %s", exc)

    try:
        oborot_mgr, oborot_unmatched = oborot_by_search_manager(salary, today)
    except Exception as exc:
        logger.warning("Оборот по менеджерам не посчитан: %s", exc)
        oborot_mgr, oborot_unmatched = {}, 0

    # ─ Битрикс: воронка дегустаций
    deals = fetch_deals()
    users = fetch_users(sorted({d["ASSIGNED_BY_ID"] for d in deals
                                if d["DATE_MODIFY"] >= start.strftime("%Y-%m-%d")}))
    period_iso = start.strftime("%Y-%m-%d")

    tastings = defaultdict(list)        # дегустации, отправленные в этом месяце
    active_rows = []                    # сделки в работе (движение в этом месяце)
    stuck_rows = []                     # активные без движения дольше 30 дней
    won_month = []                      # закрепили сотрудничество в этом месяце
    seen_titles = defaultdict(list)
    tests = []                          # тестовые карточки CRM — в борд не идут
    stage_names = {**STAGE_NAMES_FALLBACK, **fetch_stage_names()}

    for d in deals:
        stage = d["STAGE_ID"]
        title = (d["TITLE"] or "").strip()
        created = d["DATE_CREATE"][:10]
        modified = d["DATE_MODIFY"][:10]
        who = users.get(str(d["ASSIGNED_BY_ID"]), "")
        if TEST_TITLE.search(title):
            if created >= period_iso or modified >= period_iso:
                tests.append({"id": d["ID"], "title": title[:60],
                              "mgr": first_name(who) if who != "без менеджера" else who})
            continue
        short = who if who == "без менеджера" else first_name(who)
        note = last_note(d.get("COMMENTS"))
        if created >= period_iso:
            tastings[short or "без менеджера"].append(
                {"id": d["ID"], "title": title[:60],
                 "created": created, "stage": stage})
            seen_titles[norm_title(title)].append(
                {"id": d["ID"], "title": title[:60], "mgr": short})
        if stage == "WON" and modified >= period_iso:
            won_month.append({"title": title[:60], "mgr": short})
        if stage not in CLOSED_STAGES and modified < (
                today - timedelta(days=30)).strftime("%Y-%m-%d"):
            stuck_rows.append({"id": d["ID"], "title": title[:60], "mgr": short,
                               "modified": modified})
        if modified >= period_iso and stage != "WON":
            dt = note_date(note, today)
            last_touch = max([x for x in (dt, datetime.strptime(modified, "%Y-%m-%d"))
                              if x] or [None])
            active_rows.append({
                "id": d["ID"],
                "title": title[:60],
                "mgr": short or "—",
                "stage": stage,
                "stage_name": stage_names.get(stage, stage),
                "status": STAGE_STATUS.get(stage, "none"),
                "note": note,
                "empty": not note,
                "modified": modified,
                "days": (today - last_touch).days if last_touch else None,
            })

    # ─ статусы: стадия + разбор комментария моделью (с кешем)
    llm_used = False
    if use_llm and active_rows:
        cache = load_cache()
        need, fresh = [], {}
        for r in active_rows:
            h = hashlib.sha1(f"{r['stage']}|{r['note']}".encode()).hexdigest()[:16]
            hit = cache.get(r["id"])
            if hit and hit.get("h") == h:
                fresh[r["id"]] = hit
            else:
                need.append({"id": r["id"], "stage": r["stage"], "note": r["note"] or ""})
                fresh[r["id"]] = {"h": h}
        got = llm_classify(need)
        llm_used = bool(got)
        for did, v in got.items():
            if did in fresh:
                fresh[did].update(status=v["status"], action=v["action"])
        for r in active_rows:
            hit = fresh.get(r["id"], {})
            status, action = hit.get("status"), hit.get("action")
            if status == "won" and r["stage"] != "WON":
                # клиент уже заказывает, а стадия в CRM другая — это работа РОПу
                status = "push"
                action = ((action or "") + " · в CRM стадия не обновлена").strip(" ·")
            if status:
                r["status"] = status
            if action:
                r["action"] = action
        save_cache({k: v for k, v in fresh.items() if v.get("status")})

    for r in active_rows:
        r.setdefault("action", r["note"] or "нет информации в карточке")
        if r["empty"] and r["status"] not in ("out", "won"):
            r["status"] = "fill"

    # ─ менеджеры: факт, план, воронка
    mgr_names = []
    for name in sales:
        mgr_names.append(name)
    for name in tastings:
        if name not in mgr_names and name != "без менеджера":
            mgr_names.append(name)

    managers = []
    for name in mgr_names:
        plan = plans["personal"].get(name)
        is_search = plan is not None or name in ("Дарья", "Ксения", "Лилия")
        if plan is None and is_search:
            plan = plans["search_default"]
        rows = [r for r in active_rows if r["mgr"] == name]
        live = [r for r in rows if r["status"] not in ("out", "won")]
        managers.append({
            "name": name,
            "sales": sales.get(name, 0) if sales_meta["exact"] else None,
            "plan": plan or 0,
            "tastings": len(tastings.get(name, [])),
            "in_work": len(live),
            "closed": len(rows) - len(live),
            "empty": len([r for r in live if r["empty"]]),
            "stale": len([r for r in live if (r["days"] or 0) > STALE_DAYS]),
            "oborot": oborot_mgr.get(name, 0),
        })
    managers.sort(key=lambda m: (-(m["sales"] or 0), m["name"]))

    # ─ дубли карточек в воронке за месяц
    dupes = [{"title": cards[0]["title"], "cards": cards}
             for t, cards in seen_titles.items() if len(cards) > 1 and t]

    # ─ «на что обратить внимание»
    flags = []
    if bases_down:
        flags.append({"kind": "crit",
                      "text": f"1С: базы недоступны — {', '.join(bases_down)}. "
                              f"Оборот показан без них."})
    if postup_error:
        flags.append({"kind": "crit", "text": f"Касса GREENCH не ответила: {postup_error}"})
    if not sales_meta["exact"]:
        flags.append({"kind": "crit",
                      "text": f"В «ОТЧЕТАХ ПО ПРОДАЖАМ» нет листа за "
                              f"{MONTHS_RU[today.month - 1]} {today.year} — новые продажи не "
                              f"считаю, чтобы не выдать цифры прошлого периода. Создайте лист "
                              f"(как «август-сентябрь»), борд подхватит его сам на следующем "
                              f"прогоне."})
    behind = [m for m in managers
              if m["plan"] and m["sales"] is not None
              and m["sales"] / m["plan"] < pace * 0.7]
    if behind:
        flags.append({"kind": "crit",
                      "text": "Сильно ниже темпа по новым продажам: "
                              + ", ".join(f"{m['name']} "
                                          f"{round(m['sales'] / m['plan'] * 100)}%"
                                          for m in behind),
                      "items": [{"title": m["name"],
                                 "sub": f"{m['sales']:,.0f} ₽ из {m['plan']:,.0f} — "
                                        f"не хватает {m['plan'] - m['sales']:,.0f} ₽"
                                        .replace(",", " ")}
                                for m in behind]})
    live_rows = [r for r in active_rows if r["status"] not in ("out", "won")]
    for sup in support:
        if sup["pct"] is not None and not sup["stale"] and sup["pct"] < pace * 0.9:
            flags.append({"kind": "warn",
                          "text": f"Оплаты ресторанов {sup['name']}: "
                                  f"{sup['pct'] * 100:.0f}% плана при темпе месяца "
                                  f"{pace * 100:.0f}%"})

    empty_cards = [r for r in live_rows if r["empty"]]
    if empty_cards:
        by = defaultdict(int)
        for r in empty_cards:
            by[r["mgr"]] += 1
        flags.append({"kind": "warn",
                      "text": f"Карточек без информации — {len(empty_cards)}: "
                              + ", ".join(f"{k} {v}" for k, v in
                                          sorted(by.items(), key=lambda x: -x[1])),
                      "items": [{"id": r["id"], "title": r["title"],
                                 "sub": f"{r['mgr']} · стадия "
                                        f"«{stage_names.get(r['stage'], r['stage'])}»"}
                                for r in sorted(empty_cards,
                                                key=lambda r: (r["mgr"], r["title"]))]})
    stale_rows = [r for r in live_rows if (r["days"] or 0) > STALE_DAYS]
    if stale_rows:
        flags.append({"kind": "warn",
                      "text": f"Без движения дольше {STALE_DAYS} дней — "
                              f"{len(stale_rows)} сделок в работе",
                      "items": [{"id": r["id"], "title": r["title"],
                                 "sub": f"{r['mgr']} · {r['days']} дн. без движения · "
                                        f"{r['action']}"}
                                for r in sorted(stale_rows,
                                                key=lambda r: -(r["days"] or 0))]})
    if dupes:
        flags.append({"kind": "warn",
                      "text": f"Дубли карточек в воронке — {len(dupes)}: "
                              + "; ".join(d["title"] for d in dupes[:5]),
                      "items": [{"title": d["title"],
                                 "sub": f"{len(d['cards'])} карточки — оставить одну",
                                 "links": [{"id": c["id"],
                                            "label": f"{c['title']} ({c['mgr']})"}
                                           for c in d["cards"]]}
                                for d in dupes]})
    if tests:
        flags.append({"kind": "info",
                      "text": f"Тестовых карточек в воронке за месяц: {len(tests)} — "
                              f"в борде не показаны",
                      "items": [{"id": t["id"], "title": t["title"], "sub": t["mgr"]}
                                for t in tests]})
    if stuck_rows:
        shown = sorted(stuck_rows, key=lambda r: r["modified"], reverse=True)[:60]
        note = (f" Показаны {len(shown)} самых свежих из {len(stuck_rows)}."
                if len(shown) < len(stuck_rows) else "")
        flags.append({"kind": "info",
                      "text": f"В воронке {len(stuck_rows)} открытых сделок без движения "
                              f"больше 30 дней — их не видно в работе месяца." + note,
                      "items": [{"id": r["id"], "title": r["title"],
                                 "sub": f"{r['mgr']} · последнее движение "
                                        f"{r['modified'][8:10]}.{r['modified'][5:7]}."
                                        f"{r['modified'][:4]}"}
                                for r in shown]})

    data = {
        "generated": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "period_label": f"{MONTHS_RU[today.month - 1].capitalize()} {today.year}",
        "as_of": f"{today.day} {MONTHS_GEN[today.month - 1]}",
        "pace": round(pace, 4),
        "day": today.day,
        "days_in_month": days_in_month,
        "settings_period": plans["period"],
        "kpi": {
            "oborot": {"fact": oborot, "plan": round(plans["oborot"]),
                       "reason": ("1С не ответила: " + ", ".join(bases_down)
                                  if bases_down and oborot == 0 else None)},
            "postup": {"fact": postup, "plan": round(plans["postup"]),
                       "reason": "Касса GREENCH не ответила" if postup is None else None},
            "new": {"fact": (round(sum(v for v in sales.values() if v))
                             if sales_meta["exact"] else None),
                    "plan": round(plans["new"]),
                    "reason": (None if sales_meta["exact"] else
                               f"нет листа за {MONTHS_RU[today.month - 1]} "
                               f"{today.year} в таблице")},
            "tastings": {
                "count": sum(len(v) for v in tastings.values()),
                "in_work": len(live_rows),
                "closed": len(active_rows) - len(live_rows),
                "empty": len(empty_cards),
                "push": len([r for r in live_rows if r["status"] == "push"]),
                "won": len(won_month),
            },
        },
        "support": support,
        "oborot_bases": oborot_bases,
        "oborot_unmatched": oborot_unmatched,
        "managers": managers,
        "tastings": {k: v for k, v in sorted(tastings.items(),
                                             key=lambda kv: -len(kv[1]))},
        "deals": sorted(active_rows, key=lambda r: (r["mgr"], r["title"])),
        "won_month": won_month,
        "flags": flags,
        "status_titles": STATUS_TITLES,
        "sales_meta": sales_meta,
        "top_clients": {k: sorted(v, key=lambda c: -c["sum"])[:5]
                        for k, v in sales_clients.items()},
        "llm": llm_used,
    }
    return data


# ─── рендер и доставка ────────────────────────────────────────────────────────

def render(data, template=TEMPLATE):
    with open(template, encoding="utf-8") as f:
        html = f.read()
    marker = "/*__DATA__*/"
    if marker not in html:
        raise RuntimeError(f"В шаблоне {template} нет маркера {marker}")
    return html.replace(marker, json.dumps(data, ensure_ascii=False))


def summary_text(data, url=None):
    """Короткая сводка для сообщения в MAX/Telegram."""
    k = data["kpi"]

    def line(title, fact, plan):
        if fact is None:
            return f"{title}: нет данных"
        pct = f" · {fact / plan * 100:.0f}% плана" if plan else ""
        return f"{title}: {fact:,.0f} ₽{pct}".replace(",", " ")

    parts = [
        f"Борд продаж · {data['period_label']} (на {data['as_of']}, темп месяца "
        f"{data['pace'] * 100:.0f}%)",
        line("Оборот", k["oborot"]["fact"], k["oborot"]["plan"]),
        line("Оплаты", k["postup"]["fact"], k["postup"]["plan"]),
        line("Новые продажи", k["new"]["fact"], k["new"]["plan"]),
    ] + [
        f"Оплаты ресторанов {s['name']}: {s['fact']:,.0f} ₽ · "
        f"{s['pct'] * 100:.0f}% плана".replace(",", " ")
        for s in data.get("support", []) if s["pct"] is not None
    ] + [
        f"Дегустации: {k['tastings']['count']} · в работе "
        f"{k['tastings']['in_work']} · на дожиме {k['tastings']['push']} · "
        f"без инфо {k['tastings']['empty']}",
    ]
    for f in data["flags"][:4]:
        parts.append(("⚠️ " if f["kind"] != "info" else "· ") + f["text"])
    if url:
        parts.append(url)
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Борд РОПа: сбор данных и страница")
    ap.add_argument("--out", help="куда положить index.html")
    ap.add_argument("--json", dest="json_path", help="куда положить данные JSON")
    ap.add_argument("--no-llm", action="store_true", help="без разбора комментариев моделью")
    ap.add_argument("--print", dest="do_print", action="store_true", help="сводка в консоль")
    ap.add_argument("--notify", choices=["max", "tg"], help="отправить сводку со ссылкой")
    ap.add_argument("--url", help="ссылка на борд для сообщения")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_env()

    data = build(use_llm=not args.no_llm)

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"данные: {args.json_path}")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(render(data))
        print(f"страница: {args.out}")
    if args.do_print or not (args.out or args.json_path):
        print(summary_text(data, args.url))
    if args.notify:
        send_summary(data, args.notify, args.url)


def send_summary(data, target, url=None):
    """Сводка со ссылкой в MAX (по умолчанию) или Telegram Анне."""
    text = summary_text(data, url or os.environ.get("BOARD_URL"))
    if target == "max":
        token = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN")
        chat = os.environ.get("MAX_ANNA_CHAT_ID") or os.environ.get("BOARD_MAX_CHAT_ID")
        if not (token and chat):
            raise RuntimeError("Для MAX нужны MAX_TOKEN и MAX_ANNA_CHAT_ID в .env")
        # хост и авторизация — как в рабочем клиенте MAX (obrez-report/core/maxgroup.py)
        r = requests.post("https://platform-api.max.ru/messages",
                          params={"chat_id": chat},
                          json={"text": text, "notify": True},
                          headers={"Authorization": token,
                                   "Content-Type": "application/json"}, timeout=60)
        r.raise_for_status()
    else:
        token = os.environ["BOT_TOKEN"]
        chat = os.environ.get("ANNA_CHAT_ID")
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text,
                                "disable_web_page_preview": True}, timeout=60)
        r.raise_for_status()
    print(f"сводка отправлена ({target})")


if __name__ == "__main__":
    main()
