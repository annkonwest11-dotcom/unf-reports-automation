#!/usr/bin/env python3
"""
Проверка продаж из OData для ИП Перфильев на 23.06.2026
Сравнение с эталоном из 1С
"""

import requests
import base64
import json
from datetime import datetime

# Конфигурация
LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"  # Перфильев
BASE_URL = f"https://base.42clouds.com/unf/{BASE_ID}/odata/standard.odata/"

TEST_DATE = "2026-06-23"
NEXT_DATE = "2026-06-24"

# Эталон из 1С
EXPECTED_TOTAL = 23239.00
EXPECTED_TOP = {
    'ФРЕСА': 7050.00,
    'Санфрутбери': 4223.00,
    'А 81': 3048.00,
}

def get_basic_auth():
    """Подготовить Basic Auth заголовок"""
    creds = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json"
    }

def fetch_odata_records(entity_name, filter_str=""):
    """Получить записи из OData"""
    url = f"{BASE_URL}{entity_name}"
    if filter_str:
        url += f"?$filter={filter_str}"

    headers = get_basic_auth()
    results = []

    print(f"  📡 Запрашиваю {entity_name}...")

    while url:
        try:
            resp = requests.get(url, headers=headers, timeout=30, verify=False)

            if resp.status_code != 200:
                print(f"  ❌ Ошибка {resp.status_code}")
                return None

            data = resp.json()
            if 'value' in data:
                results.extend(data['value'])
                print(f"    ✅ Получено {len(data['value'])} записей")

            url = data.get('@odata.nextLink')
        except Exception as e:
            print(f"  ❌ Ошибка сети: {e}")
            return None

    return results

def get_contractor_names():
    """Получить имена контрагентов"""
    print("\n📋 Загружаю справочник контрагентов...")
    contractors = fetch_odata_records('Catalog_Контрагенты')

    if not contractors:
        return {}

    names_map = {}
    for c in contractors:
        ref_key = c.get('Ref_Key')
        description = c.get('Description', 'Unknown')
        names_map[ref_key] = description

    print(f"  ✅ Загружено {len(names_map)} контрагентов")
    return names_map

def check_sales(contractor_names):
    """Проверить продажи за 23.06.2026"""
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 ОТЧЁТ №1: ПРОДАЖИ ЗА {TEST_DATE}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Эталон из 1С: {EXPECTED_TOTAL:,.2f} ₽\n")

    # Фильтр для продаж за день
    filter_str = f"Period ge datetime'{TEST_DATE}T00:00:00' and Period lt datetime'{NEXT_DATE}T00:00:00'"

    sales = fetch_odata_records('AccumulationRegister_Продажи_RecordType', filter_str)

    if sales is None:
        print("❌ Не удалось получить данные из OData")
        return

    print(f"Всего записей в OData: {len(sales)}\n")

    # Разбор по типам
    by_record_type = {}
    by_active = {}
    by_recorder_type = {}

    for r in sales:
        rt = r.get('RecordType', 'unknown')
        active = r.get('Active', True)
        recorder = r.get('Recorder_Type', 'unknown')

        by_record_type[rt] = by_record_type.get(rt, 0) + 1
        by_active[str(active)] = by_active.get(str(active), 0) + 1
        by_recorder_type[recorder] = by_recorder_type.get(recorder, 0) + 1

    print("📋 РАЗБОР СТРУКТУРЫ:")
    print("  По RecordType:")
    for k, v in by_record_type.items():
        print(f"    {k}: {v}")
    print("  По Active:")
    for k, v in by_active.items():
        print(f"    {k}: {v}")
    print("  По Recorder_Type:")
    for k, v in by_recorder_type.items():
        print(f"    {k}: {v}\n")

    # Суммируем только Receipt (продажи, не возвраты)
    total_sales = 0
    receipt_count = 0
    sales_by_contractor = {}

    for r in sales:
        record_type = r.get('RecordType', 'Receipt')
        if record_type != 'Receipt':
            continue

        receipt_count += 1
        amount = r.get('Сумма', 0) or 0
        total_sales += amount

        contractor_key = r.get('Контрагент_Key', 'unknown')
        if contractor_key not in sales_by_contractor:
            sales_by_contractor[contractor_key] = 0
        sales_by_contractor[contractor_key] += amount

    print(f"✅ ИТОГО (RecordType=Receipt):")
    print(f"   Записей: {receipt_count}")
    print(f"   Сумма: {total_sales:,.2f} ₽")
    print(f"⚖️  Эталон из 1С: {EXPECTED_TOTAL:,.2f} ₽")
    print(f"📊 Разница: {total_sales - EXPECTED_TOTAL:+,.2f} ₽")

    if abs(total_sales - EXPECTED_TOTAL) < 0.01:
        print("✅ СОВПАДАЕТ!\n")
    else:
        print(f"❌ РАСХОЖДЕНИЕ: {abs(total_sales - EXPECTED_TOTAL):,.2f} ₽\n")

    # Топ покупатели
    print("🏆 ТОП-5 ПОКУПАТЕЛЕЙ:")
    top_sales = sorted(sales_by_contractor.items(), key=lambda x: x[1], reverse=True)[:5]

    for idx, (contractor_key, amount) in enumerate(top_sales, 1):
        name = contractor_names.get(contractor_key, f'Unknown ({contractor_key})')

        # Проверить с эталоном
        expected_amount = EXPECTED_TOP.get(name)
        if expected_amount and abs(amount - expected_amount) < 0.01:
            match = "✅"
        else:
            match = "  "

        print(f"  {idx}. {name}: {amount:,.2f} ₽ {match}")

    print()

# Основная логика
if __name__ == "__main__":
    print(f"""
╔════════════════════════════════════════════════════════════════╗
║  ПРОВЕРКА OData — ИП ПЕРФИЛЬЕВ                                ║
║  Дата: {TEST_DATE}
╚════════════════════════════════════════════════════════════════╝
""")

    # Отключить SSL warnings
    import urllib3
    urllib3.disable_warnings()

    # Загрузить контрагентов
    contractor_names = get_contractor_names()

    # Проверить продажи
    check_sales(contractor_names)

    print("=" * 70)
    print("✅ ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 70)
