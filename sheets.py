import logging
import re
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from parser import Report

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER_ROW = 4

_MONTHS_RU = {
    'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4,
    'май': 5, 'мая': 5, 'июн': 6, 'июл': 7, 'август': 8,
    'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12,
}

_MONTHS_GENITIVE = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
    5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
    9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря',
}

_MONTHS_NOMINATIVE = {
    1: 'январь', 2: 'февраль', 3: 'март', 4: 'апрель',
    5: 'май', 6: 'июнь', 7: 'июль', 8: 'август',
    9: 'сентябрь', 10: 'октябрь', 11: 'ноябрь', 12: 'декабрь',
}

_MONTHS_NOMINATIVE_CAP = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}

_MONTHS_SHORT_UPPER = {
    1: 'ЯНВ', 2: 'ФЕВ', 3: 'МАР', 4: 'АПР',
    5: 'МАЙ', 6: 'ИЮН', 7: 'ИЮЛ', 8: 'АВГ',
    9: 'СЕН', 10: 'ОКТ', 11: 'НОЯ', 12: 'ДЕК',
}


def _parse_period(period: str) -> tuple[int, int]:
    """Returns (month, year) from period string like 'Май 2026'."""
    _, month = _strip_month(period)
    m = re.search(r'(\d{4})', period)
    year = int(m.group(1)) if m else datetime.now().year
    return (month or datetime.now().month), year


def _next_month_label(period: str) -> str:
    month, year = _parse_period(period)
    next_month = month % 12 + 1
    next_year = year + 1 if month == 12 else year
    return f"{_MONTHS_NOMINATIVE_CAP[next_month]} {next_year}"


def _strip_month(period: str) -> tuple[str, int | None]:
    p = period.lower().strip()
    for prefix, num in _MONTHS_RU.items():
        idx = p.find(prefix)
        if idx != -1:
            end = idx + len(prefix)
            while end < len(p) and p[end].isalpha():
                end += 1
            p = (p[:idx] + p[end:]).strip()
            return p, num
    return p, None


def _parse_day_range(period: str) -> set[int]:
    stripped, _ = _strip_month(period)
    stripped = stripped.strip(' .,')

    if not stripped:
        return set(range(1, 32))

    m = re.match(r'(\d{1,2})\s*[-–]\s*(\d{1,2})', stripped)
    if m:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))

    m = re.match(r'(\d{1,2})', stripped)
    if m:
        return {int(m.group(1))}

    return set(range(1, 32))


def _format_period_label(period: str) -> str:
    now = datetime.now()
    stripped, month_num = _strip_month(period)
    stripped = stripped.strip(' .,')
    month = month_num or now.month
    year = now.year

    if not stripped:
        return f"{_MONTHS_NOMINATIVE[month]} {year}"

    m = re.match(r'(\d{1,2})\s*[-–]\s*(\d{1,2})', stripped)
    if m:
        return f"{m.group(1)}–{m.group(2)} {_MONTHS_GENITIVE[month]} {year}"

    m = re.match(r'(\d{1,2})', stripped)
    if m:
        return f"{int(m.group(1))} {_MONTHS_GENITIVE[month]} {year}"

    return f"{_MONTHS_NOMINATIVE[month]} {year}"


