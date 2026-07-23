#!/usr/bin/env python3
"""
Проверка дебиторки из OData для ИП Перфильев на 24.06.2026
Сравнение с отчётом "Задолженость покупателей по срокам долга" из 1С
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

TEST_DATE = "2026-06-24"

# Эталон из скриншота 1С (видимые контрагенты)
EXPECTED_CONTRACTORS = {
    'А 81 (перевод)': 334256.00,
    'ФРЕСА (ООО ФЕЛИСА с 01.11.25)': 314892.00,
    'А20 (ИП Тагаева Роза Бахридиновна с 20.10.25)': 162446.00,
    'ДИМА (перевод)': 158689.00,
    'Кросс док Слава (наличка)': 158349.80,
    'ПЕРВАЯ ФРУКТОВАЯ (ООО ПЕРСПЕКТИВА)': 106028.00,
    'РУСПРОДУКТ (ООО ИЗОБИЛИЕ)': 91232.00,
    'А 71 (ООО Фреш Фуд Лайн ООО с 07.11.25)': 87084.00,
    'Санфрутбери (ООО ПРОДСЕРВИС)': 35785.00,
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

    page = 0
    while url:
        page += 1
        try:
            resp = requests.get(url, headers=headers, timeout=30, verify=False)

            if resp.status_code != 200:
                print(f"  ❌ Ошибка {resp.status_code}")
                return None

            data = resp.json()
            if 'value' in data:
                results.extend(data['value'])
                print(f"    📄 Страница {page}: {len(data['value'])} записей")

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

def check_receivables(contractor_names):
    """Проверить дебиторку на начало дня (на 24.06 00:00:00)"""
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"💳 ОТЧЁТ №3: ДЕБИТОРКА (на начало {TEST_DATE})")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Источник: AccumulationRegister_РасчетыСПокупателями_RecordType\n")

    # Фильтр: все на начало дня
    filter_str = f"Period le datetime'{TEST_DATE}T00:00:00'"

    settlements = fetch_odata_records('AccumulationRegister_РасчетыСПокупателями_RecordType', filter_str)

    if settlements is None:
        print("❌ Не удалось получить данные из OData")
        return

    print(f"Всего записей в OData: {len(settlements)}\n")

    # Структура: { контрагент: { договор: { receipt, expense } } }
    settlements_by_ctg_deal = {}

    for r in settlements:
        ctg_key = r.get('Контрагент_Key', 'unknown')
        deal_key = r.get('Договор_Key', 'nodeal')
        amount = r.get('Сумма', 0) or 0
        record_type = r.get('RecordType', 'Receipt')

        if ctg_key not in settlements_by_ctg_deal:
            settlements_by_ctg_deal[ctg_key] = {}
        if deal_key not in settlements_by_ctg_deal[ctg_key]:
            settlements_by_ctg_deal[ctg_key][deal_key] = {'receipt': 0, 'expense': 0}

        if record_type == 'Receipt':
            settlements_by_ctg_deal[ctg_key][deal_key]['receipt'] += amount
        elif record_type == 'Expense':
            settlements_by_ctg_deal[ctg_key][deal_key]['expense'] += amount

    # Считаем дебиторку: сумма только положительных остатков по договорам
    debt_by_contractor = {}

    for ctg_key, deals in settlements_by_ctg_deal.items():
        contractor_debt = 0
        for deal_key, balances in deals.items():
            deal_balance = balances['receipt'] - balances['expense']
            if deal_balance > 0:
                contractor_debt += deal_balance
        if contractor_debt > 0:
            debt_by_contractor[ctg_key] = contractor_debt

    total_debt = sum(debt_by_contractor.values())

    print(f"✅ ИТОГО ДЕБИТОРКА: {total_debt:,.2f} ₽\n")

    # Топ контрагентов
    print("🏆 ТОП-15 ДОЛЖНИКОВ:")
    top_debtors = sorted(debt_by_contractor.items(), key=lambda x: x[1], reverse=True)[:15]

    print(f"{'#':<3} {'Контрагент':<50} {'Сумма':>15} {'Совпадение':>10}")
    print("─" * 80)

    for idx, (ctg_key, amount) in enumerate(top_debtors, 1):
        name = contractor_names.get(ctg_key, f'Unknown ({ctg_key})')

        # Проверить с эталоном
        expected_amount = None
        for expected_name, expected_val in EXPECTED_CONTRACTORS.items():
            if expected_name.split('(')[0].strip() in name or name in expected_name:
                expected_amount = expected_val
                break

        if expected_amount:
            diff = abs(amount - expected_amount)
            if diff < 0.01:
                match = "✅"
            else:
                match = f"❌ {diff:+.2f}"
        else:
            match = "❓"

        print(f"{idx:<3} {name:<50} {amount:>15,.2f} {match:>10}")

    print("\n" + "─" * 80)
    print(f"ВСЕГО НА СЧЁТЕ: {total_debt:,.2f} ₽")

# Основная логика
if __name__ == "__main__":
    print(f"""
╔════════════════════════════════════════════════════════════════╗
║  ПРОВЕРКА ДЕБИТОРКИ — ИП ПЕРФИЛЬЕВ                            ║
║  Дата: {TEST_DATE} (начало дня)
╚════════════════════════════════════════════════════════════════╝
""")

    # Отключить SSL warnings
    import urllib3
    urllib3.disable_warnings()

    # Загрузить контрагентов
    contractor_names = get_contractor_names()

    # Проверить дебиторку
    check_receivables(contractor_names)

    print("\n" + "=" * 70)
    print("✅ ДИАГНОСТИКА ДЕБИТОРКИ ЗАВЕРШЕНА")
    print("=" * 70)
