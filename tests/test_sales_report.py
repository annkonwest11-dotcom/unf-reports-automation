"""Отчёт по продажам: правила классификации, склейки, вычета и записи в лист.

Проверяются решения Анны, записанные в `sales_report.py` и в листе «ТЗ — отчёт по
продажам»: лист месяца, окно и граница месяца, кто один клиент, вычет за салаты,
матчинг строк листа и то, что чужие суммы скрипт не переписывает.
Все тесты без сети: данные 1С подставляются руками.
"""
import os
import sys
import gspread
import unittest
from unittest import mock
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sales_report as sr


class TestSheetNaming(unittest.TestCase):
    """Лист месяца M называется «<M-1>-<M>» (проверено на живых листах 12.10.2026)."""

    def test_october_is_september_october(self):
        self.assertEqual(sr.sheet_title("2026-10"), "сентябрь-октябрь")

    def test_january_takes_december(self):
        self.assertEqual(sr.sheet_title("2026-01"), "декабрь-январь")
        self.assertEqual(sr.prev_month("2026-01"), "2025-12")

    def test_month_bounds(self):
        self.assertEqual(sr.month_bounds("2026-10"), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(sr.month_bounds("2026-02"), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(sr.month_bounds("2026-12"), (date(2026, 12, 1), date(2026, 12, 31)))

    def test_sheet_titles_match_salary_sync(self):
        """Тот же лист читает зарплата — названия обязаны совпадать."""
        from sync_novye import MONTH_TO_KPI_SHEET
        months = {"Январь": 1, "Февраль": 2, "Март": 3, "Апрель": 4, "Май": 5, "Июнь": 6,
                  "Июль": 7, "Август": 8, "Сентябрь": 9, "Октябрь": 10, "Ноябрь": 11,
                  "Декабрь": 12}
        for ru, num in months.items():
            self.assertEqual(sr.sheet_title(f"2026-{num:02d}"), MONTH_TO_KPI_SHEET[ru], ru)


class TestGroupCards(unittest.TestCase):
    """Правило 9: один клиент — одно название и одно юрлицо."""

    def test_typo_and_nal_duplicates_are_one_client(self):
        """Дубли карточек за разные названия не считаем (Анна, 12.10)."""
        cards = [("ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС", "5050057890"),
                 ("причал чарли нал( комлекс) ООО", ""),
                 ("Причал Чарли нал", ""),
                 ("ПРИЧАЛ ООО", "5032113800"),
                 ("НАЙТСБРИДЖ ООО ( ЧАРЛИ)", "9704118453")]
        groups = sr.group_cards(cards)
        canon = {m: c for c, ms in groups.items() for m in ms}
        charly = canon["ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС"]
        self.assertEqual(canon["причал чарли нал( комлекс) ООО"], charly)
        self.assertEqual(canon["Причал Чарли нал"], charly)
        # своё юрлицо с более общим названием — отдельный клиент
        self.assertNotEqual(canon["ПРИЧАЛ ООО"], charly)
        self.assertNotEqual(canon["НАЙТСБРИДЖ ООО ( ЧАРЛИ)"], charly)

    def test_same_entity_different_names_stay_apart(self):
        """ЛУЖНИКИ и МАГАДАН — оба ООО СПОРТКОРТ, но это разные клиенты."""
        cards = [("МАГАДАН ЛУЖНИКИ (ООО СПОРТКОРТ) ЭДО", "9728159032"),
                 ("МАРИКА и МЕДУЗА ЛУЖНИКИ (ООО СПОРТКОРТ) ЭДО", "9728159032")]
        self.assertEqual(len(sr.group_cards(cards)), 2)

    def test_same_name_different_entities_stay_apart(self):
        """«Стейк ит изи» — пять юрлиц, значит пять клиентов."""
        cards = [("СТЕЙК ИТ ИЗИ Steak it easy (ООО ОЛИМП)", "7722366712"),
                 ("СТЕЙК ИТ ИЗИ Steak it easy ( ООО ДЕМЕТРА )", "7736293790"),
                 ("СТЕЙК ИТ ИЗИ Steak it easy (ООО МОНТОНИКО)", "7714396255")]
        self.assertEqual(len(sr.group_cards(cards)), 3)

    def test_abandoned_card_joins_the_live_one(self):
        """Пометка «НЕ ВЕРНЫЙ ЕСТЬ 2-Й» — та же карточка, деньги должны сложиться."""
        cards = [("СТЕЙК ХАУС (ООО ГОЛДЕН ТАУЭР)", "9703160163"),
                 ("СТЕЙК ХАУС (ООО ГОЛДЕН ТАУЭР) НЕ ВЕРНЫЙ", "9703160163")]
        groups = sr.group_cards(cards)
        self.assertEqual(len(groups), 1)
        self.assertEqual(next(iter(groups)), "СТЕЙК ХАУС (ООО ГОЛДЕН ТАУЭР)")

    def test_network_points_merge(self):
        """Приёмки одного склада — один клиент (ТЗ, п.7: Анна ответила «да»)."""
        cards = [(f"Peshi ( Пеши ) - Приёмка {i}", "") for i in range(1, 5)]
        self.assertEqual(len(sr.group_cards(cards)), 1)

    def test_different_points_do_not_merge(self):
        """«ШЕСТНАДЦАТЬ ТОНН КЕЙТЕРИНГ» ≠ «ШЕСТНАДЦАТЬ ТОНН ПРЕСНЯ»."""
        cards = [("ШЕСТНАДЦАТЬ ТОНН ПРЕСНЯ (ООО 16 ТОНН ПРЕСНЯ) счет", "7703428378"),
                 ("ШЕСТНАДЦАТЬ ТОНН КЕЙТЕРИНГ ООО счет", "7703741301")]
        self.assertEqual(len(sr.group_cards(cards)), 2)


class TestClassify(unittest.TestCase):
    """Правила 1–5: вид события, окно, граница месяца."""

    def test_new_client_amount_cut_by_month(self):
        """Made in bali: событие 23.07 → июльская часть в лист июля, хвост в август."""
        hist = {"Made in bali": [(date(2026, 7, 23), 30_000.0), (date(2026, 7, 30), 31_592.0),
                                 (date(2026, 8, 5), 100_000.0), (date(2026, 8, 21), 64_014.0)]}
        july = {r["client"]: r for r in sr.classify(hist, "2026-07")}["Made in bali"]
        self.assertEqual(july["kind"], "новый")
        self.assertEqual(july["event"], date(2026, 7, 23))
        self.assertEqual(july["window_end"], date(2026, 8, 21))
        self.assertEqual(july["amount"], 61_592.0)
        self.assertEqual(july["tail_next_month"], 164_014.0)

    def test_event_of_previous_month_keeps_its_tail_in_this_sheet(self):
        """Лист месяца M держит и события M-1 — с их частью окна внутри M."""
        hist = {"Рубель": [(date(2026, 9, 11), 6_880.0), (date(2026, 10, 2), 5_472.0)]}
        row = sr.classify(hist, "2026-10")[0]
        self.assertEqual(row["event"], date(2026, 9, 11))
        self.assertEqual(row["amount"], 5_472.0)        # только октябрьская часть

    def test_window_is_30_days_inclusive(self):
        hist = {"X": [(date(2026, 10, 2), 1.0), (date(2026, 10, 31), 2.0),
                      (date(2026, 11, 1), 4.0), (date(2026, 11, 2), 8.0)]}
        row = sr.classify(hist, "2026-10")[0]
        self.assertEqual(row["window_end"], date(2026, 10, 31))
        self.assertEqual(row["amount"], 3.0)
        self.assertEqual(row["tail_next_month"], 0.0)   # 01.11 уже вне окна

    def test_return_candidate_after_silence(self):
        """Заказ после 28+ дней тишины — кандидат, вердикт за бланком (правило 2)."""
        hist = {"Чемодан": [(date(2026, 4, 18), 3_000.0), (date(2026, 8, 1), 3_000.0),
                            (date(2026, 9, 29), 5_000.0)]}
        row = sr.classify(hist, "2026-09")[0]
        self.assertEqual(row["kind"], "кандидат")
        self.assertEqual(row["event"], date(2026, 9, 29))
        self.assertEqual(row["gap"], 59)
        self.assertEqual(row["source"], "1С")

    def test_new_client_wins_over_later_gap(self):
        """Новый в октябре с разрывом внутри месяца остаётся новым, сумма — с начала."""
        hist = {"Новичок": [(date(2026, 10, 2), 1_000.0), (date(2026, 10, 30), 2_000.0)]}
        row = sr.classify(hist, "2026-10")[0]
        self.assertEqual((row["kind"], row["event"]), ("новый", date(2026, 10, 2)))
        self.assertEqual(row["amount"], 3_000.0)

    def test_freshest_return_wins_when_old_window_closed(self):
        """Два возврата в периоде — в лист идёт свежий, его окно и живёт в месяце."""
        hist = {"Красота": [(date(2025, 12, 5), 900.0), (date(2026, 9, 2), 1_000.0),
                            (date(2026, 10, 2), 2_865.0)]}
        row = sr.classify(hist, "2026-10")[0]
        self.assertEqual((row["kind"], row["event"]), ("кандидат", date(2026, 10, 2)))
        self.assertEqual(row["amount"], 2_865.0)

    def test_short_gap_is_not_an_event(self):
        """Обычный ритм в 20 дней событием не считается."""
        hist = {"Ровный": [(date(2026, 6, 1), 1_000.0), (date(2026, 6, 21), 1_000.0),
                           (date(2026, 7, 11), 1_000.0), (date(2026, 7, 31), 1_000.0),
                           (date(2026, 8, 20), 1_000.0), (date(2026, 9, 9), 1_000.0),
                           (date(2026, 9, 29), 1_000.0)]}
        self.assertEqual(sr.classify(hist, "2026-09"), [])

    def test_one_order_candidates(self):
        """Разовые — только среди новых и вернувшихся месяца (Анна, 12.10)."""
        hist = {"Разовый": [(date(2026, 10, 5), 2_000.0)],
                "Повторный": [(date(2026, 10, 5), 2_000.0), (date(2026, 10, 20), 2_000.0)]}
        rows = sr.classify(hist, "2026-10")
        ones = [r["client"] for r in sr.one_order_candidates(rows)]
        self.assertEqual(ones, ["Разовый"])


class TestBeby(unittest.TestCase):
    """Правило 7: вычет 40% за салаты сверх 4 кг за месяц."""

    def row(self, amount=10_000.0):
        return dict(client="X", kind="новый", event=date(2026, 10, 1),
                    window_end=date(2026, 10, 30), amount=amount)

    def test_cut_applied_over_threshold(self):
        """Пич Новый: 10 390 − 40% × 7 250 = 7 490 (как в листе Анны)."""
        rows = sr.apply_beby([self.row(10_390.0)],
                             {"X": [(date(2026, 10, 5), 7_250.0, 50)]})
        self.assertEqual(rows[0]["beby_cut"], 2_900.0)
        self.assertEqual(rows[0]["amount"], 7_490.0)
        self.assertEqual(rows[0]["amount_gross"], 10_390.0)

    def test_no_cut_under_threshold(self):
        """40 упаковок — ровно 4 кг, порог «больше 4 кг» не перешагнут."""
        rows = sr.apply_beby([self.row()], {"X": [(date(2026, 10, 5), 5_000.0, 40)]})
        self.assertEqual(rows[0]["beby_cut"], 0.0)
        self.assertEqual(rows[0]["amount"], 10_000.0)

    def test_threshold_by_month_cut_by_window(self):
        """Порог — по всему месяцу, вычет — только с той части, что попала в окно."""
        sales = [(date(2026, 10, 5), 6_000.0, 30), (date(2026, 11, 2), 4_000.0, 20)]
        rows = sr.apply_beby([self.row()], {"X": sales})
        self.assertEqual(rows[0]["beby_kg"], 5.0)        # порог считаем по месяцу
        self.assertEqual(rows[0]["beby_cut"], 2_400.0)   # 40% только от 6 000 в окне

    def test_shiso_and_basil_are_not_salad(self):
        """Анна, 12.10: шисо и базилик 100 гр — не салаты, цветы тоже."""
        self.assertFalse(sr.is_beby("Шисо зелёный 100 гр", "Беби листы"))
        self.assertFalse(sr.is_beby("Базилик фиолетовый 100 гр", ""))
        self.assertFalse(sr.is_beby("Хрустальная трава 100 гр", "Цветы"))
        self.assertTrue(sr.is_beby("Руккола 100 гр", ""))
        self.assertTrue(sr.is_beby("Микс салатов", "Беби листы"))

    def test_note_has_formula(self):
        rows = sr.apply_beby([self.row(10_390.0)],
                             {"X": [(date(2026, 10, 5), 7_250.0, 50)]})
        note = sr.beby_note(rows[0])
        self.assertIn("40%", note)
        self.assertIn("7 490", note)
        self.assertEqual(sr.beby_note(dict(beby_cut=0.0)), "")


class TestMatching(unittest.TestCase):
    """Строка листа → клиент 1С."""

    def index(self, *names):
        import sync_odata as so
        return so.build_token_index(list(names))

    def test_short_name_and_entity(self):
        idx = self.index("РУБЕЛЬ (ООО АВА ЦЕНТР)", "РЫБА МОЯ (ООО МАСА) ЭДО")
        self.assertEqual(sr.match_client("Рубель ООО Ава центр", idx), "РУБЕЛЬ (ООО АВА ЦЕНТР)")

    def test_single_word_row(self):
        """«Цыпочка» без юрлица — но кандидат один."""
        idx = self.index("ЦЫПОЧКА (ООО НОВЫЙ КОНЦЕПТ)", "РУБЕЛЬ (ООО АВА ЦЕНТР)")
        self.assertEqual(sr.match_client("Цыпочка", idx), "ЦЫПОЧКА (ООО НОВЫЙ КОНЦЕПТ)")

    def test_typo_in_sheet(self):
        """В листе «Просекко», в 1С «ПРОСЕКО»."""
        idx = self.index("ПРОСЕКО БАР (ООО ПР 11)", "РУБЕЛЬ (ООО АВА ЦЕНТР)")
        self.assertEqual(sr.match_client("Просекко Бар ООО ПР11", idx), "ПРОСЕКО БАР (ООО ПР 11)")

    def test_ambiguous_is_left_to_anna(self):
        """Двое подходят — лучше ничего, чем деньги чужому клиенту."""
        idx = self.index("РЫБА МОЯ (ООО МАСА) ЭДО", "РЫБА МОЯ (ООО СЫТОСТЬ)")
        self.assertIsNone(sr.match_client("Рыба моя", idx))

    def test_num(self):
        self.assertEqual(sr._num("12 127,00"), 12127.0)
        self.assertEqual(sr._num("2\xa0015,00"), 2015.0)
        self.assertIsNone(sr._num("-"))
        self.assertIsNone(sr._num(""))


class TestPlanSheet(unittest.TestCase):
    """Что скрипт пишет в лист, а о чём спрашивает (правила 1, 2, 8, 10)."""

    def sheet(self, rows):
        return dict(header=["Ресторан", "Юр лицо", "Создан", "Классифицкация",
                            "до какого числа считаем (+30 дней)", "Дарья", "Алена"],
                    managers={6: "Дарья Вольнова", 7: "Алена Черкашина"},
                    rows=rows, last_row=len(rows) + 1)

    def calc(self, **kw):
        base = dict(client="РУБЕЛЬ (ООО АВА ЦЕНТР)", kind="новый", event=date(2026, 10, 2),
                    window_end=date(2026, 10, 31), amount=5_472.0, tail_next_month=0.0,
                    gap=None, rhythm=None, orders=1, source="1С", manager=None,
                    beby_cut=0.0, beby_kg=0.0, beby_amount=0.0, amount_gross=5_472.0)
        base.update(kw)
        return base

    def test_fills_empty_until_column(self):
        """Колонка E пустая — ставим «по 31.10» (ответ Анны: дата события + 30 дней)."""
        sheet = self.sheet([dict(row=2, restaurant="Рубель", entity="ООО Ава центр",
                                 created="первый заказ 02.10", kind="новый", until="",
                                 sums={6: 5_472.0, 7: None})])
        plan = sr.plan_sheet([self.calc()], sheet, "2026-10")
        self.assertEqual(plan["until"], [(2, "по 31.10")])
        self.assertEqual(plan["conflicts"], [])

    def test_rewrites_human_sum_by_1c(self):
        """Сумма человека расходится с 1С — ставим свою, прежнюю в примечание.

        Решение Анны 12.10.2026 («1 вариант»): отчёт обязан сходиться с 1С.
        """
        sheet = self.sheet([dict(row=5, restaurant="Рубель", entity="ООО Ава центр",
                                 created="первый заказ 02.10", kind="новый", until="по 31.10",
                                 sums={6: 3_000.0, 7: None})])
        plan = sr.plan_sheet([self.calc()], sheet, "2026-10")
        self.assertEqual(len(plan["amount"]), 1)
        row, col, amount, note = plan["amount"][0]
        self.assertEqual((row, col, amount), (5, 6, 5_472.0))
        self.assertIn("было 3 000", note)
        self.assertIn("стало 5 472", note)
        self.assertEqual(len(plan["conflicts"]), 1)
        c = plan["conflicts"][0]
        self.assertEqual((c["row"], c["in_sheet"], c["by_1c"]), (5, 3_000.0, 5_472.0))
        self.assertEqual(c["manager"], "Дарья Вольнова")
        self.assertTrue(c["rewritten"])

    def test_zero_by_1c_does_not_erase_human_sum(self):
        """По 1С в окне пусто — чужую сумму нулём не затираем, только сообщаем."""
        sheet = self.sheet([dict(row=5, restaurant="Рубель", entity="ООО Ава центр",
                                 created="первый заказ 02.10", kind="новый", until="по 31.10",
                                 sums={6: 3_000.0, 7: None})])
        plan = sr.plan_sheet([self.calc(amount=0.0)], sheet, "2026-10")
        self.assertEqual(plan["amount"], [])
        self.assertFalse(plan["conflicts"][0]["rewritten"])

    def test_blank_sum_goes_to_manager_column(self):
        """Менеджер известен из бланка — сумма идёт в его колонку (правило 8)."""
        sheet = self.sheet([dict(row=7, restaurant="Рубель", entity="ООО Ава центр",
                                 created="первый заказ 02.10", kind="новый", until="по 31.10",
                                 sums={6: None, 7: None})])
        plan = sr.plan_sheet([self.calc(source="бланк", manager="Алена Черкашина")],
                             sheet, "2026-10")
        self.assertEqual(plan["amount"], [(7, 7, 5_472.0, "")])
        self.assertEqual(plan["ask"], [])

    def test_unknown_manager_is_asked_not_written(self):
        """Менеджера нет — сумму не пишем никуда, спрашиваем."""
        sheet = self.sheet([dict(row=7, restaurant="Рубель", entity="ООО Ава центр",
                                 created="первый заказ 02.10", kind="новый", until="по 31.10",
                                 sums={6: None, 7: None})])
        plan = sr.plan_sheet([self.calc()], sheet, "2026-10")
        self.assertEqual(plan["amount"], [])
        self.assertEqual([a["kind"] for a in plan["ask"]], ["нет суммы"])

    def test_client_missing_in_sheet_is_asked(self):
        """Новый по 1С без бланка в лист молча не попадает (правило 1)."""
        plan = sr.plan_sheet([self.calc()], self.sheet([]), "2026-10")
        self.assertEqual([a["kind"] for a in plan["ask"]], ["нет в листе"])
        self.assertIn("РУБЕЛЬ", plan["ask"][0]["client"])

    def test_summary_mentions_rhythm_for_candidates(self):
        """В сообщении Анне у кандидата видно молчание и обычный ритм (правило 11)."""
        row = self.calc(client="ГВИДОН (ООО КАМЕЛОТ) ЭДО", kind="кандидат", gap=54, rhythm=2)
        plan = sr.plan_sheet([row], self.sheet([]), "2026-10")
        text = sr.summary_text("2026-10", plan, [row])
        self.assertIn("ГВИДОН", text)
        self.assertIn("54 дн", text)
        self.assertIn("ритм 2", text)




class TestAnnaMarkup(unittest.TestCase):
    """Разбор размеченного прогона: кому сумма, как имя ложится в лист (12.10.2026)."""

    def test_manager_from_note(self):
        self.assertEqual(sr.manager_from_note("алены"), "Алена Черкашина")
        self.assertEqual(sr.manager_from_note("алена"), "Алена Черкашина")
        self.assertEqual(sr.manager_from_note("соня"), "София Хакимова")
        # поиск важнее сопровождения (правило 8)
        self.assertEqual(sr.manager_from_note("дарья поиск , алена сопровождение"),
                         "Дарья Вольнова")
        # прямой клиент на сопровождении Алёны — сумма всё равно Алёне (ответ Анны)
        self.assertEqual(sr.manager_from_note("прямой клиент , алена сопровождение"),
                         "Алена Черкашина")
        self.assertIsNone(sr.manager_from_note("прямой клиент"))
        self.assertIsNone(sr.manager_from_note(""))

    def test_split_client_name(self):
        self.assertEqual(sr.split_client_name("ЛЕСНОЙ РЕСТОРАН (OOO РЮМКА НА ЛЕСНОЙ) В 1С/dsbx"),
                         ("ЛЕСНОЙ РЕСТОРАН", "OOO РЮМКА НА ЛЕСНОЙ"))
        self.assertEqual(sr.split_client_name("БАГЕБИ (ООО ЛАЙНИК) в ЭДО с 09.10"),
                         ("БАГЕБИ", "ООО ЛАЙНИК"))
        self.assertEqual(sr.split_client_name("РЕЛОТ ООО ЭДО"), ("РЕЛОТ ООО", ""))
        self.assertEqual(sr.split_client_name("КОФЕ В ПАРКЕ ООО"), ("КОФЕ В ПАРКЕ ООО", ""))

    def test_excluded_client_drops_out(self):
        rows = [dict(client="Владимир Грин Хаус (нал)", kind="кандидат", gap=523,
                     amount=0.0, event=date(2026, 9, 24))]
        kept, dropped = sr.apply_excluded(
            rows, {"Владимир Грин Хаус (нал)": dict(reason="конкуренты убрать", rhythm_days=None)})
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0][1], "конкуренты убрать")

    def test_manual_rhythm_keeps_client_but_raises_threshold(self):
        """ГЛАВТОРГ: ритм 3 недели → возврат только после «ритм + 3 недели» (42 дня)."""
        rule = {"ООО ГЛАВТОРГ в 1С счет/dsbx": dict(reason="", rhythm_days=21)}
        early = [dict(client="ООО ГЛАВТОРГ в 1С счет/dsbx", kind="кандидат", gap=30,
                      amount=1.0, event=date(2026, 10, 1))]
        kept, dropped = sr.apply_excluded(early, rule)
        self.assertEqual(kept, [])
        self.assertIn("3 недели", dropped[0][1])
        late = [dict(client="ООО ГЛАВТОРГ в 1С счет/dsbx", kind="кандидат", gap=59,
                     amount=1.0, event=date(2026, 10, 1))]
        kept, dropped = sr.apply_excluded(late, rule)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_entity_change_is_not_a_new_client(self):
        """«NO SUGAR ИП БЕЛИКОВА» — тот же ресторан, что «NO Sugar (ИП ГУСЕВ)»:
        старая карточка затихла 07.09, новая начала 13.09."""
        rows = [dict(client="NO SUGAR ИП БЕЛИКОВА О.И.", kind="новый",
                     event=date(2026, 9, 13))]
        hist = {"NO SUGAR ИП БЕЛИКОВА О.И.": [(date(2026, 9, 13), 3_000.0)],
                "NO Sugar (ИП ГУСЕВ СЕРГЕЙ ЛЕОНИДОВИЧ)": [(date(2026, 5, 2), 2_000.0),
                                                           (date(2026, 9, 7), 2_000.0)],
                "РУБЕЛЬ (ООО АВА ЦЕНТР)": [(date(2026, 9, 11), 1_000.0)]}
        self.assertIn("NO SUGAR ИП БЕЛИКОВА О.И.", sr.entity_twins(rows, hist))

    def test_live_old_card_is_not_an_entity_change(self):
        """Старая карточка продолжает заказывать — значит это не переезд юрлица."""
        rows = [dict(client="РУБИ (ООО ЛУЧШИЕ ДРУЗЬЯ)", kind="новый",
                     event=date(2026, 9, 18))]
        hist = {"РУБИ (ООО ЛУЧШИЕ ДРУЗЬЯ)": [(date(2026, 9, 18), 5_756.0)],
                "ДРУЗЬЯ ПО КОФЕ ООО": [(date(2025, 3, 1), 900.0), (date(2026, 10, 10), 900.0)]}
        self.assertEqual(sr.entity_twins(rows, hist), {})

    def test_truly_new_client_has_no_twin(self):
        rows = [dict(client="РЕЛОТ ООО ЭДО", kind="новый", event=date(2026, 10, 1))]
        hist = {"РЕЛОТ ООО ЭДО": [(date(2026, 10, 1), 40_492.0)],
                "РУБЕЛЬ (ООО АВА ЦЕНТР)": [(date(2026, 9, 11), 1_000.0)],
                "КОФЕ В ПАРКЕ ООО": [(date(2026, 1, 1), 900.0)]}
        self.assertEqual(sr.entity_twins(rows, hist), {})

    def test_excluded_does_not_catch_namesakes(self):
        """«Алена физ лицо» в исключениях не должна убирать «Матвей физ лицо»."""
        rows = [dict(client="Матвей Физ лицо нал сразу", kind="кандидат", gap=368,
                     amount=0.0, event=date(2026, 9, 21))]
        kept, dropped = sr.apply_excluded(
            rows, {"Алена физ лицо НАЛ СРАЗУ": dict(reason="хз", rhythm_days=None)})
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])


