"""Тесты zp_files: список «переведённых в начале месяца» — по подписи раздела."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zp_files


class FakeWS:
    def __init__(self, col):
        self._col = col

    def col_values(self, n):
        return self._col


class FakeSS:
    def __init__(self, col):
        self._ws = FakeWS(col)

    def worksheet(self, name):
        assert name == "НАСТРОЙКИ"
        return self._ws


BASE = ["НАСТРОЙКИ", "", "РАСЧЁТНЫЙ ПЕРИОД", "Месяц и год расчёта", "",
        "ПЛАНЫ НА МЕСЯЦ", "Сотрудник / группа", "Менеджеры поиска (каждый)"]


class TestMovedClients(unittest.TestCase):
    def test_chitaet_spisok_pod_zagolovkom(self):
        col = BASE + ["", "КЛИЕНТЫ, ПЕРЕВЕДЁННЫЕ В НАЧАЛЕ МЕСЯЦА — считаем с октября",
                      "Контрагент (имя как в листах ДАННЫЕ)",
                      "ЛОМОНОСОВ (ООО СК2)", "Гастроном Времена ООО", ""]
        self.assertEqual(zp_files._moved_clients(FakeSS(col)),
                         ["ЛОМОНОСОВ (ООО СК2)", "Гастроном Времена ООО"])

    def test_vstavka_stroki_vyshe_ne_lomaet(self):
        # ровно тот случай, из-за которого срез [45:51] заменён поиском по подписи
        col = BASE + ["Виолетта Караханова — личный план", "",
                      "КЛИЕНТЫ, ПЕРЕВЕДЁННЫЕ В НАЧАЛЕ МЕСЯЦА",
                      "Контрагент (имя как в листах ДАННЫЕ)", "АльмаМоре (ООО СОЛ МООН)"]
        self.assertEqual(zp_files._moved_clients(FakeSS(col)), ["АльмаМоре (ООО СОЛ МООН)"])

    def test_bez_razdela_pustoy_spisok(self):
        self.assertEqual(zp_files._moved_clients(FakeSS(BASE)), [])

    def test_bez_yo_tozhe_nahodit(self):
        col = BASE + ["КЛИЕНТЫ, ПЕРЕВЕДЕННЫЕ В НАЧАЛЕ МЕСЯЦА", "Контрагент", "Бибирево ООО Марула"]
        self.assertEqual(zp_files._moved_clients(FakeSS(col)), ["Бибирево ООО Марула"])

    def test_ostanavlivaetsya_na_pustoy_stroke(self):
        col = BASE + ["КЛИЕНТЫ, ПЕРЕВЕДЁННЫЕ В НАЧАЛЕ МЕСЯЦА", "Контрагент",
                      "ЛОМОНОСОВ (ООО СК2)", "", "ДРУГОЙ РАЗДЕЛ", "что-то ещё"]
        self.assertEqual(zp_files._moved_clients(FakeSS(col)), ["ЛОМОНОСОВ (ООО СК2)"])


if __name__ == "__main__":
    unittest.main()


class TestSearchReportName(unittest.TestCase):
    """Имя файла взаиморасчётов — «Взаиморасчеты ФАМИЛИЯ ИМЯ» для любого состава."""

    @staticmethod
    def fname(who):
        parts = who.split()
        fio = f"{parts[-1].upper()} {parts[0].upper()}" if len(parts) > 1 else who.upper()
        return f"Взаиморасчеты {fio}"

    def test_imya_familiya(self):
        self.assertEqual(self.fname("Дарья Вольнова"), "Взаиморасчеты ВОЛЬНОВА ДАРЬЯ")
        self.assertEqual(self.fname("Виолетта Караханова"),
                         "Взаиморасчеты КАРАХАНОВА ВИОЛЕТТА")

    def test_odno_slovo(self):
        self.assertEqual(self.fname("Ия"), "Взаиморасчеты ИЯ")
