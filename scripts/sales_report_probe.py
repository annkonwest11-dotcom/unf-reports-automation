# -*- coding: utf-8 -*-
"""Разведка отчёта по продажам: новые и вернувшиеся клиенты за месяц по 1С.

Черновик будущего `sales_report.py`. Считает то, что Анна ведёт руками в таблице
«ОТЧЕТЫ ПО ПРОДАЖАМ» (лист на месяц, последний — «июль-август»):
  • НОВЫЙ    — первая в истории расходная накладная попала в отчётный месяц;
  • ВЕРНУЛИ  — заказ после молчания ≥28 дней. ★Решение Анны от 27.08.2026: считаем
               по ГОЛОМУ МОЛЧАНИЮ, личный ритм клиента в условии не участвует. Раньше
               требовалось молчание вдвое длиннее ритма — так не проходил ЧЕМОДАН
               (30 дней тишины при ритме 19). Обратная сторона решения: клиент,
               берущий раз в месяц (ОТДЫХ Щелково — 13 заказов по 2 880 раз в 3–4
               недели без пропусков), попадает в возвраты почти каждый месяц.
               Ритм по-прежнему считается и печатается — но только для справки;
  • СУММА    — отгружено за 30 дней от события, обрезанное границей месяца:
               что попало до 31-го — в лист этого месяца, хвост — в следующий
               (правило Анны от 24.08.2026).

Запуск:  python3 scripts/sales_report_probe.py [ГГГГ-ММ]

★Склейка карточек-двойников тут СВОЯ, шире общей `sync_odata.group_same_client`:
добавлены «сбис» в шум, срез пометки «НЕ ВЕРНЫЙ / ЕСТЬ 2-Й / ДУБЛЬ» и группы из
трёх и более карточек. В `sync_odata` не вносил: расширение задевает дебиторку
и ритм (например, «Peshi Приёмка 1..4» станут одной строкой) — сперва проверить.
"""

import re
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, "/Users/anna/claude-test")
import sync_odata as so

RETURN_GAP = 28        # молчание, после которого заказ считается возвратом
WINDOW_DAYS = 30       # сколько дней клиент считается в отчёт
HISTORY_FROM = "2023-01-01"

# Пометка менеджеров на заброшенной карточке: «НЕ ВЕРНЫЙ ЕСТЬ 2-Й», «дубль», «не использовать»
_JUNK_TAIL = re.compile(r"\s*(?:не\s*вер\w*|не\s*исп\w*|дубл\w*)\b.*$", re.I)
# Хвосты, которые к названию дописывают в 1С и которые клиента не различают
_TAILS = re.compile(r"\s*(эдо|dsbx|сбис|в\s*1с|счет|счёт|нал|перевод|адрес\s*доставки)\b[\s/!,]*", re.I)


def key_tokens(name):
    """Различающие слова имени — без пометки о заброшенной карточке и без «сбис»."""
    return (so.name_tokens(_JUNK_TAIL.sub("", str(name or ""))) - {"сбис"}) - so._GENERIC_WORDS


def group_cards(names):
    """{каноническое имя: [карточки этого клиента]}.

    Класс эквивалентности — одинаковый набор различающих слов. Карточки с РАЗНЫМИ
    длинными номерами (телефонами) внутри класса разводим: номер различает клиента.
    """
    by_key = {}
    for n in names:
        t = key_tokens(n)
        if t:
            by_key.setdefault(t, []).append(n)
    groups = {}
    for members in by_key.values():
        nums = {n: so._long_numbers(n) for n in members}
        if len({frozenset(v) for v in nums.values() if v}) > 1:
            buckets = {}
            for n in members:
                buckets.setdefault(frozenset(nums[n]) or ("free", n), []).append(n)
            for b in buckets.values():
                groups[canonical(b)] = b
        else:
            groups[canonical(members)] = members
    for n in names:
        if not key_tokens(n):
            groups.setdefault(n, [n])
    return groups


def canonical(members):
    """Имя, под которым клиент в ходу: не заброшенное и не с пометкой о переводе."""
    return min(members, key=lambda n: (bool(_JUNK_TAIL.search(n)),
                                       bool(so._TRANSFER_TAIL.search(n)), -len(n)))


