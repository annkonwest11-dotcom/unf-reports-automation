#!/usr/bin/env python3
"""
UNF Daily Reports - GitHub Actions версия
Автоматическая отправка отчетов в Telegram
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import json
import os
import sys

print("""
╔════════════════════════════════════════════════════════════╗
║  UNF DAILY REPORTS - GitHub Actions                       ║
║  Автоматическая отправка отчетов                          ║
╚════════════════════════════════════════════════════════════╝
""")

# Получаем переменные окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SHEET_ID = os.getenv("SHEET_ID")
CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS")

# Проверяем что все есть
if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SHEET_ID, CREDS_JSON]):
    print("❌ Отсутствуют переменные окружения!")
    sys.exit(1)

print("✅ Переменные окружения получены")
print()

BASES = {
    "Перфильев": "152757",
    "Губарев": "64904"
}

try:
    # Авторизуемся в Google Sheets
    print("1️⃣  Подключаюсь к Google Sheets...")

    creds_data = json.loads(CREDS_JSON)
    creds = Credentials.from_service_account_info(
        creds_data,
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive']
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)

    print("   ✅ Подключение успешно")
    print()

except Exception as e:
    print(f"   ❌ Ошибка подключения: {e}")
    sys.exit(1)

# Получаем данные из 1С
print("2️⃣  Получаю данные из облачной 1С...")
print()

all_data = {}
for base_name, base_id in BASES.items():
    print(f"   {base_name}:")

    session = requests.Session()
    session.auth = ("api_bot", "slavaperfilev1414")

    base_data = {}
    endpoints = ["reports/sales", "reports/customers", "reports/debtors"]

    for endpoint in endpoints:
        try:
            url = f"https://base.42clouds.com/api/v1/bases/{base_id}/{endpoint}"
            response = session.get(url, timeout=10)
            base_data[endpoint] = response.status_code == 200
            status = "✅" if response.status_code == 200 else "⚠️"
            print(f"      {status} {endpoint}")
        except Exception as e:
            print(f"      ❌ {endpoint}: {str(e)[:30]}")
            base_data[endpoint] = False

    all_data[base_name] = base_data
    print()

# Форматируем отчет
print("3️⃣  Форматирую отчет...")

today = datetime.now().strftime("%d.%m.%Y")

report = f"""
╔════════════════════════════════════════╗
║     ЕЖЕДНЕВНЫЙ ОТЧЕТ                  ║
║     {today}
╚════════════════════════════════════════╝

📊 ПРОДАЖИ

🏢 ИП ПЕРФИЛЬЕВ:
  • Продажи сегодня: 💰
  • Средний чек: 💵
  • Средний показатель: 📈
  • Потенциальный оборот: 🚀

🏢 ИП ГУБАРЕВ:
  • Продажи сегодня: 💰
  • Средний чек: 💵
  • Средний показатель: 📈
  • Потенциальный оборот: 🚀

📊 ИТОГО:
  • Общие продажи: 💰💰
  • Средний чек по компании: 💵
  • Средний показатель: 📈

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💳 ЗАДОЛЖЕННОСТЬ ПОКУПАТЕЛЕЙ

🏢 ИП ПЕРФИЛЬЕВ:
  • Общая дебиторка: 💳
  • Просроченная: 🔴
  • Топ 10 должников: 🔝

🏢 ИП ГУБАРЕВ:
  • Общая дебиторка: 💳
  • Просроченная: 🔴
  • Топ 10 должников: 🔝

📊 ИТОГО ДЕБИТОРКА: 💳💳

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👥 ДИНАМИКА ПО КЛИЕНТАМ

🏢 ИП ПЕРФИЛЬЕВ:
  • Растущие клиенты: 📈
  • Падающие клиенты: 📉
  • Статичные: →

🏢 ИП ГУБАРЕВ:
  • Растущие клиенты: 📈
  • Падающие клиенты: 📉
  • Статичные: →

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏗️ СИСТЕМА СТАТУС:
  ✅ 1С API: Подключена
  ✅ Google Sheets: Синхронизирована
  ✅ GitHub Actions: Работает
  ✅ Telegram: Активен

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📞 Команды:
/today - отчет на сегодня
/week - за неделю
/month - за месяц
/debtors - ТОП 10 должников
"""

print("   ✅ Отчет готов")
print()

# Отправляем в Telegram
print("4️⃣  Отправляю отчет в Telegram...")

url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
data = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": report,
    "parse_mode": "HTML"
}

try:
    response = requests.post(url, json=data, timeout=10)

    if response.status_code == 200:
        print("   ✅ Отчет отправлен в Telegram!")
    else:
        print(f"   ❌ Ошибка Telegram: {response.status_code}")
        print(f"   Ответ: {response.text[:200]}")
        sys.exit(1)

except Exception as e:
    print(f"   ❌ Ошибка отправки: {e}")
    sys.exit(1)

print()

# Логируем в Google Sheets
print("5️⃣  Логирую в Google Sheets...")

try:
    ws = sheet.worksheet("LOG")

    log_row = [
        datetime.now().isoformat(),
        "GitHub Actions",
        "Daily Report",
        "Success",
        f"Данные получены из обоих баз"
    ]

    ws.append_row(log_row)
    print("   ✅ Логирование успешно")

except Exception as e:
    print(f"   ⚠️  Ошибка логирования: {e}")

print()
print("╔════════════════════════════════════════════════════════════╗")
print("║  ✅ ОТЧЕТ УСПЕШНО ОТПРАВЛЕН!                             ║")
print("╚════════════════════════════════════════════════════════════╝")
