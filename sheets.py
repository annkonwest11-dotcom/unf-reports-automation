import logging
import re
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

from parser import Report

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER_ROW = 4
MSK = timezone(timedelta(hours=3))
# Диапазоны данных дней в листе смен (осн. смены / подработки), колонки E:AI.
# Осн. смены — строки 5-9 (Дарья/Ксения/Алена/Влада/Анна),
# подработки — строки 14-16 (Алена/Влада/Анна). Раскладка после удаления
# Валерии Папоян (2026-08-11); диапазоны покрывают ровно строки сотрудников.
_SHIFT_DAY_RANGES = ('E5:AI9', 'E14:AI16')

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
    stripped = re.sub(r'\b\d{4}\b', '', stripped).strip(' .,')

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
    stripped = re.sub(r'\b\d{4}\b', '', stripped).strip(' .,')
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

    def _shifts_ws(self) -> gspread.Worksheet:
        """Лист смен для СЕГОДНЯШНЕЙ даты. Если календарный месяц уже следующий за
        расчётным периодом (окно 1-10, старый месяц ещё не закрыт) — пишем/читаем в
        временный лист СМЕНЫ_СЛЕД (создаём копией СМЕНЫ при необходимости), чтобы
        смены нового месяца не столкнулись со старыми в тех же колонках дней.
        При закрытии месяца archive_month переносит СМЕНЫ_СЛЕД → СМЕНЫ и удаляет его."""
        sh = self._gc.open_by_key(self._spreadsheet_id)
        period = sh.worksheet('НАСТРОЙКИ').acell('B4').value or ''
        try:
            pm, py = _parse_period(period)
        except Exception:
            return sh.worksheet('СМЕНЫ')
        today = datetime.now(MSK)
        if (today.year, today.month) == (py, pm):
            return sh.worksheet('СМЕНЫ')
        nxt_m = pm % 12 + 1
        nxt_y = py + (1 if pm == 12 else 0)
        if (today.year, today.month) == (nxt_y, nxt_m):
            try:
                return sh.worksheet('СМЕНЫ_СЛЕД')
            except gspread.WorksheetNotFound:
                base = sh.worksheet('СМЕНЫ')
                nw = sh.duplicate_sheet(base.id, new_sheet_name='СМЕНЫ_СЛЕД')
                nw.batch_clear(list(_SHIFT_DAY_RANGES))
                nw.update([[_next_month_label(period)]], 'A2')
                logger.info("Created СМЕНЫ_СЛЕД for overlap month (%s)", _next_month_label(period))
                return nw
        logger.warning("Shifts routing: today %d-%02d vs period %r — defaulting to СМЕНЫ",
                       today.year, today.month, period)
        return sh.worksheet('СМЕНЫ')

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
        # Шаблон «Смена Влада»: поля «Заказы будни (да/нет)» и «Заказы выхи (да/нет)».
        #   • «Заказы выхи = да» → ВЫХОДНОЙ: осн.смену НЕ ставим, подработка 2000.
        #   • иначе → осн.смена 3000 ВСЕГДА (будни/выхи пусто или «нет» — тоже 3000).
        #       при этом «Заказы будни = да» → +подработка 2000.
        # Старое поле «Заказы (да/нет)» (report.orders) = будни (обратная совместимость).
        def _yes(v: str) -> bool:
            return v.strip().lower().startswith(("да", "+", "yes"))

        vyhi_yes = _yes(report.orders_weekend)                               # «Заказы выхи»
        budni_yes = _yes(report.orders_weekday) or _yes(report.orders)      # «Заказы будни» (+старое)

        if vyhi_yes:                                        # выходной с заказами
            main_val = ""
            side_val = "2000"
            day_kind = "вых"
        else:                                              # будний (или без заказов) → осн.3000
            main_val = "3000"
            side_val = "2000" if budni_yes else ""
            day_kind = "будн"

        main_row = self._find_employee_row(
            all_rows, report.employee, self._section_employee_rows(all_rows, "основные смены"))
        side_row = self._find_employee_row(
            all_rows, report.employee, self._section_employee_rows(all_rows, "подработки"))

        if main_row:
            ws.update_cell(main_row, col_num, main_val)
        if side_row:
            ws.update_cell(side_row, col_num, side_val)
        logger.info(
            "Влада %s день=%d: осн=%s подраб=%s (будни=%r выхи=%r orders=%r main_row=%s side_row=%s)",
            day_kind, day, main_val or "—", side_val or "—",
            report.orders_weekday, report.orders_weekend, report.orders, main_row, side_row,
        )
        return bool(main_row or side_row)

    def _update_soprovozhdenie(self, report: Report, ws, all_rows: list, day: int, col_num: int) -> bool:
        # Шаблон «Смена Менеджер сопровождение»:
        #   Тип будний → осн.смена 2500; выходной → осн. нет.
        #   Фирмы=да → +1800 в подработки (любой тип).
        #   Заказы выходные (телефонов 1/2): тел 1 → 1800, тел 2 → 2100 (1800+300).
        #   Заказы будние (доп телефон да/нет): да → +1800.
        #   Подработки = сумма компонентов (0 → пусто).
        is_weekend = bool(re.search(r'выход', report.day_type.lower()))
        firms_yes = report.firms.strip().lower().startswith(("да", "+", "yes"))
        ow = report.orders_weekend.strip()             # "1" | "2" | ""
        obd_yes = report.orders_weekday.strip().lower().startswith(("да", "+", "yes"))

        main_val = "" if is_weekend else "2500"
        side = 0
        if firms_yes:
            side += 1800
        if re.search(r'2', ow):
            side += 2100
        elif re.search(r'1', ow):
            side += 1800
        if obd_yes:
            side += 1800

        main_row = self._find_employee_row(
            all_rows, report.employee, self._section_employee_rows(all_rows, "основные смены"))
        side_row = self._find_employee_row(
            all_rows, report.employee, self._section_employee_rows(all_rows, "подработки"))
        if main_row:
            ws.update_cell(main_row, col_num, main_val)
        if side_row:
            ws.update_cell(side_row, col_num, str(side) if side > 0 else "")
        logger.info(
            "Сопровождение %s день=%d: тип=%s осн=%s подраб=%s (firms=%s ow=%r будн.доп=%s)",
            report.employee, day, "вых" if is_weekend else "будн", main_val or "—",
            side or "—", firms_yes, ow, obd_yes,
        )
        return bool(main_row or side_row)

    def update_report(self, report: Report) -> bool:
        ws = self._shifts_ws()
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

        if report.manager_type == "сопровождение":
            return self._update_soprovozhdenie(report, ws, all_rows, day, col_num)

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
        ws = self._shifts_ws()
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
        ws = self._shifts_ws()
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

    def _build_month_archive(self, sh, period: str) -> str:
        """Собирает единый лист АРХИВ_<МЕСЯЦ>_<ГОД>: все рабочие листы секциями,
        застывшие значения (без формул), оформление и объединения перенесены из
        живых листов, крупные секции и детали сотрудников свёрнуты группировкой.
        Автономная версия — scripts/build_archive.py. Возвращает имя листа."""
        mon, yr = period.split()
        title = f"АРХИВ_{mon.upper()}_{yr}"
        SEC = [
            ("НАСТРОЙКИ",        "⚙️  НАСТРОЙКИ — параметры месяца",               "A1:C40",   False),
            ("СВОДНАЯ_ЗП",       "\U0001f4b0  СВОДНАЯ ЗП — ведомость (свёрнута до ИТОГО)", "A24:F166", "svod"),
            ("СМЕНЫ",            "\U0001f4c5  СМЕНЫ — табель за месяц",                    None,       True),
            ("ДАННЫЕ_Губарев",   "\U0001f4c7  ДАННЫЕ · Губарев — взаиморасчёты 1С",        None,       True),
            ("ДАННЫЕ_Перфильев", "\U0001f4c7  ДАННЫЕ · Перфильев — взаиморасчёты 1С",      None,       True),
            ("БЕБИ_ЛИСТЫ",       "\U0001f37c  БЕБИ-ЛИСТЫ — клиенты с вычетом 40%",          None,       True),
            ("НОВЫЕ_КЛИЕНТЫ",    "✨  НОВЫЕ КЛИЕНТЫ — поиск за месяц",                 None,       True),
            ("КОНКУРС",          "\U0001f3c6  КОНКУРС — бонусы за результат",              None,       True),
        ]

        def _col(s):
            n = 0
            for ch in s:
                n = n * 26 + (ord(ch) - 64)
            return n - 1

        def parse_a1(a1):
            m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", a1)
            return int(m.group(2)) - 1, _col(m.group(1)), int(m.group(4)), _col(m.group(3)) + 1

        parts = []
        for name, hdr, rng, grp in SEC:
            ws = sh.worksheet(name)
            if rng:
                r0, c0, r1, c1 = parse_a1(rng)
                vals = ws.get(rng, value_render_option='FORMATTED_VALUE')
            else:
                vals = ws.get_all_values()
                while vals and not any(str(x).strip() for x in vals[-1]):
                    vals.pop()
                r0, c0, r1, c1 = 0, 0, len(vals), max((len(r) for r in vals), default=1)
            src = {"sheetId": ws.id, "startRowIndex": r0, "endRowIndex": r1,
                   "startColumnIndex": c0, "endColumnIndex": c1}
            parts.append((hdr, vals, src, grp))

        maxc = max(p[2]["endColumnIndex"] - p[2]["startColumnIndex"] for p in parts)
        maxc = max(maxc, 6)

        def pad(r):
            return list(r) + [""] * (maxc - len(r))

        matrix = [pad([f"АРХИВ · {period}"]),
                  pad(["❄ Застывшие значения (без формул). Крупные секции свёрнуты — разворот по [+] слева."]),
                  pad([])]
        layout = []
        svod_labels = None
        svod_dstart = None
        for hdr, vals, src, grp in parts:
            hrow = len(matrix)
            matrix.append(pad([hdr]))
            dstart = len(matrix)
            nc = src["endColumnIndex"] - src["startColumnIndex"]
            for r in vals:
                matrix.append(pad(r))
            layout.append((hdr, hrow, dstart, len(vals), nc, src, grp))
            if grp == "svod":
                svod_labels = [(r[0] if r else "") for r in vals]
                svod_dstart = dstart
            matrix.append(pad([]))
        total_rows = len(matrix) + 5

        if title in {w.title for w in sh.worksheets()}:
            sh.del_worksheet(sh.worksheet(title))
        aws = sh.add_worksheet(title=title, rows=total_rows, cols=maxc, index=0)
        aid = aws.id
        aws.update(matrix, "A1", value_input_option="RAW")

        def rgb(h):
            h = h.lstrip('#')
            return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}

        def gr(r0, r1, c0, c1):
            return {"sheetId": aid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}

        reqs = []
        for hdr, hrow, dstart, nr, nc, src, grp in layout:
            if nr == 0:
                continue
            reqs.append({"copyPaste": {"source": src, "destination": gr(dstart, dstart + nr, 0, nc),
                                       "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
        mmeta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId),merges)"})
        merges_by_sid = {s["properties"]["sheetId"]: s.get("merges", []) for s in mmeta["sheets"]}
        for hdr, hrow, dstart, nr, nc, src, grp in layout:
            if nr == 0:
                continue
            r0, c0, r1, c1 = src["startRowIndex"], src["startColumnIndex"], src["endRowIndex"], src["endColumnIndex"]
            for m in merges_by_sid.get(src["sheetId"], []):
                if m["startRowIndex"] >= r0 and m["endRowIndex"] <= r1 and m["startColumnIndex"] >= c0 and m["endColumnIndex"] <= c1:
                    reqs.append({"mergeCells": {"range": {"sheetId": aid,
                        "startRowIndex": dstart + (m["startRowIndex"] - r0), "endRowIndex": dstart + (m["endRowIndex"] - r0),
                        "startColumnIndex": m["startColumnIndex"] - c0, "endColumnIndex": m["endColumnIndex"] - c0},
                        "mergeType": "MERGE_ALL"}})
        reqs.append({"repeatCell": {"range": gr(0, 1, 0, maxc), "cell": {"userEnteredFormat": {"backgroundColor": rgb("#ffffff"), "textFormat": {"bold": True, "fontSize": 15, "foregroundColor": rgb("#37503f")}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
        reqs.append({"repeatCell": {"range": gr(1, 2, 0, maxc), "cell": {"userEnteredFormat": {"backgroundColor": rgb("#ffffff"), "textFormat": {"italic": True, "foregroundColor": rgb("#6b7a75")}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
        for hdr, hrow, dstart, nr, nc, src, grp in layout:
            reqs.append({"repeatCell": {"range": gr(hrow, hrow + 1, 0, maxc), "cell": {"userEnteredFormat": {"backgroundColor": rgb("#7f9990"), "textFormat": {"bold": True, "foregroundColor": rgb("#ffffff"), "fontSize": 11}}}, "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
        reqs.append({"updateSheetProperties": {"properties": {"sheetId": aid, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}})
        for hdr, hrow, dstart, nr, nc, src, grp in layout:
            if "НАСТРОЙКИ" in hdr and nr > 0:
                reqs.append({"mergeCells": {"range": gr(dstart, dstart + 1, 0, 3), "mergeType": "MERGE_ALL"}})
        widths = {0: 240, 1: 230, 2: 165, 3: 200, 4: 150, 5: 305}
        for c, w in widths.items():
            reqs.append({"updateDimensionProperties": {"range": {"sheetId": aid, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1}, "properties": {"pixelSize": w}, "fields": "pixelSize"}})
        if maxc > 6:
            reqs.append({"updateDimensionProperties": {"range": {"sheetId": aid, "dimension": "COLUMNS", "startIndex": 6, "endIndex": maxc}, "properties": {"pixelSize": 85}, "fields": "pixelSize"}})

        groups = []
        labels = [str(x).strip() for x in (svod_labels or [])]
        for idx, a in enumerate(labels):
            if a.startswith("ИТОГО ЗП"):
                nm = a.replace("ИТОГО ЗП —", "").replace("ИТОГО ЗП -", "").strip()
                h = None
                for j in range(idx - 1, -1, -1):
                    if labels[j].startswith(nm):
                        h = j
                        break
                    if labels[j].startswith("ИТОГО ЗП"):
                        break
                if h is not None and idx - 1 > h:
                    groups.append((svod_dstart + h, svod_dstart + idx))
        for hdr, hrow, dstart, nr, nc, src, grp in layout:
            if grp is True and nr > 0:
                groups.append((dstart, dstart + nr))
        for s0, e0 in groups:
            reqs.append({"addDimensionGroup": {"range": {"sheetId": aid, "dimension": "ROWS", "startIndex": s0, "endIndex": e0}}})

        sh.batch_update({"requests": reqs})
        collapse = [{"updateDimensionGroup": {"dimensionGroup": {"range": {"sheetId": aid, "dimension": "ROWS", "startIndex": s0, "endIndex": e0}, "depth": 1, "collapsed": True}, "fields": "collapsed"}} for s0, e0 in groups]
        if collapse:
            sh.batch_update({"requests": collapse})
        logger.info("Built consolidated archive %s (%d sections, %d groups)", title, len(layout), len(groups))
        return title

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

        # Единый лист-архив: все рабочие листы секциями, застывшие значения,
        # оформление и объединения перенесены, крупные секции свёрнуты группировкой
        # (та же логика, что в scripts/build_archive.py).
        archive_title = self._build_month_archive(sh, period)
        logger.info("Consolidated archive built: %s", archive_title)

        # Clear СМЕНЫ data (days only, formulas in col AJ stay)
        ws_smeny = sh.worksheet('СМЕНЫ')
        ws_smeny.batch_clear(list(_SHIFT_DAY_RANGES))
        next_label = _next_month_label(period)
        ws_smeny.update([[next_label]], 'A2')

        # Промоут смен следующего месяца: если в окне 1-10 бот писал смены нового
        # месяца во временный лист СМЕНЫ_СЛЕД — переносим их значениями в очищенный
        # СМЕНЫ и удаляем временный лист (следующий нахлёст создаст его заново).
        try:
            ws_next = sh.worksheet('СМЕНЫ_СЛЕД')

            def _grid(sid, r0, r1, c0, c1):
                return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                        "startColumnIndex": c0, "endColumnIndex": c1}
            # Осн. смены — строки 5-9 (0-инд 4..9), подработки — строки 14-16
            # (0-инд 13..16); колонки E(4)…AI(35). Совпадает с _SHIFT_DAY_RANGES.
            sh.batch_update({"requests": [
                {"copyPaste": {"source": _grid(ws_next.id, 4, 9, 4, 35),
                               "destination": _grid(ws_smeny.id, 4, 9, 4, 35),
                               "pasteType": "PASTE_VALUES", "pasteOrientation": "NORMAL"}},
                {"copyPaste": {"source": _grid(ws_next.id, 13, 16, 4, 35),
                               "destination": _grid(ws_smeny.id, 13, 16, 4, 35),
                               "pasteType": "PASTE_VALUES", "pasteOrientation": "NORMAL"}},
            ]})
            sh.del_worksheet(ws_next)
            logger.info("Promoted СМЕНЫ_СЛЕД → СМЕНЫ (overlap shifts) and removed temp sheet")
        except gspread.WorksheetNotFound:
            pass

        # Clear ДАННЫЕ_Губарев and ДАННЫЕ_Перфильев — ТОЛЬКО данные A:E
        # (контрагент, долг/оборот/оплаты/долг). Колонки F:L — ПОСТОЯННЫЕ формулы
        # (ВПР менеджеров/типа/беби из СПРАВОЧНИК, скорр.оплаты, оборот-число):
        # их НЕ трогаем, иначе после закрытия месяца ответственные не проставляются.
        for sheet_name in ('ДАННЫЕ_Губарев', 'ДАННЫЕ_Перфильев'):
            ws_d = sh.worksheet(sheet_name)
            last_row = max(len(ws_d.get_all_values()), 4)
            ws_d.batch_clear([f'A4:E{last_row}'])
            # Промоут накопленного нового месяца: если в окне 1-10 синк писал новый
            # месяц во временный лист ДАННЫЕ_*_СЛЕД — переносим A:E значениями в
            # очищенный живой лист и удаляем временный (формулы F:L живого целы).
            try:
                ws_next = sh.worksheet(sheet_name + '_СЛЕД')
            except gspread.WorksheetNotFound:
                continue
            n_next = max(len(ws_next.get_all_values()), 4)
            nxt = ws_next.get(f'A4:E{n_next}', value_render_option='UNFORMATTED_VALUE')
            nxt = [r for r in nxt if any(str(x).strip() for x in r)]
            if nxt:
                ws_d.update(nxt, f'A4:E{4 + len(nxt) - 1}', value_input_option='RAW')
            sh.del_worksheet(ws_next)
            logger.info("Promoted %s_СЛЕД → %s (%d строк) and removed temp",
                        sheet_name, sheet_name, len(nxt))

        # Clear НОВЫЕ_КЛИЕНТЫ data rows
        ws_nk = sh.worksheet('НОВЫЕ_КЛИЕНТЫ')
        last_row = max(len(ws_nk.get_all_values()), 4)
        ws_nk.batch_clear([f'A4:H{last_row}'])

        # Clear БЕБИ_ЛИСТЫ manual inputs: контрагенты (A) и обороты (D/E).
        # Формулы в B/C/F–J сохраняются — лист готов к новому месяцу.
        sh.worksheet('БЕБИ_ЛИСТЫ').batch_clear(['A4:A23', 'D4:E23'])

        # Clear СВОДНАЯ_ЗП manual input cells (доп.премии, комментарии, конкурс,
        # факты РОП, найм/контент Влады, авансы). Адреса — по раскладке после
        # удаления Валерии Папоян (2026-08-11). Формулы НЕ трогаем:
        # конкурс Ксении C47 (лист КОНКУРС) и C=E у Влады/РОП.
        ws_sv = sh.worksheet('СВОДНАЯ_ЗП')
        manual_ranges = [
            'C33:C35',            # Дарья: конкурс, доп.премия, комментарий
            'C46', 'C48:C49',     # Ксения: бонус-сторис, доп.премия, комментарий
            'C59:C60',            # Алена: доп.премия, комментарий
            'E74', 'E78',         # РОП: факты (оборот-авто / поступления) — перезапишет синк 10:35
            # ★ E69 (факт новых продаж) НЕ чистим — с 2026-08-04 это ФОРМУЛА
            # по листу НОВЫЕ_КЛИЕНТЫ, она сама пересчитается на новый месяц.
            # Чистка её убивала (проверено на закрытии июля 2026).
            'E82:E83',            # РОП: доп.премия, комментарий
            'E92',                # Влада: % контента
            'E93:G93',            # Влада: клиенты SMM (A/B/C)
            'E95:F99',            # Влада: найм (кол-во + ФИО) + бонус за план найма
            'E101:F101',          # Влада: премия за проекты + название
            'E105:E106',          # Влада: доп.премия, комментарий
            'C113:E117',          # Таблица выплат: авансы / наличные / ЗП на карту
        ]
        ws_sv.batch_clear(manual_ranges)

        # Страховка: восстанавливаем формулу факта новых продаж РОП.
        # Строка ИТОГ листа НОВЫЕ_КЛИЕНТЫ отсекается по пустому менеджеру (C),
        # иначе сумма удваивалась (баг 2026-08-04).
        ws_sv.update(
            [["=SUMIF('НОВЫЕ_КЛИЕНТЫ'!$C$4:$C$503;\"<>\";'НОВЫЕ_КЛИЕНТЫ'!$G$4:$G$503)"]],
            'E69',
            value_input_option='USER_ENTERED',
        )

        # Update period in НАСТРОЙКИ
        ws_settings.update([[next_label]], 'B4')

        # Invalidate cached СМЕНЫ worksheet
        self._ws = None

        logger.info("Month archived: %s → next period: %s", period, next_label)
        return period
