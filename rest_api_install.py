#!/usr/bin/env python3
"""
Загрузка расширения 1С через REST API 42clouds
"""

import requests
import json
import time
import sys
import os

print("""
╔════════════════════════════════════════════════════════════╗
║     ЗАГРУЗКА ЧЕРЕЗ REST API 42clouds                       ║
╚════════════════════════════════════════════════════════════╝
""")

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
EXTENSION_FILE = "/Users/anna/claude-test/1C_UNF_EXTENSION_READY.bsl"

BASES = {
    "Перфильев": {
        "base_id": "152757",
        "url": "https://base.42clouds.com/unf/152757/"
    },
    "Губарев": {
        "base_id": "64904",
        "url": "https://base.42clouds.com/unf/64904/"
    }
}

# REST API endpoints
API_BASE = "https://api.42clouds.com/v1"

if not os.path.exists(EXTENSION_FILE):
    print(f"❌ Файл не найден: {EXTENSION_FILE}")
    sys.exit(1)

# Читаем файл расширения
with open(EXTENSION_FILE, 'rb') as f:
    extension_data = f.read()

print(f"✅ Расширение загружено ({len(extension_data)} bytes)")
print()

session = requests.Session()

try:
    # 1. АВТОРИЗАЦИЯ
    print("1️⃣  Авторизуюсь через REST API...\n")

    auth_url = f"{API_BASE}/auth/login"
    auth_data = {
        "username": LOGIN,
        "password": PASSWORD
    }

    print(f"   POST {auth_url}")
    response = session.post(auth_url, json=auth_data, timeout=10)
    print(f"   Status: {response.status_code}")

    if response.status_code == 200:
        auth_result = response.json()
        token = auth_result.get('token') or auth_result.get('access_token')

        if token:
            print(f"   ✅ Токен получен: {token[:20]}...")
            session.headers.update({
                'Authorization': f'Bearer {token}',
                'X-API-Token': token
            })
        else:
            print(f"   ⚠️  Токен не найден в ответе:")
            print(f"   {json.dumps(auth_result, indent=2)}")
    else:
        print(f"   ⚠️  Статус: {response.status_code}")
        print(f"   Ответ: {response.text[:200]}")
        print("\n   💡 Пытаюсь альтернативный endpoint...")

        # Пытаемся альтернативный endpoint
        alt_url = "https://base.42clouds.com/api/v1/auth/login"
        response = session.post(alt_url, json=auth_data, timeout=10)
        print(f"   Alt Status: {response.status_code}")

        if response.status_code == 200:
            token = response.json().get('token')
            if token:
                print(f"   ✅ Токен получен через альтернативный endpoint")
                session.headers.update({'Authorization': f'Bearer {token}'})

    print()

    # 2. ЗАГРУЗКА РАСШИРЕНИЯ ДЛЯ КАЖДОЙ БАЗЫ
    for base_name, base_info in BASES.items():
        print(f"🎯 ЗАГРУЖАЮ В: {base_name}\n")

        base_id = base_info['base_id']

        # Пытаемся загрузить расширение
        print(f"2️⃣  Загружаю расширение...")

        # Вариант 1: Стандартный API endpoint
        upload_url = f"{API_BASE}/bases/{base_id}/extensions/upload"
        print(f"   POST {upload_url}")

        try:
            files = {'file': ('1C_UNF_EXTENSION_READY.bsl', extension_data, 'application/octet-stream')}
            response = session.post(upload_url, files=files, timeout=30)
            print(f"   Status: {response.status_code}")

            if response.status_code in [200, 201]:
                print(f"   ✅ Расширение загружено!")
                print(f"   Ответ: {response.text[:200]}")
            else:
                print(f"   ⚠️  Статус: {response.status_code}")
                print(f"   Ответ: {response.text[:200]}")
        except Exception as e:
            print(f"   ⚠️  Ошибка: {e}")

        # Вариант 2: Альтернативный endpoint
        alt_upload_url = f"https://base.42clouds.com/api/v1/extension/upload"
        print(f"\n   Пытаюсь альтернативный endpoint...")
        print(f"   POST {alt_upload_url}")

        try:
            params = {'baseId': base_id}
            files = {'file': extension_data}
            response = session.post(alt_upload_url, files=files, params=params, timeout=30)
            print(f"   Status: {response.status_code}")

            if response.status_code in [200, 201]:
                print(f"   ✅ Расширение загружено (alt endpoint)!")
        except Exception as e:
            print(f"   ⚠️  Ошибка: {e}")

        # 3. СОЗДАНИЕ РЕГЛАМЕНТНЫХ ЗАДАНИЙ
        print(f"\n3️⃣  Создаю регламентные задания...\n")

        tasks = [
            {
                "name": "ОтправкаОтчетовУНФ",
                "procedure": "УНФ.ОтправкаОтчетовРегламент",
                "schedule": "0 9 * * *"  # 09:30 каждый день
            },
            {
                "name": "ОпросОчередиКомандУНФ",
                "procedure": "УНФ.ОпросОчередиКомандРегламент",
                "schedule": "* * * * *"  # Каждую минуту
            }
        ]

        for task in tasks:
            print(f"   📌 {task['name']}")

            # Вариант 1
            job_url = f"{API_BASE}/bases/{base_id}/jobs/create"
            job_data = {
                "name": task['name'],
                "procedure": task['procedure'],
                "schedule": task['schedule'],
                "enabled": True
            }

            try:
                response = session.post(job_url, json=job_data, timeout=10)
                print(f"      Status: {response.status_code}")

                if response.status_code in [200, 201]:
                    print(f"      ✅ Создано!")
                else:
                    print(f"      ⚠️  {response.status_code}")
            except Exception as e:
                print(f"      ⚠️  Ошибка: {e}")

            # Вариант 2
            alt_job_url = f"https://base.42clouds.com/api/v1/reglamented-job/create"
            alt_job_data = {
                "baseId": base_id,
                "name": task['name'],
                "procedure": task['procedure'],
                "schedule": task['schedule'],
                "enabled": True
            }

            try:
                response = session.post(alt_job_url, json=alt_job_data, timeout=10)
                print(f"      Alt Status: {response.status_code}")

                if response.status_code in [200, 201]:
                    print(f"      ✅ Создано (alt)!")
            except Exception as e:
                pass

        print()

    print("=" * 60)
    print("\n✅ ПОПЫТКА ЗАВЕРШЕНА!")
    print("\nЕсли выше были статусы 200/201 - всё загружено автоматически! 🎉")
    print("Если были ошибки - нужно загружать вручную (инструкция сохранена).")

except Exception as e:
    print(f"\n❌ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()

finally:
    session.close()
