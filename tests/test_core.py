"""Юнит-тесты на чистую логику (без сети/Google/1С).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sheets as sheets_module
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
    """Снимок раскладки листа СМЕНЫ (после удаления Папоян 2026-08-11):
    осн. смены строки 5-9, подработки 14-16. Колонки: A=№, B=ФИО, C=отдел,
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
        ["3", "Алена Черкашина", "Отдел продаж", "2500"] + empty,    # 7
        ["4", "Владислава Герасимчук", "Отдел продаж", "3000"] + empty,  # 8
        ["5", "Анна Кононенко (РОП)", "Отдел продаж", "5000"] + empty,   # 9
        ["", "", "", ""] + empty,                                    # 10
        ["", "", "", ""] + empty,                                    # 11
        ["ПОДРАБОТКИ (выходные смены, доп. ставки)", "", "", ""] + empty,  # 12
        ["№", "", "", ""] + empty,                                   # 13
        ["1", "Алена Черкашина", "Отдел продаж", ""] + empty,        # 14
        ["2", "Владислава Герасимчук", "Отдел продаж", ""] + empty,  # 15
        ["3", "Анна Кононенко (РОП)", "Отдел продаж", ""] + empty,   # 16
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
        for who, row in [("Дарья Вольнова", 5), ("Ксения Наныкина", 6)]:
            got = self._run(f"Смена Менеджер поиск\nСотрудник: {who}\nДата: 15\nЗвонки всего: 20")
            self.assertEqual(got.get(row), "2500", who)

    _V = "Смена Влада\nСотрудник: Владислава Герасимчук\nДата: 15\n"

    def test_vlada_budni_yes(self):
        # будни=да → осн.3000 + подраб.2000
        got = self._run(self._V + "Заказы будни (да/нет): да\nЗаказы выхи (да/нет):")
        self.assertEqual(got.get(8), "3000")
        self.assertEqual(got.get(15), "2000")

    def test_vlada_budni_no(self):
        # будни=нет, выхи пусто → только осн.3000
        got = self._run(self._V + "Заказы будни (да/нет): нет\nЗаказы выхи (да/нет):")
        self.assertEqual(got.get(8), "3000")
        self.assertEqual(got.get(15), "")

    def test_vlada_vyhi_yes(self):
        # выхи=да → осн.не ставим, только подраб.2000
        got = self._run(self._V + "Заказы будни (да/нет):\nЗаказы выхи (да/нет): да")
        self.assertEqual(got.get(8), "")
        self.assertEqual(got.get(15), "2000")

    def test_vlada_both_no(self):
        # оба нет/пусто → осн.3000 (Анна, 2026-07-11)
        got = self._run(self._V + "Заказы будни (да/нет): нет\nЗаказы выхи (да/нет): нет")
        self.assertEqual(got.get(8), "3000")
        self.assertEqual(got.get(15), "")

    def test_vlada_autofill_employee(self):
        # ФИО не заполнено — именной шаблон подставляет «Владислава Герасимчук»
        got = self._run("Смена Влада\nДата: 15\nЗаказы выхи (да/нет): да")
        self.assertEqual(got.get(8), "")
        self.assertEqual(got.get(15), "2000")

    def test_vlada_vyhi_no_colon(self):
        # «Заказы выхи (да/нет)да» без двоеточия — значение распознаётся
        got = self._run(self._V + "Заказы будни (да/нет): нет\nЗаказы выхи (да/нет)да")
        self.assertEqual(got.get(8), "")
        self.assertEqual(got.get(15), "2000")

    def test_vlada_tasks_with_keyword_not_field(self):
        # строка задачи, начинающаяся не с ключа, не ломает поля (осн.3000 остаётся)
        got = self._run(self._V + "Выполненные задачи: разобрал заказы будни утром\nЗаказы будни (да/нет): да")
        self.assertEqual(got.get(8), "3000")
        self.assertEqual(got.get(15), "2000")

    def test_vlada_legacy_orders_yes(self):
        # обратная совместимость: старое поле «Заказы (да/нет)» = будни
        got = self._run(self._V + "Заказы (да/нет): да")
        self.assertEqual(got.get(8), "3000")
        self.assertEqual(got.get(15), "2000")

    def test_vlada_legacy_orders_no(self):
        got = self._run(self._V + "Заказы (да/нет): нет")
        self.assertEqual(got.get(8), "3000")
        self.assertEqual(got.get(15), "")

    def test_soprovozhdenie_budniy(self):
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\nТип: будний\nФирмы: нет")
        self.assertEqual(got.get(7), "2500")
        self.assertEqual(got.get(14), "")

    def test_soprovozhdenie_novyy_shablon_budniy(self):
        # ★Новый шаблон Анны (15.10.2026): только Сотрудник / Дата / Задачи / Тип.
        # «Тип(выходной/будний):» пишут без пробела перед скобкой — тоже читаем.
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\n"
                        "Дата: 15\nВыполненные задачи: разобрала заказы\n"
                        "Тип(выходной/будний): будний")
        self.assertEqual(got.get(7), "2500")
        self.assertEqual(got.get(14), "")

    def test_soprovozhdenie_novyy_shablon_vyhodnoy(self):
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\n"
                        "Дата: 15\nВыполненные задачи: приняла заказы\n"
                        "Тип(выходной/будний): выходной")
        self.assertEqual(got.get(7), "")
        self.assertEqual(got.get(14), "3600")

    def test_soprovozhdenie_vyhodnoy_starye_polya_ne_dobavlyayut(self):
        # Пришлют старый шаблон — выходной всё равно одна ставка 3600:
        # надбавок за фирмы (+1000) и «заказы выходные» (+1800) больше нет.
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\n"
                        "Тип: выходной\nФирмы: да\nЗаказы выходные: 2")
        self.assertEqual(got.get(7), "")
        self.assertEqual(got.get(14), "3600")

    def test_soprovozhdenie_budniy_starye_polya_ne_dobavlyayut(self):
        # «Заказы будние» (доп. телефон) давали +1800 — отменено вместе с пунктом
        got = self._run("Смена Менеджер сопровождение\nСотрудник: Алена Черкашина\nДата: 15\n"
                        "Тип: будний\nФирмы: да\nЗаказы будние: да")
        self.assertEqual(got.get(7), "2500")
        self.assertEqual(got.get(14), "")

    def test_rop_auto_shift(self):
        sc = self._client()
        ok = sc.write_shift("Анна Кононенко (РОП)", 15)
        self.assertTrue(ok)
        got = {w[0]: w[2] for w in self.fake.writes}
        self.assertEqual(got.get(9), "5000")


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


