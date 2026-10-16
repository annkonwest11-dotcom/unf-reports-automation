"""Индивидуальные условия Виолетты (файл Анны от 15.10.2026) — чистая логика.

Проверяем ровно то, что написано в условиях: ступени по обороту, 30% за одну
выполненную норму, нормы по звонкам и по дегустациям с пропорцией за неполную
неделю.

Запуск:  python -m unittest discover -s tests -v
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import individual_kpi
from individual_kpi import (bonus_step, calls_norm, individual_bonus,
                            tastings_norm, week_key)

D = datetime.date


class TestCallsNorm(unittest.TestCase):
    def test_srednee_i_minimum_v_norme(self):
        avg, low, ok = calls_norm({1: 30, 2: 32, 3: 28})
        self.assertAlmostEqual(avg, 30.0)
        self.assertEqual(low, 28)
        self.assertTrue(ok)

    def test_odna_smena_nizhe_25_lomaet_normu(self):
        # «и ни одной смены ниже 25» — даже при хорошем среднем
        avg, low, ok = calls_norm({1: 40, 2: 40, 3: 24})
        self.assertGreater(avg, 30)
        self.assertEqual(low, 24)
        self.assertFalse(ok)

    def test_srednee_nizhe_30_lomaet_normu(self):
        _, _, ok = calls_norm({1: 29, 2: 29, 3: 29})
        self.assertFalse(ok)

    def test_pustoy_zhurnal_norma_ne_vypolnena(self):
        # подтвердить нечем — считаем, что норма не взята
        avg, low, ok = calls_norm({})
        self.assertEqual((avg, low, ok), (0.0, 0, False))


class TestTastingsNorm(unittest.TestCase):
    def test_polnaya_nedelya_shest_kachestvennyh(self):
        shifts = [D(2026, 10, 5), D(2026, 10, 6), D(2026, 10, 7),
                  D(2026, 10, 8), D(2026, 10, 9)]
        quality = [D(2026, 10, 5)] * 3 + [D(2026, 10, 8)] * 3
        weeks, ok = tastings_norm(quality, shifts)
        self.assertTrue(ok)
        self.assertEqual(weeks[D(2026, 10, 5)]["need"], 6)

    def test_nepolnaya_nedelya_proporcionalno_smenam(self):
        # 3 смены из 5 → норма 6×3/5 = 3,6, значит нужно 4 дегустации
        shifts = [D(2026, 10, 5), D(2026, 10, 6), D(2026, 10, 7)]
        weeks, ok = tastings_norm([D(2026, 10, 5)] * 3, shifts)
        self.assertAlmostEqual(weeks[D(2026, 10, 5)]["need"], 3.6)
        self.assertFalse(ok)
        weeks, ok = tastings_norm([D(2026, 10, 5)] * 4, shifts)
        self.assertTrue(ok)

    def test_nedelya_bez_smen_ne_uchityvaetsya(self):
        # отпуск или ещё не работала — такая неделя норму не рушит
        shifts = [D(2026, 10, 12), D(2026, 10, 13), D(2026, 10, 14),
                  D(2026, 10, 15), D(2026, 10, 16)]
        weeks, ok = tastings_norm([D(2026, 10, 12)] * 6, shifts)
        self.assertEqual(list(weeks), [D(2026, 10, 12)])
        self.assertTrue(ok)

    def test_provalena_odna_nedelya_iz_dvuh(self):
        shifts = ([D(2026, 10, 5), D(2026, 10, 6), D(2026, 10, 7), D(2026, 10, 8),
                   D(2026, 10, 9)] +
                  [D(2026, 10, 12), D(2026, 10, 13), D(2026, 10, 14),
                   D(2026, 10, 15), D(2026, 10, 16)])
        quality = [D(2026, 10, 5)] * 6 + [D(2026, 10, 12)] * 5
        weeks, ok = tastings_norm(quality, shifts)
        self.assertFalse(ok)
        self.assertTrue(weeks[D(2026, 10, 5)]["ok"])
        self.assertFalse(weeks[D(2026, 10, 12)]["ok"])

    def test_week_key_ponedelnik(self):
        self.assertEqual(week_key(D(2026, 10, 15)), D(2026, 10, 12))  # чт → пн
        self.assertEqual(week_key(D(2026, 10, 12)), D(2026, 10, 12))


class TestBonusSteps(unittest.TestCase):
    def test_stupeni_po_oborotu(self):
        self.assertEqual(bonus_step(174_999)[1], 0)         # до 175 000 — ноль
        self.assertEqual(bonus_step(175_000)[1], 30_000)    # 70% плана
        self.assertEqual(bonus_step(212_500)[1], 45_000)    # 85%
        self.assertEqual(bonus_step(250_000)[1], 60_000)    # 100%
        self.assertEqual(bonus_step(400_000)[1], 60_000)    # выше — та же ступень

    def test_vse_normy_polnaya_summa(self):
        r = individual_bonus(212_500, calls_ok=True, tastings_ok=True)
        self.assertEqual(r["amount"], 45_000)
        self.assertEqual(r["part"], 1.0)

    def test_odna_norma_tridcat_procentov(self):
        # «если выполнены только звонки или только дегустации — 30% ступени»
        self.assertEqual(individual_bonus(175_000, True, False)["amount"], 9_000)
        self.assertEqual(individual_bonus(175_000, False, True)["amount"], 9_000)
        self.assertEqual(individual_bonus(212_500, True, False)["amount"], 13_500)
        self.assertEqual(individual_bonus(250_000, False, True)["amount"], 18_000)

    def test_ni_odnoy_normy_nol(self):
        self.assertEqual(individual_bonus(250_000, False, False)["amount"], 0)

    def test_oborot_nizhe_poroga_normy_ne_spasayut(self):
        # «при обороте менее 175 000 индивидуальный бонус не начисляется»
        r = individual_bonus(174_000, calls_ok=True, tastings_ok=True)
        self.assertEqual(r["amount"], 0)
        self.assertEqual(r["step_base"], 0)


if __name__ == "__main__":
    unittest.main()


class TestSummaryCells(unittest.TestCase):
    """Что именно уезжает в СВОДНУЮ — без сети."""

    def _res(self, **kw):
        base = {"employee": "Виолетта Караханова", "month": "Октябрь 2026",
                "calls_avg": 31.4, "calls_min": 27, "calls": {1: 30, 2: 33},
                "calls_ok": True, "tastings_quality": 23, "tastings_all": 29,
                "tastings_ok": False, "amount": 9000,
                "weeks": {datetime.date(2026, 9, 28): {"done": 6},
                          datetime.date(2026, 10, 5): {"done": 5}}}
        base.update(kw)
        return base

    def test_zvonki_stroka(self):
        c = individual_kpi.summary_cells(self._res())
        self.assertEqual(c[individual_kpi.ROW_CALLS],
                         "31.4 в среднем, минимум 27 (смен с отчётом 2) — ✅ выполнено")

    def test_degustacii_po_nedelyam(self):
        c = individual_kpi.summary_cells(self._res())
        self.assertEqual(c[individual_kpi.ROW_TASTINGS],
                         "по неделям 6 / 5 (качественных 23 из 29) — ❌ не выполнено")

    def test_bonus_chislom(self):
        c = individual_kpi.summary_cells(self._res(amount=45000))
        self.assertEqual(c[individual_kpi.ROW_BONUS], 45000)

    def test_bez_smen_ne_padaet(self):
        c = individual_kpi.summary_cells(self._res(weeks={}, calls={}, calls_avg=0.0,
                                                   calls_min=0, calls_ok=False, amount=0))
        self.assertIn("нет смен", c[individual_kpi.ROW_TASTINGS])
        self.assertIn("❌", c[individual_kpi.ROW_CALLS])
