#!/usr/bin/env python3
"""Перевод сотрудника на условия SMM: блок в СВОДНОЙ + ставки в НАСТРОЙКАХ.

Условия Анны (файл «KPI dlya SMM - Greench.pdf» от 28.09.2026):
  Блок 1 — оклад: ведение аккаунта 1 (Greench) 25 000 + аккаунта 2 (Вячеслав)
      25 000; плюс по 5 000 за каждый выполненный контент-план (Instagram ×2 и
      Telegram ×2) — потолок фиксированной части 70 000.
  Блок 2 — без потолка: новые клиенты из соцсетей (С 5 000 / В 10 000 / А 20 000,
      через 30 дней работы), рост живых подписчиков (поднимает оклад аккаунта 1:
      1 000→26 000, 5 000→30 000, 10 000→35 000, 15 000+→40 000), залетевшие
      Reels (100 тыс.→1 000, 500 тыс.→2 500, 1 млн→5 000, по высшему порогу).

Старый блок менеджера поиска (смены, оплаты, % плана, фикс.бонус, % от оплат)
при этом УБИРАЕТСЯ: на SMM этих показателей нет (решение Анны 16.10.2026).

Строки ищутся по подписям и перечитываются между шагами — номера в СВОДНОЙ
уезжают при каждом кадровом изменении.

    scripts/setup_smm.py --who "Ксения Наныкина"
    scripts/setup_smm.py --who "Ксения Наныкина" --apply
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SALARY_1 = 25_000          # аккаунт 1 (Greench) — базовая ступень
SALARY_2 = 0               # аккаунт 2 (Вячеслав) — включить, когда канал запустится
CONTENT_PLAN = 5_000       # премия за выполненный контент-план одного канала
SECTION = "КПИ SMM"

ROW_SUBS = "Живых подписчиков Instagram (Greench)"
ROW_PAY1 = "Оклад — аккаунт 1 (Greench)"
ROW_PAY2 = "Оклад — аккаунт 2 (Вячеслав)"
ROW_PLAN = "Контент-план — выполнено каналов"
ROW_LEADS = "Премия за новых клиентов из соцсетей"
ROW_REELS = "Премия за залетевшие Reels"
ROW_EXTRA = "Дополнительная премия"
ROW_NOTE = "Комментарий к доп.премии"


def col_a(ws):
    return [(v or "").strip() for v in ws.col_values(1)]


def row_of(names, text, after=0):
    for i, v in enumerate(names, start=1):
        if i > after and v == text:
            return i
    return None


def block_head(names, who, itogo):
    """Строка-заголовок блока сотрудника: «ФИО | роль», ближайшая над ИТОГО."""
    found = None
    for i, v in enumerate(names, start=1):
        if itogo and i >= itogo:
            break
        if v.startswith(who) and "|" in v:
            found = i
    return found


def row_starts(names, prefix, after=0):
    for i, v in enumerate(names, start=1):
        if i > after and v.startswith(prefix):
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
    svod, nastr = sh.worksheet("СВОДНАЯ_ЗП"), sh.worksheet("НАСТРОЙКИ")

    names = col_a(svod)
    itogo = row_of(names, f"ИТОГО ЗП — {who}")
    # заголовок блока — «  ФИО   |   Роль»; в дашборде вверху ФИО тоже встречается,
    # поэтому берём последнее вхождение ВЫШЕ строки ИТОГО
    head = block_head(names, who, itogo)
    if not (head and itogo and head < itogo):
        raise SystemExit(f"не нашёл блок {who}: заголовок={head}, итого={itogo}")
    if row_of(names, ROW_PAY1):
        raise SystemExit("SMM-блок уже заведён — второй раз не нужно")
    inner = itogo - head - 1
    need = 8
    dash = row_of(names, who)          # строка в дашборде вверху листа
    if not dash or dash >= head:
        raise SystemExit(f"не нашёл строку {who} в дашборде (нашёл {dash})")

    # НАСТРОЙКИ: раздел ставок вместо осиротевшего «КПИ ВЛАДЫ»
    ns = nastr.get("A1:D60")
    ns_names = [((r or [""])[0] or "").strip() for r in ns]
    old_sec = next((i for i, v in enumerate(ns_names, start=1)
                    if v.startswith("КПИ ВЛАДЫ") or v.startswith(SECTION)), None)
    if old_sec:
        end = next((i for i, v in enumerate(ns_names, start=1)
                    if i > old_sec and v.isupper() and v), len(ns_names) + 1)
        old_len = end - old_sec
    else:
        raise SystemExit("не нашёл раздел «КПИ ВЛАДЫ» в НАСТРОЙКАХ — куда класть ставки?")

    print(f"СВОДНАЯ: блок {who} — заголовок {head}, итого {itogo} "
          f"({inner} строк внутри → {need}), дашборд стр.{dash}")
    print(f"НАСТРОЙКИ: раздел «КПИ ВЛАДЫ» строки {old_sec}-{end - 1} ({old_len}) → "
          f"«{SECTION}» (4 строки)")
    if not args.apply:
        print("\n(это план — ничего не записано; добавь --apply)")
        return

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join("docs", f"бэкап_smm_{stamp}.json")
    json.dump({"СВОДНАЯ_ЗП": svod.get("A1:H200", value_render_option="FORMULA"),
               "НАСТРОЙКИ": nastr.get("A1:D60", value_render_option="FORMULA")},
              open(path, "w"), ensure_ascii=False)
    print(f"бэкап: {path}")

    # ── 1. НАСТРОЙКИ ───────────────────────────────────────────────────────
    reqs = []
    if old_len > 4:
        reqs.append({"deleteDimension": {"range": {
            "sheetId": nastr.id, "dimension": "ROWS",
            "startIndex": old_sec + 3, "endIndex": old_sec - 1 + old_len}}})
    elif old_len < 4:
        reqs.append({"insertDimension": {"range": {
            "sheetId": nastr.id, "dimension": "ROWS",
            "startIndex": old_sec - 1 + old_len, "endIndex": old_sec + 3},
            "inheritFromBefore": True}})
    if reqs:
        sh.batch_update({"requests": reqs})
    nastr.update(values=[
        [SECTION, "", "", "Ставки по файлу «KPI dlya SMM - Greench.pdf» (28.09.2026)"],
        [who, "SMM оклад — аккаунт 1 (Greench)", SALARY_1,
         "Растёт с живыми подписчиками: 1 000→26 000 · 5 000→30 000 · "
         "10 000→35 000 · 15 000+→40 000"],
        [who, "SMM оклад — аккаунт 2 (Вячеслав)", SALARY_2,
         "25 000, когда канал запустится — уточнить в конце месяца"],
        [who, "SMM премия за контент-план (за канал)", CONTENT_PLAN,
         "4 канала: Instagram Greench и Вячеслава, Telegram Greench и Вячеслава — до 20 000"],
    ], range_name=f"A{old_sec}:D{old_sec + 3}", value_input_option="USER_ENTERED")
    r_pay1, r_pay2, r_plan = old_sec + 1, old_sec + 2, old_sec + 3
    print(f"НАСТРОЙКИ: ставки в строках {r_pay1}-{r_plan}")

    # ── 2. СВОДНАЯ: подгоняем размер блока ─────────────────────────────────
    names = col_a(svod)
    itogo = row_of(names, f"ИТОГО ЗП — {who}")
    head = block_head(names, who, itogo)
    if not head:
        raise SystemExit(f"после правки НАСТРОЕК не нашёл заголовок блока {who}")
    inner = itogo - head - 1
    if inner > need:
        sh.batch_update({"requests": [{"deleteDimension": {"range": {
            "sheetId": svod.id, "dimension": "ROWS",
            "startIndex": head + need, "endIndex": head + inner}}}]})
    elif inner < need:
        sh.batch_update({"requests": [{"insertDimension": {"range": {
            "sheetId": svod.id, "dimension": "ROWS",
            "startIndex": head + inner, "endIndex": head + need},
            "inheritFromBefore": True}}]})

    r = head + 1                                    # первая строка блока
    s, p1, p2, pl, ld, re_, ex = r, r + 1, r + 2, r + 3, r + 4, r + 5, r + 6
    svod.batch_update([
        {"range": f"A{s}:F{s}", "values": [[ROW_SUBS,
            "Ставит директор; подписчики должны быть живыми, из Reels — бывают проверки на накрутку",
            "", 0, "", "← введите число"]]},
        {"range": f"A{p1}:D{p1}", "values": [[ROW_PAY1,
            f"{SALARY_1} ₽; с ростом живых подписчиков 1 000→26 000 · 5 000→30 000 · "
            f"10 000→35 000 · 15 000+→40 000",
            f"=IF(D{s}>=15000;40000;IF(D{s}>=10000;35000;IF(D{s}>=5000;30000;"
            f"IF(D{s}>=1000;26000;'НАСТРОЙКИ'!$C${r_pay1}))))", ""]]},
        {"range": f"A{p2}:C{p2}", "values": [[ROW_PAY2,
            "25 000, когда канал запустится — пока 0, уточнить в конце месяца",
            f"='НАСТРОЙКИ'!$C${r_pay2}"]]},
        {"range": f"A{pl}:F{pl}", "values": [[ROW_PLAN,
            f"Instagram ×2 и Telegram ×2, по {CONTENT_PLAN} ₽ за выполненный план (до "
            f"{CONTENT_PLAN * 4} ₽)",
            f"=IFERROR(D{pl}*'НАСТРОЙКИ'!$C${r_plan};0)", 0, "", "← сколько каналов (0–4)"]]},
        {"range": f"A{ld}:F{ld}", "values": [[ROW_LEADS,
            "Категория С → 5 000 · В → 10 000 · А → 20 000; клиент новый, пришёл из "
            "соцсетей, премия через 30 дней сотрудничества", 0, "", "", "← сумма и расшифровка в D"]]},
        {"range": f"A{re_}:F{re_}", "values": [[ROW_REELS,
            "100 000 просмотров → 1 000 · 500 000 → 2 500 · 1 млн → 5 000; только органика, "
            "за ролик по высшему порогу, фиксируется на 30-й день", 0, "", "", "← сумма и расшифровка в D"]]},
        {"range": f"A{ex}:F{ex}", "values": [[ROW_EXTRA, "", "", "", "", "← введите сумму"]]},
        # B чистим явно: в строке мог остаться текст прежней подписи блока
        {"range": f"A{ex + 1}:B{ex + 1}", "values": [[ROW_NOTE, ""]]},
    ], value_input_option="USER_ENTERED")

    # ★формат ставим явно: вставленные строки наследуют его от соседа сверху, и
    # на живой таблице 16.10 «Контент-план» и ИТОГО уехали в проценты (25 000 ₽
    # показывалось как 2 500 000%). Старые строки блока были «% плана» и «% от оплат».
    sh.batch_update({"requests": [{"repeatCell": {
        "range": {"sheetId": svod.id, "startRowIndex": head, "endRowIndex": ex + 1,
                  "startColumnIndex": 2, "endColumnIndex": 4},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                                                        "pattern": "#,##0"}}},
        "fields": "userEnteredFormat.numberFormat"}}]})

    names = col_a(svod)
    itogo = row_of(names, f"ИТОГО ЗП — {who}")
    sh.batch_update({"requests": [{"repeatCell": {
        "range": {"sheetId": svod.id, "startRowIndex": itogo - 1, "endRowIndex": itogo,
                  "startColumnIndex": 2, "endColumnIndex": 3},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER",
                                                        "pattern": "#,##0"}}},
        "fields": "userEnteredFormat.numberFormat"}}]})
    svod.update(values=[[f"=C{p1}+C{p2}+C{pl}+IF(ISNUMBER(C{ld});C{ld};0)"
                         f"+IF(ISNUMBER(C{re_});C{re_};0)+IF(ISNUMBER(C{ex});C{ex};0)"]],
                range_name=f"C{itogo}", value_input_option="USER_ENTERED")
    print(f"СВОДНАЯ: блок {r}-{ex + 1}, ИТОГО {itogo}")

    # ── 3. дашборд: отдельная секция SMM вместо строки у менеджеров поиска ──
    names = col_a(svod)
    dash = row_of(names, who)
    rop = row_starts(names, "РОП")
    if not (dash and rop and dash < rop):
        raise SystemExit(f"дашборд не разобран: {who}={dash}, РОП={rop}")
    sh.batch_update({"requests": [
        {"deleteDimension": {"range": {"sheetId": svod.id, "dimension": "ROWS",
                                       "startIndex": dash - 1, "endIndex": dash}}},
        {"insertDimension": {"range": {"sheetId": svod.id, "dimension": "ROWS",
                                       "startIndex": rop - 2, "endIndex": rop},
                             "inheritFromBefore": True}},
    ]})
    names = col_a(svod)
    itogo = row_of(names, f"ИТОГО ЗП — {who}")
    svod.batch_update([
        {"range": f"A{rop - 1}:C{rop - 1}", "values": [["SMM", "", ""]]},
        {"range": f"A{rop}:C{rop}", "values": [[who, "SMM", f"=C{itogo}"]]},
    ], value_input_option="USER_ENTERED")
    print(f"дашборд: секция SMM в строках {rop - 1}-{rop}, ссылка на C{itogo}")


if __name__ == "__main__":
    main()
