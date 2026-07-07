#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
СВЕРКА ОПЛАТ МЕНЕДЖЕРА (read-only).

Сверяет файл взаиморасчётов сотрудника (Excel, выгрузка из 1С) построчно против
живого листа ДАННЫЕ в Google Sheets. Показывает расхождения по контрагентам.
НИЧЕГО не пишет обратно — это инструмент сверки перед ручными правками.

Как это работает
----------------
В файле взаиморасчётов колонка D («Уменьшение долга контрагента») = оплаты за период.
В ДАННЫХ те же оплаты лежат в колонке D (сырьё из 1С) и J (скорректированные —
именно J читает бонус «% от оплат» в СВОДНОЙ). Менеджер поиска — колонка F,
сопровождения — G. Скрипт суммирует оплаты по контрагентам менеджера и сверяет.

Грабли (см. docs/СТАВКИ_и_KPI.md и историю правок):
  • Короткие/полные имена и служебные хвосты («ЭДО», «СЧЁТ!!!», «dsbx») — матчим
    сперва точно, потом по «ядру» имени (до первой скобки).
  • Привязка менеджера (F/G) в ДАННЫХ — это ВПР из СПРАВОЧНИК (колонка B/C).
    Чинить привязку надо в СПРАВОЧНИКЕ, не в ДАННЫХ (синк 1С перезаписывает D, но
    не трогает СПРАВОЧНИК и колонку J).

Запуск:
  python scripts/recon_manager.py "Ксения Наныкина" "~/Desktop/ИЮНЬ 2026 НАНЫКИНА КСЕНИЯ .xlsx"
  python scripts/recon_manager.py "Валерия Абрамова" <файл> --role soprovozhdenie

Требует: credentials.json в корне репо, SPREADSHEET_ID в .env (или дефолт ниже).
"""
import argparse
import os
import re
import sys

import gspread
import openpyxl
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID") or "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"
DATA_TABS = ("ДАННЫЕ_Губарев", "ДАННЫЕ_Перфильев")


def norm(s):
    return re.sub(r"\s+", " ", (str(s) or "").replace("\xa0", " ")).strip().lower()


def core(s):
    """Ядро имени — до первой скобки, для матчинга служебных хвостов."""
    return re.sub(r"\(.*", "", norm(s)).strip()


def num(s):
    s = str(s or "").replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if s in ("", "-", "—", "None", "#ERROR!"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def rub(x):
    return f"{x:,.2f}".replace(",", " ")


def read_file(path):
    """Файл взаиморасчётов → {norm_имя: (сырое_имя, оплата)} и сумма."""
    wb = openpyxl.load_workbook(os.path.expanduser(path), data_only=True)
    ws = wb.active
    rows, total = {}, 0.0
    for r in ws.iter_rows(min_row=2, values_only=True):
        name = r[0]
        if not name or norm(name) in ("итог", "итого", "всего"):
            continue
        d = num(r[3])
        rows[norm(name)] = (name, d)
        total += d
    return rows, total


def read_data(gc, sh, manager, role):
    """Строки ДАННЫХ, где менеджер = поиск (F) или сопровождение (G)."""
    col = 5 if role == "poisk" else 6   # F=5, G=6 (0-индекс)
    rows = {}
    for tab in DATA_TABS:
        for i, r in enumerate(sh.worksheet(tab).get_all_values()[3:], start=4):
            if len(r) < 10:
                continue
            if norm(r[col]) == norm(manager):
                rows[norm(r[0])] = (r[0], num(r[3]), num(r[9]), tab.split("_")[1], i)  # D, J
    return rows


def reconcile(manager, path, role):
    if not os.path.exists("credentials.json"):
        sys.exit("Нет credentials.json в корне репо — доступ к таблицам невозможен.")
    gc = gspread.service_account(filename="credentials.json")
    sh = gc.open_by_key(SPREADSHEET_ID)

    file_rows, file_total = read_file(path)
    sheet_rows = read_data(gc, sh, manager, role)
    sumD = sum(v[1] for v in sheet_rows.values())
    sumJ = sum(v[2] for v in sheet_rows.values())

    print("═" * 76)
    print(f"  СВЕРКА ОПЛАТ — {manager}   (роль: {role}, read-only)")
    print("═" * 76)
    print(f"ФАЙЛ:   {len(file_rows)} контрагентов, сумма оплат (D) = {rub(file_total)}")
    print(f"ДАННЫЕ: {len(sheet_rows)} строк, sum D = {rub(sumD)}   sum J = {rub(sumJ)}  (J → бонус)")
    print(f"Δ (ДАННЫЕ.J − файл) = {rub(sumJ - file_total)}\n")

    file_left, sheet_left, deltas = dict(file_rows), dict(sheet_rows), []
    for n in list(file_left):
        if n in sheet_left:
            fp, sv = file_left[n][1], sheet_left[n][2]
            if abs(fp - sv) > 0.5:
                deltas.append((file_left[n][0], fp, sv, "точн"))
            del file_left[n], sheet_left[n]

    def by_core(name, pool):
        c = core(name)
        if len(c) < 4:
            return None
        return next((k for k, v in pool.items() if core(v[0]) == c), None)

    for n in list(file_left):
        k = by_core(file_left[n][0], sheet_left)
        if k:
            fp, sv = file_left[n][1], sheet_left[k][2]
            if abs(fp - sv) > 0.5:
                deltas.append((f"{file_left[n][0]} ≈ {sheet_left[k][0]}", fp, sv, "ядро"))
            del file_left[n], sheet_left[k]

    if deltas:
        print("── СУММЫ РАЗЛИЧАЮТСЯ ──")
        for nm, fp, sv, how in deltas:
            print(f"  [{how}] {nm[:46]:48} файл={rub(fp):>13}  ДАННЫЕ.J={rub(sv):>13}  Δ={rub(sv - fp):>+12}")
    only_file = [(v[0], v[1]) for v in file_left.values() if v[1]]
    only_data = [(v[0], v[2], v[3], v[4]) for v in sheet_left.values() if v[2]]
    if only_file:
        print("\n── ТОЛЬКО в файле (нет у менеджера в ДАННЫХ) ──")
        for nm, d in sorted(only_file):
            print(f"  {nm[:50]:52} оплата={rub(d):>13}")
    if only_data:
        print("\n── ТОЛЬКО в ДАННЫХ (нет в файле) ──")
        for nm, j, tab, i in sorted(only_data):
            print(f"  {nm[:50]:52} J={rub(j):>13}  [{tab} стр{i}]")

    if not deltas and not only_file and not only_data:
        print("✅ Всё сошлось до копейки.")
    print("\n(Сверка завершена. В таблицы ничего не записано.)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Сверка оплат менеджера: файл взаиморасчётов vs ДАННЫЕ.")
    ap.add_argument("manager", help='ФИО как в СПРАВОЧНИКЕ, напр. "Ксения Наныкина"')
    ap.add_argument("file", help="путь к .xlsx взаиморасчётов")
    ap.add_argument("--role", choices=["poisk", "soprovozhdenie"], default="poisk",
                    help="poisk = сверять по колонке F (поиск), soprovozhdenie = по G (сопровождение)")
    a = ap.parse_args()
    reconcile(a.manager, a.file, a.role)
