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
    orders: str = ""          # "будний" | "выходной" — для шаблона Влады
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
    (r'телефон',                   'phones'),
    (r'фирм',                      'firms'),
    (r'тип',                       'day_type'),
    (r'заказ',                     'orders'),
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


def _match_field(key: str, patterns: list) -> Optional[str]:
    key_lower = key.strip().lower()
    for pattern, attr in patterns:
        if re.search(pattern, key_lower):
            return attr
    return None


def _match_section(line: str) -> Optional[str]:
    line_lower = line.strip().lower()
    for pattern, section in _SECTIONS:
        if re.search(pattern, line_lower):
            return section
    return None


def _parse(text: str, field_patterns: list, check_sections: bool) -> Optional[Report]:
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

        if current_attr and line:
            current_lines.append(line)

    flush()

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
        report = _parse(text, _NEW_FIELDS, check_sections=False)
        if report:
            report.manager_type = 'влада'
        return report

    # старый формат (обратная совместимость)
    if re.search(r'^смена', first_line):
        return _parse(text, _NEW_FIELDS, check_sections=True)
    return _parse(text, _OLD_FIELDS, check_sections=False)
