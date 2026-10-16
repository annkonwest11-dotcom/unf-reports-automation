"""Тесты перевода клиентов в СПРАВОЧНИКЕ — без сети, на списке строк."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from reassign_clients import plan_changes

HEAD = [["СПРАВОЧНИК КОНТРАГЕНТОВ"], ["⚠️"],
        ["Контрагент", "Менеджер поиска", "Менеджер сопровождения", "Тип"]]


def sheet(*rows):
    return HEAD + [list(r) for r in rows]


class TestPoiskTransfer(unittest.TestCase):
    def test_menyaet_poisk_i_dozapolnyaet_sopr(self):
        v = sheet(["БЕЛУГА ООО", "Ксения Наныкина", "", "Ресторан"],
                  ["ПЕШИ", "Ксения Наныкина", "Алена Черкашина", "Ресторан"],
                  ["ТАНУКИ", "Дарья Вольнова", "", "Ресторан"])
        ch = plan_changes(v, poisk_from="Ксения Наныкина",
                          poisk_to="Прямой клиент", sopr_to="Алена Черкашина")
        self.assertEqual([(i, c, n) for i, c, _w, n, _nm in ch],
                         [(4, "B", "Прямой клиент"), (4, "C", "Алена Черкашина"),
                          (5, "B", "Прямой клиент")])

    def test_chuzhie_stroki_ne_trogaem(self):
        v = sheet(["ТАНУКИ", "Дарья Вольнова", "", "Ресторан"])
        self.assertEqual(plan_changes(v, poisk_from="Ксения Наныкина",
                                      poisk_to="Прямой клиент"), [])

    def test_povtornyy_zapusk_nichego_ne_menyaet(self):
        v = sheet(["БЕЛУГА ООО", "Прямой клиент", "Алена Черкашина", "Ресторан"])
        self.assertEqual(plan_changes(v, poisk_from="Прямой клиент",
                                      poisk_to="Прямой клиент",
                                      sopr_to="Алена Черкашина"), [])


class TestSoprRows(unittest.TestCase):
    def test_tochechnyy_spisok_strok(self):
        v = sheet(["БЕЛУГА ООО", "Дарья Вольнова", "", "Ресторан"],
                  ["ПЕШИ", "Дарья Вольнова", "", "Ресторан"])
        ch = plan_changes(v, sopr_rows=[5], sopr_to="Алена Черкашина")
        self.assertEqual(ch, [(5, "C", "", "Алена Черкашина", "ПЕШИ")])

    def test_uzhe_stoit_propuskaem(self):
        v = sheet(["БЕЛУГА ООО", "Дарья Вольнова", "Алена Черкашина", "Ресторан"])
        self.assertEqual(plan_changes(v, sopr_rows=[4], sopr_to="Алена Черкашина"), [])

    def test_pustaya_stroka_ne_pishetsya(self):
        # промах номером в пустую строку не должен породить правку
        v = sheet(["", "", "", ""])
        self.assertEqual(plan_changes(v, sopr_rows=[4], sopr_to="Алена Черкашина"), [])

    def test_shapku_ne_trogaem(self):
        v = sheet(["БЕЛУГА ООО", "Дарья Вольнова", "", "Ресторан"])
        self.assertEqual(plan_changes(v, sopr_rows=[3], sopr_to="Алена Черкашина"), [])


if __name__ == "__main__":
    unittest.main()
