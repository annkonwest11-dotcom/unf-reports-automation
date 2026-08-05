#!/usr/bin/env python3
"""Сверка справочника: какие контрагенты из листов ДАННЫЕ и из новых продаж (KPI)
ОТСУТСТВУЮТ в СПРАВОЧНИКЕ (значит не привязаны к менеджеру, VLOOKUP пустой).

Только отчёт, ничего не пишет. Запуск:  venv/bin/python check_spravochnik.py
Заведение найденных пропусков делается отдельно (руками/скриптом), т.к. по клиентам
из ДАННЫЕ ответственного знает только Анна. sync_odata в справочник НЕ пишет —
автозаводятся лишь клиенты из новых продаж KPI через sync_novye.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sync_odata import norm_name, SKIP_CONTRACTORS, _open_spreadsheet, DATA_START_ROW
from sync_novye import sync_novye

ss = _open_spreadsheet()

# ── СПРАВОЧНИК: множество норм-имён (колонка A с 4-й строки) ──
spr = ss.worksheet("СПРАВОЧНИК")
spr_names = [v for v in spr.col_values(1)[3:] if v and v.strip()]
spr_set = {norm_name(v) for v in spr_names}
print(f"СПРАВОЧНИК: {len(spr_names)} строк ({len(spr_set)} уникальных норм-имён)\n")

skip_norm = {norm_name(s) for s in SKIP_CONTRACTORS}

# ── ДАННЫЕ: контрагенты не в СПРАВОЧНИКЕ (точный norm-матч) ──
print("=" * 60)
print("ЛИСТЫ ДАННЫЕ → контрагенты, которых НЕТ в СПРАВОЧНИКЕ")
print("=" * 60)
total_missing = {}
for sh in ("ДАННЫЕ_Губарев", "ДАННЫЕ_Перфильев"):
    ws = ss.worksheet(sh)
    names = [v for v in ws.col_values(1)[DATA_START_ROW - 1:] if v and v.strip()]
    missing = []
    seen = set()
    for n in names:
        nn = norm_name(n)
        if not nn or nn in skip_norm:
            continue
        if nn not in spr_set and nn not in seen:
            seen.add(nn)
            missing.append(n)
    print(f"\n{sh}: {len(names)} контрагентов, НЕ в справочнике — {len(missing)}")
    for n in missing:
        print(f"   • {n}")
    for n in missing:
        total_missing[norm_name(n)] = n

print(f"\n>>> ИТОГО уникальных контрагентов из ДАННЫЕ вне справочника: {len(total_missing)}")

# ── НОВЫЕ ПРОДАЖИ (KPI): что sync_novye добавил бы сейчас ──
# NB: матч нечёткий (_best_match по токенам) — короткие имена типа «нал» дают
# ложные «добавить» (плодят дубли), а совпадение по одному токену («маргарита»)
# может ложно счесть нового клиента существующим. Проверять глазами.
print("\n" + "=" * 60)
print("НОВЫЕ ПРОДАЖИ (KPI) → что sync_novye добавил бы в СПРАВОЧНИК")
print("=" * 60)
rep = sync_novye(dry_run=True)
print(f"\nKPI-лист: {rep['kpi_sheet']}, строк новых продаж: {rep['novye_rows']}")
print(f"Надо ДОБАВИТЬ в справочник (added): {len(rep['added'])}")
for name, B, C in rep["added"]:
    tag = "  ⚠ НЕ найден в ДАННЫЕ" if name in rep["no_data"] else ""
    print(f"   • {name[:45]:<45} поиск={B!r} сопр={C!r}{tag}")
print(f"Расхождения ответственных (discrepancies): {len(rep['discrepancies'])}")
for cl, kpi, cur in rep["discrepancies"]:
    print(f"   • {cl[:30]:<30} KPI={kpi} | СПР {cur}")
