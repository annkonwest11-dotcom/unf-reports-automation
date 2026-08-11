"""Логика наличного аванса (колонка D таблицы выплат СВОДНАЯ_ЗП).

Телеграм-диалог живёт в bot.py; здесь — чистая логика без сети:
план опроса, расчёт предлагаемой суммы, парсинг ответа Анны, сводка.

Правила (Анна, 2026-07-24): наличные без копеек (отбрасываем дробь).
  • Ксения — чтобы аванс ВСЕГО (офиц.+нал) вышел 20 000  → нал = 20000 − офиц.
  • Алёна  — чтобы всего 15 000                         → нал = 15000 − офиц.
  • Дарья  — только официальный, наличных нет (D пусто)
  • Влада  — спрашиваем сумму (без дефолта)
  • Анна   — 15 000 (подтверждаем каждый раз)
  • Ия     — 10 200 (разово; строку убрать после закрытия месяца)
"""

import math

# Порядок опроса. Каждый пункт: (row, короткое имя, rule).
# rule: ("total", N) нал = N − офиц.(без копеек);  ("fixed", N) дефолт N;
#       ("ask", None) без дефолта — спросить.
# Дарья здесь НЕ фигурирует — у неё наличных нет (обрабатываем отдельно).
CASH_PLAN = [
    (114, "Ксения",  ("total", 20000)),
    (115, "Алёна",   ("total", 15000)),
    (116, "Влада",   ("ask",   None)),
    (117, "Анна",    ("fixed", 15000)),
]

# Строки, у которых наличный аванс принудительно 0/пусто (не спрашиваем).
NO_CASH_ROWS = {113: "Дарья"}

COL_CASH = "D"        # Аванс 25 — наличными
COL_OFFICIAL = "C"    # Аванс 24 — на карту (офиц.)


def compute_default(rule, official_c):
    """Предлагаемая сумма наличных по правилу. None — если дефолта нет (ask)."""
    kind, val = rule
    if kind == "ask":
        return None
    if kind == "fixed":
        return int(val)
    if kind == "total":
        # официальный аванс берём БЕЗ копеек, наличными добиваем до ровного итого:
        # напр. офиц 12253,78 → 12253, нал = 15000 − 12253 = 2747, итого ровно 15000
        c = math.floor(float(official_c or 0))
        return max(0, int(val) - c)
    raise ValueError(f"Неизвестное правило: {rule!r}")


def parse_amount(text):
    """Ответ Анны → сумма (int) или None (не распознано).
    «0», «нет», «-», «без» → 0."""
    if text is None:
        return None
    t = str(text).strip().lower()
    if t in ("0", "-", "нет", "без", "без наличных", "ноль"):
        return 0
    # оставляем цифры, точку/запятую как разделитель дроби
    cleaned = (t.replace(" ", "").replace(" ", "")
               .replace("руб", "").replace("р.", "").replace("₽", "")
               .replace("р", "").replace(",", "."))
    try:
        return max(0, math.floor(float(cleaned)))
    except (TypeError, ValueError):
        return None


def _fmt(x):
    """Число → строка без лишних копеек: 12253.78→'12 253,78', 7746→'7 746'."""
    x = float(x or 0)
    if abs(x - round(x)) < 0.005:
        s = f"{int(round(x)):,}".replace(",", " ")
    else:
        s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return s


def _cell(x):
    """Число для таблицы: 0/пусто → «—», иначе форматированное."""
    x = float(x or 0)
    return _fmt(x) if abs(x) > 0.005 else "—"


def build_summary(rows, month_label="", show_zp=False):
    """rows: список (name, zp_b, official_c, cash_d) в порядке таблицы выплат.
    Возвращает HTML-текст (моноширинная таблица в <pre>): по каждому
    офиц.аванс / наличный (+ЗП, если show_zp), строка ИТОГО и итог наличными.
    Колонка ЗП скрыта для авансов; включается для зарплатного цикла (show_zp=True)."""
    NW, W = 22, 9  # ширина колонки имени и числовых колонок
    head = f"📋 Авансы{(' — ' + month_label) if month_label else ''}"

    def short(name):
        # убрать хвост в скобках («(РОП)», «(разово)») — чтобы имя влезало
        return name.split(" (")[0].strip()

    def line(n, cells):
        return f"{n[:NW]:<{NW}}" + "".join(f"{c:>{W}}" for c in cells)

    header = (["ЗП", "Офиц", "Нал"] if show_zp else ["Офиц", "Нал"])
    body = [line("Сотрудник", header)]
    tz = tc = td = 0.0
    for name, zp, c, d in rows:
        zp = float(zp or 0); c = float(c or 0); d = float(d or 0)
        tz += zp; tc += c; td += d
        vals = ([_cell(zp), _cell(c), _cell(d)] if show_zp
                else [_cell(c), _cell(d)])
        body.append(line(short(name), vals))
    body.append("─" * (NW + len(header) * W))
    totals = ([_cell(tz), _cell(tc), _cell(td)] if show_zp
              else [_cell(tc), _cell(td)])
    body.append(line("ИТОГО", totals))

    table = "<pre>" + "\n".join(body) + "</pre>"
    return f"{head}\n{table}\n💰 К выплате наличными: <b>{_fmt(td)} ₽</b>"
