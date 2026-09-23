"""Распознавание колонок менеджеров в KPI-таблице (без сети).

Анна пишет заголовок то «Менеджер Дарья», то просто «Дарья» — 23.09.2026 из-за
точного сравнения за сентябрь распозналась бы одна колонка «Анна», и у всех
менеджеров поиска % плана уехал бы в ноль.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_novye import KPI_MANAGERS, kpi_key


def managers(headers):
    return {KPI_MANAGERS[kpi_key(h)][0] for h in headers if kpi_key(h) in KPI_MANAGERS}


class TestKpiHeaders(unittest.TestCase):
    # лист «август-сентябрь» — имена без слова «Менеджер»
    SEPT = ["Ресторан", "Юр лицо", "Создан", "Классифицкация",
            "до какого числа считаем (+30 дней)",
            "Дарья", "Алена", "Ксения", "Лилия", "София", "Виолетта", "Анна", "ИТОГ"]
    # лист «июль-август» — со словом «Менеджер»
    AUG = ["чемодан", "Юр лицо", "Создан", "Классифицкация", "до какого числа",
           "Менеджер Дарья", "Менеджер Алена", "Менеджер Ксения", "Менеджер Лилия",
           "Анна", "Влада", "ИТОГ"]

    def test_headers_without_prefix(self):
        self.assertEqual(
            managers(self.SEPT),
            {"Дарья Вольнова", "Алена Черкашина", "Ксения Наныкина", "Лилия Сулименко",
             "София Хакимова", "Виолетта Караханова", "Анна Кононенко (РОП)"})

    def test_headers_with_prefix(self):
        self.assertIn("Дарья Вольнова", managers(self.AUG))
        self.assertIn("Лилия Сулименко", managers(self.AUG))

    def test_yo_and_case(self):
        self.assertEqual(kpi_key("Менеджер Алёна"), "алена")
        self.assertEqual(kpi_key("  МЕНЕДЖЕР  Дарья "), "дарья")

    def test_service_columns_not_managers(self):
        for h in ("ИТОГ", "Юр лицо", "Ресторан", "Создан", ""):
            self.assertNotIn(kpi_key(h), KPI_MANAGERS, h)


if __name__ == "__main__":
    unittest.main()
