#!/usr/bin/env python3
"""
Список всех сущностей в OData
"""

import requests
import base64

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"  # Перфильев
BASE_URL = f"https://base.42clouds.com/unf/{BASE_ID}/odata/standard.odata/"

def get_basic_auth():
    creds = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json"
    }

# Отключить SSL warnings
import urllib3
urllib3.disable_warnings()

print("""
╔════════════════════════════════════════════════════════════════╗
║  СПИСОК ВСЕХ СУЩНОСТЕЙ В OData                                ║
║  Ищем договоры и условия платежа
╚════════════════════════════════════════════════════════════════╝
""")

# Получаем OData feed
url = BASE_URL
headers = get_basic_auth()

print("\n📡 Запрашиваю OData metadata...\n")

resp = requests.get(url, headers=headers, timeout=30, verify=False)
if resp.status_code == 200:
    data = resp.json()
    if 'value' in data:
        entities = data['value']
        print(f"✅ Найдено {len(entities)} сущностей\n")

        # Ищем договоры
        print("🔍 ДОГОВОРЫ И УСЛОВИЯ ПЛАТЕЖА:\n")
        keywords = ['догов', 'платеж', 'условие', 'срок', 'контракт']

        for entity in entities:
            name = entity.get('name', '')
            for keyword in keywords:
                if keyword.lower() in name.lower():
                    print(f"  • {name}")
                    break

        print("\n\n📋 ВСЕ СУЩНОСТИ (отсортированы):\n")
        for entity in sorted(entities, key=lambda x: x.get('name', '')):
            name = entity.get('name', '')
            if name:
                print(f"  {name}")

else:
    print(f"❌ Ошибка {resp.status_code}")
