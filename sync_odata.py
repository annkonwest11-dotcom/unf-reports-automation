"""
Синхронизация взаиморасчётов из 1С (42clouds) в Google Sheets через OData.

Заменяет сломанный sync_42clouds_v2.py (HTTP-парсинг отчёта e1cib → 404).

Источник: регистр накопления AccumulationRegister_РасчетыСПокупателями,
метод BalanceAndTurnovers() за ТЕКУЩИЙ месяц. Даёт ровно 4 колонки листа ДАННЫЕ:
  СуммаOpeningBalance  → B (долг на начало)
  СуммаReceipt         → C (отгрузка / увеличение долга)
  СуммаExpense         → D (оплаты / уменьшение долга)
  СуммаClosingBalance  → E (долг на конец)

Имена контрагентов резолвятся из Catalog_Контрагенты (Ref_Key → Description) и
совпадают с колонкой A листа ДАННЫЕ.

Поведение записи (согласовано):
  * обновляем ТОЛЬКО B:E у существующих строк, матч по имени (колонка A);
  * F (менеджеры), J (скорр.оплаты с ручными правками), БЕБИ_ЛИСТЫ — НЕ трогаем;
  * новых контрагентов (нет в листе) — дописываем в конец + сообщаем отдельно;
  * значения пишем ЧИСЛАМИ (RAW) — заодно лечит текстовый формат колонок B:E.

CLI по умолчанию — dry-run (только план, без записи). Из бота sync_all_bases()
пишет по-настоящему.
"""

import argparse
import base64
import logging
import os
import re
from collections import defaultdict
from datetime import datetime

import gspread
import requests
import urllib3
from google.oauth2.service_account import Credentials

try:  # запуск и как модуль бота, и как standalone-скрипт
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

urllib3.disable_warnings()  # verify=False на 42clouds

logger = logging.getLogger(__name__)

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Данные начинаются с 4-й строки (1 — заголовок листа, 2-3 пустые)
DATA_START_ROW = 4

BASES = {
    "perfilev": {"id": "152757", "sheet_name": "ДАННЫЕ_Перфильев"},
    "gubarev": {"id": "64904", "sheet_name": "ДАННЫЕ_Губарев"},
}

