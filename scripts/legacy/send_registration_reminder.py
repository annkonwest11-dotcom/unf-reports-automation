#!/usr/bin/env python3
"""
Отправляет приватные сообщения каждому сотруднику о необходимости переустановить регистрацию.
"""

import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from sheets import SheetsClient

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")

bot = Bot(token=BOT_TOKEN)
sheets = SheetsClient(CREDENTIALS_PATH, SPREADSHEET_ID)

# Получаем список сотрудников из Google Sheets
ws = sheets._get_sheet()
all_rows = ws.get_all_values()
section_rows = sheets._section_employee_rows(all_rows, 'основные смены')

employees = []
for row_num in sorted(section_rows):
    row = all_rows[row_num - 1]
    name = row[1].strip() if len(row) > 1 else ''
    if name:
        employees.append(name)

print(f"📋 Найдено сотрудников: {len(employees)}\n")

# Сообщение для отправки
MESSAGE = """🤖 Привет! Система регистрации требует переустановку.

Чтобы продолжить отправлять отчеты о смене, выполни пожалуйста:

1️⃣ Отправь мне команду: /start
2️⃣ Напиши свое имя и фамилию (как в таблице смен)

После этого сможешь нормально работать! ✅

Если это сообщение ошибочно, просто проигнорируй его."""

print("📝 Текст сообщения:")
print("-" * 50)
print(MESSAGE)
print("-" * 50)
print(f"\n⚠️  Внимание! Это отправит сообщение {len(employees)} сотрудникам")
print("Это требует знания их Telegram ID, которых нет в системе.")
print("\n💡 Рекомендация: Отправь сообщение в групповой чат вместо этого.")
print("\nТекст для группового чата:")
print("=" * 50)

group_message = f"""⚠️ Требуется переустановка регистрации!

Система потеряла данные регистрации. Каждому нужно переустановить:

1️⃣ Напиши мне (@shift_job_bot) в личку
2️⃣ Отправь /start
3️⃣ Напиши свое имя и фамилию (как в таблице смен)

После этого сможете отправлять отчеты! ✅

Спасибо за понимание! 🙏"""

print(group_message)
print("=" * 50)
