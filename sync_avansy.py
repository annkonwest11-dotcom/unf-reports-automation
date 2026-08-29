"""Авто-заполнение выплат официально устроенным сотрудникам из «Кассы GREENCH» →
таблица выплат листа СВОДНАЯ_ЗП.

Официально устроены (выплаты на карту, фиксируются в кассе «Операции», категория
обычно «Зарплата Офис», описание «Заработная плата за … половину месяца»):
    Дарья Вольнова, Ксения Наныкина, Алёна Черкашина, Владислава Герасимчук.

Две выплаты в месяц:
  • «первую половину месяца»  → АВАНС  (23-25, иногда 29) → колонка C «Аванс 24 — на карту (офиц.)»
  • «вторую половину месяца»  → ЗП     (08-10)            → колонка E «ЗП 9 — на карту (офиц.)»

Источник до 28.08.2026 — ADesk, потом касса (ADesk закрыл API). Формат операций
одинаковый: за это отвечает kassa_api.month_operations.

Даты плавают, поэтому тип выплаты определяем по ОПИСАНИЮ операции, а не по числу.
Матч сотрудника — по фамилии в поле contractor (уникальна среди офисных).
Пишем ТОЛЬКО в свои 4 строки и только в колонку C или E — остальное не трогаем.

CLI:
    python sync_avansy.py avans          # dry-run: что впишется в C (аванс)
    python sync_avansy.py zp             # dry-run: что впишется в E (зарплата)
    python sync_avansy.py avans --apply  # записать в таблицу
"""

import logging
import math
import os
from datetime import datetime

import kassa_api

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

_TYPE_EXPENSE = 2  # 2 = расход/выплата

# фамилия-ключ (в contractor) → (строка в СВОДНАЯ_ЗП, отображаемое имя)
EMPLOYEES = {
    "Вольнова":   (126, "Дарья Вольнова"),
    "Наныкина":   (127, "Ксения Наныкина"),
    "Сулименко":  (128, "Лилия Сулименко"),
    "Черкашина":  (129, "Алёна Черкашина"),
    "Герасимчук": (130, "Владислава Герасимчук"),
}

# тип выплаты → колонка таблицы выплат
KIND_COL = {
    "avans": "C",   # Аванс 24 — на карту (офиц.)  ← «первая половина месяца»
    "zp":    "E",   # ЗП 9 — на карту (офиц.)      ← «вторая половина месяца»
}
KIND_TITLE = {"avans": "Аванс (24) — на карту", "zp": "ЗП (9/10) — на карту"}

SHEET_NAME = "СВОДНАЯ_ЗП"


def _contractor_name(t):
    c = t.get("contractor")
    if isinstance(c, dict):
        return c.get("name") or ""
    return c or ""


def _kind_of(description):
    """Определить тип зарплатной выплаты по описанию операции.
    Возвращает 'avans' / 'zp' / None (если это не зарплатная половина)."""
    d = (description or "").lower()
    if "половин" not in d:
        return None
    if "перв" in d:
        return "avans"
    if "втор" in d:
        return "zp"
    return None


def _match_surname(name):
    for surname in EMPLOYEES:
        if surname.lower() in (name or "").lower():
            return surname
    return None


def fetch_payouts(kind, today=None, token=None, ym=None):
    """Суммы выплат нужного типа (kind) по 4 официальным за месяц ym (YYYY-MM).

    ym — месяц ДАТЫ операций кассы. Если не задан, берётся календарный месяц из
    today/now (обратная совместимость). Осмысленный ym передаёт sync_avansy: под
    расчётный период (аванс — сам месяц, ЗП — следующий, т.к. её платят 9-10 числа
    следующего месяца) — чтобы выплата попадала в свою ведомость независимо от даты
    закрытия месяца.

    Возвращает dict: surname → {"amount": float, "name": str, "row": int,
    "date": "DD.MM", "count": int}. Если у сотрудника несколько операций
    этого типа за месяц — суммирует (доплаты), дата = последней операции.
    """
    if kind not in KIND_COL:
        raise ValueError(f"kind должен быть avans|zp, а не {kind!r}")
    ym = ym or (today or datetime.now()).strftime("%Y-%m")

    result = {}
    for t in kassa_api.month_operations(ym, token=token):
        if t.get("type") != _TYPE_EXPENSE:
            continue
        di = t.get("dateIso") or ""
        if not di.startswith(ym):
            continue
        if _kind_of(t.get("description")) != kind:
            continue
        surname = _match_surname(_contractor_name(t))
        if not surname:
            continue
        row, name = EMPLOYEES[surname]
        amt = float(t.get("amount", 0) or 0)
        cur = result.get(surname)
        ddmm = f"{di[8:10]}.{di[5:7]}"
        if cur:
            cur["amount"] = round(cur["amount"] + amt, 2)
            cur["count"] += 1
            if di > cur["_di"]:
                cur["date"], cur["_di"] = ddmm, di
        else:
            result[surname] = {"amount": round(amt, 2), "name": name,
                               "row": row, "date": ddmm, "_di": di, "count": 1}
    for v in result.values():
        v.pop("_di", None)
    logger.info("Касса, выплаты (%s) за %s: %d сотрудников", kind, ym, len(result))
    return result