# Синонимы: имя контрагента в 1С → имя строки в листе, куда его влить.
# Это отдельные карточки 1С (ЭДО / dsbx / счёт) того же ресторана — их суммы
# складываются в одну существующую строку листа (Группа A, подтверждено вручную).
ALIASES = {
    "BURO Tsum (ООО Ресторанные Технологии) dsbx/ЭДО":
        "BURO Tsum (ООО Ресторанные Технологии) dsbx",
    "Lucky Izakaya Bar (ООО БОЛЬШАЯ НИКИТСКАЯ)":
        "БОЛЬШАЯ НИКИТСКАЯ ООО (Lucky Izakaya Bar)",
    "Sigma (ООО Мистер О) dsbx сигма": "Sigma (ООО Мистер О) dsbx",
    "БИБИРЕВО (ООО МАРУЛА)": "Бибирево ООО Марула",
    "КОФЕЙНЯ НА ПАТРИКАХ ООО": "ООО КОФЕЙНЯ НА ПАТРИКАХ адрес доставки!",
    "МАРИКА и МЕДУЗА ЛУЖНИКИ (ООО СПОРТКОРТ) ЭДО": "СПОРТКОРТ ООО ЭДО",
    "ООО ГЛАВТОРГ в 1С счет": "ООО ГЛАВТОРГ в 1С СЧЕТ!!!",
    "ТУРАНДОТ (ООО ЮСТА ЛАЙН) ЭДО": "ТУРАНДОТ (ООО ЮСТА ЛАЙН)",
    "ЦИРК (КБ БАР ООО) ": "ЦИРК (ООО КБ БАР) dsbx",
    "СЕМПРЕ (ООО БРЕЙГЕЛЬ)": "«БРЕЙГЕЛЬ» ООО",

    # ★ Разбор 2026-08-04: в 1С завели/переименовали карточки, имя перестало
    # совпадать со строкой листа → суммы никуда не попадали (за июль ~545 тыс
    # отгрузки). Это те же точки, отличается только хвост (ЭДО/счёт/«в 1С»),
    # Ё вместо Е или порядок «бренд ↔ юрлицо».
    "Made in bali МЕЙД ИН БАЛИ (ООО АБЕРДИН РОУД)":
        "Made in bali (ООО АБЕРДИН РОУД) мэйд ин бали",
    "SAVVA (ООО БРАНЧ)": "SAVVA (ООО БРАНЧ) ЭДО",
    "КАМЕЛОТ ООО (Гвидон)/ЭДО": "ГВИДОН (ООО КАМЕЛОТ) dsbx/ЭДО",
    "ЩЕПКА (ИП КОЗЫРЕВ АНДРЕЙ ЮРЬЕВИЧ)":
        "ЩЕПКА (ИП КОЗЫРЕВ АНДРЕЙ ЮРЬЕВИЧ) в 1С/ЭДО",
    "ПИЧ (ООО ПИЧ РЕСТ) ЭДО": "ПИЧ (ООО ПИЧ РЕСТ)",
    "Печь Бистро ": "ПЕЧЬ БИСТРО (ООО БИСТРО СЕРВИС)",
    "Дабл Спейс Кейтеринг ООО счет": "Дабл Спейс Кейтеринг ООО СЧЕТ!!!",
    "Зайцев Сергей Александрович Кейтеринг good chef":
        "КЕЙТЕРИНГ gold chef (ИП Зайцев Сергей Александрович)",
    "БАГЕБИ (ООО ЛАЙНИК)": "Багеби ООО Лайник",
    "БЕРЖЕВИК 2 (ООО ВОЛЬФМАН)": "БЕРЖЕВИК 2 (ООО ВОЛЬФМАН) ЭДО",
    "СЕВЕРЯНЕ (ООО ВАСИЛЁК)": "СЕВЕРЯНЕ (ООО ВАСИЛЕК)",
    "Tutto Benne ТУТТО БЕННЕ (ООО ДОННА БРУНА) счет":
        "Tutto Benne ТУТТО БЕННЕ (ООО ДОННА БРУНА) СЧЕТ!!!",
    "СТЕЙК ТВЕРСКАЯ ООО (Мясо рыба Тверская)":
        "МЯСО РЫБА ТВЕРСКАЯ (ООО СТЕЙК ТВЕРСКАЯ)",
    "ЛУМИ (ООО ПВБ СОЛНЦЕ)": "ЛУМИ (ООО ПВБ СОЛНЦЕ) в 1С",
    # Анна 05.08: ИП Софронова и ООО Жуль Занг — РАЗНЫЕ юрлица одной точки, у каждого
    # своя строка в листе. Раньше алиас сливал ИП в строку ООО → деньги ИП считались
    # дважды (в строке ООО и старым остатком в строке ИП). Теперь ИП идёт в свою строку.
    "Jules Zang ЖУЛЬ ЗАНГ (ИП Софронова Я.М.) счет":
        "Jules Zang (ИП Софронова Я.М.)!!!СЧЕТ!!!",
    "NAIOLI (ООО НАЙОЛИ)": "NAIOLI (ООО НАЙОЛИ) ЭДО",
    "ООО \"АЙТИБ\" НЕ ВЕРНЫЙ": "ООО \"АЙТИБ\"",
    "ЛЯ МАРЭ ПЕТРОВКА (ООО ША-ДЭ) НЕ ВЕРНЫЙ ЕСТЬ 2":
        "ЛЯ МАРЭ ПЕТРОВКА (ООО ША-ДЭ)",
    "Ферменто (ИП Кудюков)": "ФЕРМЕНТО (ИП КУДЮКОВ МАКСИМ АНАТОЛЬЕВИЧ)",
    "Облако (Ип Белов М.С.)": "ОБЛАКО (ИП БЕЛОВ МАКСИМ СЕРГЕЕВИЧ)",
    "БРЕЙГЕЛЬ ООО (Семпре)": "«БРЕЙГЕЛЬ» ООО",
    # Анна 04.08: та же точка, что Мун Лаунж (одно юрлицо) — вливаем.
    "МУНТЕРРА (ООО МУНТЕРРА ГРУПП)": "МУН ЛАУНЖ ООО ( МУНТЕРРА ГРУПП)",

    # ★ 05.08: карточки Ксении, переименованные в 1С — суммы не попадали в лист
    # (нашлось при сборке её файла взаиморасчётов: 14 511 + 20 881 = 35 392).
    "The Caters ИП ДМИТРИЕВ ЕВГЕНИЙ НИКОЛАЕВИЧ зе катерс":
        "The Caters (ИП ДМИТРИЕВ ЕВГЕНИЙ НИКОЛАЕВИЧ)",
    "ГВИДОН (ООО КАМЕЛОТ) ЭДО": "ГВИДОН (ООО КАМЕЛОТ) dsbx/ЭДО",
    # карточку переименовали в 1С (Варварка → Варкарка), оплаты не доходили до строки
    "ВАРКАРКА (ООО НОВЫЙ АТРИУМ)": "НОВЫЙ АТРИУМ ООО (ВАРВАРКА)",
}