class TestDashAndEntity(unittest.TestCase):
    """★12.10.2026: прочерк = чей клиент (правило 12), пометка юрлица (правило 13).

    Нашлось на живом листе: Гвидон вернулся 11.10 на 7 996, Maya взяла 4 225 — суммы
    не встали никуда, потому что бланка нет, а прочерк менеджера скрипт не читал.
    """

    def sheet(self, rows):
        return dict(header=["Ресторан", "Юр лицо", "Создан", "Классифицкация",
                            "до какого числа считаем (+30 дней)", "Дарья", "Алена"],
                    managers={6: "Дарья Вольнова", 7: "Алена Черкашина"},
                    rows=rows, last_row=len(rows) + 1)

    def row(self, **kw):
        base = dict(row=33, restaurant="Maya", entity="ООО Амазонка",
                    created="первый заказ 29.09", kind="новый", until="по 28.10",
                    sums={6: None, 7: None}, dashes=[])
        base.update(kw)
        return base

    def calc(self, **kw):
        base = dict(client="Maya (ООО АМАЗОНИКА)", kind="новый", event=date(2026, 9, 29),
                    window_end=date(2026, 10, 28), amount=4_225.0, tail_next_month=0.0,
                    gap=None, rhythm=None, orders=1, source="1С", manager=None,
                    beby_cut=0.0, beby_kg=0.0, beby_amount=0.0, amount_gross=4_225.0)
        base.update(kw)
        return base

    def test_dash_tells_whose_client(self):
        """Прочерк в колонке Алёны — значит клиент её, сумму ставим туда."""
        plan = sr.plan_sheet([self.calc()], self.sheet([self.row(dashes=[7])]), "2026-10")
        self.assertEqual(plan["amount"], [(33, 7, 4_225.0, "")])
        self.assertEqual(plan["ask"], [])
        self.assertEqual(plan["filled"][0]["manager"], "Алена Черкашина")
        self.assertTrue(plan["filled"][0]["by_dash"])

    def test_two_dashes_are_asked(self):
        """Прочерк в двух колонках ответа не даёт — спрашиваем Анну."""
        plan = sr.plan_sheet([self.calc()], self.sheet([self.row(dashes=[6, 7])]), "2026-10")
        self.assertEqual(plan["amount"], [])
        self.assertEqual([a["kind"] for a in plan["ask"]], ["нет суммы"])

    def test_blank_manager_wins_over_dash(self):
        """Бланк главнее прочерка: менеджер из бланка — ему и сумма (правило 8)."""
        plan = sr.plan_sheet([self.calc(source="бланк", manager="Дарья Вольнова")],
                             self.sheet([self.row(dashes=[7])]), "2026-10")
        self.assertEqual(plan["amount"], [(33, 6, 4_225.0, "")])

    def test_zero_amount_keeps_dash(self):
        """Окно закрылось, отгрузок в месяце нет — прочерк не трогаем и не спрашиваем."""
        plan = sr.plan_sheet([self.calc(amount=0.0)], self.sheet([self.row(dashes=[7])]), "2026-10")
        self.assertEqual(plan["amount"], [])
        self.assertEqual(plan["ask"], [])

    def test_empty_row_without_dash_is_asked(self):
        """Строка Гвидона: ни суммы, ни прочерка — сумма посчитана, но чья, спрашиваем."""
        row = self.row(row=37, restaurant="Гвидон ", entity="", created="", kind="", until="")
        plan = sr.plan_sheet([self.calc(client="ГВИДОН (ООО КАМЕЛОТ) ЭДО", kind="кандидат",
                                        event=date(2026, 10, 11), window_end=date(2026, 11, 9),
                                        gap=54, amount=7_996.0, amount_gross=7_996.0)],
                             self.sheet([row]), "2026-10")
        self.assertEqual(plan["amount"], [])
        ask = plan["ask"][0]
        self.assertEqual((ask["kind"], ask["row"], ask["amount"]), ("нет суммы", 37, 7_996.0))
        self.assertIn("НЕ ЗНАЮ, В ЧЬЮ КОЛОНКУ", sr.summary_text("2026-10", plan, []))

    def test_entity_of(self):
        """Юрлицо из названия карточки — то, что идёт в колонку «Юр лицо»."""
        cases = {"ГВИДОН (ООО КАМЕЛОТ) ЭДО": "ООО КАМЕЛОТ",
                 "ХОРСА ООО (Красота)": "ХОРСА ООО",
                 "ЛЕСНОЙ РЕСТОРАН (OOO РЮМКА НА ЛЕСНОЙ) В 1С/dsbx": "ООО РЮМКА НА ЛЕСНОЙ",
                 "ОШИ ИЗАКАЯ (АО Фалькон)": "АО Фалькон",
                 "Матвей Физ лицо нал сразу": "нал",
                 "Цыпочка": ""}
        for card, want in cases.items():
            self.assertEqual(sr.entity_of(card), want, card)

    def test_entity_marks_show_every_card(self):
        """У клиента две карточки — в примечании обе, с числом накладных и датой."""
        sr.CARDS.clear()
        sr.CARDS.update({
            "ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС": dict(inn="7733", docs=4, last=date(2026, 10, 6),
                                              sum=6_550.0, canon="ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС"),
            "причал чарли нал( комлекс) ООО": dict(inn="", docs=1, last=date(2026, 9, 12),
                                                   sum=3_275.0, canon="ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС")})
        try:
            row = self.row(row=14, restaurant="Причал Чарли", entity="")
            plan = sr.plan_sheet([self.calc(client="ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС")],
                                 self.sheet([row]), "2026-10")
            mark = plan["entities"][0]
            self.assertEqual(mark["row"], 14)
            self.assertIn("ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС", mark["note"])
            self.assertIn("причал чарли нал( комлекс) ООО", mark["note"])
            self.assertIn("4 накл., последняя 06.10", mark["note"])
            self.assertEqual(mark["in_sheet"], "")
        finally:
            sr.CARDS.clear()

    def test_entity_of_anna_is_not_overwritten(self):
        """Юрлицо, вписанное Анной, остаётся: план помечает, что ячейка занята."""
        sr.CARDS.clear()
        sr.CARDS.update({"Maya (ООО АМАЗОНИКА)": dict(inn="77", docs=1, last=date(2026, 10, 9),
                                                      sum=4_225.0, canon="Maya (ООО АМАЗОНИКА)")})
        try:
            plan = sr.plan_sheet([self.calc()], self.sheet([self.row()]), "2026-10")
            self.assertEqual(plan["entities"][0]["in_sheet"], "ООО Амазонка")
            self.assertEqual(plan["entities"][0]["entity"], "ООО АМАЗОНИКА")
        finally:
            sr.CARDS.clear()

    def test_sheet_columns_old_and_new_layout(self):
        """★12.10.2026 «База 1С» третьей колонкой: позиции ищем по шапке, не по номерам."""
        old_head = ["Ресторан", "Юр лицо", "Создан", "Классифицкация",
                    "до какого числа считаем (+30 дней)", "Дарья", "Алена"]
        cols = sr.sheet_columns(old_head)
        self.assertEqual((cols["entity"], cols["created"], cols["kind"], cols["until"]),
                         (2, 3, 4, 5))
        self.assertEqual(sorted(sr.manager_columns(old_head, cols["until"] + 1)), [6, 7])

        new_head = ["Ресторан", "Юр лицо", "База 1С", "Создан", "Классифицкация",
                    "до какого числа считаем (+30 дней)", "Дарья", "Алена"]
        cols = sr.sheet_columns(new_head)
        self.assertEqual((cols["entity"], cols["base"], cols["created"], cols["kind"],
                          cols["until"]), (2, 3, 4, 5, 6))
        self.assertEqual(sorted(sr.manager_columns(new_head, cols["until"] + 1)), [7, 8])

    def test_plan_writes_into_columns_of_this_sheet(self):
        """Лист с «База 1С» на C: «до какого числа» пишем в F, юрлицо в B, базу в C."""
        head = ["Ресторан", "Юр лицо", "База 1С", "Создан", "Классифицкация",
                "до какого числа считаем (+30 дней)", "Дарья", "Алена"]
        cols = sr.sheet_columns(head)
        sheet = dict(header=head, cols=cols, managers={7: "Дарья Вольнова", 8: "Алена Черкашина"},
                     rows=[dict(row=33, restaurant="Maya", entity="", created="первый заказ 29.09",
                                kind="новый", until="", sums={7: None, 8: None}, dashes=[8])],
                     last_row=33)
        sr.CARDS.clear()
        sr.CARDS.update({"Maya (ООО АМАЗОНИКА)": dict(inn="77", docs=2, last=date(2026, 10, 9),
                                                      sum=4_225.0, canon="Maya (ООО АМАЗОНИКА)",
                                                      bases={"volodihina": 2})})
        try:
            plan = sr.plan_sheet([self.calc()], sheet, "2026-10")
            self.assertEqual(plan["until"], [(33, "по 28.10")])
            self.assertEqual(plan["amount"], [(33, 8, 4_225.0, "")])   # прочерк у Алёны
            self.assertEqual(plan["entities"][0]["entity"], "ООО АМАЗОНИКА")
            self.assertEqual(plan["bases"][0]["text"], "Володихина")
        finally:
            sr.CARDS.clear()

    def test_match_by_entity_finds_other_name(self):
        """★«Шануар» + «ООО ПУАССОН» → ПУАССОН КЕЙТЕРИНГ: названия разные, юрлицо одно."""
        sr.CARDS.clear()
        sr.CARDS.update({
            "ПУАССОН КЕЙТЕРИНГ (ООО ПУАССОН)": dict(inn="77", docs=21, last=date(2026, 10, 10),
                                                    sum=1.0, canon="ПУАССОН КЕЙТЕРИНГ (ООО ПУАССОН)",
                                                    bases={"perfilev": 21}),
            "Пуассон Кейтеринг (ООО МЕЗОН)": dict(inn="78", docs=2, last=date(2026, 10, 1),
                                                  sum=1.0, canon="Пуассон Кейтеринг (ООО МЕЗОН)",
                                                  bases={"perfilev": 2})})
        try:
            self.assertEqual(sr.match_by_entity("ООО ПУАССОН"), "ПУАССОН КЕЙТЕРИНГ (ООО ПУАССОН)")
            self.assertEqual(sr.match_by_entity("ООО МЕЗОН"), "Пуассон Кейтеринг (ООО МЕЗОН)")
            self.assertIsNone(sr.match_by_entity(""))
        finally:
            sr.CARDS.clear()

    def test_match_by_entity_refuses_one_entity_two_names(self):
        """Одно юрлицо на разных названиях (ЛУЖНИКИ и МАГАДАН — ООО ВОСТОК) — без ответа."""
        sr.CARDS.clear()
        sr.CARDS.update({
            "ЛУЖНИКИ (ООО ВОСТОК)": dict(inn="7", docs=5, last=date(2026, 10, 1), sum=1.0,
                                         canon="ЛУЖНИКИ (ООО ВОСТОК)", bases={"gubarev": 5}),
            "МАГАДАН (ООО ВОСТОК)": dict(inn="7", docs=5, last=date(2026, 10, 1), sum=1.0,
                                         canon="МАГАДАН (ООО ВОСТОК)", bases={"gubarev": 5})})
        try:
            self.assertIsNone(sr.match_by_entity("ООО ВОСТОК"))
        finally:
            sr.CARDS.clear()

    def test_row_without_event_still_gets_base(self):
        """★Анна «почему 3 без указанной базы?»: событие не нужно, нужна карточка в 1С."""
        sr.CARDS.clear()
        sr.CARDS.update({"Vino e Cucina (ООО ИНТЕКС)": dict(
            inn="77", docs=9, last=date(2026, 10, 7), sum=1.0,
            canon="Vino e Cucina (ООО ИНТЕКС)", bases={"gubarev": 9})})
        try:
            row = self.row(row=4, restaurant="Vino e Cucina", entity="ООО ИНТЕКС")
            plan = sr.plan_sheet([], self.sheet([row]), "2026-10",
                                 all_clients=["Vino e Cucina (ООО ИНТЕКС)"])
            self.assertEqual([u["row"] for u in plan["unmatched_sheet"]], [4])
            self.assertEqual(plan["bases"][0]["text"], "Губарев")
            self.assertEqual(plan["entities"][0]["entity"], "ООО ИНТЕКС")
        finally:
            sr.CARDS.clear()

    def test_row_unknown_in_1c_gets_no_base(self):
        """Карточки в 1С нет — базу не выдумываем (Шануар: название не сходится)."""
        sr.CARDS.clear()
        row = self.row(row=5, restaurant="Шануар", entity="ООО ПУАССОН")
        plan = sr.plan_sheet([], self.sheet([row]), "2026-10", all_clients=["РУБЕЛЬ (ООО АВА ЦЕНТР)"])
        self.assertEqual(plan["bases"], [])
        self.assertEqual(plan["entities"], [])

    def test_base_mark_one_base(self):
        """Колонка «База 1С»: одна база — её имя и её цвет (просьба Анны 12.10)."""
        sr.CARDS.clear()
        sr.CARDS.update({"Maya (ООО АМАЗОНИКА)": dict(inn="77", docs=2, last=date(2026, 10, 9),
                                                      sum=4_225.0, canon="Maya (ООО АМАЗОНИКА)",
                                                      bases={"volodihina": 2})})
        try:
            plan = sr.plan_sheet([self.calc()], self.sheet([self.row()]), "2026-10")
            mark = plan["bases"][0]
            self.assertEqual((mark["row"], mark["text"]), (33, "Володихина"))
            self.assertEqual(mark["color"], sr.BASE_COLORS["volodihina"])
            self.assertEqual(mark["detail"], "Володихина — 2 накл.")
        finally:
            sr.CARDS.clear()

    def test_base_mark_two_bases(self):
        """Клиент грузится из двух баз — обе в ячейке, главная первой, цвет отдельный."""
        sr.CARDS.clear()
        sr.CARDS.update({
            "РЕЛОТ ООО ЭДО": dict(inn="77", docs=3, last=date(2026, 10, 12), sum=1.0,
                                  canon="РЕЛОТ ООО ЭДО", bases={"volodihina": 3}),
            "РЕЛОТ ООО": dict(inn="77", docs=7, last=date(2026, 9, 1), sum=1.0,
                              canon="РЕЛОТ ООО ЭДО", bases={"gubarev": 7})})
        try:
            row = self.row(row=43, restaurant="РЕЛОТ ООО", entity="")
            plan = sr.plan_sheet([self.calc(client="РЕЛОТ ООО ЭДО")], self.sheet([row]), "2026-10")
            mark = plan["bases"][0]
            self.assertEqual(mark["text"], "Губарев + Володихина")
            self.assertEqual(mark["color"], sr.MIXED_COLOR)
        finally:
            sr.CARDS.clear()

    def test_base_column_is_free(self):
        """Колонка базы не должна налезать на колонки менеджеров и на ИТОГ."""
        sheet = self.sheet([])
        self.assertGreater(sr.COL_BASE, max(sheet["managers"]) + 1)

    def test_auto_rhythm_counts_from_own_pace(self):
        """ГЛАВТОРГ (12.10): «свой ритм + 3 недели» — ритм берём из 1С, не из листа."""
        rule = {"ООО ГЛАВТОРГ в 1С счет/dsbx": dict(reason="ритм", rhythm_days="auto")}
        early = [dict(client="ООО ГЛАВТОРГ в 1С счет/dsbx", kind="кандидат", gap=30,
                      rhythm=14, amount=5_000.0, event=date(2026, 10, 5))]
        kept, dropped = sr.apply_excluded(early, rule)
        self.assertEqual(kept, [])                      # 14 + 21 = 35 дней ещё не прошли
        late = [dict(client="ООО ГЛАВТОРГ в 1С счет/dsbx", kind="кандидат", gap=40,
                     rhythm=14, amount=5_000.0, event=date(2026, 10, 5))]
        kept, dropped = sr.apply_excluded(late, rule)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])



