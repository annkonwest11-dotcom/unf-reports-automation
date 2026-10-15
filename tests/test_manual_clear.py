"""Чистка ручных ячеек СВОДНОЙ при закрытии месяца — по подписям, не по адресам.

Раскладка СВОДНОЙ уезжает при каждом кадровом изменении (добавили стажёров — всё
ниже сдвинулось на 28 строк; уволились Лилия и Влада — уедет снова). С жёсткими
адресами чистка попадала бы в чужие ячейки и затирала формулы, поэтому строки
ищутся по подписям. Тесты проверяют и совпадение с прежним поведением, и
устойчивость к сдвигу.

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sheets import SheetsClient


def _block(name, premium_in_e=False):
    """Строки одного блока сотрудника: суммы + доп.премия + комментарий."""
    prem_c = "=E" if premium_in_e else "20000"
    return [
        [f"  {name}  |  Менеджер", "", "", "", "", "", "", ""],
        ["Смены", "из СМЕН", "=IFERROR('СМЕНЫ'!AJ5;0)", "", "", "", "", ""],
        ["Конкурс (бонусы)", "", "0", "", "", "", "", ""],
        ["Дополнительная премия", "", prem_c, "", "20000" if premium_in_e else "", "", "", ""],
        ["Комментарий к доп.премии", "", "", "", "за выходные" if premium_in_e else "", "", "", ""],
        [f"ИТОГО ЗП — {name}", "", "=C2+C4", "", "", "", "", ""],
    ]


def _fixture(with_helper=True):
    rows = [["СВОДНАЯ ЗАРПЛАТНАЯ ВЕДОМОСТЬ", "", "", "", "", "", "", ""]]
    rows += _block("Дарья Вольнова")
    rows += _block("Ксения Наныкина")
    # РОП: в C формулы, ручной ввод в E
    rows += [
        ["  Анна Кононенко (РОП)", "", "", "", "", "", "", ""],
        ["Факт — новые продажи", "", "0", "", "=SUMIF(…)", "", "", ""],
        ["Факт — оборот", "", "0", "", "7930375", "", "", ""],
        ["Факт — поступления", "", "0", "", "7242507", "", "", ""],
        ["Дополнительная премия", "", "=IF(ISNUMBER(E);E;0)", "", "", "", "", ""],
        ["Комментарий к доп.премии", "", "", "", "", "", "", ""],
        ["ИТОГО ЗП — Анна Кононенко (РОП)", "", "=C13+C14", "", "", "", "", ""],
    ]
    if with_helper:
        rows += [
            ["  Владислава Герасимчук", "", "", "", "", "", "", ""],
            ["Премия за контент", "", "=IF(E>=90;5000;0)", "", "103", "", "", ""],
            ["Клиенты SMM", "", "=7000*E+4000*F", "", "1", "", "", ""],
            ["Найм: менеджер (месяц)", "", "=E*20000", "", "0", "", "", ""],
            ["Премия за проекты", "", "=E", "", "", "", "", ""],
            ["Дополнительная премия", "", "=E", "", "7000", "", "", ""],
            ["Комментарий к доп.премии", "", "", "", "за проект", "", "", ""],
            ["ИТОГО ЗП — Владислава Герасимчук", "", "=C20", "", "", "", "", ""],
        ]
    rows += [
        ["ТАБЛИЦА ВЫПЛАТ ЗА МЕСЯЦ", "", "", "", "", "", "", ""],
        ["Сотрудник", "Итого ЗП", "Аванс карта", "Аванс нал", "ЗП карта", "Остаток", "", ""],
        ["Дарья Вольнова", "=C7", "12811", "", "12811", "=B-C-D-E", "", ""],
        ["Ксения Наныкина", "=C13", "12811", "7189", "12811", "=B-C-D-E", "", ""],
        ["ИТОГО", "=SUM(B:B)", "", "", "", "", "", ""],
    ]
    return rows


class TestManualClearRanges(unittest.TestCase):
    def _ranges(self, rows):
        # значения и формулы различаются только тем, что формулы начинаются с «=»
        values = [[("" if str(c).startswith("=") else c) for c in r] for r in rows]
        return SheetsClient._manual_clear_ranges(values, rows)

    def test_menedzher_premiya_v_c(self):
        got = self._ranges(_fixture())
        # у менеджера доп.премия введена прямо в C → чистим C, комментарий тоже C
        self.assertIn("C5", got)
        self.assertIn("C6", got)

    def test_rop_premiya_i_kommentariy_v_e(self):
        got = self._ranges(_fixture())
        # у РОП в C формула, ручной ввод в E — и комментарий там же
        self.assertIn("E18", got)      # доп.премия
        self.assertIn("E19", got)      # комментарий к ней
        self.assertNotIn("C18", got)

    def test_fakty_ropa_chistyatsya_a_novye_prodazhi_net(self):
        got = self._ranges(_fixture())
        self.assertIn("E16", got)     # факт — оборот
        self.assertIn("E17", got)     # факт — поступления
        self.assertNotIn("E15", got)  # «Факт — новые продажи» — формула, не трогаем

    def test_konkurs_ne_chistitsya(self):
        # формула по листу КОНКУРС однажды погибла от чистки — больше не чистим
        rows = _fixture()
        konkurs = [i + 1 for i, r in enumerate(rows) if r[0] == "Конкурс (бонусы)"]
        got = self._ranges(rows)
        for i in konkurs:
            self.assertNotIn(f"C{i}", got)

    def test_tablica_vyplat_odnim_diapazonom(self):
        got = self._ranges(_fixture())
        # строки сотрудников таблицы выплат (у них B — ссылка на ИТОГО), колонки C:E
        self.assertTrue(any(r.startswith("C") and ":E" in r for r in got), got)

    def test_sdvig_raskladki_ne_lomaet(self):
        # уволились помощник и один менеджер: все строки ниже уехали, но подписи те же
        full = self._ranges(_fixture())
        short = self._ranges(_fixture(with_helper=False))
        self.assertNotEqual(full, short)
        # у РОП премия по-прежнему находится и по-прежнему в E
        self.assertTrue(any(r.startswith("E") for r in short), short)
        # и ни один диапазон не ссылается на строки за пределами листа
        last = len(_fixture(with_helper=False))
        for r in short:
            row = int("".join(ch for ch in r.split(":")[0] if ch.isdigit()))
            self.assertLessEqual(row, last, r)


if __name__ == "__main__":
    unittest.main()
