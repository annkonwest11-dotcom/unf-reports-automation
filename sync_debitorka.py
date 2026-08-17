"""Дебиторка по менеджерам: 2 файла из 1С -> листы в таблице ДЕБИТОРКА + задачи-чеклисты в Битриксе.

Логика (правила Анны, см. память zarplata-debitorka):
  - объединяем контрагентов из обеих баз (дубли суммируем, дни = макс);
  - тип "Конкурент"/"Закупки" -> исключаем; тип "Фирма" -> лист «Фирмы» (приоритет над менеджером);
    не нашли в справочнике -> лист «НЕ НАЙДЕНО»; иначе менеджер = сопровождение C, иначе поиск B,
    «на Алену» -> Алена, оба пусты -> «Без менеджера»;
  - таблица: СВОДКА + лист на каждого ответственного, живые формулы =SUM / ссылки из СВОДКИ;
  - задачи: просрочка > 6000; маршрутизация лист Ксении->Ксения#20, Дарьи->Дарья#15,
    Абрамовой->Владислава#17, Алены->Анна#7 (как 28.07); остальные листы задач не порождают.

Запуск:
  python deb.py               # dry-run: печатает раскладку и план задач
  python deb.py --apply       # перезаписывает листы таблицы + создаёт задачи
  python deb.py --apply --no-tasks   # только таблица
"""

import argparse
import datetime
import os
import sys
from collections import defaultdict

import gspread

sys.path.insert(0, "/Users/anna/claude-test")
try:
    from dotenv import load_dotenv
    load_dotenv("/Users/anna/claude-test/.env")
except Exception:
    pass

import openpyxl
from sync_rhythm import (_norm, lookup, load_directory, task_name, _bitrix,
                         DEBT_SPREADSHEET, CREDENTIALS_PATH)
from sync_odata import (_fetch_odata, BASES as ODATA_BASES, actual_name,
                        group_same_client)

import glob

DOWNLOADS = os.path.expanduser("~/Downloads")


def find_sources():
    """2 самые свежие выгрузки «по срокам долга» из ~/Downloads (крупная + малая база)."""
    files = glob.glob(os.path.join(DOWNLOADS, "*срокам долга*.xlsx"))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    files.sort(key=os.path.getmtime, reverse=True)
    return files[:2]
SKIP_TYPES = {"Конкурент", "Закупки"}
FIRM_TYPE = "Фирма"
SUMMARY = "СВОДКА"
FIRMS_SHEET = "Фирмы"
NOMGR_SHEET = "Без менеджера"
NOTFOUND_SHEET = "НЕ НАЙДЕНО"
KEEP_SHEETS = {"РИТМ_ЗАКАЗОВ"}          # чужой лист (ритм заказов) — не трогаем

# лист (сырой менеджер) -> (кому ставим задачу, id в Битриксе, порог просрочки ₽)
# порог 0 = берём всех должников (клиенты < 6000 тоже); Алена с порогом 6000 (список большой)
TASK_ROUTE = {
    "Ксения Наныкина":  ("Ксения Наныкина", 20, 0),
    "Дарья Вольнова":   ("Дарья Вольнова", 15, 0),
    "Валерия Абрамова": ("Владислава Герасимчук", 17, 0),
    "Алена Черкашина":  ("Алена Черкашина", 11, 6000),
}
# долги по фирмам — отдельной задачей на Анну
FIRM_TASK_ASSIGNEE = ("Анна Кононенко", 7)
# критичные долги (просрочка > порога) — отдельной сводной задачей на Анну (дублируем)
CRITICAL_ASSIGNEE = ("Анна Кононенко", 7)
CRITICAL_OVERDUE = 50000
# «непонятные» (без менеджера + не найдены в справочнике) — отдельной задачей на Анну
UNCLEAR_ASSIGNEE = ("Анна Кононенко", 7)
CHUNK = 30                              # пунктов в одной секции чек-листа (иначе бьём на несколько)

HEADERS = ["Контрагент", "Общая задолженность", "В т.ч. просроченная",
           "Срок просрочки (дней)", "До 7", "8 - 14", "15 - 30", "31 - 60", "От 61", "Тип"]


