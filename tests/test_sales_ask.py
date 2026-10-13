"""Вопросы Анне в MAX и её ответы кнопками (sales_ask + sales_report.apply_answers).

Правило 6 ТЗ: спрашиваем в MAX в личку. Кнопки — типа «message», поэтому нажатие
приходит обычным сообщением, и его разбирает следующий прогон. Сети здесь нет.
"""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sales_ask as sa
import sales_report as sr


def calc(**kw):
    base = dict(client="РУБЕЛЬ (ООО АВА ЦЕНТР)", kind="новый", source="1С",
                event=date(2026, 10, 2), window_end=date(2026, 10, 31),
                amount=5_472.0, gap=None, rhythm=None, orders=2, beby_cut=0.0)
    base.update(kw)
    return base


ANNA = 229336226
BOT = 396784514


def msg(text, ts=1, sender=ANNA, is_bot=False):
    return {"timestamp": ts, "body": {"mid": f"m{ts}", "text": text},
            "sender": {"user_id": sender, "is_bot": is_bot}}


class TestQuestion(unittest.TestCase):
    def test_new_client_question(self):
        text, options = sa.question_text(calc())
        self.assertIn("РУБЕЛЬ (ООО АВА ЦЕНТР)", text)
        self.assertIn("первый заказ по 1С, бланка нет: 02.10, 5 472 ₽", text)
        self.assertIn("окно считаю по 31.10", text)
        self.assertEqual(options, ["вношу · РУБЕЛЬ (ООО АВА ЦЕНТР)",
                                   "не вношу · РУБЕЛЬ (ООО АВА ЦЕНТР)",
                                   "разовый · РУБЕЛЬ (ООО АВА ЦЕНТР)"])

    def test_return_candidate_shows_silence_and_rhythm(self):
        """По возврату главное — сколько молчал против своего ритма (правило 9)."""
        text, _ = sa.question_text(calc(kind="кандидат", gap=59, rhythm=16.5))
        self.assertIn("похож на возврат, бланка нет", text)
        self.assertIn("молчал 59 дн. при обычном ритме 16.5 дн.", text)

    def test_beby_cut_is_mentioned(self):
        """Сумма уже с вычетом за салаты — иначе Анна сверит её с 1С и не сойдётся."""
        text, _ = sa.question_text(calc(beby_cut=13_800.0))
        self.assertIn("вычтено 40% за салаты (13 800 ₽)", text)

    def test_long_name_fits_the_button(self):
        """MAX режет кнопку на 64 символах — имя обрезаем сами, с запасом на вердикт."""
        _, options = sa.question_text(calc(client="А" * 80))
        self.assertTrue(all(len(o) <= 64 for o in options))


class TestFalsePresses(unittest.TestCase):
    """★13.10.2026: разделитель « · » стоит и в обычных отчётах бота.

    По первой версии парсера в личке насчиталось 33 «ответа» — все от самого бота,
    и любой мог молча исключить клиента из отчёта. Проверяем на том, что реально
    лежит в переписке.
    """

    def setUp(self):
        self.p = mock.patch.object(sa, "_anna_user_id", lambda: ANNA)
        self.p.start()
        self.known = {sa._flat("Долма")}

    def tearDown(self):
        self.p.stop()

    def test_bot_report_is_not_an_answer(self):
        отчёт = msg("15 750 ₽ · Закупка у конкурентов — нет описания: что купили?",
                    sender=BOT, is_bot=True)
        self.assertEqual(sa.parse_answers([отчёт], known=self.known), {})

    def test_multiline_text_is_not_a_press(self):
        """Кнопка присылает ровно свой текст — одной строкой."""
        длинный = msg("Борд продаж · Сентябрь 2026\nОборот: 7 730 000 ₽")
        self.assertEqual(sa.parse_answers([длинный], known=self.known), {})

    def test_too_long_text_is_not_a_press(self):
        self.assertEqual(sa.parse_answers([msg("вношу · " + "Я" * 90)], known=self.known), {})

    def test_unasked_client_is_ignored(self):
        """Ответ про клиента, о котором не спрашивали, не применяем."""
        self.assertEqual(sa.parse_answers([msg("не вношу · РЫБА МОЯ")], known=self.known), {})

    def test_real_press_passes_all_checks(self):
        self.assertEqual(sa.parse_answers([msg("вношу · Долма")], known=self.known),
                         {"Долма": "вносить"})

    def test_known_clients_come_from_state(self):
        state = {"asked": {"вносить:долма": {"client": "Долма"},
                           "колонка:рубель": {"client": "РУБЕЛЬ (ООО АВА ЦЕНТР)"}}}
        self.assertEqual(sa.asked_clients(state), {"долма", "рубельоооавацентр"})


