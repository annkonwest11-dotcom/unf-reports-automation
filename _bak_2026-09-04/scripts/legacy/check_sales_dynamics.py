#!/usr/bin/env python3
"""
Динамика продаж по периодам (17.06-23.06.2026)
"""

import requests
import base64
from datetime import datetime, timedelta

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"
BASE_ID = "152757"  # Перфильев
BASE_URL = f"https://base.42clouds.com/unf/{BASE_ID}/odata/standard.odata/"

START_DATE = "2026-06-17"
END_DATE = "2026-06-23"

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

import urllib3
urllib3.disable_warnings()

print(f"""
╔════════════════════════════════════════════════════════════════╗
║  ДИНАМИКА ПРОДАЖ ПО ПЕРИОДАМ                                  ║
║  ИП ПЕРФИЛЬЕВ
║  Период: {START_DATE} - {END_DATE}
╚════════════════════════════════════════════════════════════════╝
""")

print("📋 Загружаю данные из OData...")

# Получаем продажи за период
filter_str = f"Period ge datetime'{START_DATE}T00:00:00' and Period lt datetime'{END_DATE}T23:59:59' and RecordType eq 'Receipt'"
sales = fetch_odata_records('AccumulationRegister_Продажи_RecordType', filter_str)

if not sales:
    print("❌ Не удалось получить данные")
    exit(1)

print(f"✅ Получено {len(sales)} записей\n")

# Группируем по датам
sales_by_date = {}
for s in sales:
    period_str = s.get('Period', '')
    amount = s.get('Сумма', 0) or 0

    try:
        date_str = period_str.split('T')[0]
        if date_str not in sales_by_date:
            sales_by_date[date_str] = 0
        sales_by_date[date_str] += amount
    except:
        pass

# Генерируем все дни периода
start_obj = datetime.strptime(START_DATE, '%Y-%m-%d')
end_obj = datetime.strptime(END_DATE, '%Y-%m-%d')

all_dates = []
current = start_obj
while current <= end_obj:
    date_str = current.strftime('%Y-%m-%d')
    all_dates.append(date_str)
    current += timedelta(days=1)

print("=" * 70)
print(f"{'День':<12} {'Выручка, ₽':>15}")
print("=" * 70)

total_sales = 0
for date_str in all_dates:
    amount = sales_by_date.get(date_str, 0)
    total_sales += amount
    print(f"{date_str:<12} {amount:>15,.2f}")

print("=" * 70)
print(f"{'ИТОГО':<12} {total_sales:>15,.2f}")
print("=" * 70)

# Вычисляем среднее и прогноз
days_count = len(all_dates)
avg_per_day = total_sales / days_count if days_count > 0 else 0
forecast_month = avg_per_day * 30

print(f"\n📊 АНАЛИТИКА:")
print(f"  Дней в периоде: {days_count}")
print(f"  ВСЕГО выручка: {total_sales:,.2f} ₽")
print(f"  Среднее в день: {avg_per_day:,.2f} ₽")
print(f"  Прогноз на месяц (30 дн): {forecast_month:,.2f} ₽")

print(f"\n📌 ЭТАЛОН ИЗ 1С:")
print(f"  ВСЕГО выручка: 324,135.50 ₽")
print(f"  Среднее в день: 46,305.07 ₽")
print(f"  Прогноз на месяц: 1,389,152.14 ₽")

print(f"\n✅ СРАВНЕНИЕ:")
diff = total_sales - 324135.50
status = "✅ СОВПАДАЕТ!" if abs(diff) < 0.01 else f"❌ РАЗНИЦА: {diff:+,.2f} ₽"
print(f"  {status}")
EOF
python3 check_sales_dynamics.py
