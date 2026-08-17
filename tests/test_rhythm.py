"""Юнит-тесты на склейку карточек-двойников в отчёте ритма (без сети).

Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_rhythm import (
    ACTIVE_DAYS,
    LOST_DAYS,
    _key_tokens,
    _same_client,
    checklist_line,
    compute,
    merge_cards,
    plural,
    task_name,
)


class TestSameClient(unittest.TestCase):
    def same(self, a, b):
        return _same_client(_key_tokens(a), _key_tokens(b))

    def test_transfer_tail_ignored(self):
        """Переезд между базами: та же карточка с пометкой о переводе."""
        self.assertTrue(self.same("ПУШКИН (ООО МОНЕ) с 10.08.26 на ПЕРФИЛЬЕВ",
                                  "ПУШКИН (ООО МОНЕ)"))
        self.assertTrue(self.same("La Virgen ЛА ВИРГЕН (ИП Погонина Д.А.) с 10.08.26 на ПЕРФИЛЬЕВ",
                                  "La Virgen ЛА ВИРГЕН (ИП Погонина Д.А.)"))

    def test_service_marks_ignored(self):
        """Пометки «нал», «dsbx», «ЭДО», форма собственности — не различают клиента."""
        self.assertTrue(self.same("Ильфорно Неглинная ( МЕТАЛЛ ТРЕЙДИНГ) нал",
                                  "Ильфорно Неглинная (ООО МЕТАЛЛ ТРЕЙДИНГ) dsbx"))

    def test_yo_and_hyphen(self):
        self.assertTrue(self.same("СЕВЕРЯНЕ (ООО ВАСИЛЁК)", "СЕВЕРЯНЕ (ООО ВАСИЛЕК)"))
        self.assertTrue(self.same("БУТИК-БАР ДЖАННЕТ (ООО ВИНОТЕКА)",
                                  "БУТИК БАР ДЖАННЕТ (ООО ВИНОТЕКА)"))

    def test_different_legal_entities_stay_apart(self):
        """Одно название, разные юрлица — разные точки, ритм у каждой свой."""
        self.assertFalse(self.same("СТЕЙК ИТ ИЗИ (ООО ОЛИМП)",
                                   "СТЕЙК ИТ ИЗИ (ООО МОНТОНИКО)"))

    def test_network_points_stay_apart(self):
        """★Грабли: точка сети — это лишнее слово, а не уточнение той же карточки."""
        self.assertFalse(self.same("ШЕСТНАДЦАТЬ ТОНН КЕЙТЕРИНГ ООО счет",
                                   "ШЕСТНАДЦАТЬ ТОНН ПРЕСНЯ (ООО 16 ТОНН ПРЕСНЯ) счет"))
        self.assertFalse(self.same("Фреш кафе Сити", "Фреш кафе Оружейная"))

    def test_generic_words_alone_never_match(self):
        """★Грабли: «ФУД КАФЕ» липло к «ФИНЧ КАФЕ» по родовым словам."""
        self.assertFalse(self.same("ФУД КАФЕ ООО",
                                   "ФУД СОЛЮШНС ООО (ФИНЧ КАФЕ ФУДСОЛЮШН) dsbx"))
        self.assertFalse(self.same("КАФЕ ООО", "БАР ООО"))


class TestMergeCards(unittest.TestCase):
    def test_orders_join_under_fresh_card(self):
        """Заказы обеих карточек считаем вместе, имя берём у актуальной."""
        old = "ТЕРРИН (ООО ГАСТРОКЛУБ) с 10.08.26 на ПЕРФИЛЬЕВ"
        new = "ТЕРРИН (ООО ГАСТРОКЛУБ)"
        orders = {old: [(date(2026, 8, 5), 1000.0), (date(2026, 8, 7), 2000.0)],
                  new: [(date(2026, 8, 12), 3000.0), (date(2026, 8, 17), 4000.0)]}
        base_of = {old: "Губарев", new: "Перфильев"}
        merged, bases, cards = merge_cards(orders, base_of)

        self.assertEqual(list(merged), [new])
        self.assertEqual(len(merged[new]), 4)
        self.assertEqual(bases[new], "Перфильев (был Губарев)")
        self.assertEqual(cards[new], sorted([old, new]))

    def test_no_false_merge_keeps_both(self):
        a, b = "СТЕЙК ИТ ИЗИ (ООО ОЛИМП)", "СТЕЙК ИТ ИЗИ (ООО МОНТОНИКО)"
        orders = {a: [(date(2026, 8, 1), 100.0)], b: [(date(2026, 8, 4), 200.0)]}
        merged, bases, cards = merge_cards(orders, {a: "Губарев", b: "Губарев"})
        self.assertEqual(sorted(merged), sorted([a, b]))
        self.assertEqual(cards, {})

    def test_merged_client_is_not_overdue(self):
        """Главный смысл фикса: переехавший клиент перестаёт быть «просроченным»."""
        today = date(2026, 8, 17)
        old = "ПУШКИН (ООО МОНЕ) с 10.08.26 на ПЕРФИЛЬЕВ"
        new = "ПУШКИН (ООО МОНЕ)"
        # старая карточка: ровный ритм через день, оборвалась 09.08
        orders = {old: [(date(2026, 8, d), 1000.0) for d in (1, 3, 5, 7, 9)],
                  new: [(date(2026, 8, d), 1000.0) for d in (11, 13, 15, 17)]}
        base_of = {old: "Губарев", new: "Перфильев"}

        before = compute(orders, base_of, today)
        self.assertEqual({r["client"]: r["status"] for r in before}[old], "ПРОСРОЧЕНО")

        merged, bases, _ = merge_cards(orders, base_of)
        after = compute(merged, bases, today)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["client"], new)
        self.assertEqual(after[0]["status"], "рано")
        self.assertEqual(after[0]["orders"], 9)


class TestLostClients(unittest.TestCase):
    """★17.08: раньше клиент, переставший заказывать, просто исчезал из отчёта."""

    def rows_for(self, last_order, ritm_days=7, today=date(2026, 8, 17)):
        days = [last_order - timedelta(days=ritm_days * i) for i in range(6)]
        orders = {"КРАБЫ КУТАБЫ (ООО АРАБИКА)": [(d, 5000.0) for d in days]}
        return compute(orders, {"КРАБЫ КУТАБЫ (ООО АРАБИКА)": "Губарев"}, today)

    def test_silent_client_stays_in_report(self):
        rows = self.rows_for(date(2026, 7, 17))       # молчит 31 день
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ОТВАЛИВАЕТСЯ")
        self.assertEqual(rows[0]["silent"], 31)

    def test_gone_too_long_drops_out(self):
        rows = self.rows_for(date(2026, 8, 17) - timedelta(days=ACTIVE_DAYS + 1))
        self.assertEqual(rows, [])

    def test_active_client_not_marked_lost(self):
        rows = self.rows_for(date(2026, 8, 16))
        self.assertNotEqual(rows[0]["status"], "ОТВАЛИВАЕТСЯ")

    def test_history_window_follows_last_order(self):
        """У молчащего клиента ритм считается по ЕГО последним 8 неделям, а не по
        восьми неделям до сегодня — иначе заказов в окне не остаётся."""
        rows = self.rows_for(date(2026, 7, 20), ritm_days=7)
        self.assertEqual(rows[0]["orders"], 6)
        # клиент берёт раз в неделю по понедельникам: его «рабочий день» наступает
        # раз в неделю, поэтому ритм в рабочих днях = 1, а в календарных — 7
        self.assertEqual(rows[0]["median_gap"], 1)
        self.assertEqual(rows[0]["median_gap_days"], 7)

    def test_lost_line_shows_calendar_days(self):
        r = self.rows_for(date(2026, 7, 17))[0]
        line = checklist_line(r)
        self.assertIn("УХОДИТ", line)
        self.assertIn("молчит 31 дн.", line)
        self.assertIn("17.07", line)

    def test_boundary_exactly_lost_days(self):
        rows = self.rows_for(date(2026, 8, 17) - timedelta(days=LOST_DAYS))
        self.assertEqual(rows[0]["status"], "ОТВАЛИВАЕТСЯ")


class TestTaskTexts(unittest.TestCase):
    def test_transfer_mark_hidden_from_manager(self):
        """Служебная пометка 1С в чек-листе менеджеру не нужна, юр. лицо остаётся."""
        self.assertEqual(task_name("Under Dog (ООО АНДЕР ДОГ) с 10.08.26 на ПЕРФИЛЬЕВ"),
                         "Under Dog (ООО АНДЕР ДОГ)")
        self.assertEqual(task_name("ПУШКИН  (ООО МОНЕ)"), "ПУШКИН (ООО МОНЕ)")

    def test_plural(self):
        self.assertEqual(plural(21, "день", "дня", "дней"), "день")
        self.assertEqual(plural(22, "день", "дня", "дней"), "дня")
        self.assertEqual(plural(25, "день", "дня", "дней"), "дней")
        self.assertEqual(plural(11, "день", "дня", "дней"), "дней")


if __name__ == "__main__":
    unittest.main()
