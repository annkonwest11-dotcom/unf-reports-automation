#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/Users/anna/claude-test/credentials.json',
    scopes=SCOPES
)
client = gspread.authorize(creds)

SPREADSHEET_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
sheet = client.open_by_key(SPREADSHEET_ID)

print("📊 Результаты VLOOKUP в ДАННЫЕ листах:\n")

sheets_to_check = ['ДАННЫЕ_Губарев', 'ДАННЫЕ_Перфильев']

for sheet_name in sheets_to_check:
    try:
        ws = sheet.worksheet(sheet_name)
        data = ws.get_all_values()

        contractors_total = 0
        found = 0
        not_found = 0

        for idx, row in enumerate(data[1:], start=2):
            if len(row) < 7 or not row[0].strip():
                continue

            contractor = row[0].strip()
            lookup_result = row[5].strip() if len(row) > 5 else ""

            contractors_total += 1

            # Проверяю результат VLOOKUP (столбец F)
            if lookup_result and not lookup_result.startswith('#'):
                found += 1
            else:
                not_found += 1

        total = found + not_found
        percent = (found / total * 100) if total > 0 else 0

        print(f"📋 {sheet_name}")
        print(f"   Всего контрагентов: {total}")
        print(f"   ✅ Найдено: {found} ({percent:.1f}%)")
        print(f"   ❌ Не найдено: {not_found}")
        print()

    except Exception as e:
        print(f"⚠️  {sheet_name}: {e}\n")

print("✅ Проверка завершена!")
