# -*- coding: utf-8 -*-
"""Привести порядок листов зарплатной таблицы к канону: рабочие, потом архивы.

Анна, 15.10.2026: «архивные листы переноси в конец, они мешают». Сам архив
месяца теперь и создаётся последним (sheets.archive_month), но порядок уже
разъехался, а ещё его легко сбить руками — этот скрипт его восстанавливает.

⚠️Две граблИ Sheets API, обе проверены на себе 15.10.2026:
  • в ОДНОМ batch_update несколько updateSheetProperties с индексами применяются
    последовательно, и каждое перемещение сдвигает остальные — листы встают
    вперемешку. Значит по одному запросу на лист, перечитывая порядок;
  • лист сначала ИЗВЛЕКАЕТСЯ из текущей позиции, а потом вставляется. Поэтому
    при движении ВПРАВО целевой индекс нужно увеличить на 1, иначе лист встанет
    на позицию раньше нужной. Из-за этого «двигаем каждый в конец» давало
    круговой сдвиг и возвращало исходный порядок.

Запуск:  venv/bin/python scripts/order_sheets.py          — показать план
         venv/bin/python scripts/order_sheets.py --apply  — применить
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

# Канонический порядок рабочих листов: сначала настройки и расчёт, потом
# источники данных, в конце табель и новые клиенты. Листы *_СЛЕД идут сразу за
# своим живым листом, архивы — в самом конце, от старого месяца к новому.
WORK_ORDER = ["НАСТРОЙКИ", "СВОДНАЯ_ЗП", "СПРАВОЧНИК",
              "ДАННЫЕ_Губарев", "ДАННЫЕ_Перфильев", "ДАННЫЕ_Володихина",
              "БЕБИ_ЛИСТЫ", "СМЕНЫ", "НОВЫЕ_КЛИЕНТЫ"]
MONTHS = ["ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ",
          "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ"]


def target_order(titles: list[str]) -> list[str]:
    def month_key(t: str):
        up = t.upper()
        year = next((int(y) for y in up.replace("_", " ").split() if y.isdigit()), 0)
        month = next((i for i, m in enumerate(MONTHS) if m in up), 99)
        return (year, month, t)

    rest = [t for t in titles if t not in WORK_ORDER]
    archives = sorted([t for t in rest if t.startswith("АРХИВ_")], key=month_key)
    others = [t for t in rest if t not in archives]          # напр. листы *_СЛЕД
    out = []
    for name in WORK_ORDER:
        if name in titles:
            out.append(name)
            out += [t for t in others if t.startswith(name + "_")]
    out += [t for t in others if t not in out]
    return out + archives


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    gc = gspread.authorize(Credentials.from_service_account_file(
        "credentials.json", scopes=SCOPES))
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    titles = [w.title for w in sh.worksheets()]
    target = target_order(titles)

    print("сейчас: ", titles)
    print("станет: ", target)
    if titles == target:
        print("\nпорядок уже канонический")
        return
    if not args.apply:
        print("\n(это только план; чтобы применить — добавь --apply)")
        return

    for want, name in enumerate(target):
        props = {s["properties"]["title"]: s["properties"]
                 for s in sh.fetch_sheet_metadata()["sheets"]}
        cur = props[name]["index"]
        if cur == want:
            continue
        index = want if cur > want else want + 1
        sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": props[name]["sheetId"], "index": index},
            "fields": "index"}}]})
    final = [s["properties"]["title"] for s in sh.fetch_sheet_metadata()["sheets"]]
    print("\nитог:  ", final)
    print("совпало с целевым:", "да" if final == target else "НЕТ")


if __name__ == "__main__":
    main()