# Контрагенты 1С, которые полностью игнорируем (не обновляем и не дописываем).
# Бывшая Группа B разобрана (2026-07-23): Дабл Спейс→Дарья, ФУД СОЛЮШНС→Прямой,
# Вилла Паста (ФОРТУНА)→новый клиент Ксении — все заведены в лист+СПРАВОЧНИК,
# синк теперь обновляет их как обычно. Остался телефонный мусор и служебные
# карточки водителей/логистов/переводов (2026-08-04) — это не клиенты.
SKIP_CONTRACTORS = {
    "+79299588161 коллеги",
    "Артур водитель",
    "Никита логист",
}


# ─── Расчётный период (НАСТРОЙКИ!B4) vs календарь ──────────────────────────────
# Синк пишет данные того месяца, который сейчас РАССЧИТЫВАЕТСЯ (НАСТРОЙКИ!B4), а не
# просто текущего календарного. Пока Анна не закрыла месяц (B4 = «Июль 2026», а на
# дворе август) — живой лист остаётся июльским, а новый месяц копится в отдельном
# листе ДАННЫЕ_*_СЛЕД (тот же приём, что и СМЕНЫ_СЛЕД). archive_month при закрытии
# переносит _СЛЕД → живой лист.

SUFFIX_NEXT = "_СЛЕД"

_RU_MONTHS_NUM = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11,
    "декабрь": 12,
}


def _parse_settings_period(spreadsheet):
    """(year, month) из НАСТРОЙКИ!B4 ('Июль 2026'); None если не распознать."""
    try:
        raw = (spreadsheet.worksheet("НАСТРОЙКИ").acell("B4").value or "").strip().lower()
    except Exception:
        logger.exception("Не удалось прочитать НАСТРОЙКИ!B4")
        return None
    parts = raw.split()
    month = next((_RU_MONTHS_NUM[p] for p in parts if p in _RU_MONTHS_NUM), None)
    year = next((int(p) for p in parts if p.isdigit() and len(p) == 4), None)
    if not month or not year:
        return None
    return year, month


def resolve_mode(spreadsheet, today=None):
    """Как синкать, исходя из расчётного периода НАСТРОЙКИ!B4 vs календаря.

      normal  — календарь == расчётный период: пишем ЖИВОЙ лист за расчётный месяц
                (обычное поведение, как было до нахлёста);
      overlap — календарь ушёл вперёд, месяц ещё не закрыт: ЖИВОЙ лист НЕ трогаем,
                текущий календарный месяц копим в <лист>_СЛЕД.

    Возвращает dict: mode, month_date (дата внутри целевого месяца — для запроса
    OData через _current_month_period), suffix (""|"_СЛЕД"), period_label."""
    today = today or datetime.now()
    pp = _parse_settings_period(spreadsheet)
    if not pp:
        logger.warning("НАСТРОЙКИ!B4 не распознан — синк за текущий месяц (normal)")
        return {"mode": "normal", "month_date": today, "suffix": "",
                "period_label": today.strftime("%Y-%m")}
    py, pm = pp
    if (today.year, today.month) == (py, pm):
        return {"mode": "normal", "month_date": today, "suffix": "",
                "period_label": f"{py}-{pm:02d}"}
    if (today.year, today.month) > (py, pm):
        return {"mode": "overlap", "month_date": today, "suffix": SUFFIX_NEXT,
                "period_label": f"{today.year}-{today.month:02d} → _СЛЕД "
                                f"(расчётный {py}-{pm:02d} не закрыт)"}
    # расчётный период впереди календаря — не должно случаться; безопасный дефолт
    logger.warning("Расчётный период %r впереди календаря %s — normal fallback",
                   pp, today.strftime("%Y-%m"))
    return {"mode": "normal", "month_date": today, "suffix": "",
            "period_label": today.strftime("%Y-%m")}


# ─── OData ────────────────────────────────────────────────────────────────────

def _auth_headers():
    creds = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def _base_url(base_id):
    return f"https://base.42clouds.com/unf/{base_id}/odata/standard.odata/"


