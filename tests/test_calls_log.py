"""Журнал звонков по сменам (лист ЗВОНКИ) — вход для нормы Виолетты.

Норма из её индивидуальных условий считается за месяц и по каждой смене
(«в среднем не менее 30 успешных, и ни одной смены ниже 25»), поэтому цифры из
отчётов смен нужно накапливать, а не только сравнивать с порогом.

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_report
from sheets import SheetsClient


class _FakeCallsWS:
    """Лист ЗВОНКИ: только то, что использует log_calls."""

    def __init__(self, rows=None):
        self.rows = rows or [SheetsClient.CALLS_HEADER[:]]
        self.appended = []
        self.updated = []

    def get_all_values(self):
        return [[str(c) for c in r] for r in self.rows]

    def append_row(self, row, value_input_option=None):
        self.appended.append(row)
        self.rows.append(row)

    def update(self, values=None, range_name=None):
        self.updated.append((range_name, values[0]))
        row = int(range_name[1:])
        self.rows[row - 1] = values[0]

    def acell(self, a1):
        class _C:
            value = "Октябрь 2026"
        return _C()


class TestLogCalls(unittest.TestCase):
    def _client(self, ws=None):
        sc = SheetsClient.__new__(SheetsClient)
        self.ws = ws or _FakeCallsWS()
        sc._calls_ws = lambda month_label: self.ws
        sc._shifts_ws = lambda: self.ws
        return sc

    def _report(self, text):
        r = parse_report(text)
        self.assertIsNotNone(r, f"parse вернул None: {text!r}")
        return r

    _POISK = ("Смена Менеджер поиск\nСотрудник: Виолетта Караханова\nДата: 14\n"
              "Выполненные задачи: звонила по базе\n")

    def test_razbivka_uspeshnye_ot_minuty(self):
        sc = self._client()
        ok = sc.log_calls(self._report(
            self._POISK + "Звонки всего: 40\nЗвонки < 1 мин: 8\nЗвонки 1-2 мин: 20\n"
            "Звонки 2-5 мин: 10\nЗвонки > 5 мин: 2"), "Октябрь 2026")
        self.assertTrue(ok)
        row = self.ws.appended[0]
        self.assertEqual(row[:3], ["Октябрь 2026", 14, "Виолетта Караханова"])
        self.assertEqual(row[3], 40)          # всего
        self.assertEqual(row[8], 32)          # успешные: 20 + 10 + 2, короткие не в счёт

    def test_bez_razbivki_uspeshnye_vse(self):
        # разбивку по длительности заполняют не всегда — тогда берём «всего»
        sc = self._client()
        sc.log_calls(self._report(self._POISK + "Звонки всего: 31"), "Октябрь 2026")
        row = self.ws.appended[0]
        self.assertEqual(row[3], 31)
        self.assertEqual(row[8], 31)

    def test_povtornaya_smena_obnovlyaet_stroku(self):
        # ту же смену присылают заново (поправить задачи) — журнал не должен пухнуть
        ws = _FakeCallsWS([SheetsClient.CALLS_HEADER[:],
                           ["Октябрь 2026", "14", "Виолетта Караханова", "20",
                            "0", "20", "0", "0", "20", "2026-10-14 18:00"]])
        sc = self._client(ws)
        sc.log_calls(self._report(self._POISK + "Звонки всего: 33"), "Октябрь 2026")
        self.assertEqual(ws.appended, [])
        self.assertEqual(ws.updated[0][0], "A2")
        self.assertEqual(ws.updated[0][1][3], 33)

    def test_smena_bez_zvonkov_ne_pishetsya(self):
        # сопровождение и Влада звонки не сдают — журнал их не касается
        sc = self._client()
        ok = sc.log_calls(self._report(
            "Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 14\n"
            "Выполненные задачи: заказы\nТип(выходной/будний): будний"), "Октябрь 2026")
        self.assertFalse(ok)
        self.assertEqual(self.ws.appended, [])


if __name__ == "__main__":
    unittest.main()
