"""Тесты логики sync_avansy — без сети (источник операций подменяется фейковым).

Операции приходят из kassa_api.month_operations уже в форме ADesk
(type/amount/dateIso/description/contractor.name), её и подменяем.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync_avansy as sa


def _tx(name, amount, dateIso, desc, ttype=2):
    return {"type": ttype, "amount": amount, "dateIso": dateIso,
            "description": desc, "contractor": {"name": name}}


class TestKindDetection(unittest.TestCase):
    def test_pervaya_polovina_is_avans(self):
        self.assertEqual(sa._kind_of("Заработная плата за первую половину месяца НДС не облагается"), "avans")

    def test_vtoraya_polovina_is_zp(self):
        self.assertEqual(sa._kind_of("ПП №215 Заработная плата за вторую половину месяца"), "zp")

    def test_bolnichny_is_none(self):
        self.assertIsNone(sa._kind_of("Выплата больничного листа НДС не облагается"))

    def test_empty_is_none(self):
        self.assertIsNone(sa._kind_of(""))
        self.assertIsNone(sa._kind_of(None))


class TestSurnameMatch(unittest.TestCase):
    def test_matches_official(self):
        self.assertEqual(sa._match_surname("Вольнова Дарья Павловна"), "Вольнова")
        self.assertEqual(sa._match_surname("Наныкина Ксения Сергеевна"), "Наныкина")
        self.assertEqual(sa._match_surname("Черкашина Алена Анатольевна"), "Черкашина")
        self.assertEqual(sa._match_surname("Герасимчук Владислава Павловна"), "Герасимчук")

    def test_ignores_other_office_staff(self):
        # чужие сотрудники в тот же день с той же категорией — не наши
        for other in ["Вдовина Ирина Александровна", "Коваль Марина Александровна",
                      "Боднарь Мирослава Альбиновна", "Яковлева Татьяна Геннадьевна"]:
            self.assertIsNone(sa._match_surname(other))


class TestFetchAndSync(unittest.TestCase):
    def setUp(self):
        self._orig_ops = sa.kassa_api.month_operations

    def tearDown(self):
        sa.kassa_api.month_operations = self._orig_ops

    def _install(self, txs):
        sa.kassa_api.month_operations = lambda ym, token=None: txs

    def test_avans_picks_first_half_only(self):
        self._install([
            _tx("Вольнова Дарья Павловна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Наныкина Ксения Сергеевна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Черкашина Алена Анатольевна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Герасимчук Владислава Павловна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Сулименко Лилия", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            # шум: вторая половина, больничный, чужой сотрудник, прошлый месяц
            _tx("Вольнова Дарья Павловна", "9999", "2026-07-09", "Заработная плата за вторую половину месяца"),
            _tx("Вольнова Дарья Павловна", "500", "2026-07-24", "Выплата больничного листа"),
            _tx("Вдовина Ирина Александровна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Вольнова Дарья Павловна", "111", "2026-06-24", "Заработная плата за первую половину месяца"),
        ])
        rep = sa.sync_avansy("avans", today=__import__("datetime").datetime(2026, 7, 24),
                             apply=False, ws=FakeWS())
        self.assertEqual(rep["col"], "C")
        # строки берутся из ведомости по ФИО: Дарья 141, Ксения 142, Алёна 145, Влада 146
        cells = {it["cell"]: it["amount"] for it in rep["items"]}
        self.assertEqual(cells, {"C141": 12253, "C142": 12253,
                                 "C145": 12253, "C146": 12253})
        # стажёрам официальную ЗП ещё не платят — они честно попадают в «не выплачено»
        self.assertEqual(rep["missing"], ["София Хакимова", "Виолетта Караханова"])
        # Лилия уволена: выплата в кассе есть, а строки в ведомости нет — не пишем
        self.assertEqual(rep["gone"], ["Лилия Сулименко"])

    def test_zp_uses_second_half_and_col_E(self):
        self._install([
            _tx("Вольнова Дарья Павловна", "14640.57", "2026-08-10", "Заработная плата за вторую половину месяца"),
            _tx("Черкашина Алена Анатольевна", "14640.57", "2026-08-08", "Заработная плата за вторую половину месяца"),
        ])
        rep = sa.sync_avansy("zp", today=__import__("datetime").datetime(2026, 8, 10),
                             apply=False, ws=FakeWS())
        self.assertEqual(rep["col"], "E")
        cells = {it["cell"]: it["amount"] for it in rep["items"]}
        self.assertEqual(cells, {"E141": 14640, "E145": 14640})
        # Ксения и Владислава не выплачены → в missing
        self.assertIn("Ксения Наныкина", rep["missing"])
        self.assertIn("Владислава Герасимчук", rep["missing"])

    def test_multiple_ops_summed(self):
        self._install([
            _tx("Черкашина Алена Анатольевна", "10000", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Черкашина Алена Анатольевна", "2253.78", "2026-07-25", "Доплата за первую половину месяца"),
        ])
        rep = sa.sync_avansy("avans", today=__import__("datetime").datetime(2026, 7, 25), apply=False)
        it = [x for x in rep["items"] if x["name"] == "Алёна Черкашина"][0]
        self.assertEqual(it["amount"], 12253)
        self.assertEqual(it["count"], 2)
        self.assertEqual(it["date"], "25.07")  # дата последней операции

    def test_bad_kind_raises(self):
        with self.assertRaises(ValueError):
            sa.fetch_payouts("nonsense")


class FakeWS:
    """Мок листа: current — {cell: значение}; фиксирует записи в self.written.

    Колонка A повторяет ведомость: после удаления Лилии строки сотрудников
    уехали на 141-147 — ровно тот случай, из-за которого номера строк больше не
    хранятся в коде, а ищутся по ФИО.
    """

    LEDGER = {139: "ТАБЛИЦА ВЫПЛАТ ЗА МЕСЯЦ", 140: "Сотрудник",
              141: "Дарья Вольнова", 142: "Ксения Наныкина",
              143: "София Хакимова", 144: "Виолетта Караханова",
              145: "Алена Черкашина", 146: "Владислава Герасимчук",
              147: "Анна Кононенко (РОП)", 148: "ИТОГО"}

    def __init__(self, current=None, ledger=None):
        self._current = current or {}
        self._ledger = ledger if ledger is not None else self.LEDGER
        self.written = []

    def get(self, rng, value_render_option=None):
        last = max(self._ledger) if self._ledger else 0
        return [[self._ledger.get(i, "")] for i in range(1, last + 1)]

    def batch_get(self, ranges, value_render_option=None):
        out = []
        for r in ranges:
            v = self._current.get(r)
            out.append([[v]] if v is not None else [[]])
        return out

    def batch_update(self, updates, value_input_option=None):
        for u in updates:
            self.written.append((u["range"], u["values"][0][0]))


class TestOnlyChanged(unittest.TestCase):
    def setUp(self):
        self._orig_ops = sa.kassa_api.month_operations

    def tearDown(self):
        sa.kassa_api.month_operations = self._orig_ops

    def _install(self, txs):
        sa.kassa_api.month_operations = lambda ym, token=None: txs

    def test_skips_already_written_writes_only_new(self):
        import datetime as _dt
        self._install([
            _tx("Вольнова Дарья Павловна", "12253.78", "2026-07-24", "первую половину месяца"),
            _tx("Наныкина Ксения Сергеевна", "12253.78", "2026-07-24", "первую половину месяца"),
        ])
        # Дарья уже стоит в C141 той же суммой → не меняется; Ксения C142 пусто → новая
        ws = FakeWS(current={"C141": 12253, "C142": None, "C145": None, "C146": None})
        rep = sa.sync_avansy("avans", today=_dt.datetime(2026, 7, 24),
                             apply=True, only_changed=True, ws=ws)
        changed_cells = {it["cell"] for it in rep["changed"]}
        self.assertEqual(changed_cells, {"C142"})           # только Ксения
        self.assertEqual(ws.written, [("C142", 12253)])  # записана только она

    def test_changed_when_amount_differs(self):
        import datetime as _dt
        self._install([
            _tx("Вольнова Дарья Павловна", "13000", "2026-07-25", "первую половину месяца"),
        ])
        ws = FakeWS(current={"C141": 12253, "C142": None, "C145": None, "C146": None})
        rep = sa.sync_avansy("avans", today=_dt.datetime(2026, 7, 25),
                             apply=True, only_changed=True, ws=ws)
        self.assertEqual([it["cell"] for it in rep["changed"]], ["C141"])
        self.assertEqual(ws.written, [("C141", 13000.0)])


if __name__ == "__main__":
    unittest.main()


class TestPaymentRows(unittest.TestCase):
    """Строки ведомости ищутся по ФИО — номера уезжают при каждом увольнении."""

    def test_nahodit_po_fio(self):
        rows = sa.payment_rows(FakeWS())
        self.assertEqual(rows["Вольнова"], 141)
        self.assertEqual(rows["Черкашина"], 145)      # «Алена» без ё — тоже она
        self.assertNotIn("Сулименко", rows)           # уволена, строки нет

    def test_sdvig_vedomosti_ne_lomaet(self):
        # ведомость уехала вверх (удалили ещё и помощника) — ищем всё равно верно
        ledger = {100: "ТАБЛИЦА ВЫПЛАТ ЗА МЕСЯЦ", 101: "Сотрудник",
                  102: "Дарья Вольнова", 103: "Алена Черкашина", 104: "ИТОГО"}
        rows = sa.payment_rows(FakeWS(ledger=ledger))
        self.assertEqual(rows, {"Вольнова": 102, "Черкашина": 103})

    def test_itogo_ostanavlivaet_poisk(self):
        # ниже строки ИТОГО бывают тёзки в примечаниях — туда не заглядываем
        ledger = {10: "ТАБЛИЦА ВЫПЛАТ ЗА МЕСЯЦ", 11: "Сотрудник",
                  12: "Дарья Вольнова", 13: "ИТОГО", 14: "Ксения Наныкина"}
        rows = sa.payment_rows(FakeWS(ledger=ledger))
        self.assertEqual(rows, {"Вольнова": 12})

    def test_bez_vedomosti_pusto(self):
        rows = sa.payment_rows(FakeWS(ledger={1: "СВОДНАЯ", 2: "Смены"}))
        self.assertEqual(rows, {})