def _ym_for_period(spreadsheet, kind, today=None):
    """Месяц (YYYY-MM) операций кассы, соответствующий РАСЧЁТНОМУ периоду
    (НАСТРОЙКИ!B4): аванс («первую половину») платят в самом расчётном месяце;
    ЗП («вторую половину») — 9-10 числа СЛЕДУЮЩЕГО месяца. Так авансы читают
    операции того месяца, что сейчас в работе, а не календарного — выплата не
    уедет в чужую ведомость из-за момента закрытия. Если B4 не прочитать —
    None (fetch_payouts откатится на календарный месяц)."""
    from sync_odata import _parse_settings_period
    pp = _parse_settings_period(spreadsheet)
    if not pp:
        return None
    py, pm = pp
    if kind == "zp":
        py, pm = (py + 1, 1) if pm == 12 else (py, pm + 1)
    return f"{py:04d}-{pm:02d}"


def _open_summary_ws():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds_path = os.path.join(os.path.dirname(__file__), "credentials.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    return sh.worksheet(SHEET_NAME)


def _read_current(ws, col):
    """Текущие значения целевых ячеек колонки col для 4 сотрудников.
    Возвращает {cell: float|None} (None = пусто/нечисло)."""
    cells = [f"{col}{row}" for row, _ in EMPLOYEES.values()]
    got = ws.batch_get(cells, value_render_option="UNFORMATTED_VALUE")
    current = {}
    for cell, block in zip(cells, got):
        val = None
        if block and block[0]:
            raw = block[0][0]
            try:
                val = float(raw)
            except (TypeError, ValueError):
                val = None
        current[cell] = val
    return current


def sync_avansy(kind, today=None, apply=True, token=None, ws=None,
                only_changed=False):
    """Тянет выплаты из кассы и (при apply) пишет в СВОДНАЯ_ЗП.

    only_changed=True — сравнивает с тем, что уже стоит в ячейке, и пишет/
    отмечает changed ТОЛЬКО отличающиеся суммы (для частого опроса без спама).

    Возвращает dict: {"kind", "col",
      "items":   [ {name,row,cell,amount,date,count,changed} ]  — все найденные,
      "changed": [ подмножество items, где сумма новая/изменилась ],
      "missing": [имена без операции в этом месяце],
      "applied": bool}.
    """
    col = KIND_COL[kind]

    need_ws = apply or only_changed
    if need_ws and ws is None:
        ws = _open_summary_ws()

    # Операции берём под РАСЧЁТНЫЙ период (НАСТРОЙКИ!B4), а не календарь. Читаем B4
    # только если есть настоящий лист (у мок-ws в тестах атрибута .spreadsheet нет —
    # тогда откат на календарный месяц, поведение как раньше).
    ym = None
    ss = getattr(ws, "spreadsheet", None) if ws is not None else None
    if ss is not None:
        try:
            ym = _ym_for_period(ss, kind, today)
        except Exception:
            logger.exception("Период B4 не прочитан — беру календарный месяц")

    payouts = fetch_payouts(kind, today=today, token=token, ym=ym)
    current = _read_current(ws, col) if (only_changed and ws) else {}

    items, changed, updates = [], [], []
    for surname, (row, name) in EMPLOYEES.items():
        p = payouts.get(surname)
        if not p:
            continue
        cell = f"{col}{row}"
        # официальный аванс/ЗП в ведомость — без копеек (Анна: копейки отсекаем,
        # наличными добиваем до ровного итого)
        val = math.floor(p["amount"])
        old = current.get(cell)
        is_changed = (old is None) or abs(old - val) > 0.01
        it = {"name": name, "row": row, "cell": cell, "amount": val,
              "date": p["date"], "count": p["count"], "changed": is_changed}
        items.append(it)
        if is_changed:
            changed.append(it)
        if not only_changed or is_changed:
            updates.append({"range": cell, "values": [[val]]})

    missing = [name for surname, (row, name) in EMPLOYEES.items()
               if surname not in payouts]

    applied = False
    if apply and updates:
        ws = ws or _open_summary_ws()
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        applied = True
        logger.info("Записано %d ячеек в %s (%s)", len(updates), SHEET_NAME, col)

    return {"kind": kind, "col": col, "items": items, "changed": changed,
            "missing": missing, "applied": applied}


def format_report(rep, only_changed=False):
    """Человекочитаемый отчёт для Telegram.
    only_changed=True — показать лишь появившиеся/изменившиеся выплаты."""
    shown = rep["changed"] if only_changed else rep["items"]
    lines = [f"💳 Выплаты — {KIND_TITLE[rep['kind']]} (колонка {rep['col']})"]
    if shown:
        for it in shown:
            amt = f"{it['amount']:,.2f}".replace(",", " ")
            extra = f" ×{it['count']}" if it["count"] > 1 else ""
            mark = "✅" if rep["applied"] else "•"
            lines.append(f"  {mark} {it['name']}: {amt} ₽  ({it['date']}{extra}) → {it['cell']}")
    else:
        lines.append("  — операций за этот месяц пока нет")
    if rep["missing"]:
        lines.append("⏳ Ещё не выплачено (нет операции): " + ", ".join(rep["missing"]))
    if shown and not rep["applied"]:
        lines.append("\n(dry-run — в таблицу не записано)")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    kind = sys.argv[1] if len(sys.argv) > 1 else "avans"
    apply = "--apply" in sys.argv
    rep = sync_avansy(kind, apply=apply)
    print(format_report(rep))
