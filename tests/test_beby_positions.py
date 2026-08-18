"""Сопоставление названий позиций беби-листов (накладная ↔ 1С ↔ отчёт).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beby_report import canon_pos


class TestCanonPos(unittest.TestCase):
    def name(self, s):
        return canon_pos(s)[1]

    def key(self, s):
        return canon_pos(s)[0]

    def test_one_letter_colour_in_invoice(self):
        """★18.08: Юшин пишет цвет одной буквой, «Пакчой к» уезжал в зелёный."""
        self.assertEqual(self.name("Пакчой к"), "Пак чой красный")
        self.assertEqual(self.name("Пакчой з"), "Пак чой зеленый")
        self.assertEqual(self.name("Мизуна з"), "Мизуна зелёная")
        self.assertEqual(self.name("Мангольд з"), "Мангольд зелёный")
        self.assertEqual(self.name("Мангольд б"), "Мангольд бордо")

    def test_full_colour_names_still_work(self):
        self.assertEqual(self.name("Пак чой красный"), "Пак чой красный")
        self.assertEqual(self.name("Пак чой red"), "Пак чой красный")
        self.assertEqual(self.name("Мизуна зеленая"), "Мизуна зелёная")

    def test_defaults_without_colour(self):
        """Без цвета: пакчой зелёный, мизуна красная, мангольд алый (правило Анны)."""
        self.assertEqual(self.name("Пакчой"), "Пак чой зеленый")
        self.assertEqual(self.name("Мизуна"), "Мизуна красная")
        self.assertEqual(self.name("Мангольд"), "Мангольд алый")

    def test_aisberg_is_frillis(self):
        """Анна 13.08: айсберг и фриллис — одно и то же, в 1С карточка «Фриллис»."""
        self.assertEqual(self.key("Айсберг"), self.key("Фриллис"))
        self.assertEqual(self.name("Айсберг"), "Фриллис")

    def test_1c_names_with_prefix(self):
        """В 1С позиции зовутся «Беби лист Кейл 100 гр» — служебное отбрасываем."""
        self.assertEqual(self.name("Беби лист Кейл 100 гр"), "Кейл")
        self.assertEqual(self.key("Беби лист Пак чой красный 100 гр"),
                         self.key("Пакчой к"))

    def test_invoice_and_1c_meet(self):
        """Главное: одна позиция из накладной и из 1С должна дать один ключ."""
        pairs = [("Салатный микс", "Беби лист Микс 100 гр"),
                 ("Кейл", "Беби лист Кейл 100 гр"),
                 ("Пакчой з", "Беби лист Пак чой зеленый 100 гр"),
                 ("Романо", "Беби лист Романо 100 гр")]
        for inv, one_c in pairs:
            self.assertEqual(self.key(inv), self.key(one_c), f"{inv} ↔ {one_c}")


if __name__ == "__main__":
    unittest.main()
