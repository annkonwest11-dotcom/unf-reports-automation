#!/usr/bin/env python3
"""
Полный список должников из OData для проверки актов сверок
"""

import requests
import base64

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"  # Перфильев
BASE_URL = f"https://base.42clouds.com/unf/{BASE_ID}/odata/standard.odata/"
TEST_DATE = "2026-06-24"

def get_basic_auth():
    creds = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json"
    }

def fetch_odata_records(entity_name, filter_str=""):
    url = f"{BASE_URL}{entity_name}"
    if filter_str:
        url += f"?$filter={filter_str}"
    headers = get_basic_auth()
    results = []
    while url:
        resp = requests.get(url, headers=headers, timeout=30, verify=False)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if 'value' in data:
            results.extend(data['value'])
        url = data.get('@odata.nextLink')
    return results

def get_contractor_names():
    contractors = fetch_odata_records('Catalog_Контрагенты')
    if not contractors:
        return {}
    names_map = {}
    for c in contractors:
        ref_key = c.get('Ref_Key')
        description = c.get('Description', 'Unknown')
        names_map[ref_key] = description
    return names_map

# Отключить SSL warnings
import urllib3
urllib3.disable_warnings()

print("""
╔════════════════════════════════════════════════════════════════╗
║  ПОЛНЫЙ СПИСОК ДОЛЖНИКОВ ИП ПЕРФИЛЬЕВ                         ║
║  На начало 2026-06-24
╚════════════════════════════════════════════════════════════════╝
""")

# Загрузить контрагентов
print("📋 Загружаю контрагентов...")
contractor_names = get_contractor_names()
print(f"✅ Загружено {len(contractor_names)}")

# Получить дебиторку
print("\n💳 Загружаю дебиторку из OData...")
filter_str = f"Period le datetime'{TEST_DATE}T00:00:00'"
settlements = fetch_odata_records('AccumulationRegister_РасчетыСПокупателями_RecordType', filter_str)

if not settlements:
    print("❌ Ошибка загрузки")
    exit(1)

print(f"✅ Получено {len(settlements)} записей")

# Считаем дебиторку
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

# Считаем итоговую дебиторку
debt_by_contractor = {}
for ctg_key, deals in settlements_by_ctg_deal.items():
    contractor_debt = 0
    for deal_key, balances in deals.items():
        deal_balance = balances['receipt'] - balances['expense']
        if deal_balance > 0:
            contractor_debt += deal_balance
    if contractor_debt > 0:
        debt_by_contractor[ctg_key] = contractor_debt

# Сортируем по сумме
sorted_debtors = sorted(debt_by_contractor.items(), key=lambda x: x[1], reverse=True)

print(f"\n📊 ВСЕ ДОЛЖНИКИ ({len(sorted_debtors)} контрагентов):")
print("=" * 80)
print(f"{'#':<3} {'Контрагент':<55} {'Сумма':>15}")
print("=" * 80)

total = 0
for idx, (ctg_key, amount) in enumerate(sorted_debtors, 1):
    name = contractor_names.get(ctg_key, f'Unknown ({ctg_key})')
    total += amount
    print(f"{idx:<3} {name:<55} {amount:>15,.2f} ₽")

print("=" * 80)
print(f"{'ВСЕГО':<58} {total:>15,.2f} ₽")
print("=" * 80)

print("\n✅ Проверь этот список с актами сверок!")
