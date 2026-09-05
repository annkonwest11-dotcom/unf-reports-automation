#!/usr/bin/env python3
"""Файлы взаиморасчётов по сотрудникам — в формате выгрузки 1С, как их собирает Анна.

Строки берём из листов ДАННЫЕ (кто чей клиент), суммы — из регистра
«РасчетыСПокупателями» 1С за расчётный месяц (НАСТРОЙКИ!B4). У кого есть
беби-клиенты — справа колонки БЕБИ / %беби / оплаты беби / оплаты после вычета,
чтобы было видно, из чего складывается база ЗП. Внизу — блок ФАКТ/ПЛАН под KPI
конкретной роли.

★ ИТОГ пишем ЧИСЛАМИ, а не =SUM(): openpyxl не сохраняет вычисленное значение,
и Numbers с предпросмотром Telegram показывают нули.

Запуск:  venv/bin/python zp_files.py                 — собрать в /tmp
         venv/bin/python zp_files.py --send          — собрать и отправить Анне
         venv/bin/python zp_files.py --only Дарья    — только по одному человеку
"""
import argparse
import os
import tempfile
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from sync_odata import (BASES, SHEET_BASES, ALIASES, DATA_START_ROW, _contractor_names, _fetch_odata,
                        _open_spreadsheet, _parse_settings_period, aggregate_balances,
                        build_token_index, norm_name, soft_lookup)
from zp_text import MONTHS, Sheet, big, num

_ALIAS_NORM = {norm_name(k): v for k, v in ALIASES.items()}

HEADERS = ["Контрагент", "Начальный остаток", "Увеличение долга контрагента",
           "Уменьшение долга контрагента", "Конечный остаток",
           "БЕБИ", "% беби", "Оплаты беби-листов", "Оплаты после вычета беби"]
WIDTHS = (("A", 46.6), ("B", 15.2), ("C", 21.0), ("D", 21.0), ("E", 38.0),
          ("F", 8.0), ("G", 8.0), ("H", 17.0), ("I", 20.0))


def canon(name):
    nn = norm_name(name)
    return norm_name(_ALIAS_NORM[nn]) if nn in _ALIAS_NORM else nn


def balance_for(name, bal, index):
    """Движения контрагента: точно по имени, иначе — мягким матчем по словам.

    Карточки в 1С переименовывают на ходу («… с 10.08.26 на ПЕРФИЛЬЕВ», метки
    «dsbx бюро», «ензо»), и строгий матч отдавал нули — файл недобирал сотни
    тысяч против листа. Логика подбора — sync_odata.soft_lookup.
    """
    c = canon(name)
    if c in bal:
        return bal[c]
    soft = soft_lookup(c, index)
    return bal[soft] if soft in bal else [0.0, 0.0, 0.0, 0.0]


def _period(ss):
    """(StartPeriod, EndPeriod, «ИЮЛЬ», год) расчётного месяца из НАСТРОЙКИ!B4."""
    pp = _parse_settings_period(ss)
    if not pp:
        raise RuntimeError("НАСТРОЙКИ!B4 не распознан — не знаю, за какой месяц считать")
    year, month = pp
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    fmt = "datetime'%Y-%m-%dT00:00:00'"
    return start.strftime(fmt), end.strftime(fmt), MONTHS[month - 1], year


def load_balances(base_id, start, end):
    """{canon: [нач.остаток, отгрузка, оплаты, кон.остаток]} за расчётный месяц."""
    rows = _fetch_odata(base_id, "AccumulationRegister_РасчетыСПокупателями/BalanceAndTurnovers("
                                 f"StartPeriod={start},EndPeriod={end})")
    names = _contractor_names(base_id)
    out = {}
    for key, vals in aggregate_balances(rows).items():
        nm = names.get(key)
        if not nm:
            continue
        cur = out.setdefault(canon(nm), [0.0, 0.0, 0.0, 0.0])
        for i in range(4):
            cur[i] += vals[i]
    return out


