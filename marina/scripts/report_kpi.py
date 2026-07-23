#!/usr/bin/env python3
"""Читает КПИ-таблицу Марины и выводит текущий статус: КПИ ДАННЫЕ + ИТОГ (зарплата).

Работает read-only: ничего не меняет в таблице, только показывает снимок.
Запуск:  python3 marina/scripts/report_kpi.py
"""

import os
import gspread
from google.oauth2.service_account import Credentials

# Таблица КПИ Марины
MARINA_TABLE = "1XhGBVBYbin56iOUPs944BnQjZJDIKE39pdP_lpr1PIo"

# credentials.json лежит в корне репозитория (на два уровня выше этого файла)
REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREDS_FILE = os.path.join(REPO_ROOT, "credentials.json")
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _print_sheet(book, title):
    """Печатает непустые строки листа title, если он существует."""
    try:
        ws = book.worksheet(title)
    except gspread.WorksheetNotFound:
        print(f"  (лист «{title}» не найден)")
        return
    rows = ws.get_all_values()
    printed = 0
    for row in rows:
        if any(cell.strip() for cell in row):
            cells = [c for c in row if c.strip()]
            print("  " + " | ".join(cells))
            printed += 1
    if printed == 0:
        print("  (пусто)")


def report():
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    book = gc.open_by_key(MARINA_TABLE)

    print(f"📊 КПИ Марина — «{book.title}»")
    print(f"   Листы: {', '.join(ws.title for ws in book.worksheets())}\n")

    print("═" * 50)
    print("KPI ДАННЫЕ")
    print("═" * 50)
    _print_sheet(book, "KPI ДАННЫЕ")

    print("\n" + "═" * 50)
    print("ИТОГ (зарплата)")
    print("═" * 50)
    _print_sheet(book, "ИТОГ")


if __name__ == "__main__":
    report()
