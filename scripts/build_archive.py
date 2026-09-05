# -*- coding: utf-8 -*-
"""Создаёт единый лист АРХИВ_<месяц>_<год>.
   ЗНАЧЕНИЯ пишутся готовыми (посчитаны в живом листе — застывшие, не ломаются),
   ФОРМАТ (цвета/границы/числовые форматы) накладывается из живых листов (PASTE_FORMAT).
   НЕ трогает живые листы и НЕ меняет период. Безопасный снимок."""
import os, gspread, re
from dotenv import load_dotenv
load_dotenv()
gc = gspread.service_account(filename="credentials.json")
sh = gc.open_by_key(os.environ.get("SPREADSHEET_ID") or "1KaxfaSWTDR31eAJfmpahaNwaO2Qohrh5xua1Rrjf2Zo")

MONTHS={"Январь":"ЯНВАРЬ","Февраль":"ФЕВРАЛЬ","Март":"МАРТ","Апрель":"АПРЕЛЬ","Май":"МАЙ","Июнь":"ИЮНЬ",
        "Июль":"ИЮЛЬ","Август":"АВГУСТ","Сентябрь":"СЕНТЯБРЬ","Октябрь":"ОКТЯБРЬ","Ноябрь":"НОЯБРЬ","Декабрь":"ДЕКАБРЬ"}
period = sh.worksheet("НАСТРОЙКИ").acell("B4").value or "Июнь 2026"
mon, yr = period.split()
title = f"АРХИВ_{MONTHS.get(mon,mon.upper())}_{yr}"

# (лист, заголовок секции, явный диапазон|None, группировать_всю_секцию)
SEC = [
 ("НАСТРОЙКИ",        "⚙  НАСТРОЙКИ — параметры месяца",              "A1:C40",   False),
 ("СВОДНАЯ_ЗП",       "💰  СВОДНАЯ ЗП — ведомость (свёрнута до ИТОГО)", "A24:F194", "svod"),
 ("СМЕНЫ",            "📅  СМЕНЫ — табель за месяц",                  None,       True),
 ("ДАННЫЕ_Губарев",   "📇  ДАННЫЕ · Губарев — взаиморасчёты 1С",      None,       True),
 ("ДАННЫЕ_Перфильев", "📇  ДАННЫЕ · Перфильев — взаиморасчёты 1С",    None,       True),
 ("БЕБИ_ЛИСТЫ",       "🍼  БЕБИ-ЛИСТЫ — клиенты с вычетом 40%",        None,       True),
 ("НОВЫЕ_КЛИЕНТЫ",    "✨  НОВЫЕ КЛИЕНТЫ — поиск за месяц",            None,       True),
 ("КОНКУРС",          "🏆  КОНКУРС — бонусы за результат",             None,       True),
]

def parse_a1(a1):  # -> (r0,c0,r1,c1) 0-based, r1/c1 exclusive
    m=re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", a1)
    def col(s):
        n=0
        for ch in s: n=n*26+(ord(ch)-64)
        return n-1
    return int(m.group(2))-1, col(m.group(1)), int(m.group(4)), col(m.group(3))+1

# --- читаем значения + запоминаем исходный диапазон (для наложения формата) ---
parts=[]  # (hdr, values2d, src_gridrange, grouptype)
for name,hdr,rng,grp in SEC:
    ws=sh.worksheet(name); sid=ws.id
    if rng:
        r0,c0,r1,c1=parse_a1(rng)
        vals=ws.get(rng, value_render_option='FORMATTED_VALUE')
    else:
        vals=ws.get_all_values()
        while vals and not any(str(x).strip() for x in vals[-1]): vals.pop()
        nr=len(vals); nc=max((len(r) for r in vals), default=1)
        r0,c0,r1,c1=0,0,nr,nc
    src={"sheetId":sid,"startRowIndex":r0,"endRowIndex":r1,"startColumnIndex":c0,"endColumnIndex":c1}
    parts.append((hdr,vals,src,grp))

maxc=max((c1:=p[2]["endColumnIndex"]-p[2]["startColumnIndex"]) for p in parts); maxc=max(maxc,6)

# --- матрица значений + разметка (0-based) ---
def pad(r): return list(r)+[""]*(maxc-len(r))
matrix=[pad([f"АРХИВ · {period}"]),
        pad(["❄ Застывшие значения (без формул). СВОДНАЯ и длинные секции свёрнуты — разворот по [+] слева."]),
        pad([])]
layout=[]  # (hdr, header_row0, data_start0, nrows, ncols, src, grp)
svod_labels=None; svod_dstart=None
for hdr,vals,src,grp in parts:
    hrow=len(matrix); matrix.append(pad([hdr]))
    dstart=len(matrix)
    nc=src["endColumnIndex"]-src["startColumnIndex"]
    for r in vals: matrix.append(pad(r))
    layout.append((hdr,hrow,dstart,len(vals),nc,src,grp))
    if grp=="svod": svod_labels=[(r[0] if r else "") for r in vals]; svod_dstart=dstart
    matrix.append(pad([]))
total_rows=len(matrix)+5

# --- пересоздать лист, записать значения ---
try:
    sh.del_worksheet(sh.worksheet(title)); print("Старый",title,"удалён")
except gspread.WorksheetNotFound: pass
aws=sh.add_worksheet(title=title, rows=total_rows, cols=maxc, index=0); aid=aws.id
aws.update(matrix, "A1", value_input_option="RAW")
print(f"Значения записаны: {len(matrix)} строк × {maxc} колонок")

