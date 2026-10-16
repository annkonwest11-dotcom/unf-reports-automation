"""Тесты поиска строк-дублей в листах ДАННЫЕ."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from drop_duplicate_rows import find_duplicates

HEAD = [["ДАННЫЕ — ИП Губарев"], [], ["", "", "", "", ""]]


class TestFindDuplicates(unittest.TestCase):
    def test_pustoy_dubl_nahoditsya(self):
        v = HEAD + [["ЛЯ МАРЭ", 1, 2, 3, 4], ["ЛЯ МАРЭ", "", "", "", ""]]
        dups, with_data = find_duplicates(v)
        self.assertEqual(dups, [(5, "ЛЯ МАРЭ")])
        self.assertEqual(with_data, [])

    def test_dubl_s_summami_ne_trogaem(self):
        v = HEAD + [["ЛЯ МАРЭ", 1, 2, 3, 4], ["ЛЯ МАРЭ", 5, 0, 0, 5]]
        dups, with_data = find_duplicates(v)
        self.assertEqual(dups, [])
        self.assertEqual(with_data, [(5, "ЛЯ МАРЭ", 4)])

    def test_pervoe_vhozhdenie_ostaetsya(self):
        # пустой ПЕРВЫЙ, заполненный второй — чистим всё равно второй? нет: первый остаётся
        v = HEAD + [["ЛЯ МАРЭ", "", "", "", ""], ["ЛЯ МАРЭ", "", "", "", ""],
                    ["ЛЯ МАРЭ", "", "", "", ""]]
        dups, _ = find_duplicates(v)
        self.assertEqual(dups, [(5, "ЛЯ МАРЭ"), (6, "ЛЯ МАРЭ")])

    def test_shapku_i_pustye_propuskaem(self):
        v = HEAD + [["", "", "", "", ""], ["", "", "", "", ""], ["ТАНУКИ", 1, 1, 1, 1]]
        self.assertEqual(find_duplicates(v), ([], []))

    def test_probely_v_imeni_ne_sozdayut_dubl(self):
        v = HEAD + [["ЛЯ МАРЭ", 1, 1, 1, 1], ["  ЛЯ МАРЭ  ", "", "", "", ""]]
        dups, _ = find_duplicates(v)
        self.assertEqual(dups, [(5, "ЛЯ МАРЭ")])
