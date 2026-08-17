"""Ритм заказов клиентов: отчёт в Google Sheets + задачи менеджерам в Битрикс24.

Что делает (ежедневно по будням в 11:00, cron на VPS):
  1. тянет расходные накладные из 1С (OData, обе базы) за HIST_DAYS;
  2. считает личный ритм каждого клиента — медиану интервалов между заказами,
     в ЕГО рабочих днях (дни недели, когда он вообще заказывает; иначе после
     выходных все выглядят просроченными);
  3. обновляет лист РИТМ_ЗАКАЗОВ в таблице ДЕБИТОРКА;
  4. тем, у кого срок подошёл или прошёл, ставит задачи-чек-листы менеджерам.

Маршрутизация задач (правило Анны): есть менеджер сопровождения → ему, иначе
менеджеру поиска; клиенты Абрамовой → Владиславе. Всё,
что не удалось распределить (неактивный сотрудник, «Прямой клиент», нет в
справочнике) → в задачу Анны, чтобы клиент не потерялся.

Запуск:
    python sync_rhythm.py            # dry-run: считает и печатает план
    python sync_rhythm.py --apply    # пишет лист и создаёт задачи
    python sync_rhythm.py --apply --no-tasks   # только обновить отчёт
"""

import argparse
import base64
import datetime
import json
import logging
import os
import re
import statistics
from collections import Counter, defaultdict

import gspread
import requests
import urllib3

# склейка карточек одного контрагента — общая с взаиморасчётами и дебиторкой
from sync_odata import (_TRANSFER_TAIL, group_same_client, key_tokens as _key_tokens,
                        same_client as _same_client)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

urllib3.disable_warnings()
logger = logging.getLogger(__name__)

# --- источники ---
ODATA_LOGIN = os.environ.get("ODATA_LOGIN", "api_bot")
ODATA_PASSWORD = os.environ.get("ODATA_PASSWORD", "slavaperfilev1414")
BASES = {"Перфильев": "152757", "Губарев": "64904"}

CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
SALARY_SPREADSHEET = "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"   # СПРАВОЧНИК менеджеров
DEBT_SPREADSHEET = os.environ.get("DEBT_SPREADSHEET_ID",
                                  "1uEyglRghdoEhNBS1xw63sBBiz942Rja6H15bJE2a2z4")
RHYTHM_SHEET = "РИТМ_ЗАКАЗОВ"

BITRIX_WEBHOOK = os.environ.get("BITRIX_WEBHOOK", "").rstrip("/")

# --- параметры расчёта ---
HIST_DAYS = 56     # окно истории для медианы ритма (8 недель — выбор Анны 17.08)
ACTIVE_DAYS = 45   # клиент остаётся в отчёте, пока молчит не дольше 45 дней
LOST_DAYS = 21     # молчит 3 недели и дольше → «ОТВАЛИВАЕТСЯ», отдельный статус
OVERDUE_RATIO = 1.5  # во сколько раз пропущено больше ритма → «ПРОСРОЧЕНО»
# ★17.08: порог был 21 день, и клиент, переставший заказывать, просто исчезал из
# отчёта — чем дольше молчал, тем меньше его было видно. Так терялись 26 клиентов,
# среди них Крабы Кутабы (130 тыс.), 16 тонн Пресня (88 тыс.), Милтон Грин (78 тыс.).

# --- маршрутизация задач ---
# менеджер из справочника → на кого реально ставим задачу
REROUTE = {"Валерия Абрамова": "Владислава Герасимчук"}
# исполнители в Битриксе
MANAGER_IDS = {"Анна Кононенко": 7, "Владислава Герасимчук": 17,
               "Дарья Вольнова": 15, "Ксения Наныкина": 20,
               "Алена Черкашина": 11}
FALLBACK_MANAGER = "Анна Кононенко"   # куда девать нераспределённых
SKIP_TYPES = {"Конкурент", "Закупки"}
# «Фирмы» (тип в справочнике) ведёт Анна отдельной задачей — приоритет над менеджером
FIRM_TYPE = "Фирма"
FIRM_GROUP = "ФИРМЫ"
FIRM_ASSIGNEE = "Анна Кононенко"


