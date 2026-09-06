import asyncio
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import time as dtime, timezone, timedelta, datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError, RetryAfter, TimedOut
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, TypeHandler, CallbackQueryHandler, filters)

from parser import parse_report
from sheets import SheetsClient
from sync_odata import sync_all_bases, sync_oborot, oborot_report
from sync_novye import sync_novye
import watch_otvetstvennye
import zp_text
from sync_avansy import sync_avansy, format_report as _format_avansy, _open_summary_ws
import cash_avans
import beby_invoice
import beby_report

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
ANNA_CHAT_ID = os.environ.get("ANNA_CHAT_ID", "")
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
EMPLOYEES_FILE = os.path.join(os.path.dirname(__file__), "employees.json")
CALLS_NORM = 25
SHEETS_WRITE_ATTEMPTS = 3      # попыток записи смены при сетевом сбое
SHEETS_RETRY_DELAY_SEC = 3     # базовая пауза между попытками (растёт линейно)

sheets = SheetsClient(CREDENTIALS_PATH, SPREADSHEET_ID)

ANNA_USER_ID = int(ANNA_CHAT_ID) if ANNA_CHAT_ID else 0
MSK = timezone(timedelta(hours=3))
LAST_OFFSET_FILE = os.path.join(os.path.dirname(__file__), "last_update_id.txt")


