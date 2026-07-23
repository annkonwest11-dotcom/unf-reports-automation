#!/usr/bin/env python3
"""
Подробный отчёт по дебиторке с сроками отсрочки
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
    page = 0
    while url:
        page += 1
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
║  ПОДРОБНЫЙ ОТЧЁТ ПО ДЕБИТОРКЕ                                                    ║
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

# Группируем по контрагентам и договорам
settlements_by_ctg_deal = {}
for r in settlements:
    ctg_key = r.get('Контрагент_Key', 'unknown')
    deal_key = r.get('Договор_Key', 'nodeal')
    amount = r.get('Сумма', 0) or 0
    record_type = r.get('RecordType', 'Receipt')
    period_str = r.get('Period', '')

    if ctg_key not in settlements_by_ctg_deal:
        settlements_by_ctg_deal[ctg_key] = {}
    if deal_key not in settlements_by_ctg_deal[ctg_key]:
        settlements_by_ctg_deal[ctg_key][deal_key] = {
            'receipt': 0,
            'expense': 0,
            'first_date': None,
            'contract_key': deal_key
        }

    if period_str:
        try:
            op_date = datetime.fromisoformat(period_str.split('T')[0])
            if not settlements_by_ctg_deal[ctg_key][deal_key]['first_date']:
                settlements_by_ctg_deal[ctg_key][deal_key]['first_date'] = op_date
            else:
                earliest = min(
                    settlements_by_ctg_deal[ctg_key][deal_key]['first_date'],
                    op_date
                )
                settlements_by_ctg_deal[ctg_key][deal_key]['first_date'] = earliest
        except:
            pass

    if record_type == 'Receipt':
        settlements_by_ctg_deal[ctg_key][deal_key]['receipt'] += amount
    elif record_type == 'Expense':
        settlements_by_ctg_deal[ctg_key][deal_key]['expense'] += amount

# Счёт по контрагентам
debt_details = {}

for ctg_key, deals in settlements_by_ctg_deal.items():
    if ctg_key not in debt_details:
        debt_details[ctg_key] = {
            'name': contractor_names.get(ctg_key, 'Unknown'),
            'deals': []
        }

    for deal_key, balances in deals.items():
        balance = balances['receipt'] - balances['expense']
        if balance <= 0:
            continue

        first_date = balances.get('first_date')
        contract_key = deal_key

        # Получаем срок из договора
        term_days = 14
        if contract_key in contract_terms:
            term_days = contract_terms[contract_key]['term_days']

        # Рассчитываем дату просрочки
        due_date = None
        days_overdue = 0
        if first_date:
            due_date = first_date + timedelta(days=term_days)
            if test_date_obj > due_date:
                days_overdue = (test_date_obj - due_date).days

        debt_details[ctg_key]['deals'].append({
            'contract_key': contract_key,
            'amount': balance,
            'first_date': first_date,
            'term_days': term_days,
            'due_date': due_date,
            'days_overdue': days_overdue
        })

# Группируем по контрагентам (сумма всех договоров)
contractors_total = {}
for ctg_key, details in debt_details.items():
    total_debt = sum(d['amount'] for d in details['deals'])
    if total_debt > 0:
        contractors_total[ctg_key] = {
            'name': details['name'],
            'total_debt': total_debt,
            'deals_count': len(details['deals']),
            'deals': details['deals']
        }

# Сортируем
sorted_contractors = sorted(contractors_total.items(), key=lambda x: x[1]['total_debt'], reverse=True)

# Выводим отчёт
print("=" * 130)
print(f"{'#':<3} {'Контрагент':<50} {'Дебиторка':>12} {'Договоров':>10} {'Срок':>8} {'Дата поставки':>18} {'Просрочка':>12}")
print("=" * 130)

for idx, (ctg_key, details) in enumerate(sorted_contractors, 1):
    name = details['name'][:48]
    total = details['total_debt']
    deals_count = details['deals_count']

    # Берём параметры из первого договора (или среднее значение)
    if details['deals']:
        first_deal = details['deals'][0]
        term = first_deal['term_days']
        first_date = first_deal['first_date'].strftime('%Y-%m-%d') if first_deal['first_date'] else 'N/A'
        due_date = first_deal['due_date'].strftime('%Y-%m-%d') if first_deal['due_date'] else 'N/A'
        days_overdue = first_deal['days_overdue']

        print(f"{idx:<3} {name:<50} {total:>12,.2f} ₽ {deals_count:>10} {term:>8}д  {first_date:>18}  {days_overdue:>10}д 🔴")

        # Если несколько договоров, выводим остальные
        for deal in details['deals'][1:]:
            term = deal['term_days']
            first_date = deal['first_date'].strftime('%Y-%m-%d') if deal['first_date'] else 'N/A'
            days_overdue = deal['days_overdue']
            print(f"    └─ Договор: {deal['amount']:>12,.2f} ₽                    {term:>8}д  {first_date:>18}  {days_overdue:>10}д")

print("=" * 130)

# Итого
total_debt_all = sum(d['total_debt'] for d in contractors_total.values())
print(f"ВСЕГО: {total_debt_all:,.2f} ₽")
print("\n✅ Проверь эти суммы с актами сверок!")
print("📌 Столбцы:")
print("   • Срок - кол-во дней отсрочки из договора")
print("   • Дата поставки - первая дата операции (Receipt)")
print("   • Просрочка - на сколько дней превышен срок (дней после срока платежа)")
