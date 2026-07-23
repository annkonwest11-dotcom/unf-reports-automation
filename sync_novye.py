"""Еженедельная синхронизация новых продаж из KPI-таблицы (пн 11:00 МСК).

Делает три вещи за один проход по листу KPI текущего месяца:
1) обновляет лист НОВЫЕ_КЛИЕНТЫ (суммы новых продаж по менеджерам) — как прежний
   scripts/sync_novye_klienty.py;
2) автозаводит новых клиентов в СПРАВОЧНИК с ответственным по правилу Анны:
   менеджер поиска → B=менеджер, C='';  менеджер сопровождения → B='Прямой клиент',
   C=менеджер;  Анна/РОП → B='Прямой клиент';
3) для клиентов «вернули», которые УЖЕ в СПРАВОЧНИКе и у которых ответственный из KPI
   РАСХОДИТСЯ с текущим в СПР — собирает список для сообщения Анне (она решает вручную).

Имена KPI короткие («Главторг»), а в СПРАВОЧНИК/ДАННЫЕ — полные из 1С; матчим по
токенам. Новым строкам СПР даём имя из совпавшей строки ДАННЫЕ (тогда VLOOKUP в
ДАННЫЕ.F/G подхватит менеджера), иначе — юрлицо/название из KPI.
"""

import logging
import os
import re
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

KPI_SS_ID = "1QuvmjSPJUbqGTbGKKBcDu8QdQaFv1Gg2VbzUb-bEbL4"
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPR_START = 4          # СПРАВОЧНИК: данные с 4-й строки
NK_CLEAR = "A4:H203"   # НОВЫЕ_КЛИЕНТЫ: диапазон очистки

MONTH_TO_KPI_SHEET = {
    "Январь": "декабрь-январь", "Февраль": "январь-февраль", "Март": "февраль-март",
    "Апрель": "март-апрель", "Май": "апрель-май", "Июнь": "май-июнь",
    "Июль": "июнь-июль", "Август": "июль-август", "Сентябрь": "август-сентябрь",
    "Октябрь": "сентябрь-октябрь", "Ноябрь": "октябрь-ноябрь", "Декабрь": "ноябрь-декабрь",
}

# Заголовок колонки KPI (lower) → (ФИО менеджера, тип)
KPI_MANAGERS = {
    "менеджер дарья": ("Дарья Вольнова", "поиск"),
    "менеджер алена": ("Алена Черкашина", "сопровождение"),
    "менеджер ксения": ("Ксения Наныкина", "поиск"),
    "менеджер лера": ("Валерия Папоян", "поиск"),
    "анна": ("Анна Кононенко (РОП)", "роп"),
}

_STOP = {"ооо", "ип", "эдо", "dsbx", "счет", "в", "1с", "с", "нал", "бар", "кафе",
         "ресторан", "кейтеринг", "наличка", "the", "по", ""}


def _toks(s):
    t = re.findall(r"[a-zA-Zа-яА-Я0-9]+", (s or "").lower())
    return set(w for w in t if w not in _STOP and len(w) > 2)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _best_match(qtoks, candidates):
    """candidates: [(payload, name), ...] → (payload, name, score) лучшего или None."""
    best, score = None, 0
    for payload, name in candidates:
        ov = len(qtoks & _toks(name))
        if ov > score:
            best, score = (payload, name), ov
    return (best[0], best[1], score) if best else (None, None, 0)


def _assignment(mtype, mname):
    """(B поиск, C сопровождение) по типу менеджера."""
    if mtype == "поиск":
        return mname, ""
    if mtype == "сопровождение":
        return "Прямой клиент", mname
    return "Прямой клиент", ""  # роп


def _parse_amount(val):
    s = str(val).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _open(gc=None):
    if gc is None:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        gc = gspread.authorize(creds)
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID не задан")
    return gc