def _fetch_odata(base_id, entity):
    """Тянет сущность OData целиком, разворачивая пагинацию @odata.nextLink."""
    url = _base_url(base_id) + entity
    url += ("&" if "?" in url else "?") + "$format=json"
    headers = _auth_headers()
    out = []
    while url:
        resp = requests.get(url, headers=headers, timeout=60, verify=False)
        if resp.status_code != 200:
            raise RuntimeError(
                f"OData {resp.status_code} для {entity[:60]} (база {base_id})"
            )
        data = resp.json()
        out.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return out


def _current_month_period(today=None):
    """(StartPeriod, EndPeriod) как datetime-литералы OData: 1-е число этого и
    1-е число следующего месяца."""
    today = today or datetime.now()
    start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    fmt = "datetime'%Y-%m-%dT00:00:00'"
    return start.strftime(fmt), end.strftime(fmt)


def _contractor_names(base_id):
    names = {}
    for c in _fetch_odata(base_id, "Catalog_Контрагенты"):
        names[c.get("Ref_Key")] = c.get("Description", "")
    return names


def aggregate_balances(rows):
    """BalanceAndTurnovers отдаёт строки в разрезе договор/документ — суммируем
    по Контрагент_Key. Возвращает {ctg_key: [open, receipt, expense, close]}."""
    agg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for r in rows:
        k = r.get("Контрагент_Key")
        agg[k][0] += r.get("СуммаOpeningBalance", 0) or 0
        agg[k][1] += r.get("СуммаReceipt", 0) or 0
        agg[k][2] += r.get("СуммаExpense", 0) or 0
        agg[k][3] += r.get("СуммаClosingBalance", 0) or 0
    return agg


def fetch_base_balances(base_id, today=None):
    """Возвращает {имя_контрагента: [open, receipt, expense, close]} за текущий
    месяц, только контрагенты с ненулевыми движениями/остатком."""
    start, end = _current_month_period(today)
    entity = (
        "AccumulationRegister_РасчетыСПокупателями/BalanceAndTurnovers("
        f"StartPeriod={start},EndPeriod={end})"
    )
    rows = _fetch_odata(base_id, entity)
    agg = aggregate_balances(rows)
    names = _contractor_names(base_id)
    result = {}
    for key, vals in agg.items():
        if not any(vals):
            continue
        name = names.get(key)
        if not name:
            continue
        result[name] = [round(v, 2) for v in vals]
    logger.info("База %s: %d контрагентов с движениями", base_id, len(result))
    return result


# ─── Матчинг с листом ─────────────────────────────────────────────────────────

def norm_name(s):
    """Нормализация имени для матчинга: схлопнуть пробелы, убрать края, lower.
    Устойчиво к двойным пробелам и хвостовым пробелам в СПРАВОЧНИК/1С."""
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def plan_updates(sheet_col_a, odata_balances, aliases=None, skip=None):
    """Составляет план записи, сопоставляя данные OData со строками листа.

    sheet_col_a — список значений колонки A начиная с DATA_START_ROW (строка N →
    индекс N-DATA_START_ROW). odata_balances — {имя: [b,c,d,e]}.

    aliases — {имя_1С: имя_строки_листа} для карточек, которые надо влить в уже
    существующую строку (суммируются, если на одну строку легло несколько).
    skip — множество имён 1С, которые полностью игнорируются.

    Возвращает (updates, new_clients):
      updates     — [(row_number, [b,c,d,e]), ...] для существующих строк (суммы);
      new_clients — [(имя, [b,c,d,e]), ...] которых нет в листе.
    """
    aliases = ALIASES if aliases is None else aliases
    skip = SKIP_CONTRACTORS if skip is None else skip
    skip_norm = {norm_name(s) for s in skip}
    alias_norm = {norm_name(k): v for k, v in aliases.items()}

    index = {}
    for i, name in enumerate(sheet_col_a):
        key = norm_name(name)
        if key and key not in index:  # первая (рабочая) строка при дублях
            index[key] = DATA_START_ROW + i

    row_sums = {}  # row → [b,c,d,e] (аккумулятор)
    new_clients = []
    for name, vals in odata_balances.items():
        nn = norm_name(name)
        if nn in skip_norm:
            continue
        target = norm_name(alias_norm[nn]) if nn in alias_norm else nn
        row = index.get(target)
        if row is not None:
            acc = row_sums.setdefault(row, [0.0, 0.0, 0.0, 0.0])
            for j in range(4):
                acc[j] += vals[j]
        else:
            new_clients.append((name, vals))

    updates = sorted((row, [round(v, 2) for v in acc])
                     for row, acc in row_sums.items())
    new_clients.sort()
    return updates, new_clients