def num(v):
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def read_file(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    out = []
    for r in range(3, ws.max_row + 1):
        name = ws.cell(r, 1).value
        if not name or not str(name).strip():
            continue
        if str(name).strip().lower().startswith("итог"):
            continue
        out.append({
            "name": str(name).strip(),
            "total": num(ws.cell(r, 2).value),
            "overdue": num(ws.cell(r, 3).value),
            "days": int(num(ws.cell(r, 4).value)),
            "buckets": [num(ws.cell(r, c).value) for c in range(5, 10)],  # E..I
        })
    return out


def _join(m, rec):
    """Долг второй карточки — в ту же строку."""
    m["total"] += rec["total"]
    m["overdue"] += rec["overdue"]
    m["days"] = max(m["days"], rec["days"])
    m["buckets"] = [a + b for a, b in zip(m["buckets"], rec["buckets"])]


def combine(records):
    """Объединяем дубли: суммы складываем, дни = макс.

    Два прохода. Сперва точное совпадение имени, затем карточки одного
    контрагента, названные по-разному: клиента при переводе между базами
    заводят заново («ПУШКИН (ООО МОНЕ)» и «… с 10.08.26 на ПЕРФИЛЬЕВ»),
    держат отдельную карточку под наличные («ЮНОСТЬ (ООО ГРАНДЕ)» и
    «ГРАНДЕ (ЮНОСТЬ) НАЛ ООО») или переставляют слова. Пока их считали
    разными, долг клиента был разнесён на две строки: менеджер видел два
    мелких вместо одного крупного, часть кусков не дотягивала до порога
    задачи, а одна из карточек могла вообще уехать в «НЕ НАЙДЕНО».
    """
    merged = {}
    for rec in records:
        k = _norm(rec["name"])
        if k not in merged:
            merged[k] = {**rec, "buckets": list(rec["buckets"])}
        else:
            m = merged[k]
            _join(m, rec)
            if len(rec["name"]) > len(m["name"]):
                m["name"] = rec["name"]

    by_name = {r["name"]: r for r in merged.values()}
    out = []
    for members in group_same_client(by_name).values():
        main = by_name[actual_name(members)]
        for name in members:
            if name != main["name"]:
                _join(main, by_name[name])
                print(f"  склеены карточки: {main['name']} ← {name}")
        out.append(main)
    return out


def raw_manager(search, support):
    m = support or search
    if m and "на алену" in m.lower():
        m = "Алена Черкашина"
    return m or "Без менеджера"


def distribute(items, idx):
    """{имя_листа: [контрагенты]} + список исключённых конкурентов/закупок."""
    sheets = defaultdict(list)
    skipped = []
    for it in items:
        rec = lookup(it["name"], idx)          # (search, support, type) | None
        typ = rec[2] if rec else ""
        if rec and typ in SKIP_TYPES:
            skipped.append((it["name"], typ))
            continue
        if rec and typ == FIRM_TYPE:
            it["type"] = typ
            sheets[FIRMS_SHEET].append(it)
            continue
        if not rec:
            it["type"] = ""
            sheets[NOTFOUND_SHEET].append(it)
            continue
        it["type"] = typ
        sheets[raw_manager(rec[0], rec[1])].append(it)
    for lst in sheets.values():
        lst.sort(key=lambda x: -x["total"])
    return sheets, skipped


def sheet_order(sheets):
    """Порядок листов: СВОДКА, менеджеры по убыванию долга, Фирмы, Без менеджера, НЕ НАЙДЕНО."""
    special = {FIRMS_SHEET, NOMGR_SHEET, NOTFOUND_SHEET}
    mgrs = sorted((s for s in sheets if s not in special),
                  key=lambda s: -sum(x["total"] for x in sheets[s]))
    tail = [s for s in (FIRMS_SHEET, NOMGR_SHEET, NOTFOUND_SHEET) if s in sheets]
    return mgrs + tail


# ---------- запись таблицы ----------

def write_table(gc, sheets, order, today):
    sp = gc.open_by_key(DEBT_SPREADSHEET)
    existing = {ws.title: ws for ws in sp.worksheets()}

    # 1) удаляем старые листы дебиторки (кроме РИТМ_ЗАКАЗОВ)
    dels = [{"deleteSheet": {"sheetId": ws.id}}
            for t, ws in existing.items() if t not in KEEP_SHEETS]
    if dels:
        sp.batch_update({"requests": dels})

    # 2) создаём заново: СВОДКА + листы по порядку
    titles = [SUMMARY] + order
    add = []
    for i, t in enumerate(titles):
        rows = 2 if t == SUMMARY else len(sheets.get(t, [])) + 3
        cols = 4 if t == SUMMARY else len(HEADERS)
        add.append({"addSheet": {"properties": {
            "title": t, "index": i + 1,   # 0 занят РИТМ_ЗАКАЗОВ
            "gridProperties": {"rowCount": max(rows + 5, 10),
                                "columnCount": cols, "frozenRowCount": 1}}}})
    sp.batch_update({"requests": add})
    ws_by = {ws.title: ws for ws in sp.worksheets()}

    # 3) данные листов менеджеров/спец. + запоминаем строку ИТОГО каждого
    total_row = {}
    value_data = []
    for t in order:
        items = sheets[t]
        grid = [HEADERS]
        for it in items:
            grid.append([it["name"], it["total"], it["overdue"], it["days"],
                         *it["buckets"], it.get("type", "")])
        last = len(items) + 1                       # последняя строка данных (1-based)
        itogo = last + 1
        total_row[t] = itogo
        srange = f"A2:C{last}" if last >= 2 else None
        grid.append(["ИТОГО",
                     f"=SUM(B2:B{last})" if last >= 2 else 0,
                     f"=SUM(C2:C{last})" if last >= 2 else 0,
                     "",
                     *[f"=SUM({col}2:{col}{last})" if last >= 2 else 0
                       for col in ("E", "F", "G", "H", "I")],
                     ""])
        value_data.append({"range": f"'{t}'!A1", "values": grid})

    # 4) СВОДКА — тянет из ИТОГО каждого листа
    sgrid = [["Менеджер / лист", "Контрагентов", "Общий долг", "В т.ч. просроченный"]]
    for t in order:
        n = len(sheets[t])
        itogo = total_row[t]
        sgrid.append([t,
                      f"=COUNTA('{t}'!A2:A{itogo - 1})" if n else 0,
                      f"='{t}'!B{itogo}",
                      f"='{t}'!C{itogo}"])
    slast = len(order) + 1
    sgrid.append(["ИТОГО",
                  f"=SUM(B2:B{slast})", f"=SUM(C2:C{slast})", f"=SUM(D2:D{slast})"])
    value_data.append({"range": f"'{SUMMARY}'!A1", "values": sgrid})

    sp.values_batch_update({"value_input_option": "USER_ENTERED", "data": value_data})

    # 5) форматирование
    reqs = []
    money_cols = {"managers": (1, 9), "summary": (1, 4)}
    for t in [SUMMARY] + order:
        sid = ws_by[t].id
        # шапка жирная + фон
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": .87, "green": .91, "blue": .89}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)"}})
        # числовой формат денег
        lo, hi = money_cols["summary"] if t == SUMMARY else money_cols["managers"]
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1,
                      "startColumnIndex": lo, "endColumnIndex": hi},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
            "fields": "userEnteredFormat.numberFormat"}})
        reqs.append({"autoResizeDimensions": {"dimensions": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 10}}})
        # строка ИТОГО жирная
        if t != SUMMARY:
            ir = total_row[t]
            reqs.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": ir - 1, "endRowIndex": ir},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat"}})
    # СВОДКА: строка ИТОГО жирная
    reqs.append({"repeatCell": {
        "range": {"sheetId": ws_by[SUMMARY].id, "startRowIndex": slast, "endRowIndex": slast + 1},
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat.textFormat"}})
    sp.batch_update({"requests": reqs})


# ---------- задачи в Битриксе ----------

def checklist_line(it, firm=False):
    if firm:
        return (f"{task_name(it['name'])} — долг {round(it['total']):,} ₽ "
                f"(просроч {round(it['overdue']):,}) — {it['days']} дн.").replace(",", " ")
    return f"{task_name(it['name'])} — просроч {round(it['overdue']):,} ₽ — {it['days']} дн.".replace(",", " ")


def add_checklist(tid, lines):
    """Пункты чек-листа; если больше CHUNK — бьём на несколько секций, чтобы все показывались."""
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


def plan_tasks(sheets):
    """Список задач: по менеджерам (свой порог просрочки) + отдельная по фирмам."""
    tasks = []
    for sheet_name, (assignee, uid, thr) in TASK_ROUTE.items():
        items = [it for it in sheets.get(sheet_name, []) if it["overdue"] > thr]
        items.sort(key=lambda x: -x["overdue"])
        if items:
            tasks.append({"assignee": assignee, "uid": uid, "items": items,
                          "firm": False, "title": "Сбор просроченной задолженности"})
    firms = [it for it in sheets.get(FIRMS_SHEET, []) if it["total"] > 0]
    firms.sort(key=lambda x: -x["total"])
    if firms:
        a, u = FIRM_TASK_ASSIGNEE
        tasks.append({"assignee": a, "uid": u, "items": firms,
                      "firm": True, "title": "Долги по фирмам"})
    # критичные долги (просрочка > порога) — сводно на Анну, кроме фирм (у них своя задача)
    crit = [it for name, lst in sheets.items() if name != FIRMS_SHEET
            for it in lst if it["overdue"] > CRITICAL_OVERDUE]
    crit.sort(key=lambda x: -x["overdue"])
    if crit:
        a, u = CRITICAL_ASSIGNEE
        title = f"Критичные долги (просрочка > {CRITICAL_OVERDUE:,} ₽)".replace(",", " ")
        tasks.append({"assignee": a, "uid": u, "items": crit, "firm": False, "title": title})
    # «непонятные» — без менеджера + не найдены в справочнике — на Анну для разбора
    unclear = [it for name in (NOMGR_SHEET, NOTFOUND_SHEET)
               for it in sheets.get(name, []) if it["total"] > 0]
    unclear.sort(key=lambda x: -x["total"])
    if unclear:
        a, u = UNCLEAR_ASSIGNEE
        tasks.append({"assignee": a, "uid": u, "items": unclear, "firm": True, "noun": "клиентов",
                      "title": "Клиенты без менеджера / не найдены — разобрать",
                      "desc": "Клиенты, которых не удалось привязать к менеджеру (нет в справочнике "
                              "или без ответственного). Разобрать и назначить.\n"
                              "Формат: клиент (юр. лицо) — долг (в т.ч. просрочка) — дней просрочки."})
    return tasks


def create_tasks(tasks, today):
    deadline = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=3))
    ).replace(hour=18, minute=0, second=0, microsecond=0).isoformat()
    created = []
    for t in sorted(tasks, key=lambda x: -len(x["items"])):
        firm, items = t["firm"], t["items"]
        noun = t.get("noun", "фирм" if firm else "должников")
        desc = t.get("desc") or (
            ("Долги по фирмам.\n" if firm else "Собрать просроченную задолженность по клиентам.\n")
            + f"Всего {len(items)} {noun}.\n"
            + ("Формат: фирма (юр. лицо) — долг (в т.ч. просрочка) — дней просрочки."
               if firm else "Формат: клиент (юр. лицо) — сумма просрочки — дней просрочки."))
        task = _bitrix("tasks.task.add", {"fields": {
            "TITLE": f"{t['title']} ({today.strftime('%d.%m.%Y')})",
            "RESPONSIBLE_ID": t["uid"], "DESCRIPTION": desc,
            "DEADLINE": deadline, "TASK_CONTROL": "Y"}})
        tid = (task or {}).get("task", {}).get("id")
        lines = [checklist_line(it, firm) for it in items]
        add_checklist(tid, lines)
        sec = f" [{(len(lines) + CHUNK - 1) // CHUNK} секции]" if len(lines) > CHUNK else ""
        created.append((tid, t["assignee"], len(items), firm))
        print(f"  Задача #{tid} -> {t['assignee']} ({len(items)} {noun}){sec}")
    return created


