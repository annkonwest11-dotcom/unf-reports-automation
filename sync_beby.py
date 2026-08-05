#!/usr/bin/env python3
"""Автозаполнение листа БЕБИ_ЛИСТЫ из 1С (OData).

Что делает: берёт из СПРАВОЧНИКА клиентов с отметкой «Беби-листы = Да», тянет их
обороты за расчётный месяц из регистра «Продажи» в разрезе номенклатуры и пишет
в лист БЕБИ_ЛИСТЫ три колонки:
    A — контрагент (имя строки листа ДАННЫЕ, чтобы работал VLOOKUP в колонке G)
    D — оборот микрозелени (всё, кроме беби-листов: н/с, срез, цветы, доставка)
    E — оборот беби-листов
Остальное (B менеджер, C итого, F %беби, G оплаты, H/I/J) считают формулы листа.

★ ПРИЗНАК БЕБИ-ЛИСТА — ФАСОВКА «100 гр» В НАЗВАНИИ номенклатуры (правило Анны,
05.08.2026). Группа «Беби листы» есть только в базе Губарева, в базе Перфильева те же
позиции лежат без группы — поэтому матчим по названию, а не по группе. Исключение:
«Хрустальная трава 100 гр» — это группа «Цветы», не беби-лист.

Клиенты без оборота и без оплат в расчётном месяце в лист не попадают.

Запуск:  venv/bin/python sync_beby.py            (показать план)
         venv/bin/python sync_beby.py --apply    (записать в таблицу)
"""
import argparse
import logging
from collections import defaultdict
from datetime import datetime

from sync_odata import (BASES, ALIASES, DATA_START_ROW, _fetch_odata, _open_spreadsheet,
                        _parse_settings_period, aggregate_balances, norm_name)

logger = logging.getLogger(__name__)

SHEET = "БЕБИ_ЛИСТЫ"
FIRST_ROW = 4           # первая строка данных
LAST_ROW = 23           # последняя строка с готовыми формулами B/C/F..J
BEBY_MARK = "100 гр"    # признак фасовки беби-листа
NOT_BEBY_GROUPS = {"Цветы"}   # «Хрустальная трава 100 гр» — цветок, не беби-лист

_ALIAS_NORM = {norm_name(k): v for k, v in ALIASES.items()}


def canon(name):
    """Имя карточки 1С → ключ строки листа (склеивает ЭДО/dsbx/счёт-дубли)."""
    nn = norm_name(name)
    return norm_name(_ALIAS_NORM[nn]) if nn in _ALIAS_NORM else nn


def _period(spreadsheet):
    """(StartPeriod, EndPeriod, ярлык) расчётного месяца из НАСТРОЙКИ!B4 — того же,
    по которому считается СВОДНАЯ (в overlap-режиме это ещё НЕ закрытый месяц)."""
    pp = _parse_settings_period(spreadsheet)
    if not pp:
        raise RuntimeError("НАСТРОЙКИ!B4 не распознан — не знаю, за какой месяц считать")
    year, month = pp
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    fmt = "datetime'%Y-%m-%dT00:00:00'"
    return start.strftime(fmt), end.strftime(fmt), start.strftime("%Y-%m")


def beby_clients(spreadsheet):
    """{canon: имя из СПРАВОЧНИКА} для клиентов с «Беби-листы = Да» (колонка E)."""
    out = {}
    for r in spreadsheet.worksheet("СПРАВОЧНИК").get("A1:H1000"):
        name = (r[0] or "").strip() if r else ""
        if name and len(r) > 4 and (r[4] or "").strip().lower() == "да":
            out.setdefault(canon(name), name)
    return out


def data_rows(spreadsheet):
    """{canon: (имя строки листа ДАННЫЕ, отметка «беби» в колонке I)}.

    ★ В колонку A листа БЕБИ_ЛИСТЫ надо писать имя ИМЕННО ТАК, как строка названа в
    ДАННЫХ: формула G ищет оплаты через VLOOKUP по точному совпадению. Имя в
    СПРАВОЧНИКЕ может отличаться (у SAVVA: строка листа «…(ООО БРАНЧ) ЭДО», а в
    справочнике есть и «…(ООО БРАНЧ)» — VLOOKUP не находил, G оставался 0)."""
    out = {}
    for cfg in BASES.values():
        grid = spreadsheet.worksheet(cfg["sheet_name"]).get("A1:L600")
        for r in grid[DATA_START_ROW - 1:]:
            name = (r[0] or "").strip() if r else ""
            if name:
                out.setdefault(canon(name), (name, (r[8] or "").strip() if len(r) > 8 else ""))
    return out


