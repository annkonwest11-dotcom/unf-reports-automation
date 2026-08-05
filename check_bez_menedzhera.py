#!/usr/bin/env python3
"""Кто в листах ДАННЫЕ остался без менеджера поиска (пустая колонка F).

Такие оплаты не попадают ни в чью базу. Гонять ПЕРЕД ЗАКРЫТИЕМ МЕСЯЦА:
    venv/bin/python check_bez_menedzhera.py

По решению Анны (05.08.2026) строки с нулевыми оплатами не заполняем — они
безвредны; важны только те, где J > 0. Заполняется ответственный в
СПРАВОЧНИК!B (ВПР-источник), а не в самом листе ДАННЫЕ — иначе синк затрёт.
Только отчёт, ничего не пишет.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sync_odata import _open_spreadsheet, DATA_START_ROW


def _num(x):
    """Оплаты в листе бывают текстом («11 205,00») — приводим к числу."""
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def main():
    ss = _open_spreadsheet()
    grand = 0.0
    grand_rows = 0
    for sh in ("ДАННЫЕ_Губарев", "ДАННЫЕ_Перфильев"):
        rows = ss.worksheet(sh).get("A1:L600")
        with_money, without_money = [], 0
        for i, r in enumerate(rows[DATA_START_ROW - 1:], start=DATA_START_ROW):
            name = (r[0] if len(r) > 0 else "").strip()
            if not name:
                continue
            if (r[5] if len(r) > 5 else "").strip():
                continue
            pay = _num(r[9] if len(r) > 9 else 0)  # J — скорр. оплаты
            if pay > 0:
                with_money.append((i, name, (r[6] if len(r) > 6 else "").strip(), pay))
            else:
                without_money += 1
        with_money.sort(key=lambda x: -x[3])
        total = sum(e[3] for e in with_money)
        grand += total
        grand_rows += len(with_money)
        print(f"\n=== {sh} ===")
        print(f"  без менеджера и С ОПЛАТАМИ: {len(with_money)} стр., {total:,.0f} ₽".replace(",", " "))
        print(f"  без менеджера, оплат нет:   {without_money} стр. (не трогаем)")
        for i, name, g, pay in with_money:
            print(f"    стр.{i:<4} {name[:45]:<45} {pay:>12,.0f}  сопр: {g}".replace(",", " "))

    print(f"\n>>> ИТОГО зависших оплат: {grand:,.0f} ₽ ({grand_rows} стр.)".replace(",", " "))
    if grand_rows == 0:
        print(">>> ✅ чисто — все оплаты привязаны к ответственному")


if __name__ == "__main__":
    main()
