#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  ЕДИНЫЙ БОT (ПРОТОТИП)  —  УНФ → Telegram + Google Sheets
================================================================================

ЧТО ЭТО
  Один самодостаточный файл — прототип «одного бота», в который собрано ВСЁ:
    1) Отчёты из 1С по команде за любой период      (модуль REPORTS)
    2) Учёт смен из группового чата → лист СМЕНЫ      (модуль SHIFTS)
    3) Зарплата сотрудников (1С + смены → СВОДНАЯ_ЗП) (модуль SALARY)  ← приоритет
    4) Дашборды (заполнение листа DASHBOARD)          (модуль DASHBOARD)
    5) Сообщения по зарплатам тебе в личку            (часть SALARY)

  Файл специально разбит на ПОНЯТНЫЕ СЕКЦИИ (см. баннеры «=== СЕКЦИЯ N ===»),
  чтобы можно было дорабатывать/чинить ОДНУ фичу, не трогая остальное.
  Когда прототип отлажен — каждую секцию легко вынести в свой файл.

КАК ЗАПУСКАТЬ (прототип, без webhook — простой polling, проще отлаживать):
    pip install python-telegram-bot==20.7 gspread google-auth requests python-dotenv
    python bot_prototype.py

  Бот читает секреты из .env (см. СЕКЦИЯ 1). Для Google Sheets нужен
  service-account JSON (credentials.json) с доступом к таблице (расшарить
  таблицу на email из этого JSON).

ОТЛАДКА БЕЗ ПОДКЛЮЧЕНИЙ:
    python bot_prototype.py --selftest
  Прогонит парсер смен и расчёт зарплаты на тестовых данных, ничего не отправляя.

ЛЕГЕНДА ПО МЕТКАМ:
    # TODO:1С   — уточнить у данных 1С (поля/регистры)
    # TODO:ЗП   — уточнить правило расчёта зарплаты
    # TODO:ЛИСТ — согласовать колонки листа в таблице
