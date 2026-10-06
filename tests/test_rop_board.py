"""Тесты борда РОПа — разбор данных без сети.

Проверяем то, на чём борд легко соврал бы: чтение планов из НАСТРОЕК (строка
плана новых клиентов называется «Новые клиенты — оплаты (план)» и не должна
попасть в план оплат), хвост комментария Битрикса, дату из текста менеджера,
нормализацию имён для поиска дублей и разметку статусов по стадиям.
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rop_board as rb


class FakeWorksheet:
    def __init__(self, values, title="лист", wsid=1):
        self._values = values
        self.title = title
        self.id = wsid

    def get_all_values(self):
        return self._values


class FakeSpreadsheet:
    def __init__(self, sheets):
        self._sheets = sheets

    def worksheet(self, title):
        for ws in self._sheets:
            if ws.title == title:
                return ws
        raise KeyError(title)

    def worksheets(self):
        return list(self._sheets)


SETTINGS = [
    ["НАСТРОЙКИ — Расчётный период и планы", "", "", ""],
    ["", "", "", ""],
    ["РАСЧЁТНЫЙ ПЕРИОД", "", "", ""],
    ["Месяц и год расчёта", "Сентябрь 2026", "", ""],
    ["", "", "", ""],
    ["Сотрудник / группа", "Показатель", "План (₽)", "Примечание"],
    ["Менеджеры поиска (каждый)", "Оборот новых клиентов (план)", "210000", ""],
    ["Алена Черкашина", "Оплаты ресторанов (план)", "4174949", ""],
    ["София Хакимова (стажёр)", "Оборот новых клиентов (план)", "105000", ""],
    ["Виолетта Караханова (стажёр)", "Оборот новых клиентов (план)", "105000", ""],
    ["РОП Кононенко А. (отдел)", "Новые клиенты — оплаты (план)", "620000", ""],
    ["РОП Кононенко А. (отдел)", "Оплаты (план)", "9500000", ""],
    ["РОП Кононенко А. (отдел)", "Оборот (план)", "9500000", ""],
]


class TestPlans(unittest.TestCase):
    def setUp(self):
        self.plans = rb.read_plans(FakeSpreadsheet([FakeWorksheet(SETTINGS, "НАСТРОЙКИ")]))

    def test_new_plan_not_confused_with_payments(self):
        """«Новые клиенты — оплаты (план)» → план новых продаж, не план оплат."""
        self.assertEqual(self.plans["new"], 620000)
        self.assertEqual(self.plans["postup"], 9500000)
        self.assertEqual(self.plans["oborot"], 9500000)

    def test_trainee_plans_are_personal(self):
        self.assertEqual(self.plans["search_default"], 210000)
        self.assertEqual(self.plans["personal"]["София"], 105000)
        self.assertEqual(self.plans["personal"]["Виолетта"], 105000)

    def test_support_plan_is_not_a_search_plan(self):
        """План оплат сопровождения не должен стать планом новых продаж Алёны."""
        self.assertNotIn("Алена", self.plans["personal"])

    def test_period_label(self):
        self.assertEqual(self.plans["period"], "Сентябрь 2026")


SALES = [
    ["Ресторан", "Юр лицо", "Создан", "Классифицкация", "до какого числа",
     "Дарья", "Алена", "Ксения", "Лилия", "София", "Виолетта", "Анна", "ИТОГ"],
    ["ЛЕСНОЙ", "", "первый заказ 06.09", "новый", "по 04.10",
     "30\xa0250,00", "", "", "", "", "", "", ""],
    ["ЗЭТТА", "", "первый заказ 07.09", "новый", "по 05.10",
     "", "", "-", "", "", "1\xa0000,00", "", ""],
    ["", "", "итоги ниже — колонка A пустая", "", "", "999999", "", "", "", "", "", "", ""],
]


class TestManagerSales(unittest.TestCase):
    def test_sums_by_manager_column(self):
        book = FakeSpreadsheet([FakeWorksheet(SALES, "август-сентябрь")])
        totals, meta, clients = rb.manager_sales(book, datetime(2026, 9, 28))
        self.assertEqual(totals["Дарья"], 30250)
        self.assertEqual(totals["Виолетта"], 1000)
        self.assertEqual(totals["Ксения"], 0)          # «-» — это не сумма
        self.assertEqual(meta["rows"], 2)              # итоговый блок листа не считаем
        self.assertTrue(meta["exact"])
        self.assertEqual(clients["Дарья"][0]["sum"], 30250)

    def test_sheet_of_current_month_is_picked(self):
        book = FakeSpreadsheet([FakeWorksheet(SALES, "июль-август", 1),
                                FakeWorksheet(SALES, "август-сентябрь", 2),
                                FakeWorksheet(SALES, "август-сентябрь КОПИЯ", 3)])
        ws, exact = rb.pick_sales_sheet(book, datetime(2026, 9, 28))
        self.assertEqual(ws.title, "август-сентябрь")
        self.assertTrue(exact)

    def test_missing_month_falls_back_and_flags(self):
        book = FakeSpreadsheet([FakeWorksheet(SALES, "июль-август", 1)])
        ws, exact = rb.pick_sales_sheet(book, datetime(2026, 9, 28))
        self.assertEqual(ws.title, "июль-август")
        self.assertFalse(exact)                        # борд покажет предупреждение

    def test_last_year_sheet_with_same_month_is_not_picked(self):
        """★Регрессия 02.10.2026: названия месяцев повторяются каждый год.

        В книге лежат прошлогодние «конец сентября-октярь» и «Октябрь (конец)-Ноябрь»,
        а листа за октябрь 2026 ещё нет. Раньше борд брал прошлогодний лист и показывал
        его 496 355 ₽ как новые продажи октября 2026.
        """
        titles = ["конец сентября-октярь", "Октябрь (конец)-Ноябрь", "декабрь-январь",
                  "январь-февраль", "февраль-март", "март-апрель", "апрель-май",
                  "май-июнь", "июнь-июль", "июль-август", "август-сентябрь"]
        book = FakeSpreadsheet([FakeWorksheet(SALES, t, i) for i, t in enumerate(titles)])
        ws, exact = rb.pick_sales_sheet(book, datetime(2026, 10, 2))
        self.assertEqual(ws.title, "август-сентябрь")   # самый правый, а не прошлогодний
        self.assertFalse(exact)

    def test_new_month_sheet_is_picked_once_created(self):
        titles = ["Октябрь (конец)-Ноябрь", "июль-август", "август-сентябрь",
                  "сентябрь-октябрь"]
        book = FakeSpreadsheet([FakeWorksheet(SALES, t, i) for i, t in enumerate(titles)])
        ws, exact = rb.pick_sales_sheet(book, datetime(2026, 10, 2))
        self.assertEqual(ws.title, "сентябрь-октябрь")
        self.assertTrue(exact)

    def test_no_sheet_means_no_numbers(self):
        """Нет листа месяца — суммы не отдаём вовсе, чтобы не выдать чужой период."""
        book = FakeSpreadsheet([FakeWorksheet(SALES, "июль-август", 1)])
        totals, meta, clients = rb.manager_sales(book, datetime(2026, 10, 2))
        self.assertFalse(meta["exact"])
        self.assertEqual(meta["rows"], 0)
        self.assertTrue(all(v is None for v in totals.values()))
        self.assertFalse(clients)


class TestComments(unittest.TestCase):
    def test_bb_codes_stripped(self):
        raw = "[p] [b]28.09.26[/b] не дозвон [/p][p]26.09 шеф просил прайс[/p]"
        self.assertEqual(rb.clean_bb(raw), ["28.09.26", "не дозвон", "26.09 шеф просил прайс"])

    def test_last_note_keeps_history_tail(self):
        raw = "[p]01.09 первый контакт[/p][p]20.09 дегустация[/p][p]28.09 не дозвон[/p]"
        note = rb.last_note(raw)
        self.assertIn("28.09 не дозвон", note)
        self.assertIn("20.09 дегустация", note)

    def test_empty_comment(self):
        self.assertEqual(rb.last_note(""), "")
        self.assertEqual(rb.last_note(None), "")

    def test_date_from_text(self):
        today = datetime(2026, 9, 28)
        self.assertEqual(rb.note_date("28.09-созвонилась с шефом", today),
                         datetime(2026, 9, 28))

    def test_future_date_ignored(self):
        today = datetime(2026, 9, 28)
        self.assertEqual(rb.note_date("перезвонить 15.10 после обеда · 20.09 был звонок",
                                      today), datetime(2026, 9, 20))

    def test_no_date(self):
        self.assertIsNone(rb.note_date("нет информации", datetime(2026, 9, 28)))


class TestTitles(unittest.TestCase):
    def test_duplicates_match_after_normalisation(self):
        self.assertEqual(rb.norm_title("Хуан ( Juan)"), rb.norm_title("Juan (хуан)"))

    def test_legal_form_ignored(self):
        self.assertEqual(rb.norm_title("Просекко бар Pr11 (ООО Пр 11)"),
                         rb.norm_title("просекко pr11 пр 11 бар"))

    def test_test_cards_detected(self):
        self.assertTrue(rb.TEST_TITLE.search("РЕСТОРАН ТЕСТ"))
        self.assertTrue(rb.TEST_TITLE.search("ресторан теремок тест"))
        self.assertIsNone(rb.TEST_TITLE.search("Тестораны Ко"))


class TestStages(unittest.TestCase):
    def test_every_stage_has_status(self):
        for stage, status in rb.STAGE_STATUS.items():
            self.assertIn(status, rb.STATUS_TITLES, stage)

    def test_closed_stages_are_marked_out_or_won(self):
        for stage in rb.CLOSED_STAGES:
            self.assertIn(rb.STAGE_STATUS[stage], ("out", "obj", "won"), stage)

    def test_first_order_stage_is_push(self):
        self.assertEqual(rb.STAGE_STATUS["UC_0LGKWV"], "push")

    def test_razobrat_stage_asks_to_fill_crm(self):
        self.assertEqual(rb.STAGE_STATUS["UC_ZX1F5K"], "fill")


class TestNumbers(unittest.TestCase):
    def test_russian_money(self):
        self.assertEqual(rb.num("30\xa0250,00"), 30250.0)
        self.assertEqual(rb.num("1 000,50"), 1000.5)

    def test_placeholders_are_zero(self):
        for empty in ("", "-", "—", None):
            self.assertEqual(rb.num(empty), 0.0)

    def test_first_name(self):
        self.assertEqual(rb.first_name("Дарья Вольнова"), "Дарья")
        self.assertEqual(rb.first_name(""), "")


class TestRender(unittest.TestCase):
    def test_template_has_data_marker(self):
        with open(rb.TEMPLATE, encoding="utf-8") as f:
            self.assertIn("/*__DATA__*/", f.read())

    def test_render_injects_json(self):
        html = rb.render({"period_label": "Сентябрь 2026", "pace": 0.93})
        self.assertIn('"period_label": "Сентябрь 2026"', html)
        self.assertNotIn("/*__DATA__*/", html)


class TestSummary(unittest.TestCase):
    DATA = {
        "period_label": "Сентябрь 2026", "as_of": "28 сентября", "pace": 0.93,
        "kpi": {"oborot": {"fact": 7511309, "plan": 9500000},
                "postup": {"fact": None, "plan": 9500000},
                "new": {"fact": 442819, "plan": 620000},
                "tastings": {"count": 39, "in_work": 65, "empty": 21, "push": 10, "won": 0}},
        "flags": [{"kind": "crit", "text": "Лилия 8% плана"}],
    }

    def test_summary_mentions_facts_and_link(self):
        text = rb.summary_text(self.DATA, "https://example.test/b/x/")
        self.assertIn("Оборот: 7 511 309 ₽", text)
        self.assertIn("79% плана", text)
        self.assertIn("https://example.test/b/x/", text)
        self.assertIn("Лилия 8% плана", text)

    def test_missing_source_is_reported_not_zeroed(self):
        """Касса не ответила — пишем «нет данных», а не 0 ₽."""
        text = rb.summary_text(self.DATA)
        self.assertIn("Оплаты: нет данных", text)
        self.assertNotIn("Оплаты: 0", text)


if __name__ == "__main__":
    unittest.main()


DATA_SHEET = [
    ["ДАННЫЕ — ИП Губарев", "", "", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", "", "", ""],
    ["Контрагент", "Долг начало", "Увеличение", "Уменьшение", "Долг конец",
     "Менеджер поиска", "Менеджер сопровожд.", "Тип клиента", "Беби-листы",
     "Скорр. оплаты", "Статус", "Оборот"],
    ["САВОЙ", "0", "100 000", "88 757", "0", "Дарья", "Алена Черкашина", "Ресторан",
     "36 390", "52 367", "", ""],
    ["РУМИ", "0", "20 000", "18 825", "0", "", "Алена Черкашина", "Ресторан",
     "0", "18 825", "", ""],
    ["КОНКУРЕНТ", "0", "5 000", "5 000", "0", "", "Алена Черкашина", "Конкурент",
     "0", "5 000", "", ""],
    ["ФИРМА", "0", "7 000", "7 000", "0", "", "Ия Шарашанидзе", "Фирма",
     "0", "7 000", "", ""],
]


class TestSupportPayments(unittest.TestCase):
    """Оплаты сопровождения — как в СВОДНОЙ: сумма по ресторанам этого менеджера."""

    def setUp(self):
        self.book = FakeSpreadsheet([FakeWorksheet(DATA_SHEET, "ДАННЫЕ_Губарев"),
                                     FakeWorksheet(DATA_SHEET, "ДАННЫЕ_Перфильев")])

    def test_only_restaurants_of_that_manager(self):
        res = rb.support_payments(self.book, ["Алена Черкашина"])
        raw, adj = res["Алена Черкашина"]
        self.assertEqual(raw, (88757 + 18825) * 2)     # две базы, конкурент не считается
        self.assertEqual(adj, (52367 + 18825) * 2)     # колонка «Скорр. оплаты»

    def test_unknown_manager_gets_zero(self):
        res = rb.support_payments(self.book, ["Ия Шарашанидзе"])
        self.assertEqual(res["Ия Шарашанидзе"], (0, 0))   # «Фирма» — не ресторан

    def test_missing_sheet_does_not_raise(self):
        book = FakeSpreadsheet([FakeWorksheet(DATA_SHEET, "ДАННЫЕ_Губарев")])
        res = rb.support_payments(book, ["Алена Черкашина"])
        self.assertEqual(res["Алена Черкашина"][0], 88757 + 18825)


class TestSupportPlan(unittest.TestCase):
    def test_support_plan_read_from_settings(self):
        plans = rb.read_plans(FakeSpreadsheet([FakeWorksheet(SETTINGS, "НАСТРОЙКИ")]))
        self.assertEqual(plans["support"]["Алена Черкашина"], 4174949)
        self.assertNotIn("Ия Шарашанидзе", plans["support"])   # план пуст — не берём

    def test_support_summary_line(self):
        data = dict(TestSummary.DATA,
                    support=[{"name": "Алена", "plan": 4174949, "fact": 3765902,
                              "fact_adj": 3678761, "pct": 0.9019}])
        text = rb.summary_text(data)
        self.assertIn("Оплаты ресторанов Алена: 3 765 902 ₽ · 90% плана", text)


class TestStageNames(unittest.TestCase):
    def test_fallback_covers_all_stages(self):
        """Если Битрикс не отдаст названия стадий, подписи всё равно человеческие."""
        for stage in rb.STAGE_STATUS:
            self.assertIn(stage, rb.STAGE_NAMES_FALLBACK, stage)

    def test_fallback_names_are_not_ids(self):
        for stage, name in rb.STAGE_NAMES_FALLBACK.items():
            self.assertNotEqual(stage, name)
            self.assertTrue(name.strip())


class TestPeriodMixups(unittest.TestCase):
    """Данные разных периодов не должны выдаваться за текущий месяц."""

    def test_support_line_marks_other_period(self):
        data = dict(TestSummary.DATA,
                    support=[{"name": "Алена", "plan": 4174949, "fact": 4392679,
                              "fact_adj": 4300000, "pct": 1.052,
                              "period": "Сентябрь 2026", "stale": True}])
        text = rb.summary_text(data)
        self.assertIn("Оплаты ресторанов Алена", text)

    def test_new_sales_reason_instead_of_silence(self):
        """Нет листа месяца — борд объясняет причину, а не показывает ноль."""
        book = FakeSpreadsheet([FakeWorksheet(SALES, "июль-август", 1)])
        totals, meta, _ = rb.manager_sales(book, datetime(2026, 10, 2))
        self.assertFalse(meta["exact"])
        self.assertTrue(all(v is None for v in totals.values()))


class TestLlmFlag(unittest.TestCase):
    """Подпись «статусы разобраны моделью» не должна зависеть от попадания в кеш."""

    def test_cached_statuses_count_as_llm(self):
        rows = [{"id": "1", "stage": "NEW", "note": "не дозвон"}]
        fresh = {"1": {"h": "x", "status": "call", "action": "дозвониться"}}
        self.assertTrue(any(fresh.get(r["id"], {}).get("status") for r in rows))

    def test_no_statuses_means_no_llm(self):
        rows = [{"id": "1", "stage": "NEW", "note": ""}]
        fresh = {"1": {"h": "x"}}
        self.assertFalse(any(fresh.get(r["id"], {}).get("status") for r in rows))


class TestPaceFlag(unittest.TestCase):
    """«Сильно ниже темпа» — только после 10 числа (решение Анны 06.10.2026)."""

    MANAGERS = [
        {"name": "Лилия", "plan": 210000, "sales": 10000},    # 5% — сильно ниже
        {"name": "Дарья", "plan": 210000, "sales": 200000},   # в темпе
        {"name": "Анна", "plan": 0, "sales": 65000},          # без плана
        {"name": "Ксения", "plan": 210000, "sales": None},    # нет данных
    ]

    def test_silent_in_the_beginning_of_month(self):
        self.assertEqual(rb.behind_pace(self.MANAGERS, 0.19, 6), [])
        self.assertEqual(rb.behind_pace(self.MANAGERS, 0.32, 10), [])

    def test_fires_from_the_eleventh(self):
        names = [m["name"] for m in rb.behind_pace(self.MANAGERS, 0.35, 11)]
        self.assertEqual(names, ["Лилия"])

    def test_manager_in_pace_and_without_plan_are_not_flagged(self):
        names = [m["name"] for m in rb.behind_pace(self.MANAGERS, 0.93, 29)]
        self.assertNotIn("Дарья", names)
        self.assertNotIn("Анна", names)
        self.assertNotIn("Ксения", names)   # факта нет — не ругаемся
