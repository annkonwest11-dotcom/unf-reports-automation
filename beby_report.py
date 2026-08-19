#!/usr/bin/env python3
"""Отчёт по беби-листам: «купили» (накладные) vs «продали» (1С) за период.

Таблица «аналитика беби» (Анна): лист на месяц, слева блоки накладных (A дата,
B позиция, C кол-во, D сумма), справа отчёт по периодам — «купили»/«продали»
в штуках и рублях, ниже выручка/налоги/логистика/прибыль.

Что делает скрипт:
  «продали» — регистр AccumulationRegister_Продажи 1С по группе «Беби листы»
              (обе базы), КоличествоTurnover + СуммаTurnover. Сверено с ручным
              отчётом за 31.07-03.08: сошлось 1:1 по всем позициям.
  «купили»  — из блоков накладных того же листа. Товар, привезённый в день X,
              продаётся с X+1, поэтому в период [d1..d2] попадают накладные
              с датами [d1-1 .. d2-1] (правило выведено из июля: период
              «07-20 июля» = накладные 06/09/13/16.07).

Запуск:
    venv/bin/python beby_report.py --from 04.08 --to 13.08
    venv/bin/python beby_report.py --from 04.08 --to 13.08 --sheet август
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import gspread

sys.path.insert(0, "/Users/anna/claude-test")
import beby_invoice
from sync_odata import BASES, _fetch_odata
from sync_rhythm import CREDENTIALS_PATH

SPREADSHEET = "1l-znGUP6LspsGM391FBII9r54dIFlniiq7dZFvopvTs"   # «аналитика беби»
GROUP = "Беби листы"          # группа номенклатуры 1С
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь",
          "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# Один вид = один ключ. Слева regex по очищенному имени (без «беби лист»/«100 гр»),
# справа ключ + как показывать в отчёте. Порядок важен: уточнённые виды раньше общих.
# «Мизуна»/«Мангольд» без цвета = красная/алый — так их пишут в накладных (сверено
# по цене: мангольд 190 ₽/шт = «Мангольд алый» в 1С).
RULES = [
    # ★в накладной «Салатный микс», в 1С и в листе «Микс» (18.08) — без этого
    # закупка и продажа микса считались разными позициями, а в сводке листа
    # появлялась лишняя строка-двойник
    (r"^(салатн\w*\s+)?микс",       ("микс", "Микс")),
    # ★в накладных цвет пишут одной буквой: «Пакчой к» / «Пакчой з» (18.08).
    # Без этого «Пакчой к» падал в общее правило и уезжал в зелёный.
    (r"^пак\s*чой\s*(крас|red|к\b)",  ("пакчой_крас", "Пак чой красный")),
    (r"^пак\s*чой",                ("пакчой_зел", "Пак чой зеленый")),
    (r"^мизуна\s*(зел|з\b)",       ("мизуна_зел", "Мизуна зелёная")),
    (r"^мизуна",                   ("мизуна_крас", "Мизуна красная")),
    (r"^мангольд\s*(зел|з\b)",     ("мангольд_зел", "Мангольд зелёный")),
    (r"^мангольд\s*(борд|б\b)",    ("мангольд_борд", "Мангольд бордо")),
    (r"^мангольд",                 ("мангольд_алый", "Мангольд алый")),
    (r"^рук+ола",                  ("рукола", "Рукола")),
    (r"^кейл",                     ("кейл", "Кейл")),
    # айсберг = фриллис, одно и то же (Анна 13.08); в 1С отдельной карточки нет,
    # поставщик пишет «Айсберг», в 1С он оприходован как «Беби лист Фриллис»
    (r"^(фриллис|айсберг)",        ("фриллис", "Фриллис")),
    (r"^романо",                   ("романо", "Романо")),
    (r"^щавел",                    ("щавель", "Щавель")),
    (r"^шпинат",                   ("шпинат", "Шпинат")),
    (r"^шисо",                     ("шисо", "Шисо")),
    (r"^горчиц",                   ("горчица", "Горчица")),
    (r"^базилик",                  ("базилик", "Базилик")),
    (r"^вербена",                  ("вербена", "Вербена")),
]


def canon_pos(name):
    """Название позиции (из 1С или из накладной) → (ключ, отображаемое имя)."""
    s = str(name).lower().replace("ё", "е")
    s = re.sub(r"беби\s*лист|100\s*гр|[,.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pat, val in RULES:
        if re.match(pat, s):
            return val
    return s, str(name).strip()


def parse_day(s, year):
    """«04.08» / «2026-08-04» / «4 августа» → date."""
    s = str(s).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m"):
        try:
            d = datetime.strptime(s, fmt).date()
            return d.replace(year=year) if fmt == "%d.%m" else d
        except ValueError:
            continue
    raise ValueError(f"не понимаю дату {s!r} — нужен формат ДД.ММ")


def read_invoices(ws, year):
    """[(дата, позиция, кол-во, сумма)] из левого блока листа."""
    out, cur = [], None
    # ★UNFORMATTED_VALUE: иначе формат ячейки подменяет число — у шпината стоял
    # процентный формат, и 10 пачек читались как 1000 (18.08)
    for row in ws.get("A1:D400", value_render_option="UNFORMATTED_VALUE"):
        row = (row + [""] * 4)[:4]
        a, b, c, d = (str(x).strip() for x in row)
        if a and re.match(r"^\d{1,2}[.,]\d{1,2}", a):
            cur = parse_day(a.replace(",", "."), year)
        if not b or b.lower().startswith("итого") or b.lower() == "позиция":
            continue
        if cur is None:
            continue
        out.append((cur, b, _num(c), _num(d)))
    return out


def _num(v):
    s = str(v).replace("\xa0", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def invoice_dates(ws, year):
    """Отсортированные даты накладных листа."""
    return sorted({dt for dt, *_ in read_invoices(ws, year)})


def read_blocks(ws):
    """Блоки отчёта из правой части: [{label, top, itog, rows:{ключ: [...]}}].

    В rows на позицию: [куп.кол, прод.кол, куп.сумма, прод.сумма, списали, остаток]."""
    grid = ws.get("L1:R400", value_render_option="UNFORMATTED_VALUE")
    blocks, cur = [], None
    for i, row in enumerate(grid, 1):
        row = (list(row) + [""] * 7)[:7]
        head = str(row[0]).strip()
        if not head and not any(str(c).strip() for c in row):
            continue
        if head and not any(str(c).strip() for c in row[1:]):     # заголовок блока
            cur = {"label": head, "top": i, "itog": None, "rows": {}, "rownos": {},
                   "start_row": None}
            blocks.append(cur)
            continue
        if cur is None or head in ("", "купили"):
            continue
        if head == "итог:":
            cur["itog"] = i
            continue
        if head.startswith(("Недо", "Расхожд", "Выруч", "Заработ", "Минус",
                            "Прибыль", "Рентаб")):
            continue
        if head.startswith("было на начало"):
            cur["start_row"] = i
            continue
        k, _ = canon_pos(head)
        cur["rows"][k] = [_num(x) for x in row[1:7]]
        cur["rownos"][k] = i
    return blocks


def last_remains(ws):
    """{ключ: остаток пачек} из последнего блока листа — что физически осталось.

    Берём то, что стоит в колонке R (ручная правка Анны в приоритете); если пусто —
    считаем расчётно: купили − продали − списали."""
    blocks = [b for b in read_blocks(ws) if b["rows"]]
    if not blocks:
        return {}
    last = blocks[-1]
    out = {}
    for k, v in last["rows"].items():
        kq, sq, _ks, _ss, spis, rest = v
        out[k] = rest if rest else max(kq - sq - spis, 0)
    return out


def fetch_sold(d1, d2):
    """{ключ позиции: [кол-во, сумма]} — продажи 1С за [d1..d2] включительно."""
    fmt = "datetime'%sT00:00:00'"
    start, end = fmt % d1.isoformat(), fmt % (d2 + timedelta(days=1)).isoformat()
    agg, titles = defaultdict(lambda: [0.0, 0.0]), {}
    for cfg in BASES.values():
        nom = _fetch_odata(cfg["id"], "Catalog_Номенклатура")
        folders = {n["Ref_Key"]: n.get("Description", "") for n in nom if n.get("IsFolder")}
        names = {n["Ref_Key"]: (n.get("Description", ""), folders.get(n.get("Parent_Key"), ""))
                 for n in nom if not n.get("IsFolder")}
        rows = _fetch_odata(cfg["id"], "AccumulationRegister_Продажи/Turnovers("
                                       f"StartPeriod={start},EndPeriod={end})")
        for r in rows:
            nm, grp = names.get(r.get("Номенклатура_Key"), ("", ""))
            if grp != GROUP:
                continue
            k, title = canon_pos(nm)
            titles.setdefault(k, title)
            agg[k][0] += float(r.get("КоличествоTurnover", 0) or 0)
            agg[k][1] += float(r.get("СуммаTurnover", 0) or 0)
    return agg, titles


def build(sheet, d1, d2, shift=1):
    """Отчёт за период: {ключ: [куп.кол, куп.сумма, прод.кол, прод.сумма]}."""
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    sp = gc.open_by_key(SPREADSHEET)
    ws = sp.worksheet(sheet)
    inv = read_invoices(ws, d1.year)

    # накладные периода: привезли за день до продажи
    b1, b2 = d1 - timedelta(days=shift), d2 - timedelta(days=shift)
    rep, titles = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]), {}
    used = []
    for dt, pos, qty, summ in inv:
        if b1 <= dt <= b2:
            k, title = canon_pos(pos)
            titles.setdefault(k, title)
            rep[k][0] += qty
            rep[k][1] += summ
            used.append(dt)
    sold, stitles = fetch_sold(d1, d2)
    for k, (q, s) in sold.items():
        titles.setdefault(k, stitles.get(k, k))

        rep[k][2] += q
        rep[k][3] += s
    return rep, titles, sorted(set(used)), ws


def write_block(ws, label, rows, logistics=1000, start_qty=0):
    """Дописывает блок отчёта в правую часть листа (L:R), как это делает Анна вручную.

    rows: [(имя, куп.кол, куп.сумма, прод.кол, прод.сумма, остаток)] в нужном порядке.
    Q «списали» оставляем пустой — это ручной ввод Анны; R «на остатке» пишем расчётный
    (прошлый остаток + купили − продали), её ручная правка не перетирается: следующий
    расчёт берёт то, что стоит в R."""
    used = ws.get("L1:R400")
    last = max((i for i, r in enumerate(used, 1) if any(str(c).strip() for c in r)), default=0)
    top = last + 3                                   # две пустые строки между блоками
    first, lastpos = top + 2, top + 1 + len(rows)
    grid = [[label] + [""] * 6,
            ["", "купили", "продали", "купили", "продали", "списали", "на остатке:"]]
    for row in rows:
        name, kq, ks, sq, ss = row[:5]
        rest = row[5] if len(row) > 5 else ""
        grid.append([name, kq, sq, ks, ss, "", rest])
    grid.append(["итог:"] + [f"=SUM({c}{first}:{c}{lastpos})" for c in "MNOP"] +
                [f"=SUM({c}{first}:{c}{lastpos})" for c in "QR"])
    t = lastpos + 1                                  # строка «итог:»
    grid.append(["было на начало:", start_qty, "пачек", "", "", "", ""])
    grid.append([])
    # ★18.08 (решение Анны «вести остатки честно»): баланс склада, а не «купили −
    # продали». Прежняя формула не знала про переходящий запас и уходила в минус
    # ровно на его величину. В норме здесь 0; число появляется, если товар пропал
    # мимо списаний или остаток поправили руками после пересчёта.
    grid.append(["Расхождение (проверка):",
                 f"=M{t + 1}+M{t}-N{t}-Q{t}-R{t}", "пачки", "", "", "", ""])
    grid.append([])
    grid.append(["Выручка (оборот)", f"=P{t}", "", "", "", "", ""])
    grid.append(["Минус налоги 11%", f"=P{t}*0,11", "", "", "", "", ""])
    grid.append(["Минус логистика", logistics, "", "", "", "", ""])
    v = t + 5                                        # строка «Выручка» (ниже «было на начало»)
    grid.append(["Прибыль:", f"=M{v}-M{v + 1}-M{v + 2}-O{t}", "", "", "", "", ""])
    grid.append(["Рентабельность", f"=M{v + 3}/M{v}", "", "", "", "", ""])
    ws.spreadsheet.values_batch_update({"value_input_option": "USER_ENTERED", "data": [
        {"range": f"'{ws.title}'!L{top}", "values": grid}]})

    sid, reqs = ws.id, []
    reqs.append({"repeatCell": {                     # заголовок периода — красный, крупный
        "range": {"sheetId": sid, "startRowIndex": top - 1, "endRowIndex": top,
                  "startColumnIndex": 11, "endColumnIndex": 18},
        "cell": {"userEnteredFormat": {"textFormat": {
            "bold": True, "fontSize": 14,
            "foregroundColor": {"red": .8, "green": .25, "blue": .15}}}},
        "fields": "userEnteredFormat.textFormat"}})
    for r in (t, v + 3, v + 4):                      # итог / прибыль / рентабельность
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r - 1, "endRowIndex": r,
                      "startColumnIndex": 11, "endColumnIndex": 18},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}})
    for lo, hi, c1, c2 in ((top, t, 14, 16),          # колонки «купили ₽»/«продали ₽»
                           (v - 1, v + 3, 12, 13)):   # выручка/налоги/логистика/прибыль
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": lo, "endRowIndex": hi,
                      "startColumnIndex": c1, "endColumnIndex": c2},
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}},
            "fields": "userEnteredFormat.numberFormat"}})
    reqs.append({"repeatCell": {                     # процент рентабельности
        "range": {"sheetId": sid, "startRowIndex": v + 3, "endRowIndex": v + 4,
                  "startColumnIndex": 12, "endColumnIndex": 13},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}},
        "fields": "userEnteredFormat.numberFormat"}})
    ws.spreadsheet.batch_update({"requests": reqs})
    return top, t


def open_sheet(sheet):
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    return gc.open_by_key(SPREADSHEET).worksheet(sheet)


def insert_invoice(ws, inv, year=None):
    """Вставляет блок накладной в левую часть листа, соблюдая хронологию.

    Возвращает (первая строка, строка ИТОГО) или None, если накладная этой даты уже есть."""
    year = year or inv["date"].year
    rows_raw = ws.get("A1:D400", value_render_option="UNFORMATTED_VALUE")
    dates = {}                                   # дата → строка, где она стоит
    for i, row in enumerate(rows_raw, 1):
        a = str((row or [""])[0]).strip()
        if a and re.match(r"^\d{1,2}[.,]\d{1,2}", a):
            dates[parse_day(a.replace(",", "."), year)] = i
    if inv["date"] in dates:
        return None                              # уже внесена
    last_data = max((i for i, row in enumerate(rows_raw, 1)
                     if row and any(str(c).strip() for c in row)), default=1)
    later = [d for d in dates if d > inv["date"]]
    at = dates[min(later)] if later else last_data + 2   # перед следующей / в конец

    grid = [[inv["date"].strftime("%d.%m.%Y") if i == 0 else "",
             canon_pos(name)[1], packs, summ]
            for i, (name, packs, summ) in enumerate(inv["items"])]
    grid.append(["", "ИТОГО", sum(p for _, p, _ in inv["items"]), inv["total"]])
    grid.append(["", "", "", ""])

    if later:                                    # раздвигаем лист под блок
        ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": at - 1, "endIndex": at - 1 + len(grid)},
            "inheritFromBefore": False}}]})
    ws.spreadsheet.values_batch_update({"value_input_option": "USER_ENTERED", "data": [
        {"range": f"'{ws.title}'!A{at}", "values": grid}]})
    itogo = at + len(inv["items"])
    ws.spreadsheet.batch_update({"requests": [
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": at - 1, "endRowIndex": at,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "DATE", "pattern": "dd.mm"},
                "horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": itogo - 1, "endRowIndex": itogo,
                      "startColumnIndex": 0, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}}]})
    return at, itogo


def period_rows(ws, d1, d2, shift=1):
    """Строки блока за период + итоги: ([(имя, kq, ks, sq, ss, остаток)], итоги)."""
    inv = read_invoices(ws, d1.year)
    b1, b2 = d1 - timedelta(days=shift), d2 - timedelta(days=shift)
    rep, titles = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]), {}
    for dt, pos, qty, summ in inv:
        if b1 <= dt <= b2:
            k, title = canon_pos(pos)
            titles.setdefault(k, title)
            rep[k][0] += qty
            rep[k][1] += summ
    sold, stitles = fetch_sold(d1, d2)
    for k, (q, s) in sold.items():
        titles.setdefault(k, stitles.get(k, k))
        rep[k][2] += q
        rep[k][3] += s
    prev = last_remains(ws)
    rows = []
    for k, v in sorted(rep.items(), key=lambda kv: -kv[1][3]):
        rest = max(prev.get(k, 0) + v[0] - v[2], 0)
        rows.append((titles.get(k, k), v[0], v[1], v[2], v[3], rest))
    tot = [sum(r[i] for r in rows) for i in (1, 2, 3, 4)]
    return rows, tot


KNOWN_KEYS = frozenset(v[0] for _, v in RULES)


def match_position(name):
    """(ключ, имя) для названия позиции, где бы оно ни стояло во фразе.

    canon_pos читает строку с начала, а Анна пишет с обрамлением («писали мизуна
    зеленая», «19 микса списали»), поэтому пробуем срезы: сперва всю фразу, потом
    начиная со второго слова и так далее. Не нашли — возвращаем None, и списание
    уходит в «не понял», а не в случайную позицию.
    """
    words = str(name or "").split()
    for i in range(len(words)):
        key, title = canon_pos(" ".join(words[i:]))
        if key in KNOWN_KEYS:
            return key, title
    return None


def parse_writeoffs(text, today=None):
    """Свободный текст про списания → ([(дата, ключ, имя, пачек)], непонятое).

    Анна пишет как говорит: «мизуна зеленая 5 сегодня, микс салат 1, пакчой зел 2
    вчера списали», «16 числа 19 микса списали», «Микс 23 за 11 число»,
    «Пакчой красный 2 от 11 числа». Дата может стоять и до, и после позиции;
    если её нет — берём дату предыдущего куска (она пишет их подряд одним днём),
    а для самого первого — сегодня.

    Число рядом со словом «число/числа» — это ДЕНЬ, а не количество: в «16 числа
    19 микса» списано 19 пачек 16-го, а не наоборот.
    """
    today = today or date.today()
    out, unknown, last_day = [], [], None
    for chunk in re.split(r"[,;\n]+|(?<=\d)\s+и\s+", str(text or "")):
        s = " ".join(chunk.split())
        if not s:
            continue
        day = None
        low = s.lower().replace("ё", "е")
        if "позавчера" in low:
            day = today - timedelta(days=2)
        elif "вчера" in low:
            day = today - timedelta(days=1)
        elif "сегодня" in low:
            day = today
        s = re.sub(r"(?i)\b(поза)?вчера\b|\bсегодня\b", " ", s)

        m = re.search(r"(?i)(?:за|от|)\s*(\d{1,2})\s*числ[аоеу]?", s)
        if m:
            day = _day_in_month(int(m.group(1)), today)
            s = s[:m.start()] + " " + s[m.end():]
        else:
            m = re.search(r"\b(\d{1,2})[.\-](\d{1,2})(?:[.\-](\d{2,4}))?\b", s)
            if m:
                year = today.year
                if m.group(3):
                    year = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
                day = date(year, int(m.group(2)), int(m.group(1)))
                s = s[:m.start()] + " " + s[m.end():]

        nums = re.findall(r"\d+(?:[.,]\d+)?", s)
        if not nums:
            continue
        qty = float(nums[-1].replace(",", "."))
        name = " ".join(re.sub(r"\d+(?:[.,]\d+)?", " ", s).split())
        name = re.sub(r"(?i)\b(списал[аи]?|списание|списать|шт|штук|пачек|пачки|пачка)\b",
                      " ", name)
        name = " ".join(name.split()).strip(" -—:")
        if not name:
            continue
        hit = match_position(name)
        day = day or last_day or today
        last_day = day
        if hit is None:
            unknown.append((day, name, qty))
            continue
        out.append((day, hit[0], hit[1], qty))
    return out, unknown


def _day_in_month(day, today):
    """«16 числа» → дата: этот месяц, а если день ещё не наступил — прошлый."""
    if day <= today.day:
        return today.replace(day=day)
    prev_end = today.replace(day=1) - timedelta(days=1)
    return prev_end.replace(day=min(day, prev_end.day))


def block_for_day(ws, day):
    """Блок отчёта, в период которого попадает дата (или None)."""
    for b in read_blocks(ws):
        end = label_end(b["label"], day.year, day.month)
        start = block_start(b["label"], day.year, day.month)
        if start and end and start <= day <= end:
            return b
    return None


def block_start(label, year, month):
    """Первый день периода из заголовка блока («11-18 августа» → 11.08)."""
    m = re.match(r"\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s+(\S+)", label)
    if not m:
        return None
    mon = next((i + 1 for i, name in enumerate(MONTHS_GEN)
                if m.group(3).lower().startswith(name[:4])), month)
    try:
        return date(year, mon, int(m.group(1)))
    except ValueError:
        return None


def remains_before(ws, block):
    """Остатки на начало блока = остатки конца предыдущего блока с позициями."""
    blocks = [b for b in read_blocks(ws) if b["rows"]]
    prev = None
    for b in blocks:
        if b["top"] == block["top"]:
            break
        prev = b
    if prev is None:
        return {}
    return {k: (v[5] if v[5] else max(v[0] - v[1] - v[4], 0))
            for k, v in prev["rows"].items()}


def apply_writeoffs(sheet, items):
    """Вносит списания в колонку «списали» нужных блоков и пересчитывает остаток.

    items: [(дата, ключ, имя, пачек)] из parse_writeoffs. Списание кладём в блок,
    в период которого попадает дата. Остаток пересчитываем как
    «было на начало + купили − продали − списали», не ниже нуля.
    Возвращает (применённое, проблемы).
    """
    ws = open_sheet(sheet)
    by_block = defaultdict(list)
    problems = []
    for day, key, title, qty in items:
        block = block_for_day(ws, day)
        if block is None:
            problems.append(
                f"{title} {qty:g} от {day:%d.%m} — нет закрытого периода с этой датой")
            continue
        by_block[block["top"]].append((day, key, title, qty))

    applied, updates = [], []
    for b in read_blocks(ws):
        chunk = by_block.get(b["top"])
        if not chunk:
            continue
        prev = remains_before(ws, b)
        for day, key, title, qty in chunk:
            rowno = b["rownos"].get(key)
            if rowno is None:
                problems.append(
                    f"{title} {qty:g} от {day:%d.%m} — позиции нет в блоке «{b['label']}»")
                continue
            kq, sq, _ks, _ss, spis, _rest = b["rows"][key]
            spis += qty
            rest = max(prev.get(key, 0) + kq - sq - spis, 0)
            b["rows"][key][4] = spis
            b["rows"][key][5] = rest
            updates.append({"range": f"'{ws.title}'!Q{rowno}:R{rowno}",
                            "values": [[spis, rest]]})
            applied.append((b["label"], day, title, qty, rest))
    if updates:
        ws.spreadsheet.values_batch_update(
            {"value_input_option": "USER_ENTERED", "data": updates})
    return applied, problems


def close_period(sheet, d1, d2, label=None, logistics=1000, shift=1):
    """Считает период и дописывает блок в лист. Возвращает (label, rows, tot)."""
    ws = open_sheet(sheet)
    rows, tot = period_rows(ws, d1, d2, shift)
    label = label or f"{d1:%d}-{d2:%d} {MONTHS_GEN[d2.month - 1]}"
    if any(b["label"] == label for b in read_blocks(ws)):
        return label, rows, tot, False           # блок уже есть — не дублируем
    write_block(ws, label, rows, logistics, start_qty=sum(last_remains(ws).values()))
    return label, rows, tot, True


def label_end(label, year, month):
    """Из заголовка блока («04-10 августа», «ИТОГО ИЮЛЬ») — последний день периода."""
    m = re.match(r"\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s+(\S+)", label)
    if not m:
        return None
    day = int(m.group(2))
    mon = next((i + 1 for i, name in enumerate(MONTHS_GEN)
                if m.group(3).lower().startswith(name[:4])), month)
    try:
        return date(year, mon, day)
    except ValueError:
        return None


def current_period(ws, today=None):
    """(d1, d2) незакрытого периода: со дня после последнего блока по сегодня."""
    today = today or date.today()
    ends = [label_end(b["label"], today.year, today.month) for b in read_blocks(ws)]
    ends = [e for e in ends if e]
    if ends:
        return max(ends) + timedelta(days=1), today
    inv = invoice_dates(ws, today.year)
    start = (min(inv) + timedelta(days=1)) if inv else today.replace(day=1)
    return start, today


def period_summary(sheet, d1, d2, logistics=1000, prefix=""):
    """Текст сводки по периоду (для Telegram), ничего не записывает."""
    if d1 > d2:
        return f"{prefix}Предыдущий период закрыт по {d1 - timedelta(days=1):%d.%m}, новый ещё не начался."
    ws = open_sheet(sheet)
    rows, tot = period_rows(ws, d1, d2)
    if not rows:
        return f"{prefix}За {d1:%d.%m}–{d2:%d.%m} движений нет."
    nalog = tot[3] * 0.11
    profit = tot[3] - nalog - tot[1] - logistics
    rent = f"{profit / tot[3] * 100:.1f}%" if tot[3] else "—"
    top = ", ".join(f"{r[0]} {r[3]:.0f}" for r in sorted(rows, key=lambda r: -r[4])[:3])
    return (f"{prefix}📊 {d1:%d.%m}–{d2:%d.%m}\n"
            f"купили {tot[0]:.0f} пачек — {tot[1]:,.0f} ₽\n"
            f"продали {tot[2]:.0f} пачек — {tot[3]:,.0f} ₽\n"
            f"налоги 11% {nalog:,.0f} ₽, логистика {logistics:,.0f} ₽\n"
            f"прибыль {profit:,.0f} ₽ ({rent})\n"
            f"топ продаж: {top}").replace(",", " ")


def process_invoice(path, logistics=1000, today=None):
    """Вносит накладную в лист и показывает, как идёт текущий (незакрытый) период.

    Блок отчёта НЕ пишется: границы периода выбирает Анна (её периоды объединяют
    по несколько накладных) — закрытие идёт отдельной командой/кнопкой.
    Возвращает (текст для Telegram, (лист, d1, d2) незакрытого периода)."""
    inv = beby_invoice.parse(path)
    sheet = MONTHS[inv["date"].month - 1]
    ws = open_sheet(sheet)

    placed = insert_invoice(ws, inv)
    packs = sum(p for _, p, _ in inv["items"])
    lines = [f"📄 Накладная №{inv['number']} от {inv['date']:%d.%m.%Y}"]
    if placed is None:
        lines.append("Уже была в листе — повторно не вносил.")
    else:
        lines.append(f"Внесена в «{sheet}»: {len(inv['items'])} позиций, "
                     f"{packs} пачек, {inv['total']:,.0f} ₽".replace(",", " "))
        lines.append("   " + ", ".join(f"{canon_pos(n)[1]} {p}"
                                       for n, p, _ in inv["items"]))
    ws = open_sheet(sheet)                        # перечитать после вставки
    # период считаем по сегодняшний день: накладная может прийти задним числом
    d1, d2 = current_period(ws, max(today or date.today(), inv["date"]))
    lines.append("")
    lines.append(period_summary(sheet, d1, d2, logistics, prefix="Текущий период — "))
    return "\n".join(lines), (sheet, d1, d2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--invoice", help="PDF накладной: внести и закрыть предыдущий период")
    ap.add_argument("--from", dest="d1", help="начало периода, ДД.ММ")
    ap.add_argument("--to", dest="d2", help="конец периода, ДД.ММ (включительно)")
    ap.add_argument("--sheet", help="лист таблицы (по умолчанию — месяц начала периода)")
    ap.add_argument("--year", type=int, default=date.today().year)
    ap.add_argument("--shift", type=int, default=1,
                    help="на сколько дней накладная раньше продажи (по умолчанию 1)")
    ap.add_argument("--apply", action="store_true", help="дописать блок отчёта в лист")
    ap.add_argument("--label", help="заголовок блока (по умолчанию «04-10 августа»)")
    ap.add_argument("--logistics", type=float, default=1000, help="логистика за период, ₽")
    a = ap.parse_args()
    if a.invoice:
        text, _ = process_invoice(os.path.expanduser(a.invoice), a.logistics)
        print(text)
        return
    if not (a.d1 and a.d2):
        ap.error("нужны --from и --to (или --invoice)")
    d1, d2 = parse_day(a.d1, a.year), parse_day(a.d2, a.year)
    sheet = a.sheet or MONTHS[d1.month - 1]

    rep, titles, used, ws = build(sheet, d1, d2, a.shift)
    print(f"\nЛист «{sheet}», период {d1.strftime('%d.%m')}–{d2.strftime('%d.%m')}"
          f"  (накладные {', '.join(d.strftime('%d.%m') for d in used) or '—'})\n")
    head = f"{'Позиция':<18}{'купили':>8}{'продали':>9}{'куплено ₽':>13}{'продано ₽':>13}{'разница шт':>12}"
    print(head)
    print("-" * len(head))
    tot = [0.0] * 4
    for k, v in sorted(rep.items(), key=lambda kv: -kv[1][3]):
        print(f"{titles.get(k, k):<18}{v[0]:>8.0f}{v[2]:>9.0f}"
              f"{v[1]:>13,.2f}{v[3]:>13,.2f}{v[0] - v[2]:>12.0f}".replace(",", " "))
        tot = [t + x for t, x in zip(tot, v)]
    print("-" * len(head))
    print(f"{'ИТОГО':<18}{tot[0]:>8.0f}{tot[2]:>9.0f}"
          f"{tot[1]:>13,.2f}{tot[3]:>13,.2f}{tot[0] - tot[2]:>12.0f}".replace(",", " "))
    nalog = tot[3] * 0.11
    print(f"\nВыручка (продали):   {tot[3]:>12,.2f} ₽".replace(",", " "))
    print(f"Минус налоги 11%:    {nalog:>12,.2f} ₽".replace(",", " "))
    print(f"Минус закупка:       {tot[1]:>12,.2f} ₽".replace(",", " "))
    print(f"Минус логистика:     {a.logistics:>12,.2f} ₽".replace(",", " "))
    print(f"Прибыль:             {tot[3] - nalog - tot[1] - a.logistics:>12,.2f} ₽".replace(",", " "))

    if not a.apply:
        print("\n(ничего не записано — добавь --apply, чтобы дописать блок в лист)")
        return
    label = a.label or (f"{d1.strftime('%d')}-{d2.strftime('%d')} "
                        f"{MONTHS_GEN[d2.month - 1]}")
    prev = last_remains(ws)
    rows = [(titles.get(k, k), v[0], v[1], v[2], v[3],
             max(prev.get(k, 0) + v[0] - v[2], 0))
            for k, v in sorted(rep.items(), key=lambda kv: -kv[1][3])]
    top, itog = write_block(ws, label, rows, a.logistics)
    print(f"\nБлок «{label}» записан в лист «{sheet}» (строки {top}-{itog + 8}). "
          f"Колонки «списали»/«на остатке» оставлены пустыми — заполни вручную.")


if __name__ == "__main__":
    main()
