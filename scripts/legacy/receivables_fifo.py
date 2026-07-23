#!/usr/bin/env python3
"""
Дебиторка с логикой FIFO:
- Каждый Receipt операция = отдельный "долг" с датой
- Платежи (Expense) погашают старые заказы ПЕРВЫМИ
- Просроченная = сумма Receipt старше срока
"""

import requests
import base64
from datetime import datetime, timedelta

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"
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
        term_days = contract.get('СрокОплатыПокупателя', 0) or 0
        try:
            term_days = int(term_days)
        except:
            term_days = 0
        if term_days <= 0:
            term_days = 14
        contract_terms[ref_key] = term_days

    return contract_terms

import urllib3
urllib3.disable_warnings()

print(f"""
╔════════════════════════════════════════════════════════════════╗
║  ДЕБИТОРКА - FIFO (старые заказы погашаются первыми)         ║
║  На {TEST_DATE}
╚════════════════════════════════════════════════════════════════╝
""")

print("📋 Загружаю данные...")
contractor_names = get_contractor_names()
contract_terms = get_contracts_with_terms()

filter_str = f"Period le datetime'{TEST_DATE}T00:00:00'"
settlements = fetch_odata_records('AccumulationRegister_РасчетыСПокупателями_RecordType', filter_str)
print(f"✅ Готово\n")

test_date_obj = datetime.strptime(TEST_DATE, '%Y-%m-%d')

# Группируем по контрагентам и договорам
data_by_ctg_deal = {}  # key: (ctg_key, deal_key)

for r in settlements:
    ctg_key = r.get('Контрагент_Key', 'unknown')
    deal_key = r.get('Договор_Key', 'nodeal')
    amount = r.get('Сумма', 0) or 0
    record_type = r.get('RecordType', 'Receipt')
    period_str = r.get('Period', '')

    try:
        period_date = datetime.fromisoformat(period_str.split('T')[0])
    except:
        period_date = test_date_obj

    key = (ctg_key, deal_key)
    if key not in data_by_ctg_deal:
        data_by_ctg_deal[key] = {
            'receipts': [],  # list of (date, amount)
            'expenses': 0,   # total expenses
            'contract_key': deal_key
        }

    if record_type == 'Receipt':
        data_by_ctg_deal[key]['receipts'].append((period_date, amount))
    elif record_type == 'Expense':
        data_by_ctg_deal[key]['expenses'] += amount

# Теперь для каждого договора считаем FIFO
debt_by_contractor = {}

for (ctg_key, deal_key), data in data_by_ctg_deal.items():
    # Сортируем Receipt по датам (старые первыми)
    receipts_sorted = sorted(data['receipts'], key=lambda x: x[0])

    # Общий долг
    total_receipt = sum(amount for _, amount in receipts_sorted)
    total_expense = data['expenses']
    balance = total_receipt - total_expense

    if balance <= 0:
        continue  # Нет задолженности

    if ctg_key not in debt_by_contractor:
        debt_by_contractor[ctg_key] = {
            'name': contractor_names.get(ctg_key, 'Unknown'),
            'total': 0,
            'overdue': 0
        }

    debt_by_contractor[ctg_key]['total'] += balance

    # Считаем просроченную часть FIFO
    # Платежи погашают старые заказы ПЕРВЫМИ
    term_days = contract_terms.get(deal_key, 14)

    remaining_to_pay = balance  # Остаток, который нужно оплатить
    overdue_part = 0

    # Идём по Receipt от старых к новым (FIFO)
    for receipt_date, receipt_amount in receipts_sorted:
        if remaining_to_pay <= 0:
            break

        due_date = receipt_date + timedelta(days=term_days)

        # Сколько из этого заказа нужно погасить платежами?
        amount_to_cover = min(receipt_amount, remaining_to_pay)
        remaining_to_pay -= amount_to_cover

        # Если этот заказ просроченный, добавляем в просроченную дебиторку
        if test_date_obj > due_date:
            overdue_part += amount_to_cover

    debt_by_contractor[ctg_key]['overdue'] += overdue_part

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
print(f"  ⚠️  Просроченная (FIFO): {total_overdue:,.2f} ₽")
print(f"  📈 Процент просрочки: {(total_overdue/total_all*100 if total_all > 0 else 0):.1f}%")
