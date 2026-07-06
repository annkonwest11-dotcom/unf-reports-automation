#!/usr/bin/env python3
"""
Дебиторка: общая считается правильно, просроченная только для старых операций
Вариант A: просроченная = сумма только заказов старше срока
"""

import requests
import base64
from datetime import datetime, timedelta

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

def get_contracts_with_terms():
    contracts = fetch_odata_records('Catalog_ДоговорыКонтрагентов')
    if not contracts:
        return {}

    contract_terms = {}
    for contract in contracts:
        ref_key = contract.get('Ref_Key')
        owner_key = contract.get('Owner_Key')
        term_days = contract.get('СрокОплатыПокупателя', 0) or 0

        try:
            term_days = int(term_days)
        except (ValueError, TypeError):
            term_days = 0

        if term_days <= 0:
            term_days = 14

        contract_terms[ref_key] = {
            'contractor_key': owner_key,
            'term_days': term_days
        }

    return contract_terms

import urllib3
urllib3.disable_warnings()

print(f"""
╔════════════════════════════════════════════════════════════════╗
║  ДЕБИТОРКА - ПРАВИЛЬНЫЙ РАСЧЁТ                               ║
║  На {TEST_DATE}
║  Вариант A: просроченная = только старые заказы (> срока)
╚════════════════════════════════════════════════════════════════╝
""")

print("📋 Загружаю данные...")
contractor_names = get_contractor_names()
contract_terms = get_contracts_with_terms()

filter_str = f"Period le datetime'{TEST_DATE}T00:00:00'"
settlements = fetch_odata_records('AccumulationRegister_РасчетыСПокупателями_RecordType', filter_str)
print(f"✅ Готово ({len(settlements)} записей)\n")

test_date_obj = datetime.strptime(TEST_DATE, '%Y-%m-%d')

# Группируем по контрагентам и договорам
settlements_by_ctg_deal = {}
receipt_operations = {}  # key: (ctg_key, deal_key, date), value: amount

for r in settlements:
    ctg_key = r.get('Контрагент_Key', 'unknown')
    deal_key = r.get('Договор_Key', 'nodeal')
    amount = r.get('Сумма', 0) or 0
    record_type = r.get('RecordType', 'Receipt')
    period_str = r.get('Period', '')

    if ctg_key not in settlements_by_ctg_deal:
        settlements_by_ctg_deal[ctg_key] = {}
    if deal_key not in settlements_by_ctg_deal[ctg_key]:
        settlements_by_ctg_deal[ctg_key][deal_key] = {'receipt': 0, 'expense': 0}

    if record_type == 'Receipt':
        settlements_by_ctg_deal[ctg_key][deal_key]['receipt'] += amount
        # Сохраняем отдельно каждую Receipt операцию
        try:
            op_date = datetime.fromisoformat(period_str.split('T')[0])
        except:
            op_date = test_date_obj
        key = (ctg_key, deal_key, op_date)
        receipt_operations[key] = receipt_operations.get(key, 0) + amount
    elif record_type == 'Expense':
        settlements_by_ctg_deal[ctg_key][deal_key]['expense'] += amount

# Считаем дебиторку и просроченность
debt_by_contractor = {}

for ctg_key, deals in settlements_by_ctg_deal.items():
    if ctg_key not in debt_by_contractor:
        debt_by_contractor[ctg_key] = {
            'name': contractor_names.get(ctg_key, 'Unknown'),
            'total': 0,
            'overdue': 0
        }

    for deal_key, balances in deals.items():
        balance = balances['receipt'] - balances['expense']
        if balance <= 0:
            continue

        # Добавляем в общую дебиторку
        debt_by_contractor[ctg_key]['total'] += balance

        # Для просроченности: смотрим на Receipt операции
        term_days = 14
        if deal_key in contract_terms:
            term_days = contract_terms[deal_key]['term_days']

        # Считаем просроченную часть
        # Берём все Receipt для этого договора и смотрим, какие старше срока
        overdue_part = 0
        for (r_ctg, r_deal, r_date), r_amount in receipt_operations.items():
            if r_ctg == ctg_key and r_deal == deal_key:
                due_date = r_date + timedelta(days=term_days)
                if test_date_obj > due_date:
                    overdue_part += r_amount

        # Просроченная часть остатка - это доля старых операций от остатка
        if balances['receipt'] > 0:
            # Пропорциональная часть
            overdue_ratio = min(overdue_part / balances['receipt'], 1.0)
            debt_by_contractor[ctg_key]['overdue'] += balance * overdue_ratio

# Сортируем
sorted_contractors = sorted(
    debt_by_contractor.items(),
    key=lambda x: x[1]['total'],
    reverse=True
)

print("=" * 100)
print(f"{'#':<3} {'Контрагент':<50} {'Всего':>15} {'Просроч':>15} {'%':>8}")
print("=" * 100)

total_all = 0
total_overdue = 0

for idx, (ctg_key, details) in enumerate(sorted_contractors, 1):
    name = details['name'][:48]
    total = details['total']
    overdue = details['overdue']

    total_all += total
    total_overdue += overdue

    pct = (overdue / total * 100) if total > 0 else 0

    status = "✅" if overdue == 0 else "⚠️"
    print(f"{idx:<3} {name:<50} {total:>15,.2f} ₽ {overdue:>15,.2f} ₽ {pct:>7.1f}% {status}")

print("=" * 100)
print(f"{'ВСЕГО':<53} {total_all:>15,.2f} ₽ {total_overdue:>15,.2f} ₽ {(total_overdue/total_all*100 if total_all > 0 else 0):>7.1f}%")
print("=" * 100)

print(f"\n📊 ИТОГО:")
print(f"  ✅ Общая дебиторка: {total_all:,.2f} ₽")
print(f"  ⚠️  Просроченная: {total_overdue:,.2f} ₽")
print(f"  📈 Процент просрочки: {(total_overdue/total_all*100 if total_all > 0 else 0):.1f}%")
