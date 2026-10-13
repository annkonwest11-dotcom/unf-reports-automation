# -*- coding: utf-8 -*-
"""Отчёт по продажам: новые и вернувшиеся клиенты за месяц → таблица «ОТЧЕТЫ ПО ПРОДАЖАМ».

Боевой скрипт вместо разведочного `scripts/sales_report_probe.py` (тот теперь тонкая
обёртка над этим модулем, чтобы правила жили в одном месте). ТЗ — лист
«ТЗ — отчёт по продажам» таблицы «ТЗ АВТОМАТИЗАЦИИ», ответы Анны от 12.10.2026.

## Как устроен лист (проверено на живых листах 12.10.2026)

Лист месяца M называется «<месяц M-1>-<месяц M>» («сентябрь-октябрь» — это ОКТЯБРЬ,
так же его читает `sync_novye.MONTH_TO_KPI_SHEET`). В листе строки событий ДВУХ
месяцев — M-1 и M, — а сумма в строке — отгрузки, попавшие в месяц M внутри
30-дневного окна события. Сверка 12.10: РУБЕЛЬ (ООО АВА ЦЕНТР), событие 11.09,
в листе 5 472 — ровно октябрьская часть окна 11.09–10.10 по 1С.

## Правила (решения Анны, даты — когда приняты)

1. **Новый** (12.10) — бланк «ПЕРВЫЙ ЗАКАЗ» от менеджера: вносим сразу, менеджер
   берётся из автора бланка. Кого 1С видит новым БЕЗ бланка (первая в истории
   расходная накладная попала в месяц) — не вносим молча, а отдаём Анне на
   подтверждение кнопкой в MAX.
2. **Вернувшийся** (31.08 + 12.10) — бланк «ВОЗВРАЩЁННЫЙ КЛИЕНТ»: вносим сразу.
   Остальных, кто похож на возврат (заказ после молчания ≥28 дней, `RETURN_GAP`), —
   Анне в личку по каждому. Порога, который отделил бы возврат от редкого ровного
   ритма, не существует (ОТДЫХ Щелково: 13 заказов по 2 880 раз в 3–4 недели без
   пропусков) — решает бланк или слово Анны.
3. **Разовый** (12.10) — подвид нового. В конце месяца список новых и вернувшихся
   месяца с ОДНИМ заказом уходит Анне, она подтверждает кнопкой, и в колонке D
   ставится «разовая». Старых клиентов с редким ритмом в этот список не берём.
4. **Окно** (12.10) — 30 дней от события: у нового это первый заказ, у вернувшегося —
   тот заказ, которым он вернулся. Колонка E = дата события + 30 дней.
5. **Граница месяца** (24.08) — окно режется месяцем: часть окна внутри месяца M
   идёт в лист месяца M, хвост — в лист следующего месяца.
6. **Сумма** (12.10) — отгружено (не оплачено) по расходным накладным ТРЁХ баз:
   Губарев 64904, Перфильев 152757, Володихина 184621.
7. **Вычет за салаты** (01.09 + 12.10) — клиенту, который берёт салатов больше 4 кг
   (40 упаковок по 100 гр) за МЕСЯЦ, в ячейку идёт сумма минус 40% от оборота
   салатов, попавшего в окно. Шисо 100 гр, базилик 100 гр и цветы («Хрустальная
   трава 100 гр») салатами не считаются. В ячейку — число, расчёт — в примечании.
8. **Менеджер** (12.10) — из автора бланка. Если бланк прислала Алёна, в поиск идёт
   «прямой клиент», а сумма — в колонку Алёны.
9. **Один клиент** (12.10) — одно название и одно юрлицо. Дубли карточек 1С за
   разные названия НЕ считаем (хвосты ЭДО/нал/сбис/дубль, опечатки: «ПРИЧАЛ ЧАРЛИ
   ООО КОМПЛЕКС» и «причал чарли нал( комлекс) ООО» — один клиент). Одно юрлицо с
   РАЗНЫМИ названиями — разные клиенты (ЛУЖНИКИ и МАГАДАН — оба ООО ВОСТОК), как и
   одно название на разных юрлицах («Стейк ит изи» — пять юрлиц).
10. **Расхождение с 1С** (12.10) — сумму, поставленную человеком, скрипт не
    переписывает: пишет Анне, она решает. Свои суммы (помеченные примечанием)
    пересчитывает сам.
11. **Личный ритм** (27.08 + 12.10) — в вердикт не входит, идёт справкой в
    сообщении Анне: «молчал 30 дней при обычном ритме 19». В листе ИСКЛЮЧЕНИЯ
    колонка «Личный ритм (недель)» задаёт порог вручную; слово «авто» — считать от
    ритма самого клиента по 1С плюс 3 недели (ООО ГЛАВТОРГ, решение Анны 12.10).
12. **Прочерк = менеджер** (12.10) — прочерк в колонке менеджера значит «клиент мой,
    сумма ещё не посчитана»: так заполнен весь лист. Сумму ставим в эту колонку, не
    спрашивая. Если прочерков два или их нет и бланка нет — спрашиваем Анну.
13. **Юрлицо** (12.10) — в колонку B пишем, на какое юрлицо реально идут отгрузки по
    1С (если Анна её не заполнила), а в примечание — все карточки клиента с числом
    накладных и датой последней. Так видно, что «Рыба моя» ездит на четыре юрлица.
14. **База 1С** (12.10) — колонка «База 1С» ТРЕТЬЕЙ, рядом с юрлицом (просьба Анны):
    из какой нашей базы грузим клиента (Губарев, Перфильев, Володихина), каждая
    своим цветом; клиент из двух баз — сиреневым, обе базы в ячейке. Из-за этой
    вставки позиции колонок в листах разных месяцев разъехались, поэтому все
    колонки ищем по ШАПКЕ (`sheet_columns`), а не по номерам. Тот же лист читают
    `sync_novye` (классификация) и `rop_board` (колонки менеджеров) — там это
    тоже переведено на шапку.

Запуск:
    python3 sales_report.py                  # текущий месяц, прогон в КОПИЮ листа
    python3 sales_report.py 2026-10          # конкретный месяц
    python3 sales_report.py 2026-10 --dry    # ничего не писать, только показать
    python3 sales_report.py 2026-10 --live   # писать в живой лист (после «ок» Анны)
"""

import json
import logging
import os
import re
import statistics
import sys
from collections import defaultdict
from functools import lru_cache
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

import gspread
from google.oauth2.service_account import Credentials

import sales_ask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_odata as so

logger = logging.getLogger(__name__)

SPREADSHEET_ID = "1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4"   # «ОТЧЕТЫ ПО ПРОДАЖАМ»
CREDENTIALS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

RETURN_GAP = 28        # молчание, после которого клиент попадает в кандидаты на возврат
WINDOW_DAYS = 30       # окно, за которое считаем сумму
HISTORY_FROM = "2023-01-01"

# ── Вычет за салаты (беби-листы), правила Анны 01.09 и 12.10.2026 ────────────
BEBY_RATE = 0.4         # вычитаем 40% от оборота салатов
BEBY_MIN_KG = 4.0       # порог за МЕСЯЦ
BEBY_PACK_KG = 0.1      # фасовка 100 гр
BEBY_GROUP = "Беби листы"
BEBY_MARK = "100 гр"
NOT_BEBY_GROUPS = {"Цветы"}
# ★12.10.2026: «шисо 100гр и базилик 100 гр тоже не считаем» — это зелень, не салат,
# и в порог 4 кг она тоже не идёт.
NOT_BEBY_NAMES = ("шисо", "базилик", "хрустальная трава")

# Листы: месяц → название листа. Проверено по живым листам и совпадает с
# sync_novye.MONTH_TO_KPI_SHEET (там же этот лист читается в зарплату).
_MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь",
           "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

# Колонки листа
COL_RESTAURANT, COL_ENTITY, COL_CREATED, COL_KIND, COL_UNTIL = 1, 2, 3, 4, 5
FIRST_MANAGER_COL = 6   # F
# ★12.10.2026 Анна попросила колонку «База 1С» третьей, рядом с юрлицом, — и позиции
# разъехались: в листах прошлых месяцев её нет. Поэтому колонки ищем по ШАПКЕ, а
# константы выше остались запасным вариантом для листов без нужного заголовка.
COL_PATTERNS = (("restaurant", r"ресторан"), ("entity", r"юр"), ("base", r"база"),
                ("created", r"создан"), ("kind", r"классиф"),
                ("until", r"какого\s*числа|\+\s*30"))
# Заголовок колонки менеджера → кого писать (ключи как в sync_novye.KPI_MANAGERS)
MANAGER_NOTE = "поставлено ботом"   # метка в примечании: эту сумму скрипт вправе пересчитать
DASHES = frozenset({"-", "—", "–"})   # прочерк Анны: «клиент мой, сумма ещё не посчитана»
COL_BASE = 14          # запасное место колонки «База 1С» — для листов, где её нет в шапке
BASE_HEADER = "База 1С"
BASE_TITLES = {"gubarev": "Губарев", "perfilev": "Перфильев", "volodihina": "Володихина"}
# Цвет под каждую базу (просьба Анны «выдели цветами»): пастель, чтобы текст читался
BASE_COLORS = {"gubarev": {"red": 0.84, "green": 0.94, "blue": 0.82},
               "perfilev": {"red": 0.81, "green": 0.89, "blue": 0.97},
               "volodihina": {"red": 1.0, "green": 0.92, "blue": 0.76}}
MIXED_COLOR = {"red": 0.91, "green": 0.86, "blue": 0.97}   # клиент грузится из двух баз
ENTITY_NOTE = "по 1С заказы идут на"  # начало примечания к колонке «Юр лицо»
# Карточка 1С → сколько накладных и когда последняя; заполняет load_history, читает
# entity_marks — из этого делается пометка «кто на какое юрлицо ездит» (просьба Анны 12.10.2026)
CARDS = {}

# Пометка менеджеров на заброшенной карточке: «НЕ ВЕРНЫЙ ЕСТЬ 2-Й», «дубль»
_JUNK_TAIL = re.compile(r"\s*(?:не\s*вер\w*|не\s*исп\w*|дубл\w*)\b.*$", re.I)
# Хвосты, которые к названию дописывают в 1С и которые клиента не различают
_TAILS = re.compile(r"\s*(эдо|dsbx|сбис|в\s*1с|счет|счёт|нал|перевод|адрес\s*доставки)\b[\s/!,]*", re.I)