def _load_last_offset() -> int:
    try:
        with open(LAST_OFFSET_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _save_last_offset(update_id: int) -> None:
    try:
        with open(LAST_OFFSET_FILE, 'w') as f:
            f.write(str(update_id))
    except Exception:
        logger.warning("Failed to save update offset %d", update_id)

AWAITING_NAME_FILE = os.path.join(os.path.dirname(__file__), "awaiting_name.json")


def _load_awaiting_names() -> set[int]:
    """Пользователи, от которых ждём имя для регистрации. Храним на диске,
    чтобы состояние переживало рестарт бота (иначе незавершённая регистрация
    теряется и человек не попадает в реестр)."""
    try:
        with open(AWAITING_NAME_FILE, encoding='utf-8') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return set()


def _save_awaiting_names() -> None:
    try:
        with open(AWAITING_NAME_FILE, 'w', encoding='utf-8') as f:
            json.dump(sorted(_awaiting_name), f)
    except Exception:
        logger.warning("Failed to persist awaiting_name set")


_awaiting_name: set[int] = _load_awaiting_names()
_awaiting_archive_confirm: set[int] = set()


# ─── employees.json helpers ───────────────────────────────────────────────────

def _load_employees() -> dict[str, str]:
    try:
        with open(EMPLOYEES_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_employees(data: dict):
    # Резервная копия перед сохранением
    if os.path.exists(EMPLOYEES_FILE):
        backup_path = EMPLOYEES_FILE.replace('.json', '.backup.json')
        try:
            with open(EMPLOYEES_FILE, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # Если бэкап не сработал, всё равно сохраняем новые данные

    with open(EMPLOYEES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _name_matches(registered: str, reported: str) -> bool:
    """True, если хотя бы одно значимое слово имени совпало.

    Порядок слов не важен, регистр тоже, ё считается за е: «Караханова Виолетта»
    и «Виолетта Караханова» — один человек, «Алёна» и «Алена» тоже.
    """
    def norm(t):
        return t.lower().replace("ё", "е")

    words = [w for w in norm(registered).split() if len(w) > 3 and w.isalpha()]
    rep = norm(reported)
    return any(w in rep for w in words)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _is_from_anna(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == ANNA_USER_ID)


def _is_report_request(text: str) -> bool:
    first_line = text.strip().splitlines()[0].strip().lower()
    if not re.match(r'^смена\b', first_line):
        return False
    if re.search(r'смена\s+(менеджер|влада)', first_line):
        return False
    return True


def _fmt_amount(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def _format_report(data: dict, include_amounts: bool) -> str:
    lines = [f"📊 Отчёт за {data['period_label']}\n"]
    grand_total = 0

    основные = [(n, s, a) for n, s, a in data['основные'] if s > 0]
    if основные:
        lines.append("Основные смены:")
        for name, shifts, amount in основные:
            if include_amounts:
                lines.append(f"  {name} — {shifts} смен / {_fmt_amount(amount)} ₽")
                grand_total += amount
            else:
                lines.append(f"  {name} — {shifts} смен")
        lines.append("")

    подработки = [(n, r1, r2, f1, f2, a) for n, r1, r2, f1, f2, a in data['подработки'] if r1 + r2 + f1 + f2 > 0]
    if подработки:
        lines.append("Подработки:")
        for name, rest_1, rest_2, firms_1, firms_2, amount in подработки:
            parts = []
            if rest_1:
                parts.append(f"рест.1тел: {rest_1}")
            if rest_2:
                parts.append(f"рест.2тел: {rest_2}")
            if firms_1:
                parts.append(f"фирмы+1тел: {firms_1}")
            if firms_2:
                parts.append(f"фирмы+2тел: {firms_2}")
            detail = ", ".join(parts)
            if include_amounts:
                lines.append(f"  {name} — {detail} / {_fmt_amount(amount)} ₽")
                grand_total += amount
            else:
                lines.append(f"  {name} — {detail}")
        lines.append("")

    if include_amounts and grand_total:
        lines.append(f"Итого: {_fmt_amount(grand_total)} ₽")

    return "\n".join(lines).strip()


# ─── handlers ─────────────────────────────────────────────────────────────────

def _format_sync_summary(summary) -> str:
    """Человекочитаемая сводка результата OData-синка для сообщения Анне."""
    if not isinstance(summary, dict):
        return "✅ Синхронизация из 1С завершена"
    titles = {"perfilev": "Перфильев", "gubarev": "Губарев"}
    lines = ["✅ Синхронизация из 1С завершена"]
    if summary.get("_mode") == "overlap":
        lines.append(
            f"🔒 Месяц не закрыт ({summary.get('_period', '')}).\n"
            "Новый месяц копится в листах ДАННЫЕ_*_СЛЕД, живой лист не тронут.\n"
            "Закрой месяц командой закрытия — данные перенесутся автоматически."
        )
    new_all = []
    for base, s in summary.items():
        if base.startswith("_"):
            continue
        lines.append(
            f"• {titles.get(base, base)}: обновлено {s.get('updates', 0)} строк"
        )
        for name in s.get("new_names", []):
            new_all.append(name)
    if new_all:
        lines.append("")
        lines.append(f"⚠️ Нет в листе ({len(new_all)}) — назначь менеджера/сверь:")
        lines.extend(f"  – {n}" for n in new_all)
    return "\n".join(lines)


async def handle_sync_1c(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Синхронизировать данные из 1С в Google Sheets"""
    if not _is_from_anna(update):
        await update.message.reply_text("⛔ Эта команда только для Анны")
        return

    await update.message.reply_text("🔄 Начинаю синхронизацию из 1С...")

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, sync_all_bases)
        oborot = await loop.run_in_executor(None, sync_oborot)
        text = _format_sync_summary(summary)
        if summary.get("_mode") == "overlap":
            text += (f"\n\n💰 Оборот (справочно, тек. месяц): {oborot:,.0f} ₽"
                     .replace(",", " ") + "\n🔒 В СВОДНУЮ не записан — месяц не закрыт")
        else:
            text += f"\n\n💰 Оборот (Продажи): {oborot:,.0f} ₽".replace(",", " ")
        await update.message.reply_text(text)
    except Exception as e:
        logger.exception("Failed to sync 1C data")
        await update.message.reply_text(f"❌ Ошибка синхронизации: {str(e)}")


_RU_MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
              "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

# Состояние интерактивного диалога наличного аванса (в личке Анны). Пусто = не идёт.
_cash_flow = {}


def _month_label():
    now = datetime.now(MSK)
    return f"{_RU_MONTHS[now.month - 1]} {now.year}"


AVANS_STATE_FILE = os.path.join(os.path.dirname(__file__), "avans_state.json")


def _avans_confirmed_month():
    """Ключ месяца, за который наличный аванс уже подтверждён (или None)."""
    try:
        with open(AVANS_STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("cash_confirmed_month")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _mark_avans_confirmed():
    key = datetime.now(MSK).strftime("%Y-%m")
    with open(AVANS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"cash_confirmed_month": key}, f)


def _is_avans_confirmed():
    return _avans_confirmed_month() == datetime.now(MSK).strftime("%Y-%m")


def _read_payout_rows():
    """Строки таблицы выплат (A154:D163) → [(имя, ЗП, офиц, наличные), …]."""
    grid = _open_summary_ws().get("A154:D163", value_render_option="UNFORMATTED_VALUE")
    rows = []
    for r in grid:
        name = (r[0] if r else "") or ""
        if not name:
            continue
        zp = r[1] if len(r) > 1 else 0
        c = r[2] if len(r) > 2 else 0
        d = r[3] if len(r) > 3 else 0
        rows.append((name, zp, c, d))
    return rows


async def _send_avans_summary(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Прислать итоговую сводку по авансам (табличный вид, HTML)."""
    import asyncio
    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(None, _read_payout_rows)
    await context.bot.send_message(
        chat_id, cash_avans.build_summary(rows, _month_label()), parse_mode="HTML")


async def _cash_start(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Запустить диалог наличного аванса: читает офиц.авансы (C), считает
    предлагаемые суммы и начинает опрос по CASH_PLAN."""
    import asyncio
    loop = asyncio.get_event_loop()
    grid = await loop.run_in_executor(
        None, lambda: _open_summary_ws().get(
            "A154:D163", value_render_option="UNFORMATTED_VALUE"))
    official = {}
    for i, row in enumerate(grid):
        official[154 + i] = row[2] if len(row) > 2 else None

    queue = []
    for row, name, rule in cash_avans.CASH_PLAN:
        default = cash_avans.compute_default(rule, official.get(row))
        queue.append({"row": row, "name": name, "default": default,
                      "official": float(official.get(row) or 0)})

    _cash_flow.clear()
    _cash_flow.update({"queue": queue, "idx": 0, "results": {},
                       "await_amount": False, "chat_id": chat_id})
    await context.bot.send_message(
        chat_id, "💵 Официальные авансы вписаны. Теперь наличные — по каждому:")
    await _cash_ask(context)


async def _cash_ask(context: ContextTypes.DEFAULT_TYPE):
    """Показать вопрос по текущему сотруднику (или завершить диалог)."""
    fl = _cash_flow
    if not fl or fl["idx"] >= len(fl["queue"]):
        await _cash_finish(context)
        return
    it = fl["queue"][fl["idx"]]
    name, default, off = it["name"], it["default"], it["official"]
    if default is None:
        fl["await_amount"] = True
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⏭ Без наличных", callback_data="cash:skip")]])
        await context.bot.send_message(
            fl["chat_id"],
            f"💵 {name}: сколько наличными? Пришлите сумму сообщением (или «0»).",
            reply_markup=kb)
    else:
        fl["await_amount"] = False
        itg = cash_avans._fmt(off + default)
        txt = (f"💵 {name} — наличный аванс\n"
               f"Официальный (на карту): {cash_avans._fmt(off)} ₽\n"
               f"Предлагаю наличными: {cash_avans._fmt(default)} ₽  → итого {itg} ₽")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ {cash_avans._fmt(default)} ₽",
                                  callback_data="cash:ok")],
            [InlineKeyboardButton("✏️ Другая", callback_data="cash:edit"),
             InlineKeyboardButton("⏭ Без наличных", callback_data="cash:skip")],
        ])
        await context.bot.send_message(fl["chat_id"], txt, reply_markup=kb)


async def _cash_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок диалога наличного аванса."""
    q = update.callback_query
    await q.answer()
    if not _cash_flow or not q.from_user or q.from_user.id != ANNA_USER_ID:
        return
    it = _cash_flow["queue"][_cash_flow["idx"]]
    data = q.data
    if data == "cash:ok":
        _cash_flow["results"][it["row"]] = it["default"]
        await q.edit_message_text(
            f"✅ {it['name']}: наличными {cash_avans._fmt(it['default'])} ₽")
        _cash_flow["idx"] += 1
        await _cash_ask(context)
    elif data == "cash:edit":
        _cash_flow["await_amount"] = True
        await q.edit_message_text(
            f"✏️ {it['name']}: пришлите сумму наличными сообщением.")
    elif data == "cash:skip":
        _cash_flow["results"][it["row"]] = 0
        await q.edit_message_text(f"⏭ {it['name']}: без наличных.")
        _cash_flow["idx"] += 1
        await _cash_ask(context)


async def _cash_handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Анна прислала сумму наличных текстом (после «Другая» или для Влады)."""
    amt = cash_avans.parse_amount(text)
    it = _cash_flow["queue"][_cash_flow["idx"]]
    if amt is None:
        await update.message.reply_text(
            "Не понял сумму. Пришлите число, напр. 7000, или «0».")
        return
    _cash_flow["results"][it["row"]] = amt
    _cash_flow["await_amount"] = False
    await update.message.reply_text(
        f"✅ {it['name']}: наличными {cash_avans._fmt(amt)} ₽")
    _cash_flow["idx"] += 1
    await _cash_ask(context)


async def _cash_finish(context: ContextTypes.DEFAULT_TYPE):
    """Записать наличные в колонку D, отметить месяц подтверждённым и прислать итог."""
    fl = _cash_flow
    chat_id = fl.get("chat_id", ANNA_CHAT_ID and int(ANNA_CHAT_ID))
    results = dict(fl["results"])
    import asyncio
    loop = asyncio.get_event_loop()

    def _write():
        ws = _open_summary_ws()
        updates = [{"range": f"D{row}", "values": [[amt if amt else ""]]}
                   for row, amt in results.items()]
        updates.append({"range": "D154", "values": [[""]]})  # Дарья — без наличных
        if updates:
            ws.batch_update(updates, value_input_option="USER_ENTERED")

    await loop.run_in_executor(None, _write)
    _cash_flow.clear()
    _mark_avans_confirmed()
    await _send_avans_summary(context, chat_id)


async def handle_avans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/avans — если наличные уже подтверждены за этот месяц, просто прислать итог;
    иначе заполнить официальные авансы (C) из кассы и запустить диалог наличных."""
    if not _is_from_anna(update):
        await update.message.reply_text("⛔ Эта команда только для Анны")
        return
    if _cash_flow:
        await update.message.reply_text(
            "Диалог аванса уже идёт — ответьте на текущий вопрос или /cancel_avans.")
        return
    # уже подтверждала в этом месяце → не переспрашиваем, просто итог
    if _is_avans_confirmed():
        await _send_avans_summary(context, update.effective_chat.id)
        return
    await update.message.reply_text("🔄 Заполняю официальные авансы из кассы...")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        rep = await loop.run_in_executor(None, lambda: sync_avansy("avans", apply=True))
        await update.message.reply_text(_format_avansy(rep))
        await _cash_start(context, update.effective_chat.id)
    except Exception as e:
        logger.exception("handle_avans failed")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def handle_cancel_avans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cancel_avans — прервать незавершённый диалог наличного аванса."""
    if not _is_from_anna(update):
        return
    if _cash_flow:
        _cash_flow.clear()
        await update.message.reply_text("Диалог аванса прерван. Наличные не записаны.")
    else:
        await update.message.reply_text("Активного диалога аванса нет.")


ZP_ORDER = list(zp_text.SHORT)          # порядок сотрудников в кнопках
ZP_STATE_FILE = os.path.join(os.path.dirname(__file__), "zp_send_state.json")
# куда уходит автоматическая рассылка расчётов: группа «зарплата», если её id задан
# в .env (ZP_GROUP_CHAT_ID), иначе — Анне в личку
ZP_GROUP_CHAT_ID = os.environ.get("ZP_GROUP_CHAT_ID", "")


# ─── беби-листы: накладная PDF → лист «аналитика беби» ────────────────────────

# Кто может присылать боту накладные по беби. Решение Анны 06.09.2026: накладные
# кидает Влада, и ТОЛЬКО в личку — «мы в группе продажи график этого не делаем,
# всё только через личку». По умолчанию Влада (id из employees.json), список
# можно переопределить в .env: BEBY_SENDER_IDS=111,222
BEBY_VLADA_ID = 6630193697
BEBY_SENDER_IDS = {int(x) for x in os.environ.get(
    "BEBY_SENDER_IDS", str(BEBY_VLADA_ID)).replace(" ", "").split(",") if x}
if ANNA_USER_ID:
    BEBY_SENDER_IDS.add(ANNA_USER_ID)


def _beby_sender_name(user) -> str | None:
    """Имя приславшего накладную или None, если ему это не разрешено."""
    if not user or user.id not in BEBY_SENDER_IDS:
        return None
    if user.id == ANNA_USER_ID:
        return "Анна"
    return _load_employees().get(str(user.id)) or user.full_name or str(user.id)


def _beby_close_kb(sheet, d1, d2) -> InlineKeyboardMarkup:
    """Кнопка «Закрыть период» — показываем только Анне: границы периодов её."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        f"Закрыть период {d1:%d.%m}–{d2:%d.%m}",
        callback_data=f"beby:close:{sheet}:{d1:%Y-%m-%d}:{d2:%Y-%m-%d}")]])


async def handle_beby_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """PDF накладной в личке от Анны или Влады: внести в таблицу.

    Приславшему уходит подтверждение по накладной, Анне — оно же плюс сводка
    текущего периода с прибылью и кнопка «Закрыть период»."""
    message = update.effective_message
    doc = message.document if message else None
    chat = update.effective_chat
    user = update.effective_user
    logger.info("Beby: документ %r (mime %s) от %s в чате %s (%s)",
                getattr(doc, "file_name", None), getattr(doc, "mime_type", None),
                getattr(user, "id", None), getattr(chat, "id", None),
                getattr(chat, "type", None))
    if not doc:
        return
    name = (doc.file_name or "").lower()
    if not (name.endswith(".pdf") or doc.mime_type == "application/pdf"):
        logger.info("Beby: пропускаю, не PDF (%s)", name or doc.mime_type)
        return
    sender = _beby_sender_name(user)
    if sender is None:
        logger.info("Beby: пропускаю, отправителю %s накладные не разрешены (%s)",
                    getattr(user, "id", None), sorted(BEBY_SENDER_IDS))
        return
    if chat.type != "private":
        await message.reply_text(
            "📄 Накладную по беби пришлите мне в личку — здесь я её не разбираю.")
        return

    await message.reply_text("📄 Разбираю накладную…")
    tmp = os.path.join(tempfile.gettempdir(), f"beby_{doc.file_unique_id}.pdf")
    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(tmp)
        loop = asyncio.get_event_loop()
        head, summary, period = await loop.run_in_executor(
            None, lambda: beby_report.process_invoice(tmp))
    except beby_invoice.NotAnInvoice as e:
        # Юшин шлёт и счета на оплату — их в отчёт не берём (правило Анны 18.08)
        await message.reply_text(f"↩️ Пропустил: {e}.")
        return
    except Exception as e:
        logger.exception("Beby invoice failed")
        await message.reply_text(f"❌ Не смог разобрать накладную: {e}")
        return
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    sheet, d1, d2 = period
    is_anna = user.id == ANNA_USER_ID
    if is_anna:
        await message.reply_text(f"{head}\n\n{summary}",
                                 reply_markup=_beby_close_kb(sheet, d1, d2))
        return

    # Влада видит только свою накладную: прибыль и рентабельность — Анне
    await message.reply_text(f"{head}\n\nПередал Анне, период закроет она.")
    if ANNA_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"📄 Накладную прислала {sender}.\n\n{head}\n\n{summary}",
                reply_markup=_beby_close_kb(sheet, d1, d2))
        except Exception:
            logger.exception("Beby: не смог переслать накладную Анне")


async def handle_beby(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/beby — как идёт текущий (незакрытый) период по беби-листам (Анна)."""
    if not _is_from_anna(update):
        # Владе сводку с прибылью не показываем — только напоминаем порядок
        if _beby_sender_name(update.effective_user):
            await update.message.reply_text(
                "Пришлите PDF накладной сюда, в личку — я внесу её в таблицу. "
                "Отчёт по периоду закрывает Анна.")
        return
    loop = asyncio.get_event_loop()
    try:
        sheet, d1, d2 = await loop.run_in_executor(None, _beby_current)
        text = await loop.run_in_executor(
            None, lambda: beby_report.period_summary(sheet, d1, d2,
                                                     prefix="Беби-листы, текущий период\n"))
    except Exception as e:
        logger.exception("Beby summary failed")
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return
    await update.message.reply_text(text, reply_markup=_beby_close_kb(sheet, d1, d2))


async def handle_beby_writeoff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Списания беби-листов сообщением: «мизуна зеленая 5 сегодня, микс 1…».

    Сразу не пишем: показываем, что поняли, и ждём подтверждения кнопкой —
    текст свободный, ошибиться легко, а списание меняет остатки.
    """
    if not _is_from_anna(update) or update.effective_chat.type != "private":
        return
    text = (update.effective_message.text or "")
    loop = asyncio.get_event_loop()
    today = datetime.now(MSK).date()
    try:
        items, unknown = await loop.run_in_executor(
            None, lambda: beby_report.parse_writeoffs(text, today))
    except Exception as e:
        logger.exception("Beby writeoff parse failed")
        await update.message.reply_text(f"❌ Не смог разобрать списания: {e}")
        return
    if not items and not unknown:
        return                                   # не про списания — молчим

    lines = ["📝 Списания, как я понял:"]
    lines += [f"   {d:%d.%m}  {name} — {q:g} пачек" for d, _k, name, q in items]
    if unknown:
        lines.append("")
        lines.append("Не понял, что за позиция (не внесу):")
        lines += [f"   {d:%d.%m}  «{name}» — {q:g}" for d, name, q in unknown]
    kb = None
    if items:
        token = str(uuid.uuid4())[:8]
        context.bot_data.setdefault("beby_writeoffs", {})[token] = items
        lines.append("")
        lines.append("Вносить?")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Внести", callback_data=f"beby:wo:{token}"),
            InlineKeyboardButton("Отмена", callback_data="beby:wocancel")]])
    await update.message.reply_text("\n".join(lines), reply_markup=kb)


