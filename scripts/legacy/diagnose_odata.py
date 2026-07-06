#!/usr/bin/env python3
"""
Диагностика OData для UNF Reports — проверка продаж и дебиторки
"""
import requests
import json
from datetime import datetime, timedelta
from base64 import b64encode
from collections import defaultdict

# Конфигурация
ODATA_USER = 'api_bot'
ODATA_PASS = 'slavaperfilev1414'
BASES = {
    'perfilev': 'https://base.42clouds.com/unf/152757/odata/standard.odata/',
    'gubarev': 'https://base.42clouds.com/unf/64904/odata/standard.odata/',
}

# Дата для тестирования
TEST_DATE = '2026-06-18'
NEXT_DAY = '2026-06-19'

def build_auth():
    creds = f'{ODATA_USER}:{ODATA_PASS}'
    b64 = b64encode(creds.encode()).decode()
    return f'Basic {b64}'

def fetch_odata(base_id, entity, filter_str=''):
    """Читает все записи из OData с пагинацией"""
    base_url = BASES[base_id]
    url = f'{base_url}{entity}?$format=json'
    if filter_str:
        url += f'&$filter={filter_str}'

    headers = {
        'Authorization': build_auth(),
        'Accept': 'application/json'
    }

    results = []
    page = 1
    while url:
        # print(f'Fetching page {page}: {url[:80]}...')
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f'ERROR {resp.status_code}: {resp.text[:200]}')
            break

        data = resp.json()
        if 'value' in data:
            results.extend(data['value'])
            # print(f'  → {len(data["value"])} records, total so far: {len(results)}')

        url = data.get('@odata.nextLink')
        page += 1

    return results

def get_contractor_names(base_id):
    """Получает каталог контрагентов"""
    contractors = fetch_odata(base_id, 'Catalog_Контрагенты', '')
    names = {}
    for c in contractors:
        key = c.get('Ref_Key')
        desc = c.get('Description')
        if key and desc:
            names[key] = desc
    return names

def format_money(v):
    return f'{int(v):,} ₽'.replace(',', ' ')

def diagnose_sales(base_id):
    """Диагностика продаж за день"""
    print(f'\n{"="*70}')
    print(f'ДИАГНОСТИКА ПРОДАЖ: {base_id.upper()} за {TEST_DATE}')
    print(f'{"="*70}')

    # Читаем имена контрагентов
    contractor_names = get_contractor_names(base_id)
    print(f'Загружено {len(contractor_names)} имён контрагентов')

    # Фильтр: дата в диапазоне, Active=true
    filter_str = f"Period ge datetime'{TEST_DATE}T00:00:00' and Period lt datetime'{NEXT_DAY}T00:00:00' and Active eq true"

    sales = fetch_odata(base_id, 'AccumulationRegister_Продажи_RecordType', filter_str)
    print(f'\n📊 Всего записей с Active=true: {len(sales)}')

    # Анализ по RecordType
    by_record_type = defaultdict(int)
    for s in sales:
        rt = s.get('RecordType', 'Receipt')
        by_record_type[rt] += 1

    print('\nРазбивка по RecordType:')
    for rt, count in sorted(by_record_type.items()):
        print(f'  {rt}: {count}')

    # Считаем только Receipt (продажи)
    receipts = [s for s in sales if s.get('RecordType', 'Receipt') == 'Receipt']
    print(f'\n💰 Receipt записей (продажи): {len(receipts)}')

    total_sum = sum(r.get('Сумма', 0) for r in receipts)
    print(f'   СУММА: {format_money(total_sum)}')
    print(f'   ⚖️  Эталон из 1С: 38 050 ₽ (Перфильев)')
    diff = total_sum - 38050
    print(f'   ✅ Совпадение!' if diff == 0 else f'   ⚠️  Расхождение: {format_money(diff)}')

    # Топ-5 по сумме (по контрагентам)
    by_contractor = defaultdict(float)
    for r in receipts:
        key = r.get('Контрагент_Key', 'unknown')
        by_contractor[key] += r.get('Сумма', 0)

    print(f'\nТоп-5 контрагентов по продажам:')
    for key, amount in sorted(by_contractor.items(), key=lambda x: x[1], reverse=True)[:5]:
        name = contractor_names.get(key, f'Unknown({key[:8]})')
        print(f'  {name}: {format_money(amount)}')

    return {
        'total_sales': total_sum,
        'receipt_count': len(receipts),
        'contractors': by_contractor,
        'names': contractor_names
    }