def rgb(h): h=h.lstrip('#'); return {"red":int(h[0:2],16)/255,"green":int(h[2:4],16)/255,"blue":int(h[4:6],16)/255}
def gr(r0,r1,c0,c1): return {"sheetId":aid,"startRowIndex":r0,"endRowIndex":r1,"startColumnIndex":c0,"endColumnIndex":c1}

reqs=[]
# наложить ФОРМАТ из живых листов (без значений) на данные каждой секции
for hdr,hrow,dstart,nr,nc,src,grp in layout:
    if nr==0: continue
    dest=gr(dstart,dstart+nr,0,nc)
    reqs.append({"copyPaste":{"source":src,"destination":dest,"pasteType":"PASTE_FORMAT","pasteOrientation":"NORMAL"}})
# перенести ОБЪЕДИНЕНИЯ ячеек из живых листов (PASTE_FORMAT их не копирует)
mmeta=sh.fetch_sheet_metadata({"fields":"sheets(properties(sheetId),merges)"})
merges_by_sid={s["properties"]["sheetId"]:s.get("merges",[]) for s in mmeta["sheets"]}
for hdr,hrow,dstart,nr,nc,src,grp in layout:
    if nr==0: continue
    r0,c0,r1,c1=src["startRowIndex"],src["startColumnIndex"],src["endRowIndex"],src["endColumnIndex"]
    for m in merges_by_sid.get(src["sheetId"],[]):
        if m["startRowIndex"]>=r0 and m["endRowIndex"]<=r1 and m["startColumnIndex"]>=c0 and m["endColumnIndex"]<=c1:
            reqs.append({"mergeCells":{"range":{"sheetId":aid,
                "startRowIndex":dstart+(m["startRowIndex"]-r0),"endRowIndex":dstart+(m["endRowIndex"]-r0),
                "startColumnIndex":m["startColumnIndex"]-c0,"endColumnIndex":m["endColumnIndex"]-c0},"mergeType":"MERGE_ALL"}})
# оформление заголовков листа/секций (поверх формата)
reqs.append({"repeatCell":{"range":gr(0,1,0,maxc),"cell":{"userEnteredFormat":{"backgroundColor":rgb("#ffffff"),"textFormat":{"bold":True,"fontSize":15,"foregroundColor":rgb("#37503f")}}},"fields":"userEnteredFormat(backgroundColor,textFormat)"}})
reqs.append({"repeatCell":{"range":gr(1,2,0,maxc),"cell":{"userEnteredFormat":{"backgroundColor":rgb("#ffffff"),"textFormat":{"italic":True,"foregroundColor":rgb("#6b7a75")}}},"fields":"userEnteredFormat(backgroundColor,textFormat)"}})
for hdr,hrow,dstart,nr,nc,src,grp in layout:
    reqs.append({"repeatCell":{"range":gr(hrow,hrow+1,0,maxc),"cell":{"userEnteredFormat":{"backgroundColor":rgb("#7f9990"),"textFormat":{"bold":True,"foregroundColor":rgb("#ffffff"),"fontSize":11}}},"fields":"userEnteredFormat(backgroundColor,textFormat)"}})
reqs.append({"updateSheetProperties":{"properties":{"sheetId":aid,"gridProperties":{"frozenRowCount":1}},"fields":"gridProperties.frozenRowCount"}})
# объединить строку-заголовок секции НАСТРОЙКИ (первая строка данных) до столбца C
for hdr,hrow,dstart,nr,nc,src,grp in layout:
    if "НАСТРОЙКИ" in hdr and nr>0:
        reqs.append({"mergeCells":{"range":gr(dstart,dstart+1,0,3),"mergeType":"MERGE_ALL"}})
# ширина колонок (A-F как в СВОДНОЙ, дальше узкие дни)
WIDTHS={0:240,1:230,2:165,3:200,4:150,5:305}
for c,w in WIDTHS.items():
    reqs.append({"updateDimensionProperties":{"range":{"sheetId":aid,"dimension":"COLUMNS","startIndex":c,"endIndex":c+1},"properties":{"pixelSize":w},"fields":"pixelSize"}})
if maxc>6:
    reqs.append({"updateDimensionProperties":{"range":{"sheetId":aid,"dimension":"COLUMNS","startIndex":6,"endIndex":maxc},"properties":{"pixelSize":85},"fields":"pixelSize"}})

# --- группировки ---
groups=[]
labels=[str(x).strip() for x in (svod_labels or [])]
for idx,a in enumerate(labels):
    if a.startswith("ИТОГО ЗП"):
        nm=a.replace("ИТОГО ЗП —","").replace("ИТОГО ЗП -","").strip()
        h=None
        for j in range(idx-1,-1,-1):
            if labels[j].startswith(nm): h=j; break
            if labels[j].startswith("ИТОГО ЗП"): break
        if h is not None and idx-1>h:
            groups.append((svod_dstart+h, svod_dstart+idx))  # [заголовок .. ИТОГО-1]
for hdr,hrow,dstart,nr,nc,src,grp in layout:
    if grp is True and nr>0: groups.append((dstart, dstart+nr))
for s0,e0 in groups:
    reqs.append({"addDimensionGroup":{"range":{"sheetId":aid,"dimension":"ROWS","startIndex":s0,"endIndex":e0}}})

sh.batch_update({"requests":reqs})
col=[{"updateDimensionGroup":{"dimensionGroup":{"range":{"sheetId":aid,"dimension":"ROWS","startIndex":s0,"endIndex":e0},"depth":1,"collapsed":True},"fields":"collapsed"}} for s0,e0 in groups]
if col: sh.batch_update({"requests":col})
print(f"{title}: секций {len(layout)}, групп {len(groups)} (свёрнуты), {maxc}кол × {total_rows}стр, gid {aid}")
print("ГОТОВО — живые листы не тронуты, период:", period)