def _beby_current():
    """(лист, d1, d2) незакрытого периода текущего месяца."""
    today = datetime.now(MSK).date()
    sheet = beby_report.MONTHS[today.month - 1]
    ws = beby_report.open_sheet(sheet)
    d1, d2 = beby_report.current_period(ws, today)
    return sheet, d1, d2


async def _beby_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопки беби: «Закрыть период» и подтверждение списаний — только Анна."""
    query = update.callback_query
    if not query.from_user or query.from_user.id != ANNA_USER_ID:
        await query.answer("Период закрывает Анна.", show_alert=True)
        return
    await query.answer()
    loop = asyncio.get_event_loop()

    if query.data == "beby:wocancel":
        await query.edit_message_text("Отменил, ничего не вносил.")
        return

    if query.data.startswith("beby:wo:"):
        token = query.data.split(":")[2]
        items = (context.bot_data.get("beby_writeoffs") or {}).pop(token, None)
        if not items:
            await query.edit_message_text(
                "Не нашёл эти списания (бот перезапускался) — пришлите текст ещё раз.")
            return
        sheet = beby_report.MONTHS[datetime.now(MSK).date().month - 1]
        try:
            applied, problems = await loop.run_in_executor(
                None, lambda: beby_report.apply_writeoffs(sheet, items))
        except Exception as e:
            logger.exception("Beby writeoff apply failed")
            await query.edit_message_text(f"❌ Не смог внести списания: {e}")
            return
        lines = [f"✅ Внёс списаний: {len(applied)}"] if applied else ["Ничего не внёс."]
        lines += [f"   {label}: {name} −{q:g} → на остатке {rest:g}"
                  for label, _d, name, q, rest in applied]
        if problems:
            lines.append("")
            lines.append("Не вышло:")
            lines += [f"   {p}" for p in problems]
        await query.edit_message_text("\n".join(lines))
        return

    _, _, sheet, s1, s2 = query.data.split(":")
    d1 = datetime.strptime(s1, "%Y-%m-%d").date()
    d2 = datetime.strptime(s2, "%Y-%m-%d").date()
    loop = asyncio.get_event_loop()
    try:
        label, rows, tot, written = await loop.run_in_executor(
            None, lambda: beby_report.close_period(sheet, d1, d2))
    except Exception as e:
        logger.exception("Beby close failed")
        await query.edit_message_text(f"❌ Не смог закрыть период: {e}")
        return
    if not written:
        await query.edit_message_text(f"Блок «{label}» в листе «{sheet}» уже есть — "
                                      f"ничего не менял.")
        return
    nalog = tot[3] * 0.11
    profit = tot[3] - nalog - tot[1] - 1000
    await query.edit_message_text(
        (f"✅ Блок «{label}» записан в лист «{sheet}».\n"
         f"купили {tot[0]:.0f} — {tot[1]:,.0f} ₽, продали {tot[2]:.0f} — {tot[3]:,.0f} ₽\n"
         f"прибыль {profit:,.0f} ₽\n"
         f"Колонка «списали» пустая — впиши, если что-то испортилось; "
         f"«на остатке» посчитан, можно поправить руками.").replace(",", " "))


async def handle_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chatid — сказать id текущего чата. Нужен, чтобы подключить новую группу:
    id группы иначе не узнать (бот в polling забирает апдейты себе)."""
    # без parse_mode: подчёркивание в «chat_id» Telegram принимает за начало курсива
    # и падает с «Can't parse entities»
    chat = update.effective_chat
    await update.message.reply_text(
        f"id этого чата: {chat.id}\nтип: {chat.type}\nназвание: {chat.title or '—'}")


