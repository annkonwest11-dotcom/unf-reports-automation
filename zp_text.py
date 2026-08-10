#!/usr/bin/env python3
"""Генератор текста расчёта ЗП по всем сотрудникам — в том формате, в котором Анна
рассылает его людям (⭕️ЗП <ИМЯ> ЗА <МЕСЯЦ>⭕️ … ИТОГ).

Всё берётся из живой таблицы: компоненты — из блоков листа СВОДНАЯ_ЗП, авансы и
остаток к выплате — из «ТАБЛИЦЫ ВЫПЛАТ» внизу того же листа, факт оплат без вычета
беби-листов — из листов ДАННЫЕ (колонка D против скорректированной J).

Блоки и строки ищутся ПО ПОДПИСЯМ, а не по номерам строк: раскладка СВОДНОЙ уже
не раз сдвигалась (удаление сотрудника двигает всё ниже), номера бы устарели.

Запуск:  venv/bin/python zp_text.py                  — показать тексты
         venv/bin/python zp_text.py --send           — отправить их Анне в Telegram
         venv/bin/python zp_text.py --only Алена     — только по одному человеку
"""
import argparse
import os
import re
import sys
from html import escape

import requests
from dotenv import load_dotenv

from sync_odata import (BASES, DATA_START_ROW, _open_spreadsheet, _parse_settings_period)

MONTHS = ["ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ",
          "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ"]

# как человека зовут в сообщении (в таблице — полное ФИО)
SHORT = {
    "Дарья Вольнова": "ДАРЬЯ",
    "Ксения Наныкина": "КСЕНИЯ",
    "Валерия Папоян": "ВАЛЕРИЯ",
    "Алена Черкашина": "АЛЁНА",
    "Владислава Герасимчук": "ВЛАДА",
    "Анна Кононенко (РОП)": "АННА (РОП)",
}


def num(x):
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x or "").replace("\xa0", "").replace(" ", "").replace(",", ".").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def rub(x):
    """Суммы внутри строк — как их пишет Анна: 42336, без разделителей."""
    return f"{int(round(x))}"


def big(x):
    """Крупные числа (базы, планы, ИТОГ) — с пробелами: 4 233 645,02."""
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return s[:-3] if s.endswith(",00") else s


def pct(x):
    return f"{x * 100:.0f}%"


def shifts_word(n):
    n = int(n)
    tail, tens = n % 10, n % 100
    if tens in range(11, 15) or tail in (0, 5, 6, 7, 8, 9):
        return "смен"
    return "смена" if tail == 1 else "смены"


class Sheet:
    """Лист СВОДНАЯ_ЗП: доступ к блокам сотрудников по подписям строк."""

    def __init__(self, grid):
        self.grid = [(r or []) + [""] * (8 - len(r or [])) for r in grid]

    def find(self, text, col=0, start=0):
        for i in range(start, len(self.grid)):
            if text.lower() in str(self.grid[i][col]).lower():
                return i
        return -1

    def block(self, full_name):
        """Строки блока сотрудника: от его заголовка до «ИТОГО ЗП — …».

        Ищем ОТ строки «ИТОГО ЗП» вверх: имя встречается ещё и в сводке наверху листа,
        и поиск сверху захватывал бы вместе с блоком человека весь предыдущий блок.
        """
        end = self.find(f"ИТОГО ЗП — {full_name}")
        if end < 0:
            raise RuntimeError(f"не нашёл «ИТОГО ЗП — {full_name}» в СВОДНОЙ")
        head = -1
        for i in range(end - 1, -1, -1):
            if full_name.lower() in str(self.grid[i][0]).lower():
                head = i
                break
        if head < 0:
            raise RuntimeError(f"не нашёл заголовок блока «{full_name}» в СВОДНОЙ")
        return self.grid[head:end + 1], num(self.grid[end][2])

    @staticmethod
    def row(block, label):
        """Строка блока по подписи в колонке A → (C, D, E, B-подпись).

        Точное совпадение подписи важнее вхождения: в блоке РОП есть и «Бонус»,
        и «Бонус %», и «Бонус (ставка по %плана…)» — поиск по подстроке путал их.
        """
        low = label.strip().lower()
        for exact in (True, False):
            for r in block:
                a = str(r[0]).strip().lower()
                if (a == low) if exact else (low in a):
                    return num(r[2]), num(r[3]), num(r[4]), str(r[1])
        return 0.0, 0.0, 0.0, ""

    def payments(self):
        """{ФИО: (итого, аванс_карта, аванс_нал, зп_карта, остаток_нал)}."""
        start = self.find("ТАБЛИЦА ВЫПЛАТ")
        out = {}
        for r in self.grid[start + 2:]:
            name = str(r[0]).strip()
            if not name or name == "ИТОГО":
                if name == "ИТОГО":
                    break
                continue
            out[name] = tuple(num(r[i]) for i in range(1, 6))
        return out


