import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Report:
    employee: str = ""
    date: str = ""
    tasks: str = ""
    manager_type: str = ""   # "сопровождение" | "поиск" | "влада" | ""
    day_type: str = ""       # "будний" | "выходной"
    phones: str = ""         # "1" | "2"
    firms: str = ""          # "да" | "нет"
    calls_total: str = ""
    calls_under_1min: str = ""
    calls_1_2min: str = ""
    calls_2_5min: str = ""
    calls_over_5min: str = ""
    orders: str = ""          # "да"/"нет" — шаблон Влады «Заказы (да/нет)»
    orders_weekend: str = ""  # сопровождение: «Заказы выходные», телефонов "1"/"2"
    orders_weekday: str = ""  # сопровождение: «Заказы будние», доп телефон "да"/"нет"
    # Old-format fields (backward compat)
    shift_type: str = ""
    side_job_type: str = ""


_NEW_FIELDS = [
    (r'выполненные\s*задачи',      'tasks'),
    (r'звонки\s*всего',            'calls_total'),
    (r'звонки\s*<\s*1',            'calls_under_1min'),
    (r'звонки\s*1\s*[-–]\s*2',     'calls_1_2min'),
    (r'звонки\s*2\s*[-–]\s*5',     'calls_2_5min'),
    (r'звонки\s*>\s*5',            'calls_over_5min'),
    (r'заказ.*вых',                'orders_weekend'),   # сопров.: телефонов 1/2 | Влада: «Заказы выхи» да/нет
    (r'заказ.*будн',               'orders_weekday'),   # сопров.: доп телефон да/нет | Влада: «Заказы будни» да/нет
    (r'телефон',                   'phones'),
    (r'фирм',                      'firms'),
    (r'тип',                       'day_type'),
    (r'заказ',                     'orders'),           # Влада: «Заказы (да/нет)»
    (r'сотрудник',                 'employee'),
    (r'дата',                      'date'),
]

_OLD_FIELDS = [
    (r'выполненные\s*задачи',       'tasks'),
    (r'сколько\s*звонков',          'calls_total'),
    (r'менее\s*1\s*мин',            'calls_under_1min'),
    (r'больше\s*5\s*мин',           'calls_over_5min'),
    (r'больше\s*2\s*мин',           'calls_2_5min'),
    (r'больше\s*1\s*мин',           'calls_1_2min'),
    (r'вид\s*(подработки|работы)',  'side_job_type'),
    (r'тип\s*смены',                'shift_type'),
    (r'сотрудник',                  'employee'),
    (r'дата',                       'date'),
]

_SECTIONS = [
    (r'менеджер\s+сопровождени',   'сопровождение'),
    (r'менеджер\s+поиск',          'поиск'),
]

# Поля «да/нет», которые разрешено распознавать без двоеточия (значение слито с
# подсказкой «(да/нет)»). Остальные поля требуют двоеточия — во избежание ложных
# срабатываний на строках задач.
_NO_COLON_ATTRS = {'orders', 'orders_weekday', 'orders_weekend', 'firms'}


def _match_field(key: str, patterns: list) -> Optional[str]:
    key_lower = key.strip().lower()
    for pattern, attr in patterns:
        if re.search(pattern, key_lower):
            return attr
    return None


def _match_field_prefix(key: str, patterns: list) -> Optional[str]:
    """Как _match_field, но поле должно стоять В НАЧАЛЕ строки — для распознавания
    полей без двоеточия («Заказы выхи (да/нет)да»), не ловя ключевые слова из задач."""
    key_lower = key.strip().lower()
    for pattern, attr in patterns:
        m = re.search(pattern, key_lower)
        if m and m.start() <= 2:
            return attr
    return None


def _match_section(line: str) -> Optional[str]:
    line_lower = line.strip().lower()
    for pattern, section in _SECTIONS:
        if re.search(pattern, line_lower):
            return section
    return None


def _parse(text: str, field_patterns: list, check_sections: bool,
           default_employee: str = "") -> Optional[Report]:
    report = Report()
    current_attr: Optional[str] = None
    current_lines: list[str] = []

    def flush():
        if current_attr:
            setattr(report, current_attr, " ".join(current_lines).strip())

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if check_sections:
            section = _match_section(line)
            if section:
                flush()
                current_attr = None
                current_lines = []
                report.manager_type = section
                continue

        if ":" in line:
            key_part, _, value_part = line.partition(":")
            attr = _match_field(key_part, field_patterns)
            if attr:
                flush()
                current_attr = attr
                current_lines = [value_part.strip()] if value_part.strip() else []
                continue

        # Поле БЕЗ двоеточия («Заказы выхи (да/нет)да»): распознаём поле по началу
        # строки (убрав подсказку «(...)»), значение — да/нет/число из хвоста.
        # Только для да/нет-полей заказов/фирм — иначе строки задач, начинающиеся
        # с «Дата»/«Сотрудник», ложно перезаписали бы эти поля.
        cleaned = re.sub(r'\(.*?\)', ' ', line)
        attr = _match_field_prefix(cleaned, field_patterns)
        if attr in _NO_COLON_ATTRS:
            m = re.search(r'(да|нет|yes|no|\+|\d+)\s*$', cleaned.strip(), re.IGNORECASE)
            flush()
            current_attr = attr
            current_lines = [m.group(1)] if m else []
            continue

        if current_attr and line:
            current_lines.append(line)

    flush()

    # Именной шаблон (напр. «Смена Влада») — ФИО можно не заполнять.
    if not report.employee and default_employee:
        report.employee = default_employee

    if report.employee and report.date:
        return report
    return None


def parse_report(text: str) -> Optional[Report]:
    if not text.strip():
        return None
    first_line = text.strip().splitlines()[0].strip().lower()

    if re.search(r'смена\s+менеджер\s+сопровождени', first_line):
        report = _parse(text, _NEW_FIELDS, check_sections=False)
        if report:
            report.manager_type = 'сопровождение'
        return report

    if re.search(r'смена\s+менеджер\s+поиск', first_line):
        report = _parse(text, _NEW_FIELDS, check_sections=False)
        if report:
            report.manager_type = 'поиск'
        return report

    if re.search(r'смена\s+влада', first_line):
        # Именной шаблон: ФИО подставляем автоматически, если не заполнено.
        report = _parse(text, _NEW_FIELDS, check_sections=False,
                        default_employee='Владислава Герасимчук')
        if report:
            report.manager_type = 'влада'
        return report

    # старый формат (обратная совместимость)
    if re.search(r'^смена', first_line):
        return _parse(text, _NEW_FIELDS, check_sections=True)
    return _parse(text, _OLD_FIELDS, check_sections=False)
