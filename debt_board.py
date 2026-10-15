# -*- coding: utf-8 -*-
"""Борд дебиторки: данные 1С → готовая HTML-страница для артефакта.

Запуск:  python3 debt_board.py            (срез на сегодня)
         python3 debt_board.py 2026-10-01 (срез на дату)
Печатает путь к собранной странице — её нужно залить в артефакт
«Дебиторка GREENCH» https://claude.ai/artifact/U89PuMzXTwkAm6pRg6e5Uy
ПО ТОМУ ЖЕ URL (иначе появится второй борд со старой ссылкой у Анны).

Чем отличается от debt_report.py: тот делает PDF и XLSX на Desktop для печати,
здесь — живая страница с фильтрами. Методика расчёта общая (fetch_base).
"""
import datetime
import json
import os
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, "/Users/anna/GREENCH/01-деньги/зарплата")
os.chdir("/Users/anna/GREENCH/01-деньги/зарплата")

from sync_debitorka import fetch_base            # noqa: E402

from sync_odata import BASES                      # noqa: E402
from debt_payments import by_name, бренд           # noqa: E402

ОКНО_ОПЛАТ = 30          # дней, за которые считаем «клиент платил»

ПОРЯДОК = ["gubarev", "perfilev", "volodihina"]   # индекс ИП в странице
ИМЕНА = {"gubarev": "ИП Губарев И. С.",
         "perfilev": "ИП Перфильев В. К.",
         "volodihina": "ИП Володихина В. В."}
ШАБЛОН = "/Users/anna/GREENCH/01-деньги/зарплата/templates/debt_board.html"

СРЕЗ = (datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1
        else datetime.date.today())

МОМЕНТ = datetime.datetime.combine(СРЕЗ, datetime.time.min)
КОНЕЦ_ДНЯ = datetime.datetime.combine(СРЕЗ, datetime.time.max)
НАЧАЛО_ОКНА = МОМЕНТ - datetime.timedelta(days=ОКНО_ОПЛАТ)

строки = []
оплачено_окно = оплат_окно = 0.0
висит_всего = снимет_разноска = 0.0
висит_клиентов = висит_должников = 0
база_данных = {}
for ключ in ПОРЯДОК:
    cfg = BASES[ключ]
    записи = fetch_base(cfg["id"], СРЕЗ)
    # оплаты нужны, чтобы отличить «не платит» от «заплатил, но не разнесли»
    оплаты, висят = by_name(cfg["id"], СРЕЗ)
    база_данных[ключ] = (записи, оплаты, висят)

# Клиента переводят на другое юрлицо и заводят вторую карточку: накладные идут на
# новую, деньги продолжают приходить на старую. По своей карточке «нет оплат», хотя
# платит он исправно — поэтому ищем ещё и по бренду (ТУРАНДОТ, САХАЛИН, А 81…).
оплаты_бренда = {}
for ключ, (_, оплаты, _) in база_данных.items():
    for имя, список in оплаты.items():
        for дата, сумма, куда in список:
            оплаты_бренда.setdefault(бренд(имя), []).append(
                (дата, сумма, куда, имя, ИМЕНА[ключ]))
for v in оплаты_бренда.values():
    v.sort(key=lambda x: x[0])

for ключ in ПОРЯДОК:
    cfg = BASES[ключ]
    записи, оплаты, висят = база_данных[ключ]
    долг = sum(r["total"] for r in записи)
    просроч = sum(r["overdue"] for r in записи)
    for список in оплаты.values():
        for дата, сумма, _ in список:
            if НАЧАЛО_ОКНА <= дата <= КОНЕЦ_ДНЯ:
                оплачено_окно += сумма
                оплат_окно += 1
    долг_по_имени = {r["name"]: r["total"] for r in записи}
    for имя, (своб, перепл) in висят.items():
        висит_всего += своб + перепл
        висит_клиентов += 1
        if долг_по_имени.get(имя):
            висит_должников += 1
            снимет_разноска += min(своб + перепл, долг_по_имени[имя])
    print("база %-12s (%s): должников %3d | долг %12.0f | просрочка %12.0f"
          % (ключ, cfg["id"], len(записи), долг, просроч))
    for r in записи:
        история = [о for о in оплаты.get(r["name"], []) if о[0] <= КОНЕЦ_ДНЯ]
        карточка = ""
        if not история:
            чужие = [о for о in оплаты_бренда.get(бренд(r["name"]), [])
                     if о[3] != r["name"] and о[0] <= КОНЕЦ_ДНЯ]
            if чужие:
                история = [(д, с, к) for д, с, к, _, _ in чужие]
                карточка = f"{чужие[-1][3]} ({чужие[-1][4].replace('ИП ', '')})"
        посл = история[-1] if история else None
        своб, перепл = висят.get(r["name"], (0.0, 0.0))
        строки.append({"name": r["name"], "ip": ПОРЯДОК.index(ключ),
                       "g": бренд(r["name"]),
                       "total": round(r["total"]), "overdue": round(r["overdue"]),
                       "days": r["days"],
                       "buckets": [round(b) for b in r["buckets"]],
                       "pd": f"{посл[0]:%d.%m}" if посл else "",
                       "ps": round(посл[1]) if посл else 0,
                       "pdays": (СРЕЗ - посл[0].date()).days if посл else None,
                       "p30": round(sum(о[1] for о in история if о[0] >= НАЧАЛО_ОКНА)),
                       "pc": карточка,
                       "un": round(своб + перепл)})

if not строки:
    sys.exit("1С не отдала ни одной записи — страницу НЕ обновляем, "
             "иначе Анна увидит пустую дебиторку вместо аварии")

строки.sort(key=lambda r: (-r["overdue"], -r["total"]))

оплаты_итог = {"paid": round(оплачено_окно), "cnt": int(оплат_окно), "days": ОКНО_ОПЛАТ,
               "un": round(висит_всего), "unClients": висит_клиентов,
               "unDebtors": висит_должников, "unFix": round(снимет_разноска)}

шаблон = open(ШАБЛОН, encoding="utf-8").read()
страница = (шаблон
            .replace("/*__ДАННЫЕ__*/", json.dumps(строки, ensure_ascii=False))
            .replace("/*__ОПЛАТЫ__*/", json.dumps(оплаты_итог, ensure_ascii=False))
            .replace("/*__СРЕЗ__*/", СРЕЗ.isoformat()))
путь = os.path.join(tempfile.gettempdir(), f"debt_board_{СРЕЗ:%Y-%m-%d}.html")
open(путь, "w", encoding="utf-8").write(страница)

двойные = defaultdict(set)
for s in строки:
    двойные[s["g"]].add(s["ip"])
print("\nсрез %s | должников %d | долг %d ₽ | просрочено %d ₽ | старше 60 дн. %d ₽"
      % (СРЕЗ, len(строки), sum(s["total"] for s in строки),
         sum(s["overdue"] for s in строки), sum(s["buckets"][4] for s in строки)))
print("клиентов сразу у нескольких ИП: %d"
      % sum(1 for ип in двойные.values() if len(ип) > 1))
print("оплачено за %d дн.: %d ₽ (%d оплат) | деньги без разноски: %d ₽ у %d клиентов,"
      " из них должников %d — разноска снимет %d ₽"
      % (ОКНО_ОПЛАТ, оплачено_окно, оплат_окно, висит_всего, висит_клиентов,
         висит_должников, снимет_разноска))
print("СТРАНИЦА:", путь)
print("залить в артефакт по тому же URL: "
      "https://claude.ai/artifact/U89PuMzXTwkAm6pRg6e5Uy")