def _load_zp_state() -> dict:
    try:
        with open(ZP_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_zp_state(state: dict) -> None:
    with open(ZP_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def _zp_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("📊 Сводка по отделу", callback_data="zp:dept")]]
    pairs = [InlineKeyboardButton(zp_text.SHORT[n], callback_data=f"zp:one:{i}")
             for i, n in enumerate(ZP_ORDER)]
    rows += [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
    rows.append([InlineKeyboardButton("📨 Тексты всем", callback_data="zp:all"),
                 InlineKeyboardButton("📎 Файлы 1С", callback_data="zp:files")])
    return InlineKeyboardMarkup(rows)


async def handle_zarplata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/zp и /zarplata — расчёт ЗП в любой момент: по отделу или по человеку.

    С аргументом («/zp Дарья») сразу отдаёт расчёт этого сотрудника, без — меню."""
    if not _is_from_anna(update):
        await update.message.reply_text("⛔ Эта команда только для Анны")
        return
    arg = " ".join(context.args).strip().lower() if context.args else ""
    if not arg:
        await update.message.reply_text("💰 Зарплата — что показать?",
                                        reply_markup=_zp_keyboard())
        return
    who = next((n for n in ZP_ORDER
                if arg in n.lower() or arg in zp_text.SHORT[n].lower()), None)
    if not who:
        await update.message.reply_text(
            "Не нашла такого сотрудника. Попробуйте /zp без имени — там кнопки со всеми.")
        return
    msg = await update.message.reply_text(f"⏳ Считаю — {zp_text.SHORT[who]}…")
    package = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _zp_files().build_package(only=who))
    await msg.delete()
    await _send_pairs(context, update.effective_chat.id, package)


async def _zp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопки меню /zp."""
    query = update.callback_query
    await query.answer()
    if not _is_from_anna(update):
        return
    parts = query.data.split(":")
    action = parts[1]
    loop = asyncio.get_event_loop()
    chat_id = query.message.chat_id

    if action == "dept":
        await query.edit_message_text("⏳ Считаю…")
        text = await loop.run_in_executor(None, zp_text.department_summary)
        await query.edit_message_text(text, parse_mode="HTML")
        return

    if action == "one":
        who = ZP_ORDER[int(parts[2])]
        await query.edit_message_text(f"⏳ Считаю — {zp_text.SHORT[who]}…")
        package = await loop.run_in_executor(
            None, lambda: _zp_files().build_package(only=who))
        await query.edit_message_text(f"💰 {zp_text.SHORT[who]}")
        await _send_pairs(context, chat_id, package)
        return

    if action == "all":
        await query.edit_message_text("⏳ Считаю расчёты и собираю файлы по всем…")
        package = await loop.run_in_executor(None, _zp_files().build_package)
        await query.edit_message_text("💰 Расчёты по всем — ниже, у каждого сразу его файл")
        await _send_pairs(context, chat_id, package)
        await _send_totals(context, chat_id)
        return

    if action == "files":
        await query.edit_message_text("⏳ Собираю файлы взаиморасчётов из 1С…")
        files = await loop.run_in_executor(None, _zp_files().build_files)
        for path, caption, *_ in files:
            with open(path, "rb") as fh:
                await context.bot.send_document(chat_id=chat_id, document=fh,
                                                filename=os.path.basename(path),
                                                caption=caption)
        await query.edit_message_text(f"✅ Файлы ({len(files)} шт.) — выше")


def _zp_files():
    """Ленивый импорт: zp_files требует openpyxl, и без него должен отваливаться
    только сбор файлов, а не весь бот (05.08 бот так ушёл в цикл рестартов)."""
    import zp_files
    return zp_files


async def _retry_send(what: str, coro_factory, attempts: int = 3):
    """Отправить с повторами. Одна сетевая заминка не должна обрывать всю рассылку:
    05.08 TimedOut на четвёртом сотруднике оставил Анну без половины расчётов.
    Возможный побочный эффект — дубль сообщения, если ответ Telegram потерялся уже
    после доставки; это лучше, чем молча пропущенный расчёт."""
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except RetryAfter as exc:
            # Telegram притормаживает при пачке сообщений подряд и сам говорит,
            # сколько ждать — это не ошибка, просто пауза
            await asyncio.sleep(exc.retry_after + 1)
        except (TimedOut, NetworkError) as exc:
            if attempt == attempts - 1:
                logger.warning("Не удалось отправить %s: %s", what, exc)
                return None
            await asyncio.sleep(3 * (attempt + 1))
        except Exception:
            # что угодно ещё (битый файл, ошибка разметки) — пропускаем этот пункт,
            # но рассылку по остальным людям не роняем
            logger.exception("Ошибка при отправке %s", what)
            return None
    logger.warning("Не удалось отправить %s: исчерпаны попытки", what)
    return None


async def _send_pairs(context: ContextTypes.DEFAULT_TYPE, chat_id: int, package) -> None:
    """Расчёт сотрудника и сразу под ним его файл — чтобы не путать, чей файл чей."""
    failed = []
    for who, text, path, caption in package:
        sent = await _retry_send(f"расчёт {who}", lambda: context.bot.send_message(
            chat_id=chat_id, text=text, read_timeout=60, write_timeout=60))
        if sent is None:
            failed.append(who)
        if path:
            async def send_file(path=path, caption=caption):
                # именно async с await внутри with: если вернуть корутину наружу,
                # файл закроется до отправки («read of closed file»)
                with open(path, "rb") as fh:
                    return await context.bot.send_document(
                        chat_id=chat_id, document=fh, filename=os.path.basename(path),
                        caption=caption, read_timeout=120, write_timeout=120)
            if await _retry_send(f"файл {who}", send_file) is None:
                failed.append(f"{who} (файл)")
        await asyncio.sleep(1)
    if failed:
        await _retry_send("список несработавших", lambda: context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Не удалось отправить: " + ", ".join(failed) +
                 "\nПовторите /zp — Telegram не принял эти сообщения."))


