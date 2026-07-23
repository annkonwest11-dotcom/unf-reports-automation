#!/usr/bin/env python3
"""
Анализ активности клиентов (10.06-24.06.2026)
"""

import requests
import base64
from datetime import datetime, timedelta
from collections import defaultdict

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"
BASE_URL = f"https://base.42clouds.com/unf/{BASE_ID}/odata/standard.odata/"

START_DATE = "2026-06-10"
END_DATE = "2026-06-24"

def get_basic_auth():
    creds = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}

def fetch_odata(entity):
    url = f"{BASE_URL}{entity}"
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
    contractors = fetch_odata('Catalog_Контрагенты')
    if not contractors:
        return {}
    names_map = {}
    for c in contractors:
        ref_key = c.get('Ref_Key')
        description = c.get('Description', 'Unknown')
        names_map[ref_key] = description
    return names_map

import urllib3
urllib3.disable_warnings()

print(f"""
╔════════════════════════════════════════════════════════════════╗
║  АНАЛИЗ АКТИВНОСТИ КЛИЕНТОВ                                   ║
║  Период: {START_DATE} - {END_DATE}
╚════════════════════════════════════════════════════════════════╝
""")

print("📋 Загружаю данные...")

# Получаем продажи
sales = fetch_odata('AccumulationRegister_Продажи_RecordType')
contractor_names = get_contractor_names()

if not sales:
    print("❌ Нет данных")
    exit(1)

print(f"✅ Получено {len(sales)} записей\n")

# Группируем по клиентам и датам
customer_data = defaultdict(lambda: {
    'sales_by_date': defaultdict(float),
    'total_amount': 0,
    'order_dates': set()
})

for s in sales:
    period = s.get('Period', '')
    date_str = period[:10]

    # Проверяем, входит ли дата в период
    if date_str < START_DATE or date_str > END_DATE:
        continue

    ctg_key = s.get('Контрагент_Key', 'unknown')
    amount = s.get('Сумма', 0) or 0

    customer_data[ctg_key]['sales_by_date'][date_str] += amount
    customer_data[ctg_key]['total_amount'] += amount
    customer_data[ctg_key]['order_dates'].add(date_str)

# Анализируем активность для каждого клиента
today = datetime.strptime(END_DATE, '%Y-%m-%d')

analysis = []

for ctg_key, data in customer_data.items():
    name = contractor_names.get(ctg_key, 'Unknown')
    total_amount = data['total_amount']
    order_dates = sorted(data['order_dates'])

    if not order_dates:
        continue

    # Считаем периодичность (интервалы между заказами)
    intervals = []
    for i in range(1, len(order_dates)):
        date1 = datetime.strptime(order_dates[i-1], '%Y-%m-%d')
        date2 = datetime.strptime(order_dates[i], '%Y-%m-%d')
        interval = (date2 - date1).days
        intervals.append(interval)

    avg_periodicity = sum(intervals) / len(intervals) if intervals else 0

    # Дней без заказов (от последнего заказа до сегодня)
    last_order_date = datetime.strptime(order_dates[-1], '%Y-%m-%d')
    days_without_orders = (today - last_order_date).days

    # Отклонение
    deviation = days_without_orders - avg_periodicity

    # Статус
    status = "✅"
    if deviation >= 3:
        status = "🔴 КРИТИЧНО"
    elif deviation >= 1:
        status = "⚠️ ВНИМАНИЕ"

    analysis.append({
        'name': name,
        'total_amount': total_amount,
        'order_count': len(order_dates),
        'last_order': order_dates[-1],
        'avg_periodicity': round(avg_periodicity, 1),
        'days_without_orders': days_without_orders,
        'deviation': round(deviation, 1),
        'status': status,
        'ctg_key': ctg_key
    })

# Сортируем: сначала критичные, потом по объёму продаж
analysis.sort(key=lambda x: (
    0 if "КРИТИЧНО" in x['status'] else (1 if "ВНИМАНИЕ" in x['status'] else 2),
    -x['total_amount']
))

print("=" * 130)
print(f"{'Клиент':<50} {'ИТОГО':>12} {'Заказов':>8} {'Последний':>12} {'Период':>8} {'Дней БЕЗ':>8} {'Откл.':>8} {'Статус':>15}")
print("=" * 130)

for item in analysis:
    print(f"{item['name']:<50} {item['total_amount']:>12,.2f} ₽ {item['order_count']:>8} {item['last_order']:>12} {item['avg_periodicity']:>8.1f}д {item['days_without_orders']:>8}д {item['deviation']:>8.1f}д {item['status']:>15}")

print("=" * 130)

# Статистика
critical = [a for a in analysis if "КРИТИЧНО" in a['status']]
warning = [a for a in analysis if "ВНИМАНИЕ" in a['status']]

print(f"\n📊 СТАТИСТИКА:")
print(f"  Всего клиентов: {len(analysis)}")
print(f"  🔴 КРИТИЧНО (отклонение ≥ 3 дня): {len(critical)}")
print(f"  ⚠️ ВНИМАНИЕ (отклонение 1-2 дня): {len(warning)}")
print(f"  ✅ В НОРМЕ: {len(analysis) - len(critical) - len(warning)}")

if critical:
    print(f"\n🔴 КРИТИЧНЫЕ (требуют внимания):")
    for item in critical[:10]:
        print(f"   • {item['name']}: {item['days_without_orders]}д без заказа (период {item['avg_periodicity']}д, откл. +{item['deviation']}д)")
EOF
python3 analyze_customer_activity.py