class TestGroupCardsIndex(unittest.TestCase):
    """★13.10.2026: склейка ускорена индексом по словам имени — результат тот же.

    Старая версия сравнивала каждую группу с каждой (2 753 карточки 1С → 62 с, а на
    сервере прогон не укладывался в cron). Индекс отсекает группы без общего слова:
    и опечатка, и вложенность общего слова требуют. Проверяем то, что индекс мог бы
    сломать, — склейку ВТОРЫМ проходом, когда группа уже получила новое имя.
    """

    def test_second_pass_merge_still_works(self):
        """«Причал Чарли нал» прилипает к паре КОМПЛЕКС/комлекс только вторым проходом."""
        cards = [("причал чарли нал( комлекс) ООО", ""),
                 ("ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС", "5050057890"),
                 ("Причал Чарли нал", "")]
        groups = sr.group_cards(cards)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(next(iter(groups.values()))), 3)

    def test_different_inn_still_never_merges(self):
        """Разные непустые ИНН не склеиваются, даже когда название вложено."""
        cards = [("ПРИЧАЛ ООО", "5032113800"), ("ПРИЧАЛ ЧАРЛИ ООО КОМПЛЕКС", "5050057890")]
        self.assertEqual(len(sr.group_cards(cards)), 2)

    def test_no_common_word_no_merge(self):
        """Группы без общего слова индекс даже не сравнивает — и не должен."""
        cards = [("ОРАНДЖ ООО", ""), ("ДОЛМА НАЛ", ""), ("БАГЕБИ (ООО ЛАЙНИК)", "")]
        self.assertEqual(len(sr.group_cards(cards)), 3)

    def test_tokens_are_cached(self):
        """key_tokens спрашивают миллионы раз — он обязан быть с кешем."""
        self.assertTrue(hasattr(sr.key_tokens, "cache_info"))


