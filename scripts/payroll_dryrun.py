#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОГОН зарплаты (read-only).

Читает факты из живых Google-таблиц, считает ЗП каждого сотрудника по правилам
из docs/СТАВКИ_и_KPI.md и ПЕЧАТАЕТ подробную разбивку в консоль.
НИЧЕГО не пишет обратно в таблицы — это калькулятор для сверки перед записью.

Запуск:  python scripts/payroll_dryrun.py
Требует: credentials.json в корне репо.
"""
import os
import sys
from collections import defaultdict
from datetime import date

import gspread
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# ID таблиц
# ─────────────────────────────────────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID") or "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo"
KPI_ID = "1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4"
KPI_SHEET = "май-июнь"   # лист KPI-таблицы, где лежат данные за июнь

# ═════════════════════════════════════════════════════════════════════════════
# ⚙️  ВВОД ВРУЧНУЮ — заполни за июнь и перезапусти прогон
#     (нули = «ещё не введено», в итоге видно, чего не хватает)
# ═════════════════════════════════════════════════════════════════════════════
# --- KPI Влады (финальные суммы за месяц, см. раздел 4 справочника) ---
VLADA = {
    "hr":          0,      # БЛОК 1 HR: сумма бонусов за приём (20к план / +5к / +20к / 10к / 20к)
    "smm_salary":  25000,  # БЛОК 2 SMM: оклад за операционку (обычно 25000)
    "smm_bonus":   0,      # БЛОК 2 SMM: премия 90%+ плана контента (0 или 5000)
    "smm_clients": 0,      # БЛОК 2 SMM: за клиентов (А:7000 / В:4000 / С:2000 за каждого)
    "projects":    0,      # БЛОК 3 Проекты: премия за сроки (финальное число)
    "logistics":   0,      # БЛОК 4 Логистика: администрирование (макс 10000, финальное число)
}

# --- РОП Блок 4: поступления оплат, факт за июнь (Анна вставляет вручную;
#     на июль подключим ADesk). 0 = не введено → авто-сумма из ДАННЫЕ показана как справка. ---
ROP_FACT_PAYMENTS = 0

# ═════════════════════════════════════════════════════════════════════════════

# ─── Группы сотрудников (подтверждено по колонкам F/G листа ДАННЫЕ, 2026-07-07) ───
EMPLOYEE_GROUP = {
    "Дарья Вольнова":        "poisk",
    "Ксения Наныкина":       "poisk",
    "Валерия Папоян":        "poisk",
    "Лианна Багдасарян":     "poisk",          # уволена в конце июня, считаем и уберём после закрытия
    "Алена Черкашина":       "soprovozhdenie",
    "Валерия Абрамова":      "soprovozhdenie",
    "Владислава Герасимчук": "vlada",
    "Анна Кононенко (РОП)":  "rop",
}
# Имя менеджера поиска в KPI-таблице (колонка) → ФИО в СМЕНАХ/ДАННЫХ
KPI_COL_TO_MANAGER = {
    "Менеджер Дарья":  "Дарья Вольнова",
    "Менеджер Ксения": "Ксения Наныкина",
    "Менеджер Лера":   "Валерия Папоян",
    "Менеджер Лианна": "Лианна Багдасарян",
}

SHIFT_RATE = {
    "poisk":          {"weekday": 2500, "weekend": None},   # поиск в выходные не работает
    "soprovozhdenie": {"weekday": 2500, "weekend": 1800},
    "vlada":          {"weekday": 3000, "weekend": 0},
    "rop":            {"weekday": 5000, "weekend": 5000},
}
VLADA_SIDE_FLAT = {"weekday": 2500, "weekend": 2000}

PLAN_POISK = 210000
KPI_TABLE_POISK = [
    (50, 5000, 0.01), (70, 10000, 0.02), (100, 15000, 0.03),
    (115, 25000, 0.03), (130, 35000, 0.05), (150, 45000, 0.05), (200, 60000, 0.07),
]

EXCLUDE_TYPES = {"Конкурент", "Конкуренты", "Закупки", "Закупка"}
POISK5 = {"Дарья Вольнова", "Ксения Наныкина", "Лианна Багдасарян",
          "Валерия Папоян", "Прямой клиент"}

FLAGS = []   # предупреждения/допущения — печатаются в конце


def kpi_poisk(plan_pct):
    fix, pct = 0.0, 0.0
    for thr, f, p in KPI_TABLE_POISK:
        if plan_pct >= thr:
            fix, pct = float(f), p
    return fix, pct


def kpi_rop_block(plan, fact):
    if plan <= 0:
        return 0.0
    pct = fact / plan * 100
    if pct < 70:
        return 0.0
    return round(fact * 0.01) if pct >= 100 else round(fact * 0.007)


def kpi_rop_premium(plan, fact):
    if plan <= 0:
        return 0.0
    return 10000.0 if fact / plan * 100 >= 115 else 0.0


def num(s):
    s = (s or "").replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if s in ("", "-", "—", "#ERROR!"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def rub(x):
    return f"{x:,.0f}".replace(",", " ")


def parse_period(label):
    """'Июнь 2026' → (year, month)."""
    months = {"январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
              "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12}
    parts = label.lower().split()
    m = next((months[p] for p in parts if p in months), None)
    y = next((int(p) for p in parts if p.isdigit()), date.today().year)
    return y, m


def day_type_for(year, month, day):
    try:
        return "weekend" if date(year, month, day).weekday() >= 5 else "weekday"
    except ValueError:
        return "weekday"


# ─────────────────────────────────────────────────────────────────────────────
def main():
    creds = "credentials.json"
    if not os.path.exists(creds):
        sys.exit("Нет credentials.json в корне репо — доступ к таблицам невозможен.")
    gc = gspread.service_account(filename=creds)
    sh = gc.open_by_key(SPREADSHEET_ID)

    st = sh.worksheet("НАСТРОЙКИ")
    period_label = st.acell("B4").value or "Июнь 2026"
    year, month = parse_period(period_label)
    plan_new = num(st.acell("C13").value)      # новые продажи
    plan_pay = num(st.acell("C14").value)      # поступления
    plan_turn = num(st.acell("C15").value)     # оборот

    print("═" * 74)
    print(f"  ПРОГОН ЗАРПЛАТЫ — {period_label}   (read-only, в таблицы не пишется)")
    print("═" * 74)

    # ── 1. СМЕНЫ: база + подработки ──────────────────────────────────────────
    smeny = sh.worksheet("СМЕНЫ").get_all_values()
    # найти строку-заголовок дней и разделы
    day_cols = {}   # индекс колонки → номер дня
    header_row = None
    for i, r in enumerate(smeny):
        if r and r[0].strip() == "№" and any(c.strip().isdigit() for c in r[4:]):
            header_row = i
            for ci in range(4, len(r)):
                if r[ci].strip().isdigit():
                    day_cols[ci] = int(r[ci].strip())
            break

    def find_section(title_sub):
        for i, r in enumerate(smeny):
            if r and title_sub in r[0].upper():
                return i
        return None

    osn_start = find_section("ОСНОВНЫЕ")
    pod_start = find_section("ПОДРАБОТ")

    base = defaultdict(float)       # факт по ячейкам листа
    base_recalc = defaultdict(float)  # пересчёт по ставкам
    shifts_cnt = defaultdict(int)
    side = defaultdict(float)

    def iter_people(start):
        """строки с ФИО от start+1 до пустой строки/след. раздела."""
        for i in range(start + 1, len(smeny)):
            r = smeny[i]
            name = r[1].strip() if len(r) > 1 else ""
            if r and r[0].strip() and ("СМЕН" in r[0].upper() or "ПОДРАБОТ" in r[0].upper()):
                break
            if not name or name.lower() in ("сотрудник",):
                continue
            yield i, r

    # ОСНОВНЫЕ смены
    for i, r in iter_people(osn_start):
        name = r[1].strip()
        if name == "№":
            continue
        grp = EMPLOYEE_GROUP.get(name)
        for ci, dnum in day_cols.items():
            val = num(r[ci]) if ci < len(r) else 0.0
            if val <= 0:
                continue
            base[name] += val
            shifts_cnt[name] += 1
            if grp:
                dt = day_type_for(year, month, dnum)
                rate = SHIFT_RATE[grp][dt]
                if rate is None:
                    FLAGS.append(f"{name}: смена {dnum:02d}.{month:02d} в ВЫХОДНОЙ, но группа «поиск» "
                                 f"в выходные не работает (в листе стоит {rub(val)}).")
                    base_recalc[name] += val
                else:
                    base_recalc[name] += rate
                    if abs(rate - val) > 0.5:
                        FLAGS.append(f"{name}: день {dnum:02d} — в листе {rub(val)}, "
                                     f"по ставке ({grp}/{dt}) ожидалось {rub(rate)}.")

    # ПОДРАБОТКИ
    if pod_start is not None:
        for i, r in iter_people(pod_start):
            name = r[1].strip()
            if name == "№":
                continue
            for ci, dnum in day_cols.items():
                val = num(r[ci]) if ci < len(r) else 0.0
                if val <= 0:
                    continue
                side[name] += val
                if EMPLOYEE_GROUP.get(name) == "vlada":
                    dt = day_type_for(year, month, dnum)
                    exp = VLADA_SIDE_FLAT[dt]
                    if abs(exp - val) > 0.5:
                        FLAGS.append(f"Влада подработка {dnum:02d}.{month:02d} ({dt}): в листе {rub(val)}, "
                                     f"ожидалось {rub(exp)}.")

    # ── 2. Факты из ДАННЫЕ (оборот, поступления) ─────────────────────────────
    spr = sh.worksheet("СПРАВОЧНИК").get_all_values()
    typ = {r[0].strip(): (r[3].strip() if len(r) > 3 else "")
           for r in spr[3:] if r and r[0].strip()}

    turn_all = turn_clean = pay_total = 0.0
    pay_by_poisk = defaultdict(float)
    for tab in ("ДАННЫЕ_Губарев", "ДАННЫЕ_Перфильев"):
        for r in sh.worksheet(tab).get_all_values()[3:]:
            if len(r) < 7:
                continue
            name = r[0].strip()
            c, d, f = num(r[2]), num(r[3]), r[5].strip()
            turn_all += c
            if typ.get(name, "") not in EXCLUDE_TYPES:
                turn_clean += c
            pay_total += d
            if f in POISK5:
                pay_by_poisk[f] += d

    if not any(t in typ.values() for t in EXCLUDE_TYPES if t != "Конкурент"):
        FLAGS.append("В СПРАВОЧНИК!D нет типа «Закупки» — из оборота вычтены только «Конкурент». "
                     "Если закупки есть под другим типом — уточнить.")

    # ── 3. Факты из KPI-таблицы (новые продажи) ──────────────────────────────
    kpi_rows = gc.open_by_key(KPI_ID).worksheet(KPI_SHEET).get_all_values()
    kpi_hdr = kpi_rows[0]
    kpi_col = {h.strip(): ci for ci, h in enumerate(kpi_hdr)}
    fact_new_sales = 0.0
    itog_ci = kpi_col.get("ИТОГ")
    if itog_ci is not None:
        fact_new_sales = sum(num(r[itog_ci]) for r in kpi_rows[1:] if itog_ci < len(r))
    # оборот по новым клиентам на каждого менеджера поиска (его колонка)
    poisk_new_by_mgr = {}
    mgrsum_check = 0.0
    for col_name, mgr in KPI_COL_TO_MANAGER.items():
        ci = kpi_col.get(col_name)
        if ci is not None:
            s = sum(num(r[ci]) for r in kpi_rows[1:] if ci < len(r))
            poisk_new_by_mgr[mgr] = s
            mgrsum_check += s
    FLAGS.append("KPI поиск «% от оплат»: доля считается от ВСЕХ поступлений менеджера "
                 "(ДАННЫЕ кол. D по его контрагентам). Если премия должна идти только с оплат "
                 "по НОВЫМ клиентам — суммы KPI поиска сильно завышены, надо уточнить базу.")
    # все колонки менеджеров F..(перед ИТОГ) — для проверки расхождения с M
    allmgr = 0.0
    for ci in range(5, itog_ci if itog_ci else len(kpi_hdr)):
        allmgr += sum(num(r[ci]) for r in kpi_rows[1:] if ci < len(r))
    if itog_ci and allmgr > fact_new_sales * 1.3:
        FLAGS.append(f"KPI «{KPI_SHEET}»: сумма колонок по менеджерам = {rub(allmgr)}, "
                     f"а ИТОГ (M) = {rub(fact_new_sales)} (~в {allmgr/fact_new_sales:.1f}× меньше). "
                     f"Блок 2 РОП взят по M «ИТОГ» — проверить, что это верный факт новых продаж.")

    # ── ВЫВОД по сотрудникам ─────────────────────────────────────────────────
    grand = 0.0
    order = list(EMPLOYEE_GROUP.keys())
    everyone = order + [n for n in set(list(base) + list(side)) if n not in order]

    for name in everyone:
        grp = EMPLOYEE_GROUP.get(name, "?")
        b, s_ = base.get(name, 0.0), side.get(name, 0.0)
        if b == 0 and s_ == 0 and name not in EMPLOYEE_GROUP:
            continue
        print(f"\n┌─ {name}   [{grp}]")
        print(f"│  Смены: {shifts_cnt.get(name,0)} осн.  База (лист): {rub(b):>10}   "
              f"пересчёт: {rub(base_recalc.get(name, b)):>10}")
        if s_:
            print(f"│  Подработки: {rub(s_):>10}")
        emp_total = b + s_

        if grp == "poisk":
            fact = poisk_new_by_mgr.get(name, 0.0)
            payments = pay_by_poisk.get(name, 0.0)
            pct = round(fact / PLAN_POISK * 100, 1)
            fix, share = kpi_poisk(pct)
            kpi_pay = round(payments * share)
            print(f"│  KPI поиск: оборот по новым {rub(fact)} = {pct}% плана 210 000")
            print(f"│            фикс-бонус {rub(fix)} + {share*100:.0f}% от поступлений "
                  f"{rub(payments)} = {rub(kpi_pay)}")
            emp_total += fix + kpi_pay

        elif grp == "vlada":
            smm = VLADA["smm_salary"] + VLADA["smm_bonus"] + VLADA["smm_clients"]
            vtot = VLADA["hr"] + smm + VLADA["projects"] + VLADA["logistics"]
            print(f"│  KPI Влады [ВРУЧНУЮ]: HR {rub(VLADA['hr'])} + SMM {rub(smm)} + "
                  f"Проекты {rub(VLADA['projects'])} + Логистика {rub(VLADA['logistics'])} = {rub(vtot)}")
            if vtot == smm and VLADA["hr"] == 0:
                print("│            ⚠ похоже входы Влады ещё не заполнены (только оклад SMM)")
            emp_total += vtot

        elif grp == "rop":
            fact_pay = ROP_FACT_PAYMENTS
            b2 = kpi_rop_block(plan_new, fact_new_sales) + kpi_rop_premium(plan_new, fact_new_sales)
            b3 = kpi_rop_block(plan_turn, turn_clean)
            b4 = kpi_rop_block(plan_pay, fact_pay)
            print(f"│  Блок 2 новые продажи: факт {rub(fact_new_sales)} / план {rub(plan_new)} "
                  f"= {fact_new_sales/plan_new*100:.0f}% → {rub(b2)}")
            print(f"│  Блок 3 оборот:        факт {rub(turn_clean)} / план {rub(plan_turn)} "
                  f"= {turn_clean/plan_turn*100:.0f}% → {rub(b3)}")
            if fact_pay:
                print(f"│  Блок 4 поступления:   факт {rub(fact_pay)} / план {rub(plan_pay)} "
                      f"= {fact_pay/plan_pay*100:.0f}% → {rub(b4)}")
            else:
                print(f"│  Блок 4 поступления:   [ВРУЧНУЮ, не введено]  "
                      f"справка авто по 5 менеджерам: {rub(sum(pay_by_poisk.values()))}")
            emp_total += b2 + b3 + b4

        print(f"└─ ИТОГО: {rub(emp_total)} ₽")
        grand += emp_total

    print("\n" + "═" * 74)
    print(f"  ФОНД ЗП ЗА {period_label.upper()}:  {rub(grand)} ₽")
    print("═" * 74)

    # ── Справка по общим фактам ──────────────────────────────────────────────
    print("\nОБЩИЕ ФАКТЫ (из живых таблиц):")
    print(f"  Оборот (ДАННЫЕ C) всего:            {rub(turn_all)}")
    print(f"  Оборот без конкурентов/закупок:     {rub(turn_clean)}  (Блок 3)")
    print(f"  Поступления (ДАННЫЕ D) всего:       {rub(pay_total)}")
    print(f"  Поступления по 5 менеджерам:        {rub(sum(pay_by_poisk.values()))}  (справка для Блока 4)")
    print(f"  Новые продажи KPI «ИТОГ» (M):       {rub(fact_new_sales)}  (Блок 2)")

    if FLAGS:
        print("\n⚠ ФЛАГИ / ДОПУЩЕНИЯ (проверить перед записью):")
        for i, f in enumerate(dict.fromkeys(FLAGS), 1):   # уникальные, с порядком
            print(f"  {i}. {f}")
    print("\n(Прогон завершён. В таблицы ничего не записано.)")


if __name__ == "__main__":
    main()
