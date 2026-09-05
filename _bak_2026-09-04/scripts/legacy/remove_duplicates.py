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

print("🗑️  Удаление дублей из СПРАВОЧНИКА...\n")

ref_sheet = sheet.worksheet('СПРАВОЧНИК')
data = ref_sheet.get_all_values()

print(f"Было строк: {len(data)}")

# Сохраняю заголовок
header = data[0]
rows = data[1:]

# Удаляю пустые строки
rows = [row for row in rows if row and row[0].strip()]

# Сортирую и удаляю дубли (оставляю первый экземпляр каждого контрагента)
seen = set()
unique_rows = []

for row in rows:
    contractor = row[0].strip()
    if contractor not in seen:
        seen.add(contractor)
        unique_rows.append(row)
    else:
        print(f"  ❌ Удаляю дубль: {contractor}")

print(f"\nУдалено {len(rows) - len(unique_rows)} дублей")
print(f"Осталось уникальных: {len(unique_rows)}\n")

# Перезаписываю лист
print("📝 Перезаписываю СПРАВОЧНИК...")
ref_sheet.clear()
ref_sheet.append_row(header)

# Добавляю уникальные строки партиями по 20 (чтобы не превышать лимит API)
for i in range(0, len(unique_rows), 20):
    batch = unique_rows[i:i+20]
    for row in batch:
        ref_sheet.append_row(row)
    print(f"  {i+len(batch)}/{len(unique_rows)} добавлено")

print(f"\n✅ Готово! В СПРАВОЧНИКЕ теперь {len(unique_rows)} уникальных контрагентов")
