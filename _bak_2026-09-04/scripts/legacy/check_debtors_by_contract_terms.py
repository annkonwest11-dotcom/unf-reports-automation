#!/usr/bin/env python3
"""
Дебиторка с учётом ПРАВИЛЬНЫХ сроков платежа из договоров
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

    # Создаём карту: договор_key -> (контрагент_key, срок_дней)
    contract_terms = {}
    for contract in contracts:
        ref_key = contract.get('Ref_Key')
        owner_key = contract.get('Owner_Key')  # Контрагент
        term_days = contract.get('СрокОплатыПокупателя', 0) or 0

        # Конвертируем в число
        try:
            term_days = int(term_days)
        except (ValueError, TypeError):
            term_days = 0

        # Если срок = 0, используем 14 дней по умолчанию
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
║  ДЕБИТОРКА С УЧЁТОМ ПРАВИЛЬНЫХ СРОКОВ ИЗ ДОГОВОРОВ           ║
║  На {TEST_DATE}
╚════════════════════════════════════════════════════════════════╝
""")

# Загружаем данные
print("📋 Загружаю справочники...")
contractor_names = get_contractor_names()
print(f"  ✅ Контрагентов: {len(contractor_names)}")

print("📋 Загружаю договоры со сроками...")
contract_terms = get_contracts_with_terms()
print(f"  ✅ Договоров: {len(contract_terms)}")

print("💳 Загружаю дебиторку...")
filter_str = f"Period le datetime'{TEST_DATE}T00:00:00'"
settlements = fetch_odata_records('AccumulationRegister_РасчетыСПокупателями_RecordType', filter_str)
print(f"  ✅ Записей: {len(settlements)}")

# Считаем дебиторку с учётом сроков
test_date_obj = datetime.strptime(TEST_DATE, '%Y-%m-%d')

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

    # Запоминаем первую дату операции (дату поставки)
    if period_str:
        try:
            op_date = datetime.fromisoformat(period_str.split('T')[0])
            if not settlements_by_ctg_deal[ctg_key][deal_key]['first_date']:
                settlements_by_ctg_deal[ctg_key][deal_key]['first_date'] = op_date
            else:
                # Берём самую раннюю дату
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

# Считаем итоги с правильными сроками просрочки
debt_by_contractor = {}

for ctg_key, deals in settlements_by_ctg_deal.items():
    if ctg_key not in debt_by_contractor:
        debt_by_contractor[ctg_key] = {'total': 0, 'overdue': 0}

    for deal_key, balances in deals.items():
        balance = balances['receipt'] - balances['expense']
        if balance <= 0:
            continue

        # Добавляем в общую дебиторку
        debt_by_contractor[ctg_key]['total'] += balance

        # Проверяем просроченность по срокам договора
        first_date = balances.get('first_date')
        if first_date:
            # Получаем срок из договора
            contract_key = deal_key
            term_days = 14  # По умолчанию

            if contract_key in contract_terms:
                term_days = contract_terms[contract_key]['term_days']

            # Вычисляем дату, до которой был срок платежа
            due_date = first_date + timedelta(days=term_days)

            # Если сегодня после срока - это просроченная дебиторка
            if test_date_obj > due_date:
                debt_by_contractor[ctg_key]['overdue'] += balance

# Фильтруем должников и сортируем
debtors = {k: v for k, v in debt_by_contractor.items() if v['total'] > 0}
sorted_debtors = sorted(debtors.items(), key=lambda x: x[1]['total'], reverse=True)

print(f"\n📊 ДЕБИТОРКА ПО КОНТРАГЕНТАМ ({len(sorted_debtors)} контрагентов):")
print("=" * 100)
print(f"{'#':<3} {'Контрагент':<50} {'Общая':>15} {'Просроченная':>15} {'%':>8}")
print("=" * 100)

total_all = 0
total_overdue = 0

for idx, (ctg_key, debt_info) in enumerate(sorted_debtors, 1):
    name = contractor_names.get(ctg_key, f'Unknown ({ctg_key})')
    total_debt = debt_info['total']
    overdue_debt = debt_info['overdue']

    total_all += total_debt
    total_overdue += overdue_debt

    pct = (overdue_debt / total_debt * 100) if total_debt > 0 else 0

    print(f"{idx:<3} {name:<50} {total_debt:>15,.2f} ₽ {overdue_debt:>15,.2f} ₽ {pct:>7.1f}%")

print("=" * 100)
print(f"{'ВСЕГО':<53} {total_all:>15,.2f} ₽ {total_overdue:>15,.2f} ₽ {(total_overdue/total_all*100 if total_all > 0 else 0):>7.1f}%")
print("=" * 100)

print(f"\n📊 ИТОГО:")
print(f"  ✅ Общая дебиторка: {total_all:,.2f} ₽")
print(f"  ⚠️  Просроченная: {total_overdue:,.2f} ₽")
print(f"  📈 Процент просрочки: {(total_overdue/total_all*100 if total_all > 0 else 0):.1f}%")