class TestAnswers(unittest.TestCase):
    def test_parses_button_presses(self):
        answers = sa.parse_answers([msg("вношу · РУБЕЛЬ (ООО АВА ЦЕНТР)", 1),
                                    msg("не вношу · ЭКСПЕРТ ООО", 2),
                                    msg("разовый · Долма", 3),
                                    msg("привет", 4)])
        self.assertEqual(answers, {"РУБЕЛЬ (ООО АВА ЦЕНТР)": "вносить",
                                   "ЭКСПЕРТ ООО": "не вносить",
                                   "Долма": "разовый"})

    def test_last_press_wins(self):
        """Анна может передумать и нажать снова — берём последнее нажатие."""
        answers = sa.parse_answers([msg("вношу · Долма", 1), msg("не вношу · Долма", 2)])
        self.assertEqual(answers, {"Долма": "не вносить"})

    def test_match_by_prefix(self):
        """Имя в кнопке обрезано до 44 символов — сверяем по префиксу."""
        long = "ШЕСТНАДЦАТЬ ТОНН КЕЙТЕРИНГ ООО (ООО ШЕСТНАДЦАТЬ ТОНН)"
        answers = {long[:44]: "вносить"}
        self.assertEqual(sa.match_answer(long, answers), "вносить")

    def test_manager_name_passes_through(self):
        """Имя менеджера с кнопки отдаём как есть — разбирает его отчёт."""
        self.assertEqual(sa.parse_answers([msg("Дарья · Долма")]), {"Долма": "Дарья"})

    def test_other_client_not_matched(self):
        self.assertIsNone(sa.match_answer("РЫБА МОЯ (ООО МАСА)", {"Долма": "вносить"}))


class TestApplyAnswers(unittest.TestCase):
    def test_yes_marks_the_source(self):
        """«Вношу» — такая же санкция человека, как бланк: строка пойдёт в живой лист."""
        kept, refused = sr.apply_answers([calc()], {"РУБЕЛЬ (ООО АВА ЦЕНТР)": "вносить"})
        self.assertEqual((kept[0]["source"], kept[0]["kind"]), ("ответ Анны", "новый"))
        self.assertEqual(refused, [])

    def test_one_time_changes_the_kind(self):
        kept, _ = sr.apply_answers([calc()], {"РУБЕЛЬ (ООО АВА ЦЕНТР)": "разовый"})
        self.assertEqual(kept[0]["kind"], "разовый")

    def test_no_removes_the_row(self):
        kept, refused = sr.apply_answers([calc()], {"РУБЕЛЬ (ООО АВА ЦЕНТР)": "не вносить"})
        self.assertEqual(kept, [])
        self.assertEqual(refused[0]["client"], "РУБЕЛЬ (ООО АВА ЦЕНТР)")

    def test_manager_answer_fills_the_column(self):
        """Нажала «Дарья» — сумма пойдёт в её колонку (это и есть ответ «чей клиент»)."""
        kept, refused = sr.apply_answers([calc()], {"РУБЕЛЬ (ООО АВА ЦЕНТР)": "Дарья"})
        self.assertEqual(kept[0]["manager"], "Дарья Вольнова")
        self.assertEqual((kept[0]["source"], refused), ("ответ Анны", []))

    def test_unknown_answer_does_not_break_the_run(self):
        """Написала что-то своё — не роняем прогон, строка остаётся как была."""
        kept, _ = sr.apply_answers([calc()], {"РУБЕЛЬ (ООО АВА ЦЕНТР)": "ну посмотрим"})
        self.assertEqual((kept[0]["source"], kept[0].get("manager")), ("1С", None))

    def test_unanswered_row_is_left_alone(self):
        kept, refused = sr.apply_answers([calc()], {})
        self.assertEqual((kept[0]["source"], refused), ("1С", []))

    def test_refusal_goes_to_excluded_sheet(self):
        """Отказ помним в листе ИСКЛЮЧЕНИЯ — иначе спросим про того же в ноябре."""
        with mock.patch.object(sr, "write_excluded") as w:
            sr.remember_refused(mock.Mock(), [calc()], {}, today=date(2026, 10, 13))
        rows, stamp = w.call_args.args[1], w.call_args.args[2]
        self.assertEqual(rows, [("РУБЕЛЬ (ООО АВА ЦЕНТР)", sr.REFUSED_REASON)])
        self.assertEqual(stamp, "13.10")           # как пишет даты сама Анна

    def test_already_excluded_is_not_written_twice(self):
        with mock.patch.object(sr, "write_excluded") as w:
            sr.remember_refused(mock.Mock(), [calc()],
                                {"РУБЕЛЬ (ООО АВА ЦЕНТР)": {}}, today=date(2026, 10, 13))
        w.assert_not_called()


