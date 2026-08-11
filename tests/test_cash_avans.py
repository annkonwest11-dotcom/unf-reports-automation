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