def fact_by_manager(ss):
    """{ФИО: (сырые оплаты, скорр. оплаты)} — по колонкам D и J листов ДАННЫЕ.

    Нужно, чтобы показать факт ДО вычета беби-листов: в СВОДНОЙ лежит только
    величина после вычета (J), а в тексте Анна называет обе.
    Ключи: менеджер поиска (F), сопровождение (G, только тип «Ресторан»),
    и «ВСЕ РЕСТОРАНЫ» — база бонусов РОП.
    """
    out = {}
    for cfg in BASES.values():
        for r in ss.worksheet(cfg["sheet_name"]).get(
                "A1:L600", value_render_option="UNFORMATTED_VALUE")[DATA_START_ROW - 1:]:
            r = (r or []) + [""] * (12 - len(r or []))
            if not str(r[0]).strip():
                continue
            d, j = num(r[3]), num(r[9])
            f, g, h = (str(r[5]).strip(), str(r[6]).strip(), str(r[7]).strip())
            keys = []
            if f:
                keys.append(f)
            if g and h == "Ресторан":
                keys.append(g)
            if h == "Ресторан":
                keys.append("ВСЕ РЕСТОРАНЫ")
            for k in keys:
                cur = out.setdefault(k, [0.0, 0.0])
                cur[0] += d
                cur[1] += j
    return out


def line(sign, amount, comment):
    return f"{sign}{rub(amount)} ({comment})"


def build_search(sh, name, month, facts, pay, new_plan_setting=0.0):
    """Менеджер поиска: смены + KPI по новым клиентам + % от всех оплат."""
    block, total = sh.block(name)
    shifts, cnt, _, _ = sh.row(block, "Смены")
    pays, _, _, _ = sh.row(block, "Оплаты (все клиенты)")
    new_fact, _, _, _ = sh.row(block, "Оплаты (новые клиенты)")
    plan_pct, _, _, _ = sh.row(block, "% выполнения плана")
    fix, _, _, _ = sh.row(block, "Фикс.бонус")
    rate, _, _, _ = sh.row(block, "% от оплат (ставка)")
    bonus, _, _, _ = sh.row(block, "Бонус % от оплат")
    stories, _, _, _ = sh.row(block, "сторис")
    contest, _, _, _ = sh.row(block, "Конкурс")
    extra, _, extra_e, _ = sh.row(block, "Дополнительная премия")
    _, _, _, note = sh.row(block, "Комментарий к доп.премии")
    extra = extra or extra_e

    raw, adj = facts.get(name, (pays, pays))
    new_plan = new_plan_setting or (round(new_fact / plan_pct) if plan_pct else 0)

    out = [f"⭕️ЗП {SHORT[name]} ЗА {month} ⭕️", line("+", shifts, f"{int(cnt)} {shifts_word(cnt)} × 2500")]
    if raw - adj > 1:
        out.append(f"⭕️Оплаты клиентов {big(raw)} (без вычета беби), "
                   f"в расчёт ЗП {big(adj)} (вычет −{big(raw - adj)})")
    else:
        out.append(f"⭕️Оплаты клиентов {big(pays)}")
    out.append(f"⭕️Новые клиенты {big(new_fact)} из {big(new_plan)} — "
               f"{pct(plan_pct)} выполнения плана")
    if fix:
        out.append(line("+", fix, f"фикс. бонус KPI за {pct(plan_pct)} плана"))
    else:
        out.append("фикс. бонус KPI — 0 (план по новым клиентам ниже 50%)")
    if bonus:
        out.append(line("+", bonus, f"{pct(rate)} от оплат клиентов"))
    else:
        out.append("% от оплат — 0 (ставка начинается с 50% плана)")
    if stories:
        out.append(line("+", stories, "ведение сторис"))
    if contest:
        out.append(line("+", contest, "конкурс"))
    if extra:
        out.append(line("+", extra, note.strip() or "премия"))
    return finish(out, total, name, pay)