class TestShiftRanges(unittest.TestCase):
    """Диапазоны дней листа смен — по подписям секций, а не по номерам строк.

    Номера уезжают при каждом кадровом изменении: после увольнения Лилии и Влады
    основные смены стали 5-10, подработки 15-16 (были 5-12 и 17-19). На этих
    границах держатся чистка листа при закрытии месяца и промоут СМЕНЫ_СЛЕД.
    """

    class _WS:
        def __init__(self, rows):
            self._rows = rows

        def get_all_values(self):
            return [r[:] for r in self._rows]

    def _client(self):
        return SheetsClient.__new__(SheetsClient)

    def _rows(self, main, extra):
        out = [["СМЕНЫ — Учёт рабочих дней", "", "", ""], ["Октябрь 2026", "", "", ""],
               ["ОСНОВНЫЕ СМЕНЫ", "", "", ""], ["№", "Сотрудник", "Отдел", "Ставка"]]
        for i, name in enumerate(main, 1):
            out.append([str(i), name, "Отдел продаж", "2500"])
        out += [["", "", "", ""], ["ПОДРАБОТКИ (выходные смены)", "", "", ""],
                ["№", "", "", ""]]
        for i, name in enumerate(extra, 1):
            out.append([str(i), name, "Отдел продаж", ""])
        return out

    def test_posle_uvolneniy(self):
        rows = self._rows(["Дарья", "Ксения", "София", "Виолетта", "Алена", "Анна"],
                          ["Алена", "Анна"])
        a1, bounds = self._client()._shift_ranges(self._WS(rows))
        self.assertEqual(a1, ["E5:AI10", "E14:AI15"])
        self.assertEqual(bounds, [(4, 10), (13, 15)])

    def test_dobavili_cheloveka(self):
        rows = self._rows(["Дарья", "Ксения", "София", "Виолетта", "Алена", "Анна", "Новый"],
                          ["Алена", "Анна"])
        a1, _ = self._client()._shift_ranges(self._WS(rows))
        self.assertEqual(a1[0], "E5:AI11")

    def test_bez_podpisey_zapasnye(self):
        # лист без секций — отдаём запасные диапазоны, а не пустую чистку
        a1, bounds = self._client()._shift_ranges(self._WS([["что-то", "", "", ""]]))
        self.assertEqual(a1, list(sheets_module._SHIFT_DAY_RANGES))
        self.assertEqual(bounds, [(4, 12), (16, 19)])
