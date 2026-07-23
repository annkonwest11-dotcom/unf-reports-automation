import functions_framework
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import json
import os

TELEGRAM_TOKEN = "8602166476:AAEo3ySMNmF38lyH0yppcW7CKejzXK_w7cY"
TELEGRAM_CHAT_ID = "796207056"
SHEET_ID = "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"

BASES = {
    "Перфильев": "152757",
    "Губарев": "64904"
}

@functions_framework.http
def unf_reports_scheduler(request):
    """
    Облачная функция для автоматических отчетов
    Запускается по расписанию (09:30 каждый день)
    """

    try:
        print("🚀 Запуск системы автоматических отчетов...")

        # Получаем данные из 1С
        all_data = {}
        for base_name, base_id in BASES.items():
            session = requests.Session()
            session.auth = ("api_bot", "slavaperfilev1414")

            base_data = {}
            for endpoint in ["reports/sales", "reports/customers", "reports/debtors"]:
                try:
                    url = f"https://base.42clouds.com/api/v1/bases/{base_id}/{endpoint}"
                    response = session.get(url, timeout=10)
                    base_data[endpoint] = response.status_code == 200
                except:
                    base_data[endpoint] = False

            all_data[base_name] = base_data

        print(f"✅ Данные получены: {all_data}")

        # Форматируем отчет для Telegram
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

Команды для отчетов:
/today - на сегодня
/week - за неделю
/month - за месяц
/debtors - ТОП 10 должников
"""

        # Отправляем в Telegram
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": report,
            "parse_mode": "HTML"
        }

        response = requests.post(url, json=data, timeout=10)

        if response.status_code == 200:
            print("✅ Отчет отправлен в Telegram")

            return {
                'status': 'success',
                'message': 'Отчет успешно создан и отправлен',
                'timestamp': datetime.now().isoformat(),
                'data': all_data
            }, 200
        else:
            print(f"❌ Ошибка Telegram: {response.status_code}")
            return {
                'status': 'error',
                'message': f'Ошибка Telegram: {response.status_code}'
            }, 500

    except Exception as e:
        print(f"❌ Ошибка: {str(e)}")
        return {
            'status': 'error',
            'message': str(e)
        }, 500
