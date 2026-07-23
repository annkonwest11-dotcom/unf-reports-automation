#!/usr/bin/env python3
"""
Проверка деталей договоров - ищем сроки платежа
"""

import requests
import base64
import json

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"
BASE_URL = f"https://base.42clouds.com/unf/{BASE_ID}/odata/standard.odata/"

def get_basic_auth():
    creds = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json"
    }

import urllib3
urllib3.disable_warnings()

print("""
╔════════════════════════════════════════════════════════════════╗
║  ДЕТАЛИ ДОГОВОРОВ - ПОЛЯ И СРОКИ ПЛАТЕЖА                    ║
╚════════════════════════════════════════════════════════════════╝
""")

# Получаем договоры
url = f"{BASE_URL}Catalog_ДоговорыКонтрагентов?$top=10"
headers = get_basic_auth()

print("\n📡 Запрашиваю договоры...\n")

resp = requests.get(url, headers=headers, timeout=30, verify=False)
if resp.status_code == 200:
    data = resp.json()
    contracts = data.get('value', [])

    if contracts:
        print(f"✅ Получено {len(contracts)} договоров\n")

        # Показываем первые 3 договора со всеми полями
        for idx, contract in enumerate(contracts[:3], 1):
            print(f"\n{'='*80}")
            print(f"📋 ДОГОВОР #{idx}")
            print(f"{'='*80}")

            for key, value in sorted(contract.items()):
                if not key.startswith('@'):
                    # Сокращаем длинные значения
                    val_str = str(value)
                    if len(val_str) > 60:
                        val_str = val_str[:60] + "..."

                    # Подсвечиваем поля со сроком платежа
                    if 'срок' in key.lower() or 'платеж' in key.lower() or 'день' in key.lower():
                        print(f"  ⭐ {key:<45} = {val_str}")
                    else:
                        print(f"     {key:<45} = {val_str}")

        # Выводим список всех ключей
        print(f"\n{'='*80}")
        print("📌 ВСЕ ПОЛЯ В ДОГОВОРЕ:")
        print(f"{'='*80}")
        if contracts:
            all_keys = set()
            for contract in contracts:
                all_keys.update([k for k in contract.keys() if not k.startswith('@')])

            for key in sorted(all_keys):
                print(f"  • {key}")

else:
    print(f"❌ Ошибка {resp.status_code}")
    print(f"   {resp.text[:200]}")
