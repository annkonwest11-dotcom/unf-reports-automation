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

    BASE = ["Ресторан", "Юр лицо", "База 1С", "Создан", "Классифицкация",
            "до какого числа", "Дарья", "Алена", "Ксения", "Лилия", "София",
            "Виолетта", "Анна", "ИТОГ"]

    def test_klass_column_follows_header(self):
        """★12.10.2026: с колонкой «База 1С» классификация уехала с D (3) на E (4)."""
        from sync_novye import klass_column
        self.assertEqual(klass_column(self.SEPT), 3)
        self.assertEqual(klass_column(self.BASE), 4)
        self.assertEqual(klass_column(["Ресторан", "Юр лицо"]), 3)   # нет колонки — старое место

    def test_base_column_is_not_a_manager(self):
        from sync_novye import KPI_MANAGERS, kpi_key
        self.assertNotIn(kpi_key("База 1С"), KPI_MANAGERS)

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
