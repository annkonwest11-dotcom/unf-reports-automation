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

print("🔍 Удаляю дубли из СПРАВОЧНИКА (безопасно)...\n")

ref_sheet = sheet.worksheet('СПРАВОЧНИК')
data = ref_sheet.get_all_values()

# Находю строки для удаления (дубли)
seen = set()
rows_to_delete = []  # Строки с индексами которые нужно удалить

for idx, row in enumerate(data[1:], start=2):  # Начиная со строки 2 (после заголовка)
    if not row or not row[0].strip():
        continue

    contractor = row[0].strip()

    if contractor in seen:
        # Это дубль - пометь для удаления
        rows_to_delete.append(idx)
        print(f"  ❌ Дубль в строке {idx}: {contractor}")
    else:
        seen.add(contractor)

print(f"\nОбнаружено дублей для удаления: {len(rows_to_delete)}")

if rows_to_delete:
    print(f"\nУдаляю {len(rows_to_delete)} дублей (это может занять время)...")

    # Удаляю строки с конца (чтобы индексы не смещались)
    for row_idx in sorted(rows_to_delete, reverse=True):
        try:
            ref_sheet.delete_rows(row_idx, 1)
        except Exception as e:
            print(f"  ⚠️  Ошибка при удалении строки {row_idx}: {e}")

print(f"\n✅ Готово! Удалено {len(rows_to_delete)} дублей")

# Проверка результата
data = ref_sheet.get_all_values()
contractors = [r[0].strip() for r in data[1:] if r and r[0].strip()]
print(f"   Осталось контрагентов: {len(set(contractors))}")