def fetch_oborot_by_group(base_id, start, end, clients):
    """{canon: [микро, беби]} — обороты расчётного месяца по клиентам из clients."""
    nom = _fetch_odata(base_id, "Catalog_Номенклатура")
    folders = {n["Ref_Key"]: n.get("Description", "") for n in nom if n.get("IsFolder")}
    is_beby = {}
    for n in nom:
        if n.get("IsFolder"):
            continue
        name = (n.get("Description") or "").lower()
        group = folders.get(n.get("Parent_Key"), "")
        is_beby[n["Ref_Key"]] = BEBY_MARK in name and group not in NOT_BEBY_GROUPS
    ctg = {c["Ref_Key"]: c.get("Description", "")
           for c in _fetch_odata(base_id, "Catalog_Контрагенты")}
    out = defaultdict(lambda: [0.0, 0.0])
    for r in _fetch_odata(base_id, "AccumulationRegister_Продажи/Turnovers("
                                   f"StartPeriod={start},EndPeriod={end})"):
        cn = canon(ctg.get(r.get("Контрагент_Key"), ""))
        if cn not in clients:
            continue
        out[cn][1 if is_beby.get(r.get("Номенклатура_Key")) else 0] += (
            r.get("СуммаTurnover", 0) or 0)
    return out


def fetch_pay(base_id, start, end, clients):
    """{canon: оплаты расчётного месяца} — чтобы не заводить строки без движений."""
    ctg = {c["Ref_Key"]: c.get("Description", "")
           for c in _fetch_odata(base_id, "Catalog_Контрагенты")}
    rows = _fetch_odata(base_id, "AccumulationRegister_РасчетыСПокупателями/BalanceAndTurnovers("
                                 f"StartPeriod={start},EndPeriod={end})")
    out = defaultdict(float)
    for key, vals in aggregate_balances(rows).items():
        cn = canon(ctg.get(key, ""))
        if cn in clients:
            out[cn] += vals[2]
    return out


def build_rows(spreadsheet):
    """Список [имя, микро, беби] для записи в лист, по убыванию оборота."""
    start, end, label = _period(spreadsheet)
    clients = beby_clients(spreadsheet)
    logger.info("Период %s, клиентов с беби='Да': %d", label, len(clients))

    oborot, pay = defaultdict(lambda: [0.0, 0.0]), defaultdict(float)
    for cfg in BASES.values():
        for cn, vals in fetch_oborot_by_group(cfg["id"], start, end, clients).items():
            oborot[cn][0] += vals[0]
            oborot[cn][1] += vals[1]
        for cn, v in fetch_pay(cfg["id"], start, end, clients).items():
            pay[cn] += v

    in_data = data_rows(spreadsheet)
    rows, warns = [], []
    for cn, name in clients.items():
        micro, beby = oborot.get(cn, [0.0, 0.0])
        if micro <= 0 and beby <= 0 and pay.get(cn, 0.0) <= 0:
            continue        # ни оборота, ни оплат — в лист не заводим
        sheet_name, mark = in_data.get(cn, (None, ""))
        if sheet_name is None:
            warns.append(f"{name}: нет строки в ДАННЫХ — оплаты (G) не подтянутся")
        elif mark.lower() != "да":
            warns.append(f"{sheet_name}: в ДАННЫХ колонка I = '{mark}' (не «Да») — вычет "
                         f"не применится, проставьте беби в СПРАВОЧНИКЕ у ЭТОЙ строки")
        rows.append([sheet_name or name, round(micro, 2), round(beby, 2)])
    rows.sort(key=lambda x: -(x[1] + x[2]))
    for w in warns:
        logger.warning("⚠️ %s", w)
    return rows, label


def sync(dry_run=True):
    ss = _open_spreadsheet()
    rows, label = build_rows(ss)
    capacity = LAST_ROW - FIRST_ROW + 1
    if len(rows) > capacity:
        logger.warning("Клиентов %d, а строк с формулами только %d — лишние не влезут "
                       "(протяните формулы ниже строки %d)", len(rows), capacity, LAST_ROW)
        rows = rows[:capacity]

    print(f"БЕБИ_ЛИСТЫ, период {label}: строк к записи {len(rows)}")
    print(f"{'контрагент':<46} {'микро':>12} {'беби':>12} {'%беби':>7}")
    for name, micro, beby in rows:
        total = micro + beby
        print(f"{name[:46]:<46} {micro:>12,.2f} {beby:>12,.2f} "
              f"{(beby / total if total else 0):>7.1%}".replace(",", " "))

    if dry_run:
        print("\n(dry-run — ничего не записано; запусти с --apply)")
        return rows

    ws = ss.worksheet(SHEET)
    ws.batch_clear([f"A{FIRST_ROW}:A{LAST_ROW}", f"D{FIRST_ROW}:E{LAST_ROW}"])
    if rows:
        ws.update([[r[0]] for r in rows], f"A{FIRST_ROW}:A{FIRST_ROW + len(rows) - 1}",
                  value_input_option="RAW")
        ws.update([[r[1], r[2]] for r in rows], f"D{FIRST_ROW}:E{FIRST_ROW + len(rows) - 1}",
                  value_input_option="RAW")
    print(f"\n✅ записано строк: {len(rows)}")
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Автозаполнение листа БЕБИ_ЛИСТЫ из 1С")
    p.add_argument("--apply", action="store_true", help="записать в таблицу")
    args = p.parse_args()
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        level=logging.INFO)
    sync(dry_run=not args.apply)
