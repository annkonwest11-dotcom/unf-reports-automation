#!/usr/bin/env python3
# Разовая проверка: по новым клиентам Ксении из KPI (лист «май-июнь»)
# проверяем, что в СПРАВОЧНИК зарплатной таблицы Ксения стоит ответственной.
import os, re, gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)

KPI_ID = "1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4"
ZP_ID = "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"

def num(s):
    if s is None: return 0.0
    s = str(s).replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if s in ("", "-"): return 0.0
    try: return float(s)
    except: return 0.0

def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()

# --- KPI: лист «май-июнь», колонка Ксении = H (F Дарья, G Алена, H Ксения) ---
kpi = gc.open_by_key(KPI_ID).worksheet("май-июнь")
rows = kpi.get_all_values()
hdr = rows[0]
print("KPI заголовки:", hdr)
KSENIA_COL = 7  # 0-based H
ksenia_clients = []
for r in rows[1:]:
    if len(r) <= KSENIA_COL: continue
    name = (r[0] or "").strip()
    if not name: continue
    val = num(r[KSENIA_COL])
    if val > 0:
        ur = (r[1].strip() if len(r) > 1 else "")   # B юр.лицо
        ksenia_clients.append((name, ur, val))

print(f"\nНовых клиентов Ксении в KPI (сумма>0): {len(ksenia_clients)}")

# --- СПРАВОЧНИК: A контрагент, B менеджер поиска, C сопровождение ---
sp = gc.open_by_key(ZP_ID).worksheet("СПРАВОЧНИК")
sp_rows = sp.get_all_values()
# индекс по нормализованному имени -> (строка, поиск, сопровожд)
idx = {}
for i, r in enumerate(sp_rows[3:], start=4):
    a = r[0] if len(r) > 0 else ""
    b = r[1] if len(r) > 1 else ""
    c = r[2] if len(r) > 2 else ""
    if a.strip():
        idx.setdefault(norm(a), (i, a.strip(), b.strip(), c.strip()))

def is_ksenia(x):
    return "ксения" in norm(x) or "наныкин" in norm(x)

STOP = {"ооо","оо","ип","зао","бар","кафе","ресторан","за","наличку","групп","group","the"}
def tokens(s):
    return {t for t in re.split(r"[^\wа-яё]+", norm(s)) if len(t) >= 3 and t not in STOP}

# токен-индекс СПРАВОЧНИК для поиска кандидатов
sp_index = []
for i, r in enumerate(sp_rows[3:], start=4):
    a = r[0] if len(r) > 0 else ""
    b = r[1] if len(r) > 1 else ""
    c = r[2] if len(r) > 2 else ""
    if a.strip():
        sp_index.append((i, a.strip(), b.strip(), c.strip(), tokens(a)))

def candidates(name, ur):
    want = tokens(name) | tokens(ur)
    res = []
    for i, a, b, c, tk in sp_index:
        inter = want & tk
        if inter:
            res.append((len(inter), i, a, b, c))
    res.sort(reverse=True)
    return res[:3]

print("\n{:<45} {:>10}  {}".format("Клиент (KPI)", "Сумма", "Статус в СПРАВОЧНИК"))
print("-"*100)
ok, notfound, wrong = [], [], []
for name, ur, val in ksenia_clients:
    hit = idx.get(norm(name))
    if not hit and ur:
        hit = idx.get(norm(ur))
    if not hit:
        notfound.append((name, ur, val))
        print("{:<45} {:>10.0f}  ❓ НЕ НАЙДЕН в СПРАВОЧНИК".format(name[:44], val))
        continue
    row, a, b, c = hit
    if is_ksenia(b) or is_ksenia(c):
        ok.append((name, val))
        who = []
        if is_ksenia(b): who.append("поиск")
        if is_ksenia(c): who.append("сопров.")
        print("{:<45} {:>10.0f}  ✅ Ксения ({}) стр.{}".format(name[:44], val, "+".join(who), row))
    else:
        wrong.append((name, val, b, c, row))
        print("{:<45} {:>10.0f}  ⚠️ поиск='{}' сопр='{}' стр.{}".format(name[:44], val, b, c, row))

print("\n" + "="*60)
print(f"Итого клиентов Ксении в KPI: {len(ksenia_clients)}")
print(f"  ✅ Ксения ответственная:   {len(ok)}")
print(f"  ⚠️ другой ответственный:   {len(wrong)}")
print(f"  ❓ нет в СПРАВОЧНИК:        {len(notfound)}")
if wrong:
    print("\nТРЕБУЮТ ВНИМАНИЯ (не Ксения):")
    for name, val, b, c, row in wrong:
        print(f"  стр.{row}: {name} | поиск='{b}' сопр='{c}' | {val:.0f}")
if notfound:
    print("\nНЕ НАЙДЕНЫ прямым совпадением — кандидаты по токенам:")
    for name, ur, val in notfound:
        print(f"\n  ▸ {name} (юр:{ur}) | {val:.0f}")
        cands = candidates(name, ur)
        if not cands:
            print("      — вообще нет похожих строк в СПРАВОЧНИК")
        for score, i, a, b, c in cands:
            mark = "✅Ксения" if (is_ksenia(b) or is_ksenia(c)) else "⚠️другой"
            print(f"      стр.{i} [{mark}] A='{a}' поиск='{b}' сопр='{c}'")
