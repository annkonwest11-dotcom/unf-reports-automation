import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cash_avans as ca


class TestComputeDefault(unittest.TestCase):
    def test_total_rule_subtracts_official_no_kopecks(self):
        # офиц. без копеек (12253), наличными добиваем до ровного итого:
        # Ксения: 20000 − 12253 = 7747 → итого ровно 20000
        self.assertEqual(ca.compute_default(("total", 20000), 12253.78), 7747)
        # Алёна: 15000 − 12253 = 2747 → итого ровно 15000
        self.assertEqual(ca.compute_default(("total", 15000), 12253.78), 2747)

    def test_total_rule_empty_official(self):
        self.assertEqual(ca.compute_default(("total", 20000), None), 20000)
        self.assertEqual(ca.compute_default(("total", 20000), ""), 20000)

    def test_total_rule_negative_clamped(self):
        self.assertEqual(ca.compute_default(("total", 10000), 12253.78), 0)

    def test_fixed_rule(self):
        self.assertEqual(ca.compute_default(("fixed", 15000), 999), 15000)
        self.assertEqual(ca.compute_default(("fixed", 10200), None), 10200)

    def test_ask_rule_has_no_default(self):
        self.assertIsNone(ca.compute_default(("ask", None), 5000))


class TestParseAmount(unittest.TestCase):
    def test_plain_numbers(self):
        self.assertEqual(ca.parse_amount("15000"), 15000)
        self.assertEqual(ca.parse_amount("7 746"), 7746)
        self.assertEqual(ca.parse_amount("10200 руб"), 10200)
        self.assertEqual(ca.parse_amount("2746,50"), 2746)  # копейки убираются

    def test_zero_words(self):
        for t in ("0", "нет", "-", "без", "без наличных", "ноль"):
            self.assertEqual(ca.parse_amount(t), 0)

    def test_unparseable(self):
        self.assertIsNone(ca.parse_amount("abc"))
        self.assertIsNone(ca.parse_amount(""))
        self.assertIsNone(ca.parse_amount(None))


class TestSummary(unittest.TestCase):
    def test_totals_and_lines(self):
        # (name, ЗП, офиц, наличные) — как в таблице выплат
        rows = [
            ("Дарья Вольнова", 37500, 12253, 0),
            ("Ксения Наныкина", 51362, 12253, 7747),
            ("Алена Черкашина", 111927, 12253, 2747),
            ("Владислава Герасимчук", 123000, 12253, 50000),
            ("Анна Кононенко (РОП)", 97200, 0, 15000),
        ]
        s = ca.build_summary(rows, "июль 2026")
        self.assertIn("К выплате наличными", s)
        # итог к выплате = только наличные (D); Папоян и Ия убраны из ведомости 11.08
        self.assertEqual(sum(d for _, _, _, d in rows), 75494)
        self.assertIn(ca._fmt(75494), s)
        self.assertIn("ИТОГО", s)
        self.assertIn("<pre>", s)  # моноширинная таблица

    def test_avans_summary_has_no_zp_column(self):
        rows = [("Ксения Наныкина", 51362, 12253, 7747)]
        s = ca.build_summary(rows)              # авансы — без ЗП
        self.assertNotIn("ЗП", s)
        self.assertIn("Офиц", s)
        self.assertIn("Нал", s)
        self.assertNotIn("51 362", s)           # ЗП не показывается

    def test_zarplata_summary_shows_zp_column(self):
        rows = [("Ксения Наныкина", 51362, 12253, 7747)]
        s = ca.build_summary(rows, show_zp=True)  # зарплата — с ЗП
        self.assertIn("ЗП", s)
        self.assertIn("51 362", s)

    def test_fmt(self):
        self.assertEqual(ca._fmt(7746), "7 746")
        self.assertEqual(ca._fmt(12253.78), "12 253,78")
        self.assertEqual(ca._fmt(0), "0")


if __name__ == "__main__":
    unittest.main()


class TestPlanFromLedger(unittest.TestCase):
    """★16.10.2026: план наличных строится из ведомости, а не из номеров строк.

    Прежний список (154-161) писал наличные в пустые строки ниже таблицы —
    ведомость уехала на 114-122 после приёма стажёров и двух увольнений.
    """

    LEDGER = [(116, "Дарья Вольнова"), (117, "Ксения Наныкина"),
              (118, "София Хакимова"), (119, "Виолетта Караханова"),
              (120, "Алена Черкашина"), (121, "Анна Кононенко (РОП)")]

    def test_stroki_iz_vedomosti(self):
        plan = ca.build_plan(self.LEDGER)
        self.assertEqual([(r, n) for r, n, _ in plan],
                         [(117, "Ксения"), (118, "София"), (119, "Виолетта"),
                          (120, "Алена"), (121, "Анна")])

    def test_darya_bez_nalichnyh(self):
        plan = ca.build_plan(self.LEDGER)
        self.assertNotIn("Дарья", [n for _, n, _ in plan])
        self.assertEqual(ca.no_cash_rows(self.LEDGER), {116: "Дарья"})

    def test_pravila_po_familii(self):
        plan = dict((n, rule) for _, n, rule in ca.build_plan(self.LEDGER))
        self.assertEqual(plan["Ксения"], ("total", 20000))
        self.assertEqual(plan["Алена"], ("total", 15000))
        self.assertEqual(plan["Анна"], ("fixed", 15000))
        self.assertEqual(plan["София"], ("ask", None))

    def test_sdvig_vedomosti_ne_lomaet(self):
        ledger = [(r - 40, n) for r, n in self.LEDGER]
        plan = ca.build_plan(ledger)
        self.assertEqual(plan[0][0], 77)
        self.assertEqual(plan[0][1], "Ксения")

    def test_novyy_sotrudnik_sprashivaem(self):
        plan = ca.build_plan([(130, "Ия Шарашанидзе")])
        self.assertEqual(plan, [(130, "Ия", ("ask", None))])

    def test_summa_dobivaetsya_do_rovnogo(self):
        # Ксения: офиц. 12 253,78 → наличными 20 000 − 12 253 = 7 747
        _, _, rule = ca.build_plan(self.LEDGER)[0]
        self.assertEqual(ca.compute_default(rule, 12253.78), 7747)
