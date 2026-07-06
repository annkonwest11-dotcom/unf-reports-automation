#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials
import json

# Подключение к Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/Users/anna/claude-test/credentials.json',
    scopes=SCOPES
)
client = gspread.authorize(creds)

# ID таблицы
SPREADSHEET_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
sheet = client.open_by_key(SPREADSHEET_ID)

print("📊 Поиск не найденных контрагентов...\n")

# Листы для проверки
sheets_to_check = ['ДАННЫЕ_Губарев', 'ДАННЫЕ_Перфильев']
missing_contractors = set()

for sheet_name in sheets_to_check:
    try:
        ws = sheet.worksheet(sheet_name)
        print(f"Проверяю {sheet_name}...")

        # Читаю все данные (A:F) — контрагент и результат VLOOKUP
        data = ws.get_all_values()

        # Пропускаю заголовок (строка 1)
        for idx, row in enumerate(data[1:], start=2):
            if len(row) < 6:  # Нет данных в этой строке
                continue

            contractor = row[0].strip() if row[0] else ""
            lookup_result = row[5].strip() if len(row) > 5 else ""  # Столбец F (Менеджер поиска)

            if not contractor:  # Пустая строка
                continue

            # Проверяю на ошибки #N/A или пусто
            if lookup_result.startswith('#') or lookup_result == "":
                missing_contractors.add(contractor)
                print(f"  ❌ {sheet_name}:{idx} → '{contractor}' (результат: '{lookup_result}')")

    except Exception as e:
        print(f"⚠️  Ошибка при чтении {sheet_name}: {e}")

if not missing_contractors:
    print("\n✅ Все контрагенты найдены в СПРАВОЧНИКЕ!")
else:
    print(f"\n⚠️  Найдено {len(missing_contractors)} уникальных не найденных контрагентов:")
    for contractor in sorted(missing_contractors):
        print(f"  • {contractor}")

    # Добавляю в СПРАВОЧНИК
    print("\n📝 Добавляю контрагентов в СПРАВОЧНИК...\n")
    try:
        ref_sheet = sheet.worksheet('СПРАВОЧНИК')
        ref_data = ref_sheet.get_all_values()

        # Находим последнюю заполненную строку
        last_row = len(ref_data)
        for idx in range(len(ref_data) - 1, -1, -1):
            if ref_data[idx][0].strip():  # Первый столбец не пуст
                last_row = idx + 1
                break

        print(f"Последняя строка СПРАВОЧНИКА: {last_row}")
        print(f"Добавляю {len(missing_contractors)} новых контрагентов:\n")

        # Структура СПРАВОЧНИКА: [Контрагент, Тип(B), Менеджер(C), ТипКлиента(D), Беби(E), ?(F), Статус(G), ?(H)]
        for idx, contractor in enumerate(sorted(missing_contractors), 1):
            new_row = [contractor, "", "", "", "Нет", "", "Активен", ""]

            # Вставляю через append_row
            ref_sheet.append_row(new_row)
            print(f"  ✅ Добавлен: {contractor}")

        print(f"\n🎉 Успешно добавлено {len(missing_contractors)} контрагентов!")

    except Exception as e:
        print(f"❌ Ошибка при добавлении в СПРАВОЧНИК: {e}")
        print("\nДобавьте вручную:")
        for contractor in sorted(missing_contractors):
            print(f"  {contractor}")
