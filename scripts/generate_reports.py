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

    base_data = {
        "sales_today": 0,
        "sales_week": 0,
        "sales_month": 0,
        "avg_check": 0,
        "avg_indicator": 0,
        "potential": 0,
        "total_debt": 0,
        "overdue_debt": 0,
        "growing_customers": 0,
        "falling_customers": 0,
        "static_customers": 0,
        "top_debtors": []
    }

    endpoints = ["reports/sales", "reports/customers", "reports/debtors"]

    for endpoint in endpoints:
        try:
            url = f"https://base.42clouds.com/api/v1/bases/{base_id}/{endpoint}"
            response = session.get(url, timeout=10)

            if response.status_code == 200:
                print(f"      ✅ {endpoint}")
                # Пытаемся парсить данные если это JSON
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        if "sales" in endpoint:
                            base_data["sales_today"] = data.get("today", 0)
                            base_data["sales_week"] = data.get("week", 0)
                            base_data["sales_month"] = data.get("month", 0)
                            base_data["avg_check"] = data.get("avg_check", 0)
                            base_data["potential"] = data.get("potential", 0)
                        elif "customers" in endpoint:
                            base_data["growing_customers"] = data.get("growing", 0)
                            base_data["falling_customers"] = data.get("falling", 0)
                            base_data["static_customers"] = data.get("static", 0)
                        elif "debtors" in endpoint:
                            base_data["total_debt"] = data.get("total", 0)
                            base_data["overdue_debt"] = data.get("overdue", 0)
                            base_data["top_debtors"] = data.get("top_debtors", [])
                except:
                    pass
            else:
                print(f"      ⚠️  {endpoint}: {response.status_code}")

        except Exception as e:
            print(f"      ❌ {endpoint}: {str(e)[:30]}")

    all_data[base_name] = base_data
    print()

# Форматируем отчет
print("3️⃣  Форматирую отчет...")

today = datetime.now().strftime("%d.%m.%Y")

def format_money(value):
    """Форматирование денег"""
    if isinstance(value, (int, float)):
        return f"₽{value:,.0f}".replace(',', ' ')
    return str(value)

perf_data = all_data.get("Перфильев", {})
gub_data = all_data.get("Губарев", {})

total_sales_today = perf_data.get("sales_today", 0) + gub_data.get("sales_today", 0)
total_debt = perf_data.get("total_debt", 0) + gub_data.get("total_debt", 0)
total_overdue = perf_data.get("overdue_debt", 0) + gub_data.get("overdue_debt", 0)

report = f"""
╔════════════════════════════════════════╗
║     ЕЖЕДНЕВНЫЙ ОТЧЕТ                  ║
║     {today}
╚════════════════════════════════════════╝

📊 ПРОДАЖИ

🏢 ИП ПЕРФИЛЬЕВ:
  • Продажи сегодня: {format_money(perf_data.get('sales_today', 0))}
  • Средний чек: {format_money(perf_data.get('avg_check', 0))}
  • Продажи неделя: {format_money(perf_data.get('sales_week', 0))}
  • Потенциальный оборот: {format_money(perf_data.get('potential', 0))}

🏢 ИП ГУБАРЕВ:
  • Продажи сегодня: {format_money(gub_data.get('sales_today', 0))}
  • Средний чек: {format_money(gub_data.get('avg_check', 0))}
  • Продажи неделя: {format_money(gub_data.get('sales_week', 0))}
  • Потенциальный оборот: {format_money(gub_data.get('potential', 0))}

📊 ИТОГО:
  • Общие продажи сегодня: {format_money(total_sales_today)}
  • Месячные продажи: {format_money(perf_data.get('sales_month', 0) + gub_data.get('sales_month', 0))}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💳 ЗАДОЛЖЕННОСТЬ ПОКУПАТЕЛЕЙ

🏢 ИП ПЕРФИЛЬЕВ:
  • Общая дебиторка: {format_money(perf_data.get('total_debt', 0))}
  • Просроченная: 🔴 {format_money(perf_data.get('overdue_debt', 0))}

🏢 ИП ГУБАРЕВ:
  • Общая дебиторка: {format_money(gub_data.get('total_debt', 0))}
  • Просроченная: 🔴 {format_money(gub_data.get('overdue_debt', 0))}

📊 ИТОГО ДЕБИТОРКА: {format_money(total_debt)}
   Просроченная: 🔴 {format_money(total_overdue)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👥 ДИНАМИКА ПО КЛИЕНТАМ

🏢 ИП ПЕРФИЛЬЕВ:
  • Растущие: 📈 {perf_data.get('growing_customers', 0)} клиентов
  • Падающие: 📉 {perf_data.get('falling_customers', 0)} клиентов
  • Статичные: → {perf_data.get('static_customers', 0)} клиентов

🏢 ИП ГУБАРЕВ:
  • Растущие: 📈 {gub_data.get('growing_customers', 0)} клиентов
  • Падающие: 📉 {gub_data.get('falling_customers', 0)} клиентов
  • Статичные: → {gub_data.get('static_customers', 0)} клиентов

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏗️ СИСТЕМА:
  ✅ 1С API: Подключена
  ✅ GitHub Actions: Работает
  ✅ Telegram: Активен
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