class TestBlanks(unittest.TestCase):
    """Журнал бланков от orders-bot: бланк — слово менеджера, оно главнее 1С."""

    def calc(self, **kw):
        base = dict(client="KOJI (ООО КАЛАШНЫЙ) ЭДО", kind="кандидат", source="1С",
                    manager=None, amount=5_000.0, event=date(2026, 9, 8))
        base.update(kw)
        return base

    def blank(self, **kw):
        base = dict(kind="вернули", client="Koji", entity="Koji ООО КАЛАШНЫЙ",
                    manager="", date=date(2026, 9, 8))
        base.update(kw)
        return base

    def test_blank_sets_kind_and_source(self):
        """Есть бланк — вносим сразу: вид из бланка, догадка по 1С не нужна."""
        rows = sr.attach_blanks([self.calc()], [self.blank()])
        self.assertEqual((rows[0]["kind"], rows[0]["source"]), ("вернули", "бланк"))

    def test_blank_author_becomes_manager(self):
        """Автор бланка → менеджер: «соня» в журнале значит София (правило 8)."""
        rows = sr.attach_blanks([self.calc()], [self.blank(manager="соня")])
        self.assertEqual(rows[0]["manager"], "София Хакимова")

    def test_unknown_author_is_kept_as_is(self):
        """Автор не из реестра — пишем как есть, Анна поймёт по имени."""
        rows = sr.attach_blanks([self.calc()], [self.blank(manager="Пётр Новый")])
        self.assertEqual(rows[0]["manager"], "Пётр Новый")

    def test_empty_author_does_not_erase_manager(self):
        """Строки, восстановленные из логов, автора не знают — не затираем своего."""
        rows = sr.attach_blanks([self.calc(manager="Дарья Вольнова")], [self.blank()])
        self.assertEqual(rows[0]["manager"], "Дарья Вольнова")
        self.assertEqual(rows[0]["source"], "бланк")

    def test_blank_found_by_entity_only(self):
        """«Шануар» в 1С зовётся «ПУАССОН КЕЙТЕРИНГ (ООО ПУАССОН)» — ищем по юрлицу."""
        rows = sr.attach_blanks(
            [self.calc(client="ПУАССОН КЕЙТЕРИНГ (ООО ПУАССОН)")],
            [self.blank(client="Шануар", entity="Пуассон кейтеринг (ООО ПУАССОН)")])
        self.assertEqual(rows[0]["source"], "бланк")