def diagnose_receivables(base_id):
    """Диагностика дебиторки"""
    print(f'\n{"="*70}')
    print(f'ДИАГНОСТИКА ДЕБИТОРКИ: {base_id.upper()} по {NEXT_DAY}')
    print(f'{"="*70}')

    # Читаем имена контрагентов
    contractor_names = get_contractor_names(base_id)
    print(f'Загружено {len(contractor_names)} имён контрагентов')

    # Читаем все расчёты с покупателями до даты включительно
    filter_str = f"Period le datetime'{NEXT_DAY}T00:00:00'"
    settlements = fetch_odata(base_id, 'AccumulationRegister_РасчетыСПокупателями_RecordType', filter_str)
    print(f'\n💼 Всего записей в РасчетыСПокупателями: {len(settlements)}')

    # Структурируем по (контрагент + договор)
    by_contractor_deal = defaultdict(lambda: defaultdict(lambda: {'receipt': 0, 'expense': 0}))

    for s in settlements:
        ctg_key = s.get('Контрагент_Key', 'unknown')
        deal_key = s.get('Договор_Key', 'nodeal')
        amount = s.get('Сумма', 0)
        record_type = s.get('RecordType', 'Receipt')

        if record_type == 'Receipt':
            by_contractor_deal[ctg_key][deal_key]['receipt'] += amount
        elif record_type == 'Expense':
            by_contractor_deal[ctg_key][deal_key]['expense'] += amount

    # Считаем долги: для каждого контрагента — сумма положительных остатков по договорам
    debt_by_contractor = {}
    for ctg_key, deals in by_contractor_deal.items():
        debt = 0
        for deal_key, balances in deals.items():
            balance = balances['receipt'] - balances['expense']
            if balance > 0:  # Только долги, авансы не вычитаем
                debt += balance
        if debt > 0:
            debt_by_contractor[ctg_key] = debt

    total_debt = sum(debt_by_contractor.values())
    print(f'\n💳 ИТОГО ДЕБИТОРКА (положительные остатки по договорам): {format_money(total_debt)}')
    print(f'   ⚖️  Эталон из 1С: ≈ 1 457 629 ₽ (Перфильев)')
    diff = total_debt - 1457629
    print(f'   ⚠️  Расхождение: {format_money(diff)} ({int(diff/1457629*100):+d}%)')

    # Топ-5
    print(f'\nТоп-5 контрагентов по дебиторке:')
    top5 = sorted(debt_by_contractor.items(), key=lambda x: x[1], reverse=True)[:5]
    for ctg_key, debt in top5:
        name = contractor_names.get(ctg_key, f'Unknown({ctg_key[:8]})')
        print(f'  {name}: {format_money(debt)}')

    # Эталоны из 1С (если это Перфильев)
    if base_id == 'perfilev':
        print(f'\n✅ Эталоны топ-5 из 1С (должны совпадать):')
        expected = {
            'А 81 (перевод)': 305498,
            'ФРЕСА': 250128,
            'Кросс док Слава (наличка)': 158350,
            'А20': 125417,
            'ДИМА': 106901,
        }
        for name, expected_amount in expected.items():
            # Ищем контрагента по имени
            key = next((k for k, v in contractor_names.items() if name in v), None)
            if key:
                actual = debt_by_contractor.get(key, 0)
                match = '✅' if abs(actual - expected_amount) < 1 else '❌'
                print(f'  {match} {name}: OData={format_money(actual)}, 1С={format_money(expected_amount)}')
            else:
                print(f'  ❌ {name}: не найден в OData')

    return {
        'total_debt': total_debt,
        'contractors': debt_by_contractor,
        'names': contractor_names
    }

if __name__ == '__main__':
    try:
        print('🔍 ПОЛНАЯ ДИАГНОСТИКА OData 1С базы')
        print('Анализируем продажи и дебиторку...\n')

        for base_id in ['perfilev', 'gubarev']:
            sales = diagnose_sales(base_id)
            recv = diagnose_receivables(base_id)

        print(f'\n{"="*70}')
        print('✅ Диагностика завершена')
        print('='*70)
    except Exception as e:
        print(f'\n❌ ОШИБКА: {e}')
        import traceback
        traceback.print_exc()
