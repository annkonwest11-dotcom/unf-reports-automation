"""Разбор списаний беби-листов из свободного текста (без сети).

Эталон — первое живое сообщение Анны 18.08.2026:
    «писали мизуна зеленая 5 сегодня, микс салат 1, пакчой зел 2 вчера списали,
     16 числа 19 микса списали, Микс 23 за 11 число»
    «Пакчой красный 2 от 11 числа и вот списали»

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beby_report import block_start, match_position, parse_writeoffs

TODAY = date(2026, 8, 18)


class TestParseWriteoffs(unittest.TestCase):
    def parse(self, text):
        items, unknown = parse_writeoffs(text, TODAY)
        return [(d, name, q) for d, _k, name, q in items], unknown

    def test_annas_first_message(self):
        items, unknown = self.parse(
            "писали мизуна зеленая 5 сегодня , микс салат 1 , пакчой зел 2 вчера списали , "
            "16 числа 19 микса списали , Микс 23 за 11 число")
        self.assertEqual(unknown, [])
        self.assertEqual(items, [
            (date(2026, 8, 18), "Мизуна зелёная", 5),
            (date(2026, 8, 18), "Микс", 1),
            (date(2026, 8, 17), "Пак чой зеленый", 2),
            (date(2026, 8, 16), "Микс", 19),
            (date(2026, 8, 11), "Микс", 23),
        ])

    def test_annas_second_message(self):
        items, unknown = self.parse("Пакчой красный 2 от 11 числа и вот списали")
        self.assertEqual(unknown, [])
        self.assertEqual(items, [(date(2026, 8, 11), "Пак чой красный", 2)])

    def test_day_before_quantity(self):
        """★«16 числа 19 микса» — 19 пачек 16-го, а не 16 пачек 19-го."""
        items, _ = self.parse("16 числа 19 микса списали")
        self.assertEqual(items, [(date(2026, 8, 16), "Микс", 19)])

    def test_date_inherited_from_previous_chunk(self):
        """Без даты берём дату предыдущего куска — Анна пишет их подряд одним днём."""
        items, _ = self.parse("кейл 3 вчера, романо 2, шпинат 1")
        self.assertEqual([d for d, _, _ in items], [date(2026, 8, 17)] * 3)

    def test_today_when_no_date_at_all(self):
        items, _ = self.parse("кейл 4")
        self.assertEqual(items[0][0], TODAY)

    def test_numeric_date(self):
        items, _ = self.parse("шпинат 6 11.08")
        self.assertEqual(items[0][0], date(2026, 8, 11))

    def test_future_day_means_previous_month(self):
        """«25 числа», когда сегодня 18-е, — это прошлый месяц."""
        items, _ = self.parse("кейл 2 за 25 число")
        self.assertEqual(items[0][0], date(2026, 7, 25))

    def test_unknown_position_is_reported_not_guessed(self):
        """★Непонятое НЕ вносим в случайную позицию, а показываем Анне."""
        items, unknown = self.parse("укроп 5 сегодня")
        self.assertEqual(items, [])
        self.assertEqual(len(unknown), 1)
        self.assertIn("укроп", unknown[0][1])

    def test_empty(self):
        self.assertEqual(parse_writeoffs("", TODAY), ([], []))
        self.assertEqual(parse_writeoffs("списали", TODAY), ([], []))


class TestMatchPosition(unittest.TestCase):
    def test_finds_name_anywhere_in_phrase(self):
        """★Название может стоять не с начала: «писали мизуна зеленая»."""
        self.assertEqual(match_position("писали мизуна зеленая")[1], "Мизуна зелёная")
        self.assertEqual(match_position("микса")[1], "Микс")
        self.assertEqual(match_position("микс салат")[1], "Микс")

    def test_unknown_returns_none(self):
        self.assertIsNone(match_position("укроп"))
        self.assertIsNone(match_position(""))


class TestBlockStart(unittest.TestCase):
    def test_period_bounds_from_label(self):
        self.assertEqual(block_start("11-18 августа", 2026, 8), date(2026, 8, 11))
        self.assertEqual(block_start("04-10 августа", 2026, 8), date(2026, 8, 4))

    def test_not_a_period_label(self):
        self.assertIsNone(block_start("ИТОГО ИЮЛЬ", 2026, 7))


if __name__ == "__main__":
    unittest.main()
