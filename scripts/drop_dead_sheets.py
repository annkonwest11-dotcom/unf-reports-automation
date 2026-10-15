# -*- coding: utf-8 -*-
"""Удалить мёртвые листы зарплатной таблицы (решение Анны 15.10.2026).

Что и почему (проверено графом формульных ссылок между всеми листами + grep по коду):

  КОНКУРС              ⛔ остановлен 31.08.2026, формульных ссылок нет; с 15.10 Анна
                       считает конкурс в отчёте по продажам. Формулы листа лежат в
                       docs/КОНКУРС_формулы_бэкап_2026-08-31.json.
  ДАШБОРД_ДАННЫЕ       нужен только старому GAS-дашборду KPI (dashboard/Code.gs,
                       doGet). Его заменил борд РОПа — «пусть будет только он».
  КПИ_ДАННЫЕ           мусор: в нём лежит копия журнала БЛАНКИ, а не KPI. Наполнял
                       scripts/sync_kpi.py (копировал ПОСЛЕДНИЙ лист KPI-таблицы, а
                       последним с 12.10 стал «БЛАНКИ»), и в cron он прописан на
                       несуществующий путь /opt/tgbot — то есть не работает.
  LOG                  писал GitHub Action daily_reports.yml; последняя запись
                       09.07.2026, три месяца молчит.
  СВОДНАЯ_ЗП_МАЙ_2026  архив мая в старом формате: с июня месяц архивируется одним
  СМЕНЫ_МАЙ_2026       листом АРХИВ_<МЕСЯЦ>_2026.

★Перед запуском на сервере должен лежать sheets.py от 15.10 или новее: прежняя
версия включала КОНКУРС в архив месяца жёстким списком и падала бы на его
отсутствии при закрытии месяца.

Запуск:  venv/bin/python scripts/drop_dead_sheets.py          — план
         venv/bin/python scripts/drop_dead_sheets.py --apply  — удалить
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

DEAD = {
    "КОНКУРС": "остановлен 31.08.2026, конкурс считаем в отчёте по продажам",
    "ДАШБОРД_ДАННЫЕ": "старый GAS-дашборд KPI заменён бордом РОПа",
    "КПИ_ДАННЫЕ": "копия журнала БЛАНКИ, наполнитель sync_kpi.py мёртв",
    "LOG": "GitHub Action молчит с 09.07.2026",
    "СВОДНАЯ_ЗП_МАЙ_2026": "архив мая в старом формате",
    "СМЕНЫ_МАЙ_2026": "архив мая в старом формате",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    gc = gspread.authorize(Credentials.from_service_account_file(
        "credentials.json", scopes=SCOPES))
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    titles = [w.title for w in sh.worksheets()]

    found = [t for t in DEAD if t in titles]
    missing = [t for t in DEAD if t not in titles]
    print("УДАЛЯЕМ:")
    for t in found:
        ws = sh.worksheet(t)
        filled = len([r for r in ws.get_all_values() if any(str(c).strip() for c in r)])
        print(f"  {t:22} {filled:>4} строк — {DEAD[t]}")
    for t in missing:
        print(f"  {t:22}   — уже нет")
    print(f"\nостаётся листов: {len(titles) - len(found)}")

    if not args.apply:
        print("\n(это только план; чтобы выполнить — добавь --apply)")
        return
    if not found:
        print("\nнечего удалять")
        return

    # Бэкап: содержимое и формулы — чтобы лист можно было восстановить целиком.
    data = {"дата": datetime.date.today().isoformat(), "листы": {}}
    for t in found:
        ws = sh.worksheet(t)
        data["листы"][t] = {
            "причина": DEAD[t],
            "values": ws.get_all_values(),
            "formulas": ws.get(value_render_option="FORMULA"),
        }
    path = f"docs/бэкап_удалённые_листы_{data['дата']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"\nбэкап: {path}")

    for t in found:
        sh.del_worksheet(sh.worksheet(t))
        print(f"удалён: {t}")
    print("\nготово. Листов в таблице:", len(sh.worksheets()))


if __name__ == "__main__":
    main()