class TestAuthorsFromSheets(unittest.TestCase):
    """Кто ведёт клиента, когда автора бланка нет: смотрим прошлые листы отчёта."""

    def sheets(self, data):
        """{название листа: строки} → подменённые read_sheet и worksheet."""
        managers = {7: "Дарья Вольнова", 8: "Алена Черкашина", 12: "Виолетта Караханова"}

        def read(ws):
            rows = []
            for i, (name, ent, sums, dashes) in enumerate(data[ws], start=2):
                rows.append(dict(row=i, restaurant=name, entity=ent, created="", kind="",
                                 until="", sums={c: sums.get(c) for c in managers},
                                 dashes=dashes))
            return dict(managers=managers, rows=rows, header=[], cols=None)

        ss = mock.Mock()
        ss.worksheet = lambda title: (title if title in data
                                      else self.fail(f"нет листа {title}"))
        return ss, mock.patch.object(sr, "read_sheet", side_effect=read)

    def test_manager_from_column_with_sum(self):
        data = {"сентябрь-октябрь": [("Главторг", "ООО ГЛАВТОРГ", {8: 4_991.0}, [])],
                "август-сентябрь": []}
        ss, patch = self.sheets(data)
        with patch:
            known = sr.authors_from_sheets(ss, "2026-10")
        self.assertEqual(known["Главторг ООО ГЛАВТОРГ"][0], "Алена Черкашина")

    def test_dash_counts_as_an_answer(self):
        """Прочерк — тоже «клиент мой» (правило 12), значит менеджер известен."""
        data = {"сентябрь-октябрь": [("Райт хопс", "ООО Райт Хопс", {}, [7])],
                "август-сентябрь": []}
        ss, patch = self.sheets(data)
        with patch:
            known = sr.authors_from_sheets(ss, "2026-10")
        self.assertEqual(known["Райт хопс ООО Райт Хопс"][0], "Дарья Вольнова")

    def test_two_managers_in_a_row_tell_nothing(self):
        """Сумма у двоих — чей клиент, непонятно: такую строку не берём."""
        data = {"сентябрь-октябрь": [("Орандж", "ООО АНУТА", {7: 100.0, 12: 200.0}, [])],
                "август-сентябрь": []}
        ss, patch = self.sheets(data)
        with patch:
            known = sr.authors_from_sheets(ss, "2026-10")
        self.assertEqual(known, {})

    def test_missing_sheet_is_skipped(self):
        """Листа за прошлый месяц может не быть — это не повод падать."""
        data = {"сентябрь-октябрь": [("Долма", "долма", {7: 3_854.0}, [])]}
        ss, patch = self.sheets(data)
        ss.worksheet = lambda title: (title if title in data
                                      else (_ for _ in ()).throw(gspread.WorksheetNotFound()))
        with patch:
            known = sr.authors_from_sheets(ss, "2026-10")
        self.assertEqual(len(known), 1)