# ---------- 1С OData ----------

def _odata(base_id, entity):
    auth = base64.b64encode(f"{ODATA_LOGIN}:{ODATA_PASSWORD}".encode()).decode()
    url = f"https://base.42clouds.com/unf/{base_id}/odata/standard.odata/{entity}"
    out = []
    while url:
        r = requests.get(url, headers={"Authorization": "Basic " + auth},
                         verify=False, timeout=300)
        r.raise_for_status()
        data = r.json()
        out += data.get("value", [])
        url = data.get("@odata.nextLink")
    return out


def fetch_orders(today):
    """{клиент: [(дата, сумма), ...]} по всем базам.

    Тянем HIST_DAYS + ACTIVE_DAYS: у клиента, который молчит месяц, окно истории
    отсчитывается от ЕГО последнего заказа (см. compute), иначе считать ритм
    отвалившемуся было бы не по чему.
    """
    since = (today - datetime.timedelta(days=HIST_DAYS + ACTIVE_DAYS)).isoformat()
    orders, base_of = defaultdict(list), {}
    for base_name, base_id in BASES.items():
        names = {c["Ref_Key"]: (c.get("Description") or "").strip()
                 for c in _odata(base_id, "Catalog_Контрагенты?$select=Ref_Key,Description&$format=json")}
        docs = _odata(base_id, (
            "Document_РасходнаяНакладная?"
            f"$filter=Date ge datetime'{since}T00:00:00' and Posted eq true and DeletionMark eq false"
            "&$select=Date,Контрагент_Key,СуммаДокумента&$format=json"))
        logger.info("База %s: накладных %s", base_name, len(docs))
        for d in docs:
            client = names.get(d.get("Контрагент_Key"), "").strip()
            if not client:
                continue
            day = datetime.date.fromisoformat(d["Date"][:10])
            orders[client].append((day, float(d.get("СуммаДокумента") or 0)))
            base_of[client] = base_name
    return orders, base_of


# ---------- склейка карточек одного клиента ----------

def merge_cards(orders, base_of):
    """Заказы с карточек-двойников — на одного клиента.

    Клиента, переведённого между базами, в 1С заводят заново: старую карточку
    помечают «с 10.08.26 на ПЕРФИЛЬЕВ», новая начинает историю с нуля. Пока их
    считали разными, старая уходила в ПРОСРОЧЕНО (менеджеру летела задача
    «клиент пропал»), а у новой ритм считался по обрывку истории.

    Склеиваем только при однозначности: если у карточки больше одного кандидата,
    оставляем как есть — лучше лишняя строка, чем перепутанные клиенты.
    Имя и база берутся у карточки со свежим заказом (актуальной).
    """
    merged, merged_base, cards = defaultdict(list), {}, {}
    for members in group_same_client(orders).values():
        # актуальная карточка — та, где заказывали последней
        main = max(members, key=lambda n: max(d for d, _ in orders[n]))
        for n in members:
            merged[main] += orders[n]
        bases = {base_of[n] for n in members}
        merged_base[main] = base_of[main]
        if len(members) > 1:
            cards[main] = sorted(members)
            others = bases - {base_of[main]}
            if others:
                merged_base[main] = f"{base_of[main]} (был {', '.join(sorted(others))})"
            logger.info("Склеены карточки: %s ← %s", main,
                        " | ".join(n for n in members if n != main))
    return merged, merged_base, cards


# ---------- расчёт ритма ----------

def _workdays_between(a, b, weekdays):
    """Сколько «рабочих дней клиента» прошло с a по b (a не считаем)."""
    n, cur = 0, a
    while cur < b:
        cur += datetime.timedelta(days=1)
        if cur.weekday() in weekdays:
            n += 1
    return n