def build_support(sh, name, month, facts, pay, plan):
    """Менеджер сопровождения: смены + подработки + 1% операц. + 1% за план."""
    block, total = sh.block(name)
    shifts, cnt_main, cnt_extra, _ = sh.row(block, "Смены")
    base, _, _, _ = sh.row(block, "Оплаты ресторанов")
    plan_pct, _, _, _ = sh.row(block, "% выполнения плана")
    oper, _, _, _ = sh.row(block, "KPI рестораны — операц")
    plan_bonus, _, _, _ = sh.row(block, "KPI рестораны — план")
    extra, _, extra_e, _ = sh.row(block, "Дополнительная премия")
    _, _, _, note = sh.row(block, "Комментарий к доп.премии")
    extra = extra or extra_e

    raw, _ = facts.get(name, (base, base))
    office = cnt_main * 2500

    out = [f"⭕️ЗП {SHORT[name]} ЗА {month} ⭕️",
           line("+", office, f"{int(cnt_main)} {shifts_word(cnt_main)} офис")]
    if shifts - office:
        out.append(line("+", shifts - office, "подработка в будни и выходные"))
    out += [f"⭕️План на месяц {big(plan)}, факт {big(raw)} (без вычета беби) "
            f"({pct(plan_pct)} выполнения плана), итог с вычетом беби {big(base)} файл ниже 👇",
            line("+", oper, "1% от оплат клиентов")]
    if plan_bonus:
        out.append(line("+", plan_bonus,
                        f"1% от оплат клиентов за выполнение плана на {pct(plan_pct)}"))
    if extra:
        out.append(line("+", extra, note.strip() or "премия"))
    return finish(out, total, name, pay)


def build_rop(sh, name, month, pay, plans):
    """РОП: смены + подработки + три блока KPI (новые продажи, оборот, поступления)."""
    block, total = sh.block(name)
    shifts, cnt, _, _ = sh.row(block, "Смены")
    extra_work, _, _, _ = sh.row(block, "Подработки")
    _, _, new_fact, _ = sh.row(block, "Факт — новые продажи")
    new_pct, _, _, _ = sh.row(block, "% выполнения плана — новые продажи")
    new_bonus, _, _, _ = sh.row(block, "Бонус %")
    prem115, _, _, _ = sh.row(block, "Премия 115%")
    _, _, ob_fact, _ = sh.row(block, "Факт — оборот")
    ob_pct, _, _, _ = sh.row(block, "% выполнения плана — оборот")
    ob_bonus, _, _, _ = sh.row(block, "Бонус")
    _, _, pos_fact, _ = sh.row(block, "Факт — поступления")
    pos_pct, _, _, _ = sh.row(block, "% выполнения плана — поступления")
    # в этой же строке колонка E — база «оплаты ресторанов», от которой считают бонус
    pos_bonus, _, rest_base, _ = sh.row(block, "Бонус (ставка по %плана")
    extra, _, extra_e, _ = sh.row(block, "Дополнительная премия")
    _, _, _, note = sh.row(block, "Комментарий к доп.премии")
    extra = extra or extra_e

    out = [f"⭕️ЗП {SHORT[name]} ЗА {month} ⭕️",
           line("+", shifts, f"{int(cnt)} {shifts_word(cnt)} × 5000")]
    if extra_work:
        out.append(line("+", extra_work, "подработки в выходные"))
    out.append(f"⭕️Новые продажи {big(new_fact)} из {big(plans['new'])} — {pct(new_pct)} плана")
    if new_bonus:
        out.append(line("+", new_bonus, f"бонус за новые продажи ({pct(new_pct)} плана)"))
    else:
        out.append("бонус за новые продажи — 0 (порог 70% плана)")
    if prem115:
        out.append(line("+", prem115, "премия за 115% плана"))
    out.append(f"⭕️Оборот {big(ob_fact)} из {big(plans['oborot'])} — {pct(ob_pct)} плана")
    if ob_bonus:
        out.append(line("+", ob_bonus,
                        f"0,7% от оплат ресторанов {big(rest_base)} за оборот"))
    out.append(f"⭕️Поступления {big(pos_fact)} из {big(plans['post'])} — {pct(pos_pct)} плана")
    if pos_bonus:
        out.append(line("+", pos_bonus,
                        f"0,7% от оплат ресторанов {big(rest_base)} за поступления"))
    if extra:
        out.append(line("+", extra, note.strip() or "премия"))
    return finish(out, total, name, pay)


