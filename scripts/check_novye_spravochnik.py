#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОВЕРКА привязки новых клиентов к СПРАВОЧНИКУ (read-only).

Для каждого клиента на листе НОВЫЕ_КЛИЕНТЫ (колонка C = менеджер поиска)
проверяет, что тот же менеджер стоит ответственным (колонка B) в СПРАВОЧНИКЕ.
Ловит новых клиентов, у которых в СПРАВОЧНИКЕ поиск = «Прямой клиент» или пусто —
из-за этого их оплаты не попадают в бонус менеджера «% от оплат».

Имена на НОВЫЕ_КЛИЕНТЫ короткие («Тануки»), в СПРАВОЧНИКЕ — полные «(ООО …)»,
поэтому матчим по токенам (все значимые слова короткого имени есть в полном).

Запуск:
  python scripts/check_novye_spravochnik.py                 # все менеджеры
  python scripts/check_novye_spravochnik.py "Дарья Вольнова" "Ксения Наныкина"

Требует: credentials.json в корне репо, SPREADSHEET_ID в .env.
Чинить найденное — в СПРАВОЧНИКЕ (колонка B), т.к. F в ДАННЫХ = ВПР из СПРАВОЧНИКА.
"""
import os
import re
import sys

import gspread
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID") or "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"
STOP = {"ооо", "ип", "бар", "кафе", "ресторан", "the", "и", "в", "на", "by", "ко",
        "group", "«", "»", "steak", "it", "easy", "holl", "hall"}


def norm(s):
    return re.sub(r"\s+", " ", (str(s) or "").replace("\xa0", " ")).strip().lower()


def toks(s):
    s = re.sub(r"[()«».,/]", " ", norm(s))
    return [t for t in s.split() if len(t) >= 3 and t not in STOP]


def main(managers):
    if not os.path.exists("credentials.json"):
        sys.exit("Нет credentials.json в корне репо.")
    gc = gspread.service_account(filename="credentials.json")
    sh = gc.open_by_key(SPREADSHEET_ID)

    nk = sh.worksheet("НОВЫЕ_КЛИЕНТЫ").get_all_values()
    new_clients = [(i, r[1].strip(), r[2].strip()) for i, r in enumerate(nk[3:], start=4)
                   if len(r) >= 3 and r[1].strip()]

    spr = sh.worksheet("СПРАВОЧНИК").get_all_values()
    spr_rows = [(i, r[0].strip(), r[1].strip() if len(r) > 1 else "", norm(r[0]))
                for i, r in enumerate(spr[3:], start=4) if r and r[0].strip()]

    def find_spr(short):
        st = toks(short)
        return [(row, name, p) for row, name, p, nn in spr_rows if st and all(t in nn for t in st)]

    if not managers:
        managers = sorted({c[2] for c in new_clients if c[2]})

    total_problems = 0
    for target in managers:
        subset = [c for c in new_clients if norm(c[2]) == norm(target)]
        print("═" * 72)
        print(f"  {target} — новых клиентов: {len(subset)}")
        print("═" * 72)
        bad = 0
        for row, name, _ in subset:
            hits = find_spr(name)
            ok = [h for h in hits if norm(h[2]) == norm(target)]
            if ok:
                continue
            bad += 1
            if not hits:
                print(f"  ❌ {name[:36]:38} — не найден в СПРАВОЧНИКЕ (проверить написание/юрлицо)")
            else:
                print(f"  ⚠️  {name[:36]:38} — ответственный (B) не {target}:")
                for h in hits:
                    print(f"        СПР стр{h[0]}: {h[1][:44]!r}  B={h[2]!r}")
        print(f"  → сошлось {len(subset) - bad} из {len(subset)}, требует внимания: {bad}\n")
        total_problems += bad

    print(f"ИТОГО требует внимания: {total_problems}")
    print("(Проверка завершена. В таблицы ничего не записано.)")


if __name__ == "__main__":
    main(sys.argv[1:])