================================================================================
"""

import os
import re
import sys
import time
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Tuple

import requests

# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 1. КОНФИГУРАЦИЯ (секреты и константы) ============================
# ──────────────────────────────────────────────────────────────────────────────
# Все секреты берём из .env, НЕ хардкодим в коде. Значения по умолчанию ниже —
# плейсхолдеры; реальные значения у тебя уже лежат в .env проекта.

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


class CONFIG:
    # — Telegram —
    BOT_TOKEN   = _env("BOT_TOKEN")                      # токен от @BotFather
    ANNA_CHAT_ID = _env("ANNA_CHAT_ID", "796207056")     # твоя личка (отчёты, ЗП)
    GROUP_CHAT_ID = _env("GROUP_CHAT_ID")                # id рабочей группы (смены)

    # — Google Sheets —
    SPREADSHEET_ID  = _env("SPREADSHEET_ID")             # ID таблицы (между /d/ и /edit)
    CREDENTIALS_PATH = _env("CREDENTIALS_PATH", "./credentials.json")

    # — 1С OData (42clouds) —
    ODATA_USER = _env("ODATA_USER", "api_bot")
    ODATA_PASS = _env("ODATA_PASS")                      # пароль из .env, не в коде
    ODATA_TIMEOUT = 25                                   # сек на запрос
    ODATA_RETRIES = 3

    # — Бизнес-константы —
    TIMEZONE = "Europe/Moscow"
    CALLS_NORM = 20                                      # норма звонков за смену  # TODO:ЗП

    # Две базы 1С. base_id — как в URL 42clouds.
    BASES = ["perfilev", "gubarev"]
    BASE_ENDPOINT = {
        "perfilev": "https://base.42clouds.com/unf/152757/odata/standard.odata/",
        "gubarev":  "https://base.42clouds.com/unf/64904/odata/standard.odata/",
    }
    BASE_TITLE = {"perfilev": "Перфильев", "gubarev": "Губарев"}


# Названия листов в таблице (единое место — меняешь тут, а не по всему коду).
class SHEETS:
    SHIFTS   = "СМЕНЫ"
    SALARY   = "СВОДНАЯ_ЗП"
    RECV     = "ИНТЕГРАЦИЯ"        # дебиторка из 1С
    SETTLE   = "ВЗАИМОРАСЧЁТЫ"
    DASHBOARD = "DASHBOARD"
    SETTINGS = "НАСТРОЙКИ"
    LOG      = "LOG"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
log = logging.getLogger("bot")


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 2. КЛИЕНТ TELEGRAM ==============================================
# ──────────────────────────────────────────────────────────────────────────────
# Тонкая обёртка над Bot API. В прототипе используем простой polling (getUpdates),
# а не webhook — так проще отлаживать и не ловить спам (с которым уже намучились).

class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def _call(self, method: str, **params):
        try:
            r = requests.post(self.base + method, json=params, timeout=20)
            return r.json()
        except Exception as e:
            log.error("Telegram %s failed: %s", method, e)
            return {"ok": False, "error": str(e)}

    def send(self, chat_id, text: str):
        # Длинные сообщения режем на части по 4000 символов.
        for i in range(0, len(text), 4000):
            self._call("sendMessage", chat_id=chat_id,
                       text=text[i:i + 4000], parse_mode="HTML",
                       disable_web_page_preview=True)

    def get_updates(self, offset: int, timeout: int = 25):
        r = self._call("getUpdates", offset=offset, timeout=timeout)
        return r.get("result", []) if r.get("ok") else []


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 3. КЛИЕНТ GOOGLE SHEETS =========================================
# ──────────────────────────────────────────────────────────────────────────────
# Через gspread (service account). Если gspread не установлен / нет credentials —
# работаем в «сухом» режиме (печатаем в лог), чтобы прототип всё равно запускался.

class Sheets:
    def __init__(self):
        self.ss = None
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(
                CONFIG.CREDENTIALS_PATH, scopes=scopes)
            self.ss = gspread.authorize(creds).open_by_key(CONFIG.SPREADSHEET_ID)
            log.info("Google Sheets подключены.")
        except Exception as e:
            log.warning("Sheets в сухом режиме (нет подключения): %s", e)

    def ws(self, name: str):
        if not self.ss:
            return None
        try:
            return self.ss.worksheet(name)
        except Exception:
            return self.ss.add_worksheet(title=name, rows=200, cols=26)

    def append(self, sheet_name: str, row: list):
        ws = self.ws(sheet_name)
        if ws is None:
            log.info("[DRY] append %s <- %s", sheet_name, row)
            return
        ws.append_row(row, value_input_option="USER_ENTERED")

    def set_cell(self, sheet_name: str, a1: str, value):
        ws = self.ws(sheet_name)
        if ws is None:
            log.info("[DRY] set %s!%s = %s", sheet_name, a1, value)
            return
        ws.update_acell(a1, value)

    def read_all(self, sheet_name: str) -> List[list]:
        ws = self.ws(sheet_name)
        if ws is None:
            return []
        return ws.get_all_values()


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 4. КЛИЕНТ 1С (OData) ============================================
# ──────────────────────────────────────────────────────────────────────────────
# Единый клиент 1С (раньше логика была раздвоена Python+GAS — здесь один источник).
# Basic Auth, $format=json, пагинация через @odata.nextLink, retry + timeout.

class OData:
    def __init__(self, base_id: str):
        self.base_id = base_id
        self.root = CONFIG.BASE_ENDPOINT[base_id]
        self.auth = (CONFIG.ODATA_USER, CONFIG.ODATA_PASS)

    def _get(self, url: str) -> dict:
        last = None
        for attempt in range(CONFIG.ODATA_RETRIES):
            try:
                r = requests.get(url, auth=self.auth, timeout=CONFIG.ODATA_TIMEOUT)
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}: {r.text[:200]}"
            except Exception as e:
                last = str(e)
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"OData {self.base_id} fail: {last}")

    def fetch(self, entity: str, query: str = "") -> List[dict]:
        """Тянет ВСЕ записи сущности с учётом пагинации."""
        sep = "&" if "?" in (entity + query) else "?"
        url = f"{self.root}{entity}{('?' + query) if query else ''}"
        if "$format" not in url:
            url += ("&" if "?" in url else "?") + "$format=json"
        rows: List[dict] = []
        while url:
            data = self._get(url)
            rows.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return rows

    # — Справочник контрагентов: Ref_Key -> Название —
    def contractors(self) -> Dict[str, str]:
        rows = self.fetch("Catalog_Контрагенты", "$select=Ref_Key,Description")
        return {r["Ref_Key"]: r.get("Description", "") for r in rows}

    # — Продажи (выручка) за период —
    def sales(self, d1: date, d2: date) -> float:
        # TODO:1С — подтвердить, что нужное поле выручки = «Сумма».
        # Сейчас даёт расхождение (70 727 vs эталон 38 050). Возможные варианты
        # поля: Сумма / СтоимостьПродажи / СуммаБезНДС. Сверить с отчётом 1С.
        flt = (f"Period ge datetime'{d1:%Y-%m-%d}T00:00:00' and "
               f"Period le datetime'{d2:%Y-%m-%d}T23:59:59'")
        rows = self.fetch("AccumulationRegister_Продажи_RecordType",
                          f"$filter={flt}")
        return float(sum(r.get("Сумма", 0) or 0 for r in rows))

    # — Дебиторка по договорам (только положительные остатки = долг) —
    def receivables(self) -> Tuple[float, List[Tuple[str, float]]]:
        # TODO:1С — авансы 1С не сворачивает с долгами. Считаем остаток по паре
        # (Контрагент_Key + Договор_Key); в долг берём только положительные.
        rows = self.fetch("AccumulationRegister_РасчетыСПокупателями_RecordType", "")
        names = self.contractors()
        bal: Dict[Tuple[str, str], float] = {}
        for r in rows:
            key = (r.get("Контрагент_Key", ""), r.get("Договор_Key", ""))
            amt = float(r.get("Сумма", 0) or 0)
            sign = 1 if r.get("RecordType") == "Receipt" else -1
            bal[key] = bal.get(key, 0.0) + sign * amt
        by_client: Dict[str, float] = {}
        for (ck, _dk), v in bal.items():
            if v > 0:                                    # только долг, авансы отдельно
                by_client[ck] = by_client.get(ck, 0.0) + v
        total = sum(by_client.values())
        top = sorted(((names.get(k, k), v) for k, v in by_client.items()),
                     key=lambda x: -x[1])[:8]
        return total, top


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 5. МОДУЛЬ SHIFTS — смены из группы ==============================
# ──────────────────────────────────────────────────────────────────────────────
# Парсит сообщение о смене из группы и пишет строку в лист СМЕНЫ.
# Формат (пример из проекта):  "смена 25 5 100 рест.1тел:2 250"
#                               смена ДЕНЬ ОСН_СМЕН ОСН_СУММА [подработка:кол-во] ПОДР_СУММА

@dataclass
class Shift:
    employee: str
    day: str
    main_shifts: int = 0
    main_amount: float = 0.0
    side_label: str = ""
    side_count: int = 0
    side_amount: float = 0.0
    day_type: str = "weekday"   # weekday | weekend — берётся из шаблона смены


def parse_shift(text: str, employee: str) -> Optional[Shift]:
    t = text.strip().lower()
    if not t.startswith("смена"):
        return None
    body = t[len("смена"):].strip()
    # тип дня из шаблона смены: «выходной»/«вых» -> weekend, иначе weekday
    day_type = "weekend" if re.search(r"выходн|\bвых\b", body) else "weekday"
    body = re.sub(r"выходн\w*|будн\w*|\bвых\b|\bбуд\b", " ", body)
    # вытащим подработку вида "слово:число"
    side_label, side_count = "", 0
    m = re.search(r"([a-zа-я0-9_.+]+):(\d+)", body)
    if m:
        side_label, side_count = m.group(1), int(m.group(2))
        body = body.replace(m.group(0), " ")
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+[.,]?\d*", body)]
    if not nums:
        return None
    # nums: [день, осн_смен, осн_сумма, ..., подр_сумма]
    day = str(int(nums[0])) if nums else ""
    main_shifts = int(nums[1]) if len(nums) > 1 else 0
    main_amount = nums[2] if len(nums) > 2 else 0.0
    side_amount = nums[-1] if (side_label and len(nums) > 3) else 0.0
    return Shift(employee, day, main_shifts, main_amount,
                 side_label, side_count, side_amount, day_type)


class ShiftsModule:
    def __init__(self, tg: Telegram, sheets: Sheets):
        self.tg, self.sheets = tg, sheets

    def handle_group_message(self, employee: str, text: str, reply_chat):
        sh = parse_shift(text, employee)
        if not sh:
            return False
        # TODO:ЛИСТ — согласовать порядок колонок листа СМЕНЫ.
        self.sheets.append(SHEETS.SHIFTS, [
            sh.day, sh.employee, sh.main_shifts, sh.main_amount,
            sh.side_label, sh.side_count, sh.side_amount,
            sh.day_type,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ])
        # лёгкая валидация-алерт
        warn = ""
        if sh.side_count and sh.side_count < CONFIG.CALLS_NORM:
            warn = f"  ⚠️ мало ({sh.side_count}<{CONFIG.CALLS_NORM})"
        self.tg.send(reply_chat, f"✅ Смена принята: {sh.employee}, "
                                 f"день {sh.day}, осн {sh.main_amount:.0f}{warn}")
        return True


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 6. МОДУЛЬ REPORTS — данные из 1С по команде =====================
# ──────────────────────────────────────────────────────────────────────────────
# Команды: /today  /range ДД.ММ ДД.ММ  /sales ...  /debt
# Тянет из обеих баз, считает отдельно и Итог, шлёт текстом.

def parse_ddmm(s: str, default_year: int) -> Optional[date]:
    m = re.match(r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?$", s.strip())
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else default_year
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


class ReportsModule:
    def __init__(self, tg: Telegram):
        self.tg = tg

    def report_period(self, chat_id, d1: date, d2: date):
        lines = [f"<b>Отчёт 1С: {d1:%d.%m.%Y} – {d2:%d.%m.%Y}</b>"]
        grand_sales = grand_debt = 0.0
        for base in CONFIG.BASES:
            try:
                od = OData(base)
                sales = od.sales(d1, d2)
                debt, top = od.receivables()
                grand_sales += sales
                grand_debt += debt
                lines.append(
                    f"\n<b>{CONFIG.BASE_TITLE[base]}</b>\n"
                    f"  Продажи: {sales:,.0f} ₽\n"
                    f"  Дебиторка: {debt:,.0f} ₽\n"
                    f"  Топ-долг: " +
                    "; ".join(f"{n} {v:,.0f}" for n, v in top[:3])
                )
            except Exception as e:
                lines.append(f"\n<b>{CONFIG.BASE_TITLE[base]}</b>: ошибка — {e}")
        lines.append(f"\n<b>ИТОГО</b>  продажи {grand_sales:,.0f} ₽, "
                     f"дебиторка {grand_debt:,.0f} ₽")
        self.tg.send(chat_id, "\n".join(lines).replace(",", " "))


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 7. МОДУЛЬ SALARY — зарплата (ПРИОРИТЕТ) =========================
# ──────────────────────────────────────────────────────────────────────────────
# Что делает:
#   1) собирает смены сотрудника за период (из листа СМЕНЫ);
#   2) (опц.) добавляет показатели из 1С (выручка/продажи сотрудника);  # TODO:1С
#   3) считает зарплату по правилу (ставка за смену + % + подработки);  # TODO:ЗП
#   4) пишет результат в лист СВОДНАЯ_ЗП;                                # TODO:ЛИСТ
#   5) шлёт тебе в личку сводку по зарплатам.
#
# Правило расчёта вынесено в SALARY_RULES — меняешь тут, не трогая остальное.

# ─── Сотрудники → группа оплаты. ФИ как пишутся в смене/Telegram. ─── # TODO:ЗП
EMPLOYEE_GROUP = {
    "Валерия Абрамова":      "soprovozhdenie",
    "Алена Черкашина":       "soprovozhdenie",
    "Валерия Папоян":        "poisk",
    "Ксения Наныкина":       "poisk",
    "Дарья Вольнова":        "poisk",
    "Лианна Багдасарян":     "poisk",
    "Владислава Герасимчук": "vlada",
    "Анна Кононенко":        "rop",
}
DEFAULT_GROUP = "poisk"

# ─── Ставки за основную смену по группам (₽) ───
SHIFT_RATE = {
    "poisk":          {"weekday": 2500, "weekend": 2500},  # TODO:ЗП выходной поиска?
    "soprovozhdenie": {"weekday": 2500, "weekend": 1800},
    "vlada":          {"weekday": 3000, "weekend": 0},     # выходной Влады = только подработки
    "rop":            {"weekday": 5000, "weekend": 5000},
}

# ─── Ставки подработок (₽ за смену, абсолютные суммы) ───
SIDE_RATE = {
    "рест.1тел":  1800,   # ресторан, 1 телефон
    "рест.2тел":  2100,   # ресторан, 2 телефона (1800 + 300)
    "фирмы":      1800,   # только фирмы
    "фирмы+1тел": 3600,   # фирмы (1800) + 1 телефон (1800)
    "фирмы+2тел": 3900,   # фирмы (1800) + 2 телефона (1800 + 300)
}
VLADA_SIDE_FLAT = {"weekday": 2500, "weekend": 2000}  # у Влады подработка — фикс за смену

# ─── KPI «поиск»: план + таблица порогов ───
PLAN_POISK = 210000  # ₽/мес — на КАЖДОГО менеджера поиска, оборот по новым клиентам
# (порог % плана, фикс-бонус ₽, доля от оплат). Берётся ВЫСШИЙ достигнутый порог.
KPI_TABLE_POISK = [
    (50,  5000,  0.01),
    (70,  10000, 0.02),
    (100, 15000, 0.03),
    (115, 25000, 0.03),
    (130, 35000, 0.05),
    (150, 45000, 0.05),
    (200, 60000, 0.07),
]


def kpi_poisk(plan_pct: float) -> Tuple[float, float]:
    """% выполнения плана → (фикс_бонус, доля_от_оплат). Ниже 50% → (0, 0)."""
    fix, pct = 0.0, 0.0
    for thr, f, p in KPI_TABLE_POISK:
        if plan_pct >= thr:
            fix, pct = float(f), p
    return fix, pct


@dataclass
class SalaryRow:
    employee: str
    group: str = ""
    shifts: int = 0
    base_pay: float = 0.0
    side_pay: float = 0.0
    plan_pct: float = 0.0        # % выполнения плана (для KPI)
    kpi_fix: float = 0.0         # фикс-бонус по таблице KPI
    kpi_pay: float = 0.0         # выплата «% от оплат»
    total: float = 0.0


def compute_salary(shift_rows: List[list],
                   kpi_inputs: Dict[str, dict] = None) -> List[SalaryRow]:
    """
    shift_rows — нормализованные строки (как пишет ShiftsModule):
        [день, сотрудник, осн_смен, осн_сумма, подр_метка, подр_кол, подр_сумма, ...]
    kpi_inputs — {сотрудник: {"plan_fact": оборот_по_новым, "payments": поступления}}.
        Для группы «поиск». Берётся из таблицы (лист ПЛАН/справочник). # TODO:ЛИСТ
    """
    kpi_inputs = kpi_inputs or {}
    agg: Dict[str, SalaryRow] = {}
    for row in shift_rows:
        if len(row) < 4:
            continue
        emp = str(row[1]).strip()
        if not emp:
            continue
        grp = EMPLOYEE_GROUP.get(emp, DEFAULT_GROUP)
        r = agg.setdefault(emp, SalaryRow(emp, grp))
        day_type = str(row[7]).strip() if len(row) > 7 else "weekday"
        if day_type not in ("weekday", "weekend"):
            day_type = "weekday"
        # основные смены — ставка по типу дня
        try:
            shifts = int(float(row[2] or 0))
        except Exception:
            shifts = 0
        r.shifts += shifts
        r.base_pay += shifts * SHIFT_RATE[grp][day_type]
        # подработки
        label = str(row[4]).strip() if len(row) > 4 else ""
        try:
            cnt = int(float(row[5] or 0)) if len(row) > 5 else 0
        except Exception:
            cnt = 0
        if grp == "vlada":
            r.side_pay += cnt * VLADA_SIDE_FLAT[day_type]
        elif label in SIDE_RATE:
            r.side_pay += cnt * SIDE_RATE[label]
        elif len(row) > 6:                                   # запасной вариант — сумма из смены
            try:
                r.side_pay += float(row[6] or 0)
            except Exception:
                pass

    # KPI считаем для «поиска»
    for emp, r in agg.items():
        if r.group == "poisk":
            inp = kpi_inputs.get(emp, {})
            fact = float(inp.get("plan_fact", 0) or 0)
            payments = float(inp.get("payments", 0) or 0)
            r.plan_pct = round(fact / PLAN_POISK * 100, 1) if PLAN_POISK else 0
            r.kpi_fix, pct = kpi_poisk(r.plan_pct)
            r.kpi_pay = round(payments * pct)
        r.total = r.base_pay + r.side_pay + r.kpi_fix + r.kpi_pay
    return sorted(agg.values(), key=lambda x: -x.total)


class SalaryModule:
    def __init__(self, tg: Telegram, sheets: Sheets):
        self.tg, self.sheets = tg, sheets

    def _kpi_inputs(self) -> Dict[str, dict]:
        # Для «поиска»:
        #   plan_fact = оборот по НОВЫМ клиентам менеджера (план 210 000 ₽/чел).
        #   payments  = «% от оплат» считается от УМЕНЬШЕНИЯ долга контрагентов
        #               (поступления) по файлу/листу ВЗАИМОРАСЧЁТЫ, в разрезе
        #               ответственного менеджера.
        # TODO:ЛИСТ — прочитать оба числа на сотрудника из таблицы. Пока пусто.
        return {}

    def run(self, chat_id, period_label: str = ""):
        shift_rows = self.sheets.read_all(SHEETS.SHIFTS)
        if shift_rows and not str(shift_rows[0][0]).strip().isdigit():
            shift_rows = shift_rows[1:]                       # снять заголовок
        rows = compute_salary(shift_rows, self._kpi_inputs())

        for r in rows:                                        # запись в СВОДНАЯ_ЗП # TODO:ЛИСТ
            self.sheets.append(SHEETS.SALARY, [
                period_label, r.employee, r.group, r.shifts,
                round(r.base_pay), round(r.side_pay),
                f"{r.plan_pct}%", round(r.kpi_fix), round(r.kpi_pay),
                round(r.total),
            ])

        total = sum(r.total for r in rows)
        text = [f"<b>💰 Зарплата {period_label}</b>"]
        for r in rows:
            extra = ""
            if r.group == "poisk":
                extra = f", KPI {r.plan_pct}% (+{r.kpi_fix:,.0f}+{r.kpi_pay:,.0f})"
            text.append(f"{r.employee} [{r.group}]: <b>{r.total:,.0f}</b> ₽ "
                        f"(смен {r.shifts}, подр {r.side_pay:,.0f}{extra})")
        text.append(f"\n<b>ФОТ итого: {total:,.0f} ₽</b>")
        self.tg.send(chat_id, "\n".join(text).replace(",", " "))
        return rows


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 8. МОДУЛЬ DASHBOARD — заполнение листа DASHBOARD =================
# ──────────────────────────────────────────────────────────────────────────────
# Колонки: C — Перфильев, D — Губарев, E — Итого.  # TODO:ЛИСТ — согласовать адреса.

CELL_MAP = {
    "sales":  {"perfilev": "C5",  "gubarev": "D5",  "total": "E5"},
    "debt":   {"perfilev": "C15", "gubarev": "D15", "total": "E15"},
}


class DashboardModule:
    def __init__(self, sheets: Sheets):
        self.sheets = sheets

    def fill(self, period_label: str):
        self.sheets.set_cell(SHEETS.DASHBOARD, "B2", period_label)
        d1 = d2 = date.today()
        totals = {"sales": 0.0, "debt": 0.0}
        for base in CONFIG.BASES:
            try:
                od = OData(base)
                sales = od.sales(d1, d2)
                debt, _ = od.receivables()
            except Exception as e:
                log.error("dashboard %s: %s", base, e)
                continue
            self.sheets.set_cell(SHEETS.DASHBOARD, CELL_MAP["sales"][base], round(sales))
            self.sheets.set_cell(SHEETS.DASHBOARD, CELL_MAP["debt"][base], round(debt))
            totals["sales"] += sales
            totals["debt"] += debt
        self.sheets.set_cell(SHEETS.DASHBOARD, CELL_MAP["sales"]["total"], round(totals["sales"]))
        self.sheets.set_cell(SHEETS.DASHBOARD, CELL_MAP["debt"]["total"], round(totals["debt"]))


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 9. РОУТЕР — кто что обрабатывает ================================
# ──────────────────────────────────────────────────────────────────────────────
# Маленькая функция: смотрит на сообщение и отдаёт нужному модулю.
# Добавить новую команду = добавить одну ветку тут + метод в модуле.

HELP = (
    "<b>Команды бота</b>\n"
    "/today — отчёт из 1С за сегодня\n"
    "/range ДД.ММ ДД.ММ — отчёт за период\n"
    "/salary [подпись] — рассчитать зарплату и записать в таблицу\n"
    "/dashboard — заполнить лист DASHBOARD\n"
    "/help — эта справка\n\n"
    "В группе: «смена 25 5 100 рест.1тел:2 250» — записать смену"
)


class Router:
    def __init__(self):
        self.tg = Telegram(CONFIG.BOT_TOKEN)
        self.sheets = Sheets()
        self.shifts = ShiftsModule(self.tg, self.sheets)
        self.reports = ReportsModule(self.tg)
        self.salary = SalaryModule(self.tg, self.sheets)
        self.dashboard = DashboardModule(self.sheets)

    def is_anna(self, chat_id) -> bool:
        return str(chat_id) == str(CONFIG.ANNA_CHAT_ID)

    def handle(self, update: dict):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat = msg["chat"]
        chat_id = chat["id"]
        text = (msg.get("text") or "").strip()
        user = msg.get("from", {})
        name = (user.get("first_name", "") + " " + user.get("last_name", "")).strip() \
            or user.get("username", "без имени")

        # — Сообщения из группы: только смены —
        if chat.get("type") in ("group", "supergroup"):
            self.shifts.handle_group_message(name, text, chat_id)
            return

        # — Личка: команды (критичные — только Анне) —
        if not text:
            return
        low = text.lower()
        if low.startswith("/help") or low == "/start":
            self.tg.send(chat_id, HELP)
        elif low.startswith("/today"):
            if self.is_anna(chat_id):
                t = date.today()
                self.reports.report_period(chat_id, t, t)
        elif low.startswith("/range"):
            if self.is_anna(chat_id):
                parts = text.split()
                y = date.today().year
                d1 = parse_ddmm(parts[1], y) if len(parts) > 1 else None
                d2 = parse_ddmm(parts[2], y) if len(parts) > 2 else d1
                if d1 and d2:
                    self.reports.report_period(chat_id, d1, d2)
                else:
                    self.tg.send(chat_id, "Формат: /range 01.06 30.06")
        elif low.startswith("/salary"):
            if self.is_anna(chat_id):
                label = text.split(maxsplit=1)[1] if " " in text else date.today().strftime("%B %Y")
                self.salary.run(chat_id, label)
        elif low.startswith("/dashboard"):
            if self.is_anna(chat_id):
                self.dashboard.fill(date.today().strftime("%B %Y"))
                self.tg.send(chat_id, "DASHBOARD обновлён.")
        else:
            self.tg.send(chat_id, "Не понял команду. /help")


# ──────────────────────────────────────────────────────────────────────────────
# ===== СЕКЦИЯ 10. ЗАПУСК (polling) + SELFTEST =================================
# ──────────────────────────────────────────────────────────────────────────────

def main_loop():
    if not CONFIG.BOT_TOKEN:
        log.error("Нет BOT_TOKEN в .env — бот не запустится.")
        return
    router = Router()
    log.info("Бот запущен (polling). Ctrl+C для остановки.")
    offset = 0
    while True:
        try:
            updates = router.tg.get_updates(offset)
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    router.handle(u)
                except Exception as e:
                    log.exception("handle error: %s", e)
        except KeyboardInterrupt:
            log.info("Остановлен.")
            break
        except Exception as e:
            log.error("loop error: %s", e)
            time.sleep(3)


def selftest():
    """Отладка логики без сети: парсер смен, KPI-таблица и расчёт ЗП по группам."""
    print("== ТЕСТ ПАРСЕРА СМЕН ==")
    for s in ["смена 25 5 100 рест.1тел:2 250", "смена 12 1 3000 выходной",
              "смена 5 1 фирмы+1тел:2 будний", "привет"]:
        sh = parse_shift(s, "тест")
        print(repr(s), "->", (sh.day_type, sh.side_label, sh.side_count) if sh else None)

    print("\n== ТЕСТ KPI-ТАБЛИЦЫ «ПОИСК» (% плана -> фикс + доля) ==")
    for pct in [40, 50, 70, 100, 115, 150, 210]:
        print(f"  {pct:>4}% -> {kpi_poisk(pct)}")

    print("\n== ТЕСТ РАСЧЁТА ЗП ПО ГРУППАМ ==")
    # столбцы: день, ФИ, осн_смен, осн_сумма, подр_метка, подр_кол, подр_сумма, тип_дня
    shift_rows = [
        ["1", "Ксения Наныкина", 20, 0, "", 0, 0, "weekday"],            # поиск
        ["1", "Валерия Абрамова", 4, 0, "фирмы+1тел", 2, 0, "weekend"],  # сопровожд. выходной
        ["1", "Анна Кононенко", 21, 0, "", 0, 0, "weekday"],            # РОП
        ["1", "Владислава Герасимчук", 5, 0, "", 3, 0, "weekday"],      # Влада будни
    ]
    kpi = {"Ксения Наныкина": {"plan_fact": 231000, "payments": 800000}}
    for r in compute_salary(shift_rows, kpi):
        print(f"  {r.employee} [{r.group}]: смен {r.shifts}, база {r.base_pay:.0f}, "
              f"подр {r.side_pay:.0f}, KPI {r.plan_pct}% "
              f"(+{r.kpi_fix:.0f}+{r.kpi_pay:.0f}), ИТОГО {r.total:.0f}")
    print("\nOK. Правила — в EMPLOYEE_GROUP / SHIFT_RATE / SIDE_RATE / KPI_TABLE_POISK.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main_loop()
