#!/usr/bin/env python3
"""Перевод клиентов между менеджерами в листе СПРАВОЧНИК.

Зачем: при каждом кадровом изменении клиенты уехавшего менеджера переходят
другому. Руками это 100+ строк и гарантированные опечатки; номера строк
справочника плавают, поэтому строки ищутся ПО СОДЕРЖИМОМУ, а не по адресам.

Два режима (можно вместе):
  --poisk-from X --poisk-to Y   все строки, где «Менеджер поиска» = X → Y
  --sopr-rows 16,20,...         точечный список строк → «Менеджер сопровождения»
  --sopr-to Z                   кем заполнять сопровождение (в обоих режимах
                                пустое сопровождение у строк первого режима)

По умолчанию — план (ничего не пишет). Запись: --apply.
Перед записью складывает полный бэкап листа в docs/бэкап_справочник_<дата>.json.

Примеры:
  # Ксения ушла в SMM: её клиенты становятся прямыми, ведёт их Алёна
  scripts/reassign_clients.py --poisk-from "Ксения Наныкина" \
      --poisk-to "Прямой клиент" --sopr-to "Алена Черкашина"
  # отдельные клиенты Дарьи передаются на сопровождение Алёне
  scripts/reassign_clients.py --sopr-rows 16,20,68 --sopr-to "Алена Черкашина"
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SHEET = "СПРАВОЧНИК"
HEADER_ROW = 3          # строка заголовков, данные с 4-й
COL_NAME, COL_POISK, COL_SOPR, COL_STATUS = 0, 1, 2, 6


def plan_changes(values, poisk_from=None, poisk_to=None,
                 sopr_rows=(), sopr_to=None):
    """Что менять: [(строка, колонка 'B'|'C', было, стало, имя клиента)].

    values — список строк листа целиком (как get_all_values), с шапкой.
    Пустую ячейку сопровождения у переводимых клиентов тоже заполняем:
    клиент не должен остаться без ведущего.
    """
    def cell(row, idx):
        return (row[idx] if len(row) > idx else "").strip()

    out = []
    for i, row in enumerate(values, start=1):
        if i <= HEADER_ROW:
            continue
        name = cell(row, COL_NAME)
        if not name:
            continue
        poisk, sopr = cell(row, COL_POISK), cell(row, COL_SOPR)
        hit_poisk = poisk_from is not None and poisk == poisk_from
        if hit_poisk and poisk_to is not None and poisk != poisk_to:
            out.append((i, "B", poisk, poisk_to, name))
        want_sopr = sopr_to is not None and (hit_poisk or i in set(sopr_rows))
        if want_sopr and sopr != sopr_to:
            out.append((i, "C", sopr, sopr_to, name))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--poisk-from")
    ap.add_argument("--poisk-to")
    ap.add_argument("--sopr-rows", default="")
    ap.add_argument("--sopr-to")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not any([args.poisk_from, args.sopr_rows]):
        ap.error("нечего делать: задай --poisk-from и/или --sopr-rows")

    rows = [int(x) for x in args.sopr_rows.replace(" ", "").split(",") if x]

    import gspread
    from google.oauth2.service_account import Credentials
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base)
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    gc = gspread.authorize(Credentials.from_service_account_file("credentials.json", scopes=scopes))
    from dotenv import load_dotenv
    load_dotenv()
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    ws = sh.worksheet(SHEET)
    values = ws.get_all_values()

    changes = plan_changes(values, args.poisk_from, args.poisk_to, rows, args.sopr_to)
    if not changes:
        print("Менять нечего — всё уже стоит как надо.")
        return

    print(f"Лист {SHEET}: {len(values)} строк, правок {len(changes)}\n")
    for i, col, was, now, name in changes:
        print(f"  {col}{i:<4} {name[:46]:48} {was or '—':20} → {now}")

    missing = [r for r in rows if r > len(values) or not values[r - 1][COL_NAME].strip()]
    if missing:
        print(f"\n⚠️ строки без контрагента: {missing}")

    if not args.apply:
        print("\n(это план — ничего не записано; добавь --apply)")
        return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    # секунды в имени: два запуска подряд не должны затирать бэкап друг друга
    backup = os.path.join("docs", f"бэкап_справочник_{stamp}.json")
    os.makedirs("docs", exist_ok=True)
    json.dump({"sheet": SHEET, "values": values, "changes": changes},
              open(backup, "w"), ensure_ascii=False)
    print(f"\nбэкап: {backup}")

    ws.batch_update([{"range": f"{col}{i}", "values": [[now]]}
                     for i, col, _was, now, _name in changes],
                    value_input_option="USER_ENTERED")
    print(f"записано ячеек: {len(changes)}")


if __name__ == "__main__":
    main()