async def _send_totals(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Хвост рассылки по всем: таблица выплат и отдельно — что отдать наличными 10-го."""
    loop = asyncio.get_event_loop()
    summary = await loop.run_in_executor(None, zp_text.department_summary)
    await _retry_send("сводку", lambda: context.bot.send_message(
        chat_id=chat_id, text=summary, parse_mode="HTML",
        read_timeout=60, write_timeout=60))
    cash = await loop.run_in_executor(None, zp_text.cash_summary)
    await _retry_send("итог наличных", lambda: context.bot.send_message(
        chat_id=chat_id, text=cash, read_timeout=60, write_timeout=60))


async def _send_zp_package(context: ContextTypes.DEFAULT_TYPE, header: str) -> None:
    """Полный пакет: заголовок и по каждому — расчёт + его файл.

    Уходит в группу «зарплата» (ZP_GROUP_CHAT_ID) и дублем Анне в личку — её решение
    от 05.08. Пока группа не подключена, остаётся только личка."""
    targets = [t for t in (ZP_GROUP_CHAT_ID, ANNA_CHAT_ID) if t]
    if not targets:
        return
    package = await asyncio.get_event_loop().run_in_executor(None, _zp_files().build_package)
    for target in targets:
        chat_id = int(target)
        await context.bot.send_message(chat_id=chat_id, text=header)
        await _send_pairs(context, chat_id, package)
        await _send_totals(context, chat_id)


async def auto_zp_monthly(context: ContextTypes.DEFAULT_TYPE):
    """Пакет расчётов ЗП дважды за цикл: 5 числа и 10-го, когда придёт офиц. зарплата.

    Висит ежечасно (см. расписание), но отправляет один раз за месяц на каждый повод —
    отметка в zp_send_state.json. 10-го ждём, пока sync_avansy проставит колонку
    «ЗП 9 — на карту»: до этого в текстах не было бы официальной части.
    """
    now = datetime.now(MSK)
    key = now.strftime("%Y-%m")
    state = _load_zp_state()
    try:
        if now.day == 5 and state.get("sent_5") != key:
            await _send_zp_package(context, "📅 5 число — расчёт ЗП за расчётный месяц")
            state["sent_5"] = key
        elif now.day in (10, 11) and state.get("sent_10") != key:
            ready = await asyncio.get_event_loop().run_in_executor(
                None, zp_text.official_zp_ready)
            if not ready:
                return                      # официальную ЗП ещё не прислали — ждём
            await _send_zp_package(
                context, "💳 Официальная зарплата проставлена — итоговый расчёт")
            state["sent_10"] = key
        else:
            return
        _save_zp_state(state)
        logger.info("ZP package sent (day=%d)", now.day)
    except Exception as e:
        logger.exception("ZP package failed")
        if ANNA_CHAT_ID:
            await context.bot.send_message(chat_id=int(ANNA_CHAT_ID),
                                           text=f"❌ Ошибка рассылки расчётов ЗП: {e}")


async def handle_avansy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Заполнить выплаты официальным сотрудникам из кассы (аванс/зарплата).

    /avansy         — по текущему числу (23-29 → аванс, 1-12 → зарплата)
    /avansy avans   — принудительно аванс (колонка C)
    /avansy zp      — принудительно зарплата (колонка E)
    """
    if not _is_from_anna(update):
        await update.message.reply_text("⛔ Эта команда только для Анны")
        return

    arg = (context.args[0].lower() if context.args else "").strip()
    if arg in ("avans", "аванс", "c"):
        kind = "avans"
    elif arg in ("zp", "зп", "зарплата", "e"):
        kind = "zp"
    else:
        day = datetime.now(MSK).day
        kind = "avans" if 20 <= day <= 31 else "zp"

    await update.message.reply_text("🔄 Тяну выплаты из кассы...")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        rep = await loop.run_in_executor(None, lambda: sync_avansy(kind, apply=True))
        await update.message.reply_text(_format_avansy(rep))
    except Exception as e:
        logger.exception("Failed to sync avansy")
        await update.message.reply_text(f"❌ Ошибка заполнения выплат: {str(e)}")


async def auto_avansy(context: ContextTypes.DEFAULT_TYPE):
    """В дни выплат опрашивает кассу (каждый час 10-15 МСК, см. расписание) и
    заполняет таблицу выплат СВОДНАЯ_ЗП, как только выплата появится.
    24-25 число → аванс (колонка C), 9-10 → зарплата (колонка E), иначе тихо выходим.
    Пишет и уведомляет Анну ТОЛЬКО по появившимся/изменившимся суммам (не спамит
    каждый час одинаковым); идемпотентно.
    """
    day = datetime.now(MSK).day
    if day in (24, 25):
        kind = "avans"
    elif day in (9, 10):
        kind = "zp"
    else:
        return
    logger.info("Starting auto avansy sync (day=%d, kind=%s)", day, kind)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        rep = await loop.run_in_executor(
            None, lambda: sync_avansy(kind, apply=True, only_changed=True))
        if not rep["changed"]:
            return  # ничего нового — не пишем и не спамим Анну
        logger.info("Avansy synced: %d new/changed applied=%s",
                    len(rep["changed"]), rep["applied"])
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=_format_avansy(rep, only_changed=True))
            # после появления официальных авансов — запустить диалог наличных
            # (только аванс, один раз: не при активном диалоге и не если Анна
            # уже подтвердила наличные за этот месяц)
            if kind == "avans" and not _cash_flow and not _is_avans_confirmed():
                await _cash_start(context, int(ANNA_CHAT_ID))
    except Exception as e:
        logger.exception("Auto avansy failed")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"❌ Ошибка авто-заполнения выплат: {str(e)}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not user:
        return

    if chat.type != 'private':
        await update.message.reply_text("Напиши мне в личку /start для регистрации.")
        return

    employees = _load_employees()
    if str(user.id) in employees:
        await update.message.reply_text(f"Ты уже зарегистрирован как {employees[str(user.id)]}.")
        return

    _awaiting_name.add(user.id)
    _save_awaiting_names()
    await update.message.reply_text("Привет! Напиши своё имя и фамилию (как в таблице смен).")


