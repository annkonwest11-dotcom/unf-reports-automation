#!/usr/bin/env python3
"""Убрать строки-дубли в листах ДАННЫЕ_* (одно имя в A дважды, суммы пустые).

Откуда берутся: клиента заводят руками, когда синк уже добавил его сам. В
СВОДНОЙ это незаметно (там суммируется J, у дубля она пустая), а zp_files
отдавал клиента в файл дважды и завышал оплаты — у Алёны на 25 212 ₽ (09.10.2026).

Имя из A ЧИСТИТСЯ, строка не удаляется: диапазоны формул в листе абсолютные
($F$4:$F$502), и удаление строки внутри них молча ужимает их на единицу.
Пустая строка в середине листа безвредна — ниже таких десятки.

    scripts/drop_duplicate_rows.py            # показать найденные дубли
    scripts/drop_duplicate_rows.py --apply
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_START = 4


def find_duplicates(values):
    """[(строка, имя)] — повторные вхождения имени, у которых B:E пустые.

    values — строки листа целиком. Оставляем ПЕРВОЕ вхождение; повтор с
    суммами не трогаем вовсе: это не мусор, а расхождение, его решать человеку.
    """
    seen, dups, kept_with_data = {}, [], []
    for i, row in enumerate(values, start=1):
        if i < DATA_START or not row:
            continue
        name = str(row[0]).strip() if row else ""
        if not name:
            continue
        if name not in seen:
            seen[name] = i
            continue
        has_data = any(str(x).strip() for x in row[1:5])
        if has_data:
            kept_with_data.append((i, name, seen[name]))
        else:
            dups.append((i, name))
    return dups, kept_with_data


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import gspread
    from google.oauth2.service_account import Credentials
    from dotenv import load_dotenv
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base)
    load_dotenv(os.path.join(base, ".env"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    gc = gspread.authorize(Credentials.from_service_account_file("credentials.json", scopes=scopes))
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])

    from sync_odata import SHEET_BASES
    sheets = [cfg["sheet_name"] for cfg in SHEET_BASES.values()]
    total, backup = 0, {}
    for name in sheets:
        try:
            ws = sh.worksheet(name)
        except Exception:
            print(f"{name}: листа нет — пропускаю")
            continue
        values = ws.get("A1:E600", value_render_option="UNFORMATTED_VALUE")
        dups, with_data = find_duplicates(values)
        print(f"\n{name}: дублей без сумм {len(dups)}, дублей С суммами {len(with_data)}")
        for i, nm in dups:
            print(f"   стр.{i:4} {nm}")
        for i, nm, first in with_data:
            print(f"   ⚠️ стр.{i:4} {nm} — повтор строки {first}, НО с суммами: разберись руками")
        if dups and args.apply:
            backup[name] = {str(i): values[i - 1] for i, _ in dups}
            ws.batch_update([{"range": f"A{i}", "values": [[""]]} for i, _ in dups],
                            value_input_option="USER_ENTERED")
            total += len(dups)

    if args.apply and backup:
        import datetime
        path = os.path.join("docs", "бэкап_дубли_"
                            + datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".json")
        json.dump(backup, open(path, "w"), ensure_ascii=False)
        print(f"\nочищено имён: {total}; бэкап: {path}")
    elif not args.apply:
        print("\n(это план — ничего не записано; добавь --apply)")


if __name__ == "__main__":
    main()