def load_history(since=HISTORY_FROM):
    """{канон: [(дата, сумма)]} по расходным накладным обеих баз."""
    docs, names_seen = [], set()
    for base in so.BASES.values():
        names = so._contractor_names(base["id"])
        names_seen.update(v for v in names.values() if v)
        entity = ("Document_РасходнаяНакладная"
                  f"?$filter=Date ge datetime'{since}T00:00:00' and Posted eq true"
                  "&$select=Date,Контрагент_Key,СуммаДокумента")
        for r in so._fetch_odata(base["id"], entity):
            nm = names.get(r.get("Контрагент_Key"))
            if nm:
                docs.append((nm, datetime.strptime(r["Date"][:19], "%Y-%m-%dT%H:%M:%S").date(),
                             float(r.get("СуммаДокумента") or 0)))
    canon = {m: c for c, ms in group_cards(sorted(names_seen)).items() for m in ms}
    hist = defaultdict(list)
    for nm, d, s in docs:
        hist[canon.get(nm, nm)].append((d, s))
    for k in hist:
        hist[k].sort()
    return hist


def personal_rhythm(items, until, lookback=180):
    """Медиана интервалов между заказами за полгода по дату `until` включительно.

    На классификацию не влияет (см. ВЕРНУЛИ в заголовке модуля) — показывается
    в выводе, чтобы было видно, насколько молчание выбивается из привычек клиента.
    """
    days = sorted({d for d, _ in items if until - timedelta(days=lookback) <= d <= until})
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return statistics.median(gaps) if len(gaps) >= 2 else None


def month_bounds(ym):
    y, m = (int(x) for x in ym.split("-"))
    start = date(y, m, 1)
    end = (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
    return start, end


def classify(hist, ym):
    """[{клиент, вид, дата события, сумма в этом месяце, хвост, ...}] за месяц ym."""
    m_start, m_end = month_bounds(ym)
    out = []
    for cli, items in hist.items():
        in_month = [i for i in items if m_start <= i[0] <= m_end]
        if not in_month:
            continue
        first_ever, first_now = items[0][0], in_month[0][0]
        before = [i for i in items if i[0] < m_start]
        prev = before[-1][0] if before else None
        if first_ever >= m_start:
            kind, event, gap, rhythm = "новый", first_ever, None, None
        elif prev:
            gap = (first_now - prev).days
            rhythm = personal_rhythm(items, prev)   # только для справки в выводе
            if gap < RETURN_GAP:
                continue
            kind, event = "вернули", first_now
        else:
            continue
        win_end = event + timedelta(days=WINDOW_DAYS - 1)
        this_month = round(sum(s for d, s in items
                               if max(event, m_start) <= d <= min(win_end, m_end)), 2)
        whole = round(sum(s for d, s in items if event <= d <= win_end), 2)
        out.append(dict(client=cli, kind=kind, event=event, window_end=win_end,
                        amount=this_month, tail_next_month=round(whole - this_month, 2),
                        gap=gap, rhythm=rhythm, orders=len(in_month)))
    out.sort(key=lambda r: (r["kind"] != "новый", r["event"]))
    return out


if __name__ == "__main__":
    ym = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m")
    rows = classify(load_history(), ym)
    print(f"\n{ym}: новых {sum(1 for r in rows if r['kind'] == 'новый')}, "
          f"вернувшихся {sum(1 for r in rows if r['kind'] == 'вернули')}\n")
    for r in rows:
        why = ""
        if r["kind"] == "вернули":
            why = f"молчал {r['gap']} дн." + (f" при ритме {r['rhythm']:g}" if r["rhythm"] else "")
        tail = f"  (хвост след. месяца {r['tail_next_month']:,.0f})" if r["tail_next_month"] else ""
        print(f"{r['kind']:<8}{r['event']:%d.%m}  {r['client'][:46]:<46}"
              f"{r['amount']:>11,.0f}  по {r['window_end']:%d.%m}  {why}{tail}")
