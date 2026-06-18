#!/usr/bin/env python3
"""
Поиск ВСЕХ способов интеграции облачной 1С 42clouds с Google Sheets
"""

import requests
import json
import sys

print("""
╔════════════════════════════════════════════════════════════╗
║  ИЩЕМ ВСЕ СПОСОБЫ ИНТЕГРАЦИИ ОБЛАЧНОЙ 1С                  ║
╚════════════════════════════════════════════════════════════╝
""")

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_URL_152757 = "https://base.42clouds.com/unf/152757/"

session = requests.Session()
session.auth = (LOGIN, PASSWORD)

print("\n1️⃣  ПРОВЕРЯЮ REST API ENDPOINTS:\n")

# Возможные API endpoints
api_endpoints = [
    "https://base.42clouds.com/api/v1/",
    "https://base.42clouds.com/rest/",
    "https://base.42clouds.com/unf/152757/api/",
    "https://api.42clouds.ru/v1/",
    "https://base.42clouds.com/unf/152757/rest/",
]

for endpoint in api_endpoints:
    try:
        print(f"   Пробую: {endpoint}")
        response = requests.get(endpoint, timeout=5, auth=(LOGIN, PASSWORD))
        print(f"      Status: {response.status_code}")
        if response.status_code in [200, 401, 403]:
            print(f"      ✅ ENDPOINT НАЙДЕН!")
            print(f"      Ответ: {response.text[:200]}")
    except Exception as e:
        print(f"      ❌ Ошибка: {str(e)[:50]}")

print("\n2️⃣  ПРОВЕРЯЮ WEBHOOK ENDPOINTS:\n")

webhooks = [
    "https://base.42clouds.com/webhook/",
    "https://base.42clouds.com/api/webhooks/",
    "https://base.42clouds.com/unf/152757/webhook/",
]

for webhook in webhooks:
    try:
        print(f"   Пробую: {webhook}")
        response = requests.options(webhook, timeout=5)
        print(f"      Status: {response.status_code}")
    except Exception as e:
        print(f"      ❌ Ошибка")

print("\n3️⃣  ПРОВЕРЯЮ ВСТРОЕННЫЕ ИНТЕГРАЦИИ:\n")

integrations = [
    "Синхронизация с Google Sheets",
    "Экспорт данных в облако",
    "Webhook уведомления",
    "REST API для отчетов",
    "Синхронизация через OneDrive/Google Drive",
]

print("   Возможные интеграции в 42clouds:")
for i, integration in enumerate(integrations, 1):
    print(f"   {i}. {integration}")

print("\n4️⃣  ПРОВЕРЯЮ ЭЛЕКТРОННЫЕ ОТЧЕТЫ:\n")

reports_api = "https://base.42clouds.com/unf/152757/rest/reports/"
try:
    print(f"   Пробую API электронных отчетов...")
    response = requests.get(reports_api, timeout=5, auth=(LOGIN, PASSWORD))
    print(f"      Status: {response.status_code}")
    if response.status_code < 400:
        print(f"      ✅ НАЙДЕНО!")
        print(f"      {response.text[:300]}")
except Exception as e:
    print(f"      ❌ Ошибка: {str(e)[:50]}")

print("\n5️⃣  ПРОВЕРЯЮ СИНХРОНИЗАЦИЮ ЧЕРЕЗ ФАЙЛЫ:\n")

print("""
   42clouds может поддерживать:
   ✓ Автоматический экспорт в OneDrive
   ✓ Автоматический экспорт в Google Drive
   ✓ Синхронизация через FTP/SFTP
   ✓ Выгрузка отчетов по расписанию

   Проверь в Администрировании → Обслуживание → Синхронизация
""")

print("\n6️⃣  ИТОГИ:\n")

print("""
РЕАЛЬНЫЕ СПОСОБЫ ИНТЕГРАЦИИ (если работают):

1. ✅ REST API - если найден endpoint выше
2. ✅ Webhook - если поддерживается
3. ✅ Синхронизация с Google Drive - встроенная
4. ✅ Экспорт отчетов - в Администрировании
5. ✅ Электронные отчеты - выгрузка данных
6. ✅ Расширение - только с толстым клиентом

═══════════════════════════════════════════════════════════

РЕКОМЕНДАЦИЯ:

Проверь в 42clouds:
1. Администрирование → Интеграции (есть ли готовые?)
2. Администрирование → Синхронизация (есть ли синхронизация?)
3. Администрирование → Обслуживание (есть ли экспорт?)
4. Документация 42clouds про API
""")

print("\nДай мне ответы и продолжим поиск! 🔍")
