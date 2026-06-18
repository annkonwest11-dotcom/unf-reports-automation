#!/usr/bin/env python3
"""Синхронизирует НОВЫЕ_КЛИЕНТЫ из КПИ-таблицы в зарплатную таблицу.
Запускается автоматически каждое утро через launchd.
"""

import os
import sys
import logging
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

# ── Конфиг ──────────────────────────────────────────────────────────────────
MAIN_SS_ID = '1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo'
KPI_SS_ID  = '1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4'
CREDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'credentials.json')
SCOPES     = ['https://www.googleapis.com/auth/spreadsheets']

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync_novye.log')
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

MONTH_TO_KPI_SHEET = {
    'Январь':   'декабрь-январь',
    'Февраль':  'январь-февраль',
    'Март':     'февраль-март',
    'Апрель':   'март-апрель',
    'Май':      'апрель-май',
    'Июнь':     'май-июнь',
    'Июль':     'июнь-июль',
    'Август':   'июль-август',
    'Сентябрь': 'август-сентябрь',
    'Октябрь':  'сентябрь-октябрь',
    'Ноябрь':   'октябрь-ноябрь',
    'Декабрь':  'ноябрь-декабрь',
}

HEADER_TO_MANAGER = {
    'Менеджер Дарья':  'Дарья Вольнова',
    'Менеджер Алена':  'Алена Черкашина',
    'Менеджер Ксения': 'Ксения Наныкина',
    'Менеджер Лера':   'Валерия Папоян',
    'Валерия':         'Валерия Абрамова',
    'Анна':            'Анна Кононенко (РОП)',
    'Менеджер Лианна': 'Лианна Багдасарян',
}


def parse_amount(val):
    """'72 000,00' → 72000.0, возвращает None если не число."""
    s = str(val).strip().replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def sync():
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)

    main_ss = gc.open_by_key(MAIN_SS_ID)
    kpi_ss  = gc.open_by_key(KPI_SS_ID)

    # Читаем текущий месяц из НАСТРОЙКИ!B4  ("Июнь 2026" → "Июнь")
    settings = main_ss.worksheet('НАСТРОЙКИ')
    period_cell = settings.acell('B4').value or ''
    month = period_cell.strip().split()[0]

    kpi_sheet_name = MONTH_TO_KPI_SHEET.get(month)
    if not kpi_sheet_name:
        logging.error('Нет маппинга для месяца: %s', month)
        sys.exit(1)

    kpi_sheet = kpi_ss.worksheet(kpi_sheet_name)
    data = kpi_sheet.get_all_values()
    if not data:
        logging.error('Лист %s пустой', kpi_sheet_name)
        sys.exit(1)

    headers = data[0]

    # Колонки менеджеров (с индекса 5)
    manager_cols = []
    for i in range(5, len(headers)):
        h = headers[i].strip()
        if h in HEADER_TO_MANAGER:
            manager_cols.append((i, HEADER_TO_MANAGER[h]))

    today_str = date.today().isoformat()
    new_rows = []
    for r, row in enumerate(data[1:], start=2):
        restaurant = str(row[0]).strip() if row else ''
        if not restaurant:
            continue
        for col_idx, manager_name in manager_cols:
            val = row[col_idx] if col_idx < len(row) else ''
            amount = parse_amount(val)
            if amount is None:
                continue
            sheet_row = len(new_rows) + 4   # строка в листе НОВЫЕ_КЛИЕНТЫ
            vlookup = (
                f'=IFERROR(VLOOKUP(B{sheet_row},'
                f"ДАННЫЕ_Губарев!$A$4:$L$503,12,0)"
                f'+VLOOKUP(B{sheet_row},'
                f"ДАННЫЕ_Перфильев!$A$4:$L$503,12,0),0)"
            )
            new_rows.append([
                today_str,                       # A дата
                restaurant,                      # B ресторан
                manager_name,                    # C менеджер
                f'из КПИ {kpi_sheet_name}',      # D примечание
                kpi_sheet_name,                  # E период
                amount,                          # F сумма
                amount,                          # G для SUMIF
                '',                              # H формула (ставим отдельно)
            ])

    # Сохраняем формулы отдельно
    formulas = []
    for i, row in enumerate(new_rows):
        sr = i + 4
        formulas.append(
            f'=IFERROR(VLOOKUP(B{sr},ДАННЫЕ_Губарев!$A$4:$L$503,12,0)'
            f'+VLOOKUP(B{sr},ДАННЫЕ_Перфильев!$A$4:$L$503,12,0),0)'
        )

    nc = main_ss.worksheet('НОВЫЕ_КЛИЕНТЫ')
    # Очищаем строки 4-203
    nc.batch_clear(['A4:H203'])

    if new_rows:
        # Данные (A:G)
        data_only = [r[:7] for r in new_rows]
        nc.update(data_only, 'A4', value_input_option='USER_ENTERED')

        # Формулы в H
        h_vals = [[f] for f in formulas]
        nc.update(h_vals, 'H4', value_input_option='USER_ENTERED')

    # Считаем итоги по менеджерам для лога
    totals: dict[str, float] = {}
    for row in new_rows:
        name = row[2]
        totals[name] = totals.get(name, 0) + row[6]

    logging.info(
        'OK: %d строк из «%s». Итого: %s',
        len(new_rows),
        kpi_sheet_name,
        ', '.join(f'{n}={int(v):,}' for n, v in sorted(totals.items()))
    )
    print(f'✓ {len(new_rows)} строк из «{kpi_sheet_name}»')
    for name, v in sorted(totals.items()):
        print(f'  {name}: {int(v):,}')


if __name__ == '__main__':
    sync()