class TestOrphanRefusals(unittest.TestCase):
    """«Не вношу» про того, кого в расчёте нет (★ДЖЕМ, 13.10.2026)."""

    STATE = {"asked": {"колонка:джемоооджем": {"client": "ДЖЕМ (ООО ДЖЕМ)"}}}

    def test_orphan_still_goes_to_excluded(self):
        """Бланк есть, в 1С клиента нет — ответ не должен повиснуть."""
        out = sr.refused_orphans({"ДЖЕМ (ООО ДЖЕМ)": "не вносить"}, self.STATE, [])
        self.assertEqual([r["client"] for r in out], ["ДЖЕМ (ООО ДЖЕМ)"])

    def test_full_name_comes_from_state(self):
        """На кнопке имя обрезано до 44 символов, а исключения матчатся строго."""
        long = "ШЕСТНАДЦАТЬ ТОНН КЕЙТЕРИНГ ООО (ООО ШЕСТНАДЦАТЬ ТОНН)"
        state = {"asked": {"вносить:x": {"client": long}}}
        out = sr.refused_orphans({long[:44]: "не вносить"}, state, [])
        self.assertEqual(out[0]["client"], long)

    def test_client_in_calc_is_not_an_orphan(self):
        """Клиент в расчёте есть — его забирает apply_answers, дубля не делаем."""
        rows = [calc(client="ДЖЕМ (ООО ДЖЕМ)")]
        self.assertEqual(sr.refused_orphans({"ДЖЕМ (ООО ДЖЕМ)": "не вносить"},
                                            self.STATE, rows), [])

    def test_other_verdicts_are_not_orphans(self):
        self.assertEqual(sr.refused_orphans({"ДЖЕМ (ООО ДЖЕМ)": "вносить"}, self.STATE, []), [])


class TestAskRows(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.state = {"asked": {}, "answers": {}}
        self.p = mock.patch.multiple(
            sa, configured=lambda: True, time=mock.Mock(),      # без паузы между вопросами
            send_question=lambda text, options, user_id=None: self.sent.append(text) or "mid1")
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_asks_once_and_remembers(self):
        sa.ask_rows([calc()], {}, self.state)
        sa.ask_rows([calc()], {}, self.state)          # второй прогон — уже не спрашиваем
        self.assertEqual(len(self.sent), 1)
        self.assertIn("вносить:рубельоооавацентр", self.state["asked"])

    def test_two_kinds_of_question_do_not_block_each_other(self):
        """«Вносить ли» и «в чью колонку» — разные вопросы про одного клиента."""
        sa.ask_rows([calc()], {}, self.state)
        sa.ask_rows([calc()], {}, self.state, kind=sa.ASK_WHO,
                    managers=["Дарья Вольнова", "Алена Черкашина"])
        self.assertEqual(len(self.sent), 2)
        self.assertIn("в чью колонку?", self.sent[1])

    def test_manager_buttons_are_short_names(self):
        """На кнопке — имя без фамилии: иначе не влезает вместе с клиентом."""
        _, options = sa.manager_question(calc(), ["Дарья Вольнова", "София Хакимова"], row=12)
        self.assertEqual(options[:2], ["Дарья · РУБЕЛЬ (ООО АВА ЦЕНТР)",
                                       "София · РУБЕЛЬ (ООО АВА ЦЕНТР)"])
        self.assertEqual(options[-1], "не вношу · РУБЕЛЬ (ООО АВА ЦЕНТР)")

    def test_answered_client_is_not_asked_again(self):
        sa.ask_rows([calc()], {"РУБЕЛЬ (ООО АВА ЦЕНТР)": "вносить"}, self.state)
        self.assertEqual(self.sent, [])

    def test_limit_protects_the_inbox(self):
        rows = [calc(client=f"КЛИЕНТ {i}") for i in range(20)]
        sent = sa.ask_rows(rows, {}, self.state, limit=5)
        self.assertEqual((sent, len(self.sent)), (5, 5))


class TestAnswersThis(unittest.TestCase):
    """Какой вердикт какой вопрос закрывает (13.10.2026, случай ТЭМУ)."""

    def test_add_question_closed_by_any_verdict(self):
        for v in ("вносить", "не вносить", "разовый", "Дарья"):
            self.assertTrue(sa.answers_this(sa.ASK_ADD, v), v)

    def test_who_question_not_closed_by_yes(self):
        """«Вношу» не говорит, чей клиент — про колонку надо спросить отдельно."""
        self.assertFalse(sa.answers_this(sa.ASK_WHO, "вносить"))
        self.assertFalse(sa.answers_this(sa.ASK_WHO, "разовый"))

    def test_who_question_closed_by_manager_name(self):
        self.assertTrue(sa.answers_this(sa.ASK_WHO, "Дарья"))
        self.assertTrue(sa.answers_this(sa.ASK_WHO, "соня"))

    def test_who_question_closed_by_refusal(self):
        """«Не вношу» — клиент уезжает в ИСКЛЮЧЕНИЯ, колонка больше не нужна."""
        self.assertTrue(sa.answers_this(sa.ASK_WHO, "не вносить"))

    def test_no_answer_means_ask(self):
        self.assertFalse(sa.answers_this(sa.ASK_ADD, None))
        self.assertFalse(sa.answers_this(sa.ASK_WHO, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
