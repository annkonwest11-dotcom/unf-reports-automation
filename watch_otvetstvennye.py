#!/usr/bin/env python3
"""Слежение за полем «Ответственный» в карточках контрагентов 1С.

Зачем: ручные выгрузки Анны из 1С строятся по этому полю, а зарплатная таблица —
по СПРАВОЧНИКУ. Когда ответственного в 1С меняют (а это происходит: Pepe Nero за
один день 05.08 успел побывать у Папоян, Ксении и Губарева), выгрузка молча
перестаёт показывать деньги клиента — и месяц не сходится. Пусть лучше скажет бот.

Хранит снимок `otvetstvennye_state.json` и сравнивает с ним при каждом запуске.
Сообщает только про изменения; если их нет — молчит (в расписании это важно).
Карточки, у которых есть строка в листах ДАННЫЕ, показываются первыми и с суммой
оплат за расчётный месяц — по ним расхождение в выгрузке будет заметно сразу.

Запуск:  venv/bin/python watch_otvetstvennye.py            — показать изменения
         venv/bin/python watch_otvetstvennye.py --send      — и отправить Анне
         venv/bin/python watch_otvetstvennye.py --reset     — принять текущее за норму
"""
import argparse
import json
import logging
import os

from sync_odata import (BASES, SHEET_BASES, ALIASES, DATA_START_ROW, _fetch_odata, _open_spreadsheet,
                        _parse_settings_period, aggregate_balances, norm_name)

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "otvetstvennye_state.json")
EMPTY = "00000000-0000-0000-0000-000000000000"

_ALIAS_NORM = {norm_name(k): v for k, v in ALIASES.items()}


def canon(name):
    nn = norm_name(name)
    return norm_name(_ALIAS_NORM[nn]) if nn in _ALIAS_NORM else nn


def snapshot():
    """{ref: {база, имя карточки, ответственный}} по всем контрагентам обеих баз."""
    out = {}
    for base_name, cfg in SHEET_BASES.items():
        emp = {e["Ref_Key"]: (e.get("Description") or "").strip()
               for e in _fetch_odata(cfg["id"], "Catalog_Сотрудники")}
        for c in _fetch_odata(cfg["id"], "Catalog_Контрагенты"):
            if c.get("IsFolder"):
                continue
            key = c.get("Ответственный_Key", EMPTY)
            out[c["Ref_Key"]] = {
                "base": base_name,
                "name": (c.get("Description") or "").strip(),
                "who": "" if key == EMPTY else emp.get(key, f"?{key[:8]}"),
            }
    return out


def our_clients():
    """{canon: оплаты за расчётный месяц} — только строки наших листов ДАННЫЕ."""
    ss = _open_spreadsheet()
    pays = {}
    for cfg in SHEET_BASES.values():
        for r in ss.worksheet(cfg["sheet_name"]).get(
                "A1:L600", value_render_option="UNFORMATTED_VALUE")[DATA_START_ROW - 1:]:
            name = str(r[0]).strip() if r and len(r) > 0 else ""
            if not name:
                continue
            val = r[3] if len(r) > 3 else 0
            pays[canon(name)] = float(val) if isinstance(val, (int, float)) else 0.0
    return pays


def diff(old, new):
    """Три списка изменений: назначен / снят / переназначен."""
    assigned, cleared, changed = [], [], []
    for ref, cur in new.items():
        was = old.get(ref)
        if was is None:
            continue                     # новая карточка — это не «изменение»
        if was["who"] == cur["who"]:
            continue
        if not was["who"]:
            assigned.append((cur, was["who"], cur["who"]))
        elif not cur["who"]:
            cleared.append((cur, was["who"], cur["who"]))
        else:
            changed.append((cur, was["who"], cur["who"]))
    return assigned, cleared, changed


def build_report(assigned, cleared, changed, pays):
    """Текст сообщения. Клиенты из наших листов — первыми, с суммой оплат."""
    def key(item):
        cur = item[0]
        return -pays.get(canon(cur["name"]), -1)

    blocks = []
    for title, items in (("🔄 Переназначены", changed),
                         ("➕ Назначен ответственный", assigned),
                         ("➖ Ответственный снят", cleared)):
        if not items:
            continue
        lines = [title]
        for cur, was, now in sorted(items, key=key):
            pay = pays.get(canon(cur["name"]))
            money = f" · оплаты {pay:,.0f} ₽".replace(",", " ") if pay else ""
            arrow = f"{was or '—'} → {now or '—'}"
            lines.append(f"  • {cur['name']}{money}\n     {arrow}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return ("⚠️ Изменения ответственных в 1С\n\n" + "\n\n".join(blocks) +
            "\n\nНа расчёт ЗП не влияет (считаем по СПРАВОЧНИКУ), но выгрузка из 1С "
            "по этому менеджеру теперь покажет другие суммы.")


def check(send=False, reset=False):
    new = snapshot()
    old = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as fh:
            old = json.load(fh)

    if reset or not old:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(new, fh, ensure_ascii=False)
        print(f"снимок записан: {len(new)} карточек"
              f"{' (сброс по --reset)' if reset else ' — первый запуск, сравнивать не с чем'}")
        return ""

    assigned, cleared, changed = diff(old, new)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(new, fh, ensure_ascii=False)

    if not (assigned or cleared or changed):
        print(f"изменений нет ({len(new)} карточек)")
        return ""

    report = build_report(assigned, cleared, changed, our_clients())
    print(report)
    if send:
        import requests
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
        resp = requests.post(
            f"https://api.telegram.org/bot{os.getenv('BOT_TOKEN')}/sendMessage",
            data={"chat_id": os.getenv("ANNA_CHAT_ID"), "text": report}, timeout=60)
        print("отправка:", "OK" if resp.json().get("ok") else resp.text[:150])
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Слежение за ответственными в 1С")
    p.add_argument("--send", action="store_true", help="отправить отчёт Анне в Telegram")
    p.add_argument("--reset", action="store_true", help="принять текущее состояние за норму")
    args = p.parse_args()
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        level=logging.INFO)
    check(send=args.send, reset=args.reset)
