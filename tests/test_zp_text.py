"""Тесты на хвост сообщения о ЗП (авансы, ИТОГ, пометка про официальную часть).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zp_text import bonus_rate, finish

PROMISE = "официальная зарплата — добавим 10-го"


class TestFinishOfficialPromise(unittest.TestCase):
    """Пометку «добавим 10-го» обещаем только тем, у кого официальная часть бывает.

    Признак — аванс на карту: он идёт по той же ведомости, что и ЗП 9-го.
    Проверено на таблицах выплат за июль, август и сентябрь 2026: у оформленных
    (Дарья, Ксения, Алёна, Влада) заполнены и C, и E, у остальных — ни одной.
    """

    def test_oformlennyy_do_10_chisla_obeshchaem(self):
        # аванс на карту есть, официальная ЗП ещё не проставлена
        pay = {"Дарья Вольнова": (120625, 12811, 0, 0, 107814)}
        text = finish(["+120625 (всё)"], 120625, "Дарья Вольнова", pay)
        self.assertIn(PROMISE, text)

    def test_oformlennyy_posle_10_chisla_ne_obeshchaem(self):
        # официальная ЗП проставлена — обещать нечего, она уже строкой выше
        pay = {"Дарья Вольнова": (120625, 12811, 0, 12811, 95003)}
        text = finish(["+120625 (всё)"], 120625, "Дарья Вольнова", pay)
        self.assertNotIn(PROMISE, text)
        self.assertIn("официальная зарплата на карту", text)

    def test_neoformlennyy_ne_obeshchaem(self):
        # Лилия, София, Виолетта, Анна-РОП: аванс только наличными, официальной
        # части не бывает — ИТОГ наличными окончательный
        pay = {"Лилия Сулименко": (45000, 0, 20000, 0, 25000)}
        text = finish(["+45000 (всё)"], 45000, "Лилия Сулименко", pay)
        self.assertNotIn(PROMISE, text)

    def test_net_v_tablice_vyplat_ne_obeshchaem(self):
        # человека нет в таблице выплат — подставляется заглушка без авансов
        text = finish(["+10000 (всё)"], 10000, "Ия Шарашанидзе", {})
        self.assertNotIn(PROMISE, text)
        self.assertIn("ИТОГ", text)


class TestBonusRate(unittest.TestCase):
    """Ставка в подписи считается из суммы, поэтому не может разойтись с ней."""

    def test_rop_oborot_100_procentov(self):
        # сентябрь 2026: оборот 100,4% плана → формула взяла 1%, а подпись врала «0,7%»
        self.assertEqual(bonus_rate(56645, 5664504, 1.0038), "1%")

    def test_rop_postupleniya_80_procentov(self):
        self.assertEqual(bonus_rate(39651, 5664504, 0.8047), "0,7%")

    def test_alena_plan_bonus_95_procentov(self):
        # 09.10.2026: при 95% плана сумма 0,7%, а в подписи стояло «1%»
        self.assertEqual(bonus_rate(34544, 4934876, 0.9497), "0,7%")

    def test_nestandartnaya_stavka_vidna_kak_est(self):
        # половинная ставка (отпускная корректировка у Алёны) не выдаётся за полную
        self.assertEqual(bonus_rate(24674, 4934876, 1.0), "0,5%")

    def test_bez_bazy_pravilo_po_planu(self):
        # бонус поставлен руками, базы нет — тогда по правилу от %плана
        self.assertEqual(bonus_rate(10000, 0, 1.2), "1%")
        self.assertEqual(bonus_rate(10000, 0, 0.8), "0,7%")

    def test_dvuznachnaya_stavka_ne_teryaet_desyatki(self):
        self.assertEqual(bonus_rate(1000000, 10000000, 0.5), "10%")


if __name__ == "__main__":
    unittest.main()
