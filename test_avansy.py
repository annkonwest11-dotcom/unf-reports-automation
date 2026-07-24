"""Тесты логики sync_avansy — без сети (fetch подменяется фейковыми операциями)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync_avansy as sa


def _tx(name, amount, dateIso, desc, ttype=2):
    return {"type": ttype, "amount": amount, "dateIso": dateIso,
            "description": desc, "contractor": {"name": name}}


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


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
        self._orig_get = sa.requests.get

    def tearDown(self):
        sa.requests.get = self._orig_get

    def _install(self, txs):
        sa.requests.get = lambda *a, **k: FakeResp({"success": True, "transactions": txs})

    def test_avans_picks_first_half_only(self):
        self._install([
            _tx("Вольнова Дарья Павловна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Наныкина Ксения Сергеевна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Черкашина Алена Анатольевна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Герасимчук Владислава Павловна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            # шум: вторая половина, больничный, чужой сотрудник, прошлый месяц
            _tx("Вольнова Дарья Павловна", "9999", "2026-07-09", "Заработная плата за вторую половину месяца"),
            _tx("Вольнова Дарья Павловна", "500", "2026-07-24", "Выплата больничного листа"),
            _tx("Вдовина Ирина Александровна", "12253.78", "2026-07-24", "Заработная плата за первую половину месяца"),
            _tx("Вольнова Дарья Павловна", "111", "2026-06-24", "Заработная плата за первую половину месяца"),
        ])
        rep = sa.sync_avansy("avans", today=__import__("datetime").datetime(2026, 7, 24), apply=False)
        self.assertEqual(rep["col"], "C")
        self.assertEqual(len(rep["items"]), 4)
        cells = {it["cell"]: it["amount"] for it in rep["items"]}
        self.assertEqual(cells, {"C127": 12253.78, "C128": 12253.78,
                                 "C130": 12253.78, "C132": 12253.78})
        self.assertEqual(rep["missing"], [])

    def test_zp_uses_second_half_and_col_E(self):
        self._install([
            _tx("Вольнова Дарья Павловна", "14640.57", "2026-08-10", "Заработная плата за вторую половину месяца"),
            _tx("Черкашина Алена Анатольевна", "14640.57", "2026-08-08", "Заработная плата за вторую половину месяца"),
        ])
        rep = sa.sync_avansy("zp", today=__import__("datetime").datetime(2026, 8, 10), apply=False)
        self.assertEqual(rep["col"], "E")
        cells = {it["cell"]: it["amount"] for it in rep["items"]}
        self.assertEqual(cells, {"E127": 14640.57, "E130": 14640.57})
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
        self.assertEqual(it["amount"], 12253.78)
        self.assertEqual(it["count"], 2)
        self.assertEqual(it["date"], "25.07")  # дата последней операции

    def test_bad_kind_raises(self):
        with self.assertRaises(ValueError):
            sa.fetch_payouts("nonsense")


if __name__ == "__main__":
    unittest.main()
