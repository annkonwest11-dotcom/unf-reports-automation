"""Матчинг клиентов в беби-синке (карточка 1С ↔ строка справочника).

Запуск:  venv/bin/python -m pytest tests/test_beby_sync.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_odata import build_token_index
from sync_beby import canon, to_client


class TestToClient(unittest.TestCase):
    def setUp(self):
        self.clients = {
            "спорткорт ооо эдо": "СПОРТКОРТ ООО ЭДО",
            "гастроном времена ооо": "Гастроном Времена ООО",
            "руми (ооо ресто групп 57) dsbx": "РУМИ (ООО РЕСТО ГРУПП 57) dsbx",
        }
        self.index = build_token_index(self.clients)

    def match(self, name_1c):
        return to_client(canon(name_1c), self.clients, self.index)

    def test_exact_name_wins(self):
        self.assertEqual(self.match("Гастроном Времена ООО"), "гастроном времена ооо")

    def test_tail_in_1c_still_finds_row(self):
        """★08.09: карточка с хвостом «адрес дост менять» — та же точка (Медуза
        Лужники). Раньше выпадала молча, беби-оборот 26 000 в лист не попадал."""
        self.assertEqual(self.match("СПОРТКОРТ ООО ЭДО адрес дост менять"),
                         "спорткорт ооо эдо")

    def test_stranger_does_not_stick(self):
        self.assertIsNone(self.match("КОФЕЙНЯ У ПРУДА ООО"))


if __name__ == "__main__":
    unittest.main()
