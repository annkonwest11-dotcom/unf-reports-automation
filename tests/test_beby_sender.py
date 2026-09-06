"""Кто может присылать боту накладные по беби-листам (решение Анны 06.09.2026).

Накладные кидает Влада — и только в личку; сводку с прибылью и кнопку
«Закрыть период» бот отдаёт одной Анне.

Запуск:  python -m unittest discover -s tests -v
"""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:                       # без .env и credentials.json бот не импортируется
    import bot
    _skip = ""
except Exception as e:     # noqa: BLE001 — причина уходит в текст пропуска
    bot, _skip = None, f"bot.py не импортируется: {e}"

ANNA = 796207056
VLADA = 6630193697
DARYA = 7813380767         # Вольнова Дарья — накладные ей не разрешены


def _update(user_id, chat_type="private", doc=True):
    message = SimpleNamespace(
        document=SimpleNamespace(
            file_name="Товарная накладная №372.pdf",
            mime_type="application/pdf",
            file_unique_id="abc",
            get_file=AsyncMock(return_value=SimpleNamespace(
                download_to_drive=AsyncMock())),
        ) if doc else None,
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=-1003410516555 if chat_type != "private" else user_id,
                                       type=chat_type),
        effective_user=SimpleNamespace(id=user_id, full_name="Кто-то"),
        message=message,
    )


@unittest.skipIf(bot is None, _skip)
class TestSenderName(unittest.TestCase):
    def name(self, user_id):
        return bot._beby_sender_name(SimpleNamespace(id=user_id, full_name="Кто-то"))

    def test_anna(self):
        self.assertEqual(self.name(ANNA), "Анна")

    def test_vlada(self):
        self.assertEqual(self.name(VLADA), "Владислава Герасимчук")

    def test_postoronniy(self):
        self.assertIsNone(self.name(DARYA))

    def test_no_user(self):
        self.assertIsNone(bot._beby_sender_name(None))


@unittest.skipIf(bot is None, _skip)
class TestInvoiceHandler(unittest.TestCase):
    def run_handler(self, update):
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(bot.beby_report, "process_invoice",
                          MagicMock(return_value=(
                              "📄 Накладная №372 от 17.08.2026\nВнесена в «август»: 7 позиций",
                              "Текущий период — 📊 11.08–18.08\nприбыль 30 101 ₽ (24,1%)",
                              ("август", bot.datetime(2026, 8, 11).date(),
                               bot.datetime(2026, 8, 18).date())))) as proc:
            asyncio.run(bot.handle_beby_invoice(update, context))
        return proc, context

    def test_vlada_private(self):
        upd = _update(VLADA)
        proc, ctx = self.run_handler(upd)
        proc.assert_called_once()
        # Владе — только её накладная, без прибыли и без кнопки
        answer = upd.message.reply_text.await_args_list[-1]
        self.assertIn("Накладная №372", answer.args[0])
        self.assertNotIn("прибыль", answer.args[0])
        self.assertIsNone(answer.kwargs.get("reply_markup"))
        # Анне — то же плюс сводка и кнопка «Закрыть период»
        to_anna = ctx.bot.send_message.await_args
        self.assertEqual(to_anna.kwargs["chat_id"], ANNA)
        self.assertIn("Накладную прислала Владислава Герасимчук", to_anna.kwargs["text"])
        self.assertIn("прибыль", to_anna.kwargs["text"])
        self.assertIn("beby:close:август",
                      to_anna.kwargs["reply_markup"].inline_keyboard[0][0].callback_data)

    def test_anna_private(self):
        upd = _update(ANNA)
        proc, ctx = self.run_handler(upd)
        proc.assert_called_once()
        answer = upd.message.reply_text.await_args_list[-1]
        self.assertIn("прибыль", answer.args[0])
        self.assertIsNotNone(answer.kwargs.get("reply_markup"))
        ctx.bot.send_message.assert_not_awaited()      # себе дубль не шлём

    def test_postoronniy_molcha(self):
        upd = _update(DARYA)
        proc, ctx = self.run_handler(upd)
        proc.assert_not_called()
        upd.message.reply_text.assert_not_awaited()
        ctx.bot.send_message.assert_not_awaited()

    def test_v_gruppe_ne_razbiraem(self):
        upd = _update(VLADA, chat_type="supergroup")
        proc, ctx = self.run_handler(upd)
        proc.assert_not_called()
        self.assertIn("в личку", upd.message.reply_text.await_args.args[0])


@unittest.skipIf(bot is None, _skip)
class TestCloseButton(unittest.TestCase):
    def press(self, user_id):
        query = SimpleNamespace(
            data="beby:close:август:2026-08-11:2026-08-18",
            from_user=SimpleNamespace(id=user_id),
            answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query)
        with patch.object(bot.beby_report, "close_period",
                          MagicMock(return_value=("11-18 августа", [], [0, 0, 0, 0], True))) as close:
            asyncio.run(bot._beby_callback(update, SimpleNamespace(bot_data={})))
        return query, close

    def test_vlada_ne_zakryvaet(self):
        query, close = self.press(VLADA)
        close.assert_not_called()
        self.assertIn("Анна", query.answer.await_args.args[0])

    def test_anna_zakryvaet(self):
        _query, close = self.press(ANNA)
        close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
