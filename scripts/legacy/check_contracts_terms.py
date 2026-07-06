#!/usr/bin/env python3
"""
Проверка договоров - ищем поле со сроком платежа
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

def fetch_odata_records(entity_name, limit=10):
    url = f"{BASE_URL}{entity_name}?$top={limit}"
    headers = get_basic_auth()
    resp = requests.get(url, headers=headers, timeout=30, verify=False)
    if resp.status_code != 200:
        print(f"❌ Ошибка {resp.status_code}")
        return None
    data = resp.json()
    return data.get('value', [])

# Отключить SSL warnings
import urllib3
urllib3.disable_warnings()

print("""
╔════════════════════════════════════════════════════════════════╗
║  ПРОВЕРКА СТРУКТУРЫ ДОГОВОРОВ                                 ║
║  Ищем поле со сроком платежа
╚════════════════════════════════════════════════════════════════╝
""")

# Проверяем договоры
print("\n📋 Читаю договоры (Catalog_Договоры)...\n")
contracts = fetch_odata_records('Catalog_Договоры', limit=5)

if contracts:
    print(f"✅ Получено {len(contracts)} договоров\n")

    # Показываем первый договор со всеми полями
    if contracts:
        contract = contracts[0]
        print("🔍 Первый договор - все поля:")
        print("=" * 80)
        for key, value in contract.items():
            if not key.startswith('@'):
                print(f"  {key:<40} = {str(value)[:40]}")
        print("=" * 80)
else:
    print("❌ Не удалось получить договоры")

# Проверяем также справочник с условиями платежа
print("\n📋 Ищу справочник условий платежа...\n")

# Пробуем разные варианты названий
possible_names = [
    'Catalog_УсловияПлатежа',
    'Catalog_ПервоначальноПредусмотренныеУсловия',
    'Catalog_ВидДоговора',
    'Catalog_ДокументОСделке',
]

for name in possible_names:
    try:
        data = fetch_odata_records(name, limit=3)
        if data:
            print(f"✅ Найден: {name}")
            if data:
                print(f"   Полей: {list(data[0].keys())[:5]}")
    except:
        pass
