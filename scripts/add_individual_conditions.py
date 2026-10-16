#!/usr/bin/env python3
"""Блок «индивидуальные условия» в СВОДНОЙ + личный план в НАСТРОЙКАХ.

Условия Анны (файл «Индивидуальные_условия_менеджера_GREENCH.pdf»): менеджер на
адаптации считается по общей сетке от 210 000, плюс отдельный бонус от ЛИЧНОГО
плана 250 000 за оборот + нормы звонков и дегустаций. Ставку «% от оплат» на
ступени 115% ему поднимают с 3% до 4% — остальные ступени как у всех.

Сам бонус считает individual_kpi.py и пишет в строку «Индивидуальный бонус».
Здесь только заводятся строки — один раз.

    scripts/add_individual_conditions.py --who "Виолетта Караханова"          # план
    scripts/add_individual_conditions.py --who "Виолетта Караханова" --apply
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PLAN_PERSONAL = 250_000
RATE_115 = "0,04"                       # у всех 3%, здесь 4%
HEAD = "ИНДИВИДУАЛЬНЫЕ УСЛОВИЯ (адаптация 01.10–30.11.2026)"
ROW_TURNOVER = "Оборот новых клиентов (отгрузки)"
ROW_PCT = "% личного плана"
ROW_CALLS = "Звонки — норма"
ROW_TASTINGS = "Дегустации — норма"
ROW_BONUS = "Индивидуальный бонус"


def find_row(values, text, start=1):
    """Номер строки по тексту в колонке A (точное совпадение после strip)."""
    for i, r in enumerate(values, start=1):
        if i >= start and r and str(r[0]).strip() == text:
            return i
    return None


def find_prefix(values, prefix, start=1):
    for i, r in enumerate(values, start=1):
        if i >= start and r and str(r[0]).strip().startswith(prefix):
            return i
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--who", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    who = args.who

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

    svod = sh.worksheet("СВОДНАЯ_ЗП")
    nastr = sh.worksheet("НАСТРОЙКИ")
    sv = svod.get("A1:H200", value_render_option="FORMULA")
    ns = nastr.get("A1:D60", value_render_option="FORMULA")

    itogo = find_row(sv, f"ИТОГО ЗП — {who}")
    if not itogo:
        raise SystemExit(f"не нашёл строку «ИТОГО ЗП — {who}» — блок сотрудника не найден")
    if find_row(sv, HEAD):
        raise SystemExit("блок индивидуальных условий уже заведён — второй раз не нужно")
    rate_row = find_row(sv, "% от оплат (ставка)", start=itogo - 12)
    konkurs = find_row(sv, "Конкурс (бонусы)", start=itogo - 12)
    if not (rate_row and konkurs and rate_row < konkurs < itogo):
        raise SystemExit(f"блок {who} выглядит не как обычно: ставка={rate_row}, "
                         f"конкурс={konkurs}, итого={itogo}")

    # личный план — новой строкой в разделе «ПЛАНЫ НА МЕСЯЦ», перед следующим разделом
    plans_head = find_row(ns, "ПЛАНЫ НА МЕСЯЦ")
    nxt = None
    for i, r in enumerate(ns, start=1):
        if i > plans_head + 1 and r and str(r[0]).strip() and str(r[0]).strip().isupper():
            nxt = i
            break
    if not nxt:
        raise SystemExit("не нашёл конец раздела «ПЛАНЫ НА МЕСЯЦ» в НАСТРОЙКАХ")
    plan_row = nxt                      # сюда вставляем, раздел ниже уедет на строку

    print(f"СВОДНАЯ: блок {who} — ставка стр.{rate_row}, конкурс стр.{konkurs}, "
          f"итого стр.{itogo}")
    print(f"  вставляем 6 строк после {konkurs}; ИТОГО уедет на {itogo + 6}")
    print(f"  ставка 115% в C{rate_row}: 3% → 4%")
    print(f"НАСТРОЙКИ: личный план {PLAN_PERSONAL:,} ₽ новой строкой {plan_row}".replace(",", " "))
    if not args.apply:
        print("\n(это план — ничего не записано; добавь --apply)")
        return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = os.path.join("docs", f"бэкап_сводная_настройки_{stamp}.json")
    json.dump({"СВОДНАЯ_ЗП": sv, "НАСТРОЙКИ": ns}, open(backup, "w"), ensure_ascii=False)
    print(f"бэкап: {backup}")

    # 1. НАСТРОЙКИ — личный план
    sh.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": nastr.id, "dimension": "ROWS",
                  "startIndex": plan_row - 1, "endIndex": plan_row},
        "inheritFromBefore": True}}]})
    nastr.update(values=[[f"{who} — личный план (инд. условия)",
                          "Оборот новых клиентов (личный план)", PLAN_PERSONAL,
                          "Индивидуальные условия 01.10–30.11.2026; общая сетка "
                          "считается от C8/C12, этот план — только для инд. бонуса"]],
                 range_name=f"A{plan_row}:D{plan_row}", value_input_option="USER_ENTERED")

    # 2. СВОДНАЯ — шесть строк после «Конкурс (бонусы)»
    sh.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": svod.id, "dimension": "ROWS",
                  "startIndex": konkurs, "endIndex": konkurs + 6},
        "inheritFromBefore": True}}]})
    r0 = konkurs + 1                     # первая новая строка
    rows = [
        [HEAD, f"Личный план {PLAN_PERSONAL} ₽ · звонки 30/смену · 6 качественных "
               f"дегустаций в неделю", "", ""],
        [ROW_TURNOVER, "Оборот новых клиентов из 1С (лист НОВЫЕ_КЛИЕНТЫ)",
         f'=IFERROR(SUMIF(\'НОВЫЕ_КЛИЕНТЫ\'!$C$4:$C$503;"{who}";'
         f'\'НОВЫЕ_КЛИЕНТЫ\'!$H$4:$H$503);0)', ""],
        [ROW_PCT, f"Оборот / личный план (НАСТРОЙКИ!C{plan_row})",
         f"=IFERROR(C{r0 + 1}/'НАСТРОЙКИ'!$C${plan_row};0)", ""],
        [ROW_CALLS, "В среднем ≥30 за смену и ни одной смены ниже 25 (лист ЗВОНКИ)",
         "", "—"],
        [ROW_TASTINGS, "6 качественных в каждую неделю; неполная неделя — по сменам "
                       "(воронка «Дегустации» Битрикса)", "", "—"],
        [ROW_BONUS, "70%→30 000 · 85%→45 000 · 100%→60 000; одна норма из двух — 30%. "
                    "Ставит individual_kpi.py --apply", 0, ""],
    ]
    svod.update(values=rows, range_name=f"A{r0}:D{r0 + 5}", value_input_option="USER_ENTERED")

    # 3. ставка 115% — 4% вместо 3%
    cur = svod.acell(f"C{rate_row}", value_render_option="FORMULA").value
    new = cur.replace("IF(C{0}>=1,15;0,03;".format(rate_row - 2),
                      "IF(C{0}>=1,15;{1};".format(rate_row - 2, RATE_115))
    if new == cur:
        print(f"⚠️ не нашёл ступень 115% в формуле C{rate_row} — поправь руками: {cur}")
    else:
        svod.update(values=[[new]], range_name=f"C{rate_row}", value_input_option="USER_ENTERED")
        label = svod.acell(f"B{rate_row}").value or ""
        svod.update(values=[[label.replace("115%→3%", "115%→4% (инд.)")]],
                    range_name=f"B{rate_row}", value_input_option="USER_ENTERED")

    # 4. ИТОГО — добавляем индивидуальный бонус
    itogo_new = itogo + 6
    cur = svod.acell(f"C{itogo_new}", value_render_option="FORMULA").value
    assert cur and cur.startswith("="), f"ИТОГО не на месте: C{itogo_new}={cur!r}"
    svod.update(values=[[cur[:-1] + f"+C{r0 + 5})" if cur.endswith(")") else cur + f"+C{r0 + 5}"]],
                range_name=f"C{itogo_new}", value_input_option="USER_ENTERED")
    print(f"готово: строки {r0}-{r0 + 5}, ИТОГО {itogo_new}")


if __name__ == "__main__":
    main()
