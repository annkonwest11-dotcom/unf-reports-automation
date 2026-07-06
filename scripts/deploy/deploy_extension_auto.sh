#!/bin/bash

echo "🚀 АВТОМАТИЧЕСКАЯ ЗАГРУЗКА РАСШИРЕНИЯ 1С"
echo ""
echo "Выбери вариант:"
echo ""
echo "1️⃣  Вариант 2: Selenium (визуальная загрузка через браузер)"
echo "2️⃣  Вариант 3: REST API (если доступен)"
echo ""

read -p "Выбери (1 или 2): " CHOICE

if [ "$CHOICE" = "1" ]; then
    echo ""
    echo "🔐 Введи пароль для api_bot (он не будет видно):"
    read -s PASSWORD
    
    echo ""
    echo "⚙️  Запускаю скрипт Selenium..."
    
    source /Users/anna/claude-test/venv/bin/activate
    python3 << 'PYPYTHON'
import subprocess
import os

os.environ['1C_LOGIN'] = 'api_bot'
os.environ['1C_PASSWORD'] = os.environ.get('1C_PASSWORD', '')

# Запускаем скрипт
result = subprocess.run(['python3', '/Users/anna/claude-test/install_extension.py'], 
                       env=os.environ)
sys.exit(result.returncode)
PYPYTHON

elif [ "$CHOICE" = "2" ]; then
    echo ""
    echo "🔍 Пытаюсь загрузить через REST API 42clouds..."
    
    source /Users/anna/claude-test/venv/bin/activate
    python3 << 'PYPYTHON'
import requests
import json
import sys

print("\n📡 Проверяю доступность REST API 42clouds...\n")

# Базовый URL для проверки
api_url = "https://api.42clouds.com/v1"

try:
    # Пытаемся авторизоваться
    auth_url = f"{api_url}/auth/login"
    
    payload = {
        "username": "api_bot",
        "password": input("🔐 Введи пароль: ")
    }
    
    response = requests.post(auth_url, json=payload, timeout=10)
    
    if response.status_code == 200:
        print("✅ Авторизация успешна!")
        token = response.json().get('token')
        print(f"🔑 Получен токен: {token[:20]}...")
        
        # Теперь загружаем расширение
        print("\n📦 Загружаю расширение...")
        
        # TODO: Реализовать загрузку через API
        print("⚠️  Загрузка через API требует дополнительной настройки")
        print("   Используй Вариант 1 (Selenium) для надежной загрузки")
        
    elif response.status_code == 401:
        print("❌ Неверные учетные данные")
    else:
        print(f"❌ Ошибка: {response.status_code}")
        print(response.text)
        
except Exception as e:
    print(f"❌ REST API не доступен или недоступен")
    print(f"   Ошибка: {e}")
    print("\n💡 Используй Вариант 1 (Selenium) - он более надежен")

PYPYTHON

else
    echo "❌ Неверный выбор"
    exit 1
fi

