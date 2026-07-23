"""Поступления из ADesk → СВОДНАЯ_ЗП!E92 (Блок 4 РОП).

Считает «Движение средств → Поступления» за текущий месяц: операции-приходы
(type==1) БЕЗ переводов между своими счетами (isTransfer). Сходится с отчётом ДДС
«Поступления» в ADesk (сверено с Анной 2026-07-23 = 6 591 531,29 за июль).

Токен — в переменной окружения ADESK_TOKEN (.env). Дата-фильтра у /transactions
нет (dateFrom/dateTo игнорируются), поэтому тянем все операции и фильтруем по
dateIso на своей стороне — это один запрос в день.
"""

import logging
import os
from datetime import datetime

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

ADESK_URL = "https://api.adesk.ru/v1/transactions"
ADESK_TOKEN = os.environ.get("ADESK_TOKEN")
POSTUP_CELL = "E92"          # Блок 4 РОП «Факт — поступления (всего, АДЕСК)»
_TYPE_INCOME = 1             # 1 = приход/поступление, 2 = расход


def fetch_postupleniya(today=None):
    """Сумма поступлений (приход без переводов) за текущий месяц из ADesk."""
    token = ADESK_TOKEN or os.environ.get("ADESK_TOKEN")
    if not token:
        raise RuntimeError("ADESK_TOKEN не задан в окружении")
    ym = (today or datetime.now()).strftime("%Y-%m")
    resp = requests.get(ADESK_URL, params={"api_token": token, "length": 1000000},
                        timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", True):
        raise RuntimeError(f"ADesk API: {data}")
    total = 0.0
    n = 0
    for t in data.get("transactions", []):
        if t.get("type") != _TYPE_INCOME:
            continue
        if t.get("isTransfer"):
            continue
        if not (t.get("dateIso") or "").startswith(ym):
            continue
        total += float(t.get("amount", 0) or 0)
        n += 1
    logger.info("ADesk поступления за %s: %d операций, сумма %.2f", ym, n, total)
    return round(total, 2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Поступления (тек. месяц): {fetch_postupleniya():,.2f}")
