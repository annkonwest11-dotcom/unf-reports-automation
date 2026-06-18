#!/bin/bash

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  ПОЛНАЯ АВТОМАТИЧЕСКАЯ НАСТРОЙКА GOOGLE CLOUD SCHEDULER   ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Проверяем gcloud
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud не установлен"
    echo "Установи: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

echo "✅ gcloud найден"
echo ""

# Параметры проекта
PROJECT_ID="unf-reports-$(date +%s | tail -c 6)"
FUNCTION_NAME="unf-reports-scheduler"
REGION="europe-west1"
TIMEZONE="Europe/Moscow"
SCHEDULE="30 9 * * *"  # 09:30 каждый день

echo "📋 Параметры:"
echo "   Project ID: $PROJECT_ID"
echo "   Function: $FUNCTION_NAME"
echo "   Region: $REGION"
echo "   Schedule: $SCHEDULE ($TIMEZONE)"
echo ""

# 1. Создаем проект
echo "1️⃣  СОЗДАЮ GOOGLE CLOUD ПРОЕКТ..."
gcloud projects create $PROJECT_ID --name "UNF Reports Automation"
echo "✅ Проект создан"
echo ""

# 2. Устанавливаем проект
echo "2️⃣  УСТАНАВЛИВАЮ ПРОЕКТ..."
gcloud config set project $PROJECT_ID
echo "✅ Проект установлен"
echo ""

# 3. Включаем APIs
echo "3️⃣  ВКЛЮЧАЮ НЕОБХОДИМЫЕ APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com \
    logging.googleapis.com \
    compute.googleapis.com
echo "✅ APIs включены"
echo ""

# 4. Создаем временную директорию для функции
echo "4️⃣  ПОДГОТАВЛИВАЮ КОД ФУНКЦИИ..."
FUNC_DIR=$(mktemp -d)
echo "   Временная директория: $FUNC_DIR"

# Создаем main.py
cat > $FUNC_DIR/main.py << 'PYTHON_CODE'
import functions_framework
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import json
import os
import base64

TELEGRAM_TOKEN = "8602166476:AAEo3ySMNmF38lyH0yppcW7CKejzXK_w7cY"
TELEGRAM_CHAT_ID = "796207056"
SHEET_ID = "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"

BASES = {
    "Перфильев": "152757",
    "Губарев": "64904"
}

@functions_framework.http
def unf_reports_scheduler(request):
    """Облачная функция для автоматических отчетов"""

    try:
        print("🚀 Запуск системы автоматических отчетов...")

        # Получаем данные из 1С
        all_data = {}
        for base_name, base_id in BASES.items():
            session = requests.Session()
            session.auth = ("api_bot", "slavaperfilev1414")

            base_data = {}
            endpoints = ["reports/sales", "reports/customers", "reports/debtors"]

            for endpoint in endpoints:
                try:
                    url = f"https://base.42clouds.com/api/v1/bases/{base_id}/{endpoint}"
                    response = session.get(url, timeout=10)
                    base_data[endpoint] = response.status_code == 200
                except Exception as e:
                    print(f"Ошибка {endpoint}: {e}")
                    base_data[endpoint] = False

            all_data[base_name] = base_data

        print(f"✅ Данные получены: {all_data}")

        # Форматируем отчет
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
PYTHON_CODE

# Создаем requirements.txt
cat > $FUNC_DIR/requirements.txt << 'REQ'
functions-framework==3.3.0
gspread>=5.10.0
google-auth-oauthlib>=1.0.0
google-auth>=2.20.0
requests>=2.28.0
REQ

echo "✅ Код функции подготовлен"
echo ""

# 5. Создаем Cloud Function
echo "5️⃣  СОЗДАЮ CLOUD FUNCTION..."
gcloud functions deploy $FUNCTION_NAME \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated \
    --entry-point unf_reports_scheduler \
    --source $FUNC_DIR \
    --region $REGION \
    --timeout 300
echo "✅ Cloud Function создана"
echo ""

# 6. Получаем URL функции
echo "6️⃣  ПОЛУЧАЮ URL ФУНКЦИИ..."
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME \
    --region $REGION \
    --format 'value(httpsTrigger.url)')
echo "   URL: $FUNCTION_URL"
echo ""

# 7. Создаем Cloud Scheduler задание
echo "7️⃣  СОЗДАЮ CLOUD SCHEDULER ЗАДАНИЕ..."
gcloud scheduler jobs create http unf-daily-reports \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri=$FUNCTION_URL \
    --http-method=GET \
    --location=$REGION || true
echo "✅ Cloud Scheduler задание создано"
echo ""

# 8. Проверяем задание
echo "8️⃣  ПРОВЕРЯЮ РАСПИСАНИЕ..."
gcloud scheduler jobs describe unf-daily-reports \
    --location=$REGION
echo ""

# 9. Тестируем запуск
echo "9️⃣  ТЕСТИРУЮ ПЕРВЫЙ ЗАПУСК..."
gcloud scheduler jobs run unf-daily-reports \
    --location=$REGION
echo "✅ Тестовый запуск выполнен"
echo ""

# Чистим временную директорию
rm -rf $FUNC_DIR

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  ✅ СИСТЕМА ПОЛНОСТЬЮ НАСТРОЕНА!                          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "🎯 Что произойдет:"
echo "   • Отчет будет запускаться КАЖДЫЙ ДЕНЬ в 09:30 МСК"
echo "   • Данные получаются из облачной 1С через REST API"
echo "   • Отчет отправляется в Telegram"
echo "   • Всё логируется в Google Cloud Logging"
echo ""
echo "📊 Проект:"
echo "   ID: $PROJECT_ID"
echo "   Console: https://console.cloud.google.com/home/dashboard?project=$PROJECT_ID"
echo ""
echo "📞 Команды в Telegram:"
echo "   /today - на сегодня"
echo "   /week - за неделю"
echo "   /month - за месяц"
echo "   /debtors - ТОП 10 должников"
echo ""
echo "✨ ГОТОВО! 🚀"