async def _handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = update.message.text.strip()

    if len(name) < 3 or not any(c.isalpha() for c in name):
        await update.message.reply_text("Напиши имя и фамилию.")
        return

    employees = _load_employees()
    employees[str(user.id)] = name
    _save_employees(employees)
    _awaiting_name.discard(user.id)
    _save_awaiting_names()

    await update.message.reply_text(f"Готово! Ты зарегистрирован как {name}.")
    logger.info("Registered user %d as %r", user.id, name)

    if ANNA_CHAT_ID:
        await context.bot.send_message(
            chat_id=int(ANNA_CHAT_ID),
            text=f"✅ Новая регистрация: {name} (id: {user.id})",
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    chat = update.effective_chat
    user = update.effective_user

    # Диагностика: логируем полный текст любого сообщения-смены на входе
    if re.search(r'^\s*смена', text.lower()):
        logger.info("Incoming shift: chat=%s(%s) user=%s\n%s",
                    getattr(chat, 'id', None), getattr(chat, 'type', None),
                    getattr(user, 'id', None), text[:400])

    # Диалог наличного аванса: Анна прислала сумму текстом
    if (_cash_flow.get("await_amount") and chat.type == 'private'
            and user and user.id == ANNA_USER_ID):
        await _cash_handle_amount(update, context, text)
        return

    # Регистрация: сотрудник вводит имя в личке
    if user and user.id in _awaiting_name and chat.type == 'private':
        await _handle_registration(update, context)
        return

    # Белый список чатов
    if chat.type in ('group', 'supergroup'):
        if str(chat.id) != GROUP_CHAT_ID:
            return
    elif chat.type == 'private':
        if not user or user.id != ANNA_USER_ID:
            first = text.strip().splitlines()[0].strip().lower()
            if re.search(r'^смена', first):
                await update.message.reply_text(
                    "Отчёты нужно отправлять в рабочий групповой чат, не мне в личку."
                )
            return

    # Команды только для Анны в личке
    if _is_from_anna(update) and chat.type == 'private':
        if user and user.id in _awaiting_archive_confirm:
            await _handle_archive_confirm(update, context, text)
            return
        if re.match(r'^закрыть\s+месяц', text.lower()) or text.lower() == 'архив':
            await _handle_archive_request(update, context)
            return

    # Запрос отчёта (только Анна)
    if _is_report_request(text) and _is_from_anna(update):
        await _handle_report(update, context, text)
        return

    # Отчёт о смене
    report = parse_report(text)
    if report is None:
        first = text.strip().splitlines()[0].strip().lower()
        is_group = chat.type in ('group', 'supergroup')
        is_anna_private = chat.type == 'private' and user and user.id == ANNA_USER_ID
        if re.search(r'^смена', first) and (is_group or is_anna_private) and user and ANNA_CHAT_ID:
            employees = _load_employees()
            registered_name = employees.get(str(user.id))
            sender = registered_name or (user.full_name or str(user.id))
            logger.warning("Failed to parse report from %s (chat=%s): %r", sender, chat.type, text[:120])
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"⚠️ Не могу прочитать отчёт от {sender} — проверь формат",
            )
        return

    # Проверка личности в группе
    if chat.type in ('group', 'supergroup') and user:
        employees = _load_employees()
        registered_name = employees.get(str(user.id))
        if not registered_name:
            logger.warning("Unregistered user %s (%s) sent report for %r", user.id, user.full_name, report.employee)
            if ANNA_CHAT_ID:
                await context.bot.send_message(
                    chat_id=int(ANNA_CHAT_ID),
                    text=f"⚠️ Незарегистрированный пользователь {user.full_name} (id: {user.id}) прислал отчёт за {report.employee}",
                )
            return
        if not _name_matches(registered_name, report.employee):
            logger.warning("Name mismatch: registered=%r reported=%r user=%s", registered_name, report.employee, user.id)
            if ANNA_CHAT_ID:
                await context.bot.send_message(
                    chat_id=int(ANNA_CHAT_ID),
                    text=f"⚠️ {registered_name} прислал отчёт за чужое имя: {report.employee}",
                )
            return

    # Запись в Google Sheets с повтором: сетевые обрывы (RemoteDisconnected,
    # ConnectionError и т.п.) не должны терять смену. update_report идемпотентна
    # (перечитывает лист и пишет одну ячейку), поэтому повтор безопасен.
    ok = None
    last_exc = None
    for attempt in range(1, SHEETS_WRITE_ATTEMPTS + 1):
        try:
            ok = sheets.update_report(report)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Sheets write failed (attempt %d/%d) for %s: %s",
                attempt, SHEETS_WRITE_ATTEMPTS, report.employee, exc,
            )
            if attempt < SHEETS_WRITE_ATTEMPTS:
                await asyncio.sleep(SHEETS_RETRY_DELAY_SEC * attempt)

    if last_exc is not None:
        logger.exception("Failed to update Google Sheets", exc_info=last_exc)
        # Сообщаем отправителю, чтобы он прислал смену повторно, и дублируем Анне.
        try:
            await update.effective_message.reply_text(
                "⚠️ Не удалось сохранить смену (сбой связи с таблицей). "
                "Пришлите отчёт ещё раз через пару минут."
            )
        except Exception:
            logger.exception("Failed to notify sender about save error")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"❌ Смена {report.employee} ({report.date}) НЕ сохранилась (сбой связи). Попросите прислать заново.",
            )
        return

    if ok:
        logger.info("Report saved | chat=%s employee=%s", chat.id, report.employee)
        await _check_calls_norm(report, context)
        await _check_early_report(report, context)
        await _check_wrong_date(report, context)
    else:
        logger.warning("Report not matched | chat=%s employee=%s date=%s", chat.id, report.employee, report.date)


async def _handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    period = text.strip().splitlines()[0].strip()[len("смена"):].strip()
    try:
        data = sheets.get_report(period)
    except Exception:
        logger.exception("Failed to get report")
        return

    is_private = update.effective_chat.type == "private"
    reply = _format_report(data, include_amounts=is_private)
    await update.effective_message.reply_text(reply)
    logger.info("Report sent | chat=%s period=%r", update.effective_chat.id, period)


