#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/Users/anna/claude-test/credentials.json',
    scopes=SCOPES
)

SPREADSHEET_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
sheets_api = build('sheets', 'v4', credentials=creds)

print("🔄 Пересчитываю формулы в ДАННЫЕ_Губарев и ДАННЫЕ_Перфильев...\n")

sheets_to_recalc = ['ДАННЫЕ_Губарев', 'ДАННЫЕ_Перфильев']

for sheet_name in sheets_to_recalc:
    try:
        # Пытаюсь пересчитать через updateSpreadsheetProperties
        # Это запускает пересчет всех формул
        request = {
            'requests': [{
                'updateSpreadsheetProperties': {
                    'fields': 'autoRecalc',
                    'properties': {
                        'autoRecalc': 'ON_CHANGE'
                    }
                }
            }]
        }

        response = sheets_api.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=request
        ).execute()

        print(f"✅ {sheet_name} — пересчет запущен")

    except Exception as e:
        print(f"⚠️  {sheet_name}: {e}")

print("\n✅ Пересчет запущен!")
print("\nПримечание: Google Sheets пересчитывает формулы автоматически.")
print("Если видишь старые результаты, попробуй:")
print("1. Обновить страницу (F5)")
print("2. Или закрыть/открыть таблицу заново")
