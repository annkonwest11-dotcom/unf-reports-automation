"""Юнит-тесты на разбор документов от поставщика беби-листов (без PDF и сети).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beby_invoice import NotAnInvoice, doc_kind, parse

НАКЛАДНАЯ = """Унифицированная форма № ТОРГ-12
ТОВАРНАЯ НАКЛАДНАЯ 346 03.08.2026
Поставщик ИП Юшин А.В., ИНН 1234567890
Основание: Счет на оплату № 511 от 01.08.2026
1 Салатный микс
 - кг 166 - 11,70 1,00 - - 1 950,00 22 815,00 Без НДС 0,00 22 815,00
"""

СЧЁТ = """Образец заполнения платежного поручения
БИК 044525225 р/с 40702810000000000000
Счет на оплату № 511 от 01 августа 2026 г.
Поставщик: ИП Юшин А.В.
Покупатель: ООО Гринч
Итого к оплате: 22 815,00
"""


class TestDocKind(unittest.TestCase):
    def test_invoice(self):
        self.assertEqual(doc_kind(НАКЛАДНАЯ), "накладная")

    def test_bill_is_not_invoice(self):
        """★Правило Анны 18.08: счета на оплату в отчёт не берём."""
        self.assertEqual(doc_kind(СЧЁТ), "счет")

    def test_invoice_wins_over_its_own_basis_line(self):
        """★Грабли: в накладной есть строка «Основание: Счет на оплату № …»."""
        self.assertEqual(doc_kind("Основание: Счет на оплату № 511\nТоварная накладная"),
                         "накладная")

    def test_yo_and_spacing(self):
        self.assertEqual(doc_kind("СЧЁТ  НА\nОПЛАТУ № 7"), "счет")
        self.assertEqual(doc_kind("Товарная\n  накладная № 1"), "накладная")

    def test_unknown(self):
        self.assertEqual(doc_kind("Акт сверки взаимных расчётов"), "неизвестно")
        self.assertEqual(doc_kind(""), "неизвестно")


class TestParseRejectsBills(unittest.TestCase):
    def test_bill_raises(self):
        import beby_invoice
        orig, beby_invoice.extract_text = beby_invoice.extract_text, lambda p: СЧЁТ
        try:
            with self.assertRaises(NotAnInvoice):
                parse("счет.pdf")
        finally:
            beby_invoice.extract_text = orig

    def test_invoice_parses(self):
        import beby_invoice
        orig, beby_invoice.extract_text = beby_invoice.extract_text, lambda p: НАКЛАДНАЯ
        try:
            inv = parse("накладная.pdf")
        finally:
            beby_invoice.extract_text = orig
        self.assertEqual(inv["number"], "346")
        self.assertEqual(inv["items"], [("Салатный микс", 117, 22815.0)])


if __name__ == "__main__":
    unittest.main()
