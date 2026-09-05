#!/usr/bin/env python3
"""
Подробный отчёт - считаем просроченность для КАЖДОГО ЗАКАЗА отдельно
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
    """Получить договоры со сроками платежа"""
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
╔════════════════════════════════════════════════════════════════════════════════════╗
║  ОТЧЁТ ПО ДЕБИТОРКЕ - РАСЧЁТ ДЛЯ КАЖДОГО ЗАКАЗА ОТДЕЛЬНО                        ║
║  На {TEST_DATE}
╚════════════════════════════════════════════════════════════════════════════════════╝
""")

# Загружаем данные
print("📋 Загружаю данные...")
contractor_names = get_contractor_names()
contract_terms = get_contracts_with_terms()

filter_str = f"Period le datetime'{TEST_DATE}T00:00:00'"
settlements = fetch_odata_records('AccumulationRegister_РасчетыСПокупателями_RecordType', filter_str)
print(f"✅ Готово\n")

test_date_obj = datetime.strptime(TEST_DATE, '%Y-%m-%d')

# Считаем для КАЖДОЙ операции Receipt отдельно
order_details = {}  # key: (ctg_key, deal_key, period), value: {amount, overdue, term_days, ...}

# Сначала собираем все Receipt операции
receipts = {}  # key: (ctg_key, deal_key, period), value: amount
expenses = {}  # key: (ctg_key, deal_key, period), value: amount

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

    key = (ctg_key, deal_key, period_date)

    if record_type == 'Receipt':
        receipts[key] = receipts.get(key, 0) + amount
    elif record_type == 'Expense':
        expenses[key] = expenses.get(key, 0) + amount

# Теперь считаем остаток для каждого заказа
# Берём Receipt минус все последующие Expense
for (ctg_key, deal_key, period_date), receipt_amount in receipts.items():
    # Собираем все Expense для этого договора, которые >= этой даты
    total_expense = 0
    for (exp_ctg, exp_deal, exp_date), exp_amount in expenses.items():
        if exp_ctg == ctg_key and exp_deal == deal_key and exp_date >= period_date:
            total_expense += exp_amount

    balance = receipt_amount - total_expense

    if balance > 0:  # Это непокрытая задолженность
        # Получаем срок из договора
        term_days = 14
        if deal_key in contract_terms:
            term_days = contract_terms[deal_key]['term_days']

        # Рассчитываем просроченность
        due_date = period_date + timedelta(days=term_days)
        days_overdue = 0
        is_overdue = False

        if test_date_obj > due_date:
            days_overdue = (test_date_obj - due_date).days
            is_overdue = True

        order_details[(ctg_key, deal_key, period_date)] = {
            'amount': balance,
            'term_days': term_days,
            'date': period_date,
            'due_date': due_date,
            'days_overdue': days_overdue,
            'is_overdue': is_overdue
        }

# Группируем по контрагентам
contractors_data = {}
for (ctg_key, deal_key, period_date), order_info in order_details.items():
    if ctg_key not in contractors_data:
        contractors_data[ctg_key] = {
            'name': contractor_names.get(ctg_key, 'Unknown'),
            'total': 0,
            'overdue_total': 0,
            'orders': []
        }

    contractors_data[ctg_key]['total'] += order_info['amount']
    if order_info['is_overdue']:
        contractors_data[ctg_key]['overdue_total'] += order_info['amount']

    contractors_data[ctg_key]['orders'].append(order_info)

# Сортируем
sorted_contractors = sorted(
    contractors_data.items(),
    key=lambda x: x[1]['total'],
    reverse=True
)

# Выводим отчёт
print("=" * 140)
print(f"{'#':<3} {'Контрагент':<50} {'Всего':>12} {'Просроч':>12} {'Заказов':>8} {'Срок':>8}")
print("=" * 140)

for idx, (ctg_key, details) in enumerate(sorted_contractors, 1):
    name = details['name'][:48]
    total = details['total']
    overdue = details['overdue_total']
    orders_count = len(details['orders'])

    # Берём срок из первого заказа
    term = details['orders'][0]['term_days'] if details['orders'] else 14

    pct = (overdue / total * 100) if total > 0 else 0

    print(f"{idx:<3} {name:<50} {total:>12,.2f} ₽ {overdue:>12,.2f} ₽ {orders_count:>8} {term:>8}д")

    # Выводим по заказам
    for order in sorted(details['orders'], key=lambda x: x['date']):
        date_str = order['date'].strftime('%Y-%m-%d')
        due_str = order['due_date'].strftime('%Y-%m-%d')
        status = "🔴 ПРОСРОЧЕН" if order['is_overdue'] else "✅ В СРОКЕ"

        print(f"      └─ {date_str} → {due_str}  {order['amount']:>12,.2f} ₽  {order['term_days']:>6}д  {status:>15} ({order['days_overdue']:>3}д)")

print("=" * 140)

# Итого
total_all = sum(d['total'] for d in contractors_data.values())
total_overdue_all = sum(d['overdue_total'] for d in contractors_data.values())

print(f"\n📊 ИТОГО:")
print(f"  Всего дебиторка: {total_all:,.2f} ₽")
print(f"  Просроченная: {total_overdue_all:,.2f} ₽")
print(f"  Процент: {(total_overdue_all/total_all*100 if total_all > 0 else 0):.1f}%")