def build_helper(sh, name, month, pay):
    """Помощник руководителя: смены + подработки + SMM + HR + проекты + логистика."""
    block, total = sh.block(name)
    shifts, cnt, _, _ = sh.row(block, "Смены")
    extra_work, _, _, _ = sh.row(block, "Подработки")
    smm, _, _, _ = sh.row(block, "Оклад SMM")
    content, _, _, _ = sh.row(block, "Премия за контент")
    clients, _, _, _ = sh.row(block, "Клиенты SMM")
    hire_plan, _, _, _ = sh.row(block, "Бонус за план найма")
    projects, _, _, _ = sh.row(block, "Премия за проекты")
    logistics, _, _, _ = sh.row(block, "KPI администрирование")
    extra, _, extra_e, _ = sh.row(block, "Дополнительная премия")
    _, _, _, note = sh.row(block, "Комментарий к доп.премии")
    extra = extra or extra_e
    hires = sum(sh.row(block, lbl)[0] for lbl in
                ("Найм: менеджер (7 раб. дней)", "Найм: менеджер (месяц)",
                 "Найм: производство", "Найм: водитель"))

    out = [f"⭕️ЗП {SHORT[name]} ЗА {month} ⭕️",
           line("+", shifts, f"{int(cnt)} {shifts_word(cnt)} × 3000")]
    if extra_work:
        out.append(line("+", extra_work, "подработки в будни и выходные"))
    if smm:
        out.append(line("+", smm, "оклад SMM"))
    if content:
        out.append(line("+", content, "премия за контент"))
    if clients:
        out.append(line("+", clients, "клиенты SMM"))
    if hires:
        out.append(line("+", hires, "найм"))
    if hire_plan:
        out.append(line("+", hire_plan, "бонус за план найма"))
    if projects:
        out.append(line("+", projects, "премия за проекты"))
    if logistics:
        out.append(line("+", logistics, "KPI администрирование (логистика)"))
    if extra:
        out.append(line("+", extra, note.strip() or "премия"))
    return finish(out, total, name, pay)


def finish(out, total, name, pay):
    """Хвост сообщения: авансы, ИТОГ и пометка про официальную часть.

    Здесь же самопроверка: сумма всех «+…» строк обязана сойтись с ИТОГО из таблицы.
    Если в блок сотрудника добавят новый компонент, а сюда его не заведут, текст
    молча разойдётся с расчётом — поэтому лучше громко предупредить, чем разослать.
    """
    parts = sum(int(re.match(r"^\+(\d+) ", s).group(1))
                for s in out if re.match(r"^\+\d+ ", s))
    if abs(parts - total) > 1:
        warn = (f"⚠️ сумма строк {rub(parts)} ≠ ИТОГО в таблице {rub(total)} — "
                f"в блоке «{name}» есть компонент, который генератор не показывает")
        print(warn, file=sys.stderr)
        out.append(warn)

    _, av_card, av_cash, zp_card, rest = pay.get(name, (total, 0, 0, 0, total))
    if av_card and av_cash:
        out.append(f"−{rub(av_card + av_cash)} аванс "
                   f"({rub(av_card)} на карту + {rub(av_cash)} наличными)")
    elif av_card or av_cash:
        out.append(f"−{rub(av_card + av_cash)} аванс")
    # официальную часть показываем строкой, как аванс: ИТОГ берётся из колонки
    # «Остаток 10 — наличными», где она уже вычтена, — без этой строки в тексте
    # получалась необъяснённая дырка между «начисления − аванс» и ИТОГом
    if zp_card:
        out.append(f"−{rub(zp_card)} официальная зарплата на карту")
    out += ["", f"ИТОГ {big(rest)}"]
    if not zp_card:
        out.append("")
        out.append("(официальная зарплата — добавим 10-го, когда будут данные)")
    return "\n".join(out)


