#!/usr/bin/env python3
"""Синхронизирует последний лист КПИ-таблицы → КПИ_ДАННЫЕ зарплатной таблицы."""

import os
import gspread
from google.oauth2.service_account import Credentials

KPI_TABLE    = "1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4"
SALARY_TABLE = "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"
CREDS_FILE   = os.path.join(os.path.dirname(__file__), "credentials.json")
SCOPES       = ["https://www.googleapis.com/auth/spreadsheets"]

def sync():
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)

    # Берём последний лист КПИ-таблицы
    kpi_book = gc.open_by_key(KPI_TABLE)
    sheet = kpi_book.worksheets()[-1]

    # Читаем данные (A1:M200)
    values = sheet.get("A1:M200", value_render_option="UNFORMATTED_VALUE")

    # Нормализуем до 13 столбцов
    normalized = []
    for row in values:
        padded = list(row) + [''] * (13 - len(row))
        normalized.append(padded[:13])

    # Очищаем и пишем в КПИ_ДАННЫЕ
    salary_book = gc.open_by_key(SALARY_TABLE)
    ws = salary_book.worksheet("КПИ_ДАННЫЕ")
    ws.batch_clear(["A1:M200"])
    ws.update(normalized, "A1", value_input_option="RAW")

    print(f"✓ Синхронизировано: '{sheet.title}' → КПИ_ДАННЫЕ ({len(normalized)} строк)")

if __name__ == "__main__":
    sync()