# ---------- источник из 1С (OData) ----------
# Воспроизводит отчёт «Задолженность покупателей по срокам долга» без ручной
# выгрузки. Методика выведена сверкой с выгрузками 31.07 (perfilev 20/20,
# gubarev 305/306): долг = расходные накладные с ПОЛОЖИТЕЛЬНЫМ остатком (авансы
# и переплаты не зачитываются); возраст от даты накладной → корзины; просрочка
# только при СрокОплатыПокупателя>0 и возраст>отсрочки.

def _bucket(age):
    if age <= 7:  return 0
    if age <= 14: return 1
    if age <= 30: return 2
    if age <= 60: return 3
    return 4


def fetch_base(base_id, asof):
    """Records одной базы 1С в формате read_file: {name,total,overdue,days,buckets}."""
    names = {c["Ref_Key"]: c.get("Description", "")
             for c in _fetch_odata(base_id, "Catalog_Контрагенты")}
    ots = {d["Ref_Key"]: int(d.get("СрокОплатыПокупателя") or 0)
           for d in _fetch_odata(base_id, "Catalog_ДоговорыКонтрагентов")}
    bal = _fetch_odata(
        base_id,
        f"AccumulationRegister_РасчетыСПокупателями/Balance(Period=datetime'{asof}T00:00:00')")
    nakl = [b for b in bal if b.get("Документ_Type", "").endswith("РасходнаяНакладная")]
    # даты накладных — батчами по Ref
    refs = list({b["Документ"] for b in nakl})
    dates = {}
    for i in range(0, len(refs), 40):
        flt = " or ".join(f"Ref_Key eq guid'{r}'" for r in refs[i:i + 40])
        for d in _fetch_odata(base_id, f"Document_РасходнаяНакладная?$select=Ref_Key,Date&$filter={flt}"):
            dates[d["Ref_Key"]] = datetime.datetime.fromisoformat(d["Date"]).date()
    agg = defaultdict(lambda: {"total": 0.0, "overdue": 0.0, "days": 0, "buckets": [0.0] * 5})
    for b in nakl:
        amt = b.get("СуммаBalance", 0) or 0
        if amt <= 0:          # только положит. долг; переплата по накладной = аванс
            continue
        dt = dates.get(b["Документ"])
        if not dt:
            continue
        age = (asof - dt).days
        o = int(ots.get(b.get("Договор_Key"), 0))
        a = agg[b["Контрагент_Key"]]
        a["total"] += amt
        a["buckets"][_bucket(age)] += amt
        if o > 0 and age - o > 0:
            a["overdue"] += amt
            a["days"] = max(a["days"], age - o)
    out = []
    for k, a in agg.items():
        if round(a["total"]) <= 0:
            continue
        out.append({"name": names.get(k, k), "total": round(a["total"], 2),
                    "overdue": round(a["overdue"], 2), "days": a["days"],
                    "buckets": [round(x, 2) for x in a["buckets"]]})
    return out


