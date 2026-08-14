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

    def test_zachet_avansa_ne_razduvaet_oboroty(self):
        """Зачёт аванса (приход по 'Аванс' + расход по 'Долг') — перенос, не деньги.
        Реальный случай: Евдокимов, июль 2026. Отгрузка 98 853, оплаты 103 157,
        зачёт 95 399; сырые суммы дали бы 194 252 / 198 556."""
        rows = [
            {"Контрагент_Key": "ev", "ТипРасчетов": "Аванс",
             "СуммаOpeningBalance": 20781, "СуммаReceipt": 95399,
             "СуммаExpense": 103157, "СуммаClosingBalance": 13023},
            {"Контрагент_Key": "ev", "ТипРасчетов": "Долг",
             "СуммаOpeningBalance": 0, "СуммаReceipt": 98853,
             "СуммаExpense": 95399, "СуммаClosingBalance": 3454},
        ]
        self.assertEqual(aggregate_balances(rows)["ev"], [20781, 98853, 103157, 16477])

    def test_bez_avansa_summy_ne_menyayutsya(self):
        rows = [
            {"Контрагент_Key": "b", "ТипРасчетов": "Долг",
             "СуммаOpeningBalance": 100, "СуммаReceipt": 50,
             "СуммаExpense": 40, "СуммаClosingBalance": 110},
        ]
        self.assertEqual(aggregate_balances(rows)["b"], [100, 50, 40, 110])


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


class TestSoftMatch(unittest.TestCase):
    """Мягкий матч имён: карточки в 1С переименовывают на ходу, и строгое
    сравнение отдавало нули (10.08.2026 так потерялось 849 тыс. в файле РОП)."""

    def _row(self, sheet_name, odata_name):
        updates, new = plan_updates([sheet_name], {odata_name: [1, 2, 3, 4]},
                                    aliases={}, skip=set())
        return updates, new

    def test_transfer_mark_matches_same_client(self):
        up, new = self._row("ТЕРРИН (ООО ГАСТРОКЛУБ)",
                            "ТЕРРИН (ООО ГАСТРОКЛУБ) с 10.08.26 на ПЕРФИЛЬЕВ")
        self.assertEqual(up, [(DATA_START_ROW, [1, 2, 3, 4])])
        self.assertEqual(new, [])

    def test_search_mark_matches(self):
        up, _ = self._row("BURO Tsum (ООО Ресторанные Технологии) dsbx",
                          "BURO Tsum (ООО Ресторанные Технологии) dsbx бюро ")
        self.assertEqual(up, [(DATA_START_ROW, [1, 2, 3, 4])])

    def test_word_order_and_legal_form(self):
        up, _ = self._row("РУБИН ООО (ЖАН ЖАК РАДИЩЕВСКАЯ)",
                          "ЖАН ЖАК РАДИЩЕВСКАЯ (ООО РУБИН)")
        self.assertEqual(up, [(DATA_START_ROW, [1, 2, 3, 4])])

    def test_yo_and_e_are_same_letter(self):
        up, _ = self._row("СЕВЕРЯНЕ (ООО ВАСИЛЕК)", "СЕВЕРЯНЕ (ООО ВАСИЛЁК)")
        self.assertEqual(up, [(DATA_START_ROW, [1, 2, 3, 4])])

    def test_hyphen_is_a_word_separator(self):
        """Джаннет 14.08: в 1С «БУТИК-БАР», в листе «БУТИК БАР» — один клиент."""
        up, new = self._row("ВИННЫЙ БУТИК БАР ДЖАННЕТ (ООО ВИНОТЕКА ТУШИНО) в 1С/ЭДО",
                            "ВИННЫЙ БУТИК-БАР ДЖАННЕТ (ООО ВИНОТЕКА ТУШИНО)")
        self.assertEqual(up, [(DATA_START_ROW, [1, 2, 3, 4])])
        self.assertEqual(new, [])

    def test_different_clients_do_not_stick(self):
        """Общие «физ лицо нал» не должны склеивать разных клиентов."""
        up, new = self._row("Елена физ лицо Северяне нал", "Онегин физ лицо нал")
        self.assertEqual(up, [])
        self.assertEqual(len(new), 1)

    def test_ambiguous_match_is_refused(self):
        """Два одинаково похожих кандидата — деньги никому не приписываем."""
        updates, new = plan_updates(
            ["Кафе Х (ООО Ромашка)", "Кафе Х (ООО Ромашка) счет"],
            {"Кафе Х (ООО Ромашка) ЭДО новый": [1, 2, 3, 4]},
            aliases={}, skip=set())
        self.assertEqual(updates, [])
        self.assertEqual(len(new), 1)


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