# ─── Запись в Google Sheets ───────────────────────────────────────────────────

# РОП-оборот: сумма регистра «Продажи» (СуммаTurnover) за текущий месяц по обеим
# базам пишется в жёлтую ячейку оборота блока РОП СВОДНОЙ (Блок 3 «Факт — оборот»).
SUMMARY_SHEET = "СВОДНАЯ_ЗП"
OBOROT_CELL = "E88"          # Блок 3 РОП «Факт — оборот» (после удаления Ии 23.07)
# %плана РОП (вычисленные) для мини-отчёта: новые продажи / оборот / поступления
ROP_PCT_CELLS = ("C84", "C89", "C93")


def fetch_oborot(base_id, today=None):
    """Оборот (выручка) базы за текущий месяц = сумма СуммаTurnover регистра
    AccumulationRegister_Продажи. Сходится с отчётом «Продажи» 1С."""
    start, end = _current_month_period(today)
    entity = (
        "AccumulationRegister_Продажи/Turnovers("
        f"StartPeriod={start},EndPeriod={end})"
    )
    rows = _fetch_odata(base_id, entity)
    total = sum(float(r.get("СуммаTurnover", 0) or 0) for r in rows)
    logger.info("База %s: оборот (Продажи) = %.2f", base_id, total)
    return round(total, 2)


def sync_oborot(dry_run=False, today=None):
    """Суммарный оборот обеих баз → СВОДНАЯ_ЗП!E88 (Блок 3 РОП). Возвращает сумму.

    В режиме нахлёста (месяц не закрыт) E88 НЕ трогаем — оборот расчётного месяца
    заморожен до закрытия; возвращаем справочный оборот текущего календарного."""
    ss = _open_spreadsheet()
    info = resolve_mode(ss, today)
    total = round(sum(fetch_oborot(cfg["id"], info["month_date"])
                      for cfg in BASES.values()), 2)
    logger.info("РОП оборот (Перф+Губ) = %.2f [режим=%s]", total, info["mode"])
    if info["mode"] == "overlap":
        logger.info("Период %s не закрыт — E88 не трогаю (заморозка)",
                    info["period_label"])
        return total
    if not dry_run:
        ss.worksheet(SUMMARY_SHEET).update(
            [[total]], OBOROT_CELL, value_input_option="RAW"
        )
        logger.info("Записан оборот в %s!%s", SUMMARY_SHEET, OBOROT_CELL)
    return total


def oborot_report(today=None):
    """Ежедневный отчёт РОП: пишет оборот (E88, из 1С Продажи) и поступления
    (E92, из ADesk), возвращает суммы, %плана (новые/оборот/поступления) и ссылку.
    Поступления недоступны (нет токена / ошибка ADesk) — не срывают оборот."""
    ss = _open_spreadsheet()
    info = resolve_mode(ss, today)
    md = info["month_date"]
    total = round(sum(fetch_oborot(cfg["id"], md) for cfg in BASES.values()), 2)
    postup = None
    try:
        from sync_adesk import fetch_postupleniya, POSTUP_CELL
        postup = fetch_postupleniya(md)
    except Exception:
        logger.exception("ADesk поступления недоступны — пишу только оборот")

    sv = ss.worksheet(SUMMARY_SHEET)
    frozen = info["mode"] == "overlap"
    if frozen:
        # месяц не закрыт — E88/E92 расчётного месяца заморожены, не перезаписываем;
        # oborot/postup ниже — справочные суммы текущего календарного месяца
        logger.info("РОП заморожен: период %s не закрыт (справочно оборот=%.2f)",
                    info["period_label"], total)
    else:
        updates = [{"range": OBOROT_CELL, "values": [[total]]}]
        if postup is not None:
            updates.append({"range": POSTUP_CELL, "values": [[postup]]})
        sv.batch_update(updates, value_input_option="RAW")
    got = sv.batch_get(list(ROP_PCT_CELLS))

    def cell(res):
        try:
            return res[0][0]
        except Exception:
            return "—"

    return {
        "frozen": frozen,
        "period": info["period_label"],
        "oborot": total,
        "postup": postup,
        "pct_new": cell(got[0]),
        "pct_oborot": cell(got[1]),
        "pct_postup": cell(got[2]),
        "url": f"https://docs.google.com/spreadsheets/d/{ss.id}/edit#gid={sv.id}",
    }