def month_bounds(ym):
    """'2026-10' → (01.10.2026, 31.10.2026)."""
    y, m = (int(x) for x in ym.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return start, end


def sheet_title(ym):
    """Лист месяца M называется «<месяц M-1>-<месяц M>» («сентябрь-октябрь» = октябрь)."""
    _, m = (int(x) for x in ym.split("-"))
    return f"{_MONTHS[m - 2]}-{_MONTHS[m - 1]}"


def prev_month(ym):
    y, m = (int(x) for x in ym.split("-"))
    return f"{y - (m == 1)}-{12 if m == 1 else m - 1:02d}"


# ── Склейка карточек одного клиента (правило 9) ───────────────────────────────

@lru_cache(maxsize=None)
def key_tokens(name):
    """Различающие слова имени: без мусорных хвостов и пометок о заброшенной карточке.

    ★Кеш обязателен: склейка карточек сравнивает группы парами и спрашивает токены
    одних и тех же имён миллионы раз (2 753 карточки 1С → 62 с без кеша).
    """
    return (so.name_tokens(_JUNK_TAIL.sub("", str(name or ""))) - {"сбис"}) - so._GENERIC_WORDS


@lru_cache(maxsize=None)
def _canonical_key(name):
    """Ключ сортировки канонического имени — считается для каждого имени один раз."""
    return (bool(_JUNK_TAIL.search(name)), bool(so._TRANSFER_TAIL.search(name)), -len(name))


def canonical(members):
    """Имя, под которым клиент в ходу: не заброшенное и не с пометкой о переводе."""
    return min(members, key=_canonical_key)


def _typo(a, b):
    """Названия различаются одной опечаткой: «…КОМПЛЕКС» ↔ «…( комлекс)».

    Слов одинаково, все совпадают кроме одного, и это одно — описка. Так ловятся
    дубли карточек, которые нельзя считать разными названиями (правило 9).
    """
    ta, tb = key_tokens(a), key_tokens(b)
    if not ta or not tb or len(ta) != len(tb):
        return False
    common = ta & tb
    rest_a, rest_b = sorted(ta - common), sorted(tb - common)
    if not common or len(rest_a) != 1 or len(rest_b) != 1:
        return False
    return SequenceMatcher(None, rest_a[0], rest_b[0]).ratio() >= 0.8


def _subset(a, b):
    """Одно название — часть другого: «Причал Чарли нал» ⊂ «причал чарли нал( комлекс)».

    Само по себе это слабый признак: лишнее слово часто и есть НАЗВАНИЕ ТОЧКИ
    («ШЕСТНАДЦАТЬ ТОНН КЕЙТЕРИНГ» ⊂ «ШЕСТНАДЦАТЬ ТОНН ПРЕСНЯ» — разные заведения,
    см. `sync_odata.same_client`). Поэтому вложенность склеивает только тогда,
    когда юрлицо не спорит — см. `_mergeable`.
    """
    ta, tb = key_tokens(a), key_tokens(b)
    return bool(ta) and bool(tb) and (ta < tb or tb < ta)


def _mergeable(g_inns, m_inns, g_name, m_name):
    """Насколько уверенно две группы карточек — один клиент: 2 — точно, 1 — можно, 0 — нет.

    Разные непустые ИНН не склеиваются никогда («ПРИЧАЛ ООО» 5032113800 — это не
    «ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС» 5050057890, хотя название вложено). Вложенность
    принимаем, только если ИНН совпадают или их нет ни у одной стороны (нал-карточки
    одного заведения в разных базах).
    """
    same_inn = bool(g_inns & m_inns)
    if g_inns and m_inns and not same_inn:
        return 0
    if _typo(g_name, m_name):
        return 2
    if _subset(g_name, m_name):
        # у короткого имени ИНН нет — это нал-дубль того же заведения («Причал Чарли
        # нал» в базе Володихиной). Если ИНН есть именно у короткого, это отдельное
        # юрлицо с общим названием, и склеивать нельзя.
        short_inns = g_inns if len(key_tokens(g_name)) < len(key_tokens(m_name)) else m_inns
        if same_inn or not short_inns:
            return 1
    return 0


def group_cards(cards):
    """[(карточка, ИНН)] → {каноническое имя: [карточки]} по правилу 9.

    Сначала класс эквивалентности по различающим словам (как в разведке), потом
    второй проход: группы склеиваются, если названия похожи (опечатка или
    уточнение) и юрлицо не противоречит — см. `_same_entity`. Две карточки с
    РАЗНЫМИ непустыми ИНН не склеиваются никогда («НАЙТСБРИДЖ ООО ( ЧАРЛИ)» —
    это не «ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС»), разные названия у одного ИНН — тоже
    (ЛУЖНИКИ и МАГАДАН — оба ООО ВОСТОК).
    """
    inn_of = {}
    by_key = {}
    for name, inn in cards:
        inn_of[name] = (inn or "").strip()
        t = key_tokens(name)
        if t:
            by_key.setdefault(frozenset(t), []).append(name)

    groups = []
    for members in by_key.values():
        nums = {n: so._long_numbers(n) for n in members}
        if len({frozenset(v) for v in nums.values() if v}) > 1:
            buckets = {}
            for n in members:
                buckets.setdefault(frozenset(nums[n]) or ("free", n), []).append(n)
            groups.extend(buckets.values())
        else:
            groups.append(members)

    # Склейка проходами до стабилизации: группа, объединившись, получает ИНН и
    # новое каноническое имя, и тогда к ней подходит то, что раньше не подходило
    # («Причал Чарли нал» прилипает к паре КОМПЛЕКС/комлекс только вторым проходом).
    merged = [list(g) for g in groups]
    for _ in range(3):
        changed = False
        result, names, inns_of_group = [], [], []
        # ★индекс «токен имени → группы»: сравнивать каждую группу с каждой не нужно.
        # И опечатка, и вложенность требуют общего слова (`_typo` без общих токенов
        # возвращает False, `_subset` — это строгое подмножество непустых множеств),
        # поэтому группы без общего слова заведомо дают 0. На 2 753 карточках 1С это
        # 62 с → меньше секунды, а на сервере прогон переставал укладываться в cron
        index = defaultdict(set)
        for g in merged:
            inns = {inn_of.get(n, "") for n in g} - {""}
            g_name = canonical(g)
            cand = {i for t in key_tokens(g_name) for i in index[t]}
            scored = [(_mergeable(inns, inns_of_group[i], g_name, names[i]), i)
                      for i in cand]
            top = max((s for s, _ in scored), default=0)
            hits = [i for s, i in scored if s == top and s > 0]
            # уверенную склейку (опечатка) берём лучшую, вложенность — только когда
            # кандидат единственный: иначе деньги уйдут соседней точке сети
            if top == 2 or (top == 1 and len(hits) == 1):
                i = hits[0]
                result[i].extend(g)
                # группа, объединившись, получает ИНН и новое каноническое имя —
                # и тогда к ней подходит то, что раньше не подходило
                inns_of_group[i] |= inns
                names[i] = canonical(result[i])
                for t in key_tokens(names[i]):
                    index[t].add(i)
                changed = True
            else:
                result.append(list(g))
                names.append(g_name)
                inns_of_group.append(inns)
                for t in key_tokens(g_name):
                    index[t].add(len(result) - 1)
        merged = result
        if not changed:
            break

    out = {canonical(g): g for g in merged}
    for name, _ in cards:
        if not key_tokens(name):
            out.setdefault(name, [name])
    return out


# ── Данные 1С ────────────────────────────────────────────────────────────────

def _contractors(base_id):
    """{Ref_Key: (название, ИНН)} — ИНН нужен склейке (правило 9)."""
    out = {}
    for c in so._fetch_odata(base_id, "Catalog_Контрагенты"):
        out[c.get("Ref_Key")] = (c.get("Description", ""), c.get("ИНН", ""))
    return out


def load_history(since=HISTORY_FROM, bases=None):
    """({канон: [(дата, сумма)]}, {карточка: канон}) по расходным накладным ТРЁХ баз.

    Выгрузка трёх баз идёт около минуты, поэтому при отладке её можно закешировать:
    `SALES_CACHE=/путь/history.pickle` — первый запуск сохраняет, следующие читают.
    В проде переменная не задана и данные всегда берутся живыми.
    """
    cache = os.environ.get("SALES_CACHE")
    if cache and os.path.exists(cache):
        import pickle
        with open(cache, "rb") as f:
            logger.info("история 1С из кеша %s", cache)
            hist, canon, cards_seen = pickle.load(f)
            CARDS.clear()
            CARDS.update(cards_seen)
            return hist, canon
    docs, cards = [], {}
    for base_key, base in (bases or so.live_bases()).items():
        ctg = _contractors(base["id"])
        for name, inn in ctg.values():
            if name:
                cards[name] = inn
        entity = ("Document_РасходнаяНакладная"
                  f"?$filter=Date ge datetime'{since}T00:00:00' and Posted eq true"
                  "&$select=Date,Контрагент_Key,СуммаДокумента")
        for r in so._fetch_odata(base["id"], entity):
            nm = ctg.get(r.get("Контрагент_Key"), ("", ""))[0]
            if nm:
                docs.append((nm, datetime.strptime(r["Date"][:19], "%Y-%m-%dT%H:%M:%S").date(),
                             float(r.get("СуммаДокумента") or 0), base_key))
    canon = {m: c for c, ms in group_cards(sorted(cards.items())).items() for m in ms}
    hist = defaultdict(list)
    seen = {}
    for nm, d, s, base_key in docs:
        hist[canon.get(nm, nm)].append((d, s))
        rec = seen.setdefault(nm, dict(inn=cards.get(nm, ""), docs=0, last=d, sum=0.0,
                                       canon=canon.get(nm, nm), bases={}))
        rec["docs"] += 1
        rec["sum"] += s
        rec["last"] = max(rec["last"], d)
        rec["bases"][base_key] = rec["bases"].get(base_key, 0) + 1
    for k in hist:
        hist[k].sort()
    CARDS.clear()
    CARDS.update(seen)
    if cache:
        import pickle
        with open(cache, "wb") as f:
            pickle.dump((dict(hist), canon, seen), f)
    return dict(hist), canon


def personal_rhythm(items, until, lookback=180):
    """Медиана интервалов между заказами за полгода — справка в сообщении Анне (правило 11)."""
    days = sorted({d for d, _ in items if until - timedelta(days=lookback) <= d <= until})
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return statistics.median(gaps) if len(gaps) >= 2 else None


def is_beby(name, group):
    """Салат ли это (правило 7).

    Признак тот же, что в `sync_beby.py`: группа «Беби листы» либо фасовка «100 гр»
    в названии (в базе Перфильева те же позиции лежат без группы). ★12.10.2026 Анна:
    шисо 100 гр и базилик 100 гр — не салаты, как и цветы («Хрустальная трава 100 гр»).
    """
    low = (name or "").lower()
    if any(w in low for w in NOT_BEBY_NAMES):
        return False
    return group == BEBY_GROUP or (BEBY_MARK in low and group not in NOT_BEBY_GROUPS)


def beby_items(base_id):
    """{Ref_Key} позиций-салатов базы."""
    nom = so._fetch_odata(base_id, "Catalog_Номенклатура")
    folders = {n["Ref_Key"]: n.get("Description", "") for n in nom if n.get("IsFolder")}
    return {n["Ref_Key"] for n in nom if not n.get("IsFolder")
            and is_beby(n.get("Description"), folders.get(n.get("Parent_Key"), ""))}


def load_beby(ym, canon=None, bases=None):
    """{клиент: [(дата, сумма салатов, упаковок)]} за месяц ym — для вычета (правило 7)."""
    m_start, m_end = month_bounds(ym)
    fmt = "datetime'%Y-%m-%dT00:00:00'"
    lo, hi = m_start.strftime(fmt), (m_end + timedelta(days=1)).strftime(fmt)
    out = defaultdict(list)
    for base in (bases or so.live_bases()).values():
        beby = beby_items(base["id"])
        ctg = _contractors(base["id"])
        docs = so._fetch_odata(
            base["id"],
            f"Document_РасходнаяНакладная?$filter=Date ge {lo} and Date lt {hi} and Posted eq true")
        for d in docs:
            nm = ctg.get(d.get("Контрагент_Key"), ("", ""))[0]
            if not nm:
                continue
            day = datetime.strptime(d["Date"][:19], "%Y-%m-%dT%H:%M:%S").date()
            amount = qty = 0.0
            for line in (d.get("Запасы") or []):
                if line.get("Номенклатура_Key") in beby:
                    amount += float(line.get("Сумма") or 0)
                    qty += float(line.get("Количество") or 0)
            if amount or qty:
                out[(canon or {}).get(nm, nm)].append((day, amount, qty))
    return dict(out)


# ── Классификация и суммы ────────────────────────────────────────────────────

def classify(hist, ym):
    """Строки для листа месяца ym: события месяцев M-1 и M, сумма — часть окна в M.

    Лист месяца M держит события двух месяцев (проверено на живых листах), поэтому
    сентябрьское событие попадает и в октябрьский лист — с октябрьской частью окна.
    Вид события тут — то, что ВИДНО ПО 1С: `новый` (первая накладная в истории) или
    `кандидат` (заказ после молчания ≥28 дней). Вердикт даёт бланк или Анна
    (правила 1–2), поэтому ниже это ещё раз сверяется с бланками.
    """
    m_start, m_end = month_bounds(ym)
    p_start, _ = month_bounds(prev_month(ym))
    out = []
    for cli, items in hist.items():
        events = []
        for i, (d, _) in enumerate(items):
            if d < p_start or d > m_end:
                continue
            if i == 0:
                events.append(("новый", d, None, None))
                continue
            gap = (d - items[i - 1][0]).days
            if gap >= RETURN_GAP:
                events.append(("кандидат", d, gap, personal_rhythm(items, items[i - 1][0])))
        if not events:
            continue
        # В листе у клиента одна строка. Главное событие — то, чьё окно ещё живо в
        # этом месяце: сначала «новый» (клиент считается новым, даже если внутри
        # месяца потом был разрыв), иначе самый свежий возврат. Если все окна уже
        # закрылись, оставляем первое — строка нужна листу с нулём, как у Анны «-».
        alive = [e for e in events if e[1] + timedelta(days=WINDOW_DAYS - 1) >= m_start]
        kind, event, gap, rhythm = (next((e for e in alive if e[0] == "новый"), None)
                                    or (alive[-1] if alive else events[0]))
        win_end = event + timedelta(days=WINDOW_DAYS - 1)
        amount = round(sum(s for d, s in items
                           if max(event, m_start) <= d <= min(win_end, m_end)), 2)
        tail = round(sum(s for d, s in items if d > m_end and d <= win_end), 2)
        orders_in_month = sum(1 for d, _ in items if m_start <= d <= m_end)
        out.append(dict(client=cli, kind=kind, event=event, window_end=win_end,
                        amount=amount, tail_next_month=tail, gap=gap, rhythm=rhythm,
                        orders=orders_in_month, source="1С", manager=None))
    out.sort(key=lambda r: (r["kind"] != "новый", r["event"]))
    return out


def apply_beby(rows, beby):
    """Вычет 40% за салаты сверх 4 кг за месяц (правило 7)."""
    for r in rows:
        sales = beby.get(r["client"], [])
        kg = sum(q for _, _, q in sales) * BEBY_PACK_KG
        in_window = sum(a for d, a, _ in sales if r["event"] <= d <= r["window_end"])
        r["beby_kg"] = round(kg, 2)
        r["beby_amount"] = round(in_window, 2)
        r["amount_gross"] = r["amount"]
        if kg > BEBY_MIN_KG and in_window:
            r["beby_cut"] = round(in_window * BEBY_RATE, 2)
            r["amount"] = round(r["amount"] - r["beby_cut"], 2)
        else:
            r["beby_cut"] = 0.0
    return rows


def money(x):
    """«25 300» — тысячи через пробел.

    Раньше число форматировалось через запятую, а потом во всей строке запятые
    менялись на пробелы — вместе с теми, что стоят в тексте («событие 12.09, окно
    по 11.10» читалось как «12.09  окно»).
    """
    return f"{x:,.0f}".replace(",", " ")


def beby_note(r):
    """Примечание к ячейке с расчётом вычета (просьба Анны 01.09.2026)."""
    if not r.get("beby_cut"):
        return ""
    return (f"{money(r['amount_gross'])} − 40% × {money(r['beby_amount'])} = "
            f"{money(r['amount'])}\n"
            f"салаты: {r['beby_kg']:g} кг за месяц (порог 4 кг)")


def conflict_note(in_sheet, r):
    """Примечание при пересчёте суммы, поставленной человеком.

    ★Решение Анны 12.10.2026 («1 вариант»): отчёт должен сходиться с 1С, поэтому
    сумму ставим свою, а то, что стояло в листе, не теряем — пишем в примечание,
    чтобы было видно, что изменилось. Прогоны при этом идут в КОПИЮ листа: живой
    лист Анна сверяет сама.
    """
    head = (f"было {money(in_sheet)} — стояло в листе\n"
            f"стало {money(r['amount'])} по 1С: событие {r['event']:%d.%m}, "
            f"окно по {r['window_end']:%d.%m}")
    note = beby_note(r)
    return f"{head}\n{note}" if note else head


def one_order_candidates(rows):
    """Кто взял ровно один раз за месяц — список «разовых» Анне на подтверждение (правило 3)."""
    return [r for r in rows if r["orders"] == 1]


# ── Лист отчёта ──────────────────────────────────────────────────────────────

def open_spreadsheet(gc=None):
    if gc is None:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def make_copy(ss, title, today=None):
    """Копия листа для прогона — правило Анны 12.10: сначала копия, живой лист после «ок»."""
    src = ss.worksheet(title)
    stamp = (today or date.today()).strftime("%d.%m")
    new_title = f"{title} КОПИЯ {stamp}"
    for w in ss.worksheets():
        if w.title == new_title:
            ss.del_worksheet(w)
            break
    return src.duplicate(new_sheet_name=new_title, insert_sheet_index=src.index + 1)


def sheet_columns(header):
    """{ключ: номер колонки} по шапке листа; чего в шапке нет — по старым местам."""
    out = {}
    for key, pat in COL_PATTERNS:
        rx = re.compile(pat, re.I)
        col = next((i for i, h in enumerate(header[:8], 1) if rx.search(str(h or ""))), None)
        if col:
            out[key] = col
    out.setdefault("restaurant", COL_RESTAURANT)
    out.setdefault("entity", COL_ENTITY)
    out.setdefault("created", COL_CREATED)
    out.setdefault("kind", COL_KIND)
    out.setdefault("until", COL_UNTIL)
    out.setdefault("base", COL_BASE)
    return out


def manager_columns(header, first_col=None):
    """{номер колонки: ФИО менеджера} по шапке листа (как в sync_novye)."""
    from sync_novye import KPI_MANAGERS, kpi_key
    first_col = first_col or FIRST_MANAGER_COL
    out = {}
    for i, h in enumerate(header, 1):
        key = kpi_key(h)
        if i >= first_col and key in KPI_MANAGERS:
            out[i] = KPI_MANAGERS[key][0]
    return out


def _num(s):
    """«12 127,00» → 12127.0; пустое и «-» → None."""
    s = str(s or "").replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if not s or s in DASHES:
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", s) or 0)
    except ValueError:
        return None


def read_sheet(ws):
    """Строки листа: {row, restaurant, entity, created, kind, until, sums{col: value}}."""
    vals = ws.get_all_values()
    header = vals[0] if vals else []
    cols = sheet_columns(header)
    mcols = manager_columns(header, first_col=cols["until"] + 1)
    rows = []
    for idx, r in enumerate(vals[1:], start=2):
        def cell(i):
            return r[i - 1].strip() if len(r) >= i else ""
        if not cell(cols["restaurant"]):
            continue      # итоговая строка и боковые блоки Анны — там названия нет
        if "итог" in cell(cols["restaurant"]).lower():
            continue
        rows.append(dict(row=idx, restaurant=cell(cols["restaurant"]),
                         entity=cell(cols["entity"]),
                         created=cell(cols["created"]), kind=cell(cols["kind"]),
                         until=cell(cols["until"]),
                         sums={c: _num(cell(c)) for c in mcols},
                         # ★12.10.2026: прочерк в колонке менеджера — пометка Анны «клиент мой,
                         # сумма ещё не посчитана»; так заполнен весь лист, и это единственный
                         # способ узнать менеджера без бланка (правило 12)
                         dashes=[c for c in mcols if cell(c) in DASHES]))
    return dict(header=header, managers=mcols, rows=rows, last_row=len(vals), cols=cols)


# Формы юрлица, по которым кусок названия признаётся юрлицом
_LEGAL = re.compile(r"(?:^|[\s(])(ооо|оао|зао|пао|ао|ип|нао|ано|нко|фгуп|гуп|мбу|тд)(?:[\s.)]|$)", re.I)
_CASH = re.compile(r"\b(нал|физ\s*лиц\w*|наличк\w*)\b", re.I)


# В 1С «ООО» часто набрано латиницей («OOO РЮМКА НА ЛЕСНОЙ») — без этого юрлицо не
# распознаётся; меняем только то слово, которое после замены становится формой юрлица
_HOMO = str.maketrans("OoAaEeCcPpXxYyKkMmHhTtBb", "ОоАаЕеСсРрХхУуКкМмНнТтВв")
_LEGAL_WORD = re.compile(r"(ооо|оао|зао|пао|ао|ип|нао|ано|нко|фгуп|гуп|мбу|тд)$", re.I)


def _fix_legal(s):
    def one(m):
        w = m.group(0)
        t = w.translate(_HOMO)
        return t if _LEGAL_WORD.fullmatch(t) else w
    return re.sub(r"\w+", one, s)


def entity_of(card):
    """Юрлицо из названия карточки 1С — то, что идёт в колонку «Юр лицо».

    «ГВИДОН (ООО КАМЕЛОТ) ЭДО» → «ООО КАМЕЛОТ», «ХОРСА ООО (Красота)» → «ХОРСА ООО»
    (в скобках тут название заведения, а не юрлицо), «Матвей Физ лицо нал сразу» →
    «нал». Если юрлица не видно — пусто: чужую колонку наугад не заполняем.
    """
    name = _fix_legal(re.sub(r"\s+", " ", str(card or "")).strip())
    for part in re.findall(r"\(([^)]*)\)", name):
        if _LEGAL.search(part):
            return part.strip(" .,/")
    outside = re.sub(r"\([^)]*\)", " ", name)
    outside = _TAILS.sub(" ", outside)
    outside = re.sub(r"\s+", " ", outside).strip(" .,/!")
    if _LEGAL.search(outside):
        return outside
    if _CASH.search(name):
        return "нал"
    return ""


def entity_marks(pairs):
    """Чем пометить колонку «Юр лицо» и её примечание (правило 13).

    Одно заведение в 1С часто живёт на нескольких карточках и юрлицах («Рыба моя» —
    МАСА, ПЕРВАЯ РЫБА, РЫБНЫЙ КОРОЛЬ, СЫТОСТЬ), и из листа не видно, на какое именно
    идут отгрузки. Примечание показывает все карточки клиента: накладных и когда
    последняя.
    """
    by_client = defaultdict(list)
    for card, info in CARDS.items():
        by_client[info.get("canon", card)].append(card)
    out = []
    for s, r in pairs:
        cards = sorted(by_client.get(r["client"], []), key=lambda c: -CARDS[c]["docs"])
        if not cards:
            continue
        ents = []
        for c in cards:
            e = entity_of(c)
            if e and e.lower() not in [x.lower() for x in ents]:
                ents.append(e)
        lines = [f"{ENTITY_NOTE}:"]
        for c in cards:
            i = CARDS[c]
            inn = f", ИНН {i['inn']}" if i.get("inn") else ""
            # год показываем, если отгрузка не этого года: «последняя 04.12» про
            # прошлый декабрь читается как будущая дата
            last = i["last"]
            when = (f"{last:%d.%m}" if last.year == date.today().year else f"{last:%d.%m.%Y}")
            lines.append(f"• {c} — {i['docs']} накл., последняя {when}{inn}")
        out.append(dict(row=s["row"], entity=" / ".join(ents), note="\n".join(lines),
                        in_sheet=s["entity"], client=r["client"], cards=cards))
    return out


def base_marks(pairs):
    """Из какой нашей базы грузим клиента — текст и цвет под базу (просьба Анны 12.10.2026).

    Накладные одного ресторана иногда идут из двух баз (переехал на другое ИП или
    часть заказов оформляют у Володихиной) — тогда в ячейке обе базы по убыванию
    числа накладных и отдельный цвет.
    """
    by_client = defaultdict(dict)
    for card, info in CARDS.items():
        client = info.get("canon", card)
        for b, n in (info.get("bases") or {}).items():
            by_client[client][b] = by_client[client].get(b, 0) + n
    out = []
    for s, r in pairs:
        counts = by_client.get(r["client"])
        if not counts:
            continue
        order = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        out.append(dict(row=s["row"],
                        text=" + ".join(BASE_TITLES.get(b, b) for b, _ in order),
                        color=(BASE_COLORS.get(order[0][0]) if len(order) == 1 else MIXED_COLOR),
                        detail=", ".join(f"{BASE_TITLES.get(b, b)} — {n} накл." for b, n in order)))
    return out


def _flat(s):
    """Имя без пробелов и служебных слов — для сверки имён с опечатками."""
    s = so._TRANSFER_TAIL.sub("", str(s or ""))
    s = re.sub(r"[^\w\s]", " ", s.replace("ё", "е").replace("Ё", "Е").lower())
    return "".join(w for w in s.split() if w not in so._NOISE_WORDS)


def match_client(label, index, strict=False):
    """Клиент 1С для строки листа. None — если однозначно не определяется.

    В листе имена короткие и часто с опиской: «Рубель» + «ООО Ава центр» против
    «РУБЕЛЬ (ООО АВА ЦЕНТР)» в 1С, «Просекко Бар» против «ПРОСЕКО БАР (ООО ПР 11)»,
    «Цыпочка» вообще без юрлица. Поэтому три попытки по убыванию строгости, и на
    каждой требуется ЕДИНСТВЕННЫЙ кандидат: лучше оставить строку Анне, чем
    приписать деньги чужому клиенту.
    """
    hit = so.soft_lookup(label, index)
    if hit:
        return hit
    t = so.name_tokens(label)
    if not t or strict:
        return None            # для исключений угадывать нельзя: см. apply_excluded
    nested = {n for ct, n in index if t < ct or ct < t}
    if len(nested) == 1:
        return nested.pop()
    flat = _flat(label)
    if len(flat) >= 8:
        close = {n for ct, n in index
                 if SequenceMatcher(None, flat, _flat(n)).ratio() >= 0.85}
        if len(close) == 1:
            return close.pop()
    # последняя попытка: два общих слова, и хотя бы одно из них редкое. Так
    # «Juan + руби ООО РЕПОСАДО» находит «Juan/Хуан (ООО РЕПОСАДО)», а «Онегин физ
    # лицо нал» не липнет к «Елена физ лицо Северяне нал» — там общее только
    # «физ лицо», которое встречается у десятков карточек.
    freq = defaultdict(int)
    for ct, _ in index:
        for w in ct:
            freq[w] += 1
    rare = {n for ct, n in index
            if len(t & ct) >= 2 and any(freq[w] <= 2 for w in (t & ct))}
    return rare.pop() if len(rare) == 1 else None


def _norm_entity(s):
    """Юрлицо для сравнения: «ООО ПУАССОН» и «Пуассон» — одно и то же."""
    s = re.sub(r"[«»\"'.,/()]", " ", str(s or "").replace("ё", "е")).lower()
    s = re.sub(r"\b(ооо|оао|зао|пао|ао|ип|нао|ано|нко|фгуп|гуп|мбу|тд)\b", " ", s)
    return re.sub(r"\s+", "", s)


def match_by_entity(sheet_entity, allowed=None):
    """Клиент 1С по ЮРЛИЦУ из листа — когда заведение в 1С названо иначе.

    ★12.10.2026: «Шануар» + «ООО ПУАССОН» в 1С зовётся «ПУАССОН КЕЙТЕРИНГ (ООО
    ПУАССОН)», слова «Шануар» там нет вовсе, а по слову «пуассон» кандидатов два
    («Пуассон Кейтеринг (ООО МЕЗОН)») — поэтому обычный поиск отказывался. Берём
    только когда юрлицо совпало РОВНО у одного клиента: одно юрлицо на разных
    названиях (ЛУЖНИКИ и МАГАДАН — оба ООО ВОСТОК) так и останется без ответа.
    """
    want = _norm_entity(sheet_entity)
    if not want or len(want) < 4:
        return None
    hits = set()
    for card, info in CARDS.items():
        client = info.get("canon", card)
        if allowed is not None and client not in allowed:
            continue
        if _norm_entity(entity_of(card)) == want:
            hits.add(client)
    return next(iter(hits)) if len(hits) == 1 else None


def match_rows(calc_rows, sheet):
    """Сопоставление расчёта со строками листа по названию и юрлицу."""
    index = so.build_token_index([r["client"] for r in calc_rows])
    by_client = {r["client"]: r for r in calc_rows}
    pairs, unmatched_sheet = [], []
    taken = set()
    for s in sheet["rows"]:
        hit = match_client(f"{s['restaurant']} {s['entity']}", index)
        if not hit:
            hit = match_by_entity(s["entity"], allowed=set(by_client))
        if hit and hit not in taken:
            taken.add(hit)
            pairs.append((s, by_client[hit]))
        else:
            unmatched_sheet.append(s)
    new_for_sheet = [r for r in calc_rows if r["client"] not in taken]
    return pairs, new_for_sheet, unmatched_sheet


def plan_sheet(calc_rows, sheet, ym, all_clients=None):
    """Что сделать с листом и о чём спросить Анну.

    В лист сам пишу только то, что бесспорно: пустую колонку E и сумму в строку,
    где её ещё нет, если менеджер известен из бланка. Чужие суммы не переписываю —
    расхождение уходит Анне (правило 10), новых без бланка она подтверждает кнопкой
    (правило 1), кандидатов на возврат — тоже (правило 2).
    """
    pairs, new_for_sheet, unmatched = match_rows(calc_rows, sheet)
    upd_until, upd_amount, conflicts, ask, dates = [], [], [], [], []
    filled_info = []
    for s, r in pairs:
        want_until = f"по {r['window_end']:%d.%m}"
        if not s["until"]:
            upd_until.append((s["row"], want_until))
        in_sheet_date = re.search(r"(\d{1,2})[.,](\d{1,2})", s["created"])
        if in_sheet_date:
            d, m = (int(x) for x in in_sheet_date.groups())
            if (d, m) != (r["event"].day, r["event"].month):
                dates.append(dict(row=s["row"], sheet_name=s["restaurant"], client=r["client"],
                                  in_sheet=s["created"], by_1c=r["event"]))
        filled = {c: v for c, v in s["sums"].items() if v is not None}
        if not filled:
            col = None
            if r["manager"]:
                col = next((c for c, m in sheet["managers"].items() if m == r["manager"]), None)
            # правило 12: прочерк — это уже ответ, чей клиент. Два прочерка в строке
            # ответа не дают, поэтому спрашиваем Анну
            if col is None and len(s.get("dashes") or []) == 1:
                col = s["dashes"][0]
            if col and r["amount"]:
                upd_amount.append((s["row"], col, r["amount"], beby_note(r)))
                filled_info.append(dict(row=s["row"], sheet_name=s["restaurant"],
                                        manager=sheet["managers"].get(col, ""),
                                        amount=r["amount"], by_dash=not r["manager"]))
            elif r["amount"]:
                ask.append(dict(kind="нет суммы", row=s["row"], client=r["client"],
                                sheet_name=s["restaurant"], amount=r["amount"], calc=r))
        else:
            for col, v in filled.items():
                if abs(v - r["amount"]) > 1:
                    # ★правило 10 в редакции Анны 12.10: сумму по 1С ставим сами,
                    # прежнюю уносим в примечание (conflict_note). Нулём чужую
                    # сумму не затираем — ноль по 1С значит «окно пустое»
                    if r["amount"]:
                        upd_amount.append((s["row"], col, r["amount"], conflict_note(v, r)))
                    conflicts.append(dict(row=s["row"], client=r["client"],
                                          sheet_name=s["restaurant"], manager=sheet["managers"][col],
                                          in_sheet=v, by_1c=r["amount"], calc=r,
                                          rewritten=bool(r["amount"])))
    for r in new_for_sheet:
        ask.append(dict(kind="нет в листе", row=None, client=r["client"],
                        sheet_name="", amount=r["amount"], calc=r))
    # строка в листе есть, а расчёт её не подхватил: либо у клиента в этом месяце
    # нет события (обычный ритм — и это нормально), либо карточку в 1С не нашли
    if all_clients is not None:
        index_all = so.build_token_index(list(all_clients))
        for u in unmatched:
            u["in_1c"] = (match_client(f"{u['restaurant']} {u['entity']}", index_all)
                          or match_by_entity(u["entity"], allowed=set(all_clients)))
    # ★12.10.2026 (Анна: «почему 3 без указанной базы?») — юрлицо и базу помечаем и
    # тем строкам, у которых в этом месяце события нет: клиент в 1С найден, значит
    # видно, на какое юрлицо и из какой базы он ездит. Без карточки в 1С — не видно.
    marked = pairs + [(u, {"client": u["in_1c"]}) for u in unmatched if u.get("in_1c")]
    return dict(until=upd_until, amount=upd_amount, conflicts=conflicts, ask=ask,
                dates=dates, unmatched_sheet=unmatched, pairs=pairs, ym=ym,
                filled=filled_info, entities=entity_marks(marked),
                bases=base_marks(marked))


def apply_plan(ws, plan, sheet, pending_rows=None, dry_run=False):
    """Пишет в лист: колонку E, свои суммы и (на прогоне в копию) строки-кандидаты."""
    body = []
    cols = sheet.get("cols") or sheet_columns(sheet.get("header") or [])
    a1 = gspread.utils.rowcol_to_a1
    letter = lambda col: re.sub(r"\d", "", a1(1, col))
    for row, text in plan["until"]:
        body.append({"range": f"{letter(cols['until'])}{row}", "values": [[text]]})
    for row, col, amount, note in plan["amount"]:
        body.append({"range": gspread.utils.rowcol_to_a1(row, col), "values": [[amount]]})
    # правило 13: пустую колонку «Юр лицо» заполняем тем, на что реально идут
    # отгрузки; заполненную Анной не трогаем — только примечание под ней
    for m in plan.get("entities", []):
        if m["entity"] and not m["in_sheet"]:
            body.append({"range": f"{letter(cols['entity'])}{m['row']}",
                         "values": [[m["entity"]]]})
    base_col = letter(cols["base"])
    if plan.get("bases"):
        body.append({"range": f"{base_col}1", "values": [[BASE_HEADER]]})
        for m in plan["bases"]:
            body.append({"range": f"{base_col}{m['row']}", "values": [[m["text"]]]})
    if dry_run:
        return len(body)
    if body:
        ws.batch_update(body, value_input_option="USER_ENTERED")
    write_entity_notes(ws, plan.get("entities", []), letter(cols["entity"]), cols["entity"])
    paint_bases(ws, plan.get("bases", []), base_col)
    for row, col, amount, note in plan["amount"]:
        if note:
            ws.update_note(gspread.utils.rowcol_to_a1(row, col), f"{MANAGER_NOTE}\n{note}")
    if pending_rows:
        # именно ВСТАВКА строк: ниже данных в листе живут итоговая строка с
        # формулами и боковые блоки Анны — перезаписывать их нельзя
        start = plan_append_start(ws)
        # сумму кандидата кладём ЗА колонкой ИТОГ: колонки менеджеров — ручные, и
        # пока Анна не сказала, чей это клиент, число в них попасть не должно
        sum_col = max(sheet["managers"], default=FIRST_MANAGER_COL) + 2
        values = []
        for r in pending_rows:
            row = [""] * sum_col
            row[cols["restaurant"] - 1] = r["client"]
            row[cols["created"] - 1] = (f"{'первый заказ' if r['kind'] == 'новый' else 'вернули'} "
                                        f"{r['event']:%d.%m}")
            row[cols["kind"] - 1] = "ждёт подтверждения"
            row[cols["until"] - 1] = f"по {r['window_end']:%d.%m}"
            row[sum_col - 1] = r["amount"]
            values.append(row)
        ws.insert_rows(values, row=start, value_input_option="USER_ENTERED")
        last = start + len(values) - 1
        ws.format(f"A{start}:{gspread.utils.rowcol_to_a1(last, sum_col)}",
                  {"backgroundColor": {"red": 1, "green": 0.95, "blue": 0.75}})
        head = gspread.utils.rowcol_to_a1(1, sum_col)
        ws.update(values=[["сумма по 1С (бот)"]], range_name=head)
        for i, r in enumerate(pending_rows):
            note = beby_note(r)
            if note:
                ws.update_note(gspread.utils.rowcol_to_a1(start + i, sum_col), note)
    return len(body)


def write_entity_notes(ws, marks, col="B", col_num=COL_ENTITY):
    """Примечание к колонке «Юр лицо»: все карточки клиента в 1С (правило 13).

    Чужие примечания не трогаем — переписываем только свои (их видно по первой строке).
    """
    if not marks:
        return 0
    try:
        notes = ws.get_notes()
    except Exception as e:            # примечаний в листе может не быть вовсе
        logger.warning("примечания листа не прочитались: %s", e)
        notes = []

    def existing(row):
        r = notes[row - 1] if len(notes) >= row else []
        return r[col_num - 1] if len(r) >= col_num else ""

    upd = {f"{col}{m['row']}": m["note"] for m in marks
           if not existing(m["row"]) or existing(m["row"]).startswith(ENTITY_NOTE)}
    if upd:
        ws.update_notes(upd)
    return len(upd)


def paint_bases(ws, marks, col):
    """Заливка колонки «База 1С» цветом базы + легенда в примечании к заголовку."""
    if not marks:
        return 0
    fmt = [{"range": f"{col}{m['row']}", "format": {"backgroundColor": m["color"]}}
           for m in marks]
    fmt.append({"range": f"{col}1", "format": {"textFormat": {"bold": True}}})
    ws.batch_format(fmt)
    legend = "\n".join(f"• {BASE_TITLES[k]}" for k in BASE_COLORS)
    ws.update_note(f"{col}1", "из какой нашей базы 1С идут отгрузки, у каждой свой цвет:\n"
                             f"{legend}\n• сиреневый — клиент грузится из двух баз")
    return len(marks)


def plan_append_start(ws):
    """Первая свободная строка под данными (над итоговой строкой не лезем)."""
    col_a = ws.col_values(COL_RESTAURANT)
    last = max((i for i, v in enumerate(col_a, 1) if v.strip()), default=1)
    return last + 1


def summary_text(ym, plan, calc_rows):
    """Короткое сообщение Анне в MAX: что нашла, о чём спрашиваю (правила 1, 2, 10)."""
    t = sheet_title(ym)
    twins = plan.get("twins", {})
    new_1c = [a for a in plan["ask"] if a["kind"] == "нет в листе"
              and a["calc"]["kind"] == "новый" and a["client"] not in twins]
    cand = [a for a in plan["ask"] if a["kind"] == "нет в листе" and a["calc"]["kind"] == "кандидат"]
    lines = [f"ОТЧЁТ ПО ПРОДАЖАМ — лист «{t}»", ""]
    if new_1c:
        lines.append(f"НОВЫЕ по 1С без бланка — {len(new_1c)}, вносить?")
        for a in sorted(new_1c, key=lambda a: -a["amount"])[:15]:
            r = a["calc"]
            lines.append(f"  • {r['client'][:42]} — первый заказ {r['event']:%d.%m}, "
                         f"{money(r['amount'])} ₽")
        lines.append("")
    if cand:
        lines.append(f"ПОХОЖИ НА ВОЗВРАТ (без бланка) — {len(cand)}:")
        for a in sorted(cand, key=lambda a: -a["amount"])[:15]:
            r = a["calc"]
            rhythm = f", обычный ритм {r['rhythm']:g}" if r["rhythm"] else ""
            lines.append(f"  • {r['client'][:42]} — заказ {r['event']:%d.%m} после "
                         f"{r['gap']} дн. тишины{rhythm}, {money(r['amount'])} ₽")
        lines.append("")
    no_col = [a for a in plan["ask"] if a["kind"] == "нет суммы"]
    if no_col:
        lines.append(f"ПОСЧИТАЛ, НО НЕ ЗНАЮ, В ЧЬЮ КОЛОНКУ — {len(no_col)} (чей клиент?):")
        for a in sorted(no_col, key=lambda a: -a["amount"])[:15]:
            r = a["calc"]
            was = "первый заказ" if r["kind"] == "новый" else "вернули"
            lines.append(f"  • {a['sheet_name'][:34]} (строка {a['row']}) — {was} "
                         f"{r['event']:%d.%m}, {money(r['amount'])} ₽")
        lines.append("")
    by_dash = [f for f in plan.get("filled", []) if f["by_dash"]]
    if by_dash:
        lines.append(f"ПОСТАВИЛ СУММУ ТУДА, ГДЕ У ВАС ПРОЧЕРК — {len(by_dash)}:")
        for f in sorted(by_dash, key=lambda f: -f["amount"])[:12]:
            lines.append(f"  • {f['sheet_name'][:34]} (строка {f['row']}) — "
                         f"{money(f['amount'])} ₽ в колонку «{f['manager']}»")
        lines.append("")
    if plan["conflicts"]:
        fixed = sum(1 for c in plan["conflicts"] if c.get("rewritten"))
        lines.append(f"СУММА В ЛИСТЕ НЕ СХОДИЛАСЬ С 1С — {len(plan['conflicts'])} "
                     + (f"(поставил по 1С — {fixed}, прежняя в примечании):" if fixed
                        else "(сам не правлю):"))
        for c in plan["conflicts"][:10]:
            стрелка = "→ поставил" if c.get("rewritten") else "— оставил"
            lines.append(f"  • {c['sheet_name'][:34]} (строка {c['row']}): было "
                         f"{money(c['in_sheet'])} {стрелка} {money(c['by_1c'])}")
        lines.append("")
    twin_asks = [a for a in plan["ask"] if a["client"] in twins]
    if twin_asks:
        lines.append(f"ПОХОЖЕ, ТО ЖЕ ЗАВЕДЕНИЕ НА НОВОМ ЮРЛИЦЕ — {len(twin_asks)} "
                     f"(новый клиент или старый?):")
        for a in twin_asks[:10]:
            kin = ", ".join(k[:30] for k in twins[a["client"]][:2])
            lines.append(f"  • {a['client'][:40]} — {money(a['amount'])} ₽; раньше "
                         f"заказывал {kin}")
        lines.append("")
    if plan.get("dropped"):
        lines.append(f"НЕ БЕРУ (лист ИСКЛЮЧЕНИЯ) — {len(plan['dropped'])}: "
                     + ", ".join(f"{r['client'][:24]}" for r, _ in plan["dropped"][:8]))
        lines.append("")
    if plan.get("dates"):
        lines.append(f"ДАТА СОБЫТИЯ В ЛИСТЕ НЕ ТА, ЧТО В 1С — {len(plan['dates'])}:")
        for d in plan["dates"][:10]:
            lines.append(f"  • {d['sheet_name'][:34]} (строка {d['row']}): в листе "
                         f"«{d['in_sheet']}», по 1С {d['by_1c']:%d.%m}")
        lines.append("")
    no_card = [u for u in plan.get("unmatched_sheet", []) if not u.get("in_1c")]
    no_event = [u for u in plan.get("unmatched_sheet", []) if u.get("in_1c")]
    if no_card:
        lines.append(f"КАРТОЧКУ В 1С НЕ НАШЛА — {len(no_card)} (проверьте название):")
        for u in no_card[:10]:
            ent = f" ({u['entity'][:22]})" if u["entity"] else ""
            lines.append(f"  • {u['restaurant'][:34]}{ent} — строка {u['row']}")
        lines.append("")
    if no_event:
        lines.append(f"В ЛИСТЕ СТОИТ, А ПО 1С СОБЫТИЯ НЕТ — {len(no_event)} "
                     f"(заказы идут обычным ритмом):")
        for u in no_event[:10]:
            lines.append(f"  • {u['restaurant'][:34]} — строка {u['row']}")
        lines.append("")
    ones = one_order_candidates([a["calc"] for a in plan["ask"]])
    if ones:
        lines.append(f"ВЗЯЛИ ОДИН РАЗ за месяц — {len(ones)} (разовые?): "
                     + ", ".join(r["client"][:24] for r in ones[:10]))
    return "\n".join(lines).strip()


BLANKS_SHEET = "БЛАНКИ"     # журнал бланков от orders-bot (этап 2, см. ТЗ п.2)
EXCLUDE_SHEET = "ИСКЛЮЧЕНИЯ"    # кого в отчёт не берём и почему (пополняет Анна)
PENDING_MARK = "ждёт подтверждения"

# Как Анна подписывает менеджера в колонке B при разборе прогона: «алены»,
# «дарья поиск , алена сопровождение», «соня», «прямой клиент». Правило 8: сумма
# идёт менеджеру ПОИСКА, а если поиска нет — тому, кто ведёт сопровождение.
MANAGER_HINTS = {
    "дарь": "Дарья Вольнова", "даш": "Дарья Вольнова",
    "алён": "Алена Черкашина", "ален": "Алена Черкашина",
    "ксени": "Ксения Наныкина", "ксюш": "Ксения Наныкина",
    "лили": "Лилия Сулименко", "лил": "Лилия Сулименко",
    "софи": "София Хакимова", "сон": "София Хакимова",
    "виолетт": "Виолетта Караханова", "виол": "Виолетта Караханова",
    "анн": "Анна Кононенко (РОП)",
}


def manager_from_note(note):
    """Кому писать сумму по пометке Анны в колонке B.

    «дарья поиск , алена сопровождение» → Дарья (поиск важнее); «алены» → Алёна;
    «прямой клиент» без имени → None (ставит Анна сама).
    """
    low = (note or "").lower().replace("ё", "е")
    found = []
    for piece in re.split(r"[,;/]| и ", low):
        for key, name in MANAGER_HINTS.items():
            if key in piece:
                found.append((name, "поиск" in piece, "сопровожд" in piece))
                break
    if not found:
        return None
    search = [n for n, is_search, _ in found if is_search]
    if search:
        return search[0]
    support_only = [n for n, _, is_support in found if is_support]
    if support_only and len(found) > 1:
        return support_only[0]
    return found[0][0]


def split_client_name(client):
    """«ЛЕСНОЙ РЕСТОРАН (OOO РЮМКА НА ЛЕСНОЙ) В 1С/dsbx» → («ЛЕСНОЙ РЕСТОРАН», «OOO РЮМКА НА ЛЕСНОЙ»).

    В листе Анна держит заведение в колонке A, юрлицо — в B. Служебные хвосты
    (ЭДО, нал, dsbx, «в 1С», счёт, дата перевода) в лист не тащим.
    """
    name = so._TRANSFER_TAIL.sub("", str(client or "")).strip()
    m = re.search(r"\(([^)]*)\)", name)
    entity = (m.group(1).strip() if m else "")
    head = (name[:m.start()] if m else name).strip()
    head = _TAILS.sub(" ", head)
    head = re.sub(r"\s*(в\s*эдо\s*с\s*\d{1,2}\.\d{1,2}(\.\d{2,4})?|в\s*1с)\b.*$", "", head, flags=re.I)
    head = re.sub(r"\s{2,}", " ", head).strip(" ,/-")
    return (head or name), entity


def load_excluded(ss):
    """{клиент: {reason, rhythm_days}} из листа ИСКЛЮЧЕНИЯ.

    Лист пополняется разбором прогона (словами Анны) и ею самой. Колонка «Личный
    ритм (недель)» — для клиентов вроде ООО ГЛАВТОРГ («поставить ритм 3 недели, не
    считать в отчёт; если от своего ритма не будет брать 3 недели — считать»): если
    ритм задан, клиент из отчёта не выпадает, но возвратом считается только после
    молчания «свой ритм + 3 недели».
    """
    try:
        ws = ss.worksheet(EXCLUDE_SHEET)
    except gspread.WorksheetNotFound:
        return {}
    out = {}
    for r in ws.get_all_values()[1:]:
        if not r or not r[0].strip():
            continue
        cell = r[4].strip() if len(r) > 4 else ""
        weeks = _num(cell)
        if weeks:
            rhythm = int(weeks * 7)
        elif re.search(r"авто|свой", cell, re.I):
            rhythm = "auto"      # ★12.10.2026 Анна про ГЛАВТОРГ: «ставь свой ритм + 3 недели»
        else:
            rhythm = None
        out[r[0].strip()] = dict(reason=(r[1].strip() if len(r) > 1 else ""),
                                 rhythm_days=rhythm)
    return out


def apply_excluded(rows, excluded):
    """Убирает из расчёта тех, кого Анна исключила, и чинит порог ручного ритма.

    Клиент с заданным личным ритмом остаётся, но его молчание сравнивается с
    «ритм + 3 недели»: заказ раньше этого срока — обычный ритм, а не возврат.
    """
    if not excluded:
        return rows, []
    # ★строгий матчинг: список исключений маленький, и мягкий поиск цеплял лишних —
    # «Алена физ лицо НАЛ СРАЗУ» вытаскивала из отчёта «Матвей Физ лицо» и «Вадим»
    index = so.build_token_index(list(excluded))
    out, dropped = [], []
    for r in rows:
        hit = match_client(r["client"], index, strict=True)
        rule = excluded.get(r["client"]) or (excluded.get(hit) if hit else None)
        if not rule:
            out.append(r)
            continue
        manual = rule.get("rhythm_days")
        if manual:
            # «авто» — ритм считает сам по 1С (медиана интервалов за полгода), и если
            # ритма не хватило на расчёт, порогом остаётся обычные 28 дней
            base = (int(r["rhythm"] or RETURN_GAP) if manual == "auto" else manual)
            if r["kind"] == "кандидат" and (r["gap"] or 0) < base + 21:
                dropped.append((r, f"свой ритм {base} дн. + 3 недели ещё не прошли"))
                continue
            out.append(r)
        else:
            dropped.append((r, rule.get("reason", "")))
    return out, dropped


# Слова, по которым «то же заведение» определять нельзя: роли и личные имена —
# карточки часто подписывают контактным лицом («Сыроварня Алексей шеф», «Хлынин
# Алексей Сергеевич»), и по ним склеивались совершенно разные клиенты.
_TWIN_STOP = frozenset({
    "шеф", "повар", "закупщик", "закупщица", "кладовщик", "менеджер", "админ",
    "директор", "бухгалтер", "физ", "лицо", "лицу", "ресторан", "рестораны",
    "александр", "алексей", "анастасия", "андрей", "анна", "антон", "артем",
    "вадим", "валентина", "василий", "виктор", "виктория", "виолетта", "владимир",
    "галина", "дарья", "денис", "дмитрий", "евгений", "егор", "екатерина", "елена",
    "иван", "игорь", "илья", "ирина", "кирилл", "ксения", "лилия", "людмила",
    "максим", "мария", "марина", "матвей", "михаил", "никита", "николай", "олег",
    "ольга", "павел", "роман", "сергей", "светлана", "софия", "станислав",
    "татьяна", "юлия", "юрий", "ярослав", "алена", "наталья", "надежда",
})


def _twin_tokens(name):
    """Слова НАЗВАНИЯ ЗАВЕДЕНИЯ (без юрлица в скобках, ролей и личных имён)."""
    head, _ = split_client_name(name)
    return (so.name_tokens(head) - so._GENERIC_WORDS) - _TWIN_STOP


def entity_twins(rows, hist):
    """Для «новых»: тот же ресторан на другом юрлице, уже работавший раньше.

    Анна, 12.10: «NO SUGAR ИП БЕЛИКОВА — поменяли юр лицо, старый клиент» (до 07.09
    тот же ресторан заказывал как «NO Sugar (ИП ГУСЕВ)»), «Пуассон Кейтеринг (ООО
    МЕЗОН)» — то же про Пуассона. Такого клиента новым называть нельзя. Но и
    склеивать юрлица молча тоже нельзя — у сетей («Стейк ит изи» — пять юрлиц) это
    РАЗНЫЕ клиенты, поэтому находку отдаём Анне вопросом.
    """
    tokens = {n: _twin_tokens(n) for n in hist}
    freq = defaultdict(int)
    for ts in tokens.values():
        for w in ts:
            freq[w] += 1
    twins = {}
    for r in rows:
        if r["kind"] != "новый":
            continue
        t = tokens.get(r["client"]) or _twin_tokens(r["client"])
        rare = {w for w in t if freq[w] <= 4}
        if not rare:
            continue
        kin = []
        for n, ct in tokens.items():
            if n == r["client"] or not (rare & ct) or ct == t:
                continue
            items = hist.get(n) or []
            if not items or items[0][0] >= r["event"]:
                continue                      # старше нашего клиента он не был
            # ★переезд виден по тому, что СТАРАЯ карточка затихла: иначе под признак
            # лезут случайные общие слова («…ТАЙМ», «ДРУЗЬЯ», «шеф»)
            if items[-1][0] <= r["event"] + timedelta(days=14):
                kin.append(n)
        if kin:
            twins[r["client"]] = kin
    return twins


def promote_confirmed(ss, ym, dry_run=False, today=None):
    """Переносит размеченный прогон из копии листа в живой лист.

    Анна разбирает строки «ждёт подтверждения» в копии: в колонке D ставит вид
    (новый / вернули / разовый), в колонке B пишет, чей это клиент или почему его
    брать не надо. Отсюда: подтверждённые строки уезжают в живой лист (сумма — в
    колонку названного менеджера), остальные — в лист ИСКЛЮЧЕНИЯ с её причиной,
    чтобы следующий прогон их больше не предлагал.
    """
    title = sheet_title(ym)
    stamp = (today or date.today()).strftime("%d.%m")
    copy = ss.worksheet(f"{title} КОПИЯ {stamp}")
    live = ss.worksheet(title)
    sheet = read_sheet(live)
    mcols = sheet["managers"]
    sum_col = max(mcols, default=FIRST_MANAGER_COL) + 2
    copy_vals = copy.get_all_values()
    # колонки копии ищем по её шапке: у листов разных месяцев они разъехались
    ccols = sheet_columns(copy_vals[0] if copy_vals else [])
    cols = sheet["cols"]

    confirmed, excluded = [], []
    for r in copy_vals[1:]:
        def cell(i):
            return r[i - 1].strip() if len(r) >= i else ""
        client = cell(ccols["restaurant"])
        note, kind = cell(ccols["entity"]), cell(ccols["kind"]).lower()
        if not client or not cell(ccols["created"]):
            continue
        amount = _num(cell(sum_col))
        if amount is None:
            continue                      # строка не из прогона — её Анна вела руками
        if PENDING_MARK in kind or not kind:
            excluded.append((client, note))
            continue
        confirmed.append(dict(client=client, note=note, kind=cell(ccols["kind"]),
                              created=cell(ccols["created"]), until=cell(ccols["until"]),
                              base=cell(ccols["base"]) if ccols["base"] <= len(r) else "",
                              amount=amount, manager=manager_from_note(note)))
    if dry_run:
        return dict(confirmed=confirmed, excluded=excluded, row=None)

    start = plan_append_start(live)
    values = []
    for c in confirmed:
        head, entity = split_client_name(c["client"])
        row = [""] * max(mcols, default=FIRST_MANAGER_COL)
        row[cols["restaurant"] - 1], row[cols["entity"] - 1] = head, entity
        row[cols["created"] - 1], row[cols["kind"] - 1] = c["created"], c["kind"]
        row[cols["until"] - 1] = c["until"]
        if c.get("base") and cols["base"] <= len(row):
            row[cols["base"] - 1] = c["base"]
        col = next((k for k, m in mcols.items() if m == c["manager"]), None)
        if col:
            row[col - 1] = c["amount"] if c["amount"] else "-"
        values.append(row)
    if values:
        live.insert_rows(values, row=start, value_input_option="USER_ENTERED")
        name_col = re.sub(r"\d", "", gspread.utils.rowcol_to_a1(1, cols["restaurant"]))
        for i, c in enumerate(confirmed):
            if c["note"]:
                live.update_note(f"{name_col}{start + i}",
                                 f"разбор Анны {stamp}: {c['note']}")
    if excluded:
        write_excluded(ss, excluded, stamp)
    return dict(confirmed=confirmed, excluded=excluded, row=start)


def write_excluded(ss, excluded, stamp):
    """Пополняет лист ИСКЛЮЧЕНИЯ: клиент, причина (словами Анны), когда решили."""
    try:
        ws = ss.worksheet(EXCLUDE_SHEET)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=EXCLUDE_SHEET, rows=200, cols=5)
        ws.update(values=[["Клиент (как в 1С)", "Почему не берём в отчёт", "Когда решили",
                           "Комментарий", "Личный ритм (недель)"]], range_name="A1:E1")
        ws.format("A1:E1", {"textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.91, "green": 0.91, "blue": 0.91}})
    have = set(load_excluded(ss))
    rows = [[c, n, stamp, ""] for c, n in excluded if c not in have]
    if rows:
        start = len(ws.col_values(1)) + 1
        ws.update(values=rows, range_name=f"A{start}:D{start + len(rows) - 1}",
                  value_input_option="USER_ENTERED")
    return len(rows)


def load_blanks(ss, ym):
    """События из бланков менеджеров: [{kind, client, entity, manager, date}].

    Бот заказов уже разбирает бланки «ПЕРВЫЙ ЗАКАЗ» и «ВОЗВРАЩЁННЫЙ КЛИЕНТ»
    (`orders-bot/core/templates.py`) во всех четырёх группах, включая «Заказы утро»
    в MAX. Осталось, чтобы он складывал разобранное в лист-журнал `БЛАНКИ` этой же
    таблицы: дата, вид, ресторан, компания, автор. Пока листа нет — список пустой,
    и тогда скрипт никого не вносит молча, а спрашивает Анну (правила 1–2).
    """
    try:
        ws = ss.worksheet(BLANKS_SHEET)
    except gspread.WorksheetNotFound:
        logger.info("листа «%s» ещё нет — бланки не подключены (ТЗ, п.2)", BLANKS_SHEET)
        return []
    m_start, _ = month_bounds(prev_month(ym))
    _, m_end = month_bounds(ym)
    out = []
    for r in ws.get_all_records():
        try:
            d = datetime.strptime(str(r.get("Дата"))[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if m_start <= d <= m_end:
            out.append(dict(kind="новый" if "перв" in str(r.get("Вид", "")).lower() else "вернули",
                            client=str(r.get("Ресторан", "")).strip(),
                            entity=str(r.get("Компания", "")).strip(),
                            manager=str(r.get("Автор", "")).strip(), date=d))
    logger.info("журнал бланков: %s строк за %s—%s", len(out), m_start, m_end)
    return out


def authors_from_sheets(ss, ym, titles=2):
    """Кто ведёт клиента — по листам отчёта за прошлые месяцы.

    ★Рабочий способ узнать менеджера, когда автора бланка нет (строки из логов,
    сообщение от имени канала): в прошлых листах у клиента уже стоит сумма или
    прочерк в чьей-то колонке. Так 12.10.2026 нашёлся менеджер ГЛАВТОРГа.
    Возвращает {подпись клиента в листе: (ФИО, лист)} по всем просмотренным листам.
    """
    out = {}
    month = ym
    for _ in range(titles):
        try:
            sh = read_sheet(ss.worksheet(sheet_title(month)))
        except gspread.WorksheetNotFound:
            logger.info("листа «%s» нет — пропускаю", sheet_title(month))
            month = prev_month(month)
            continue
        for row in sh["rows"]:
            if not row["restaurant"].strip():
                continue
            cols = [c for c, v in row["sums"].items() if v is not None]
            cols += list(row.get("dashes") or [])
            names = {sh["managers"].get(c) for c in cols} - {None, ""}
            if len(names) == 1:
                label = f"{row['restaurant']} {row['entity']}".strip()
                out.setdefault(label, (names.pop(), sheet_title(month)))
        month = prev_month(month)
    return out


def fill_blank_authors(ss, ym, dry_run=False):
    """Пустую колонку «Автор» в журнале бланков заполняем по прошлым листам.

    Строки, восстановленные из логов бота, автора не знают: в журнале systemd его
    не было. Но тот же клиент уже стоит в листе отчёта в чьей-то колонке — этого
    достаточно. Своё заполнение помечаем примечанием: видно, что это не слово
    менеджера, а догадка по листу.
    """
    ws = ss.worksheet(BLANKS_SHEET)
    header = ws.row_values(1)
    col = header.index("Автор") + 1 if "Автор" in header else 5
    known = authors_from_sheets(ss, ym)
    index = so.build_token_index(list(known))
    done, left = [], []
    for i, r in enumerate(ws.get_all_records(), start=2):
        if str(r.get("Автор", "")).strip():
            continue
        label = f'{r.get("Ресторан", "")} {r.get("Компания", "")}'.strip()
        hit = match_client(label, index)
        if hit:
            who, title = known[hit]
        else:
            # ★один клиент стоит в НЕСКОЛЬКИХ листах («Райт хопс» и «Райт хопс ООО
            # Райт Хопс»), и match_client отказывается выбирать из двух. Но если
            # ведёт их один человек, выбирать и не нужно — ответ один
            t = so.name_tokens(label)
            same = {known[k][0] for ct, k in index if t and (t <= ct or ct <= t)}
            who, title = (same.pop(), "прошлые листы") if len(same) == 1 else (None, None)
        if who:
            done.append((i, who, title, str(r.get("Ресторан", ""))))
        else:
            left.append((i, str(r.get("Ресторан", "")), str(r.get("Компания", ""))))
    if done and not dry_run:
        a1 = gspread.utils.rowcol_to_a1
        ws.batch_update([{"range": a1(i, col), "values": [[who]]} for i, who, _, _ in done],
                        value_input_option="USER_ENTERED")
        for i, who, title, _ in done:
            ws.update_note(a1(i, col), f"по листу «{title}» — автора бланка в логе не было")
    logger.info("авторы бланков: заполнено %s, осталось без автора %s", len(done), len(left))
    return done, left


def attach_blanks(rows, blanks):
    """Проставляет строкам вид и менеджера из бланка (правила 1, 2, 8).

    Бланк — слово менеджера, и оно главнее догадки по 1С: вид события берём из
    него. Автора в журнале может не быть (строки, восстановленные из логов
    12.10.2026, или сообщение от имени канала) — тогда менеджера НЕ затираем:
    пустой автор ничего не говорит, и сумму всё равно подскажет прочерк Анны,
    прошлый лист или её ответ.
    """
    if not blanks:
        return rows
    index = so.build_token_index([r["client"] for r in rows])
    by_client = {r["client"]: r for r in rows}
    for b in blanks:
        hit = match_client(f"{b['client']} {b['entity']}", index)
        if not hit:
            hit = match_by_entity(b["entity"], allowed=set(by_client)) if b["entity"] else None
        if hit:
            r = by_client[hit]
            r["source"] = "бланк"
            r["kind"] = b["kind"]
            r["blank_author"] = b["manager"]
            if b["manager"]:
                r["manager"] = manager_from_note(b["manager"]) or b["manager"]
    return rows


def apply_answers(rows, answers):
    """Ответ кнопкой из MAX — вместо бланка (правила 1-3, 5).

    «вношу» — строка идёт в лист как есть, «разовый» — тем же видом, что в листе
    пишет Анна, «не вношу» — клиента из расчёта убираем и запоминаем в листе
    ИСКЛЮЧЕНИЯ, чтобы он не предлагался в следующем месяце.
    """
    kept, refused = [], []
    for r in rows:
        verdict = sales_ask.match_answer(r["client"], answers)
        if verdict == "не вносить":
            refused.append(r)
            continue
        if verdict == "разовый":
            r["kind"], r["source"] = "разовый", "ответ Анны"
        elif verdict == "вносить":
            r["source"] = "ответ Анны"
        elif verdict:
            # на кнопке было имя менеджера («Дарья») — это ответ на вопрос
            # «в чью колонку сумма»; все написания имён лежат в MANAGER_HINTS
            who = manager_from_note(verdict)
            if who:
                r["manager"], r["source"] = who, "ответ Анны"
            else:
                logger.warning("не поняла ответ «%s» про «%s»", verdict, r["client"])
        kept.append(r)
    return kept, refused


REFUSED_REASON = "ответ кнопкой в MAX: не вносить"


def refused_orphans(answers, state, rows):
    """«Не вношу» про клиента, которого в расчёте нет.

    ★13.10.2026: так ответила Анна про ДЖЕМ — бланк «первый заказ» есть, а в 1С ни
    накладной, ни карточки, поэтому в расчёте его и не было. Ответ не должен
    повиснуть: клиента всё равно вносим в лист ИСКЛЮЧЕНИЯ, иначе спросим снова,
    как только он появится в 1С. Полное имя берём из состояния — на кнопке оно
    обрезано до 44 символов, а исключения матчатся строго.
    """
    есть = {sales_ask._flat(r["client"]) for r in rows}
    по_состоянию = {sales_ask._flat(a["client"]): a["client"]
                    for a in (state.get("asked") or {}).values() if a.get("client")}
    out = []
    for name, verdict in answers.items():
        if verdict != "не вносить":
            continue
        key = sales_ask._flat(name)
        if any(k.startswith(key) or key.startswith(k) for k in есть):
            continue
        full = next((v for k, v in по_состоянию.items()
                     if k.startswith(key) or key.startswith(k)), name)
        out.append(dict(client=full))
    return out


def remember_refused(ss, refused, excluded, today=None):
    """«Не вношу» — в лист ИСКЛЮЧЕНИЯ: иначе в следующем месяце спросим снова."""
    new = [(r["client"], REFUSED_REASON) for r in refused if r["client"] not in excluded]
    if new:
        write_excluded(ss, new, (today or date.today()).strftime("%d.%m"))
        logger.info("в лист ИСКЛЮЧЕНИЯ добавлено по ответу Анны: %s", len(new))
    return new


def run(ym=None, live=False, dry_run=False, pending=True, today=None, ask=True):
    """Полный прогон: 1С → классификация → вычет → лист → вопросы и сводка Анне."""
    ym = ym or (today or date.today()).strftime("%Y-%m")
    hist, canon = load_history()
    rows = apply_beby(classify(hist, ym), load_beby(ym, canon))
    ss = open_spreadsheet()
    rows = attach_blanks(rows, load_blanks(ss, ym))
    ask_state = sales_ask.load_state()
    # ответы принимаем только по тем клиентам, про которых сами спрашивали
    answers = sales_ask.read_answers(ask_state) if ask else {}
    excluded = load_excluded(ss)
    rows, refused = apply_answers(rows, answers)
    refused += refused_orphans(answers, ask_state, rows)
    if refused and not dry_run:
        remember_refused(ss, refused, excluded, today=today)
    rows, dropped = apply_excluded(rows, excluded)
    dropped += [(r, REFUSED_REASON) for r in refused if r.get("event")]
    twins = entity_twins(rows, hist)
    title = sheet_title(ym)
    ws = ss.worksheet(title) if live else make_copy(ss, title, today=today)
    sheet = read_sheet(ws)
    plan = plan_sheet(rows, sheet, ym, all_clients=hist.keys())
    plan["dropped"], plan["twins"] = dropped, twins
    pending_rows = ([a["calc"] for a in plan["ask"]
                     if a["kind"] == "нет в листе" and a["client"] not in twins]
                    if pending else [])
    if live:
        # в живой лист строку ставим только тогда, когда её подтвердил человек:
        # бланком менеджера или кнопкой Анны. Догадка 1С сама в лист не лезет
        pending_rows = [r for r in pending_rows if r["source"] in ("бланк", "ответ Анны")]
    written = apply_plan(ws, plan, sheet, pending_rows=pending_rows, dry_run=dry_run)
    asked = 0
    if ask:
        # спрашиваем ровно то, что человек должен решить сам: кого 1С считает новым
        # без бланка, кто похож на возврат и кто взял один раз (правила 1-3)
        state = ask_state
        # ★спрашиваем ТОЛЬКО о том, чего в листе нет: про клиента, которого Анна уже
        # разобрала (вид стоит в колонке D), вопрос — лишний шум. 13.10 на этом
        # попалась: бот собрался спросить «разовый?» про 10 строк, уже помеченных ею
        новые = [a["calc"] for a in plan["ask"]
                 if a["kind"] == "нет в листе" and a["calc"]["source"] == "1С"
                 and a["client"] not in twins]
        asked = sales_ask.ask_rows(новые, answers, state, dry_run=dry_run, now=today)
        # сумма посчитана, строка в листе есть, а колонка неизвестна (ни бланка, ни
        # прочерка) — спрашиваем кнопками с именами менеджеров
        без_колонки = [a["calc"] for a in plan["ask"] if a["kind"] == "нет суммы"]
        места = {a["calc"]["client"]: a["row"] for a in plan["ask"] if a["kind"] == "нет суммы"}
        asked += sales_ask.ask_rows(без_колонки, answers, state, dry_run=dry_run, now=today,
                                    kind=sales_ask.ASK_WHO,
                                    managers=list(sheet["managers"].values()),
                                    rows_in_sheet=места)
        if asked and not dry_run:
            sales_ask.save_state(state)
    return dict(ym=ym, sheet=ws.title, rows=rows, plan=plan, written=written, asked=asked,
                answers=answers, refused=refused,
                pending=pending_rows, summary=summary_text(ym, plan, rows))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ym = args[0] if args else date.today().strftime("%Y-%m")
    res = run(ym, live="--live" in flags, dry_run="--dry" in flags)
    rows = res["rows"]
    print(f"\nлист: {res['sheet']}   новых по 1С {sum(1 for r in rows if r['kind'] == 'новый')}, "
          f"кандидатов {sum(1 for r in rows if r['kind'] == 'кандидат')}, "
          f"записано ячеек {res['written']}, строк-кандидатов {len(res['pending'])}\n")
    for r in rows:
        why = (f"молчал {r['gap']} дн." + (f" при ритме {r['rhythm']:g}" if r["rhythm"] else "")
               if r["kind"] == "кандидат" else "")
        tail = f"  (хвост след. месяца {r['tail_next_month']:,.0f})" if r["tail_next_month"] else ""
        cut = f"  ★беби −{r['beby_cut']:,.0f}" if r["beby_cut"] else ""
        print(f"{r['kind']:<9}{r['event']:%d.%m}  {r['client'][:44]:<44}"
              f"{r['amount']:>11,.0f}  по {r['window_end']:%d.%m}  {why}{tail}{cut}")
    print(f"\nИТОГО {sum(r['amount'] for r in rows):,.0f}")
    print("\n" + "─" * 70 + "\nСООБЩЕНИЕ АННЕ:\n" + res["summary"])
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sales_report_last.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(dict(ym=res["ym"], sheet=res["sheet"], summary=res["summary"],
                       conflicts=[{k: v for k, v in c.items() if k != "calc"}
                                  for c in res["plan"]["conflicts"]],
                       ask=[dict(kind=a["kind"], client=a["client"], amount=a["amount"],
                                 event=str(a["calc"]["event"]), vid=a["calc"]["kind"])
                            for a in res["plan"]["ask"]]), f, ensure_ascii=False, indent=2)
    print(f"\nсводка сохранена: {out}")
