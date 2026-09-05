# -*- coding: utf-8 -*-
"""Лист «добивка» — кого сегодня добивать по заказам, собирается из 1С.

Анна вела этот лист руками в таблице «Потери/обрезания/перекуп»; сверка 04.09.2026
показала, откуда в нём брались ошибки, и здесь они закрыты:

  • ТРИ БАЗЫ. Лист собирался по двум ИП, а часть клиентов перевели на третье
    (Володихина, 184621) — девять человек числились молчащими, хотя заказывали
    там же в тот же день (Дабл Спейс «18 дней тишины» заказал накануне).
  • СКЛЕЙКА ДВОЙНИКОВ. Клиента, переведённого между базами, в 1С заводят заново;
    по одной карточке он «отвалился», по второй активен. Так в листе висели
    ПУАССОН («отвалился, 24 дня» — заказ в тот же день) и ВОДНЫЙ (11 дней при
    заказе сегодня). Берём общую склейку `sync_rhythm.merge_cards`.
  • ДНИ СЧИТАЕМ ОТ ПОСЛЕДНЕГО ЗАКАЗА ПО ВСЕМ КАРТОЧКАМ И БАЗАМ, а не по той,
    которую видно первой.

Комментарий и «обычная периодичность» считаются по личному ритму клиента —
медиане интервалов между его заказами, той же, что в отчёте РИТМ_ЗАКАЗОВ.

Запуск:  venv/bin/python scripts/dobivka.py           # показать, что получится
         venv/bin/python scripts/dobivka.py --apply   # записать лист
"""
import argparse
import datetime
import json
import logging
import os
import sys

import gspread

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sync_rhythm as sr

logger = logging.getLogger(__name__)

# таблица «Потери / обрезания / перекуп» — там же, где Анна вела лист руками
SPREADSHEET = os.environ.get("DOBIVKA_SSID", "1MTu7whYO05u7PmBdYGjzmgJ62CkpdX7aDW1mGWRL1SM")
SHEET = "добивка"
HEADER = ["Клиент", "Кол-во дней", "Комменатрий", "Менеджер", "Обычно раз в, дн.",
          "Заказов за период", "Последний заказ", "База"]
FEW_ORDERS = 3          # столько заказов и меньше — «мало истории, 1 поставка»


def comment(r):
    """Человеческая подпись — что делать с клиентом.

    Формулировки взяты из листа Анны: «спросить заказ», «1 поставка»,
    «отвалился», «обычно N — наладить отношения», «на грани отваливания».
    """
    gap = r["median_gap_days"]
    ratio = r["ratio"] or 0
    if r["status"] == "ОТВАЛИВАЕТСЯ":
        return f"отвалился — молчит {r['silent']} дн."
    if r["orders"] <= FEW_ORDERS or not gap:
        return f"мало истории ({r['orders']} пост.) — спросить заказ"
    if ratio >= 2:
        return f"обычно раз в {gap:.0f} дн. — наладить отношения"
    if ratio >= sr.OVERDUE_RATIO:
        return f"на грани отваливания, обычно раз в {gap:.0f} дн."
    return "спросить заказ"


def build(today=None):
    """Строки листа: только те, кому пора или уже просрочено (+ отваливающиеся)."""
    today = today or datetime.date.today()
    orders, base_of = sr.fetch_orders(today)
    orders, base_of, cards = sr.merge_cards(orders, base_of)
    rows = sr.compute(orders, base_of, today)
    gc = gspread.service_account(filename=sr.CREDENTIALS_PATH)
    idx = sr.load_directory(gc)

    out = []
    for r in rows:
        if r["status"] not in ("ПРОСРОЧЕНО", "пора заказать", "ОТВАЛИВАЕТСЯ", "мало данных"):
            continue
        rec = sr.lookup(r["client"], idx)
        if rec and rec[2] in sr.SKIP_TYPES:        # конкуренты и закупки не добиваем
            continue
        search, support = (rec[0], rec[1]) if rec else ("", "")
        manager = sr.FIRM_GROUP if (rec and rec[2] == sr.FIRM_TYPE) else sr.owner_of(search, support)
        gap = r["median_gap_days"]
        out.append([sr.task_name(r["client"]), r["silent"], comment(r), manager,
                    round(gap) if gap else "", r["orders"],
                    datetime.date.fromisoformat(r["last"]).strftime("%d.%m.%Y"), r["base"]])
    # самые запущенные сверху: по «во сколько раз просрочено», потом по дням
    order = {"ОТВАЛИВАЕТСЯ": 0, "ПРОСРОЧЕНО": 1, "пора заказать": 2, "мало данных": 3}
    by_status = {sr.task_name(r["client"]): order.get(r["status"], 9) for r in rows}
    out.sort(key=lambda x: (by_status.get(x[0], 9), -x[1]))
    return out, cards


def write(rows, today=None):
    """Перезаписывает лист. Прежнее содержимое — в docs/ (бэкап на всякий случай)."""
    today = today or datetime.date.today()
    gc = gspread.service_account(filename=sr.CREDENTIALS_PATH)
    ws = gc.open_by_key(SPREADSHEET).worksheet(SHEET)
    backup = ws.get_all_values()
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "docs", f"добивка_бэкап_{today:%Y-%m-%d}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)
    ws.batch_clear([f"A1:H{max(len(backup), len(rows) + 3) + 5}"])
    ws.update([[f"ДОБИВКА — собрано из 1С {today:%d.%m.%Y}, три базы, "
                f"карточки-двойники склеены"]], "A1")
    ws.update([HEADER], "A2")
    if rows:
        ws.update(rows, f"A3:H{len(rows) + 2}", value_input_option="USER_ENTERED")
    return len(rows), path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="записать лист «добивка»")
    a = p.parse_args()
    rows, cards = build()
    print(f"\nстрок: {len(rows)}; склеено карточек-двойников: {len(cards)}\n")
    print(f"{'клиент':<44}{'дн.':>4} {'менеджер':<22} комментарий")
    for r in rows:
        print(f"{r[0][:43]:<44}{r[1]:>4} {r[3][:21]:<22} {r[2]}")
    if a.apply:
        n, path = write(rows)
        print(f"\n✅ записано строк: {n}; бэкап прежнего листа: {path}")
    else:
        print("\n(dry-run: лист не тронут — запусти с --apply)")