def _write(path, records, bottom, month_label):
    """Собрать xlsx. records: [(имя, [4 суммы 1С], J скорр., (%беби, оплаты беби)|None)]."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Лист_1"
    thin = Side(style="thin")
    head, body = Font(name="Arial", size=10), Font(name="Arial", size=8)
    bold = Font(name="Arial", size=8, bold=True)
    green = PatternFill("solid", fgColor="E2EFDA")

    has_beby = any(r[3] for r in records)
    for j, h in enumerate(HEADERS if has_beby else HEADERS[:5], start=1):
        c = ws.cell(row=1, column=j, value=h)
        c.font, c.border = head, Border(bottom=thin)
        c.alignment = Alignment(horizontal="left", wrap_text=True)

    row = 2
    fact_raw = fact_adj = 0.0
    for name, vals, j_val, beby in records:
        ws.cell(row=row, column=1, value=name).font = body
        ws.cell(row=row, column=1).border = Border(bottom=thin)
        for col, val in zip((2, 3, 4, 5), vals):
            cell = ws.cell(row=row, column=col, value=(val if val else None))
            cell.font, cell.number_format = body, "#,##0.00"
            cell.alignment = Alignment(horizontal="right")
            cell.border = Border(bottom=thin)
        fact_raw += vals[2]
        fact_adj += j_val
        if beby:
            pct_beby, pay_beby = beby
            for col, val, fmt in ((6, "БЕБИ", None), (7, pct_beby, "0%"),
                                  (8, pay_beby or None, "#,##0.00"),
                                  (9, j_val or None, "#,##0.00")):
                cell = ws.cell(row=row, column=col, value=val)
                cell.font = bold if col == 6 else body
                cell.fill = green
                if fmt:
                    cell.number_format = fmt
                cell.alignment = Alignment(horizontal="center" if col == 6 else "right")
        row += 1

    ws.cell(row=row, column=1, value="ИТОГ ").font = bold
    for col, val in zip((2, 3, 4, 5),
                        [round(sum(r[1][i] for r in records), 2) for i in range(4)]):
        c = ws.cell(row=row, column=col, value=(val if val else None))
        c.font, c.number_format = bold, "#,##0.00"
        c.alignment = Alignment(horizontal="right")
        c.border = Border(top=thin, bottom=thin)
    beby_rows = [r for r in records if r[3]]
    if has_beby:
        for col, val in ((8, sum(r[3][1] for r in beby_rows)), (9, sum(r[2] for r in beby_rows))):
            c = ws.cell(row=row, column=col, value=round(val, 2))
            c.font, c.number_format, c.fill = bold, "#,##0.00", green

    def put(rr, col, val, font=body, fmt=None, fill=None):
        cell = ws.cell(row=rr, column=col, value=val)
        cell.font = font
        if fmt:
            cell.number_format = fmt
        if fill:
            cell.fill = fill
        cell.alignment = Alignment(
            horizontal="right" if isinstance(val, (int, float)) else "left")

    rr = row + 2
    if has_beby:
        put(rr, 4, round(fact_raw, 2), bold, "#,##0.00")
        put(rr, 5, f"ФАКТ ЗА {month_label} (без вычета беби)", bold)
        rr += 1
    put(rr, 4, round(fact_adj, 2), bold, "#,##0.00", green)
    put(rr, 5, bottom[0], bold, fill=green)
    for label, val in bottom[1:]:
        rr += 1
        is_pct = label.startswith("%")
        put(rr, 4, round(val, 4) if is_pct else round(val, 2), body,
            "0%" if is_pct else "#,##0.00")
        put(rr, 5, label, body)

    for col, w in (WIDTHS if has_beby else WIDTHS[:5]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    wb.save(path)
    return len(records), len(beby_rows), fact_raw, fact_adj


def build_files(only=None, outdir=None):
    """Собрать файлы. Возвращает [(путь, подпись, строк, оплаты 1С, в расчёт ЗП)]."""
    outdir = outdir or tempfile.mkdtemp(prefix="zp_files_")
    ss = _open_spreadsheet()
    start, end, month_label, year = _period(ss)
    sh = Sheet(ss.worksheet("СВОДНАЯ_ЗП").get("A1:H175", value_render_option="UNFORMATTED_VALUE"))

    beby = {}
    for r in ss.worksheet("БЕБИ_ЛИСТЫ").get("A4:J23"):
        nm = (r[0] or "").strip() if r else ""
        if nm:
            beby[canon(nm)] = (num(r[5] if len(r) > 5 else 0), num(r[7] if len(r) > 7 else 0))

    grids, bals, soft_idx = {}, {}, {}
    for base_name, cfg in SHEET_BASES.items():
        grids[base_name] = ss.worksheet(cfg["sheet_name"]).get("A1:L600")
        bals[base_name] = load_balances(cfg["id"], start, end)
        soft_idx[base_name] = build_token_index(bals[base_name].keys())

    def kpi(who, label, col=3):
        """Значение строки блока сотрудника из СВОДНОЙ (C по умолчанию, E при col=5)."""
        block, _ = sh.block(who)
        c, _, e, _ = Sheet.row(block, label)
        return e if col == 5 else c

    reports = [
        dict(who="Ксения Наныкина", fname="Взаиморасчеты КСЕНИЯ НАНЫКИНА",
             descr="Ксения Наныкина — клиенты поиска",
             pred=lambda f, g, h: f == "Ксения Наныкина",
             bottom=[f"ФАКТ ЗА {month_label} — оплаты всех клиентов (в расчёт ЗП)",
                     ("Новые клиенты — факт", kpi("Ксения Наныкина", "Оплаты (новые клиенты)")),
                     ("% выполнения плана по новым",
                      kpi("Ксения Наныкина", "% выполнения плана"))]),
        dict(who="Дарья Вольнова", fname="Взаиморасчеты ВОЛЬНОВА ДАРЬЯ",
             descr="Дарья Вольнова — клиенты поиска",
             pred=lambda f, g, h: f == "Дарья Вольнова",
             bottom=[f"ФАКТ ЗА {month_label} — оплаты всех клиентов (в расчёт ЗП)",
                     ("Новые клиенты — факт", kpi("Дарья Вольнова", "Оплаты (новые клиенты)")),
                     ("% выполнения плана по новым",
                      kpi("Дарья Вольнова", "% выполнения плана"))]),
        dict(who="Лилия Сулименко", fname="Взаиморасчеты СУЛИМЕНКО ЛИЛИЯ",
             descr="Лилия Сулименко — клиенты поиска",
             pred=lambda f, g, h: f == "Лилия Сулименко",
             bottom=[f"ФАКТ ЗА {month_label} — оплаты всех клиентов (в расчёт ЗП)",
                     ("Новые клиенты — факт",
                      kpi("Лилия Сулименко", "Оплаты (новые клиенты)")),
                     ("% выполнения плана по новым",
                      kpi("Лилия Сулименко", "% выполнения плана"))]),
        dict(who="Алена Черкашина", fname="Взаиморасчеты ЧЕРКАШИНА АЛЕНА",
             descr="Алёна Черкашина — рестораны на сопровождении",
             pred=lambda f, g, h: g == "Алена Черкашина" and h == "Ресторан",
             bottom=[f"ФАКТ С ВЫЧЕТОМ БЕБИ (идёт в расчёт ЗП)",
                     ("План на месяц", _plan_alena(ss)),
                     ("% выполнения плана",
                      kpi("Алена Черкашина", "% выполнения плана"))]),
        dict(who="Анна Кононенко (РОП)", fname="Взаиморасчеты АННА КОНОНЕНКО",
             descr="Анна Кононенко (РОП) — все рестораны",
             pred=lambda f, g, h: h == "Ресторан",
             bottom=[f"ФАКТ ЗА {month_label} — оплаты ресторанов (база бонуса РОП)",
                     ("Поступления всего (АДЕСК) — факт",
                      kpi("Анна Кононенко (РОП)", "Факт — поступления", col=5)),
                     ("% выполнения плана по поступлениям",
                      kpi("Анна Кононенко (РОП)", "% выполнения плана — поступления")),
                     ("Оборот — факт", kpi("Анна Кононенко (РОП)", "Факт — оборот", col=5)),
                     ("% выполнения плана по обороту",
                      kpi("Анна Кононенко (РОП)", "% выполнения плана — оборот"))]),
    ]

    out = []
    for rep in reports:
        if only and only.lower() not in rep["who"].lower():
            continue
        records = []
        for base_name, grid in grids.items():
            for r in grid[DATA_START_ROW - 1:]:
                name = (r[0] or "").strip() if r else ""
                if not name:
                    continue
                f = (r[5] or "").strip() if len(r) > 5 else ""
                g = (r[6] or "").strip() if len(r) > 6 else ""
                h = (r[7] or "").strip() if len(r) > 7 else ""
                if not rep["pred"](f, g, h):
                    continue
                c = canon(name)
                vals = [round(x, 2)
                        for x in balance_for(name, bals[base_name], soft_idx[base_name])]
                records.append((name, vals, num(r[9] if len(r) > 9 else 0), beby.get(c)))
        records.sort(key=lambda x: (x[0][0].lower() > "я", x[0].lower()))
        if not records:
            continue

        path = os.path.join(outdir, f"{rep['fname']} {month_label} {year}.xlsx")
        cnt, cnt_beby, raw, adj = _write(path, records, rep["bottom"], month_label)
        cap = [f"📊 {rep['descr']}", f"{month_label} {year}", "", f"Контрагентов: {cnt}"]
        if cnt_beby:
            cap.append(f"с беби-листами: {cnt_beby} — помечены справа")
            cap.append(f"Оплаты без вычета беби: {big(raw)} ₽")
            cap.append(f"Оплаты с вычетом беби: {big(adj)} ₽ (в расчёт ЗП)")
        else:
            cap.append(f"Оплаты: {big(adj)} ₽ (в расчёт ЗП)")
        out.append((path, "\n".join(cap), cnt, raw, adj, rep["who"]))
    return out


def build_package(only=None, outdir=None):
    """[(ФИО, текст расчёта, путь к файлу | None, подпись к файлу)] в порядке рассылки.

    Пара «расчёт + его файл» идёт подряд, чтобы не путать, чей файл под чьим расчётом
    (просьба Анны). У Влады клиентской базы нет — только текст.
    """
    import zp_text
    texts = zp_text.build_texts()
    files = {rec[5]: (rec[0], rec[1]) for rec in build_files(only=only, outdir=outdir)}
    package = []
    for who, text in texts.items():
        if only and only.lower() not in who.lower():
            continue
        path, caption = files.get(who, (None, None))
        package.append((who, text, path, caption))
    return package


def _plan_alena(ss):
    """План оплат ресторанов Алёны — НАСТРОЙКИ, строка «Алена Черкашина»."""
    for r in ss.worksheet("НАСТРОЙКИ").get("A1:D30", value_render_option="UNFORMATTED_VALUE"):
        r = (r or []) + [""] * 3
        if "алена черкашина" in str(r[0]).lower() and "оплаты ресторанов" in str(r[1]).lower():
            return num(r[2])
    return 0.0


def _tg(method, data, files=None, chat_id=None):
    import requests
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    data = dict(data, chat_id=chat_id or os.getenv("ANNA_CHAT_ID"))
    resp = requests.post(f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/{method}",
                         data=data, files=files, timeout=120)
    return "OK" if resp.json().get("ok") else resp.text[:150]


def send_package(only=None, chat_id=None):
    """Рассылка парами: расчёт сотрудника → сразу его файл взаиморасчётов."""
    for who, text, path, caption in build_package(only=only):
        print(f"── {who}: текст {_tg('sendMessage', {'text': text}, chat_id=chat_id)}", end="")
        if path:
            with open(path, "rb") as fh:
                res = _tg("sendDocument", {"caption": caption},
                          {"document": (os.path.basename(path), fh,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                          chat_id=chat_id)
            print(f" | файл {res}")
        else:
            print(" | файла нет (клиентской базы нет)")
    if not only:                      # хвост нужен только при рассылке по всем
        import zp_text
        print("── сводка:", _tg("sendMessage",
                                {"text": zp_text.department_summary(), "parse_mode": "HTML"},
                                chat_id=chat_id))
        print("── итог наличными:", _tg("sendMessage", {"text": zp_text.cash_summary()},
                                        chat_id=chat_id))


def main():
    ap = argparse.ArgumentParser(description="Файлы взаиморасчётов по сотрудникам")
    ap.add_argument("--send", action="store_true", help="отправить Анне в Telegram")
    ap.add_argument("--only", help="только по одному человеку (часть имени)")
    ap.add_argument("--package", action="store_true",
                    help="слать парами: расчёт ЗП + его файл")
    ap.add_argument("--to", choices=("anna", "group"), default="anna",
                    help="куда слать: anna (личка, по умолчанию) или group «ЗАРПЛАТЫ ОФИС»")
    args = ap.parse_args()

    if args.package:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
        chat = os.getenv("ZP_GROUP_CHAT_ID") if args.to == "group" else None
        send_package(only=args.only, chat_id=chat)
        return

    files = build_files(only=args.only)
    for path, caption, cnt, raw, adj, _who in files:
        print(f"{os.path.basename(path):<52} строк {cnt:>4} | 1С {raw:>14,.2f} | "
              f"в ЗП {adj:>14,.2f}".replace(",", " "))
        if args.send:
            import requests
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
            with open(path, "rb") as fh:
                resp = requests.post(
                    f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendDocument",
                    data={"chat_id": os.getenv("ANNA_CHAT_ID"), "caption": caption},
                    files={"document": (os.path.basename(path), fh,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    timeout=120)
            print("   отправка:", "OK" if resp.json().get("ok") else resp.text[:150])


if __name__ == "__main__":
    main()
