"""14 карточек «НЕ В ЛИСТЕ» на 14.08: суммы, есть ли клиент в СПРАВОЧНИКЕ,
в листах ДАННЫЕ и в отчёте по новым продажам (KPI-таблица)."""
import sys
sys.path.insert(0, "/Users/anna/claude-test")
import gspread
import sync_odata as SO
import sync_novye as SN
from sync_rhythm import CREDENTIALS_PATH, SALARY_SPREADSHEET

gc = gspread.service_account(filename=CREDENTIALS_PATH)
ss = gc.open_by_key(SALARY_SPREADSHEET)

# 1) что «не в листе» прямо сейчас
sheets = {"gubarev": "ДАННЫЕ_Губарев", "perfilev": "ДАННЫЕ_Перфильев"}
missing = {}
for key, sheet in sheets.items():
    ws = ss.worksheet(sheet)
    col_a = ws.col_values(1)
    bal = SO.fetch_base_balances(SO.BASES[key])
    _upd, new_clients = SO.plan_updates(col_a, bal)
    missing[key] = new_clients

# 2) справочник и данные — для проверки «есть ли клиент вообще»
spr_vals = ss.worksheet("СПРАВОЧНИК").get("A4:E1000")
spr_cands = [((4 + i, r), (r[0] if r else "")) for i, r in enumerate(spr_vals)
             if r and r[0].strip()]
data_names = []
for sh in sheets.values():
    data_names += [(sh, v) for v in ss.worksheet(sh).col_values(1)[3:] if v.strip()]

# 3) KPI-отчёт по новым продажам
kss = gc.open_by_key(SN.KPI_SS_ID)
month = (ss.worksheet("НАСТРОЙКИ").acell("B4").value or "").strip().split()[0]
kpi_name = SN.MONTH_TO_KPI_SHEET.get(month)
kpi_ws = next(w for w in kss.worksheets() if w.title.strip() == kpi_name.strip())
kdata = kpi_ws.get_all_values()
kheaders = kdata[0]
mgr_cols = {i: SN.KPI_MANAGERS[kheaders[i].strip().lower()]
            for i in range(len(kheaders)) if kheaders[i].strip().lower() in SN.KPI_MANAGERS}
kpi_cands = []
for row in kdata[1:]:
    rest = row[0].strip() if row else ""
    if not rest:
        continue
    mgr = None
    for ci, mt in mgr_cols.items():
        if ci < len(row) and row[ci].strip():
            mgr = mt
            break
    ur = row[1] if len(row) > 1 else ""
    klass = (row[3] if len(row) > 3 else "").strip()
    kpi_cands.append(((mgr, klass, ur), f"{rest} {ur}"))

print(f"KPI-лист: {kpi_name}, строк {len(kpi_cands)}, колонки менеджеров: "
      f"{[kheaders[i] for i in mgr_cols]}\n")

for key, items in missing.items():
    print(f"########## {sheets[key]} — не в листе: {len(items)}")
    for name, vals in items:
        q = SN._toks(name)
        sp_p, sp_n, sp_s = SN._best_match(q, spr_cands)
        dn_p, dn_n, dn_s = SN._best_match(q, data_names)
        kp_p, kp_n, kp_s = SN._best_match(q, kpi_cands)
        oplaty = vals[2]
        print(f"\n— {name}")
        print(f"    долг нач {vals[0]:>10} · отгрузка {vals[1]:>10} · ОПЛАТЫ {oplaty:>10}"
              f" · долг кон {vals[3]:>10}")
        print(f"    СПРАВОЧНИК: {sp_n or '—'}"
              + (f"  [поиск={sp_p[1][1] if len(sp_p[1])>1 else ''!r}"
                 f" сопр={sp_p[1][2] if len(sp_p[1])>2 else ''!r}]" if sp_p else ""))
        print(f"    ДАННЫЕ:     {dn_n or '—'}" + (f"  ({dn_p})" if dn_p else ""))
        print(f"    KPI новые:  {kp_n or '—'}" + (f"  менеджер={kp_p[0]} класс={kp_p[1]!r}"
                                                  if kp_p else ""))
