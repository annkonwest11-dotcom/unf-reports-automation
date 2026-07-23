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

print("🔍 Не найденные контрагенты:\n")

sheets_to_check = [('ДАННЫЕ_Губарев', 'Губарев'), ('ДАННЫЕ_Перфильев', 'Перфильев')]

for sheet_name, manager in sheets_to_check:
    try:
        ws = sheet.worksheet(sheet_name)
        data = ws.get_all_values()

        unfound = []

        for idx, row in enumerate(data[1:], start=2):
            if len(row) < 7 or not row[0].strip():
                continue

            contractor = row[0].strip()
            lookup_result = row[5].strip() if len(row) > 5 else ""

            # Если результат VLOOKUP пуст или ошибка
            if not lookup_result or lookup_result.startswith('#'):
                unfound.append((idx, contractor))

        print(f"📋 {sheet_name} ({manager}): {len(unfound)} не найдено\n")

        # Показываю первые 20
        for row_idx, contractor in unfound[:20]:
            print(f"  {row_idx}. {contractor}")

        if len(unfound) > 20:
            print(f"  ... и ещё {len(unfound) - 20}")

        print()

    except Exception as e:
        print(f"⚠️  {sheet_name}: {e}\n")