def build_texts(ss=None):
    """{ФИО: текст расчёта} по всем сотрудникам. Отсюда же берёт бот для команды /zp."""
    ss = ss or _open_spreadsheet()
    sh = Sheet(ss.worksheet("СВОДНАЯ_ЗП").get("A1:H140", value_render_option="UNFORMATTED_VALUE"))
    settings = ss.worksheet("НАСТРОЙКИ").get("A1:D30", value_render_option="UNFORMATTED_VALUE")
    period = _parse_settings_period(ss)
    month = MONTHS[period[1] - 1] if period else ""

    def setting(who, what):
        """План из НАСТРОЕК по паре «кому (A) + показатель (B)».

        Точное совпадение показателя первым: у РОП есть и «Оплаты (план)», и
        «Новые клиенты — оплаты (план)» — по вхождению они путаются.
        """
        low = what.strip().lower()
        for exact in (True, False):
            for r in settings:
                r = (r or []) + [""] * 3
                b = str(r[1]).strip().lower()
                if who.lower() in str(r[0]).lower() and ((b == low) if exact else (low in b)):
                    return num(r[2])
        return 0.0

    facts = fact_by_manager(ss)
    pay = sh.payments()
    plans = {"alena": setting("Алена Черкашина", "Оплаты ресторанов"),
             "search": setting("Менеджеры поиска", "Оборот новых клиентов"),
             "new": setting("РОП", "Новые клиенты"),
             "oborot": setting("РОП", "Оборот"),
             "post": setting("РОП", "Оплаты (план)")}

    texts = {}
    for name in ("Дарья Вольнова", "Ксения Наныкина", "Валерия Папоян"):
        texts[name] = build_search(sh, name, month, facts, pay, plans["search"])
    texts["Алена Черкашина"] = build_support(sh, "Алена Черкашина", month, facts, pay,
                                             plans["alena"])
    texts["Анна Кононенко (РОП)"] = build_rop(sh, "Анна Кононенко (РОП)", month, pay, plans)
    texts["Владислава Герасимчук"] = build_helper(sh, "Владислава Герасимчук", month, pay)
    return texts


def official_zp_ready(ss=None):
    """True, если официальная ЗП («ЗП 9 — на карту») уже проставлена.

    Её заполняет sync_avansy из ADesk 9-10 числа. До этого в текстах стоит
    пометка «официальная зарплата — добавим 10-го».
    """
    ss = ss or _open_spreadsheet()
    sh = Sheet(ss.worksheet("СВОДНАЯ_ЗП").get("A1:H140", value_render_option="UNFORMATTED_VALUE"))
    return any(vals[3] for vals in sh.payments().values())