def fetch_from_odata(asof):
    """Дебиторка из всех баз 1С — замена ручных xlsx."""
    records = []
    for name, cfg in ODATA_BASES.items():
        recs = fetch_base(cfg["id"], asof)
        print(f"1С/{name} ({cfg['id']}): {len(recs)} контрагентов с долгом")
        records += recs
    return records


# ---------- сценарий ----------

def run(apply=False, with_tasks=True, files=None):
    today = datetime.date.today()
    if files:                                    # запасной путь: ручные xlsx
        if len(files) < 2:
            print("Для файлового режима укажи 2 xlsx «по срокам долга».")
            return
        records = []
        for p in files:
            recs = read_file(p)
            print(f"Файл {os.path.basename(p)[:40]}… : {len(recs)} строк")
            records += recs
    else:                                        # штатно: из 1С через OData
        print(f"Тяну дебиторку из 1С на {today}…")
        records = fetch_from_odata(today)
    items = combine(records)

    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    idx = load_directory(gc)
    sheets, skipped = distribute(items, idx)
    order = sheet_order(sheets)

    print(f"\nОбъединено контрагентов: {len(items)} (исключено конкурент/закупки: {len(skipped)})")
    print("\nРаскладка по листам:")
    g_cnt = g_debt = g_over = 0
    for t in order:
        cnt = len(sheets[t])
        debt = sum(x["total"] for x in sheets[t])
        over = sum(x["overdue"] for x in sheets[t])
        g_cnt += cnt; g_debt += debt; g_over += over
        print(f"  {t:<20} {cnt:>4} контр. | долг {debt:>14,.0f} | просроч {over:>13,.0f}".replace(",", " "))
    print(f"  {'ИТОГО':<20} {g_cnt:>4} контр. | долг {g_debt:>14,.0f} | просроч {g_over:>13,.0f}".replace(",", " "))

    tasks = plan_tasks(sheets)
    print("\nПлан задач:")
    for t in sorted(tasks, key=lambda x: -len(x["items"])):
        noun = t.get("noun", "фирм" if t["firm"] else "должников")
        print(f"  {t['assignee']} (#{t['uid']}): {len(t['items'])} {noun}  — {t['title']}")
    routed = set(TASK_ROUTE) | {FIRMS_SHEET, NOMGR_SHEET, NOTFOUND_SHEET}
    orphan = [f"{t}: {n}" for t in order if t not in routed
              for n in [len([it for it in sheets[t] if it["overdue"] > 0])] if n]
    if orphan:
        print("  (без авто-задачи, есть просрочка:", ", ".join(orphan), ")")

    if not apply:
        print("\n(dry-run: ничего не записано, задачи не созданы — запусти с --apply)")
        return

    print("\nПишу таблицу…")
    write_table(gc, sheets, order, today)
    print("Таблица обновлена.")
    if with_tasks:
        print("Создаю задачи в Битриксе…")
        create_tasks(tasks, today)
    print("Готово.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-tasks", action="store_true")
    ap.add_argument("files", nargs="*", help="пути к 2 xlsx (иначе 2 свежих из ~/Downloads)")
    a = ap.parse_args()
    run(apply=a.apply, with_tasks=not a.no_tasks, files=a.files or None)
