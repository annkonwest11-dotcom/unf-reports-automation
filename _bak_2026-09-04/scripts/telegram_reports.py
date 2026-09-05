#!/usr/bin/env python3
"""
Отправка отчётов в Telegram (по запросу)
Поддерживает: Перфильев (152757) и Губарев (64904)
"""

import requests
import base64
from datetime import datetime, timedelta
from collections import defaultdict

# Параметры
TELEGRAM_TOKEN = "8102009778:AAEsLCAZEpb7mDSO-6aRNhsUSB30g1n_meM"
TELEGRAM_CHAT = 796207056

BASES = {
    'perfilev': {'id': 152757, 'name': 'ИП Перфильев'},
    'gubarev': {'id': 64904, 'name': 'ИП Губарев'}
}

LOGIN = "api_bot"
PASSWORD = "slavaperfilev1414"

def get_base_url(base_id):
    return f"https://base.42clouds.com/unf/{base_id}/odata/standard.odata/"

def get_basic_auth():
    creds = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}

def fetch_odata(base_id, entity):
    url = f"{get_base_url(base_id)}{entity}"
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

def send_telegram(text, parse_mode="Markdown"):
    """Отправляет сообщение в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except:
        return False

def get_contractor_names(base_id):
    contractors = fetch_odata(base_id, 'Catalog_Контрагенты')
    if not contractors:
        return {}
    names_map = {}
    for c in contractors:
        ref_key = c.get('Ref_Key')
        description = c.get('Description', 'Unknown')
        names_map[ref_key] = description
    return names_map

# ========== ОТЧЁТ 1: ПРОДАЖИ ==========
def report_sales(base_id, base_name, date_str):
    """Продажи за день"""
    sales = fetch_odata(base_id, 'AccumulationRegister_Продажи_RecordType')
    if not sales:
        return None

    total = 0
    for s in sales:
        period = s.get('Period', '')
        if period.startswith(date_str):
            amount = s.get('Сумма', 0) or 0
            total += amount

    msg = f"📊 *{base_name} — ПРОДАЖИ за {date_str}*\n"
    msg += f"Выручка: `{total:,.2f} ₽`\n"
    return msg

# ========== ОТЧЁТ 2: ДЕБИТОРКА ==========
def report_receivables(base_id, base_name):
    """Дебиторка (общая)"""
    contractor_names = get_contractor_names(base_id)
    settlements = fetch_odata(base_id, 'AccumulationRegister_РасчетыСПокупателями_RecordType')

    if not settlements:
        return None

    debt_by_ctg = {}
    for s in settlements:
        ctg_key = s.get('Контрагент_Key', 'unknown')
        amount = s.get('Сумма', 0) or 0
        record_type = s.get('RecordType', 'Receipt')

        if ctg_key not in debt_by_ctg:
            debt_by_ctg[ctg_key] = {'receipt': 0, 'expense': 0}

        if record_type == 'Receipt':
            debt_by_ctg[ctg_key]['receipt'] += amount
        elif record_type == 'Expense':
            debt_by_ctg[ctg_key]['expense'] += amount

    total_debt = 0
    top_debtors = []

    for ctg_key, balances in debt_by_ctg.items():
        balance = balances['receipt'] - balances['expense']
        if balance > 0:
            total_debt += balance
            top_debtors.append({
                'name': contractor_names.get(ctg_key, 'Unknown')[:30],
                'amount': balance
            })

    top_debtors.sort(key=lambda x: x['amount'], reverse=True)

    msg = f"💳 *{base_name} — ДЕБИТОРКА*\n"
    msg += f"Всего: `{total_debt:,.2f} ₽`\n"
    msg += f"Контрагентов: `{len(top_debtors)}`\n\n"
    msg += "Топ-5 должников:\n"
    for i, d in enumerate(top_debtors[:5], 1):
        msg += f"{i}. {d['name']}: `{d['amount']:,.2f} ₽`\n"

    return msg

# ========== ОТЧЁТ 3: АКТИВНОСТЬ ==========
def report_activity(base_id, base_name, days=14):
    """Активность клиентов"""
    contractor_names = get_contractor_names(base_id)
    sales = fetch_odata(base_id, 'AccumulationRegister_Продажи_RecordType')

    if not sales:
        return None

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    customer_data = defaultdict(lambda: {'order_dates': set()})

    for s in sales:
        period = s.get('Period', '')
        date_obj = datetime.fromisoformat(period.split('T')[0])

        if start_date <= date_obj <= end_date:
            ctg_key = s.get('Контрагент_Key', 'unknown')
            customer_data[ctg_key]['order_dates'].add(period[:10])

    critical = 0
    active = len(customer_data)

    msg = f"📈 *{base_name} — АКТИВНОСТЬ (за {days}д)*\n"
    msg += f"Активных клиентов: `{active}`\n"

    for ctg_key, data in list(customer_data.items())[:3]:
        name = contractor_names.get(ctg_key, 'Unknown')[:25]
        orders = len(data['order_dates'])
        msg += f"• {name}: `{orders}` заказов\n"

    return msg

# ========== ОТПРАВКА ==========
def send_all_reports(base_names='both'):
    """Отправляет все отчёты"""

    import urllib3
    urllib3.disable_warnings()

    if base_names in ['perfilev', 'both']:
        send_telegram("🔄 *Генерирую отчёты ИП Перфильев...*")

        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        # Отчёт 1: Продажи
        msg1 = report_sales(152757, 'ИП Перфильев', yesterday)
        if msg1:
            send_telegram(msg1)

        # Отчёт 2: Дебиторка
        msg2 = report_receivables(152757, 'ИП Перфильев')
        if msg2:
            send_telegram(msg2)

        # Отчёт 3: Активность
        msg3 = report_activity(152757, 'ИП Перфильев', days=14)
        if msg3:
            send_telegram(msg3)

    if base_names in ['gubarev', 'both']:
        send_telegram("🔄 *Генерирую отчёты ИП Губарев...*")

        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        # Отчёт 1: Продажи
        msg1 = report_sales(64904, 'ИП Губарев', yesterday)
        if msg1:
            send_telegram(msg1)

        # Отчёт 2: Дебиторка
        msg2 = report_receivables(64904, 'ИП Губарев')
        if msg2:
            send_telegram(msg2)

        # Отчёт 3: Активность
        msg3 = report_activity(64904, 'ИП Губарев', days=14)
        if msg3:
            send_telegram(msg3)

    send_telegram("✅ *Отчёты готовы!*")

if __name__ == "__main__":
    import sys

    base = sys.argv[1] if len(sys.argv) > 1 else 'both'

    print(f"Отправляю отчёты: {base}")
    send_all_reports(base)
    print("✅ Готово!")