def compute(orders, base_of, today):
    rows = []
    for client, recs in orders.items():
        all_days = sorted({d for d, _ in recs})
        last = all_days[-1]
        if last < today - datetime.timedelta(days=ACTIVE_DAYS):
            continue                      # молчит дольше ACTIVE_DAYS — считаем ушедшим
        # окно истории отсчитываем от последнего заказа КЛИЕНТА: у того, кто молчит
        # месяц, окно «последние 8 недель от сегодня» почти пустое, и ритма бы не вышло
        window_start = last - datetime.timedelta(days=HIST_DAYS)
        days = [d for d in all_days if d >= window_start]
        recs = [(d, s) for d, s in recs if d >= window_start]
        weekdays = {d.weekday() for d in days}
        gaps = [g for g in (_workdays_between(a, b, weekdays)
                            for a, b in zip(days, days[1:])) if g > 0]
        median_gap = statistics.median(gaps) if gaps else None
        # то же в календарных днях — для человека: у клиента, берущего раз в неделю
        # по понедельникам, ритм «в его рабочих днях» равен 1, и в отчёте это путало
        cal_gaps = [(b - a).days for a, b in zip(days, days[1:]) if (b - a).days > 0]
        median_gap_days = statistics.median(cal_gaps) if cal_gaps else None
        since_last = _workdays_between(last, today, weekdays)
        ratio = (since_last / median_gap) if median_gap else None
        if (today - last).days >= LOST_DAYS:
            status = "ОТВАЛИВАЕТСЯ"       # три недели тишины — вернуть важнее, чем допродать
        elif median_gap is None:
            status = "мало данных"
        elif ratio >= OVERDUE_RATIO:
            status = "ПРОСРОЧЕНО"
        elif ratio >= 1.0:
            status = "пора заказать"
        else:
            status = "рано"
        total = sum(s for _, s in recs)
        rows.append({"client": client, "base": base_of[client], "orders": len(days),
                     "median_gap": median_gap, "median_gap_days": median_gap_days,
                     "last": last.isoformat(),
                     "since_last": since_last, "silent": (today - last).days,
                     "ratio": ratio, "status": status,
                     "total": round(total), "avg": round(total / len(days))})
    order = {"ОТВАЛИВАЕТСЯ": 0, "ПРОСРОЧЕНО": 1, "пора заказать": 2,
             "мало данных": 3, "рано": 4}
    rows.sort(key=lambda r: (order[r["status"]], -(r["ratio"] or 0), -r["total"]))
    return rows


# ---------- справочник менеджеров ----------