def _open_spreadsheet(gc=None):
    if gc is None:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        gc = gspread.authorize(creds)
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID не задан в окружении")
    return gc.open_by_key(SPREADSHEET_ID)


def sync_base(spreadsheet, sheet_name, base_id, dry_run=True, append_new=False,
              today=None, create_if_missing=False, template_sheet=None):
    balances = fetch_base_balances(base_id, today=today)
    try:
        ws = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        if not create_if_missing:
            raise
        base_ws = spreadsheet.worksheet(template_sheet or sheet_name)
        if dry_run:
            # в dry-run временный лист не создаём — план матчим по шаблону (живому)
            ws = base_ws
            logger.info("[dry-run] лист %s отсутствует — план по шаблону %s",
                        sheet_name, base_ws.title)
        else:
            ws = spreadsheet.duplicate_sheet(base_ws.id, new_sheet_name=sheet_name)
            # новый месяц: обороты/остатки обнуляем (A — контрагенты, F:L — формулы
            # ВПР менеджеров/типа — сохраняем из копии живого листа)
            last = max(len(ws.col_values(1)), DATA_START_ROW)
            ws.batch_clear([f"B{DATA_START_ROW}:E{last}"])
            logger.info("Создан лист %s (копия %s), B:E очищены",
                        sheet_name, base_ws.title)
    col_a = ws.col_values(1)[DATA_START_ROW - 1 :]  # от строки 4 вниз
    updates, new_clients = plan_updates(col_a, balances)

    logger.info(
        "%s: обновить %d, несматчено %d (append_new=%s)",
        sheet_name, len(updates), len(new_clients), append_new,
    )
    for name, vals in new_clients:
        logger.info("  НЕ В ЛИСТЕ: %s %s", name, vals)

    if not dry_run:
        # существующие: один batch на весь лист (B:E), числами (RAW)
        if updates:
            batch = [
                {"range": f"B{row}:E{row}", "values": [vals]}
                for row, vals in updates
            ]
            ws.batch_update(batch, value_input_option="RAW")

        # несматченные дописываем в конец ТОЛЬКО по явному append_new
        # (по умолчанию НЕ дописываем — многие это варианты написания уже
        #  существующих строк, слепая дозапись даст дубли и двойной счёт)
        if append_new and new_clients:
            first_empty = len(ws.col_values(1)) + 1
            rows = [[name] + vals for name, vals in new_clients]
            ws.update(
                rows,
                f"A{first_empty}:E{first_empty + len(rows) - 1}",
                value_input_option="RAW",
            )

    return {"updates": len(updates), "new": len(new_clients),
            "new_names": [n for n, _ in new_clients]}


def sync_all_bases(dry_run=False, append_new=False, today=None):
    """Синхронизировать обе базы. Из бота вызывается с dry_run=False.

    append_new=False (по умолчанию): обновляем только совпавшие по имени строки,
    несматченных контрагентов лишь возвращаем в сводке (не дописываем)."""
    spreadsheet = _open_spreadsheet()
    info = resolve_mode(spreadsheet, today)
    logger.info("Старт OData-синка: режим=%s, период=%s (dry_run=%s, append_new=%s)",
                info["mode"], info["period_label"], dry_run, append_new)
    summary = {"_mode": info["mode"], "_period": info["period_label"]}
    for base_name, cfg in BASES.items():
        logger.info("Обработка %s...", base_name)
        target = cfg["sheet_name"] + info["suffix"]
        summary[base_name] = sync_base(
            spreadsheet, target, cfg["id"],
            dry_run=dry_run, append_new=append_new, today=info["month_date"],
            create_if_missing=(info["suffix"] != ""),
            template_sheet=cfg["sheet_name"],
        )
    logger.info("OData-синк завершён: %s", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OData-синк 1С → Google Sheets")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="реально записать в таблицу (по умолчанию только показать план)",
    )
    parser.add_argument(
        "--append-new",
        action="store_true",
        help="дописывать несматченных контрагентов в конец листа (осторожно: "
             "многие — варианты написания уже существующих строк)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    result = sync_all_bases(dry_run=not args.apply, append_new=args.append_new)
    print("\n=== ИТОГ ===")
    print(f"режим: {result.get('_mode')}  период: {result.get('_period')}")
    for base, s in result.items():
        if base.startswith("_"):
            continue
        print(f"{base}: обновить {s['updates']}, не в листе {s['new']}")
        for n in s["new_names"]:
            print(f"    не в листе: {n}")
    if not args.apply:
        print("\n(dry-run — ничего не записано; запусти с --apply чтобы применить)")