def sync_novye(dry_run=False):
    """Возвращает отчёт: {novye_rows, novye_total, added:[(name,B,C)], discrepancies:
    [(client, kpi_mgr, spr_current)], no_data:[name]}."""
    gc = _open()
    ss = gc.open_by_key(SPREADSHEET_ID)
    kss = gc.open_by_key(KPI_SS_ID)

    month = (ss.worksheet("НАСТРОЙКИ").acell("B4").value or "").strip().split()
    month = month[0] if month else ""
    kpi_name = MONTH_TO_KPI_SHEET.get(month)
    if not kpi_name:
        raise RuntimeError(f"Нет маппинга KPI-листа для месяца: {month!r}")
    kpi_ws = next((w for w in kss.worksheets() if w.title.strip() == kpi_name.strip()), None)
    if kpi_ws is None:
        raise RuntimeError(f"Лист KPI не найден: {kpi_name!r}")
    data = kpi_ws.get_all_values()
    headers = data[0] if data else []

    # колонки менеджеров
    mgr_cols = {i: KPI_MANAGERS[headers[i].strip().lower()]
                for i in range(len(headers)) if headers[i].strip().lower() in KPI_MANAGERS}

    # ── 1) НОВЫЕ_КЛИЕНТЫ: суммы новых продаж (числовые) ──────────────────────
    nk_rows = []
    for row in data[1:]:
        rest = (row[0].strip() if row else "")
        if not rest:
            continue
        for ci, (mname, _t) in mgr_cols.items():
            amt = _parse_amount(row[ci]) if ci < len(row) else None
            if amt is None:
                continue
            sr = len(nk_rows) + SPR_START
            # ru-локаль: разделитель аргументов «;». IFERROR на КАЖДЫЙ VLOOKUP,
            # чтобы клиент, который есть только в одной базе, отдавал свой оборот.
            formula = (f"=IFERROR(VLOOKUP(B{sr};ДАННЫЕ_Губарев!$A$4:$L$503;12;0);0)"
                       f"+IFERROR(VLOOKUP(B{sr};ДАННЫЕ_Перфильев!$A$4:$L$503;12;0);0)")
            nk_rows.append([date.today().isoformat(), rest, mname,
                            f"из КПИ {kpi_name}", kpi_name, amt, amt, formula])
    novye_total = sum(r[6] for r in nk_rows)

    # ── 2/3) СПРАВОЧНИК: автозаведение + расхождения ─────────────────────────
    spr = ss.worksheet("СПРАВОЧНИК")
    spr_vals = spr.get(f"A{SPR_START}:E1000")
    spr_cands = [((SPR_START + i, r), (r[0] if r else ""))
                 for i, r in enumerate(spr_vals) if r and r[0].strip()]
    data_names = []
    for sh in ("ДАННЫЕ_Губарев", "ДАННЫЕ_Перфильев"):
        data_names += [(None, v) for v in ss.worksheet(sh).col_values(1)[3:] if v.strip()]

    added, discrepancies, no_data = [], [], []
    seen = set()
    for row in data[1:]:
        rest = (row[0].strip() if row else "")
        if not rest:
            continue
        ur = row[1] if len(row) > 1 else ""
        klass = (row[3] if len(row) > 3 else "").strip().lower()
        mgr = None
        for ci, mt in mgr_cols.items():
            if ci < len(row) and row[ci].strip():
                mgr = mt
                break
        if not mgr:
            continue
        mname, mtype = mgr
        B, C = _assignment(mtype, mname)
        q = _toks(rest) | _toks(ur)
        (sp_payload, sp_name, _s) = _best_match(q, spr_cands)

        if sp_payload:  # уже в СПРАВОЧНИКе
            if klass == "вернули":
                cur_B = sp_payload[1][1] if len(sp_payload[1]) > 1 else ""
                cur_C = sp_payload[1][2] if len(sp_payload[1]) > 2 else ""
                # расхождение: KPI-ответственный не совпадает с соответств. полем СПР
                field = cur_B if mtype == "поиск" else cur_C
                if mtype != "роп" and _norm(field) != _norm(mname):
                    discrepancies.append((rest, mname, f"поиск={cur_B!r} сопр={cur_C!r}"))
            continue

        # нет в СПР → добавить
        _, dn_name, dsc = _best_match(q, data_names)
        add_name = dn_name if dn_name else (ur.strip() or rest)
        if _norm(add_name) in seen:
            continue
        seen.add(_norm(add_name))
        if not dn_name:
            no_data.append(add_name)
        added.append((add_name, B, C))

    # ── запись ───────────────────────────────────────────────────────────────
    if not dry_run:
        nk = ss.worksheet("НОВЫЕ_КЛИЕНТЫ")
        nk.batch_clear([NK_CLEAR])
        if nk_rows:
            nk.update([r[:7] for r in nk_rows], "A4", value_input_option="USER_ENTERED")
            nk.update([[r[7]] for r in nk_rows], "H4", value_input_option="USER_ENTERED")
            # строка ИТОГ под данными (F=сумма новых продаж, G — то же, H=оборот 1С)
            it = 4 + len(nk_rows)
            ld = it - 1
            nk.update(
                [["ИТОГ", "", "", "",
                  f"=SUM(F4:F{ld})", f"=SUM(G4:G{ld})", f"=SUM(H4:H{ld})"]],
                f"B{it}:H{it}", value_input_option="USER_ENTERED",
            )
        if added:
            first_empty = len(spr.col_values(1)) + 1
            spr.update(
                [[name, B, C, "Ресторан"] for name, B, C in added],
                f"A{first_empty}:D{first_empty + len(added) - 1}",
                value_input_option="RAW",
            )

    report = {"novye_rows": len(nk_rows), "novye_total": round(novye_total, 2),
              "added": added, "discrepancies": discrepancies, "no_data": no_data,
              "kpi_sheet": kpi_name}
    logger.info("sync_novye: %s", {k: (v if not isinstance(v, list) else len(v))
                                    for k, v in report.items()})
    return report


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rep = sync_novye(dry_run=not a.apply)
    print(f"\nНОВЫЕ_КЛИЕНТЫ: {rep['novye_rows']} строк, сумма {rep['novye_total']:,.0f}")
    print(f"Добавить в СПР ({len(rep['added'])}):")
    for name, B, C in rep["added"]:
        print(f"  {name[:40]:<40} поиск={B!r} сопр={C!r}")
    print(f"Расхождения ({len(rep['discrepancies'])}):")
    for cl, kpi, cur in rep["discrepancies"]:
        print(f"  {cl[:24]:<24} KPI={kpi} | СПР {cur}")
    if not a.apply:
        print("\n(dry-run — ничего не записано; --apply чтобы применить)")
