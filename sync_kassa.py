"""Поступления из «Кассы GREENCH» → СВОДНАЯ_ЗП!E91 (Блок 4 РОП).

Считает «Движение средств → Поступления» за текущий месяц: приходы БЕЗ переводов
между своими счетами. Касса считает это сама и отдаёт готовой суммой `sum_in`,
поэтому хватает одного лёгкого запроса.

До 28.08.2026 источником был ADesk (файл назывался sync_adesk.py); он закрыл API —
подписку не продлили. Сходимость проверена на июле: касса даёт ту же сумму, что
отчёт ДДС ADesk (6 591 531,29 — сверено с Анной 2026-07-23).

Ключи — KASSA_URL и KASSA_TOKEN в .env.
"""

import logging
from datetime import datetime

import kassa_api

logger = logging.getLogger(__name__)

POSTUP_CELL = "E91"          # Блок 4 РОП «Факт — поступления (всего)»


def fetch_postupleniya(today=None):
    """Сумма поступлений (приход без переводов) за текущий месяц из кассы."""
    ym = (today or datetime.now()).strftime("%Y-%m")
    total = kassa_api.month_income(ym)
    logger.info("Касса, поступления за %s: %.2f", ym, total)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Поступления (тек. месяц): {fetch_postupleniya():,.2f}")
