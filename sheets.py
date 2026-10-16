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
# Запасные диапазоны дней листа смен (осн. смены / подработки), колонки E:AI.
# ★16.10.2026: номера строк тут УСТАРЕВАЮТ при каждом кадровом изменении (после
# увольнения Лилии и Влады осн. смены стали 5-10, подработки 15-16). Поэтому
# рабочий путь — _shift_ranges(ws): он находит секции по подписям «ОСНОВНЫЕ
# СМЕНЫ» / «ПОДРАБОТКИ». Эти значения остаются только как подстраховка, если
# подписи в листе не найдены.
_SHIFT_DAY_RANGES = ('E5:AI12', 'E17:AI19')

# Ставки смен менеджера сопровождения (★Анна, 15.10.2026): будний день — обычная
# смена, выходной — подработка по одной ставке, без надбавок. Тарифы продублированы
# в НАСТРОЙКИ листа (раздел «ТАРИФЫ СМЕН») — при изменении править оба места.
SOPR_WEEKDAY = 2500
SOPR_WEEKEND = 3600

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
                nw.batch_clear(self._shift_ranges(nw)[0])
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

    def _shift_ranges(self, ws) -> tuple[list[str], list[tuple[int, int]]]:
        """Диапазоны дней листа смен по подписям секций.

        Возвращает (['E5:AI10', 'E15:AI16'], [(4, 10), (14, 16)]): первое — для
        batch_clear, второе — границы строк в 0-индексации для copyPaste при
        промоуте СМЕНЫ_СЛЕД → СМЕНЫ. Если подписи не найдены, отдаём запасные
        _SHIFT_DAY_RANGES — лучше прежнее поведение, чем пустая чистка.
        """
        rows = ws.get_all_values()
        out_a1, out_idx = [], []
        for keyword in ("основные смены", "подработки"):
            found = self._section_employee_rows(rows, keyword)
            if not found:
                logger.warning("лист смен: секция %r не найдена", keyword)
                continue
            first, last = min(found), max(found)
            out_a1.append(f"E{first}:AI{last}")
            out_idx.append((first - 1, last))
        if len(out_a1) != 2:
            logger.warning("лист смен: секции не разобраны, беру запасные диапазоны %s",
                           _SHIFT_DAY_RANGES)
            return list(_SHIFT_DAY_RANGES), [(4, 12), (16, 19)]
        return out_a1, out_idx

    def _find_employee_row(
        self,
        all_rows: list[list[str]],
        name: str,
        allowed_rows: set[int],
    ) -> int | None:
        # ё=е: в таблице «Алена», человек пишет «Алёна» — это одно имя.
        # Порядок слов не важен (сравниваем множества): «Караханова Виолетта»
        # находит строку «Виолетта Караханова» — так пишут и так, и так.
        def _norm_words(text):
            return [w for w in text.lower().replace("ё", "е").split() if len(w) > 2]

        name_words = _norm_words(name)
        if not name_words:
            return None

        best_score, best_row, ambiguous = 0, None, False
        for row_num in allowed_rows:
            row = all_rows[row_num - 1]
            if len(row) < 2 or not row[1]:
                continue
            cell_words = set(_norm_words(row[1]))
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
            # ★15.10.2026 (Анна): у сопровождения одна ставка выходного — 3600,
            # без надбавок за телефоны и фирмы. Прежние 1800/2100/3600/3900
            # складывались из «заказов выходных» и «фирм», и этих пунктов в
            # шаблоне больше нет.
            return str(SOPR_WEEKEND)

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
        # Шаблон «Смена Менеджер сопровождение» (★новый с 15.10.2026, решение Анны):
        # в нём остались только Сотрудник / Дата / Выполненные задачи / Тип.
        #   будний  → осн.смена 2500, подработка пусто;
        #   выходной → подработка 3600, осн. пусто.
        # Надбавок больше нет: ни за «заказы будние» (доп. телефон), ни за «заказы
        # выходные», ни за фирмы в выходной (+1000) — смены фирм Анна проводит
        # доп.премией. Старые поля шаблона, если их кто-то пришлёт, игнорируем:
        # платить по ним больше нечего.
        is_weekend = bool(re.search(r'выход', report.day_type.lower()))

        main_val = "" if is_weekend else str(SOPR_WEEKDAY)
        side_val = str(SOPR_WEEKEND) if is_weekend else ""

        main_row = self._find_employee_row(
            all_rows, report.employee, self._section_employee_rows(all_rows, "основные смены"))
        side_row = self._find_employee_row(
            all_rows, report.employee, self._section_employee_rows(all_rows, "подработки"))
        if main_row:
            ws.update_cell(main_row, col_num, main_val)
        if side_row:
            ws.update_cell(side_row, col_num, side_val)
        logger.info(
            "Сопровождение %s день=%d: тип=%s осн=%s подраб=%s",
            report.employee, day, "вых" if is_weekend else "будн",
            main_val or "—", side_val or "—",
        )
        return bool(main_row or side_row)

    def update_report(self, report: Report) -> bool:
        ws = self._shifts_ws()
        all_rows = ws.get_all_values()
        header_row = all_rows[HEADER_ROW - 1] if len(all_rows) >= HEADER_ROW else []

        logger.info(
            "Parsed: employee=%r manager=%r day_type=%r calls=%r phones=%r firms=%r "
            "orders=%r shift=%r",
            report.employee, report.manager_type, report.day_type,
            report.calls_total, report.phones, report.firms, report.orders,
            report.shift_type,
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

    # ── ЧИСТКА РУЧНЫХ ЯЧЕЕК ПРИ ЗАКРЫТИИ МЕСЯЦА ─────────────────────────────
    # Что считается ручным вводом. Ключ — начало подписи в колонке A (строчными),
    # значение — колонки, которые чистим. "auto" значит «C, если там введённое
    # значение, иначе E»: у менеджеров доп.премию вводят прямо в C, а у РОП и
    # помощника в C стоит формула (=E…), и ручная ячейка — E.
    MANUAL_LABELS = {
        "дополнительная премия": "auto",
        # комментарий вводят в той же колонке, где сумма премии этого блока:
        # у менеджеров это C, у РОП и помощника — E (там же, где ручной ввод)
        "комментарий к доп.премии": "same",
        "бонус за ведение сторис": "C",
        "факт — оборот": "E",
        "факт — поступления": "E",
        "премия за контент": "E",
        "клиенты smm": "E:G",
        "найм:": "E:F",
        "бонус за план найма": "E:F",
        "премия за проекты": "E:F",
    }
    # ★НЕ чистим: «Конкурс (бонусы)» — раньше там стояла формула по листу КОНКУРС,
    # и чистка её убивала (бонус Дарьи перестал считаться после закрытия июля 2026);
    # «Факт — новые продажи» — это формула по листу НОВЫЕ_КЛИЕНТЫ, она сама
    # пересчитается на новый месяц.

    @classmethod
    def _manual_clear_ranges(cls, values: list, formulas: list) -> list[str]:
        """Диапазоны ручного ввода СВОДНОЙ — по подписям строк, а не по адресам.

        Отдельно добирается ТАБЛИЦА ВЫПЛАТ: колонки C:E (авансы и официальная
        часть) у всех строк сотрудников между шапкой и строкой ИТОГО.
        """
        def cell(rows, i, col):
            r = rows[i - 1] if i - 1 < len(rows) else []
            return str(r[col]).strip() if col < len(r) else ""

        out, pay_rows = [], []
        pay_start = None
        prem_col = None        # колонка доп.премии текущего блока
        for i in range(1, len(values) + 1):
            label = cell(values, i, 0).lower()
            if not label:
                continue
            if "таблица выплат" in label:
                pay_start = i
                continue
            if pay_start and label.startswith("итого"):
                pay_start = None if pay_rows else pay_start
            if pay_start and i > pay_start + 1 and not label.startswith("итого"):
                # строка сотрудника таблицы выплат: в B стоит ссылка на его ИТОГО
                if cell(formulas, i, 1).startswith("="):
                    pay_rows.append(i)
                continue
            cols = next((v for k, v in cls.MANUAL_LABELS.items() if label.startswith(k)), None)
            if not cols:
                continue
            if cols == "auto":
                cols = "E" if cell(formulas, i, 2).startswith("=") else "C"
                prem_col = cols
            elif cols == "same":
                cols = prem_col or "C"
            if ":" in cols:
                a, b = cols.split(":")
                out.append(f"{a}{i}:{b}{i}")
            else:
                out.append(f"{cols}{i}")
        if pay_rows:
            out.append(f"C{min(pay_rows)}:E{max(pay_rows)}")
        return out

    # ── ЖУРНАЛ ЗВОНКОВ ──────────────────────────────────────────────────────
    # Звонки из отчётов смен раньше нигде не оставались: бот только сравнивал их
    # с нормой и писал Анне, если мало. Для индивидуальных условий Виолетты
    # (★Анна, 15.10.2026) норма считается ЗА МЕСЯЦ и по каждой смене («в среднем
    # не менее 30, и ни одной смены ниже 25»), поэтому цифры нужно накапливать.
    CALLS_SHEET = "ЗВОНКИ"
    # ★Анна 15.10.2026: норма считается по «Звонки всего» — то, что менеджер
    # пишет в отчёте смены. Разбивку по длительности храним, если её заполнили,
    # но в норму она не идёт.
    CALLS_HEADER = ["Месяц", "День", "Сотрудник", "Звонки всего",
                    "< 1 мин", "1-2 мин", "2-5 мин", "> 5 мин", "Записано"]

    def _calls_ws(self, month_label: str) -> gspread.Worksheet:
        sh = self._gc.open_by_key(self._spreadsheet_id)
        try:
            return sh.worksheet(self.CALLS_SHEET)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=self.CALLS_SHEET, rows=400,
                                  cols=len(self.CALLS_HEADER))
            ws.update(values=[self.CALLS_HEADER], range_name="A1")
            ws.freeze(rows=1)
            logger.info("Created sheet %s (calls log)", self.CALLS_SHEET)
            return ws

    def log_calls(self, report: Report, month_label: str = "") -> bool:
        """Звонки из отчёта смены → лист ЗВОНКИ (одна строка на смену).

        Ключ строки — месяц + день + сотрудник: смену часто присылают повторно
        (поправить задачи, не тот день), и журнал не должен от этого пухнуть.
        Месяц берём тот же, в чей лист смен попала сама смена.
        """
        if not any((report.calls_total, report.calls_under_1min, report.calls_1_2min,
                    report.calls_2_5min, report.calls_over_5min)):
            return False
        day = self._parse_day(report.date)
        if day is None:
            logger.warning("log_calls: cannot parse day from %r", report.date)
            return False

        def _num(v):
            digits = re.sub(r"\D", "", str(v or ""))
            return int(digits) if digits else 0

        total = _num(report.calls_total)
        under1 = _num(report.calls_under_1min)
        m12 = _num(report.calls_1_2min)
        m25 = _num(report.calls_2_5min)
        over5 = _num(report.calls_over_5min)

        if not month_label:
            month_label = (self._shifts_ws().acell("A2").value or "").strip()
        ws = self._calls_ws(month_label)
        row = [month_label, day, report.employee, total, under1, m12, m25, over5,
               datetime.now(MSK).strftime("%Y-%m-%d %H:%M")]

        values = ws.get_all_values()
        key = (month_label.strip().lower(), str(day), report.employee.strip().lower())
        for i, r in enumerate(values[1:], start=2):
            if len(r) < 3:
                continue
            if (r[0].strip().lower(), str(r[1]).strip(), r[2].strip().lower()) == key:
                ws.update(values=[row], range_name=f"A{i}")
                logger.info("log_calls: обновил %s день=%s всего=%s",
                            report.employee, day, total)
                return True
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info("log_calls: записал %s день=%s всего=%s",
                    report.employee, day, total)
        return True

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
            ("СВОДНАЯ_ЗП",       "\U0001f4b0  СВОДНАЯ ЗП — ведомость (свёрнута до ИТОГО)", "A24:F194", "svod"),
            ("СМЕНЫ",            "\U0001f4c5  СМЕНЫ — табель за месяц",                    None,       True),
            ("ДАННЫЕ_Губарев",   "\U0001f4c7  ДАННЫЕ · Губарев — взаиморасчёты 1С",        None,       True),
            ("ДАННЫЕ_Перфильев", "\U0001f4c7  ДАННЫЕ · Перфильев — взаиморасчёты 1С",      None,       True),
            ("ДАННЫЕ_Володихина", "\U0001f4c7  ДАННЫЕ · Володихина — взаиморасчёты 1С",    None,       True),
            ("БЕБИ_ЛИСТЫ",       "\U0001f37c  БЕБИ-ЛИСТЫ — клиенты с вычетом 40%",          None,       True),
            ("НОВЫЕ_КЛИЕНТЫ",    "✨  НОВЫЕ КЛИЕНТЫ — поиск за месяц",                 None,       True),
        ]
        # ★15.10.2026 (Анна): лист КОНКУРС убран из архива и из таблицы — конкурс
        # считаем в отчёте по продажам. Листа может не быть и по другой причине
        # (новая база, переименование), поэтому ниже пропускаем отсутствующие:
        # закрытие месяца не должно падать из-за одного листа.

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
            try:
                ws = sh.worksheet(name)
            except gspread.WorksheetNotFound:
                logger.warning("архив месяца: листа %s нет — пропускаю", name)
                continue
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
        # ★15.10.2026 (Анна: «архивные листы переноси в конец, они мешают»):
        # архив месяца создаём ПОСЛЕДНИМ листом. Раньше стоял index=0 и каждое
        # закрытие месяца выкидывало архив в начало, перед рабочими листами.
        aws = sh.add_worksheet(title=title, rows=total_rows, cols=maxc,
                               index=len(sh.worksheets()))
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
        clear_a1, _ = self._shift_ranges(ws_smeny)
        ws_smeny.batch_clear(clear_a1)
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
            # ★16.10.2026: границы секций берём из САМОГО листа (подписи «ОСНОВНЫЕ
            # СМЕНЫ» / «ПОДРАБОТКИ»), а не числами. Прежние 5-12 и 17-19 устарели
            # после увольнения Лилии и Влады (стало 5-10 и 15-16): промоут копировал
            # бы чужие строки, а подработки Алёны и РОП не переносились бы вовсе.
            _, bounds = self._shift_ranges(ws_next)
            sh.batch_update({"requests": [
                {"copyPaste": {"source": _grid(ws_next.id, r0, r1, 4, 35),
                               "destination": _grid(ws_smeny.id, r0, r1, 4, 35),
                               "pasteType": "PASTE_VALUES", "pasteOrientation": "NORMAL"}}
                for r0, r1 in bounds
            ]})
            logger.info("Промоут смен: секции строк %s", bounds)
            sh.del_worksheet(ws_next)
            logger.info("Promoted СМЕНЫ_СЛЕД → СМЕНЫ (overlap shifts) and removed temp sheet")
        except gspread.WorksheetNotFound:
            pass

        # Clear листы ДАННЫЕ_* (по одному на ИП) — ТОЛЬКО данные A:E
        # (контрагент, долг/оборот/оплаты/долг). Колонки F:L — ПОСТОЯННЫЕ формулы
        # (ВПР менеджеров/типа/беби из СПРАВОЧНИК, скорр.оплаты, оборот-число):
        # их НЕ трогаем, иначе после закрытия месяца ответственные не проставляются.
        # ★Список берём из sync_odata.SHEET_BASES: когда добавилась база Володихиной
        # (09.10.2026), жёсткий кортеж оставил бы её лист и без очистки, и без
        # промоута накопленного _СЛЕД.
        from sync_odata import SHEET_BASES
        for sheet_name in [c['sheet_name'] for c in SHEET_BASES.values()]:
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

        # Clear СВОДНАЯ_ЗП manual input cells (доп.премии, комментарии, факты РОП,
        # найм/контент помощника, авансы). Формулы НЕ трогаем.
        # ★15.10.2026: адреса больше НЕ прописаны числами. Раскладка СВОДНОЙ уже
        # трижды уезжала (добавили стажёров — всё ниже сдвинулось на 28 строк), а
        # после увольнения Лилии и Влады уедет снова; с жёсткими адресами чистка
        # попадала бы в чужие ячейки и затирала формулы. Теперь строки ищутся по
        # подписям — см. _manual_clear_ranges.
        ws_sv = sh.worksheet('СВОДНАЯ_ЗП')
        manual_ranges = self._manual_clear_ranges(
            ws_sv.get('A1:H200', value_render_option='UNFORMATTED_VALUE'),
            ws_sv.get('A1:H200', value_render_option='FORMULA'))
        logger.info("Чистим ручные ячейки СВОДНОЙ: %s", manual_ranges)
        ws_sv.batch_clear(manual_ranges)

        # Страховка: восстанавливаем формулу факта новых продаж РОП.
        # Строка ИТОГ листа НОВЫЕ_КЛИЕНТЫ отсекается по пустому менеджеру (C),
        # иначе сумма удваивалась (баг 2026-08-04). Строку ищем по подписи —
        # её номер уезжает вместе с раскладкой.
        rows_a = [(i + 1, (r[0] if r else "")) for i, r in
                  enumerate(ws_sv.get('A1:A200', value_render_option='UNFORMATTED_VALUE'))]
        fact_row = next((i for i, a in rows_a
                         if str(a).strip().lower().startswith("факт — новые продажи")), None)
        if fact_row:
            ws_sv.update(
                [["=SUMIF('НОВЫЕ_КЛИЕНТЫ'!$C$4:$C$503;\"<>\";'НОВЫЕ_КЛИЕНТЫ'!$G$4:$G$503)"]],
                f'E{fact_row}',
                value_input_option='USER_ENTERED',
            )
        else:
            logger.warning("не нашёл строку «Факт — новые продажи» — формулу не вернул")

        # Update period in НАСТРОЙКИ
        ws_settings.update([[next_label]], 'B4')

        # Invalidate cached СМЕНЫ worksheet
        self._ws = None

        logger.info("Month archived: %s → next period: %s", period, next_label)
        return period
