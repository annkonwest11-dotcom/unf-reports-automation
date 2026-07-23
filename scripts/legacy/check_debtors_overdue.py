#!/usr/bin/env python3
"""
Дебиторка с разбивкой на общую и просроченную
"""

import requests
import base64
from datetime import datetime, timedelta

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"  # Перфильев
BASE_URL = f"https://base.42clouds.com/unf/{BASE_ID}/odata/standard.odata/"
TEST_DATE = "2026-06-24"
OVERDUE_DAYS = 14  # Просроченная = старше 14 дней от даты поставки

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

# Отключить SSL warnings
import urllib3
urllib3.disable_warnings()

print(f"""
╔════════════════════════════════════════════════════════════════╗
║  ДЕБИТОРКА С РАЗБИВКОЙ НА ОБЩУЮ И ПРОСРОЧЕННУЮ                ║
║  На {TEST_DATE} (просроченная > {OVERDUE_DAYS} дней)
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

# Дата для расчета просрочки
test_date_obj = datetime.strptime(TEST_DATE, '%Y-%m-%d')
overdue_threshold = test_date_obj - timedelta(days=OVERDUE_DAYS)

# Считаем дебиторку с разбивкой по датам
debt_by_contractor = {}
overdue_by_contractor = {}

for r in settlements:
    ctg_key = r.get('Контрагент_Key', 'unknown')
    deal_key = r.get('Договор_Key', 'nodeal')
    amount = r.get('Сумма', 0) or 0
    record_type = r.get('RecordType', 'Receipt')
    period_str = r.get('Period', '')  # Дата операции

    # Инициализируем контрагента
    if ctg_key not in debt_by_contractor:
        debt_by_contractor[ctg_key] = {'total': 0, 'deals': {}}
        overdue_by_contractor[ctg_key] = {'total': 0, 'deals': {}}

    if deal_key not in debt_by_contractor[ctg_key]['deals']:
        debt_by_contractor[ctg_key]['deals'][deal_key] = {'receipt': 0, 'expense': 0}
        overdue_by_contractor[ctg_key]['deals'][deal_key] = {'receipt': 0, 'expense': 0}

    # Добавляем операцию
    if record_type == 'Receipt':
        debt_by_contractor[ctg_key]['deals'][deal_key]['receipt'] += amount
    elif record_type == 'Expense':
        debt_by_contractor[ctg_key]['deals'][deal_key]['expense'] += amount

    # Проверяем просрочку (если период старше чем OVERDUE_DAYS)
    try:
        if period_str:
            # Парсим дату (формат: 2026-06-24T12:34:56)
            period_date = datetime.fromisoformat(period_str.split('T')[0])
            if period_date <= overdue_threshold:
                if record_type == 'Receipt':
                    overdue_by_contractor[ctg_key]['deals'][deal_key]['receipt'] += amount
                elif record_type == 'Expense':
                    overdue_by_contractor[ctg_key]['deals'][deal_key]['expense'] += amount
    except:
        pass

# Считаем итоги по контрагентам
for ctg_key in debt_by_contractor:
    # Общая дебиторка (только положительные остатки)
    for deal_key, balances in debt_by_contractor[ctg_key]['deals'].items():
        balance = balances['receipt'] - balances['expense']
        if balance > 0:
            debt_by_contractor[ctg_key]['total'] += balance

    # Просроченная (только положительные остатки)
    for deal_key, balances in overdue_by_contractor[ctg_key]['deals'].items():
        balance = balances['receipt'] - balances['expense']
        if balance > 0:
            overdue_by_contractor[ctg_key]['total'] += balance

# Фильтруем только должников
debtors = {k: v for k, v in debt_by_contractor.items() if v['total'] > 0}
sorted_debtors = sorted(debtors.items(), key=lambda x: x[1]['total'], reverse=True)

print(f"\n📊 ДЕБИТОРКА ПО КОНТРАГЕНТАМ ({len(sorted_debtors)} контрагентов):")
print("=" * 95)
print(f"{'#':<3} {'Контрагент':<50} {'Общая':>15} {'Просроченная':>15}")
print("=" * 95)

total_all = 0
total_overdue = 0

for idx, (ctg_key, debt_info) in enumerate(sorted_debtors, 1):
    name = contractor_names.get(ctg_key, f'Unknown ({ctg_key})')
    total_debt = debt_info['total']
    overdue_debt = overdue_by_contractor[ctg_key]['total']

    total_all += total_debt
    total_overdue += overdue_debt

    pct = (overdue_debt / total_debt * 100) if total_debt > 0 else 0

    print(f"{idx:<3} {name:<50} {total_debt:>15,.2f} ₽ {overdue_debt:>15,.2f} ₽ ({pct:>5.1f}%)")

print("=" * 95)
print(f"{'ВСЕГО':<53} {total_all:>15,.2f} ₽ {total_overdue:>15,.2f} ₽")
print("=" * 95)

print(f"\n✅ Общая дебиторка: {total_all:,.2f} ₽")
print(f"⚠️  Просроченная (> {OVERDUE_DAYS} дней): {total_overdue:,.2f} ₽")
print(f"📊 Процент просрочки: {(total_overdue/total_all*100 if total_all > 0 else 0):.1f}%")
