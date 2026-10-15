# -*- coding: utf-8 -*-
"""Разведка отчёта по продажам: что 1С думает про месяц, без записи в таблицу.

★12.10.2026 весь расчёт переехал в боевой `sales_report.py` (ТЗ — лист «ТЗ — отчёт
по продажам»), и здесь остался только показ: правила и склейка карточек должны
жить в одном месте, иначе разведка и боевой прогон начнут расходиться.

Запуск:  python3 scripts/sales_report_probe.py [ГГГГ-ММ]
Ничего никуда не пишет. Нужен прогон с записью в копию листа — `sales_report.py`.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sales_report import (apply_beby, classify, load_beby, load_history,
                          one_order_candidates, sheet_title)

if __name__ == "__main__":
    ym = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m")
    hist, canon = load_history()
    rows = apply_beby(classify(hist, ym), load_beby(ym, canon))
    print(f"\n{ym} → лист «{sheet_title(ym)}»: новых по 1С "
          f"{sum(1 for r in rows if r['kind'] == 'новый')}, кандидатов на возврат "
          f"{sum(1 for r in rows if r['kind'] == 'кандидат')}\n")
    for r in rows:
        why = (f"молчал {r['gap']} дн." + (f" при ритме {r['rhythm']:g}" if r["rhythm"] else "")
               if r["kind"] == "кандидат" else "")
        tail = f"  (хвост след. месяца {r['tail_next_month']:,.0f})" if r["tail_next_month"] else ""
        cut = (f"  ★беби −{r['beby_cut']:,.0f} (было {r['amount_gross']:,.0f}, "
               f"салатов {r['beby_kg']:g} кг)" if r["beby_cut"] else "")
        print(f"{r['kind']:<9}{r['event']:%d.%m}  {r['client'][:44]:<44}"
              f"{r['amount']:>11,.0f}  по {r['window_end']:%d.%m}  {why}{tail}{cut}")
    ones = one_order_candidates(rows)
    print(f"\nИТОГО {sum(r['amount'] for r in rows):,.0f}"
          f"   (вычтено за салаты {sum(r['beby_cut'] for r in rows):,.0f})")
    print(f"взяли один раз за месяц — {len(ones)}: "
          + ", ".join(r["client"][:28] for r in ones))