def _norm(s):
    s = str(s or "").replace("\xa0", " ").lower()
    s = re.sub(r"[«»\"'!,.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _brand(s):
    return _norm(re.split(r"[(\[]", str(s))[0])


def _entity(s):
    m = re.findall(r"\(([^)]*)\)", str(s))
    return _norm(m[0]) if m else ""


def short_name(s):
    return re.split(r"[(\[]", s)[0].strip() or s.strip()


def task_name(s):
    """Имя для чек-листов задач: как в 1С, ВМЕСТЕ с юр. лицом в скобках (правило
    Анны 13.08 — менеджеры не понимали, на какое юр. лицо звонить).

    Служебную пометку 1С о переводе между базами («… с 10.08.26 на ПЕРФИЛЬЕВ»)
    убираем: менеджеру она ничего не говорит, а юр. лицо в скобках остаётся.
    """
    return " ".join(_TRANSFER_TAIL.sub("", str(s)).split())


def plural(n, one, few, many):
    """«21 день», «22 дня», «25 дней» — тексты задач читают люди."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def load_directory(gc):
    """Индексы справочника для матчинга имён 1С ↔ справочник."""
    ref = gc.open_by_key(SALARY_SPREADSHEET).worksheet("СПРАВОЧНИК").get_all_values()
    by_full, by_brand, by_ent, recs = {}, defaultdict(set), defaultdict(set), {}
    for row in ref[3:]:
        if not row or not row[0].strip():
            continue
        key = row[0].strip()
        rec = (row[1].strip() if len(row) > 1 else "",
               row[2].strip() if len(row) > 2 else "",
               row[3].strip() if len(row) > 3 else "")
        recs[key] = rec
        by_full[_norm(key)] = rec
        b, e = _brand(key), _entity(key)
        if b and len(b) > 2:
            by_brand[b].add(key)
        if e and len(e) > 3:
            by_ent[e].add(key)
    return by_full, by_brand, by_ent, recs


def lookup(name, idx):
    by_full, by_brand, by_ent, recs = idx
    k = _norm(name)
    if k in by_full:
        return by_full[k]
    b, e = _brand(name), _entity(name)
    for key, table in ((b, by_brand), (e, by_ent), (b, by_ent)):
        if key in table and len(table[key]) == 1:
            return recs[next(iter(table[key]))]
    return None


def owner_of(search, support):
    manager = support or search
    if manager and "на алену" in manager.lower():
        manager = "Алена Черкашина"
    if not manager:
        return FALLBACK_MANAGER
    manager = REROUTE.get(manager, manager)
    return manager if manager in MANAGER_IDS else FALLBACK_MANAGER


def distribute(rows, idx, statuses=("ПРОСРОЧЕНО", "пора заказать")):
    """{менеджер: [клиенты]} по нужным статусам."""
    due = [r for r in rows if r["status"] in statuses]
    dist = defaultdict(list)
    for r in due:
        rec = lookup(r["client"], idx)
        if rec and rec[2] in SKIP_TYPES:
            continue
        if rec and rec[2] == FIRM_TYPE:      # фирмы — отдельной задачей, менеджер не важен
            dist[FIRM_GROUP].append(r)
            continue
        search, support = (rec[0], rec[1]) if rec else ("", "")
        dist[owner_of(search, support)].append(r)
    for lst in dist.values():
        lst.sort(key=lambda x: -(x["ratio"] or 0))
    return dist


# ---------- запись отчёта ----------

def write_report(gc, rows, today):
    sp = gc.open_by_key(DEBT_SPREADSHEET)
    existing = {ws.title: ws for ws in sp.worksheets()}
    if RHYTHM_SHEET in existing:
        sp.batch_update({"requests": [{"deleteSheet": {"sheetId": existing[RHYTHM_SHEET].id}}]})
    sp.batch_update({"requests": [{"addSheet": {"properties": {
        "title": RHYTHM_SHEET, "index": 0,
        "gridProperties": {"rowCount": len(rows) + 10, "columnCount": 9, "frozenRowCount": 3}}}}]})
    ws = sp.worksheet(RHYTHM_SHEET)
    sid = ws.id

    grid = [[f"Ритм заказов клиентов — расчёт на {today.strftime('%d.%m.%Y')}"] + [""] * 8,
            ["Ритм = типичный интервал между заказами клиента (медиана, календарные дни). "
             "Статус считается по дням недели, когда клиент вообще заказывает: "
             f"пропущено ≥ ритма → пора; ≥{OVERDUE_RATIO} ритма → просрочено; "
             f"тишина {LOST_DAYS} дн. и дольше → ОТВАЛИВАЕТСЯ. "
             f"История — {HIST_DAYS // 7} недель до последнего заказа клиента; "
             f"в отчёте все, кто заказывал за {ACTIVE_DAYS} дн. "
             "Карточки-двойники одного клиента (перевод между базами) склеены."] + [""] * 8,
            ["Клиент", "База", "Заказов", "Ритм, дн.", "Последний заказ",
             "Пропущено, дн.", "Статус", f"Сумма за {HIST_DAYS // 7} нед.", "Средний чек"]]
    for r in rows:
        # в лист пишем КАЛЕНДАРНЫЕ дни — их и читают глазами; статус при этом
        # считается по дням недели, в которые клиент вообще заказывает
        grid.append([r["client"], r["base"], r["orders"], r["median_gap_days"] or "",
                     r["last"], r["silent"], r["status"], r["total"], r["avg"]])
    sp.values_batch_update({"value_input_option": "USER_ENTERED",
                            "data": [{"range": f"'{RHYTHM_SHEET}'!A1", "values": grid}]})

    colors = {"ОТВАЛИВАЕТСЯ": (0.96, 0.80, 0.80), "ПРОСРОЧЕНО": (0.98, 0.87, 0.87),
              "пора заказать": (1.0, 0.96, 0.82), "мало данных": (0.93, 0.93, 0.93)}
    reqs = [
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 12}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2},
                        "cell": {"userEnteredFormat": {
                            "textFormat": {"italic": True,
                                           "foregroundColor": {"red": .45, "green": .45, "blue": .45}},
                            "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(textFormat,wrapStrategy)"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": 3},
                        "cell": {"userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": .87, "green": .91, "blue": .89},
                            "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(textFormat,backgroundColor,wrapStrategy)"}},
        {"setBasicFilter": {"filter": {"range": {"sheetId": sid, "startRowIndex": 2,
                                                 "endRowIndex": len(grid), "endColumnIndex": 9}}}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 3, "endRowIndex": len(grid),
                                  "startColumnIndex": 7, "endColumnIndex": 9},
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
    ]
    i = 0
    while i < len(rows):
        status = rows[i]["status"]
        j = i
        while j < len(rows) and rows[j]["status"] == status:
            j += 1
        c = colors.get(status)
        if c:
            reqs.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 3 + i, "endRowIndex": 3 + j, "endColumnIndex": 9},
                "cell": {"userEnteredFormat": {"backgroundColor": {"red": c[0], "green": c[1], "blue": c[2]}}},
                "fields": "userEnteredFormat.backgroundColor"}})
        i = j
    reqs.append({"autoResizeDimensions": {"dimensions": {
        "sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 9}}})
    sp.batch_update({"requests": reqs})
    logger.info("Отчёт обновлён: %s строк", len(rows))


# ---------- задачи в Битриксе ----------

def _bitrix(method, params):
    if not BITRIX_WEBHOOK:
        raise RuntimeError("BITRIX_WEBHOOK не задан в .env")
    r = requests.post(f"{BITRIX_WEBHOOK}/{method}.json", json=params, timeout=60)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"{method}: {data.get('error')} {data.get('error_description', '')}")
    return data.get("result")


CHUNK = 30   # пунктов в секции чек-листа; больше — бьём на несколько, чтобы все показывались


def add_checklist(tid, lines):
    if len(lines) <= CHUNK:
        for ln in lines:
            _bitrix("task.checklistitem.add", {"taskId": tid, "fields": {"TITLE": ln}})
        return
    n = (len(lines) + CHUNK - 1) // CHUNK
    for i in range(0, len(lines), CHUNK):
        part = lines[i:i + CHUNK]
        sec = _bitrix("task.checklistitem.add", {"taskId": tid, "fields": {
            "TITLE": f"Часть {i // CHUNK + 1} из {n} (позиции {i + 1}–{i + len(part)})"}})
        for ln in part:
            _bitrix("task.checklistitem.add", {"taskId": tid, "fields": {"TITLE": ln, "PARENT_ID": sec}})


def checklist_line(r):
    """Строка чек-листа. Дни — календарные: менеджер читает их глазами."""
    last = datetime.date.fromisoformat(r["last"]).strftime("%d.%m")
    gap = f"{r['median_gap_days']:.0f}" if r["median_gap_days"] else "?"
    if r["status"] == "ОТВАЛИВАЕТСЯ":
        return (f"⚠️ УХОДИТ: {task_name(r['client'])} — молчит {r['silent']} дн. "
                f"(последний заказ {last}) — брали раз в {gap} дн.")
    return (f"{task_name(r['client'])} — {r['silent']} дн. без заказа — "
            f"берут раз в {gap} дн. — последний {last}")


def create_tasks(dist, today, lost=False):
    """Одна задача на менеджера, пункты чек-листа = клиенты. Возвращает [(id, кому, n)].

    lost=True — отдельная задача по отваливающимся: клиент молчит три недели и
    дольше, разговор там не «напомнить про завтра», а «выяснить, почему ушёл».
    """
    tomorrow = (today + datetime.timedelta(days=1)).strftime("%d.%m")
    deadline = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=3))
    ).replace(hour=18, minute=0, second=0, microsecond=0).isoformat()
    created = []
    for manager, clients in sorted(dist.items(), key=lambda kv: -len(kv[1])):
        is_firms = manager == FIRM_GROUP
        uid = MANAGER_IDS.get(FIRM_ASSIGNEE if is_firms else manager)
        if not uid or not clients:
            continue
        kind = "фирмы" if is_firms else "клиентов"
        if lost:
            desc = (f"Клиенты перестали заказывать — связаться и выяснить причину, "
                    f"вернуть в работу.\n\n"
                    f"В списке {len(clients)} {kind}, молчащих {LOST_DAYS} "
                    f"{plural(LOST_DAYS, 'день', 'дня', 'дней')} и дольше (по данным 1С).\n"
                    f"Формат: клиент (юр. лицо) — сколько дней молчит — дата последнего "
                    f"заказа — как часто брали раньше.")
            title = ("Вернуть клиентов — ФИРМЫ" if is_firms else "Вернуть клиентов")
        else:
            desc = (f"Связаться с клиентами и напомнить про заказ на завтра ({tomorrow}).\n\n"
                    f"В списке {len(clients)} {kind}, выпавших из обычного ритма закупок "
                    f"(по данным 1С за {HIST_DAYS // 7} недель).\n"
                    f"Формат: клиент (юр. лицо) — дней без заказа — обычная периодичность — "
                    f"дата последнего заказа.")
            title = ("Напомнить о заказе на завтра — ФИРМЫ" if is_firms
                     else "Напомнить о заказе на завтра")
        task = _bitrix("tasks.task.add", {"fields": {
            "TITLE": f"{title} ({today.strftime('%d.%m.%Y')})",
            "RESPONSIBLE_ID": uid, "DESCRIPTION": desc, "DEADLINE": deadline,
            # завершённая задача уходит постановщику на приёмку, а не закрывается сама
            "TASK_CONTROL": "Y"}})
        tid = (task or {}).get("task", {}).get("id")
        add_checklist(tid, [checklist_line(r) for r in clients])
        logger.info("Задача #%s → %s (%s клиентов)", tid, manager, len(clients))
        created.append((tid, manager, len(clients)))
    return created


# ---------- сценарий ----------

def run(apply=False, with_tasks=True, today=None):
    today = today or datetime.date.today()
    orders, base_of = fetch_orders(today)
    orders, base_of, cards = merge_cards(orders, base_of)
    rows = compute(orders, base_of, today)
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    directory = load_directory(gc)
    dist = distribute(rows, directory)
    lost = distribute(rows, directory, statuses=("ОТВАЛИВАЕТСЯ",))

    stats = Counter(r["status"] for r in rows)
    print(f"Действующих клиентов: {len(rows)} | " +
          ", ".join(f"{k}: {v}" for k, v in stats.items()))
    if cards:
        print(f"Склеено карточек-двойников: {len(cards)} "
              f"(клиент переведён между базами — считаем одним)")
    print("Напомнить о заказе:", ", ".join(f"{m} — {len(c)}" for m, c in dist.items()) or "нет")
    print("Вернуть клиента:", ", ".join(f"{m} — {len(c)}" for m, c in lost.items()) or "нет")

    if not apply:
        print("\n(dry-run: ничего не записано, задачи не созданы — запусти с --apply)")
        return {"rows": rows, "dist": dist, "lost": lost, "created": []}

    write_report(gc, rows, today)
    created = []
    if with_tasks:
        created = create_tasks(dist, today) + create_tasks(lost, today, lost=True)
    print("Создано задач:", len(created))
    return {"rows": rows, "dist": dist, "lost": lost, "created": created}


def main():
    p = argparse.ArgumentParser(description="Ритм заказов: отчёт + задачи менеджерам")
    p.add_argument("--apply", action="store_true", help="записать отчёт и создать задачи")
    p.add_argument("--no-tasks", action="store_true", help="только обновить отчёт")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(apply=args.apply, with_tasks=not args.no_tasks)


if __name__ == "__main__":
    main()
