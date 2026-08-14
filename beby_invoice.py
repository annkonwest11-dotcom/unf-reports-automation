#!/usr/bin/env python3
"""Разбор PDF товарной накладной поставщика беби-листов (ИП Юшин) → позиции.

В накладной товар в КИЛОГРАММАХ, в таблице «аналитика беби» — пачки по 100 гр,
поэтому кг × 10 = пачек, а цена за кг ÷ 10 = цена пачки (сверено с блоками июля:
микс 1 950 ₽/кг = 195 ₽ за пачку).

Формат строки позиции в тексте PDF (две строки на позицию):
    1 Салатный микс
     - кг 166 - 11,70 1,00 - - 1 950,00 22 815,00 Без НДС 0,00 22 815,00
       ^ед.        ^кол-во        ^цена     ^сумма

Запуск:  venv/bin/python beby_invoice.py "~/Downloads/Товарная накладная № 346 от 03.08.26.pdf"
"""
import os
import re
import sys
from datetime import datetime

PACKS_PER_KG = 10          # пачка = 100 гр
NUM = r"[\d\s\xa0]+(?:,\d+)?"


def _num(s):
    return float(str(s).replace("\xa0", "").replace(" ", "").replace(",", "."))


def extract_text(path):
    """Текст первой страницы PDF (pypdf)."""
    try:
        import pypdf
    except ImportError as e:                       # pragma: no cover
        raise RuntimeError("нужен pypdf: venv/bin/pip install pypdf") from e
    return pypdf.PdfReader(path).pages[0].extract_text()


def parse(path):
    """PDF → {number, date, supplier, items:[(название, пачек, сумма)], total}."""
    text = extract_text(path)
    m = re.search(r"(\d+)\s+(\d{2}\.\d{2}\.\d{4})", text)
    if not m:
        raise ValueError("не нашёл номер и дату накладной")
    number, date = m.group(1), datetime.strptime(m.group(2), "%d.%m.%Y").date()
    supplier = ""
    ms = re.search(r"Поставщик\s+([^,]+)", text)
    if ms:
        supplier = ms.group(1).strip()

    items, lines = [], text.splitlines()
    for i, line in enumerate(lines[:-1]):
        mi = re.match(r"^\s*(\d{1,2})\s+(\D[^\d]*?)\s*$", line)
        if not mi:
            continue
        data = lines[i + 1]
        md = re.match(rf"^\s*-\s+(кг|шт|уп)\s+(?:\d+|-)\s+-\s+({NUM})\s+", data)
        if not md:
            continue
        tail = re.findall(rf"({NUM})\s+Без НДС", data) or re.findall(rf"({NUM})\s*$", data)
        unit, qty = md.group(1), _num(md.group(2))
        packs = round(qty * PACKS_PER_KG) if unit == "кг" else round(qty)
        summ = _num(tail[0]) if tail else 0.0
        items.append((mi.group(2).strip(), packs, summ))

    mt = re.search(rf"Итого\s+{NUM}\s+[\d,\s]+\s+[\d,\s]+\s+X\s+({NUM})\s+X", text)
    total = _num(mt.group(1)) if mt else round(sum(s for _, _, s in items), 2)
    calc = round(sum(s for _, _, s in items), 2)
    if abs(calc - total) > 0.01:
        raise ValueError(f"накладная №{number}: сумма позиций {calc} ≠ итога {total}")
    if not items:
        raise ValueError(f"накладная №{number}: не разобрал ни одной позиции")
    return {"number": number, "date": date, "supplier": supplier,
            "items": items, "total": total}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    for path in sys.argv[1:]:
        inv = parse(os.path.expanduser(path))
        print(f"\nНакладная №{inv['number']} от {inv['date']:%d.%m.%Y} — {inv['supplier']}")
        for name, packs, summ in inv["items"]:
            print(f"   {name:<20} {packs:>5} пачек  {summ:>10,.2f} ₽".replace(",", " "))
        print(f"   {'ИТОГО':<20} {sum(p for _, p, _ in inv['items']):>5} пачек  "
              f"{inv['total']:>10,.2f} ₽".replace(",", " "))


if __name__ == "__main__":
    main()
