#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials
import time

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/Users/anna/claude-test/credentials.json',
    scopes=SCOPES
)
client = gspread.authorize(creds)

SPREADSHEET_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
sheet = client.open_by_key(SPREADSHEET_ID)

print("📊 Ищу недостающие контрагенты...\n")

# Читаю СПРАВОЧНИК
ref_sheet = sheet.worksheet('СПРАВОЧНИК')
ref_data = ref_sheet.get_all_values()
existing = set()
for row in ref_data[1:]:
    if row and row[0].strip():
        existing.add(row[0].strip())

print(f"В СПРАВОЧНИКЕ: {len(existing)} контрагентов\n")

# Ищу контрагентов в ДАННЫЕ_Губарев и ДАННЫЕ_Перфильев
sheets_to_check = ['ДАННЫЕ_Губарев', 'ДАННЫЕ_Перфильев']
missing = set()

for sheet_name in sheets_to_check:
    try:
        ws = sheet.worksheet(sheet_name)
        data = ws.get_all_values()

        for idx, row in enumerate(data[1:], start=2):
            if len(row) < 1 or not row[0].strip():
                continue

            contractor = row[0].strip()

            # Пропускаю пустые и ошибки
            if not contractor or contractor.startswith('#'):
                continue

            if contractor not in existing:
                missing.add(contractor)

    except Exception as e:
        print(f"⚠️  {sheet_name}: {e}")

print(f"Не найдено в СПРАВОЧНИКЕ: {len(missing)} уникальных контрагентов\n")

if not missing:
    print("✅ Все контрагенты уже в СПРАВОЧНИКЕ!")
else:
    print("Добавляю недостающих...\n")

    count = 0
    for idx, contractor in enumerate(sorted(missing), 1):
        try:
            new_row = [contractor, "", "", "", "Нет", "", "Активен", ""]
            ref_sheet.append_row(new_row)
            count += 1

            if idx % 5 == 0:
                print(f"  {idx}. ✅ {contractor}")
                time.sleep(0.2)  # Небольшая задержка каждые 5 добавлений

        except Exception as e:
            if "429" in str(e):
                print(f"\n⏸️  API лимит достигнут на {idx}. Добавлено {count} из {len(missing)}")
                print(f"   Последний: {contractor}")
                break
            else:
                print(f"  ❌ {contractor}: {e}")

    print(f"\n🎉 Успешно добавлено: {count} новых контрагентов")
