"""Клиент «Кассы GREENCH» — источник операций вместо ADesk.

С 28.08.2026 ADesk закрыл API (подписку не продлили), у компании свой сервис:
POST /api/kassa-ops с телом {admin_token, period:"all", month:"ГГГГ-ММ", limit, offset},
ответ — {ok, rows, total, sum_in, sum_out}. Страница максимум 500 строк.

Наружу операции отдаются В ФОРМЕ ADesk (type/amount/dateIso/description/
contractor.name/isTransfer/category.name) — на неё завязаны sync_avansy и sync_kassa,
их логику разбора менять не пришлось.

Ключи в .env: KASSA_URL (по умолчанию боевой адрес) и KASSA_TOKEN.
"""

import logging
import os

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://greenchzelen.online:8443"
PAGE = 500


def _url():
    return (os.environ.get("KASSA_URL") or DEFAULT_URL).rstrip("/")


def _token(token=None):
    token = token or os.environ.get("KASSA_TOKEN")
    if not token:
        raise RuntimeError("KASSA_TOKEN не задан в окружении")
    return token


def _post(path, token=None, **body):
    resp = requests.post(f"{_url()}/api/{path}", timeout=120,
                         json=dict(admin_token=_token(token), **body))
    resp.raise_for_status()
    data = resp.json()
    if data.get("ok") is False:
        raise RuntimeError(f"Касса: {data.get('error')}")
    return data


def _as_adesk(r):
    """Операция кассы в форме ADesk."""
    contractor = r.get("contractor")
    return {
        "type": r.get("kind"),                 # 1 — приход, 2 — расход, как в ADesk
        "amount": r.get("amount"),
        "dateIso": (r.get("op_date") or "")[:10],
        "description": r.get("description") or "",
        "contractor": {"name": contractor} if contractor else None,
        "isTransfer": bool(r.get("is_transfer")),
        "category": {"name": r.get("category")} if r.get("category") else None,
        "id": r.get("id"),
        "source": r.get("source"),
    }


def month_operations(ym, token=None):
    """Все операции месяца ym («2026-08») в форме ADesk."""
    rows = []
    while True:
        data = _post("kassa-ops", token, period="all", month=ym,
                     limit=PAGE, offset=len(rows))
        rows += data.get("rows", [])
        if not data.get("rows") or len(rows) >= data.get("total", 0):
            break
    logger.info("Касса: за %s получено %d операций", ym, len(rows))
    return [_as_adesk(r) for r in rows]


def month_income(ym, token=None):
    """Поступления за месяц — приходы без переводов между своими счетами.

    Касса считает это сама и кладёт в sum_in, поэтому хватает одного лёгкого
    запроса: sum_in относится ко всему месяцу, а не к странице.
    """
    data = _post("kassa-ops", token, period="all", month=ym, limit=1, offset=0)
    return round(float(data.get("sum_in") or 0), 2)
