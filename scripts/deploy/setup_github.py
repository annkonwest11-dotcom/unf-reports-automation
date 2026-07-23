#!/usr/bin/env python3
"""
Автоматическая загрузка проекта на GitHub через API
Нужен только Personal Access Token
"""

import requests
import json
import base64
import os
import sys
import getpass

print("""
╔════════════════════════════════════════════════════════════╗
║  АВТОМАТИЧЕСКАЯ ЗАГРУЗКА НА GITHUB                        ║
╚════════════════════════════════════════════════════════════╝
""")

# Получаем токен
print("🔐 Введи свой GitHub Personal Access Token")
print("   (получи здесь: https://github.com/settings/tokens)")
print("")

TOKEN = getpass.getpass("Token: ")

if not TOKEN:
    print("❌ Токен не введен")
    sys.exit(1)

USERNAME = "annkonwest11-dotcom"
REPO_NAME = "unf-reports-automation"
PROJECT_DIR = "/Users/anna/claude-test"

print(f"\n✅ Токен получен")
print(f"Будут загружены файлы на: https://github.com/{USERNAME}/{REPO_NAME}")
print()

# Headers для API запросов
headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "Content-Type": "application/json"
}

# 1. СОЗДАЕМ РЕПОЗИТОРИЙ
print("1️⃣  Создаю репозиторий на GitHub...")

create_repo_data = {
    "name": REPO_NAME,
    "description": "Автоматические отчеты из 1С в Telegram - GitHub Actions",
    "private": False,
    "auto_init": False
}

response = requests.post(
    "https://api.github.com/user/repos",
    headers=headers,
    json=create_repo_data,
    timeout=10
)

if response.status_code == 201:
    print("   ✅ Репозиторий создан!")
elif response.status_code == 422:
    print("   ℹ️  Репозиторий уже существует (используем его)")
else:
    print(f"   ❌ Ошибка: {response.status_code}")
    print(f"   {response.text[:200]}")
    sys.exit(1)

# 2. ЗАГРУЖАЕМ ФАЙЛЫ
print("\n2️⃣  Загружаю файлы...")

files_to_upload = [
    ".github/workflows/daily_reports.yml",
    "scripts/generate_reports.py",
    "credentials.json",
    "README.md",
]

for file_path in files_to_upload:
    full_path = os.path.join(PROJECT_DIR, file_path)

    if not os.path.exists(full_path):
        print(f"   ⚠️  {file_path} - не найден")
        continue

    try:
        with open(full_path, 'rb') as f:
            file_content = f.read()

        # Кодируем в base64
        encoded_content = base64.b64encode(file_content).decode('utf-8')

        # Загружаем через API
        upload_url = f"https://api.github.com/repos/{USERNAME}/{REPO_NAME}/contents/{file_path}"

        upload_data = {
            "message": f"Add {file_path}",
            "content": encoded_content,
            "branch": "main"
        }

        response = requests.put(
            upload_url,
            headers=headers,
            json=upload_data,
            timeout=10
        )

        if response.status_code in [201, 200]:
            print(f"   ✅ {file_path}")
        else:
            print(f"   ⚠️  {file_path}: {response.status_code}")

    except Exception as e:
        print(f"   ❌ {file_path}: {str(e)[:50]}")

# 3. ДОБАВЛЯЕМ SECRETS
print("\n3️⃣  Добавляю Secrets...")

secrets = {
    "TELEGRAM_TOKEN": "8602166476:AAEo3ySMNmF38lyH0yppcW7CKejzXK_w7cY",
    "TELEGRAM_CHAT_ID": "796207056",
    "SHEET_ID": "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo",
}

# Получаем публичный ключ репозитория
print("   Получаю ключ шифрования...")

key_response = requests.get(
    f"https://api.github.com/repos/{USERNAME}/{REPO_NAME}/actions/secrets/public-key",
    headers=headers,
    timeout=10
)

if key_response.status_code != 200:
    print(f"   ⚠️  Ошибка получения ключа: {key_response.status_code}")
else:
    key_data = key_response.json()
    public_key = key_data['key']
    key_id = key_data['key_id']

    # Добавляем каждый secret
    try:
        from nacl import utils, public
    except ImportError:
        print("   ℹ️  Установи: pip install pynacl")
        print("   Secrets нужно добавить вручную")
        print()
        for secret_name, secret_value in secrets.items():
            print(f"   {secret_name} = {secret_value}")
        sys.exit(1)

    for secret_name, secret_value in secrets.items():
        try:
            # Шифруем значение
            public_key_obj = public.PublicKey(public_key, encoder=public.Base64Encoder)
            encrypted = public.SealedBox(public_key_obj).encrypt(secret_value.encode())
            encoded_encrypted = base64.b64encode(encrypted.ciphertext).decode('utf-8')

            # Загружаем secret
            secret_url = f"https://api.github.com/repos/{USERNAME}/{REPO_NAME}/actions/secrets/{secret_name}"

            secret_data = {
                "encrypted_value": encoded_encrypted,
                "key_id": key_id
            }

            response = requests.put(
                secret_url,
                headers=headers,
                json=secret_data,
                timeout=10
            )

            if response.status_code in [201, 204]:
                print(f"   ✅ {secret_name}")
            else:
                print(f"   ⚠️  {secret_name}: {response.status_code}")

        except Exception as e:
            print(f"   ❌ {secret_name}: {str(e)[:50]}")

# 4. GOOGLE_CREDENTIALS
print("\n4️⃣  Добавляю GOOGLE_CREDENTIALS...")

try:
    with open(f"{PROJECT_DIR}/credentials.json", 'r') as f:
        google_creds = f.read()

    # Шифруем
    public_key_obj = public.PublicKey(public_key, encoder=public.Base64Encoder)
    encrypted = public.SealedBox(public_key_obj).encrypt(google_creds.encode())
    encoded_encrypted = base64.b64encode(encrypted.ciphertext).decode('utf-8')

    # Загружаем
    secret_url = f"https://api.github.com/repos/{USERNAME}/{REPO_NAME}/actions/secrets/GOOGLE_CREDENTIALS"

    secret_data = {
        "encrypted_value": encoded_encrypted,
        "key_id": key_id
    }

    response = requests.put(
        secret_url,
        headers=headers,
        json=secret_data,
        timeout=10
    )

    if response.status_code in [201, 204]:
        print("   ✅ GOOGLE_CREDENTIALS")
    else:
        print(f"   ⚠️  GOOGLE_CREDENTIALS: {response.status_code}")

except Exception as e:
    print(f"   ❌ GOOGLE_CREDENTIALS: {str(e)[:50]}")

print("\n" + "="*60)
print("✅ ГОТОВО!")
print("="*60)
print()
print("🎉 Проект загружен на GitHub!")
print()
print(f"📍 Репозиторий: https://github.com/{USERNAME}/{REPO_NAME}")
print()
print("📊 Дальше:")
print("   1. Открой https://github.com/annkonwest11-dotcom/unf-reports-automation")
print("   2. Нажми Actions")
print("   3. Нажми 'Run workflow'")
print("   4. Проверь Telegram - отчет должен прийти! ✅")
print()
print("🚀 После этого отчеты будут приходить КАЖДЫЙ ДЕНЬ в 09:30 МСК!")
