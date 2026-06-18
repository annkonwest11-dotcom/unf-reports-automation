import json
import logging
import os
import re
from datetime import time as dtime, timezone, timedelta, datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters

from parser import parse_report
from sheets import SheetsClient
from sync_42clouds_v2 import sync_all_bases

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
CALLS_NORM = 20

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

_awaiting_name: set[int] = set()
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
    """True if at least one significant word from registered name is in reported name."""
    words = [w for w in registered.lower().split() if len(w) > 3 and w.isalpha()]
    rep = reported.lower()
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

async def handle_sync_1c(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Синхронизировать данные из 1С в Google Sheets"""
    if not _is_from_anna(update):
        await update.message.reply_text("⛔ Эта команда только для Анны")
        return

    await update.message.reply_text("🔄 Начинаю синхронизацию из 1С...")

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sync_all_bases)
        await update.message.reply_text("✅ Синхронизация завершена успешно")
    except Exception as e:
        logger.exception("Failed to sync 1C data")
        await update.message.reply_text(f"❌ Ошибка синхронизации: {str(e)}")


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
        if re.search(r'^смена', first) and chat.type in ('group', 'supergroup') and user and ANNA_CHAT_ID:
            employees = _load_employees()
            registered_name = employees.get(str(user.id))
            sender = registered_name or (user.full_name or str(user.id))
            logger.warning("Failed to parse report from %s: %r", sender, text[:80])
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

    try:
        ok = sheets.update_report(report)
        if ok:
            logger.info("Report saved | chat=%s employee=%s", chat.id, report.employee)
            await _check_calls_norm(report, context)
            await _check_early_report(report, context)
            await _check_wrong_date(report, context)
        else:
            logger.warning("Report not matched | chat=%s employee=%s date=%s", chat.id, report.employee, report.date)
    except Exception:
        logger.exception("Failed to update Google Sheets")


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
            f"Листы СВОДНАЯ\\_ЗП и СМЕНЫ сохранены с форматированием.\n"
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
    ok = sheets.write_shift('Анна Кономенко (РОП)', day)
    logger.info("Anna auto-shift day=%d ok=%s", day, ok)


async def auto_sync_1c(context: ContextTypes.DEFAULT_TYPE):
    """Автоматическая синхронизация данных из 1С"""
    logger.info("Starting auto sync from 1C")
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sync_all_bases)
        logger.info("Auto sync completed successfully")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text="✅ Автосинхронизация из 1С завершена"
            )
    except Exception as e:
        logger.exception("Auto sync failed")
        if ANNA_CHAT_ID:
            await context.bot.send_message(
                chat_id=int(ANNA_CHAT_ID),
                text=f"❌ Ошибка автосинхронизации: {str(e)}"
            )


async def check_missing_reports(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(MSK).day
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
    app.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.PHOTO | filters.Document.ALL,
        handle_message,
    ))
    # Runs after all other handlers — saves the last processed update_id
    app.add_handler(TypeHandler(Update, _track_offset), group=999)

    app.job_queue.run_daily(auto_anna_shift, time=dtime(11, 0, 0, tzinfo=MSK))
    app.job_queue.run_daily(check_missing_reports, time=dtime(21, 0, 0, tzinfo=MSK))
    app.job_queue.run_daily(auto_sync_1c, time=dtime(7, 0, 0, tzinfo=MSK))

    logger.info("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