class TestPendingRow(unittest.TestCase):
    """Строка, которую бот вставляет в лист: вид и колонка суммы (13.10.2026)."""

    COLS = {"restaurant": 1, "entity": 2, "base": 3, "created": 4, "kind": 5, "until": 6}
    MANAGERS = {7: "Дарья Вольнова", 8: "Алена Черкашина", 13: "Анна Кононенко (РОП)"}
    SUM_COL = 15

    def row(self, **kw):
        r = dict(client="ТЭМУ (ООО ИНВЕСТИЦИОННЫЙ ЦЕНТР)", kind="кандидат",
                 event=date(2026, 10, 13), window_end=date(2026, 11, 11),
                 amount=4_145.0, source="1С", manager=None)
        r.update(kw)
        return sr.pending_row(r, self.COLS, self.SUM_COL, self.MANAGERS)

    def test_guess_waits_for_confirmation(self):
        """Догадка 1С без бланка так и остаётся «ждёт подтверждения», сумма — за ИТОГ."""
        row, col = self.row()
        self.assertEqual(row[self.COLS["kind"] - 1], sr.PENDING_MARK)
        self.assertEqual(col, self.SUM_COL)
        self.assertEqual(row[self.SUM_COL - 1], 4_145.0)

    def test_answer_from_anna_sets_the_kind(self):
        """Анна нажала «вношу» — вид известен, «ждёт подтверждения» писать нельзя."""
        row, _ = self.row(source="ответ Анны")
        self.assertEqual(row[self.COLS["kind"] - 1], "вернули")
        self.assertEqual(row[self.COLS["created"] - 1], "вернули 13.10")

    def test_blank_puts_money_in_manager_column(self):
        """Бланк менеджера: вид «новый», сумма — в его колонку, иначе её нет в итоге."""
        row, col = self.row(kind="новый", source="бланк", manager="Алена Черкашина")
        self.assertEqual(row[self.COLS["kind"] - 1], "новый")
        self.assertEqual(row[self.COLS["created"] - 1], "первый заказ 13.10")
        self.assertEqual(col, 8)
        self.assertEqual(row[7], 4_145.0)
        self.assertEqual(row[self.SUM_COL - 1], "")

    def test_unknown_manager_name_goes_behind_total(self):
        """Имя, которого нет в шапке листа, в колонку не превращаем."""
        row, col = self.row(source="бланк", manager="Марина")
        self.assertEqual(col, self.SUM_COL)

    def test_one_order_candidate_is_marked_as_rare(self):
        """«Разовый» подтверждён кнопкой — так и пишем (правило 3)."""
        row, _ = self.row(kind="разовый", source="ответ Анны")
        self.assertEqual(row[self.COLS["kind"] - 1], "разовый")


