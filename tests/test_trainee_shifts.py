"""Стажёрская ставка 1700 — за ПЕРВЫЕ СЕМЬ смен за всё время, не каждый месяц.

Счётчик «смен отработано в прошлых месяцах» в НАСТРОЙКАХ обновлялся руками и в
октябре 2026 остался нулём: София и Виолетта снова получили дешёвые смены, хотя
свои семь выбрали ещё в сентябре (недоплата 4 800 и 5 600 ₽). Теперь счётчик
наращивает закрытие месяца.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sheets import SheetsClient


class TestTraineeCounters(unittest.TestCase):
    COL_A = ["НАСТРОЙКИ", "", "РАСЧЁТНЫЙ ПЕРИОД", "Месяц и год расчёта", "",
             "СТАЖЁРСКАЯ СТАВКА СМЕНЫ", "Параметр", "Ставка первых смен",
             "Смен по стажёрской ставке",
             "София Хакимова — смен отработано в прошлых месяцах",
             "Виолетта Караханова — смен отработано в прошлых месяцах"]

    def test_nahodit_stroki_schetchikov(self):
        self.assertEqual(SheetsClient._trainee_counters(self.COL_A),
                         {"София Хакимова": 10, "Виолетта Караханова": 11})

    def test_sdvig_nastroek_ne_lomaet(self):
        # ★перед этим в НАСТРОЙКИ вставлен личный план Виолетты — всё уехало вниз
        shifted = ["", ""] + self.COL_A
        self.assertEqual(SheetsClient._trainee_counters(shifted),
                         {"София Хакимова": 12, "Виолетта Караханова": 13})

    def test_bez_stazherov_pusto(self):
        self.assertEqual(SheetsClient._trainee_counters(self.COL_A[:9]), {})

    def test_tire_lyubogo_vida(self):
        for dash in ("—", "–", "-"):
            col = [f"Ия Шарашанидзе {dash} смен отработано в прошлых месяцах"]
            self.assertEqual(SheetsClient._trainee_counters(col), {"Ия Шарашанидзе": 1}, dash)


class TestShiftCounts(unittest.TestCase):
    def _sheet(self):
        return [
            ["СМЕНЫ — Учёт рабочих дней"],
            ["Октябрь 2026"],
            ["ОСНОВНЫЕ СМЕНЫ"],
            ["№", "Сотрудник", "Должность", "Ставка", "1", "2", "3"],
            ["1", "Дарья Вольнова", "Отдел продаж", "2500", "2500", "", "2500"],
            ["4", "София Хакимова", "Отдел продаж", "1700", "1700", "1700", "1700"],
            ["", "", "", "", "", "", ""],
            ["ПОДРАБОТКИ"],
            ["1", "Алена Черкашина", "Отдел продаж", "", "3600", "", ""],
        ]

    def test_schitaet_zapolnennye_kletki(self):
        got = SheetsClient._shift_counts(self._sheet())
        self.assertEqual(got["София Хакимова"], 3)
        self.assertEqual(got["Дарья Вольнова"], 2)

    def test_podrabotki_summiruyutsya_s_osnovnymi(self):
        rows = self._sheet() + [["2", "София Хакимова", "", "", "3600", "", ""]]
        self.assertEqual(SheetsClient._shift_counts(rows)["София Хакимова"], 4)

    def test_pustye_stroki_i_shapka_ne_schitayutsya(self):
        got = SheetsClient._shift_counts(self._sheet())
        self.assertNotIn("Сотрудник", got)
        self.assertNotIn("", got)

    def test_bez_smen_v_slovar_ne_popadaet(self):
        rows = [["1", "Ия Шарашанидзе", "", "2500", "", "", ""]]
        self.assertEqual(SheetsClient._shift_counts(rows), {})


class TestBump(unittest.TestCase):
    """Накопление: было 6 смен, за месяц ещё 21 → в счётчике 27."""

    class FakeSettings:
        def __init__(self, col, vals):
            self._col, self._vals, self.written = col, vals, []

        def col_values(self, n):
            return self._col

        def acell(self, a1):
            return type("C", (), {"value": self._vals.get(a1)})()

        def batch_update(self, updates, value_input_option=None):
            self.written += [(u["range"], u["values"][0][0]) for u in updates]

    class FakeSmeny:
        def __init__(self, rows):
            self._rows = rows

        def get(self, rng):
            return self._rows

    def test_pribavlyaet_smeny_mesyaca(self):
        col = ["", "София Хакимова — смен отработано в прошлых месяцах"]
        st = self.FakeSettings(col, {"B2": "6"})
        sm = self.FakeSmeny([["4", "София Хакимова", "", "1700", "1700", "2500", "2500"]])
        got = SheetsClient._bump_trainee_shifts(SheetsClient.__new__(SheetsClient), st, sm)
        self.assertEqual(got, {"София Хакимова": 9})
        self.assertEqual(st.written, [("B2", 9)])

    def test_pustoy_schetchik_chitaetsya_kak_nol(self):
        col = ["Виолетта Караханова — смен отработано в прошлых месяцах"]
        st = self.FakeSettings(col, {"B1": ""})
        sm = self.FakeSmeny([["5", "Виолетта Караханова", "", "", "1700", "1700"]])
        got = SheetsClient._bump_trainee_shifts(SheetsClient.__new__(SheetsClient), st, sm)
        self.assertEqual(got, {"Виолетта Караханова": 2})

    def test_kto_ne_rabotal_ne_trogaetsya(self):
        col = ["Ия Шарашанидзе — смен отработано в прошлых месяцах"]
        st = self.FakeSettings(col, {"B1": "3"})
        sm = self.FakeSmeny([["1", "Дарья Вольнова", "", "2500", "2500"]])
        self.assertEqual(SheetsClient._bump_trainee_shifts(SheetsClient.__new__(SheetsClient), st, sm), {})
        self.assertEqual(st.written, [])


if __name__ == "__main__":
    unittest.main()