async def _handle_archive_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        period = sheets._gc.open_by_key(sheets._spreadsheet_id).worksheet('НАСТРОЙКИ').acell('B4').value or '?'
    except Exception:
        period = 'текущий месяц'
    _awaiting_archive_confirm.add(user.id)
    await update.effective_message.reply_text(
        f"⚠️ Закрываю *{period}*.\n\n"
        f"Будут созданы архивные копии листов, после чего рабочие листы очистятся. "
        f"Это действие необратимо.\n\n"
        f"Напишите *подтверждаю* чтобы продолжить, или что угодно другое для отмены.",
        parse_mode='Markdown',
    )


async def _handle_archive_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user = update.effective_user
    _awaiting_archive_confirm.discard(user.id)
    if text.strip().lower() != 'подтверждаю':
        await update.effective_message.reply_text("Отменено.")
        return
    msg = await update.effective_message.reply_text("⏳ Архивирую месяц, подождите...")
    try:
        period = sheets.archive_month()
        await msg.edit_text(
            f"✅ Месяц *{period}* заархивирован.\n"
            f"Создан единый лист-архив со всеми данными (застывшие значения, "
            f"крупные секции свёрнуты).\n"
            f"Рабочие листы очищены, период обновлён на следующий месяц.",
            parse_mode='Markdown',
        )
        logger.info("Month archived by Anna: %s", period)
    except Exception:
        logger.exception("Failed to archive month")
        await msg.edit_text("❌ Ошибка при архивировании. Проверьте логи сервера.")


async def _check_calls_norm(report, context: ContextTypes.DEFAULT_TYPE):
    if report.manager_type != "поиск":
        return
    if not ANNA_CHAT_ID or not report.calls_total:
        return
    try:
        total = int(re.sub(r"\D", "", report.calls_total))
    except ValueError:
        return
    if total < CALLS_NORM:
        text = (
            f"⚠️ {report.employee} ({report.date}): "
            f"звонков всего {total} — меньше нормы ({CALLS_NORM})"
        )
        await context.bot.send_message(chat_id=int(ANNA_CHAT_ID), text=text)
        logger.info("Low calls alert sent for %s: %d", report.employee, total)


async def _check_early_report(report, context: ContextTypes.DEFAULT_TYPE):
    if not ANNA_CHAT_ID:
        return
    now = datetime.now(MSK)
    if now.hour < 16:
        await context.bot.send_message(
            chat_id=int(ANNA_CHAT_ID),
            text=(
                f"⏰ {report.employee} ({report.date}): "
                f"отчёт сдан в {now.strftime('%H:%M')} МСК — до 16:00"
            ),
        )
        logger.info("Early report alert for %s at %s", report.employee, now.strftime("%H:%M"))


async def _check_wrong_date(report, context: ContextTypes.DEFAULT_TYPE):
    if not ANNA_CHAT_ID:
        return
    today = datetime.now(MSK)
    date_str = report.date.strip()
    m = re.match(r"(\d{1,2})[.\-/](\d{1,2})", date_str)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        if day != today.day or month != today.month:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=(
                    f"📅 {report.employee}: дата в отчёте {date_str}, "
                    f"сегодня {today.strftime('%d.%m')} — возможно ошибка"
                ),
            )
            logger.info("Wrong date alert for %s: reported=%s today=%s", report.employee, date_str, today.strftime("%d.%m"))
    else:
        m2 = re.match(r"^(\d{1,2})$", date_str)
        if m2 and int(m2.group(1)) != today.day:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=(
                    f"📅 {report.employee}: дата в отчёте {date_str}, "
                    f"сегодня {today.strftime('%d.%m')} — возможно ошибка"
                ),
            )
            logger.info("Wrong date alert for %s: reported=%s today=%s", report.employee, date_str, today.strftime("%d.%m"))


# ─── scheduled jobs ───────────────────────────────────────────────────────────

async def auto_anna_shift(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(MSK)
    if now.weekday() >= 5:
        return
    day = now.day
    ok = sheets.write_shift('Анна Кононенко (РОП)', day)
    logger.info("Anna auto-shift day=%d ok=%s", day, ok)


async def auto_sync_1c(context: ContextTypes.DEFAULT_TYPE):
    """Автоматическая синхронизация данных из 1С"""
    logger.info("Starting auto sync from 1C")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, sync_all_bases)
        logger.info("Auto sync completed successfully: %s", summary)
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text="🌅 Авто-синк 1С\n" + _format_sync_summary(summary)
            )
    except Exception as e:
        logger.exception("Auto sync failed")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"❌ Ошибка автосинхронизации: {str(e)}"
            )


async def auto_oborot(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневно в 10:35 МСК: обновить оборот из 1С (Продажи) и прислать Анне
    мини-отчёт РОП — оборот, %плана и ссылку на таблицу."""
    logger.info("Starting daily oborot update")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        rep = await loop.run_in_executor(None, oborot_report)
        logger.info("Oborot updated: %s", rep)
        if ANNA_CHAT_ID:
            oborot = f"{rep['oborot']:,.0f}".replace(",", " ")
            postup = (f"{rep['postup']:,.0f}".replace(",", " ")
                      if rep.get("postup") is not None else "н/д")
            if rep.get("frozen"):
                text = (
                    f"🔒 РОП заморожен — месяц не закрыт ({rep.get('period', '')})\n"
                    "Оборот/поступления расчётного месяца в СВОДНОЙ не тронуты.\n\n"
                    "📎 Справочно, текущий календарный месяц:\n"
                    f"  💰 Оборот (Продажи): {oborot} ₽\n"
                    f"  💳 Поступления (касса): {postup} ₽\n\n"
                    "Запишутся в СВОДНУЮ после закрытия месяца."
                )
            else:
                text = (
                    "📊 РОП обновлён (1С + касса)\n"
                    f"💰 Оборот (Продажи): {oborot} ₽\n"
                    f"💳 Поступления (касса): {postup} ₽\n\n"
                    "📈 % выполнения плана (РОП):\n"
                    f"  • Новые продажи: {rep['pct_new']}\n"
                    f"  • Оборот: {rep['pct_oborot']}\n"
                    f"  • Поступления: {rep['pct_postup']}\n\n"
                    f"🔗 Таблица: {rep['url']}"
                )
            await context.bot.send_message(chat_id=int(ANNA_CHAT_ID), text=text)
    except Exception as e:
        logger.exception("Oborot update failed")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"❌ Ошибка обновления оборота: {str(e)}"
            )


async def auto_novye_prodazhi(context: ContextTypes.DEFAULT_TYPE):
    """Каждый день 11:00 МСК: обновить новые продажи из KPI-таблицы +
    автозавести новых клиентов в СПРАВОЧНИК, прислать Анне отчёт с расхождениями.

    Было по понедельникам, стало ежедневно (2026-08-07): отключён GAS-триггер
    syncNewClientsFromKPI, который делал то же самое ночью в 03:00 и писал в лист
    битые формулы. Чтобы не спамить, полный отчёт уходит по понедельникам, в
    остальные дни — только если есть заведённые клиенты или расхождения."""
    is_monday = datetime.now(MSK).weekday() == 0
    logger.info("Starting novye-prodazhi sync (monday=%s)", is_monday)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        rep = await loop.run_in_executor(None, sync_novye)
        logger.info("Novye sync: rows=%d added=%d disc=%d",
                    rep["novye_rows"], len(rep["added"]), len(rep["discrepancies"]))
        # В будни без новостей молчим — синк идёт каждый день, отчёт нужен
        # по понедельникам либо когда реально есть что показать.
        has_news = bool(rep["added"] or rep["discrepancies"])
        if ANNA_CHAT_ID and (is_monday or has_news):
            total = f"{rep['novye_total']:,.0f}".replace(",", " ")
            lines = [
                f"🗓 Новые продажи обновлены (KPI «{rep['kpi_sheet']}»)",
                f"📋 НОВЫЕ_КЛИЕНТЫ: {rep['novye_rows']} строк, сумма {total} ₽",
            ]
            if rep["added"]:
                lines.append(f"\n➕ Заведено в справочник ({len(rep['added'])}):")
                for name, B, C in rep["added"]:
                    lines.append(f"  • {name[:34]} → {C or B}")
            if rep["no_data"]:
                nd = ", ".join(n[:22] for n in rep["no_data"])
                lines.append(f"\nℹ️ Пока нет в 1С-данных (заработают позже): {nd}")
            if rep["discrepancies"]:
                lines.append("\n🔔 Вернулись, ответственный расходится — напиши верного:")
                for cl, kpi, cur in rep["discrepancies"]:
                    lines.append(f"  • {cl}: KPI={kpi}, в СПР {cur}")
            await context.bot.send_message(chat_id=int(ANNA_CHAT_ID), text="\n".join(lines))
    except Exception as e:
        logger.exception("Novye-prodazhi sync failed")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"❌ Ошибка синка новых продаж: {str(e)}"
            )


async def auto_watch_otvetstvennye(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневно в 10:40 МСК: сверить поле «Ответственный» в карточках 1С со вчерашним
    снимком и написать Анне, если кого-то переназначили. Если изменений нет — молчим.

    Зачем: её ручные выгрузки из 1С строятся по этому полю, и смена ответственного
    незаметно убирает деньги клиента из выгрузки (так было с Pepe Nero)."""
    logger.info("Starting otvetstvennye watch")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, watch_otvetstvennye.check)
        if report and ANNA_CHAT_ID:
            await context.bot.send_message(chat_id=int(ANNA_CHAT_ID), text=report)
        logger.info("Otvetstvennye watch done, changes=%s", bool(report))
    except Exception as e:
        logger.exception("Otvetstvennye watch failed")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"❌ Ошибка слежения за ответственными: {str(e)}"
            )