class TestApplyPlanClearsBotColumn(unittest.TestCase):
    """Сумма уехала в колонку менеджера — служебную «сумма по 1С (бот)» чистим."""

    class Ws:
        def __init__(self):
            self.body = []

        def batch_update(self, body, value_input_option=None):
            self.body = body

        def update_note(self, *a, **k):
            pass

    COLS = {"restaurant": 1, "entity": 2, "base": 3, "created": 4, "kind": 5, "until": 6}
    MANAGERS = {7: "Дарья Вольнова", 8: "Алена Черкашина"}

    def sheet(self, rows=()):
        return {"cols": self.COLS, "managers": self.MANAGERS, "header": [],
                "rows": list(rows), "last_row": 10}

    def plan(self, col):
        return {"until": [], "amount": [(58, col, 4_145.0, "")], "ask": [],
                "conflicts": [], "entities": [], "bases": []}

    def ranges(self, col, rows=()):
        ws = self.Ws()
        sr.apply_plan(ws, self.plan(col), self.sheet(rows))
        return {b["range"]: b["values"][0][0] for b in ws.body}

    def test_manager_column_clears_service_cell(self):
        """ТЭМУ 13.10.2026: 4 145 ₽ встали Алёне, а в J58 висел тот же дубль."""
        got = self.ranges(8, rows=[dict(row=58, sums={7: None, 8: None}, bot=4_145.0)])
        self.assertEqual(got["H58"], 4_145.0)
        self.assertEqual(got["J58"], "")          # колонка менеджеров 7-8 → бот в 10

    def test_service_cell_itself_is_not_cleared(self):
        """Пока менеджер неизвестен, сумма живёт в служебной колонке — не чистим её."""
        got = self.ranges(10, rows=[dict(row=58, sums={7: None, 8: None}, bot=4_145.0)])
        self.assertEqual(got["J58"], 4_145.0)
        self.assertEqual(len(got), 1)

    def test_dash_alone_does_not_clear_the_draft(self):
        """Прочерк — ещё не сумма: черновик бота пока нужен."""
        got = self.ranges(10, rows=[dict(row=58, sums={7: None, 8: None}, bot=4_145.0,
                                         dashes=[8])])
        self.assertEqual(got["J58"], 4_145.0)

    def test_draft_cleared_when_money_already_in_sheet(self):
        """★ТЭМУ: сумма встала у Алёны ещё в прошлый прогон, а дубль висел за ИТОГ."""
        ws = self.Ws()
        sheet = self.sheet([dict(row=58, sums={7: None, 8: 4_145.0}, bot=4_145.0)])
        plan = {"until": [], "amount": [], "ask": [], "conflicts": [],
                "entities": [], "bases": []}
        sr.apply_plan(ws, plan, sheet)
        got = {b["range"]: b["values"][0][0] for b in ws.body}
        self.assertEqual(got, {"J58": ""})


if __name__ == "__main__":
    unittest.main(verbosity=2)
