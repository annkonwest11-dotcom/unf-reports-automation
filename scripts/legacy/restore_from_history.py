#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/Users/anna/claude-test/credentials.json',
    scopes=SCOPES
)
client = gspread.authorize(creds)

SPREADSHEET_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
sheet = client.open_by_key(SPREADSHEET_ID)

print("📋 Проверяю историю Google Sheets...\n")
print("⚠️  ВАЖНО: История версий доступна только через веб-интерфейс Google Sheets!")
print("\nДля восстановления СПРАВОЧНИКА:")
print("1. Откройте Google Sheets таблицу")
print("2. Нажмите на иконку часов (☰ → История версий)")
print("3. Найдите версию ДО 2026-07-01 14:00 (когда я запустил скрипт удаления)")
print("4. Нажмите 'Восстановить эту версию'\n")

print("Попытаюсь получить текущие метаданные листа:")
try:
    ref_sheet = sheet.worksheet('СПРАВОЧНИК')
    print(f"✅ Лист СПРАВОЧНИК существует")
    print(f"   Всего строк: {len(ref_sheet.get_all_values())}")
except Exception as e:
    print(f"❌ Ошибка: {e}")

print("\n📝 Альтернативное решение:")
print("Если история версий не поможет, то нужно:")
print("1. Проверить, есть ли старые экспорты СПРАВОЧНИКА")
print("2. Или восстановить из файла который Анна экспортировала ранее")
print("\nКакой файл Excel/CSV был последний СПРАВОЧНИК перед сегодня?")
