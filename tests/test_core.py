"""Юнит-тесты на чистую логику (без сети/Google/1С).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_report
from sheets import (
    SheetsClient,
    _parse_period,
    _next_month_label,
    _strip_month,
    _parse_day_range,
    _format_period_label,
)


class TestParser(unittest.TestCase):
    def test_manager_poisk(self):
        text = (
            "смена менеджер поиск\n"
            "сотрудник: Валерия Абрамова\n"
            "дата: 25\n"
            "звонки всего: 30\n"
        )
        r = parse_report(text)
        self.assertIsNotNone(r)
        self.assertEqual(r.manager_type, "поиск")
        self.assertEqual(r.employee, "Валерия Абрамова")
        self.assertEqual(r.date, "25")
        self.assertEqual(r.calls_total, "30")

    def test_manager_soprovozhdenie(self):
        text = (
            "смена менеджер сопровождение\n"
            "сотрудник: Дарья Вольнова\n"
            "дата: 10\n"
        )
        r = parse_report(text)
        self.assertIsNotNone(r)
        self.assertEqual(r.manager_type, "сопровождение")

    def test_vlada(self):
        text = "смена влада\nсотрудник: Владислава Герасимчук\nдата: 3\nзаказы: будний\n"
        r = parse_report(text)
        self.assertIsNotNone(r)
        self.assertEqual(r.manager_type, "влада")

    def test_empty_returns_none(self):
        self.assertIsNone(parse_report(""))
        self.assertIsNone(parse_report("   \n  "))

    def test_missing_required_fields_returns_none(self):
        # нет даты -> None
        self.assertIsNone(parse_report("смена менеджер поиск\nсотрудник: Кто-то\n"))


class TestPeriodHelpers(unittest.TestCase):
    def test_strip_month(self):
        rest, num = _strip_month("Май 2026")
        self.assertEqual(num, 5)
        self.assertEqual(rest, "2026")

    def test_parse_period(self):
        self.assertEqual(_parse_period("Май 2026"), (5, 2026))
        self.assertEqual(_parse_period("Декабрь 2025"), (12, 2025))

    def test_next_month_label(self):
        self.assertEqual(_next_month_label("Май 2026"), "Июнь 2026")
        # переход через год
        self.assertEqual(_next_month_label("Декабрь 2026"), "Январь 2027")

    def test_parse_day_range_single(self):
        self.assertEqual(_parse_day_range("25 мая"), {25})

    def test_parse_day_range_interval(self):
        self.assertEqual(_parse_day_range("1-15 мая"), set(range(1, 16)))

    def test_parse_day_range_whole_month(self):
        # только месяц без дней -> весь диапазон
        self.assertEqual(_parse_day_range("Май 2026"), set(range(1, 32)))

    def test_format_period_label_day(self):
        label = _format_period_label("25 мая")
        self.assertIn("25 мая", label)


class TestDayParsing(unittest.TestCase):
    def test_parse_day_plain(self):
        self.assertEqual(SheetsClient._parse_day("25"), 25)

    def test_parse_day_dotted(self):
        self.assertEqual(SheetsClient._parse_day("25.06"), 25)

    def test_parse_day_invalid(self):
        self.assertIsNone(SheetsClient._parse_day("abc"))


if __name__ == "__main__":
    unittest.main()
