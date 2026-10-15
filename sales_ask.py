"""Вопросы Анне в MAX по отчёту по продажам — кнопками, ответы читаем из её лички.

Правило 6 ТЗ (Анна, 12.10.2026): всё, в чём отчёт не уверен, уходит ей **в MAX в
личку**, а не в Telegram и не в группу. Спрашиваем ровно о трёх вещах, которые
1С решить не может (см. `docs/ОТЧЕТ_ПРОДАЖ.md`):

  • клиент выглядит новым по 1С, а бланка «ПЕРВЫЙ ЗАКАЗ» на него нет (правило 1);
  • клиент похож на возврат: молчал дольше своего ритма, бланка нет (правило 2);
  • клиент взял за месяц ровно один раз — «разовый?» (правило 3).

**Кнопки типа «message», а не callback.** Нажатие уходит обычным сообщением в тот
же чат, и его видит следующий прогон — работающий процесс-обработчик не нужен
(поток событий бота MAX целиком вычитывает бот расходов, второй слушатель отнял бы
у него события). Поэтому текст кнопки несёт и вердикт, и имя клиента:

    вношу · РУБЕЛЬ (ООО АВА ЦЕНТР)
    не вношу · РУБЕЛЬ (ООО АВА ЦЕНТР)
    разовый · РУБЕЛЬ (ООО АВА ЦЕНТР)

Что сделано с ответом, помним в `sales_asked.json`: иначе один и тот же вопрос
уходил бы каждый прогон, а «не вношу» забывалось бы к следующему месяцу.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta

import requests

try:  # запуск и как модуль отчёта, и как standalone-скрипт
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

BASE = "https://platform-api.max.ru"
MSK = timezone(timedelta(hours=3))
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sales_asked.json")

# сколько вопросов за один прогон: больше — это уже не вопросы, а спам в личку
LIMIT = 12

VERDICTS = {"вношу": "вносить", "не вношу": "не вносить", "разовый": "разовый"}
SEP = " · "

# два вида вопросов: вносить ли клиента вообще и в чью колонку его сумма
ASK_ADD, ASK_WHO = "вносить", "колонка"

KIND_WORDS = {"новый": "первый заказ по 1С, бланка нет",
              "кандидат": "похож на возврат, бланка нет",
              "вернули": "возврат по бланку менеджера",
              "разовый": "взял один раз за месяц"}

# ★15.10.2026 (Савва): бланк менеджера есть, а по 1С разрыв меньше RETURN_GAP —
# события нет, значит нет и строки расчёта, к которой бланк можно привязать.
# Решение Анны: «писать мне в таком случае» — такую строку не вносим молча,
# а спрашиваем кнопками, как любого кандидата
BLANK_NO_EVENT = "бланк без события"


def _token():
    return os.environ.get("MAX_TOKEN") or ""


def _anna_user_id():
    v = os.environ.get("MAX_ANNA_USER_ID")
    return int(v) if v else None


def _anna_chat_id():
    v = os.environ.get("MAX_ANNA_CHAT_ID")
    return int(v) if v else None


def configured() -> bool:
    """Без токена и адреса личка недоступна — тогда прогон просто пишет сводку."""
    return bool(_token() and _anna_user_id())


# ── состояние ────────────────────────────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"asked": {}, "answers": {}}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("не прочитала %s (%s) — считаю, что ничего не спрашивала", STATE_FILE, e)
        return {"asked": {}, "answers": {}}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except OSError as e:
        logger.warning("не сохранила %s: %s", STATE_FILE, e)


# ── MAX ──────────────────────────────────────────────────────────────────────

def send_question(text: str, options: list[str], user_id=None) -> str:
    """Вопрос с кнопками в личку. Возвращает mid сообщения (для журнала)."""
    body = {"text": text, "notify": True,
            "attachments": [{"type": "inline_keyboard", "payload": {"buttons": [
                [{"type": "message", "text": o[:64]}] for o in options]}}]}
    r = requests.post(f"{BASE}/messages", params={"user_id": user_id or _anna_user_id()},
                      json=body, timeout=30,
                      headers={"Authorization": _token(), "Content-Type": "application/json"})
    r.raise_for_status()
    return ((r.json().get("message") or {}).get("body") or {}).get("mid", "")


def fetch_messages(chat_id=None, pages: int = 2) -> list[dict]:
    """История личного чата, от старых к новым.

    Фильтры from/to у MAX не работают так, как ожидаешь, поэтому листаем назад
    через `to` — как в отчёте по обрезаниям.
    """
    chat_id = chat_id or _anna_chat_id()
    if not chat_id:
        logger.info("MAX_ANNA_CHAT_ID не задан — ответы кнопками читать негде")
        return []
    seen, to = {}, None
    for _ in range(pages):
        params = {"chat_id": chat_id, "count": 100}
        if to:
            params["to"] = to
        r = requests.get(f"{BASE}/messages", params=params, timeout=40,
                         headers={"Authorization": _token()})
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        if not msgs:
            break
        fresh = 0
        for m in msgs:
            key = (m.get("body") or {}).get("mid") or str(m["timestamp"])
            if key not in seen:
                seen[key] = m
                fresh += 1
        oldest = min(m["timestamp"] for m in msgs)
        if not fresh or (to and oldest >= to):
            break
        to = oldest - 1
        time.sleep(0.3)
    return sorted(seen.values(), key=lambda m: m["timestamp"])


# ── вопросы и ответы ─────────────────────────────────────────────────────────

def question_text(r) -> tuple[str, list[str]]:
    """«Вносить ли клиента?» — текст и кнопки по одной строке расчёта."""
    why = KIND_WORDS.get(r["kind"], r["kind"])
    lines = [f"❓ {r['client']}", f"{why}: {r['event']:%d.%m}, {_money(r['amount'])} ₽"]
    if r.get("source") == BLANK_NO_EVENT:
        # без этой строки вопрос не отличить от догадки по 1С, а разница важная:
        # менеджер клиента уже назвал, спрашиваем только из-за ритма
        lines.append("бланк менеджера есть, а по 1С это обычный ритм")
        if r.get("blank_author"):
            lines.append(f"бланк прислал: {r['blank_author'][:40]}")
    if r.get("gap"):
        ритм = f" при обычном ритме {r['rhythm']:g} дн." if r.get("rhythm") else ""
        lines.append(f"молчал {r['gap']} дн.{ритм}")
    if r.get("orders") == 1:
        # правило 3: разовый — подвид и нового, и вернувшегося, и виден он по
        # одному заказу за месяц. Отдельным вопросом не спрашиваем — кнопка тут же
        lines.append("за месяц взял ОДИН раз")
    if r.get("beby_cut"):
        lines.append(f"в сумме уже вычтено 40% за салаты ({_money(r['beby_cut'])} ₽)")
    lines.append(f"окно считаю по {r['window_end']:%d.%m}")
    name = r["client"][:44]
    options = [f"вношу{SEP}{name}", f"не вношу{SEP}{name}", f"разовый{SEP}{name}"]
    return "\n".join(lines), options


def manager_question(r, managers, row=None) -> tuple[str, list[str]]:
    """«Чей это клиент?» — сумма посчитана, а колонка неизвестна.

    Так закрывается блок сводки «ПОСЧИТАЛ, НО НЕ ЗНАЮ, В ЧЬЮ КОЛОНКУ»: 12.10 таких
    строк было 30, и вручную их разбирала Анна. Прочерк в строке отвечает на это
    сам (правило 12), спрашиваем только когда и прочерка нет.
    """
    где = f" (строка {row})" if row else ""
    lines = [f"❓ {r['client']}{где}",
             f"{'первый заказ' if r['kind'] == 'новый' else 'вернули'} {r['event']:%d.%m}, "
             f"{_money(r['amount'])} ₽ — в чью колонку?"]
    name = r["client"][:44]
    options = [f"{m.split()[0]}{SEP}{name}" for m in managers] + [f"не вношу{SEP}{name}"]
    return "\n".join(lines), options


def _money(x):
    return f"{x:,.0f}".replace(",", " ")


def parse_answers(messages: list[dict], known=None) -> dict:
    """Нажатия кнопок из истории чата → {имя клиента: ответ}.

    Ответ — либо вердикт («вносить» / «не вносить» / «разовый»), либо имя
    менеджера, как оно написано на кнопке («Дарья»): его разбирает уже отчёт
    (`manager_from_note`), там же лежат все написания имён.
    Берём ПОСЛЕДНЕЕ нажатие по клиенту: Анна может передумать и нажать снова.

    ★★13.10.2026 — ГЛАВНАЯ ЗАСАДА: разделитель « · » стоит и в обычных отчётах,
    которые бот сам же присылает Анне в личку («15 750 ₽ · Закупка у конкурентов —
    что купили?»). По первой версии парсера таких «ответов» насчиталось 33, и любой
    из них мог молча исключить клиента из отчёта. Поэтому ответом считаем сообщение,
    которое прошло ВСЕ проверки:
      • писала Анна, а не бот (`sender.is_bot`, `sender.user_id`);
      • это ровно текст кнопки: одна строка не длиннее 70 символов;
      • клиент — из тех, про кого мы спрашивали (`known`).
    """
    out = {}
    anna = _anna_user_id()
    for m in messages:
        sender = m.get("sender") or {}
        if sender.get("is_bot") or (anna and sender.get("user_id") not in (anna, None)):
            continue
        text = ((m.get("body") or {}).get("text") or "").strip()
        if SEP not in text or "\n" in text or len(text) > 70:
            continue
        head, name = (p.strip() for p in text.split(SEP, 1))
        if not name or not head:
            continue
        if known is not None and not _known(name, known):
            logger.info("сообщение «%s» похоже на нажатие, но про него не спрашивала", text)
            continue
        out[name] = VERDICTS.get(head.lower(), head)
    return out


def _known(name, known) -> bool:
    """Про этого клиента вопрос задавался? (имя на кнопке обрезано до 44 символов)"""
    flat = _flat(name)
    return any(flat.startswith(k) or k.startswith(flat) for k in known if k)


def asked_clients(state: dict) -> set:
    """Клиенты, про которых уже спрашивали — по ним и принимаем ответы."""
    return {_flat(a.get("client", "")) for a in (state.get("asked") or {}).values()}


def read_answers(state=None, pages: int = 2) -> dict:
    """Ответы Анны из её личного чата. Пусто — значит ещё не нажимала."""
    if not configured():
        return {}
    known = asked_clients(state) if state is not None else None
    try:
        answers = parse_answers(fetch_messages(pages=pages), known=known)
    except Exception as e:                                   # noqa: BLE001
        # MAX недоступен — это не повод валить весь прогон: отчёт просто спросит снова
        logger.warning("не прочитала ответы из MAX (%s)", e)
        return {}
    logger.info("ответов кнопками в личке: %s", len(answers))
    return answers


def match_answer(client: str, answers: dict) -> str | None:
    """Вердикт по клиенту: имя в кнопке обрезано до 44 символов, поэтому по префиксу."""
    flat = _flat(client)
    for name, verdict in answers.items():
        key = _flat(name)
        if key and (flat.startswith(key) or key.startswith(flat)):
            return verdict
    return None


def answers_this(kind: str, verdict: str | None) -> bool:
    """Закрывает ли уже полученный вердикт именно ЭТОТ вопрос.

    ★13.10.2026: «вношу / не вношу / разовый» отвечают на вопрос «вносить ли
    клиента», но НЕ говорят, чей он. На этом ТЭМУ застрял без колонки: Анна
    нажала «вношу», строка встала в лист, а вопрос «в чью колонку сумма» бот
    больше не задавал — сумма так и висела за колонкой ИТОГ, то есть вне итога
    листа и вне борда РОПа. Вопрос про колонку закрывают только имя менеджера
    (его сумма туда и пойдёт) и «не вношу» (клиент уезжает в ИСКЛЮЧЕНИЯ).
    """
    if not verdict:
        return False
    if kind != ASK_WHO:
        return True
    if verdict == "не вносить":
        return True
    from sales_report import manager_from_note      # цикл импорта: только внутри
    return bool(manager_from_note(verdict))


def _flat(s):
    return re.sub(r"[^\w]", "", str(s or "").lower().replace("ё", "е"))


def ask_rows(rows, answers, state, dry_run=False, limit=LIMIT, now=None,
             kind=ASK_ADD, managers=(), rows_in_sheet=None):
    """Разослать вопросы, о которых ещё не спрашивали. → сколько ушло.

    `kind=ASK_ADD` — «вносить ли клиента», `ASK_WHO` — «в чью колонку сумма»
    (тогда нужен список менеджеров листа). Про одного клиента один вопрос каждого
    вида: что спросили, помним в состоянии, иначе вопрос уходил бы каждый прогон.
    """
    if not configured():
        logger.info("MAX не настроен (MAX_TOKEN / MAX_ANNA_USER_ID) — вопросы не отправляю")
        return 0
    now = now or datetime.now(MSK)
    rows_in_sheet = rows_in_sheet or {}
    sent = 0
    for r in rows:
        if sent >= limit:
            logger.info("предел вопросов за прогон (%s) — остальных спрошу в следующий раз", limit)
            break
        key = f"{kind}:{_flat(r['client'])}"
        if key in state["asked"] or answers_this(kind, match_answer(r["client"], answers)):
            continue
        if kind == ASK_WHO:
            text, options = manager_question(r, managers, rows_in_sheet.get(r["client"]))
        else:
            text, options = question_text(r)
        if dry_run:
            print(f"\n[в личку Анне]\n{text}\nкнопки: {options}")
            sent += 1
            continue
        try:
            mid = send_question(text, options)
        except Exception as e:                               # noqa: BLE001
            logger.warning("вопрос про «%s» не ушёл в MAX: %s", r["client"], e)
            continue
        state["asked"][key] = {"client": r["client"], "kind": r["kind"], "ask": kind,
                               "amount": r["amount"], "mid": mid,
                               "asked_at": now.isoformat(timespec="seconds")}
        sent += 1
        time.sleep(0.4)             # MAX не любит очередь сообщений без паузы
    return sent
