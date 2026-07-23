#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials
from difflib import SequenceMatcher

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/Users/anna/claude-test/credentials.json',
    scopes=SCOPES
)
client = gspread.authorize(creds)

SPREADSHEET_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
sheet = client.open_by_key(SPREADSHEET_ID)

print("🔍 Ищу несовпадения в названиях контрагентов...\n")

# Читаю СПРАВОЧНИК
ref_sheet = sheet.worksheet('СПРАВОЧНИК')
ref_data = ref_sheet.get_all_values()
reference = {}  # {нижнее_имя -> оригинальное_имя}
for row in ref_data[1:]:
    if row and row[0].strip():
        name = row[0].strip()
        reference[name.lower()] = name

print(f"В СПРАВОЧНИКЕ: {len(reference)} контрагентов\n")

def find_similar(target, candidates, threshold=0.7):
    """Ищет похожее имя в списке кандидатов"""
    best_match = None
    best_score = threshold

    target_lower = target.lower()

    for ref_name_lower, ref_name in candidates.items():
        # Точное совпадение (регистр-независимое)
        if target_lower == ref_name_lower:
            return ref_name, 1.0

        # Проверяю содержится ли одно в другом
        if target_lower in ref_name_lower or ref_name_lower in target_lower:
            score = 0.95
            if score > best_score:
                best_score = score
                best_match = ref_name
        else:
            # Нечеткий поиск
            score = SequenceMatcher(None, target_lower, ref_name_lower).ratio()
            if score > best_score:
                best_score = score
                best_match = ref_name

    return best_match, best_score

# Ищу несовпадения в обоих листах
mismatches = []

for sheet_name in ['ДАННЫЕ_Губарев', 'ДАННЫЕ_Перфильев']:
    try:
        ws = sheet.worksheet(sheet_name)
        data = ws.get_all_values()

        for idx, row in enumerate(data[1:], start=2):
            if len(row) < 7 or not row[0].strip():
                continue

            contractor = row[0].strip()
            lookup_result = row[5].strip() if len(row) > 5 else ""

            # Если результат VLOOKUP пуст или ошибка
            if not lookup_result or lookup_result.startswith('#'):
                # Ищу похожего
                similar, score = find_similar(contractor, reference)

                if similar:
                    mismatches.append({
                        'sheet': sheet_name,
                        'row': idx,
                        'in_data': contractor,
                        'in_ref': similar,
                        'similarity': score
                    })

    except Exception as e:
        print(f"⚠️  {sheet_name}: {e}\n")

# Сортирую по similarity (наиболее похожие - в конце)
mismatches.sort(key=lambda x: x['similarity'])

print(f"📋 Найдено несовпадений: {len(mismatches)}\n")
print("=" * 100)
print(f"{'Sheet':<20} {'Row':<5} {'Сходство':<12} {'В ДАННЫЕ':<40} {'В СПРАВОЧНИКЕ':<40}")
print("=" * 100)

for m in mismatches[:50]:  # Показываю первые 50
    similarity_percent = f"{m['similarity']*100:.0f}%"
    in_data = m['in_data'][:37] + "..." if len(m['in_data']) > 40 else m['in_data']
    in_ref = m['in_ref'][:37] + "..." if len(m['in_ref']) > 40 else m['in_ref']

    print(f"{m['sheet']:<20} {m['row']:<5} {similarity_percent:<12} {in_data:<40} {in_ref:<40}")

if len(mismatches) > 50:
    print(f"\n... и ещё {len(mismatches) - 50} совпадений")

# Статистика
print("\n" + "=" * 100)
exact = len([m for m in mismatches if m['similarity'] >= 0.99])
high = len([m for m in mismatches if 0.8 <= m['similarity'] < 0.99])
medium = len([m for m in mismatches if 0.6 <= m['similarity'] < 0.8])
low = len([m for m in mismatches if m['similarity'] < 0.6])

print(f"\n📊 Статистика:")
print(f"   🟢 Почти совпадает (95-99%): {high}")
print(f"   🟡 Похоже (80-94%): {medium}")
print(f"   🔴 Непохоже (<80%): {low}")
print(f"   ✅ Точное совпадение: {exact}")
