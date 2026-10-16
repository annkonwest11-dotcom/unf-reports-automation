"""Тесты на хвост сообщения о ЗП (авансы, ИТОГ, пометка про официальную часть).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zp_text import Sheet, bonus_rate, finish

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


class TestStaffFromSheet(unittest.TestCase):
    """Состав сотрудников берётся из листа: наём и увольнение не правят код.

    Со списком в коде рассылка падала целиком: после увольнения Лилии
    build_texts бросал «не нашёл ИТОГО ЗП — Лилия Сулименко» и не собирал
    вообще ничего, в том числе по оставшимся.
    """

    def _sheet(self, rows):
        return Sheet([[c for c in r] for r in rows])

    def test_roli_po_sekciyam(self):
        sh = self._sheet([
            ["СВОДНАЯ ЗАРПЛАТНАЯ ВЕДОМОСТЬ"],
            ["МЕНЕДЖЕРЫ ПОИСКА"],
            ["ИТОГО ЗП — Дарья Вольнова", "", 1000],
            ["ИТОГО ЗП — Виолетта Караханова", "", 2000],
            ["МЕНЕДЖЕРЫ СОПРОВОЖДЕНИЯ"],
            ["ИТОГО ЗП — Алена Черкашина", "", 3000],
            ["РОП"],
            ["ИТОГО ЗП — Анна Кононенко (РОП)", "", 4000],
        ])
        self.assertEqual(sh.staff(), [
            ("Дарья Вольнова", "поиск"),
            ("Виолетта Караханова", "поиск"),
            ("Алена Черкашина", "сопровождение"),
            ("Анна Кононенко (РОП)", "роп"),
        ])

    def test_uvolennogo_net_v_sostave(self):
        sh = self._sheet([
            ["СВОДНАЯ ЗАРПЛАТНАЯ ВЕДОМОСТЬ"],
            ["МЕНЕДЖЕРЫ ПОИСКА"],
            ["ИТОГО ЗП — Дарья Вольнова", "", 1000],
        ])
        names = [n for n, _ in sh.staff()]
        self.assertNotIn("Лилия Сулименко", names)
        self.assertEqual(names, ["Дарья Вольнова"])

    def test_dashbord_sverhu_ne_schitaetsya(self):
        # вверху листа те же имена в сводке — состав берём только из ведомости
        sh = self._sheet([
            ["Дарья Вольнова", "", 1000],
            ["Алена Черкашина", "", 2000],
            ["СВОДНАЯ ЗАРПЛАТНАЯ ВЕДОМОСТЬ"],
            ["МЕНЕДЖЕРЫ ПОИСКА"],
            ["ИТОГО ЗП — Дарья Вольнова", "", 1000],
        ])
        self.assertEqual(sh.staff(), [("Дарья Вольнова", "поиск")])


class TestSmmText(unittest.TestCase):
    """★16.10.2026: Ксения перешла с поиска на SMM — у неё свой расчёт."""

    PAY = {"Ксения Наныкина": (55000, 12811, 0, 0, 42189)}

    def _sheet(self, subs=0, pay1=25000, pay2=0, channels=0, plan=0,
               leads=0, reels=0, extra=0, note=""):
        return Sheet([
            ["СВОДНАЯ ЗАРПЛАТНАЯ ВЕДОМОСТЬ"],
            ["SMM"],
            ["  Ксения Наныкина  |  SMM"],
            ["Живых подписчиков Instagram (Greench)", "ставит директор", "", subs],
            ["Оклад — аккаунт 1 (Greench)", "25 000 ₽", pay1],
            ["Оклад — аккаунт 2 (Вячеслав)", "когда запустится", pay2],
            ["Контент-план — выполнено каналов", "по 5 000", plan, channels],
            ["Премия за новых клиентов из соцсетей", "С/В/А", leads],
            ["Премия за залетевшие Reels", "порог", reels],
            ["Дополнительная премия", "", extra],
            ["Комментарий к доп.премии", note],
            ["ИТОГО ЗП — Ксения Наныкина", "", pay1 + pay2 + plan + leads + reels + extra],
        ])

    def test_rol_smm_iz_sekcii(self):
        self.assertEqual(self._sheet().staff(), [("Ксения Наныкина", "smm")])

    def test_oklad_s_podpischikami(self):
        from zp_text import build_smm
        t = build_smm(self._sheet(subs=1240, pay1=26000), "Ксения Наныкина",
                      "ОКТЯБРЬ", self.PAY)
        self.assertIn("ведение Instagram Greench (1240 подписчиков)", t)

    def test_bez_podpischikov_bez_skobok(self):
        from zp_text import build_smm
        t = build_smm(self._sheet(), "Ксения Наныкина", "ОКТЯБРЬ", self.PAY)
        self.assertIn("ведение Instagram Greench", t)
        self.assertNotIn("подписчиков", t)

    def test_nulevye_stroki_ne_pokazyvaem(self):
        from zp_text import build_smm
        t = build_smm(self._sheet(), "Ксения Наныкина", "ОКТЯБРЬ", self.PAY)
        for miss in ("второго аккаунта", "контент-план", "Reels", "соцсетей"):
            self.assertNotIn(miss, t)

    def test_kontent_plan_sklonenie(self):
        from zp_text import build_smm
        for cnt, word in ((1, "1 канал"), (3, "3 канала"), (4, "4 канала")):
            t = build_smm(self._sheet(channels=cnt, plan=cnt * 5000),
                          "Ксения Наныкина", "ОКТЯБРЬ", self.PAY)
            self.assertIn(f"контент-план выполнен: {word}", t)

    def test_premii_bloka_2(self):
        from zp_text import build_smm
        t = build_smm(self._sheet(leads=20000, reels=2500), "Ксения Наныкина",
                      "ОКТЯБРЬ", self.PAY)
        self.assertIn("новые клиенты из соцсетей", t)
        self.assertIn("залетевшие Reels", t)

    def test_dop_premiya_s_kommentariem(self):
        from zp_text import build_smm
        t = build_smm(self._sheet(extra=3000, note="за съёмку с шефом"),
                      "Ксения Наныкина", "ОКТЯБРЬ", self.PAY)
        self.assertIn("за съёмку с шефом", t)