class SheetsClient:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._spreadsheet_id = spreadsheet_id
        self._ws: gspread.Worksheet | None = None

    def _get_sheet(self) -> gspread.Worksheet:
        if self._ws is None:
            spreadsheet = self._gc.open_by_key(self._spreadsheet_id)
            self._ws = spreadsheet.worksheet("СМЕНЫ")
        return self._ws

    def _section_employee_rows(self, all_rows: list[list[str]], keyword: str) -> set[int]:
        section_start = None
        for i, row in enumerate(all_rows):
            if row and keyword.lower() in row[0].lower():
                section_start = i
                break
        if section_start is None:
            return set()

        result: set[int] = set()
        for i in range(section_start + 1, len(all_rows)):
            row = all_rows[i]
            col_a = row[0].strip() if row else ""
            col_b = row[1].strip() if len(row) > 1 else ""
            if col_a.isdigit() and col_b:
                result.add(i + 1)
            elif result and col_a and not col_a.isdigit():
                break
        return result

    def _find_employee_row(
        self,
        all_rows: list[list[str]],
        name: str,
        allowed_rows: set[int],
    ) -> int | None:
        name_words = [w for w in name.lower().split() if len(w) > 2]
        if not name_words:
            return None

        best_score, best_row, ambiguous = 0, None, False
        for row_num in allowed_rows:
            row = all_rows[row_num - 1]
            if len(row) < 2 or not row[1]:
                continue
            cell_words = set(row[1].lower().split())
            score = sum(1 for w in name_words if w in cell_words)
            if score == 0:
                continue
            if score > best_score:
                best_score, best_row, ambiguous = score, row_num, False
            elif score == best_score:
                ambiguous = True

        if ambiguous:
            logger.warning("Ambiguous employee name %r — use full name", name)
            return None
        return best_row

    def _find_day_column(self, header_row: list[str], day: int) -> int | None:
        for j, cell in enumerate(header_row, 1):
            if cell.strip() == str(day):
                return j
        return None

    @staticmethod
    def _parse_day(date_str: str) -> int | None:
        m = re.match(r"(\d{1,2})[.\-/]", date_str.strip())
        if m:
            return int(m.group(1))
        if date_str.strip().isdigit():
            return int(date_str.strip())
        return None

    @staticmethod
    def _is_side_job(report: Report) -> bool:
        if report.manager_type == "влада":
            return False
        if report.manager_type == "сопровождение":
            day = report.day_type.lower()
            return bool(re.search(r'выход', day))
        if report.manager_type == "поиск":
            return False
        return report.shift_type.lower().strip() in ("подработка", "подработки")

    @staticmethod
    def _shift_value(report: Report, employee_row: list[str]) -> str:
        stavka = employee_row[3].strip() if len(employee_row) > 3 else "1"

        if report.manager_type == "сопровождение" and re.search(r'выход', report.day_type.lower()):
            phones = report.phones.strip()
            firms = report.firms.strip().lower() in ("да", "yes", "+")
            if phones == "2" and firms:
                return "3900"
            if phones == "1" and firms:
                return "3600"
            if phones == "2":
                return "2100"
            return "1800"

        if report.shift_type.lower().strip() in ("подработка", "подработки"):
            side = report.side_job_type.lower()
            if re.search(r"2\s*(тел|телефон)", side):
                return "2100"
            return "1800"

        return stavka if stavka else "1"

    def _update_vlada(self, report: Report, ws, all_rows: list, day: int, col_num: int) -> bool:
        orders = report.orders.strip().lower()
        if re.search(r'будн', orders):
            # Будний: смены 3000 + подработки 2500
            main_rows = self._section_employee_rows(all_rows, "основные смены")
            main_row = self._find_employee_row(all_rows, report.employee, main_rows)
            side_rows = self._section_employee_rows(all_rows, "подработки")
            side_row = self._find_employee_row(all_rows, report.employee, side_rows)
            if main_row:
                ws.update_cell(main_row, col_num, "3000")
                logger.info("Влада будний: основные row=%d val=3000", main_row)
            if side_row:
                ws.update_cell(side_row, col_num, "2500")
                logger.info("Влада будний: подработки row=%d val=2500", side_row)
            return bool(main_row or side_row)
        elif re.search(r'выход', orders):
            # Выходной: только подработки 2000
            side_rows = self._section_employee_rows(all_rows, "подработки")
            side_row = self._find_employee_row(all_rows, report.employee, side_rows)
            if side_row:
                ws.update_cell(side_row, col_num, "2000")
                logger.info("Влада выходной: подработки row=%d val=2000", side_row)
            return bool(side_row)
        else:
            # Нет поля Заказы (старый шаблон) — только основные смены по ставке
            main_rows = self._section_employee_rows(all_rows, "основные смены")
            main_row = self._find_employee_row(all_rows, report.employee, main_rows)
            if main_row:
                stavka = all_rows[main_row - 1][3].strip() if len(all_rows[main_row - 1]) > 3 else "3000"
                ws.update_cell(main_row, col_num, stavka or "3000")
                logger.info("Влада (без заказов): основные row=%d val=%s", main_row, stavka)
            return bool(main_row)

    def update_report(self, report: Report) -> bool:
        ws = self._get_sheet()
        all_rows = ws.get_all_values()
        header_row = all_rows[HEADER_ROW - 1] if len(all_rows) >= HEADER_ROW else []

        logger.info(
            "Parsed: employee=%r manager=%r day_type=%r phones=%r firms=%r orders=%r shift=%r",
            report.employee, report.manager_type, report.day_type,
            report.phones, report.firms, report.orders, report.shift_type,
        )
        day = self._parse_day(report.date)
        if day is None:
            logger.warning("Cannot parse day from: %r", report.date)
            return False

        col_num = self._find_day_column(header_row, day)
        if col_num is None:
            logger.warning("Day column not found for day %s", day)
            return False

        if report.manager_type == "влада":
            return self._update_vlada(report, ws, all_rows, day, col_num)

        is_side = self._is_side_job(report)
        section_key = "подработки" if is_side else "основные смены"
        allowed = self._section_employee_rows(all_rows, section_key)

        row_num = self._find_employee_row(all_rows, report.employee, allowed)
        if row_num is None:
            logger.warning("Employee %r not found in section %r", report.employee, section_key)
            return False

        value = self._shift_value(report, all_rows[row_num - 1])
        ws.update_cell(row_num, col_num, value)
        logger.info(
            "Updated: employee=%r section=%s row=%d day=%d value=%r",
            report.employee, section_key, row_num, day, value,
        )
        return True

    def _columns_for_days(self, header_row: list[str], days: set[int]) -> dict[int, int]:
        cols = {}
        for j, cell in enumerate(header_row):
            cell = cell.strip()
            if cell.isdigit() and int(cell) in days:
                cols[int(cell)] = j
        return cols

    def _section_stats(
        self, all_rows: list[list[str]], section_keyword: str, cols: dict[int, int]
    ) -> list[tuple[str, int, int]]:
        section_rows = self._section_employee_rows(all_rows, section_keyword)
        result = []
        for row_num in sorted(section_rows):
            row = all_rows[row_num - 1]
            name = row[1].strip() if len(row) > 1 else ''
            if not name:
                continue
            shifts = 0
            total = 0
            for col in cols.values():
                if col < len(row):
                    cell = row[col].strip()
                    if cell:
                        try:
                            val = int(re.sub(r'\D', '', cell) or '0')
                            if val > 0:
                                shifts += 1
                                total += val
                        except ValueError:
                            pass
            result.append((name, shifts, total))
        return result

    def _section_side_job_stats(
        self, all_rows: list[list[str]], cols: dict[int, int]
    ) -> list[tuple[str, int, int, int, int, int]]:
        """Returns (name, rest_1tel, rest_2tel, firms_1tel, firms_2tel, total) for each employee in подработки."""
        section_rows = self._section_employee_rows(all_rows, 'подработки')
        result = []
        for row_num in sorted(section_rows):
            row = all_rows[row_num - 1]
            name = row[1].strip() if len(row) > 1 else ''
            if not name:
                continue
            rest_1, rest_2, firms_1, firms_2, total = 0, 0, 0, 0, 0
            for col in cols.values():
                if col < len(row):
                    cell = row[col].strip()
                    if cell:
                        try:
                            val = int(re.sub(r'\D', '', cell) or '0')
                        except ValueError:
                            val = 0
                        if val == 1800:
                            rest_1 += 1
                            total += val
                        elif val == 2100:
                            rest_2 += 1
                            total += val
                        elif val == 3600:
                            firms_1 += 1
                            total += val
                        elif val == 3900:
                            firms_2 += 1
                            total += val
            result.append((name, rest_1, rest_2, firms_1, firms_2, total))
        return result

    def get_report(self, period: str) -> dict:
        ws = self._get_sheet()
        all_rows = ws.get_all_values()
        header_row = all_rows[HEADER_ROW - 1] if len(all_rows) >= HEADER_ROW else []

        days = _parse_day_range(period)
        cols = self._columns_for_days(header_row, days)

        return {
            'period_label': _format_period_label(period),
            'основные': self._section_stats(all_rows, 'основные смены', cols),
            'подработки': self._section_side_job_stats(all_rows, cols),
        }

    def write_shift(self, employee_name: str, day: int) -> bool:
        ws = self._get_sheet()
        all_rows = ws.get_all_values()
        header_row = all_rows[HEADER_ROW - 1] if len(all_rows) >= HEADER_ROW else []

        col_num = self._find_day_column(header_row, day)
        if col_num is None:
            logger.warning("write_shift: day column not found for day %d", day)
            return False

        allowed = self._section_employee_rows(all_rows, 'основные смены')
        row_num = self._find_employee_row(all_rows, employee_name, allowed)
        if row_num is None:
            logger.warning("write_shift: employee %r not found", employee_name)
            return False

        row = all_rows[row_num - 1]
        stavka = row[3].strip() if len(row) > 3 and row[3].strip() else '5000'
        ws.update_cell(row_num, col_num, stavka)
        logger.info("write_shift: %r day=%d value=%s", employee_name, day, stavka)
        return True

    def get_employees_without_report(self, day: int) -> list[str]:
        """Returns names of employees in основные смены who have no entry for the given day."""
        ws = self._get_sheet()
        all_rows = ws.get_all_values()
        header_row = all_rows[HEADER_ROW - 1] if len(all_rows) >= HEADER_ROW else []

        col_num = self._find_day_column(header_row, day)
        if col_num is None:
            return []

        col_idx = col_num - 1
        section_rows = self._section_employee_rows(all_rows, 'основные смены')
        missing = []
        for row_num in sorted(section_rows):
            row = all_rows[row_num - 1]
            name = row[1].strip() if len(row) > 1 else ''
            if not name:
                continue
            cell = row[col_idx].strip() if col_idx < len(row) else ''
            if not cell or cell == '0':
                missing.append(name)
        return missing

    def archive_month(self) -> str:
        """
        Archives current month by duplicating СВОДНАЯ_ЗП and СМЕНЫ within the same spreadsheet.
        Uses duplicate_sheet which preserves full formatting, colors, merged cells.
        Archived sheets are named e.g. СВОДНАЯ_ЗП_МАЙ_2026 and moved to the end.
        Then clears working sheets and advances period to next month.
        Returns the archived period label (e.g. 'Май 2026').
        """
        sh = self._gc.open_by_key(self._spreadsheet_id)

        ws_settings = sh.worksheet('НАСТРОЙКИ')
        period = ws_settings.acell('B4').value or ''
        month, year = _parse_period(period)
        suffix = f"{_MONTHS_SHORT_UPPER[month]}_{year}"

        sheets_to_archive = ['СВОДНАЯ_ЗП', 'СМЕНЫ']

        existing_titles = {ws.title for ws in sh.worksheets()}
        for sheet_name in sheets_to_archive:
            archive_name = f"{sheet_name}_{suffix}"
            if archive_name in existing_titles:
                logger.warning("Archive sheet %r already exists, deleting old", archive_name)
                sh.del_worksheet(sh.worksheet(archive_name))
            ws = sh.worksheet(sheet_name)
            sh.duplicate_sheet(ws.id, new_sheet_name=archive_name)
            logger.info("Archived %s → %s", sheet_name, archive_name)

        # Clear СМЕНЫ data (days only, formulas in col AJ stay)
        ws_smeny = sh.worksheet('СМЕНЫ')
        ws_smeny.batch_clear(['E5:AI13', 'E18:AI21'])
        next_label = _next_month_label(period)
        ws_smeny.update('A2', next_label)

        # Clear ДАННЫЕ_Губарев and ДАННЫЕ_Перфильев data rows
        for sheet_name in ('ДАННЫЕ_Губарев', 'ДАННЫЕ_Перфильев'):
            ws_d = sh.worksheet(sheet_name)
            last_row = max(len(ws_d.get_all_values()), 4)
            ws_d.batch_clear([f'A4:K{last_row}'])

        # Clear НОВЫЕ_КЛИЕНТЫ data rows
        ws_nk = sh.worksheet('НОВЫЕ_КЛИЕНТЫ')
        last_row = max(len(ws_nk.get_all_values()), 4)
        ws_nk.batch_clear([f'A4:H{last_row}'])

        # Clear СВОДНАЯ_ЗП manual input cells (доп. премии, комментарии, авансы)
        ws_sv = sh.worksheet('СВОДНАЯ_ЗП')
        manual_ranges = [
            'C14:C15', 'C28:C29', 'C41:C42', 'C54:C55',
            'C64:C65', 'C80:C81', 'C86:C87',
            'C93:C96', 'C110:C111',
            'C120:C130', 'G120:G130',
        ]
        ws_sv.batch_clear(manual_ranges)

        # Update period in НАСТРОЙКИ
        ws_settings.update('B4', next_label)

        # Invalidate cached СМЕНЫ worksheet
        self._ws = None

        logger.info("Month archived: %s → next period: %s", period, next_label)
        return period, archive_url