async def check_missing_reports(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(MSK)
    if now.weekday() >= 5:  # суббота(5)/воскресенье(6) — выходные, не напоминаем
        logger.info("check_missing_reports: выходной (weekday=%d) — пропуск", now.weekday())
        return
    today = now.day
    missing = sheets.get_employees_without_report(today)
    missing = [name for name in missing if 'анн' not in name.lower()]

    if not missing:
        logger.info("All employees submitted reports for day %d", today)
        return

    names_str = '\n'.join(f"• {name}" for name in missing)
    text = f"⚠️ Не сдали отчёт за сегодня:\n{names_str}"

    if GROUP_CHAT_ID:
        await context.bot.send_message(chat_id=int(GROUP_CHAT_ID), text=text)
    if ANNA_CHAT_ID:
        await context.bot.send_message(chat_id=int(ANNA_CHAT_ID), text=text)
    logger.info("Missing report alert sent for day %d: %s", today, missing)


# ─── offset tracking ──────────────────────────────────────────────────────────

async def _track_offset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.update_id:
        _save_last_offset(update.update_id)


async def _on_startup(app: Application) -> None:
    offset = _load_last_offset()
    if not offset:
        return
    try:
        updates = await app.bot.get_updates(offset=offset + 1, limit=100, timeout=0)
    except Exception:
        logger.exception("Failed to fetch missed updates on startup")
        return
    if not updates:
        logger.info("No missed updates since update_id %d", offset)
        return
    logger.info("Recovering %d missed updates since update_id %d", len(updates), offset)
    for upd in updates:
        await app.process_update(upd)


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(_on_startup).build()
    app.add_handler(CommandHandler('start', handle_start))
    app.add_handler(CommandHandler('sync_1c', handle_sync_1c))
    app.add_handler(CommandHandler('avansy', handle_avansy))
    app.add_handler(CommandHandler('avans', handle_avans))
    app.add_handler(CommandHandler('zarplata', handle_zarplata))
    app.add_handler(CommandHandler('zp', handle_zarplata))
    app.add_handler(CommandHandler('chatid', handle_chatid))
    app.add_handler(CommandHandler('beby', handle_beby))
    app.add_handler(CommandHandler('cancel_avans', handle_cancel_avans))
    app.add_handler(CallbackQueryHandler(_cash_callback, pattern=r'^cash:'))
    app.add_handler(CallbackQueryHandler(_zp_callback, pattern=r'^zp:'))
    app.add_handler(CallbackQueryHandler(_beby_callback, pattern=r'^beby:'))
    # PDF-накладная беби-листов — до общего обработчика: у файла нет текста,
    # handle_message такое сообщение просто отбрасывает
    # ★и по mime, и по расширению: у пересланного файла mime часто
    # application/octet-stream, и фильтр по одному mime его пропускал
    app.add_handler(MessageHandler(
        filters.Document.PDF | filters.Document.FileExtension('pdf'),
        handle_beby_invoice))
    # списания беби-листов текстом («мизуна зеленая 5 сегодня, микс 1») — до
    # общего обработчика, но только в личке Анны и только со словом «списа…»
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE
        & filters.Regex(r'(?i)списа'),
        handle_beby_writeoff))
    app.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.PHOTO | filters.Document.ALL,
        handle_message,
    ))
    # Runs after all other handlers — saves the last processed update_id
    app.add_handler(TypeHandler(Update, _track_offset), group=999)

    app.job_queue.run_daily(auto_anna_shift, time=dtime(11, 0, 0, tzinfo=MSK))
    app.job_queue.run_daily(check_missing_reports, time=dtime(21, 0, 0, tzinfo=MSK))
    app.job_queue.run_daily(auto_sync_1c, time=dtime(10, 30, 0, tzinfo=MSK))
    app.job_queue.run_daily(auto_oborot, time=dtime(10, 35, 0, tzinfo=MSK))
    app.job_queue.run_daily(auto_watch_otvetstvennye, time=dtime(10, 40, 0, tzinfo=MSK))
    app.job_queue.run_daily(auto_novye_prodazhi, time=dtime(11, 0, 0, tzinfo=MSK))
    # Выплаты официальным: активен только в дни 24-25 (аванс) и 9-10 (ЗП) —
    # проверка дня внутри auto_avansy. В окне 10:00-12:00 бухгалтерия и проводит
    # платежи, поэтому там опрос каждые 20 минут; дальше ежечасно до 15:00.
    for _hh, _mm in [(h, m) for h in (10, 11) for m in (0, 20, 40)] + [(12, 0)]:
        app.job_queue.run_daily(auto_avansy, time=dtime(_hh, _mm, 0, tzinfo=MSK))
    for _hh in range(13, 16):
        app.job_queue.run_daily(auto_avansy, time=dtime(_hh, 0, 0, tzinfo=MSK))

    # пакет расчётов ЗП: 5 числа и 10-го после появления официальной зарплаты.
    # Ежечасно (проверка дня и отметки «уже слали» — внутри auto_zp_monthly);
    # :25 — чтобы опрос выплат в HH:20 успел проставить колонку «ЗП 9 — на карту».
    for _hh in range(10, 19):
        app.job_queue.run_daily(auto_zp_monthly, time=dtime(_hh, 25, 0, tzinfo=MSK))

    logger.info("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
