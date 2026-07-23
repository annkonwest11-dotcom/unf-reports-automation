"""Юнит-тесты на чистую логику (без сети/Google/1С).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_report
from sheets import (
    SheetsClient,
    _parse_period,
    _next_month_label,
    _strip_month,
    _parse_day_range,
    _format_period_label,
)


class TestParser(unittest.TestCase):
    def test_manager_poisk(self):
        text = (
            "смена менеджер поиск\n"
            "сотрудник: Валерия Абрамова\n"
            "дата: 25\n"
            "звонки всего: 30\n"
        )
        r = parse_report(text)
        self.assertIsNotNone(r)
        self.assertEqual(r.manager_type, "поиск")
        self.assertEqual(r.employee, "Валерия Абрамова")
        self.assertEqual(r.date, "25")
        self.assertEqual(r.calls_total, "30")

    def test_manager_soprovozhdenie(self):
        text = (
            "смена менеджер сопровождение\n"
            "сотрудник: Дарья Вольнова\n"
            "дата: 10\n"
        )
        r = parse_report(text)
        self.assertIsNotNone(r)
        self.assertEqual(r.manager_type, "сопровождение")

    def test_vlada(self):
        text = "смена влада\nсотрудник: Владислава Герасимчук\nдата: 3\nзаказы: будний\n"
        r = parse_report(text)
        self.assertIsNotNone(r)
        self.assertEqual(r.manager_type, "влада")

    def test_empty_returns_none(self):
        self.assertIsNone(parse_report(""))
        self.assertIsNone(parse_report("   \n  "))

    def test_missing_required_fields_returns_none(self):
        # нет даты -> None
        self.assertIsNone(parse_report("смена менеджер поиск\nсотрудник: Кто-то\n"))


def _shifts_fixture():
    """Снимок раскладки листа СМЕНЫ (после удаления Лианны/Абрамовой 2026-07-11):
    осн. смены строки 5-10, подработки 15-17. Колонки: A=№, B=ФИО, C=отдел,
    D=ставка, E.. = дни 1-31. Без сети — чистая логика записи смен."""
    days = [str(d) for d in range(1, 32)]
    empty = [""] * 31
    return [
        ["СМЕНЫ — Учёт рабочих дней", "", "", ""] + empty,           # 1
        ["Июль 2026", "", "", ""] + empty,                           # 2
        ["ОСНОВНЫЕ СМЕНЫ", "", "", ""] + empty,                      # 3
        ["№", "Сотрудник", "Отдел", "Ставка"] + days,               # 4 (заголовок дней)
        ["1", "Дарья Вольнова", "Отдел продаж", "2500"] + empty,     # 5
        ["2", "Ксения Наныкина", "Отдел продаж", "2500"] + empty,    # 6
        ["3", "Валерия Папоян", "Отдел продаж", "2500"] + empty,     # 7
        ["4", "Алена Черкашина", "Отдел продаж", "2500"] + empty,    # 8
        ["5", "Владислава Герасимчук", "Отдел продаж", "3000"] + empty,  # 9
        ["6", "Анна Кононенко (РОП)", "Отдел продаж", "5000"] + empty,   # 10
        ["", "", "", ""] + empty,                                    # 11
        ["", "", "", ""] + empty,                                    # 12
        ["ПОДРАБОТКИ (выходные смены, доп. ставки)", "", "", ""] + empty,  # 13
        ["№", "", "", ""] + empty,                                   # 14
        ["1", "Алена Черкашина", "Отдел продаж", ""] + empty,        # 15
        ["2", "Владислава Герасимчук", "Отдел продаж", ""] + empty,  # 16
        ["3", "Анна Кононенко (РОП)", "Отдел продаж", ""] + empty,   # 17
    ]


class _FakeWS:
    def __init__(self, rows):
        self._rows = rows
        self.writes = []  # список (row, col, value)

    def get_all_values(self):
        return [r[:] for r in self._rows]

    def update_cell(self, r, c, v):
        self.writes.append((r, c, v))


class TestShiftWriting(unittest.TestCase):
    """Сквозная логика записи смен (update_report/write_shift) на раскладке
    после удаления Лианны/Абрамовой. Ставки — из docs/ЧЕК-ЛИСТ_для_бота.md."""

    def _client(self):
        sc = SheetsClient.__new__(SheetsClient)
        self.fake = _FakeWS(_shifts_fixture())
        sc._shifts_ws = lambda: self.fake
        return sc

    def _run(self, text):
        sc = self._client()
        report = parse_report(text)
        self.assertIsNotNone(report, f"parse вернул None: {text!r}")
        sc.update_report(report)
        return {w[0]: w[2] for w in self.fake.writes}  # {row: value}

    def test_poisk_osn_2500(self):
        for who, row in [("Дарья Вольнова", 5), ("Ксения Наныкина", 6), ("Валерия Папоян", 7)]:
            got = self._run(f"Смена Менеджер поиск\nСотрудник: {who}\nДата: 15\nЗвонки всего: 20")
            self.assertEqual(got.get(row), "2500", who)

    _V = "Смена Влада\nСотрудник: Владислава Герасимчук\nДата: 15\n"

    def test_vlada_budni_yes(self):
        # будни=да → осн.3000 + подраб.2000
        got = self._run(self._V + "Заказы будни (да/нет): да\nЗаказы выхи (да/нет):")
        self.assertEqual(got.get(9), "3000")
        self.assertEqual(got.get(16), "2000")

    def test_vlada_budni_no(self):
        # будни=нет, выхи пусто → только осн.3000
        got = self._run(self._V + "Заказы будни (да/нет): нет\nЗаказы выхи (да/нет):")
        self.assertEqual(got.get(9), "3000")
        self.assertEqual(got.get(16), "")

    def test_vlada_vyhi_yes(self):
        # выхи=да → осн.не ставим, только подраб.2000
        got = self._run(self._V + "Заказы будни (да/нет):\nЗаказы выхи (да/нет): да")
        self.assertEqual(got.get(9), "")
        self.assertEqual(got.get(16), "2000")

    def test_vlada_both_no(self):
        # оба нет/пусто → осн.3000 (Анна, 2026-07-11)
        got = self._run(self._V + "Заказы будни (да/нет): нет\nЗаказы выхи (да/нет): нет")
        self.assertEqual(got.get(9), "3000")
        self.assertEqual(got.get(16), "")

    def test_vlada_autofill_employee(self):
        # ФИО не заполнено — именной шаблон подставляет «Владислава Герасимчук»
        got = self._run("Смена Влада\nДата: 15\nЗаказы выхи (да/нет): да")
        self.assertEqual(got.get(9), "")
        self.assertEqual(got.get(16), "2000")

    def test_vlada_vyhi_no_colon(self):
        # «Заказы выхи (да/нет)да» без двоеточия — значение распознаётся
        got = self._run(self._V + "Заказы будни (да/нет): нет\nЗаказы выхи (да/нет)да")
        self.assertEqual(got.get(9), "")
        self.assertEqual(got.get(16), "2000")

    def test_vlada_tasks_with_keyword_not_field(self):
        # строка задачи, начинающаяся не с ключа, не ломает поля (осн.3000 остаётся)
        got = self._run(self._V + "Выполненные задачи: разобрал заказы будни утром\nЗаказы будни (да/нет): да")
        self.assertEqual(got.get(9), "3000")
        self.assertEqual(got.get(16), "2000")

    def test_vlada_legacy_orders_yes(self):
        # обратная совместимость: старое поле «Заказы (да/нет)» = будни
        got = self._run(self._V + "Заказы (да/нет): да")
        self.assertEqual(got.get(9), "3000")
        self.assertEqual(got.get(16), "2000")

    def test_vlada_legacy_orders_no(self):
        got = self._run(self._V + "Заказы (да/нет): нет")
        self.assertEqual(got.get(9), "3000")
        self.assertEqual(got.get(16), "")

    def test_soprovozhdenie_budniy(self):
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\nТип: будний\nФирмы: нет")
        self.assertEqual(got.get(8), "2500")
        self.assertEqual(got.get(15), "")

    def test_soprovozhdenie_budniy_firmy(self):
        # Фирмы дают подработку в ЛЮБОЙ день (Анна, 2026-07-11): будни → осн.2500 + фирмы 1800
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\nТип: будний\nФирмы: да")
        self.assertEqual(got.get(8), "2500")
        self.assertEqual(got.get(15), "1800")

    def test_soprovozhdenie_vyhodnoy_firmy_2tel(self):
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\nТип: выходной\nФирмы: да\nЗаказы выходные: 2")
        self.assertEqual(got.get(8), "")
        self.assertEqual(got.get(15), "3900")  # 1800 фирмы + 2100 тел2

    def test_soprovozhdenie_vyhodnoy_rest_1tel(self):
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\nТип: выходной\nФирмы: нет\nЗаказы выходные: 1")
        self.assertEqual(got.get(15), "1800")

    def test_soprovozhdenie_vyhodnoy_rest_2tel(self):
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\nТип: выходной\nФирмы: нет\nЗаказы выходные: 2")
        self.assertEqual(got.get(15), "2100")

    def test_soprovozhdenie_budniy_dop_tel(self):
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\nТип: будний\nФирмы: нет\nЗаказы будние: да")
        self.assertEqual(got.get(8), "2500")
        self.assertEqual(got.get(15), "1800")

    def test_rop_auto_shift(self):
        sc = self._client()
        ok = sc.write_shift("Анна Кононенко (РОП)", 15)
        self.assertTrue(ok)
        got = {w[0]: w[2] for w in self.fake.writes}
        self.assertEqual(got.get(10), "5000")


class TestPeriodHelpers(unittest.TestCase):
    def test_strip_month(self):
        rest, num = _strip_month("Май 2026")
        self.assertEqual(num, 5)
        self.assertEqual(rest, "2026")

    def test_parse_period(self):
        self.assertEqual(_parse_period("Май 2026"), (5, 2026))
        self.assertEqual(_parse_period("Декабрь 2025"), (12, 2025))

    def test_next_month_label(self):
        self.assertEqual(_next_month_label("Май 2026"), "Июнь 2026")
        # переход через год
        self.assertEqual(_next_month_label("Декабрь 2026"), "Январь 2027")

    def test_parse_day_range_single(self):
        self.assertEqual(_parse_day_range("25 мая"), {25})

    def test_parse_day_range_interval(self):
        self.assertEqual(_parse_day_range("1-15 мая"), set(range(1, 16)))

    def test_parse_day_range_whole_month(self):
        # только месяц без дней -> весь диапазон
        self.assertEqual(_parse_day_range("Май 2026"), set(range(1, 32)))

    def test_format_period_label_day(self):
        label = _format_period_label("25 мая")
        self.assertIn("25 мая", label)


class TestDayParsing(unittest.TestCase):
    def test_parse_day_plain(self):
        self.assertEqual(SheetsClient._parse_day("25"), 25)

    def test_parse_day_dotted(self):
        self.assertEqual(SheetsClient._parse_day("25.06"), 25)

    def test_parse_day_invalid(self):
        self.assertIsNone(SheetsClient._parse_day("abc"))


if __name__ == "__main__":
    unittest.main()
