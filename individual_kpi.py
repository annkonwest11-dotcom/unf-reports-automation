# -*- coding: utf-8 -*-
"""Индивидуальные условия менеджера на адаптации (Виолетта, 01.10–30.11.2026).

Условия Анны (файл «Индивидуальные_условия_менеджера_GREENCH.pdf», 15.10.2026):
ЗП = оклад за смены + стандартная сетка (как у всех) + ИНДИВИДУАЛЬНЫЙ БОНУС.
Здесь считается только третья часть — первые две уже живут формулами в СВОДНОЙ.

    оборот новых клиентов   % личного плана   звонки(30%)  дегустации(30%)  всё(100%)
    до 175 000              < 70%                       0               0           0
    от 175 000              70%                     9 000           9 000      30 000
    от 212 500              85%                    13 500          13 500      45 000
    от 250 000              100%                   18 000          18 000      60 000

«Выполнено всё» = оборот взял ступень + норма звонков + норма дегустаций. Если
выполнена только одна норма — 30% от суммы ступени; если ни одной — ноль.

КАК СЧИТАЮТСЯ НОРМЫ (решения Анны 15.10.2026)
- **Звонки — по «Звонки всего» из отчётов смен** (не по длительности разговора):
  в среднем ≥30 за смену и ни одной смены ниже 25. Источник — лист ЗВОНКИ, его
  наполняет бот при каждом отчёте (`sheets.log_calls`). Считаются только смены, по
  которым отчёт есть: за забытый отчёт норма не штрафуется, это вопрос дисциплины.
- **Дегустации — число по бланкам + результат из Битрикса.** Бланк дегустации
  превращается в сделку воронки «Дегустации», ответственный в ней — сам менеджер,
  поэтому считаем прямо по сделкам. Качественной считается дегустация, у которой
  результат зафиксирован, то есть сделка ушла со стадий «Новая дегустация» и
  «РАЗОБРАТЬ!!!», и не закрыта как «Не вышли на ЛПР» (в условиях требуется ЛПР).
  Норма — 6 в каждую неделю месяца, за неполную неделю пропорционально сменам.

Запуск:  venv/bin/python individual_kpi.py              — показать расчёт
         venv/bin/python individual_kpi.py --apply      — записать в СВОДНУЮ
         venv/bin/python individual_kpi.py --month "Октябрь 2026"
"""
from __future__ import annotations

import argparse
import datetime
import logging
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)

EMPLOYEE = "Виолетта Караханова"
# Срок действия индивидуальных условий (по файлу — с 01.10.2026 по 30.11.2026).
PERIODS = ("Октябрь 2026", "Ноябрь 2026")

CALLS_AVG_NORM = 30        # в среднем за смену
CALLS_MIN_NORM = 25        # ни одной смены ниже
TASTINGS_PER_WEEK = 6      # качественных дегустаций в неделю
SHIFTS_PER_WEEK = 5        # полная неделя, от неё считается пропорция

PLAN_PERSONAL = 250_000    # личный план (100% ступени); ступени — доли от него
STEPS = ((1.00, 60_000), (0.85, 45_000), (0.70, 30_000))
PART_SHARE = 0.3           # выполнена одна норма из двух

# Стадии воронки «Дегустации», при которых результат НЕ зафиксирован.
# NEW — «Новая дегустация», UC_ZX1F5K — «РАЗОБРАТЬ!!!», "5" — «Не вышли на ЛПР».
STAGES_NO_RESULT = {"NEW", "UC_ZX1F5K", "5"}


# ── чистая логика (тестируется без сети) ─────────────────────────────────────

def calls_norm(day_calls: dict[int, int]) -> tuple[float, int, bool]:
    """{день: звонков} → (среднее, минимум, норма выполнена).

    Пустой журнал — норма не выполнена: нечем подтвердить.
    """
    if not day_calls:
        return 0.0, 0, False
    vals = list(day_calls.values())
    avg = sum(vals) / len(vals)
    low = min(vals)
    return avg, low, avg >= CALLS_AVG_NORM and low >= CALLS_MIN_NORM


def week_key(d: datetime.date) -> datetime.date:
    """Понедельник недели, в которую попал день."""
    return d - datetime.timedelta(days=d.weekday())


def tastings_norm(quality_days: list[datetime.date],
                  shift_days: list[datetime.date]) -> tuple[dict, bool]:
    """Качественные дегустации по неделям против нормы.

    Норма недели — 6, но за неполную неделю пропорционально сменам: если смен
    было 3 из 5, нужно 6×3/5 = 3,6, то есть 4 дегустации. Недели без смен
    (отпуск, начало работы) в расчёт не идут вовсе.
    """
    done = defaultdict(int)
    for d in quality_days:
        done[week_key(d)] += 1
    shifts = defaultdict(int)
    for d in shift_days:
        shifts[week_key(d)] += 1

    weeks = {}
    for wk, n_shifts in sorted(shifts.items()):
        need = TASTINGS_PER_WEEK * min(n_shifts, SHIFTS_PER_WEEK) / SHIFTS_PER_WEEK
        weeks[wk] = {"shifts": n_shifts, "done": done.get(wk, 0),
                     "need": need, "ok": done.get(wk, 0) >= need}
    ok = bool(weeks) and all(w["ok"] for w in weeks.values())
    return weeks, ok


