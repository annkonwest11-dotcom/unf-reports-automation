#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/Users/anna/claude-test/credentials.json',
    scopes=SCOPES
)
client = gspread.authorize(creds)

SPREADSHEET_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
sheet = client.open_by_key(SPREADSHEET_ID)

print("🔍 Проверка дублей в СПРАВОЧНИКЕ...\n")

ref_sheet = sheet.worksheet('СПРАВОЧНИК')
data = ref_sheet.get_all_values()

print(f"Всего строк в СПРАВОЧНИКЕ: {len(data)}")
print(f"Заголовок: {data[0]}\n")

# Считаю контрагентов (пропускаю заголовок и пустые)
contractors = [row[0].strip() for row in data[1:] if row and row[0].strip()]
print(f"Уникальных контрагентов: {len(set(contractors))}")
print(f"Всего контрагентов (с дублями): {len(contractors)}\n")

# Нахожу дубли
counter = Counter(contractors)
duplicates = {k: v for k, v in counter.items() if v > 1}

if duplicates:
    print(f"⚠️  Найдено {len(duplicates)} дублей:")
    for contractor, count in sorted(duplicates.items()):
        print(f"  • '{contractor}' — {count} раз")
else:
    print("✅ Дублей не найдено!")

# Последние 10 добавленных
print(f"\n📝 Последние 10 контрагентов в СПРАВОЧНИКЕ:")
for idx, contractor in enumerate(contractors[-10:], len(contractors)-9):
    print(f"  {idx}. {contractor}")
