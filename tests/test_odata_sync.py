"""Юнит-тесты на чистую логику OData-синка (без сети/Google/1С).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_odata import (
    DATA_START_ROW,
    aggregate_balances,
    norm_name,
    plan_updates,
    _current_month_period,
)


class TestAggregate(unittest.TestCase):
    def test_sums_multiple_rows_per_contractor(self):
        rows = [
            {"Контрагент_Key": "a", "СуммаOpeningBalance": 10, "СуммаReceipt": 5,
             "СуммаExpense": 3, "СуммаClosingBalance": 12},
            {"Контрагент_Key": "a", "СуммаOpeningBalance": 0, "СуммаReceipt": 7,
             "СуммаExpense": 0, "СуммаClosingBalance": 7},
            {"Контрагент_Key": "b", "СуммаOpeningBalance": 100, "СуммаReceipt": 0,
             "СуммаExpense": 40, "СуммаClosingBalance": 60},
        ]
        agg = aggregate_balances(rows)
        self.assertEqual(agg["a"], [10, 12, 3, 19])
        self.assertEqual(agg["b"], [100, 0, 40, 60])

    def test_handles_none_amounts(self):
        rows = [{"Контрагент_Key": "a", "СуммаOpeningBalance": None,
                 "СуммаReceipt": None, "СуммаExpense": None,
                 "СуммаClosingBalance": None}]
        self.assertEqual(aggregate_balances(rows)["a"], [0, 0, 0, 0])


class TestNormName(unittest.TestCase):
    def test_collapses_and_trims(self):
        self.assertEqual(norm_name("  DeLaura   Bar "), "delaura bar")

    def test_double_space_matches_single(self):
        self.assertEqual(norm_name("Mitzva  Bar"), norm_name("Mitzva Bar"))

    def test_empty(self):
        self.assertEqual(norm_name(None), "")
        self.assertEqual(norm_name("   "), "")


class TestPlanUpdates(unittest.TestCase):
    def setUp(self):
        # колонка A начиная со строки 4
        self.col_a = [
            "А 71 (ООО Фреш Фуд Лайн)",   # строка 4
            "А 81 (перевод)",              # строка 5
            "Кафе  Луна",                  # строка 6 (двойной пробел)
        ]

    def test_matched_rows_get_row_numbers(self):
        balances = {
            "А 71 (ООО Фреш Фуд Лайн)": [1, 2, 3, 4],
            "А 81 (перевод)": [5, 6, 7, 8],
        }
        updates, new = plan_updates(self.col_a, balances)
        self.assertEqual(updates, [(4, [1, 2, 3, 4]), (5, [5, 6, 7, 8])])
        self.assertEqual(new, [])

    def test_matching_is_whitespace_insensitive(self):
        balances = {"Кафе Луна": [9, 9, 9, 9]}  # одинарный пробел vs двойной в листе
        updates, new = plan_updates(self.col_a, balances)
        self.assertEqual(updates, [(DATA_START_ROW + 2, [9, 9, 9, 9])])
        self.assertEqual(new, [])

    def test_unknown_contractor_is_new(self):
        balances = {"Новый Ресторан": [1, 1, 1, 1]}
        updates, new = plan_updates(self.col_a, balances)
        self.assertEqual(updates, [])
        self.assertEqual(new, [("Новый Ресторан", [1, 1, 1, 1])])

    def test_duplicate_names_use_first_row(self):
        col_a = ["Дубль", "Дубль", "Иное"]
        updates, _ = plan_updates(col_a, {"Дубль": [1, 1, 1, 1]})
        self.assertEqual(updates, [(DATA_START_ROW, [1, 1, 1, 1])])

    def test_alias_folds_card_into_existing_row_summed(self):
        # база "Кафе Х dsbx" в листе + карточка ЭДО из 1С → сумма в одну строку
        col_a = ["Кафе Х dsbx"]
        balances = {
            "Кафе Х dsbx": [10, 20, 5, 25],           # прямое совпадение
            "Кафе Х dsbx/ЭДО": [0, 3, 2, 1],           # алиас на ту же строку
        }
        aliases = {"Кафе Х dsbx/ЭДО": "Кафе Х dsbx"}
        updates, new = plan_updates(col_a, balances, aliases=aliases, skip=set())
        self.assertEqual(updates, [(DATA_START_ROW, [10, 23, 7, 26])])
        self.assertEqual(new, [])

    def test_skip_excludes_contractor_entirely(self):
        col_a = ["Иное"]
        balances = {"мусор 123": [1, 1, 1, 1]}
        updates, new = plan_updates(col_a, balances, aliases={}, skip={"мусор 123"})
        self.assertEqual(updates, [])
        self.assertEqual(new, [])


class TestCurrentMonthPeriod(unittest.TestCase):
    def test_mid_year(self):
        start, end = _current_month_period(datetime(2026, 7, 23))
        self.assertEqual(start, "datetime'2026-07-01T00:00:00'")
        self.assertEqual(end, "datetime'2026-08-01T00:00:00'")

    def test_december_rolls_year(self):
        start, end = _current_month_period(datetime(2026, 12, 15))
        self.assertEqual(start, "datetime'2026-12-01T00:00:00'")
        self.assertEqual(end, "datetime'2027-01-01T00:00:00'")


if __name__ == "__main__":
    unittest.main()