def bonus_step(turnover: float, plan: float = PLAN_PERSONAL) -> tuple[float, float]:
    """Оборот новых клиентов → (доля личного плана, база ступени)."""
    for share, amount in STEPS:
        if plan and turnover >= plan * share:
            return share, float(amount)
    return 0.0, 0.0


def individual_bonus(turnover: float, calls_ok: bool, tastings_ok: bool,
                     plan: float = PLAN_PERSONAL) -> dict:
    """Итог индивидуального бонуса с раскладкой «почему столько»."""
    share, base = bonus_step(turnover, plan)
    if not base:
        part, amount = 0.0, 0.0
    elif calls_ok and tastings_ok:
        part, amount = 1.0, base
    elif calls_ok or tastings_ok:
        part, amount = PART_SHARE, math.trunc(base * PART_SHARE)
    else:
        part, amount = 0.0, 0.0
    return {"turnover": turnover, "plan": plan, "step_share": share,
            "step_base": base, "part": part, "amount": float(amount),
            "calls_ok": calls_ok, "tastings_ok": tastings_ok}


# ── чтение живых данных ──────────────────────────────────────────────────────

def _month_bounds(month_label: str) -> tuple[datetime.date, datetime.date]:
    from sheets import _parse_period
    m, y = _parse_period(month_label)
    first = datetime.date(y, m, 1)
    last = datetime.date(y + (1 if m == 12 else 0), m % 12 + 1, 1) - datetime.timedelta(days=1)
    return first, last


def _norm_name(name: str) -> str:
    """«Караханова Виолетта» и «Виолетта  Караханова» — один человек."""
    return " ".join(sorted(re.sub(r"[^\w\s]", " ", str(name or "")).lower().split()))


def read_calls(ss, month_label: str, employee: str = EMPLOYEE) -> dict[int, int]:
    """Лист ЗВОНКИ → {день: звонков всего} за месяц по сотруднику."""
    import gspread
    try:
        ws = ss.worksheet("ЗВОНКИ")
    except gspread.WorksheetNotFound:
        logger.warning("листа ЗВОНКИ ещё нет — бот наполняет его с 15.10.2026")
        return {}
    want_month = month_label.strip().lower()
    want_who = _norm_name(employee)
    out = {}
    for r in ws.get_all_values()[1:]:
        if len(r) < 4 or r[0].strip().lower() != want_month:
            continue
        if _norm_name(r[2]) != want_who:
            continue
        day = re.sub(r"\D", "", r[1])
        calls = re.sub(r"\D", "", r[3])
        if day and calls:
            out[int(day)] = int(calls)
    return out


def read_shift_days(ss, month_label: str, employee: str = EMPLOYEE) -> list[int]:
    """Дни, за которые в листе смен стоит ставка (значит смена была)."""
    from sheets import HEADER_ROW
    sheet = "СМЕНЫ"
    for candidate in ("СМЕНЫ", "СМЕНЫ_СЛЕД"):
        try:
            ws = ss.worksheet(candidate)
        except Exception:
            continue
        if (ws.acell("A2").value or "").strip().lower() == month_label.strip().lower():
            sheet = candidate
            break
    ws = ss.worksheet(sheet)
    rows = ws.get_all_values()
    header = rows[HEADER_ROW - 1] if len(rows) >= HEADER_ROW else []
    want = _norm_name(employee)
    for r in rows:
        if len(r) > 1 and _norm_name(r[1]) == want:
            days = []
            for i, cell in enumerate(r):
                if i >= len(header):
                    break
                d = re.sub(r"\D", "", header[i])
                if d and str(cell).strip():
                    days.append(int(d))
            return days
    logger.warning("в листе %s нет строки сотрудника %r", sheet, employee)
    return []


def read_tastings(month_label: str, employee: str = EMPLOYEE) -> tuple[list, list]:
    """Сделки воронки «Дегустации» за месяц → (все даты, качественные даты)."""
    import rop_board as rb
    first, last = _month_bounds(month_label)
    deals = rb.fetch_deals()
    users = rb.fetch_users({d.get("ASSIGNED_BY_ID") for d in deals
                            if d.get("ASSIGNED_BY_ID")})
    want = _norm_name(employee)
    all_days, quality_days = [], []
    for d in deals:
        who = users.get(d.get("ASSIGNED_BY_ID"), "")
        if _norm_name(who) != want:
            continue
        created = str(d.get("DATE_CREATE") or "")[:10]
        try:
            day = datetime.date.fromisoformat(created)
        except ValueError:
            continue
        if not (first <= day <= last):
            continue
        all_days.append(day)
        if str(d.get("STAGE_ID")) not in STAGES_NO_RESULT:
            quality_days.append(day)
    return all_days, quality_days


