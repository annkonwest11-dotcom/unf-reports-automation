# -*- coding: utf-8 -*-
"""Убрать уволившегося сотрудника из зарплатной таблицы — целиком и без #REF!.

Человек встречается в ПЯТИ местах, и забыть любое — значит получить либо
#REF! в ФОТ, либо тихо потерянное слагаемое:

  1. дашборд сверху      — строка «Имя» со ссылкой на ИТОГО его блока;
  2. детальный блок      — от заголовка «Имя | должность» до «ИТОГО ЗП — Имя»;
  3. ТАБЛИЦА ВЫПЛАТ      — строка с авансами и остатком наличными;
  4. формула ФОТ         — слагаемое C<ИТОГО его блока>;
  5. листы СМЕНЫ(_СЛЕД)  — строки в «основных сменах» и «подработках».

Плюс код: `sync_avansy.EMPLOYEES` (там номера строк таблицы выплат) и
`sheets._SHIFT_DAY_RANGES` (диапазоны строк листа смен) — их скрипт не правит,
а печатает, что именно стало неверным.

★Делать ТОЛЬКО после закрытия месяца: пока месяц не заархивирован, в блоках
живут суммы, которые ещё идут в расчёт и в рассылку.

Запуск:  venv/bin/python scripts/remove_employee.py --who "Лилия Сулименко"
         venv/bin/python scripts/remove_employee.py --who "Лилия Сулименко" --apply
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
SUMMARY = "СВОДНАЯ_ЗП"
SECTION_TITLES = ("МЕНЕДЖЕРЫ ПОИСКА", "МЕНЕДЖЕРЫ СОПРОВОЖДЕНИЯ", "РОП", "ПОМОЩНИК")
ITOGO_PREFIX = "ИТОГО ЗП —"


def norm(s) -> str:
    """«Алена»/«Алёна», лишние пробелы и регистр — одно и то же имя."""
    return " ".join(str(s or "").replace("ё", "е").lower().split())


def open_spreadsheet():
    gc = gspread.authorize(Credentials.from_service_account_file(
        "credentials.json", scopes=SCOPES))
    return gc.open_by_key(os.environ["SPREADSHEET_ID"])


def plan_summary(ws, who: str) -> dict:
    """Что удалить в СВОДНОЙ и чем заменить формулу ФОТ."""
    values = ws.get_all_values()
    col_a = [(i + 1, r[0] if r else "") for i, r in enumerate(values)]
    want = norm(who)

    payments_start = next((i for i, a in col_a if "ТАБЛИЦА ВЫПЛАТ" in a.upper()), None)
    ledger_start = next((i for i, a in col_a if "СВОДНАЯ ЗАРПЛАТНАЯ ВЕДОМОСТЬ" in a.upper()),
                        None)

    dash_row = next((i for i, a in col_a
                     if norm(a) == want and ledger_start and i < ledger_start), None)
    # Заголовок секции В ДАШБОРДЕ («ПОМОЩНИК» над строкой человека): если он там
    # один, после удаления остаётся пустая подпись — её тоже убираем.
    dash_section = None
    if dash_row:
        prev = next((i for i, a in reversed(col_a) if i < dash_row and a.strip()), None)
        if prev and col_a[prev - 1][1].strip().upper() in SECTION_TITLES:
            nxt = next((i for i, a in col_a
                        if i > dash_row and a.strip()
                        and (a.strip().upper() in SECTION_TITLES
                             or a.strip().upper().startswith("ИТОГО"))), None)
            if nxt == dash_row + 1 or nxt is None:
                dash_section = prev
    pay_row = next((i for i, a in col_a
                    if norm(a) == want and payments_start and i > payments_start), None)
    itogo_row = next((i for i, a in col_a
                      if a.startswith(ITOGO_PREFIX) and want in norm(a)), None)
    # Заголовок блока — ближайшая строка перед его ИТОГО, где стоит имя. Оформление
    # разное: у менеджеров «Имя | должность», у помощника просто «Имя», поэтому
    # опираемся на имя, а не на разделитель.
    head_row = next((i for i, a in reversed(col_a)
                     if itogo_row and ledger_start and ledger_start < i < itogo_row
                     and want in norm(a) and i != dash_row), None)

    # Заголовок секции прямо над блоком убираем, если в секции больше никого:
    # «ПОМОЩНИК» без помощника — мусор в дашборде. Соседей считаем по строкам
    # «ИТОГО ЗП — …» внутри секции, они есть у каждого блока.
    section_row = None
    if head_row:
        prev = next((i for i, a in reversed(col_a) if i < head_row and a.strip()), None)
        if prev and col_a[prev - 1][1].strip().upper() in SECTION_TITLES:
            next_section = next((i for i, a in col_a
                                 if i > head_row and a.strip().upper() in SECTION_TITLES),
                                payments_start or len(col_a) + 1)
            neighbours = [i for i, a in col_a
                          if prev < i < next_section and a.startswith(ITOGO_PREFIX)
                          and want not in norm(a)]
            if not neighbours:
                section_row = prev

    # новая формула ФОТ: сумма всех оставшихся «ИТОГО ЗП — …»
    fot_row = next((i for i, a in col_a if a.strip().upper().startswith("ИТОГО ФОТ")), None)
    keep = [i for i, a in col_a if a.startswith(ITOGO_PREFIX) and want not in norm(a)]

    # строки дашборда остальных сотрудников ссылаются на ИТОГО блоков — после
    # удаления Sheets поправит их сам, поэтому их не трогаем
    return {"dash_row": dash_row, "dash_section": dash_section, "pay_row": pay_row,
            "head_row": head_row, "itogo_row": itogo_row, "section_row": section_row,
            "fot_row": fot_row, "itogo_keep": keep, "payments_start": payments_start}


def plan_shifts(sh, who: str) -> dict:
    """Строки сотрудника в листах смен (основные смены и подработки)."""
    out = {}
    want = norm(who)
    for title in ("СМЕНЫ", "СМЕНЫ_СЛЕД"):
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            continue
        rows = [i + 1 for i, r in enumerate(ws.get_all_values())
                if len(r) > 1 and norm(r[1]) == want]
        if rows:
            out[title] = rows
    return out


def backup(sh, who: str) -> str:
    """Формулы и значения листов, которые правим, — до правки."""
    data = {"кого убираем": who, "дата": datetime.date.today().isoformat()}
    sv = sh.worksheet(SUMMARY)
    data[SUMMARY] = {
        "formulas": sv.get("A1:H200", value_render_option="FORMULA"),
        "values": sv.get("A1:H200", value_render_option="UNFORMATTED_VALUE"),
    }
    for title in ("СМЕНЫ", "СМЕНЫ_СЛЕД", "НАСТРОЙКИ"):
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            continue
        data[title] = {"formulas": ws.get("A1:AJ40", value_render_option="FORMULA")}
    path = f"docs/бэкап_увольнение_{who.split()[0]}_{data['дата']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--who", required=True, help="ФИО как в таблице")
    ap.add_argument("--apply", action="store_true", help="выполнить (иначе только план)")
    args = ap.parse_args()

    sh = open_spreadsheet()
    period = (sh.worksheet("НАСТРОЙКИ").acell("B4").value or "").strip()
    sv = sh.worksheet(SUMMARY)
    p = plan_summary(sv, args.who)
    shifts = plan_shifts(sh, args.who)

    print(f"УБИРАЕМ: {args.who}   (расчётный период в таблице: {period})")
    print("\nСВОДНАЯ_ЗП:")
    print(f"  строка дашборда:      {p['dash_row'] or '— не найдена'}")
    print(f"  секция в дашборде:    {p['dash_section'] or '— остаётся'}")
    print(f"  блок:                 {p['head_row']}–{p['itogo_row']}"
          if p["head_row"] else "  блок:                 — не найден")
    print(f"  заголовок секции:     {p['section_row'] or '— остаётся (в секции есть другие)'}")
    print(f"  строка таблицы выплат:{p['pay_row'] or '— не найдена'}")
    print(f"  ФОТ (строка {p['fot_row']}) станет суммой ИТОГО строк: {p['itogo_keep']}")
    print("\nЛИСТЫ СМЕН:")
    for title, rows in shifts.items() or {}.items():
        print(f"  {title}: строки {rows}")
    if not shifts:
        print("  — строк не найдено")
    print("\nПОСЛЕ ЭТОГО ПРАВИТЬ В КОДЕ:")
    print("  sync_avansy.EMPLOYEES — убрать сотрудника и пересчитать номера строк")
    print("  sheets._SHIFT_DAY_RANGES — диапазоны строк листа смен")
    print("  (для помощника — ещё инструкция в docs/ШАБЛОНЫ_СМЕН.md)")

    if not all((p["dash_row"], p["head_row"], p["itogo_row"], p["pay_row"], p["fot_row"])):
        print("\n⚠️ не все места найдены — правка не выполняется, разберись сначала")
        return
    if not args.apply:
        print("\n(это только план; чтобы выполнить — добавь --apply)")
        return

    path = backup(sh, args.who)
    print(f"\nбэкап: {path}")

    # Удаляем сверху вниз по убыванию номеров, иначе строки уедут под ногами.
    to_delete = sorted({p["pay_row"], *range(p["head_row"], p["itogo_row"] + 1),
                        p["dash_row"],
                        *([p["section_row"]] if p["section_row"] else []),
                        *([p["dash_section"]] if p["dash_section"] else [])},
                       reverse=True)
    for row in to_delete:
        sv.delete_rows(row)
    print(f"удалено строк в СВОДНОЙ: {len(to_delete)}")

    # ФОТ пересобираем по подписям: после сдвигов старые номера уже не те
    values = sv.get_all_values()
    itogo = [i + 1 for i, r in enumerate(values)
             if r and r[0].startswith(ITOGO_PREFIX)]
    fot_row = next(i + 1 for i, r in enumerate(values)
                   if r and r[0].strip().upper().startswith("ИТОГО ФОТ"))
    formula = "=" + "+".join(f"C{i}" for i in itogo)
    sv.update(values=[[formula]], range_name=f"C{fot_row}",
              value_input_option="USER_ENTERED")
    print(f"ФОТ (C{fot_row}) = {formula}")

    for title, rows in shifts.items():
        ws = sh.worksheet(title)
        for row in sorted(rows, reverse=True):
            ws.delete_rows(row)
        print(f"{title}: удалены строки {rows}")

    print("\nготово. Проверь: ФОТ, ИТОГО таблицы выплат и ссылки дашборда "
          "(они должны были поправиться сами).")


if __name__ == "__main__":
    main()
