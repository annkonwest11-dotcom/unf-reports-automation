#!/usr/bin/env python3
"""
Восстанавливает список сотрудников из Google Sheets.
Показывает, кого не хватает в employees.json для переустановки регистрации.
"""

import json
import os
from dotenv import load_dotenv
from sheets import SheetsClient

load_dotenv()

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
EMPLOYEES_FILE = os.path.join(os.path.dirname(__file__), "employees.json")

sheets = SheetsClient(CREDENTIALS_PATH, SPREADSHEET_ID)

# Получаем всех сотрудников из Google Sheets
ws = sheets._get_sheet()
all_rows = ws.get_all_values()

# Получаем сотрудников из секции "основные смены"
section_rows = sheets._section_employee_rows(all_rows, 'основные смены')
print(f"✅ Найдено сотрудников в листе СМЕНЫ: {len(section_rows)}\n")

# Собираем имена всех сотрудников
employees_in_sheet = []
for row_num in sorted(section_rows):
    row = all_rows[row_num - 1]
    name = row[1].strip() if len(row) > 1 else ''
    if name:
        employees_in_sheet.append(name)
        print(f"  • {name}")

# Загружаем текущий список зарегистрированных
with open(EMPLOYEES_FILE, encoding='utf-8') as f:
    registered = json.load(f)

registered_names = set(registered.values())

# Находим разницу
missing = [name for name in employees_in_sheet if name not in registered_names]

print(f"\n📊 Статистика:")
print(f"  Зарегистрировано в Telegram: {len(registered)}")
print(f"  Всего в таблице: {len(employees_in_sheet)}")
if missing:
    print(f"  ❌ Не зарегистрировано: {len(missing)}")
    print(f"\n⚠️  Сотрудники, которые должны пройти регистрацию (/start в личке):")
    for name in missing:
        print(f"    • {name}")
else:
    print(f"  ✅ Все сотрудники зарегистрированы!")

print(f"\n💡 Совет: Попросите этих сотрудников написать боту /start в личку и ввести свое имя.")