def collect(month_label: str, employee: str = EMPLOYEE) -> dict:
    """Все входы и итог за месяц — то, что печатается и пишется в СВОДНУЮ."""
    from sync_odata import _open_spreadsheet
    ss = _open_spreadsheet()
    first, _ = _month_bounds(month_label)

    calls = read_calls(ss, month_label, employee)
    avg, low, calls_ok = calls_norm(calls)

    shift_days = read_shift_days(ss, month_label, employee)
    shift_dates = [first.replace(day=d) for d in shift_days]
    all_t, quality_t = read_tastings(month_label, employee)
    weeks, tastings_ok = tastings_norm(quality_t, shift_dates)

    turnover = _turnover_new(ss, employee, month_label)
    result = individual_bonus(turnover, calls_ok, tastings_ok)
    result.update({"month": month_label, "employee": employee,
                   "calls": calls, "calls_avg": avg, "calls_min": low,
                   "shifts": len(shift_days), "weeks": weeks,
                   "tastings_all": len(all_t), "tastings_quality": len(quality_t),
                   "active": month_label.strip() in PERIODS})
    return result


def _turnover_new(ss, employee: str, month_label: str = "") -> float:
    """Оборот новых клиентов за месяц — лист НОВЫЕ_КЛИЕНТЫ, как в СВОДНОЙ.

    ⚠️Лист хранит ТОЛЬКО расчётный месяц (НАСТРОЙКИ!B4): при закрытии месяца его
    чистят. Поэтому для другого месяца цифру не выдумываем — возвращаем 0 и
    предупреждаем, иначе расчёт молча считал бы чужой месяц (поймал на себе
    15.10.2026: запросил октябрь, получил сентябрьские 24 915).
    """
    if month_label:
        period = (ss.worksheet("НАСТРОЙКИ").acell("B4").value or "").strip()
        if period.lower() != month_label.strip().lower():
            logger.warning("лист НОВЫЕ_КЛИЕНТЫ хранит %r, а расчёт запрошен за %r — "
                           "оборот новых клиентов за этот месяц взять негде",
                           period, month_label)
            return 0.0
    want = _norm_name(employee)
    total = 0.0
    for r in ss.worksheet("НОВЫЕ_КЛИЕНТЫ").get("A4:H203"):
        if len(r) < 7 or _norm_name(r[2] if len(r) > 2 else "") != want:
            continue
        num = re.sub(r"[^\d,.-]", "", str(r[6] or "")).replace(",", ".")
        try:
            total += float(num or 0)
        except ValueError:
            pass
    return total


def report_text(res: dict) -> str:
    """Человеческий отчёт: видно, какая норма не взята и почему столько денег."""
    rub = lambda v: f"{int(round(v)):,}".replace(",", " ")
    lines = [f"ИНДИВИДУАЛЬНЫЕ УСЛОВИЯ — {res['employee']}, {res['month']}"]
    if not res["active"]:
        lines.append(f"⚠️ месяц вне срока условий ({PERIODS[0]} – {PERIODS[-1]})")
    lines += [
        "",
        f"Оборот новых клиентов: {rub(res['turnover'])} из {rub(res['plan'])} "
        f"({res['turnover'] / res['plan'] * 100:.0f}% личного плана)",
        f"Ступень: {'нет' if not res['step_base'] else rub(res['step_base'])}"
        + (f" (от {int(res['step_share'] * 100)}% плана)" if res["step_base"] else ""),
        "",
        f"Звонки: смен с отчётом {len(res['calls'])}, в среднем "
        f"{res['calls_avg']:.1f} (норма {CALLS_AVG_NORM}), минимум {res['calls_min']} "
        f"(норма не ниже {CALLS_MIN_NORM}) → {'✅ выполнено' if res['calls_ok'] else '❌ нет'}",
    ]
    lines.append(f"Дегустации: всего {res['tastings_all']}, из них с результатом "
                 f"{res['tastings_quality']} → "
                 f"{'✅ выполнено' if res['tastings_ok'] else '❌ нет'}")
    for wk, w in res["weeks"].items():
        mark = "✅" if w["ok"] else "❌"
        lines.append(f"   {mark} неделя с {wk.strftime('%d.%m')}: "
                     f"{w['done']} из {w['need']:.1f} (смен {w['shifts']})")
    share = {1.0: "100% (обе нормы)", PART_SHARE: "30% (одна норма)"}.get(res["part"], "0")
    lines += ["", f"ИНДИВИДУАЛЬНЫЙ БОНУС: {rub(res['amount'])} ₽ — {share}"]
    return "\n".join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="расчётный месяц (по умолчанию из НАСТРОЕК)")
    ap.add_argument("--employee", default=EMPLOYEE)
    ap.add_argument("--apply", action="store_true",
                    help="записать результат в блок сотрудника в СВОДНОЙ")
    args = ap.parse_args()

    month = args.month
    if not month:
        from sync_odata import _open_spreadsheet
        month = (_open_spreadsheet().worksheet("НАСТРОЙКИ").acell("B4").value or "").strip()
    res = collect(month, args.employee)
    print(report_text(res))
    if args.apply:
        print("\n⚠️ запись в СВОДНУЮ появится вместе с блоком индивидуальных условий "
              "(его заводим после закрытия сентября)")


if __name__ == "__main__":
    main()
