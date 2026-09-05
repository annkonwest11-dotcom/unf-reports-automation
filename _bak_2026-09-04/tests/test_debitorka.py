"""Юнит-тесты на объединение карточек в дебиторке (без сети).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_debitorka import combine
from sync_odata import _long_numbers, actual_name, group_same_client


def rec(name, total, overdue=0, days=0):
    return {"name": name, "total": total, "overdue": overdue, "days": days,
            "buckets": [0, 0, 0, 0, 0]}


class TestCombine(unittest.TestCase):
    def test_exact_duplicates_sum(self):
        out = combine([rec("ПУШКИН (ООО МОНЕ)", 100), rec("пушкин (ооо моне)", 50)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["total"], 150)

    def test_transferred_card_joins(self):
        """★17.08: долг переехавшего клиента лежал в двух строках."""
        out = combine([rec("ПУШКИН (ООО МОНЕ) с 10.08.26 на ПЕРФИЛЬЕВ", 18630, 18630, 40),
                       rec("ПУШКИН (ООО МОНЕ)", 11009, 5000, 10)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["total"], 29639)
        self.assertEqual(out[0]["overdue"], 23630)
        self.assertEqual(out[0]["days"], 40)
        self.assertEqual(out[0]["name"], "ПУШКИН (ООО МОНЕ)")   # без пометки о переводе

    def test_cash_card_joins(self):
        out = combine([rec("ЮНОСТЬ (ООО ГРАНДЕ)", 14781), rec("ГРАНДЕ  (ЮНОСТЬ) НАЛ ООО", 2500)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["total"], 17281)

    def test_different_points_stay_apart(self):
        out = combine([rec("ШЕСТНАДЦАТЬ ТОНН КЕЙТЕРИНГ ООО", 1000),
                       rec("ШЕСТНАДЦАТЬ ТОНН ПРЕСНЯ (ООО 16 ТОНН ПРЕСНЯ)", 2000)])
        self.assertEqual(len(out), 2)

    def test_buckets_sum_elementwise(self):
        a, b = rec("ТЕРРИН (ООО ГАСТРОКЛУБ)", 10), rec("ТЕРРИН (ООО ГАСТРОКЛУБ) с 10.08.26 на ПЕРФИЛЬЕВ", 20)
        a["buckets"] = [1, 2, 3, 4, 5]
        b["buckets"] = [10, 20, 30, 40, 50]
        out = combine([a, b])
        self.assertEqual(out[0]["buckets"], [11, 22, 33, 44, 55])


class TestPhoneGuard(unittest.TestCase):
    def test_different_phones_never_merge(self):
        """★Грабли: «коллеги» с разными телефонами — разные люди."""
        groups = group_same_client(["коллеги (НАЛ) 89684708830", "+79299588161 коллеги"])
        self.assertEqual(len(groups), 2)

    def test_dates_are_not_phone_numbers(self):
        """Короткие числа (дата перевода, «А20») склейке не мешают."""
        self.assertEqual(_long_numbers("УГОЛЕК (ООО АНИЧА) с 10.08.26 на ПЕРФИЛЬЕВ"), set())
        groups = group_same_client(["А20 (ИП Тагаева Роза Бахриддиновна с 20.10.25)",
                                    "Тагаева Роза Бахриддиновна (А20)"])
        self.assertEqual(len(groups), 1)


class TestActualName(unittest.TestCase):
    def test_prefers_card_without_transfer_mark(self):
        self.assertEqual(
            actual_name(["ВОДНЫЙ (ООО ТРИБУНА) с 10.08.26 на ПЕРФИЛЬЕВ", "ВОДНЫЙ (ООО ТРИБУНА)"]),
            "ВОДНЫЙ (ООО ТРИБУНА)")


if __name__ == "__main__":
    unittest.main()