def department_summary(ss=None):
    """Сводка по отделу — как «ТАБЛИЦА ВЫПЛАТ» в самой таблице (формат Анны):
    колонки Итого / Аванс на карту / Аванс наличными / ЗП на карту / Остаток наличными.

    Возвращает HTML: моноширинный <pre>, иначе колонки в Telegram разъедутся.
    """
    ss = ss or _open_spreadsheet()
    sh = Sheet(ss.worksheet("СВОДНАЯ_ЗП").get("A1:H140", value_render_option="UNFORMATTED_VALUE"))
    period = _parse_settings_period(ss)
    month = MONTHS[period[1] - 1] if period else ""
    pay = sh.payments()

    def col(x):
        return f"{x:,.0f}".replace(",", " ") if x else "0"

    rows, totals = [], [0.0] * 5
    for name, vals in pay.items():
        if not any(vals):
            continue
        rows.append((SHORT.get(name, name.split()[0]), vals))
        for i in range(5):
            totals[i] += vals[i]

    width = max([len(r[0]) for r in rows] + [len("ИТОГО")])
    head = (f"{'':<{width}} {'Итого':>9} {'Ав.карта':>9} {'Ав.нал':>9} "
            f"{'ЗП карта':>9} {'Нал 10':>9}")
    body = [f"{n:<{width}} {col(v[0]):>9} {col(v[1]):>9} {col(v[2]):>9} "
            f"{col(v[3]):>9} {col(v[4]):>9}" for n, v in rows]
    total_line = (f"{'ИТОГО':<{width}} {col(totals[0]):>9} {col(totals[1]):>9} "
                  f"{col(totals[2]):>9} {col(totals[3]):>9} {col(totals[4]):>9}")

    table = "\n".join([head, "─" * len(head)] + body + ["─" * len(head), total_line])
    fot = num(sh.grid[sh.find("ИТОГО ФОТ ЗА МЕСЯЦ")][2]) if sh.find("ИТОГО ФОТ") >= 0 else totals[0]
    out = [f"📋 ТАБЛИЦА ВЫПЛАТ — {month}", "", f"<pre>{escape(table)}</pre>", "",
           f"💰 ФОТ ЗА МЕСЯЦ: {big(fot)} ₽"]
    if not totals[3]:
        out.append("Официальная ЗП («ЗП 9 — на карту») ещё не проставлена.")
    return "\n".join(out)


def cash_summary(ss=None):
    """Отдельное сообщение: сколько кому отдать наличными 10 числа и общий итог.

    Это колонка «Остаток 10 — наличными» таблицы выплат = ИТОГО минус авансы
    (и минус официальная часть, когда она проставлена)."""
    ss = ss or _open_spreadsheet()
    sh = Sheet(ss.worksheet("СВОДНАЯ_ЗП").get("A1:H140", value_render_option="UNFORMATTED_VALUE"))
    period = _parse_settings_period(ss)
    month = MONTHS[period[1] - 1] if period else ""
    pay = sh.payments()

    lines = [f"💵 ИТОГО 10 ЧИСЛА — НАЛИЧНЫМИ ({month})", ""]
    total = 0.0
    for name, vals in pay.items():
        if not vals[0]:
            continue
        rest = vals[4]
        total += rest
        note = "  — всё выплачено авансом" if not rest else ""
        lines.append(f"{SHORT.get(name, name)}: {big(rest)}{note}")
    fot = num(sh.grid[sh.find("ИТОГО ФОТ ЗА МЕСЯЦ")][2]) if sh.find("ИТОГО ФОТ") >= 0 else 0.0
    lines += ["", f"ВСЕГО НАЛИЧНЫМИ: {big(total)} ₽", f"ФОТ ЗА МЕСЯЦ: {big(fot)} ₽"]
    if not any(v[3] for v in pay.values()):
        lines.append("")
        lines.append("(официальная зарплата ещё не проставлена — суммы уменьшатся, "
                     "когда она придёт 10-го)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Тексты расчёта ЗП по сотрудникам")
    ap.add_argument("--send", action="store_true", help="отправить Анне в Telegram")
    ap.add_argument("--only", help="только по одному человеку (часть имени)")
    args = ap.parse_args()

    texts = build_texts()
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    token, chat = os.getenv("BOT_TOKEN"), os.getenv("ANNA_CHAT_ID")
    for name, text in texts.items():
        if args.only and args.only.lower() not in name.lower():
            continue
        print("─" * 60)
        print(text)
        if args.send:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat, "text": text}, timeout=60)
            print("  → отправлено" if r.json().get("ok") else f"  → ошибка: {r.text[:150]}")
    return texts


if __name__ == "__main__":
    sys.exit(0 if main() else 0)
